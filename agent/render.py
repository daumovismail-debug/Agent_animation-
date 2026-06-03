import re
from .models import VideoProject


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s-]+", "-", text)
    return text[:60] or "project"


def render_markdown(project: VideoProject) -> str:
    lines = [
        f"# {project.title}",
        "",
        f"**Идея:** {project.idea}",
        f"**Стиль:** {project.style}",
        f"**Сцен:** {len(project.scenes)}",
        f"**Разговорное видео:** {'да' if project.is_dialogue_heavy else 'нет'}",
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
            f"- {s.duration_sec} сек | {s.aspect_ratio} | настроение: {s.mood}",
            "",
            "### 1. Промт для картинки (ключевой кадр)",
            "",
            "```",
            s.image_prompt or "",
            "```",
            "",
            "Negative:",
            "```",
            s.image_negative or "",
            "```",
            "",
            "### 2. Промт для анимации (image-to-video)",
            "",
            "```",
            s.animation_prompt or "",
            "```",
            "",
            "Negative:",
            "```",
            s.animation_negative or "",
            "```",
            "",
        ]
        if s.dialogue:
            lines += ["### 3. Реплики", ""]
            for d in s.dialogue:
                emo = f" _({d.emotion})_" if d.emotion else ""
                lines.append(f"- **{d.speaker}**{emo}: {d.text}")
            lines.append("")
        lines += ["---", ""]
    return "\n".join(lines)


def render_scene_brief(scene, total: int) -> str:
    """Короткий блок для одной сцены — отправляется в чат как сообщение."""
    parts = [
        f"🎬 Сцена {scene.number}/{total}: {scene.summary}",
        f"⏱ {scene.duration_sec}с | {scene.aspect_ratio} | {scene.mood}",
        "",
        "🖼 Картинка:",
        f"```\n{scene.image_prompt or ''}\n```",
    ]
    if scene.image_negative:
        parts.append(f"_neg:_ `{scene.image_negative}`")
    parts += [
        "",
        "🎞 Анимация:",
        f"```\n{scene.animation_prompt or ''}\n```",
    ]
    if scene.animation_negative:
        parts.append(f"_neg:_ `{scene.animation_negative}`")
    if scene.dialogue:
        parts += ["", "💬 Реплики:"]
        for d in scene.dialogue:
            emo = f" ({d.emotion})" if d.emotion else ""
            parts.append(f"• *{d.speaker}*{emo}: {d.text}")
    return "\n".join(parts)
