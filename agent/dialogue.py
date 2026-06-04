"""
Перегенерация и парсинг реплик для одной сцены в manual-режиме.
"""
from pathlib import Path
from typing import List
from .llm import ask_json_async
from .models import DialogueLine, Scene, VideoProject

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


async def regenerate_scene_dialogue(
    project: VideoProject, scene: Scene
) -> List[DialogueLine]:
    """Просит Claude написать новые реплики для одной сцены."""
    system = (PROMPTS_DIR / "system_redialogue.md").read_text(encoding="utf-8")
    user = (
        f"Идея ролика: {project.idea}\n"
        f"Стиль: {project.style}\n"
        f"Главный герой (character_anchor): {project.character_anchor}\n"
        f"language: {project.language}\n"
        f"Длительность сцены: {scene.duration_sec} сек\n"
        f"---\n"
        f"Сцена #{scene.number}: {scene.summary}\n"
        f"Subject: {scene.subject}\n"
        f"Action: {scene.action}\n"
        f"Setting: {scene.setting}\n"
        f"Mood: {scene.mood}\n"
    )
    data = await ask_json_async(system, user)
    return [
        DialogueLine(
            speaker=d.get("speaker", ""),
            text=d.get("text", ""),
            emotion=d.get("emotion", ""),
        )
        for d in data.get("dialogue", [])
    ]


def parse_user_dialogue(text: str) -> List[DialogueLine]:
    """
    Парсит ввод пользователя в формате:
        Имя: реплика
        Имя (эмоция): реплика
        Имя | эмоция | реплика
    По одной строке на реплику. Пустые игнорируются.
    """
    lines: List[DialogueLine] = []
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        speaker, emotion, body = "", "", s
        if ":" in s:
            head, body = s.split(":", 1)
            head = head.strip()
            body = body.strip()
            if "(" in head and head.endswith(")"):
                speaker, em = head.split("(", 1)
                speaker = speaker.strip()
                emotion = em[:-1].strip()
            else:
                speaker = head
        lines.append(
            DialogueLine(speaker=speaker or "Speaker", text=body, emotion=emotion)
        )
    return lines


def format_dialogue_block(scene: Scene) -> str:
    """Короткий читаемый блок реплик одной сцены — для показа в чате."""
    if not scene.dialogue:
        return "_(реплик нет)_"
    parts = []
    for d in scene.dialogue:
        emo = f" ({d.emotion})" if d.emotion else ""
        parts.append(f"• *{d.speaker}*{emo}: {d.text}")
    return "\n".join(parts)
