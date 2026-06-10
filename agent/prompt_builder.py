import asyncio
import json
import logging
import os
from pathlib import Path
from .llm import ask_json, ask_json_async
from .models import VideoProject, Keyframe

_log = logging.getLogger("agent.prompt_builder")

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Сколько сцен обрабатывать параллельно. На слабых серверах (1 GB RAM)
# каждый claude CLI subprocess ест ~150 MB, поэтому 8 параллельных вызовов
# выбивают сервер в swap и SDK падает по таймауту. Дефолт 2 — компромисс
# между скоростью и стабильностью. На жирном сервере можно поднять через
# переменную окружения AGENT_BOT_CONCURRENCY.
_CONCURRENCY = max(1, int(os.environ.get("AGENT_BOT_CONCURRENCY", "2")))


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


def _resolve_keyframes_count(scene, project) -> int:
    """Сколько кадров делать для конкретной сцены."""
    mode = project.keyframes_mode
    if mode == "auto":
        return max(1, min(3, scene.suggested_keyframes))
    if mode in ("1", "2", "3"):
        return int(mode)
    return 1


def _image_user(scene, ctx, n: int) -> str:
    return f"{ctx}Number of keyframes to generate (N): {n}\n"


def _animation_user(scene, ctx, duration, aspect, project=None) -> str:
    kf_block = "Keyframes:\n" + "\n".join(
        f"  - [{k.label}] {k.prompt}" for k in scene.keyframes
    )
    lang_block = ""
    if project and project.language and project.language != "auto":
        lang_block = (
            f"Dialogue language: {project.language}. If the scene has dialogue, "
            f"mention native lip articulation for this language in the motion "
            f"prompt.\n"
        )
    return (
        f"{ctx}{kf_block}\n"
        f"{lang_block}"
        f"Target duration: {duration} sec\n"
        f"Aspect ratio: {aspect}\n"
    )


def _ingest_keyframes(scene, data: dict, n: int) -> bool:
    """Записывает кадры из ответа модели. Возвращает True если получено ровно n кадров."""
    raw = data.get("keyframes", [])
    keyframes = []
    for item in raw[:n]:
        keyframes.append(
            Keyframe(
                label=item.get("label", "only"),
                prompt=item.get("prompt", ""),
                negative=item.get("negative", ""),
            )
        )
    scene.keyframes = keyframes
    return len(keyframes) == n


def build_image_prompts(project: VideoProject) -> VideoProject:
    system = (PROMPTS_DIR / "system_image_prompt.md").read_text(encoding="utf-8")
    styles = _load_styles()
    style_pack = styles.get(project.style, styles["cinematic"])
    for scene in project.scenes:
        n = _resolve_keyframes_count(scene, project)
        ctx = _scene_context(scene, project, style_pack)
        user_msg = _image_user(scene, ctx, n)
        for attempt in range(3):
            data = ask_json(system, user_msg)
            got = len(data.get("keyframes", []))
            if _ingest_keyframes(scene, data, n):
                break
            if attempt < 2:
                _log.warning("Scene %d: got %d/%d keyframes, retrying (%d/3)",
                             scene.number, got, n, attempt + 2)
                user_msg = (
                    _image_user(scene, ctx, n) +
                    f"\nPREVIOUS ATTEMPT RETURNED {got} KEYFRAMES INSTEAD OF {n}. "
                    f"The 'keyframes' array MUST contain exactly {n} objects."
                )
        else:
            _log.error("Scene %d: could not get %d keyframes after 3 attempts", scene.number, n)
    return project


async def build_image_prompts_async(project: VideoProject) -> VideoProject:
    """Сцены параллельно, но с лимитом _CONCURRENCY."""
    system = (PROMPTS_DIR / "system_image_prompt.md").read_text(encoding="utf-8")
    styles = _load_styles()
    style_pack = styles.get(project.style, styles["cinematic"])
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(scene):
        async with sem:
            n = _resolve_keyframes_count(scene, project)
            ctx = _scene_context(scene, project, style_pack)
            user_msg = _image_user(scene, ctx, n)
            for attempt in range(3):
                data = await ask_json_async(system, user_msg)
                got = len(data.get("keyframes", []))
                if _ingest_keyframes(scene, data, n):
                    return
                if attempt < 2:
                    _log.warning("Scene %d: got %d/%d keyframes, retrying (%d/3)",
                                 scene.number, got, n, attempt + 2)
                    user_msg = (
                        _image_user(scene, ctx, n) +
                        f"\nPREVIOUS ATTEMPT RETURNED {got} KEYFRAMES INSTEAD OF {n}. "
                        f"The 'keyframes' array MUST contain exactly {n} objects."
                    )
            _log.error("Scene %d: could not get %d keyframes after 3 attempts", scene.number, n)

    results = await asyncio.gather(*(one(s) for s in project.scenes), return_exceptions=True)
    for scene, result in zip(project.scenes, results):
        if isinstance(result, Exception):
            _log.error("Scene %d image prompts failed: %s", scene.number, result)
    return project


def build_animation_prompts(
    project: VideoProject, duration: int, aspect: str
) -> VideoProject:
    system = (PROMPTS_DIR / "system_animation_prompt.md").read_text(encoding="utf-8")
    styles = _load_styles()
    style_pack = styles.get(project.style, styles["cinematic"])
    for scene in project.scenes:
        ctx = _scene_context(scene, project, style_pack)
        user = _animation_user(scene, ctx, duration, aspect, project)
        data = ask_json(system, user)
        scene.animation_prompt = data["animation_prompt"]
        scene.animation_negative = data.get("animation_negative", "")
        scene.duration_sec = duration
        scene.aspect_ratio = aspect
    return project


async def build_animation_prompts_async(
    project: VideoProject, duration: int, aspect: str
) -> VideoProject:
    """Сцены параллельно с лимитом _CONCURRENCY."""
    system = (PROMPTS_DIR / "system_animation_prompt.md").read_text(encoding="utf-8")
    styles = _load_styles()
    style_pack = styles.get(project.style, styles["cinematic"])
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(scene):
        async with sem:
            ctx = _scene_context(scene, project, style_pack)
            user = _animation_user(scene, ctx, duration, aspect, project)
            data = await ask_json_async(system, user)
            scene.animation_prompt = data["animation_prompt"]
            scene.animation_negative = data.get("animation_negative", "")
            scene.duration_sec = duration
            scene.aspect_ratio = aspect

    results = await asyncio.gather(*(one(s) for s in project.scenes), return_exceptions=True)
    for scene, result in zip(project.scenes, results):
        if isinstance(result, Exception):
            _log.error("Scene %d animation prompts failed: %s", scene.number, result)
    return project
