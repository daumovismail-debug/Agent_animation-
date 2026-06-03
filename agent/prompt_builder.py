import json
from pathlib import Path
from .llm import ask_json, ask_json_async
from .models import VideoProject

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_styles() -> dict:
    return json.loads((PROMPTS_DIR / "styles.json").read_text(encoding="utf-8"))


def _scene_context(scene, project, style_pack) -> str:
    dlg_block = ""
    if scene.dialogue:
        lines = [
            f"  - {d.speaker} ({d.emotion}): {d.text}" for d in scene.dialogue
        ]
        dlg_block = "Dialogue in this scene:\n" + "\n".join(lines) + "\n"
    return (
        f"Character anchor (use verbatim in prompt): {project.character_anchor}\n"
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
        f"{dlg_block}"
    )


def _animation_user(scene, ctx, duration, aspect):
    return (
        f"{ctx}"
        f"Existing image keyframe prompt: {scene.image_prompt}\n"
        f"Target duration: {duration} sec\n"
        f"Aspect ratio: {aspect}\n"
    )


def build_image_prompts(project: VideoProject) -> VideoProject:
    system = (PROMPTS_DIR / "system_image_prompt.md").read_text(encoding="utf-8")
    styles = _load_styles()
    style_pack = styles.get(project.style, styles["cinematic"])
    for scene in project.scenes:
        user = _scene_context(scene, project, style_pack)
        data = ask_json(system, user)
        scene.image_prompt = data["image_prompt"]
        scene.image_negative = data.get("image_negative", "")
    return project


async def build_image_prompts_async(project: VideoProject) -> VideoProject:
    system = (PROMPTS_DIR / "system_image_prompt.md").read_text(encoding="utf-8")
    styles = _load_styles()
    style_pack = styles.get(project.style, styles["cinematic"])
    for scene in project.scenes:
        user = _scene_context(scene, project, style_pack)
        data = await ask_json_async(system, user)
        scene.image_prompt = data["image_prompt"]
        scene.image_negative = data.get("image_negative", "")
    return project


def build_animation_prompts(
    project: VideoProject, duration: int, aspect: str
) -> VideoProject:
    system = (PROMPTS_DIR / "system_animation_prompt.md").read_text(encoding="utf-8")
    styles = _load_styles()
    style_pack = styles.get(project.style, styles["cinematic"])
    for scene in project.scenes:
        ctx = _scene_context(scene, project, style_pack)
        user = _animation_user(scene, ctx, duration, aspect)
        data = ask_json(system, user)
        scene.animation_prompt = data["animation_prompt"]
        scene.animation_negative = data.get("animation_negative", "")
        scene.duration_sec = int(data.get("duration_sec", duration))
        scene.aspect_ratio = data.get("aspect_ratio", aspect)
    return project


async def build_animation_prompts_async(
    project: VideoProject, duration: int, aspect: str
) -> VideoProject:
    system = (PROMPTS_DIR / "system_animation_prompt.md").read_text(encoding="utf-8")
    styles = _load_styles()
    style_pack = styles.get(project.style, styles["cinematic"])
    for scene in project.scenes:
        ctx = _scene_context(scene, project, style_pack)
        user = _animation_user(scene, ctx, duration, aspect)
        data = await ask_json_async(system, user)
        scene.animation_prompt = data["animation_prompt"]
        scene.animation_negative = data.get("animation_negative", "")
        scene.duration_sec = int(data.get("duration_sec", duration))
        scene.aspect_ratio = data.get("aspect_ratio", aspect)
    return project
