"""
pipeline_agent.py — агентная замена для pipeline.py.
Claude ведёт диалог и управляет проектом вместо жёсткого FSM.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.session import SessionState, get_session, reset_session, add_preference
from agent.models import VideoProject, Character, Scene
from agent.script import generate_script_async
from agent.prompt_builder import build_image_prompts_async, build_animation_prompts_async
from agent.render import render_markdown
from agent.advisor import recommend_duration_split
from agent.llm import ask_json_async

SYSTEM_TMPL = """Ты — PixarGen, агент для создания сценариев и промтов Pixar 3D анимации.
Веди диалог, собирай данные о мультфильме, запускай генерацию.
Отвечай ТОЛЬКО на русском. Только тема Pixar 3D анимации — остальное отклоняй.

## Состояние проекта:
{state}

## История диалога (последние сообщения):
{history}

## Что нужно собрать (отмечено ✓ если готово):
{checklist}

## Формат ответа — ТОЛЬКО JSON, без преамбулы, без markdown-обёртки:
{{
  "actions": [
    // Опциональные обновления данных (перед reply):
    {{"type": "set_field", "field": "title|idea|scenes_count|total_duration_sec|keyframes_mode|aspect_ratio|char_total", "value": "..."}},
    {{"type": "add_character", "name": "...", "age": "...", "appearance": "...", "clothing": "...", "personality": "...", "speech_style": "...", "special_features": "нет"}},
    // Обязательным последним — одно из:
    {{"type": "reply", "text": "...", "buttons": [{{"label": "...", "value": "..."}}]}},
    {{"type": "generate_script"}},
    {{"type": "generate_prompts"}}
  ]
}}

## Правила сбора данных:
- title: назначается автоматически из первого сообщения (название мультфильма)
- char_total: число персонажей которое назвал пользователь
- Собирай персонажей по одному, все 7 полей (имя, возраст, внешность, одежда, характер, речь, особенности)
- scenes_count: рекомендуй 4-6, максимум 12
- total_duration_sec: рекомендуй 60, минимум 10
- keyframes_mode: "1", "2" или "3" (рекомендуй "2")
- aspect_ratio: "9:16", "16:9" или "1:1"

## Когда переходить к генерации:
- generate_script: когда ВСЕ поля в чеклисте ✓ И сценарий ещё не готов
- generate_prompts: когда пользователь одобрил сценарий (сказал "ок", "да", нажал "script_ok")
- После generate_prompts — больше не нужен reply, промты будут показаны автоматически

