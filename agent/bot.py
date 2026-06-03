"""
Telegram-бот поверх агента генерации промтов для Grok.

UX: никаких слэш-команд кроме обязательного /start.
Всё управление — кнопки.

Поток:
1. /start  → приветствие, просьба отправить идею
2. Юзер шлёт идею текстом
3. Бот показывает меню настроек (стиль, кол-во сцен, кадров, формат,
   длительность) — каждая настройка циклится при тапе
4. Юзер тапает 🚀 Поехали
5. Бот задаёт уточняющие вопросы с кнопками выбора
6. Бот генерирует и присылает результат (сцены + .md + .json)

Запуск:
    export TELEGRAM_BOT_TOKEN=<токен>
    python -m agent.bot
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .llm import backend_info
from .clarify import plan_questions_async
from .script import generate_script_async
from .prompt_builder import build_image_prompts_async, build_animation_prompts_async
from .render import render_markdown, render_scene_brief, slugify
from .models import VideoProject

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

STYLES = ["cinematic", "anime", "3d", "realistic", "cartoon"]
ASPECTS = ["16:9", "9:16", "1:1"]
KEYFRAMES = ["auto", "1", "2", "3"]


@dataclass
class ChatState:
    # Этап: "idle" | "setup" | "clarify"
    stage: str = "idle"
    idea: Optional[str] = None
    style: str = "cinematic"
    scenes_count: int = 4
    duration: int = 6
    aspect: str = "16:9"
    keyframes: str = "auto"
    plan: Optional[dict] = None
    questions: list = field(default_factory=list)
    q_index: int = 0
    answers: dict = field(default_factory=dict)
    is_dialogue_heavy: bool = False
    awaiting_custom_answer: bool = False
    busy: bool = False
    setup_message_id: Optional[int] = None


STATES: dict[int, ChatState] = {}


def state_for(chat_id: int) -> ChatState:
    s = STATES.get(chat_id)
    if s is None:
        s = ChatState()
        STATES[chat_id] = s
    return s


def reset(chat_id: int):
    STATES.pop(chat_id, None)


def _cycle(values: list, current):
    try:
        i = values.index(current)
    except ValueError:
        i = -1
    return values[(i + 1) % len(values)]


# ───────────────────────────── Клавиатуры ──────────────────────────────────────


def kb_setup(st: ChatState) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"🎨 Стиль: {st.style}", callback_data="cyc:style"
            )
        ],
        [
            InlineKeyboardButton(text="🎬 −", callback_data="dec:scenes"),
            InlineKeyboardButton(
                text=f"Сцен: {st.scenes_count}", callback_data="noop"
            ),
            InlineKeyboardButton(text="＋", callback_data="inc:scenes"),
        ],
        [
            InlineKeyboardButton(
                text=f"🖼 Кадров/сцену: {st.keyframes}", callback_data="cyc:keyframes"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"📐 Формат: {st.aspect}", callback_data="cyc:aspect"
            )
        ],
        [
            InlineKeyboardButton(text="⏱ −", callback_data="dec:duration"),
            InlineKeyboardButton(
                text=f"Длительность: {st.duration}с", callback_data="noop"
            ),
            InlineKeyboardButton(text="＋", callback_data="inc:duration"),
        ],
        [
            InlineKeyboardButton(text="🚀 Поехали", callback_data="go"),
            InlineKeyboardButton(text="❌ Отменить", callback_data="cancel"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_suggestions(q_index: int, suggestions: list) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=s, callback_data=f"sug:{q_index}:{i}")]
        for i, s in enumerate(suggestions)
    ]
    rows.append(
        [
            InlineKeyboardButton(text="✏ свой", callback_data="custom"),
            InlineKeyboardButton(text="⏭ пропустить", callback_data="skip_q"),
        ]
    )
    rows.append([InlineKeyboardButton(text="❌ отменить", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def setup_caption(st: ChatState) -> str:
    return (
        f"🎯 *Идея:* {st.idea}\n\n"
        f"Настрой параметры кнопками или сразу жми *🚀 Поехали*."
    )


# ───────────────────────────── Шаги пайплайна ─────────────────────────────────


async def show_setup(message: Message, st: ChatState):
    st.stage = "setup"
    m = await message.answer(setup_caption(st), reply_markup=kb_setup(st))
    st.setup_message_id = m.message_id


async def refresh_setup(cb: types.CallbackQuery, st: ChatState):
    try:
        await cb.message.edit_text(setup_caption(st), reply_markup=kb_setup(st))
    except Exception:
        # Telegram бросает "message is not modified" если контент тот же
        pass


async def start_clarification(message: Message, st: ChatState):
    await message.answer("🧠 Анализирую идею, думаю что доуточнить…")
    plan = await plan_questions_async(st.idea, st.style)
    st.plan = plan
    st.is_dialogue_heavy = bool(plan.get("is_dialogue_heavy", False))
    st.questions = plan.get("questions", []) or []
    st.q_index = 0
    st.answers = {}
    st.stage = "clarify"

    reasoning = plan.get("reasoning", "")
    head = f"💡 {reasoning}" if reasoning else ""
    if st.is_dialogue_heavy:
        head += "\n\n🗣 Ролик разговорный — будут вопросы про голос/реплики."

    if not st.questions:
        if head:
            await message.answer(head.strip())
        await message.answer("✅ Уточнений не нужно — генерирую.")
        await run_generation(message, st)
        return

    if head:
        await message.answer(head.strip())
    await ask_next_question(message, st)


async def ask_next_question(message: Message, st: ChatState):
    if st.q_index >= len(st.questions):
        await message.answer("✅ Все вопросы собраны — генерирую.")
        await run_generation(message, st)
        return
    q = st.questions[st.q_index]
    text = f"[{st.q_index + 1}/{len(st.questions)}] {q['question']}"
    suggestions = q.get("suggestions", []) or []
    if suggestions:
        await message.answer(text, reply_markup=kb_suggestions(st.q_index, suggestions))
    else:
        st.awaiting_custom_answer = True
        await message.answer(text + "\n\n_напиши ответ сообщением_")


async def record_answer(message: Message, st: ChatState, answer: str):
    if st.q_index >= len(st.questions):
        return
    q = st.questions[st.q_index]
    st.answers[q["key"]] = answer
    st.q_index += 1
    st.awaiting_custom_answer = False
    await ask_next_question(message, st)


async def run_generation(message: Message, st: ChatState):
    if st.busy:
        await message.answer("⏳ Уже работаю над предыдущим запросом.")
        return
    st.busy = True
    try:
        await message.answer(
            f"📝 Пишу сценарий ({st.scenes_count} сцен, стиль *{st.style}*, "
            f"кадров: *{st.keyframes}*)…"
        )
        project = await generate_script_async(
            idea=st.idea,
            style=st.style,
            scenes_count=st.scenes_count,
            is_dialogue_heavy=st.is_dialogue_heavy,
            clarifications=st.answers,
            keyframes_mode=st.keyframes,
        )
        kf_summary = ", ".join(
            f"#{s.number}:{s.suggested_keyframes if st.keyframes=='auto' else st.keyframes}"
            for s in project.scenes
        )
        await message.answer(
            f"🎬 «{project.title}» — {len(project.scenes)} сцен.\n"
            f"🖼 Кадров по сценам: {kf_summary}\n"
            f"Генерирую промты для картинок…"
        )
        await build_image_prompts_async(project)
        await message.answer("🎞 Генерирую промты для анимации…")
        await build_animation_prompts_async(project, st.duration, st.aspect)
        await send_result(message, project)
    except Exception as e:
        log.exception("generation failed")
        await message.answer(f"❌ Ошибка: `{type(e).__name__}: {e}`")
    finally:
        st.busy = False
        reset(message.chat.id)


async def send_result(message: Message, project: VideoProject):
    head = (
        f"✅ Готово.\n\n*{project.title}*\n"
        f"_Anchor:_ {project.character_anchor}\n"
    )
    if project.voice_notes:
        head += f"_Голос:_ {project.voice_notes}\n"
    await message.answer(head)

    total = len(project.scenes)
    for s in project.scenes:
        await message.answer(render_scene_brief(s, total))

    slug = slugify(project.title)
    md_bytes = render_markdown(project).encode("utf-8")
    json_bytes = json.dumps(
        project.to_dict(), ensure_ascii=False, indent=2
    ).encode("utf-8")
    await message.answer_document(
        BufferedInputFile(md_bytes, filename=f"{slug}.md"),
        caption="📄 Полный сценарий — копируй промты в Grok.",
    )
    await message.answer_document(
        BufferedInputFile(json_bytes, filename=f"{slug}.json"),
        caption="🗂 То же в JSON.",
    )
    await message.answer("Готов к новой идее — просто пришли её сообщением.")


# ───────────────────────────── Хендлеры ────────────────────────────────────────


def register(dp: Dispatcher):

    @dp.message(CommandStart())
    async def cmd_start(message: Message):
        reset(message.chat.id)
        await message.answer(
            "👋 Привет! Я делаю промты для ИИ-видео в Grok.\n\n"
            f"Бэкенд: _{backend_info()}_\n"
            "Модель: *Claude Opus 4.7* (extended thinking high)\n\n"
            "Просто пришли идею ролика одним сообщением — дальше всё кнопками."
        )

    @dp.callback_query(F.data == "noop")
    async def cb_noop(cb: types.CallbackQuery):
        await cb.answer()

    @dp.callback_query(F.data == "cancel")
    async def cb_cancel(cb: types.CallbackQuery):
        reset(cb.message.chat.id)
        await cb.message.answer("❎ Сессия сброшена. Жду новую идею.")
        await cb.answer()

    @dp.callback_query(F.data.startswith("cyc:"))
    async def cb_cycle(cb: types.CallbackQuery):
        st = state_for(cb.message.chat.id)
        if st.stage != "setup":
            await cb.answer()
            return
        what = cb.data.split(":", 1)[1]
        if what == "style":
            st.style = _cycle(STYLES, st.style)
        elif what == "aspect":
            st.aspect = _cycle(ASPECTS, st.aspect)
        elif what == "keyframes":
            st.keyframes = _cycle(KEYFRAMES, st.keyframes)
        await refresh_setup(cb, st)
        await cb.answer()

    @dp.callback_query(F.data.startswith("inc:") | F.data.startswith("dec:"))
    async def cb_step(cb: types.CallbackQuery):
        st = state_for(cb.message.chat.id)
        if st.stage != "setup":
            await cb.answer()
            return
        op, field_name = cb.data.split(":", 1)
        delta = 1 if op == "inc" else -1
        if field_name == "scenes":
            st.scenes_count = max(1, min(8, st.scenes_count + delta))
        elif field_name == "duration":
            st.duration = max(3, min(15, st.duration + delta))
        await refresh_setup(cb, st)
        await cb.answer()

    @dp.callback_query(F.data == "go")
    async def cb_go(cb: types.CallbackQuery):
        st = state_for(cb.message.chat.id)
        if st.stage != "setup" or not st.idea:
            await cb.answer("Сначала отправь идею", show_alert=True)
            return
        await cb.answer()
        await start_clarification(cb.message, st)

    @dp.callback_query(F.data.startswith("sug:"))
    async def cb_suggestion(cb: types.CallbackQuery):
        st = state_for(cb.message.chat.id)
        if st.stage != "clarify":
            await cb.answer()
            return
        try:
            _, qi_str, si_str = cb.data.split(":")
            qi, si = int(qi_str), int(si_str)
        except Exception:
            await cb.answer()
            return
        if qi != st.q_index:
            await cb.answer("Этот вопрос уже не активен")
            return
        q = st.questions[qi]
        suggestions = q.get("suggestions", [])
        if 0 <= si < len(suggestions):
            chosen = suggestions[si]
            await cb.message.answer(f"_выбрано:_ {chosen}")
            await cb.answer()
            await record_answer(cb.message, st, chosen)

    @dp.callback_query(F.data == "skip_q")
    async def cb_skip_q(cb: types.CallbackQuery):
        st = state_for(cb.message.chat.id)
        if st.stage == "clarify" and st.q_index < len(st.questions):
            st.q_index += 1
            st.awaiting_custom_answer = False
            await cb.message.answer("_пропущено_")
            await cb.answer()
            await ask_next_question(cb.message, st)

    @dp.callback_query(F.data == "custom")
    async def cb_custom(cb: types.CallbackQuery):
        st = state_for(cb.message.chat.id)
        if st.stage == "clarify":
            st.awaiting_custom_answer = True
            await cb.message.answer("✏ Напиши свой ответ сообщением.")
        await cb.answer()

    @dp.message(F.text)
    async def on_text(message: Message):
        await handle_text(message, message.text.strip())


async def handle_text(message: Message, text: str):
    st = state_for(message.chat.id)

    if st.busy:
        await message.answer("⏳ Подожди, идёт генерация.")
        return

    # Если ждём ответ на вопрос — записываем
    if st.stage == "clarify":
        if not text:
            return
        await message.answer(f"_принято:_ {text}")
        await record_answer(message, st, text)
        return

    # На стадии setup новый текст = новая идея (заменяем)
    # На стадии idle — стартуем
    st.idea = text
    await show_setup(message, st)


# ───────────────────────────── Точка входа ────────────────────────────────────


async def amain():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "Не задан TELEGRAM_BOT_TOKEN. "
            "Запусти: export TELEGRAM_BOT_TOKEN=<твой токен>"
        )
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher()
    register(dp)
    log.info("Бот стартует. Бэкенд: %s", backend_info())
    await dp.start_polling(bot)


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
