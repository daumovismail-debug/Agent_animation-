from pathlib import Path
from .claude_client import ask_json
from .models import Scene, VideoProject

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def generate_script(idea: str, style: str, scenes_count: int) -> VideoProject:
    system = (PROMPTS_DIR / "system_script.md").read_text(encoding="utf-8")
    user = (
        f"Идея: {idea}\n"
        f"Стиль: {style}\n"
        f"Количество сцен: {scenes_count}\n"
    )
    data = ask_json(system, user, max_tokens=2500)

    scenes = [
        Scene(
            number=s["number"],
            summary=s["summary"],
            subject=s["subject"],
            action=s["action"],
            camera=s["camera"],
            setting=s["setting"],
            lighting=s["lighting"],
            mood=s["mood"],
        )
        for s in data["scenes"]
    ]
    return VideoProject(
        title=data["title"],
        idea=idea,
        style=style,
        character_anchor=data["character_anchor"],
        scenes=scenes,
    )