## Предлагай кнопки для удобства:
- После каждого вопроса с вариантами — добавляй buttons
- Пример для сцен: [{{"label": "4 сцены", "value": "4"}}, {{"label": "6 сцен", "value": "6"}}]
- Пример для формата: [{{"label": "📱 9:16", "value": "9:16"}}, {{"label": "🖥 16:9", "value": "16:9"}}]
"""


def _project_state_str(st: SessionState) -> str:
    if not st.project:
        return "Проект не начат"

    p = st.project
    chars_info = f"{len(p.characters)}/{st.char_total or '?'}"

    has_script = bool(p.scenes and p.scenes[0].summary)
    has_prompts = bool(p.scenes and p.scenes and p.scenes[0].keyframes)

    return "\n".join([
        f"Название: {p.title or '—'}",
        f"Идея: {(p.idea[:80] + '...') if p.idea and len(p.idea) > 80 else (p.idea or '—')}",
        f"Персонажи: {', '.join(c.name for c in p.characters) or '—'} ({chars_info})",
        f"Сцен: {st.scenes_count or '—'}",
        f"Длительность: {p.total_duration_sec} сек",
        f"Кадров на сцену: {p.keyframes_mode or '—'}",
        f"Формат: {p.aspect_ratio or '—'}",
        f"Стадия: {st.stage}",
        f"Сценарий: {'✓ готов' if has_script else '✗ нет'}",
        f"Промты: {'✓ готовы' if has_prompts else '✗ нет'}",
    ])


def _checklist(st: SessionState) -> str:
    p = st.project
    if not p:
        return "✗ название\n✗ персонажи\n✗ идея\n✗ сцены\n✗ длительность\n✗ кадры\n✗ формат"

    chars_ok = bool(p.characters) and len(p.characters) >= (st.char_total or 1)

    lines = [
        f"{'✓' if p.title else '✗'} название",
        f"{'✓' if chars_ok else '✗'} персонажи ({len(p.characters)}/{st.char_total or '?'})",
        f"{'✓' if p.idea else '✗'} идея/сюжет",
        f"{'✓' if st.scenes_count else '✗'} количество сцен",
        f"{'✓' if p.total_duration_sec else '✗'} длительность",
        f"{'✓' if p.keyframes_mode else '✗'} кадров на сцену",
        f"{'✓' if p.aspect_ratio else '✗'} формат видео",
    ]

    return "\n".join(lines)


def _format_history(rows: list[dict]) -> str:
    if not rows:
        return "(история пуста)"

    lines = []
    for r in rows[-20:]:
        role = "Пользователь" if r["role"] == "user" else "PixarGen"
        text = r["text"][:300].replace("\n", " ")
        lines.append(f"{role}: {text}")

    return "\n".join(lines)


def _apply_set_field(st: SessionState, field: str, value) -> None:
    if not st.project:
        st.project = VideoProject(session_name="", title="", idea="")

    if field == "title":
        st.project.title = str(value)
        if not st.project.session_name:
            st.project.session_name = str(value)
        if st.stage == "naming":
            st.stage = "char_count"
            return
        return

    elif field == "idea":
        st.project.idea = str(value)
        return

    elif field == "scenes_count":
        st.scenes_count = int(value)
        return

    elif field == "total_duration_sec":
        st.project.total_duration_sec = int(value)
        if st.scenes_count:
            if not st.project.scenes:
                durs = recommend_duration_split(int(value), st.scenes_count, [])
                st.project.scenes = [
                    Scene(
                        number=i + 1,
                        summary="",
                        subject="",
                        action="",
                        camera="",
                        setting="",
                        lighting="",
                        mood="",
                        duration_sec=durs[i],
                        aspect_ratio=st.project.aspect_ratio,
                    )
                    for i in range(st.scenes_count)
                ]
                return
            return
        return

    elif field == "keyframes_mode":
        st.project.keyframes_mode = str(value)
        return

    elif field == "aspect_ratio":
        st.project.aspect_ratio = str(value)
        for s in st.project.scenes:
            s.aspect_ratio = str(value)
        return

    elif field == "char_total":
        st.char_total = int(value)
        return


def _apply_add_character(st: SessionState, action: dict) -> None:
    if not st.project:
        return

    char = Character(
        name=action.get("name", ""),
        age=action.get("age", ""),
        appearance=action.get("appearance", ""),
        clothing=action.get("clothing", ""),
        personality=action.get("personality", ""),
        speech_style=action.get("speech_style", ""),
        special_features=action.get("special_features", "нет"),
    )

    st.project.characters.append(char)
    st.project.character_anchor = st.project.build_character_anchor()

    if st.stage in ("naming", "char_count", "char_build"):
        st.stage = "char_build"
        return


def _show_script(project: VideoProject) -> dict:
    lines = [f"📖 *Сценарий: {project.title}*\n"]

    for s in project.scenes:
        lines.append(f"*Сцена {s.number}* ({s.duration_sec} сек)")
        lines.append(f"_{s.summary}_")
        lines.append(f"📍 {s.setting}")
        lines.append(f"▶ {s.action}")
        if s.dialogue:
            for d in s.dialogue:
                lines.append(f"💬 {d.speaker}: «{d.text}»")
        lines.append("")

    return {
        "text": "\n".join(lines) + "Всё верно? Или напиши что изменить.",
        "buttons": [
            {"label": "✅ Сценарий ок", "value": "script_ok"},
            {"label": "✏️ Изменить", "value": "script_edit"},
        ],
    }


def _show_prompts(project: VideoProject) -> list[dict]:
    msgs = []

    for s in project.scenes:
        lines = [
            f"🎬 *Сцена {s.number}: {s.summary}*",
            f"⏱ {s.duration_sec} сек | {s.aspect_ratio}",
        ]
        for i, k in enumerate(s.keyframes, 1):
            lines.append(f"\n🖼 Кадр {i} ({k.label}):")
            lines.append(f"```\n{k.prompt}\n```")
        lines.append("\n🎞 Анимация:")
        lines.append(f"```\n{s.animation_prompt or ''}\n```")
        msgs.append({"text": "\n".join(lines)})

    msgs.append({
        "text": "✅ Все промты готовы!\nНапиши что изменить или скачай результат.",
        "buttons": [
            {"label": "🚀 Скачать промты", "value": "download"},
            {"label": "✏️ Изменить промт", "value": "edit_prompt"},
        ],
    })

    return msgs


async def process(session_id: str, user_text: str) -> list[dict]:
    """Агентная обработка сообщения пользователя."""
    st = get_session(session_id)

    if st.busy:
        return [{"text": "⏳ Подожди, идёт обработка..."}]

    # Скачать промты — специальная команда без LLM
    if user_text == "download" and st.project and st.stage == "prompt_review":
        msgs = []
        for s in st.project.scenes:
            lines = [f"📌 *СЦЕНА {s.number}: {s.summary}*\n"]
            for i, k in enumerate(s.keyframes, 1):
                lines.append(f"🖼 Картинка {i} ({k.label}):")
                lines.append(f"```\n{k.prompt}\n```")
            lines.append("\n🎞 Анимация:")
            lines.append(f"```\n{s.animation_prompt or ''}\n```")
            msgs.append({"text": "\n".join(lines)})

        msgs.append({
            "text": "✅ Готово! Для нового мультфильма напиши его название.",
            "buttons": [{"label": "🎬 Новый мультфильм", "value": "new_session"}],
        })

        reset_session(session_id)
        return msgs

    # Новая сессия
    if user_text == "new_session":
        reset_session(session_id)
        return [{"text": "Напиши название нового мультфильма:"}]

    # Основной путь: LLM-агент
    from db import get_messages
    history_rows = await get_messages(session_id)

    system = SYSTEM_TMPL.format(
        state=_project_state_str(st),
        history=_format_history(history_rows),
        checklist=_checklist(st),
    )

    try:
        result = await ask_json_async(system, user_text)
    except Exception as e:
        return [{"text": f"❌ Ошибка агента: {e}"}]

    actions = result.get("actions", [])
    if not actions:
        return [{"text": "❌ Агент вернул пустой ответ. Попробуй ещё раз."}]

    responses = []
    st.busy = True
    try:
        for action in actions:
            atype = action.get("type")

            if atype == "set_field":
                _apply_set_field(st, action.get("field", ""), action.get("value"))

            elif atype == "add_character":
                _apply_add_character(st, action)

            elif atype == "reply":
                payload = {"text": action.get("text", "")}
                if action.get("buttons"):
                    payload["buttons"] = action["buttons"]
                responses.append(payload)

            elif atype == "generate_script":
                if not st.project:
                    responses.append({"text": "❌ Проект не инициализирован"})
                    continue

                responses.append({"text": "✍️ Генерирую сценарий..."})
                st.stage = "generating_script"
                try:
                    project = await generate_script_async(
                        st.project, st.scenes_count or 4
                    )
                    st.project = project
                    st.stage = "script_review"
                    responses.append(_show_script(project))
                except Exception as e:
                    responses.append({"text": f"❌ Ошибка генерации сценария: {e}"})
                    st.stage = "script_review"

            elif atype == "generate_prompts":
                if not st.project or not st.project.scenes:
                    responses.append({"text": "❌ Сначала нужно сгенерировать сценарий"})
                    continue

                responses.append({"text": "🎨 Генерирую промты для картинок и анимации..."})
                st.stage = "generating_prompts"
                try:
                    aspect = st.project.aspect_ratio
                    await build_image_prompts_async(st.project, aspect)
                    avg_dur = st.project.total_duration_sec // max(len(st.project.scenes), 1)
                    await build_animation_prompts_async(st.project, avg_dur, aspect)
                    st.stage = "prompt_review"
                    responses.extend(_show_prompts(st.project))
                except Exception as e:
                    responses.append({"text": f"❌ Ошибка генерации промтов: {e}"})
                    st.stage = "prompt_review"

    finally:
        st.busy = False

    return responses or [{"text": "❌ Агент не вернул ответа. Попробуй ещё раз."}]
