import json
from pathlib import Path
from .claude_client import ask_json
from .models import Scene, VideoProject

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_styles() -> dict:
    return json.loads((PROMPTS_DIR / "styles.json").read_text(encoding="utf-8"))


def build_prompts(project: VideoProject, duration: int, aspect: str) -> VideoProject:
    system = (PROMPTS_DIR / "system_prompter.md").read_text(encoding="utf-8")
    styles = _load_styles()
    style_pack = styles.get(project.style, styles["cinematic"])

    for scene in project.scenes:
        user = (
            f"Character anchor (use verbatim): {project.character_anchor}\n"
            f"Scene #{scene.number}: {scene.summary}\n"
            f"Subject: {scene.subject}\n"
            f"Action: {scene.action}\n"
            f"Camera: {scene.camera}\n"
            f"Setting: {scene.setting}\n"
            f"Lighting: {scene.lighting}\n"
            f"Mood: {scene.mood}\n"
            f"Style look: {style_pack['look']}\n"
            f"Style lighting: {style_pack['lighting']}\n"
            f"Style color: {style_pack['color']}\n"
            f"Target duration: {duration} sec\n"
            f"Aspect ratio: {aspect}\n"
        )
        data = ask_json(system, user, max_tokens=800)
        scene.prompt = data["prompt"]
        scene.negative_prompt = data.get("negative_prompt", "")
        scene.duration_sec = int(data.get("duration_sec", duration))
        scene.aspect_ratio = data.get("aspect_ratio", aspect)

    return project
