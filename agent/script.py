from pathlib import Path
from .llm import ask_json
from .models import Scene, VideoProject, DialogueLine

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def generate_script(
    idea: str,
    style: str,
    scenes_count: int,
    is_dialogue_heavy: bool,
    clarifications: dict,
) -> VideoProject:
    system = (PROMPTS_DIR / "system_script.md").read_text(encoding="utf-8")

    clar_block = (
        "\n".join(f"- {k}: {v}" for k, v in clarifications.items())
        if clarifications
        else "(нет дополнительных уточнений)"
    )

    user = (
        f"Идея: {idea}\n"
        f"Стиль: {style}\n"
        f"Количество сцен: {scenes_count}\n"
        f"is_dialogue_heavy: {str(is_dialogue_heavy).lower()}\n"
        f"Уточнения от пользователя:\n{clar_block}\n"
    )
    data = ask_json(system, user)

    scenes = []
    for s in data["scenes"]:
        dlg = [
            DialogueLine(
                speaker=d.get("speaker", ""),
                text=d.get("text", ""),
                emotion=d.get("emotion", ""),
            )
            for d in s.get("dialogue", [])
        ]
        scenes.append(
            Scene(
                number=s["number"],
                summary=s["summary"],
                subject=s["subject"],
                action=s["action"],
                camera=s["camera"],
                setting=s["setting"],
                lighting=s["lighting"],
                mood=s["mood"],
                dialogue=dlg,
            )
        )

    return VideoProject(
        title=data["title"],
        idea=idea,
        style=style,
        character_anchor=data["character_anchor"],
        is_dialogue_heavy=is_dialogue_heavy,
        voice_notes=data.get("voice_notes", ""),
        scenes=scenes,
        clarifications=clarifications,
    )
