from pathlib import Path
from .llm import ask_json, ask_json_async
from .models import Scene, VideoProject, DialogueLine

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _script_user(idea, style, scenes_count, is_dialogue_heavy, clarifications,
                 keyframes_mode):
    clar_block = (
        "\n".join(f"- {k}: {v}" for k, v in clarifications.items())
        if clarifications
        else "(нет дополнительных уточнений)"
    )
    if keyframes_mode == "auto":
        kf_note = "Сам реши suggested_keyframes (1, 2 или 3) для каждой сцены."
    else:
        kf_note = (
            f"Пользователь зафиксировал suggested_keyframes = "
            f"{keyframes_mode} для ВСЕХ сцен — используй именно это число."
        )
    return (
        f"Идея: {idea}\n"
        f"Стиль: {style}\n"
        f"Количество сцен: {scenes_count}\n"
        f"is_dialogue_heavy: {str(is_dialogue_heavy).lower()}\n"
        f"Режим ключевых кадров: {kf_note}\n"
        f"Уточнения от пользователя:\n{clar_block}\n"
    )


def _build_project(data, idea, style, is_dialogue_heavy, clarifications,
                   keyframes_mode):
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
        sk = int(s.get("suggested_keyframes", 1) or 1)
        sk = max(1, min(3, sk))
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
                suggested_keyframes=sk,
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
        keyframes_mode=keyframes_mode,
        scenes=scenes,
        clarifications=clarifications,
    )


def generate_script(
    idea: str,
    style: str,
    scenes_count: int,
    is_dialogue_heavy: bool,
    clarifications: dict,
    keyframes_mode: str = "auto",
) -> VideoProject:
    system = (PROMPTS_DIR / "system_script.md").read_text(encoding="utf-8")
    user = _script_user(idea, style, scenes_count, is_dialogue_heavy,
                        clarifications, keyframes_mode)
    data = ask_json(system, user)
    return _build_project(data, idea, style, is_dialogue_heavy, clarifications,
                          keyframes_mode)


async def generate_script_async(
    idea: str,
    style: str,
    scenes_count: int,
    is_dialogue_heavy: bool,
    clarifications: dict,
    keyframes_mode: str = "auto",
) -> VideoProject:
    system = (PROMPTS_DIR / "system_script.md").read_text(encoding="utf-8")
    user = _script_user(idea, style, scenes_count, is_dialogue_heavy,
                        clarifications, keyframes_mode)
    data = await ask_json_async(system, user)
    return _build_project(data, idea, style, is_dialogue_heavy, clarifications,
                          keyframes_mode)
