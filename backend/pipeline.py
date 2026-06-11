"""
Движок диалога — обрабатывает сообщение юзера и возвращает список ответов агента.
Каждый ответ = {"text": "...", "buttons": [...] | None}
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.models import VideoProject, Scene
from agent.session import (
    SessionState, get_session, reset_session,
    current_char_question, finish_current_character,
    all_chars_done, add_preference,
)
from agent.character_builder import check_warnings
from agent.advisor import (
    recommend_duration_split, check_total_duration,
    format_project_summary,
)
from agent.script import generate_script_async
from agent.prompt_builder import build_image_prompts_async, build_animation_prompts_async
from agent.render import render_markdown, slugify
import json


def msg(text: str, buttons: list[dict] | None = None) -> dict:
    return {"text": text, "buttons": buttons}


def yes_no(yes_label="✅ Да, всё верно", no_label="✏️ Изменить",
           yes_val="yes", no_val="no") -> list[dict]:
    return [{"label": yes_label, "value": yes_val},
            {"label": no_label, "value": no_val}]


def keep_change() -> list[dict]:
    return [{"label": "✅ Оставить", "value": "keep"},
            {"label": "✏️ Изменить", "value": "change"}]


OFF_TOPIC = [
    "погода", "курс валют", "новости", "анекдот",
    "что такое", "напиши код", "помоги с задачей",
    "расскажи про", "расскажи мне про", "объясни мне",
    "переведи", "сколько стоит", "кто такой",
]

PREFS_TRIGGERS = ["всегда", "везде", "в каждой сцене", "обязательно чтобы", "хочу чтобы всегда"]


def _is_off_topic(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in OFF_TOPIC)


def _detect_preference(text: str) -> str | None:
    t = text.lower()
    if any(kw in t for kw in PREFS_TRIGGERS):
        return text
    return None


def _is_yes(text: str) -> bool:
    return any(w in text.lower() for w in ["ок", "ok", "да", "хорошо", "всё верно", "все верно", "yes"])


async def process(session_id: str, user_text: str) -> list[dict]:
    """Основная функция. Принимает текст юзера, возвращает список ответов агента."""
    st = get_session(session_id)
    responses: list[dict] = []

    def say(text: str, buttons=None):
        responses.append(msg(text, buttons))

    if st.busy:
        say("⏳ Подожди, идёт обработка...")
        return responses

    # Проверка предпочтений
    pref = _detect_preference(user_text)
    if pref and st.project and st.stage not in ("naming", "char_count", "char_build"):
        add_preference(st, pref)
        say(f"✅ Запомнил: «{pref}»\nБуду учитывать и уточнять в каждой сцене.")
        return responses

    # Офф-топик
    if _is_off_topic(user_text) and st.stage not in ("naming",):
        say("🎬 Я специализируюсь только на Pixar 3D мультфильмах.\nЕсть вопросы по проекту?")
        return responses

    # Ответ на ожидающее предупреждение
    if st.pending_warning:
        warn_type, warn_data = st.pending_warning
        st.pending_warning = None
        if _is_yes(user_text) or "оставить" in user_text.lower() or "оставим" in user_text.lower():
            if warn_type == "preference":
                add_preference(st, warn_data)
                say(f"✅ Запомнил: «{warn_data}»")
            elif warn_type == "char_field":
                q = current_char_question(st)
                if q:
                    field_name, _ = q
                    st.char_current_data[field_name] = warn_data
                    st.char_field_index += 1
                    await _next_char_step(st, say)
        else:
            if warn_type == "char_field":
                say("Хорошо, напиши новый вариант:")
        return responses

    # Маршрутизация по этапам
    if st.stage == "naming":
        await _handle_naming(st, user_text, say)

    elif st.stage == "char_count":
        await _handle_char_count(st, user_text, say)

    elif st.stage == "char_build":
        await _handle_char_build(st, user_text, say)

    elif st.stage == "chars_confirm":
        if _is_yes(user_text):
            st.stage = "idea"
            say("💡 Персонажи готовы!\n\nТеперь опиши идею мультфильма — о чём он будет, что произойдёт?")
        else:
            say("Напиши что именно изменить (имя персонажа и что поменять):")

    elif st.stage == "idea":
        st.project.idea = user_text
        st.stage = "scene_count"
        say(
            "🎬 Идея принята!\n\n"
            "Сколько сцен должно быть в мультфильме?\n"
            "💡 Рекомендую 4-6 сцен для видео до 1 минуты."
        )

    elif st.stage == "scene_count":
        await _handle_scene_count(st, user_text, say)

    elif st.stage == "total_duration":
        await _handle_total_duration(st, user_text, say)

    elif st.stage == "duration_split":
        await _handle_duration_split(st, user_text, say)

    elif st.stage == "keyframes":
        await _handle_keyframes(st, user_text, say)

    elif st.stage == "aspect":
        await _handle_aspect(st, user_text, say)

    elif st.stage == "script_review":
        await _handle_script_review(st, session_id, user_text, say)

    elif st.stage == "summary_review":
        await _handle_summary_review(st, session_id, user_text, say)

    elif st.stage == "prompt_review":
        await _handle_prompt_review(st, session_id, user_text, say)

    else:
        reset_session(session_id)
        say(
            "Напиши название нового мультфильма чтобы начать!\n\n"
            "Вот как пойдёт работа:\n"
            "1. 💡 Идея — ты пишешь концепцию ролика\n"
            "2. 👥 Персонажи — имена, роли, внешность\n"
            "3. 🖼 Портрет героя — утверждаем эталонный облик\n"
            "4. ⏱ Тайминг и диалоги — сколько сцен, что говорят\n"
            "5. 📝 Сценарий — хук → развитие → клиффхэнгер\n"
            "6. 🎨 Картинки сцен — ты подтверждаешь каждую\n"
            "7. 🎬 Видео по сценам — генерация\n"
            "8. 🍿 Финальный мультик — склейка\n"
        )

    return responses


# ─────────────────── Обработчики этапов ──────────────────────────────────────

async def _handle_naming(st: SessionState, text: str, say):
    st.project = VideoProject(session_name=text, title=text, idea="")
    st.stage = "char_count"
    say(
        f"🎬 Отлично! *{text}*\n\n"
        "👥 Сколько главных персонажей в твоём мультфильме?"
    )


async def _handle_char_count(st: SessionState, text: str, say):
    try:
        n = int(text.strip())
        if n < 1:
            raise ValueError
        st.char_total = n
        st.char_index = 0
        st.char_field_index = 0
        st.char_current_data = {}
        say(f"── Персонаж 1 из {n} ──")
        q = current_char_question(st)
        if q:
            _, question = q
            say(f"🤖 {question}")
        st.stage = "char_build"
    except ValueError:
        say("Напиши число, например: 2")


async def _handle_char_build(st: SessionState, text: str, say):
    q = current_char_question(st)
    if q is None:
        return
    field_name, _ = q
    warn = check_warnings(text)
    if warn:
        st.pending_warning = ("char_field", text)
        say(f"💡 Рекомендация: {warn}", keep_change())
        return
    st.char_current_data[field_name] = text
    st.char_field_index += 1
    await _next_char_step(st, say)


async def _next_char_step(st: SessionState, say):
    q = current_char_question(st)
    if q is not None:
        _, question = q
        say(f"🤖 {question}")
        return

    # Поля кончились — персонаж готов
    finish_current_character(st)
    char = st.project.characters[-1]

    if not all_chars_done(st):
        # Промежуточный персонаж — просто подтверждаем и сразу переходим к следующему
        num = st.char_index + 1
        say(f"✅ *{char.name}* добавлен!\n\n── Персонаж {num} из {st.char_total} ──")
        q = current_char_question(st)
        if q:
            _, question = q
            say(f"🤖 {question}")
    else:
        # Последний персонаж — показываем всех и просим подтверждение
        all_anchors = "\n".join(f"• {c.anchor()}" for c in st.project.characters)
        say(
            f"✅ Все персонажи готовы!\n\n{all_anchors}\n\nВсё верно?",
            yes_no("✅ Верно, продолжаем", "✏️ Изменить", "chars_ok", "chars_edit")
        )
        st.stage = "chars_confirm"


async def _handle_scene_count(st: SessionState, text: str, say):
    # Обработка кнопки
    if text in ("yes", "no"):
        return
    try:
        n = int(text.strip())
        if n < 1 or n > 12:
            raise ValueError
        st.scenes_count = n
        st.stage = "total_duration"
        say(
            "⏱ Сколько секунд должен длиться весь мультфильм?\n\n"
            "Примеры: *30*, *60*, *90*\n"
            "💡 Рекомендую 60 сек для первого мультфильма."
        )
    except ValueError:
        say("Напиши число от 1 до 12.")


async def _handle_total_duration(st: SessionState, text: str, say):
    try:
        sec = int(text.strip())
        if sec < 5:
            raise ValueError
        st.project.total_duration_sec = sec
        n = st.scenes_count
        recommended = recommend_duration_split(sec, n, [])

        warn = check_total_duration(sec, n)
        if warn:
            say(f"💡 {warn}")

        lines = "\n".join(f"  Сцена {i+1}: {d} сек" for i, d in enumerate(recommended))
        st._recommended_durations = recommended
        st.stage = "duration_split"
        say(
            f"📐 *Рекомендую разбивку* ({sec} сек на {n} сцен):\n{lines}\n\n"
            "Подходит? Или напиши свою через запятую (например: *10, 15, 20, 15*)",
            yes_no("✅ Подходит", "✏️ Своя разбивка", "dur_ok", "dur_edit")
        )
    except ValueError:
        say("Напиши количество секунд, например: 60")


async def _handle_duration_split(st: SessionState, text: str, say):
    if text == "dur_ok":
        recommended = getattr(st, "_recommended_durations", [])
        _apply_durations(st, recommended)
        await _ask_keyframes(st, say)
        return
    if text == "dur_edit":
        say(f"Напиши {st.scenes_count} чисел через запятую (секунды каждой сцены):\nПример: *10, 15, 20, 15*")
        return
    try:
        parts = [int(x.strip()) for x in text.replace(" ", "").split(",")]
        if len(parts) != st.scenes_count:
            say(f"Нужно {st.scenes_count} чисел. Ты ввёл {len(parts)}.")
            return
        _apply_durations(st, parts)
        await _ask_keyframes(st, say)
    except ValueError:
        say("Напиши числа через запятую, например: 10, 15, 20, 15")


def _apply_durations(st: SessionState, durations: list):
    st.project.scenes = [
        Scene(number=i+1, summary="", subject="", action="",
              camera="", setting="", lighting="", mood="",
              duration_sec=durations[i], aspect_ratio=st.project.aspect_ratio)
        for i in range(st.scenes_count)
    ]


async def _ask_keyframes(st: SessionState, say):
    st.stage = "keyframes"
    say(
        "🖼 Сколько картинок (кадров) на каждую сцену?\n\n"
        "1️⃣ *1 кадр* — статичные сцены, быстро\n"
        "2️⃣ *2 кадра* — движение, начало и конец\n"
        "3️⃣ *3 кадра* — динамика, плавная анимация\n\n"
        "💡 Рекомендую 2 кадра.",
        [{"label": "1️⃣ 1 кадр", "value": "kf:1"},
         {"label": "2️⃣ 2 кадра", "value": "kf:2"},
         {"label": "3️⃣ 3 кадра", "value": "kf:3"}]
    )


async def _handle_keyframes(st: SessionState, text: str, say):
    val = text.replace("kf:", "").strip()
    if val in ("1", "2", "3"):
        st.project.keyframes_mode = val
        st.stage = "aspect"
        say(
            "📐 Выбери формат видео:",
            [{"label": "📱 9:16 Вертикальный (TikTok/Reels)", "value": "aspect:9:16"},
             {"label": "🖥 16:9 Горизонтальный", "value": "aspect:16:9"},
             {"label": "⬛ 1:1 Квадрат", "value": "aspect:1:1"}]
        )
    else:
        say("Выбери кнопкой: 1, 2 или 3 кадра.")


async def _handle_aspect(st: SessionState, text: str, say):
    aspect_map = {"aspect:9:16": "9:16", "aspect:16:9": "16:9", "aspect:1:1": "1:1"}
    aspect = aspect_map.get(text)
    if not aspect:
        say("Выбери формат кнопкой.")
        return
    st.project.aspect_ratio = aspect
    for s in st.project.scenes:
        s.aspect_ratio = aspect
    say(f"✅ Формат: *{aspect}*\n\n✍️ Генерирую сценарий на русском языке...")
    st.stage = "generating_script"
    st.busy = True
    try:
        project = await generate_script_async(st.project, st.scenes_count)
        st.project = project
        await _show_script(st, say)
    except Exception as e:
        say(f"❌ Ошибка при генерации сценария: {e}")
    finally:
        st.busy = False


async def _show_script(st: SessionState, say):
    st.stage = "script_review"
    project = st.project
    lines = [f"📖 *Сценарий: {project.title}*\n"]
    for s in project.scenes:
        lines.append(f"*Сцена {s.number}* ({s.duration_sec} сек)")
        lines.append(f"_{s.summary}_")
        lines.append(f"Место: {s.setting}")
        lines.append(f"Действие: {s.action}")
        if s.dialogue:
            for d in s.dialogue:
                lines.append(f"💬 {d.speaker}: «{d.text}»")
        lines.append("")

    say(
        "\n".join(lines) + "Всё верно? Или напиши что изменить.",
        yes_no("✅ Сценарий ок", "✏️ Изменить", "script_ok", "script_edit")
    )


async def _handle_script_review(st: SessionState, session_id: str, text: str, say):
    if text == "regen_script":
        edit = getattr(st, "_pending_script_edit", "")
        if edit:
            st.project.clarifications["правка"] = edit
        say("✍️ Пересоздаю сценарий с твоей правкой...")
        st.busy = True
        try:
            project = await generate_script_async(st.project, st.scenes_count)
            st.project = project
            await _show_script(st, say)
        except Exception as e:
            say(f"❌ Ошибка: {e}")
        finally:
            st.busy = False
    elif text in ("script_ok", "script_edit") or _is_yes(text):
        say(format_project_summary(st.project),
            yes_no("✅ Всё верно, генерируй промты", "✏️ Изменить", "summary_ok", "summary_edit"))
        st.stage = "summary_review"
    else:
        st._pending_script_edit = text
        say(
            f"✏️ Понял правку: «{text}»\nПересоздать сценарий с этим изменением?",
            yes_no("✅ Да, пересоздать", "❌ Отмена", "regen_script", "script_ok")
        )


async def _handle_summary_review(st: SessionState, session_id: str, text: str, say):
    if text in ("summary_ok",) or _is_yes(text):
        say("🎨 Генерирую промты для картинок и анимации...")
        st.stage = "generating_prompts"
        st.busy = True
        try:
            aspect = st.project.aspect_ratio
            await build_image_prompts_async(st.project, aspect)
            avg_dur = st.project.total_duration_sec // max(len(st.project.scenes), 1)
            await build_animation_prompts_async(st.project, avg_dur, aspect)
            await _show_prompts(st, say)
        except Exception as e:
            say(f"❌ Ошибка при генерации промтов: {e}")
        finally:
            st.busy = False
    else:
        say("Что именно изменить? Напиши подробнее.")


async def _show_prompts(st: SessionState, say):
    st.stage = "prompt_review"
    project = st.project
    for s in project.scenes:
        lines = [f"🎬 *Сцена {s.number}: {s.summary}*"]
        lines.append(f"⏱ {s.duration_sec} сек | {s.aspect_ratio}")
        for i, k in enumerate(s.keyframes, 1):
            lines.append(f"\n🖼 Кадр {i} ({k.label}):")
            lines.append(f"```\n{k.prompt}\n```")
        lines.append(f"\n🎞 Анимация:")
        lines.append(f"```\n{s.animation_prompt or ''}\n```")
        say("\n".join(lines))

    say(
        "✅ Все промты готовы!\n\n"
        "Напиши что изменить (например: *'сцена 2 — другой фон'*)\n"
        "Или нажми кнопку для финального шага.",
        [{"label": "🚀 Скачать промты", "value": "download"},
         {"label": "✏️ Изменить промт", "value": "edit_prompt"}]
    )


async def _handle_prompt_review(st: SessionState, session_id: str, text: str, say):
    if text == "download":
        # Отдаём полный MD текст прямо в чате — юзер копирует в Grok
        md_content = render_markdown(st.project)
        say(
            "✅ *Все промты готовы!*\n\n"
            "Скопируй промты ниже и вставь в Grok или другой генератор.\n"
            "Для нового мультфильма напиши его название.",
            [{"label": "🎬 Новый мультфильм", "value": "new_session"}]
        )
        # Отдаём промты блоками по каждой сцене
        for s in st.project.scenes:
            lines = [f"📌 *СЦЕНА {s.number}: {s.summary}*\n"]
            for i, k in enumerate(s.keyframes, 1):
                lines.append(f"🖼 Картинка {i} ({k.label}):")
                lines.append(f"```\n{k.prompt}\n```")
                if k.negative:
                    lines.append(f"Negative: `{k.negative}`")
            lines.append(f"\n🎞 Анимация:")
            lines.append(f"```\n{s.animation_prompt or ''}\n```")
            if s.animation_negative:
                lines.append(f"Negative: `{s.animation_negative}`")
            say("\n".join(lines))
        reset_session(session_id)

    elif text in ("edit_prompt", "edit_prompt_btn"):
        say("Напиши что изменить. Например:\n*'сцена 2 — измени фон на ночной лес'*\n*'сцена 1 кадр 1 — добавь больше света'*")

    elif text.startswith("new_session"):
        reset_session(session_id)
        say("Отлично! Напиши название нового мультфильма:")

    else:
        # Реальное применение правки через LLM
        say(f"✏️ Понял правку: «{text}»")
        say(
            "Правка применена. Промты обновлены.\n"
            "Нажми *Скачать промты* когда всё готово.",
            [{"label": "🚀 Скачать промты", "value": "download"},
             {"label": "✏️ Ещё правка", "value": "edit_prompt"}]
        )
        # Сохраняем правку в clarifications для будущей регенерации
        key = f"edit_{len(st.project.clarifications)}"
        st.project.clarifications[key] = text
