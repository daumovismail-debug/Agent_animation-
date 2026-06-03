"""
Telegram-бот поверх агента генерации промтов для Grok.

Запуск:
    export TELEGRAM_BOT_TOKEN=<твой токен>
    python -m agent.bot

Команды:
    /start              — приветствие
    /new <идея>         — начать новый ролик (или просто отправить текст)
    /style <вариант>    — выбрать стиль (cinematic/anime/3d/realistic/cartoon)
    /scenes <число>     — выбрать количество сцен (по умолчанию 4)
    /skip               — пропустить уточняющие вопросы и сгенерировать сразу
    /cancel             — отменить текущую сессию

Кнопки под вопросами позволяют выбрать вариант ответа в один тап.
Свой вариант — просто отправь его текстом.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
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
DEFAULT_STYLE = "cinematic"
DEFAULT_SCENES = 4
DEFAULT_DURATION = 6
DEFAULT_ASPECT = "16:9"

# Состояние диалога с пользователем (in-memory, на чат)
@dataclass
class ChatState:
    idea: Optional[str] = None
    style: str = DEFAULT_STYLE
    scenes_count: int = DEFAULT_SCENES
    duration: int = DEFAULT_DURATION
    aspect: str = DEFAULT_ASPECT
    plan: Optional[dict] = None              # ответ plan_questions
    questions: list = field(default_factory=list)
    q_index: int = 0
    answers: dict = field(default_factory=dict)
    is_dialogue_heavy: bool = False
    busy: bool = False


STATES: dict[int, ChatState] = {}


def state_for(chat_id: int) -> ChatState:
    s = STATES.get(chat_id)
    if s is None:
        s = ChatState()
        STATES[chat_id] = s
    return s


def reset(chat_id: int):
    STATES.pop(chat_id, None)


# ───────────────────────────── Клавиатуры ──────────────────────────────────────


def kb_suggestions(q_index: int, suggestions: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for i, s in enumerate(suggestions):
        rows.append(
            [InlineKeyboardButton(text=s, callback_data=f"sug:{q_index}:{i}")]
        )
    rows.append(
        [
            InlineKeyboardButton(text="✏ свой вариант", callback_data="custom"),
            InlineKeyboardButton(text="⏭ пропустить", callback_data="skip_q"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_styles() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=s, callback_data=f"style:{s}")] for s in STYLES
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ───────────────────────────── Хелперы шагов ──────────────────────────────────


async def start_clarification(message: Message, st: ChatState):
    """Спрашиваем Claude план уточнений и шлём первый вопрос."""
    await message.answer("🧠 Анализирую идею, думаю что доуточнить…")
    plan = await plan_questions_async(st.idea, st.style)
    st.plan = plan
    st.is_dialogue_heavy = bool(plan.get("is_dialogue_heavy", False))
    st.questions = plan.get("questions", []) or []
    st.q_index = 0
    st.answers = {}

    reasoning = plan.get("reasoning", "")
    head = f"💡 {reasoning}" if reasoning else ""
    if st.is_dialogue_heavy:
        head += "\n\n🗣 Ролик разговорный — будут вопросы про голос и реплики."

    if not st.questions:
        if head:
            await message.answer(head)
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
        await message.answer(text + "\n\n_напиши ответ текстом_")


async def record_answer(message: Message, st: ChatState, answer: str):
    if st.q_index >= len(st.questions):
        return
    q = st.questions[st.q_index]
    st.answers[q["key"]] = answer
    st.q_index += 1
    await ask_next_question(message, st)


async def run_generation(message: Message, st: ChatState):
    if st.busy:
        await message.answer("⏳ Уже работаю над предыдущим запросом, подожди.")
        return
    st.busy = True
    try:
        await message.answer(
            f"📝 Пишу сценарий ({st.scenes_count} сцен, стиль *{st.style}*)…"
        )
        project = await generate_script_async(
            idea=st.idea,
            style=st.style,
            scenes_count=st.scenes_count,
            is_dialogue_heavy=st.is_dialogue_heavy,
            clarifications=st.answers,
        )
        await message.answer(
            f"🎬 «{project.title}» — {len(project.scenes)} сцен.\n"
            f"🖼 Генерирую промты для картинок…"
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
    # Краткое описание + по одному сообщению на сцену
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

    # Файлы
    slug = slugify(project.title)
    md_bytes = render_markdown(project).encode("utf-8")
    json_bytes = json.dumps(
        project.to_dict(), ensure_ascii=False, indent=2
    ).encode("utf-8")

    await message.answer_document(
        BufferedInputFile(md_bytes, filename=f"{slug}.md"),
        caption="📄 Полный сценарий — открой и копируй промты в Grok.",
    )
    await message.answer_document(
        BufferedInputFile(json_bytes, filename=f"{slug}.json"),
        caption="🗂 То же в JSON — для дальнейшей автоматизации.",
    )
    await message.answer("Готов к следующей идее — просто отправь её сообщением.")


# ───────────────────────────── Хендлеры ────────────────────────────────────────


def register(dp: Dispatcher):

    @dp.message(CommandStart())
    async def cmd_start(message: Message):
        reset(message.chat.id)
        await message.answer(
            "👋 Привет! Я помогу собрать промты для ИИ-видео в Grok.\n\n"
            f"Бэкенд: _{backend_info()}_\n"
            "Модель: *Claude Opus 4.7* + extended thinking (high)\n\n"
            "Просто отправь мне идею ролика одним сообщением, например:\n"
            "_«девочка-волшебница спасает кота из горящего дома»_\n\n"
            "Команды:\n"
            "/style — выбрать визуальный стиль\n"
            "/scenes N — сколько сцен (по умолчанию 4)\n"
            "/skip — пропустить уточняющие вопросы\n"
            "/cancel — отменить текущую сессию"
        )

    @dp.message(Command("cancel"))
    async def cmd_cancel(message: Message):
        reset(message.chat.id)
        await message.answer("❎ Сессия сброшена. Жду новую идею.")

    @dp.message(Command("style"))
    async def cmd_style(message: Message):
        st = state_for(message.chat.id)
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 2 and parts[1].strip() in STYLES:
            st.style = parts[1].strip()
            await message.answer(f"🎨 Стиль: *{st.style}*")
            return
        await message.answer(
            f"Текущий стиль: *{st.style}*\nВыбери новый:",
            reply_markup=kb_styles(),
        )

    @dp.message(Command("scenes"))
    async def cmd_scenes(message: Message):
        st = state_for(message.chat.id)
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 2 and parts[1].isdigit():
            n = max(1, min(10, int(parts[1])))
            st.scenes_count = n
            await message.answer(f"🎬 Количество сцен: *{n}*")
            return
        await message.answer(
            f"Текущее количество сцен: *{st.scenes_count}*\n"
            f"Использование: `/scenes 5`"
        )

    @dp.message(Command("skip"))
    async def cmd_skip(message: Message):
        st = state_for(message.chat.id)
        if not st.idea:
            await message.answer("Сначала отправь идею ролика.")
            return
        if st.questions and st.q_index < len(st.questions):
            await message.answer("⏭ Пропускаю уточнения, генерирую с тем что есть.")
            await run_generation(message, st)
            return
        await message.answer("✅ Запускаю генерацию.")
        await run_generation(message, st)

    @dp.message(Command("new"))
    async def cmd_new(message: Message):
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.answer("Использование: `/new идея ролика`")
            return
        await handle_idea_or_answer(message, parts[1].strip())

    @dp.callback_query(F.data.startswith("sug:"))
    async def cb_suggestion(cb: types.CallbackQuery):
        st = state_for(cb.message.chat.id)
        try:
            _, qi_str, si_str = cb.data.split(":")
            qi, si = int(qi_str), int(si_str)
        except Exception:
            await cb.answer()
            return
        if qi != st.q_index:
            await cb.answer("Этот вопрос уже не активен", show_alert=False)
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
        if st.questions and st.q_index < len(st.questions):
            st.q_index += 1
            await cb.message.answer("_пропущено_")
            await cb.answer()
            await ask_next_question(cb.message, st)

    @dp.callback_query(F.data == "custom")
    async def cb_custom(cb: types.CallbackQuery):
        await cb.message.answer("✏ Напиши свой вариант ответа сообщением.")
        await cb.answer()

    @dp.callback_query(F.data.startswith("style:"))
    async def cb_style(cb: types.CallbackQuery):
        st = state_for(cb.message.chat.id)
        new = cb.data.split(":", 1)[1]
        if new in STYLES:
            st.style = new
            await cb.message.answer(f"🎨 Стиль: *{new}*")
        await cb.answer()

    @dp.message(F.text)
    async def on_text(message: Message):
        await handle_idea_or_answer(message, message.text.strip())


async def handle_idea_or_answer(message: Message, text: str):
    st = state_for(message.chat.id)

    # Если идёт диалог по вопросам — это ответ
    if st.questions and st.q_index < len(st.questions):
        await message.answer(f"_принято:_ {text}")
        await record_answer(message, st, text)
        return

    # Иначе — это новая идея
    if st.busy:
        await message.answer("⏳ Подожди, генерирую предыдущий запрос.")
        return

    st.idea = text
    await message.answer(
        f"🎯 Идея принята: _{text}_\n"
        f"🎨 Стиль: *{st.style}*, сцен: *{st.scenes_count}*"
    )
    await start_clarification(message, st)


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
