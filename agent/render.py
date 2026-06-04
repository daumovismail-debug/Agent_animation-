import re
from .models import VideoProject


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s-]+", "-", text)
    return text[:60] or "project"


_KF_TITLE = {
    "only": "ключевой кадр",
    "start": "первый кадр (start)",
    "middle": "средний кадр (middle)",
    "end": "последний кадр (end)",
}


def render_markdown(project: VideoProject) -> str:
    lines = [
        f"# {project.title}",
        "",
        f"**Идея:** {project.idea}",
        f"**Стиль:** {project.style}",
        f"**Сцен:** {len(project.scenes)}",
        f"**Разговорное видео:** {'да' if project.is_dialogue_heavy else 'нет'}",
        f"**Режим кадров:** {project.keyframes_mode}",
        "",
        f"**Главный герой (anchor):** {project.character_anchor}",
        "",
    ]
    if project.voice_notes:
        lines += [f"**Голос:** {project.voice_notes}", ""]
    if project.clarifications:
        lines += ["**Уточнения:**", ""]
        for k, v in project.clarifications.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
    lines += ["---", ""]

    for s in project.scenes:
        lines += [
            f"## Сцена {s.number}: {s.summary}",
            "",
            f"- {s.duration_sec} сек | {s.aspect_ratio} | {s.mood} | "
            f"кадров: {len(s.keyframes)}",
            "",
            "### Промты для картинок",
            "",
        ]
        for i, k in enumerate(s.keyframes, 1):
            title = _KF_TITLE.get(k.label, k.label)
            lines += [
                f"**{i}. {title}**",
                "",
                "```",
                k.prompt,
                "```",
                "",
            ]
            if k.negative:
                lines += ["Negative:", "```", k.negative, "```", ""]
        lines += [
            "### Промт для анимации (image-to-video)",
            "",
            "```",
            s.animation_prompt or "",
            "```",
            "",
        ]
        if s.animation_negative:
            lines += ["Negative:", "```", s.animation_negative, "```", ""]
        if s.dialogue:
            lines += ["### Реплики", ""]
            for d in s.dialogue:
                emo = f" _({d.emotion})_" if d.emotion else ""
                lines.append(f"- **{d.speaker}**{emo}: {d.text}")
            lines.append("")
        lines += ["---", ""]
    return "\n".join(lines)


def render_script_preview(project) -> list[str]:
    """
    Развёрнутый сценарий на языке проекта — для показа в Telegram до
    того как пойдут промты для Grok. Возвращает список сообщений
    (один header + по одному на сцену).
    """
    messages = []
    head = [
        f"📖 *Сценарий: {project.title}*",
        "",
        f"👤 *Главный герой:* {project.character_anchor}",
    ]
    if project.voice_notes:
        head.append(f"🔊 *Голос:* {project.voice_notes}")
    head += ["", f"📋 *Всего сцен:* {len(project.scenes)}"]
    messages.append("\n".join(head))

    for s in project.scenes:
        parts = [
            f"🎬 *Сцена {s.number}/{len(project.scenes)}:* {s.summary}",
            "",
            f"👁 *В кадре:* {s.subject}",
            f"🎭 *Действие:* {s.action}",
            f"📷 *Камера:* {s.camera}",
            f"🏞 *Где:* {s.setting}",
            f"💡 *Свет:* {s.lighting}",
            f"💫 *Настроение:* {s.mood}",
        ]
        if s.dialogue:
            parts += ["", "💬 *Реплики:*"]
            for d in s.dialogue:
                emo = f" ({d.emotion})" if d.emotion else ""
                parts.append(f"• *{d.speaker}*{emo}: {d.text}")
        messages.append("\n".join(parts))
    return messages


def render_scene_brief(scene, total: int) -> str:
    """Краткий блок для одной сцены, в телеграм."""
    parts = [
        f"🎬 Сцена {scene.number}/{total}: {scene.summary}",
        f"⏱ {scene.duration_sec}с | {scene.aspect_ratio} | {scene.mood} | "
        f"🖼 кадров: {len(scene.keyframes)}",
        "",
    ]
    for i, k in enumerate(scene.keyframes, 1):
        title = _KF_TITLE.get(k.label, k.label)
        parts += [
            f"🖼 *{i}. {title}*",
            f"```\n{k.prompt}\n```",
        ]
        if k.negative:
            parts.append(f"_neg:_ `{k.negative}`")
        parts.append("")
    parts += [
        "🎞 *Анимация:*",
        f"```\n{scene.animation_prompt or ''}\n```",
    ]
    if scene.animation_negative:
        parts.append(f"_neg:_ `{scene.animation_negative}`")
    if scene.dialogue:
        parts += ["", "💬 *Реплики:*"]
        for d in scene.dialogue:
            emo = f" ({d.emotion})" if d.emotion else ""
            parts.append(f"• *{d.speaker}*{emo}: {d.text}")
    return "\n".join(parts)
