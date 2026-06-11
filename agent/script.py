from pathlib import Path
from .llm import ask_json, ask_json_async
from .models import Scene, VideoProject, DialogueLine

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _script_user(idea, style, scenes_count, is_dialogue_heavy, clarifications,
                 keyframes_mode, language, dialogue_mode):
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
        f"language: {language}\n"
        f"dialogue_mode: {dialogue_mode}\n"
        f"Режим ключевых кадров: {kf_note}\n"
        f"Уточнения от пользователя:\n{clar_block}\n"
    )


def _build_project(data, idea, style, is_dialogue_heavy, clarifications,
                   keyframes_mode, language, dialogue_mode):
    scenes = []
    for s in data["scenes"]:
        raw_dlg = s.get("dialogue", []) if dialogue_mode != "off" else []
        dlg = [
            DialogueLine(
                speaker=d.get("speaker", ""),
                text=d.get("text", ""),
                emotion=d.get("emotion", ""),
            )
            for d in raw_dlg
        ]
        sk = int(s.get("suggested_keyframes", 1) or 1)
        sk = max(1, min(3, sk))
        raw_role = s.get("dramatic_role", "").strip().lower()
        if raw_role not in ("hook", "development", "cliffhanger"):
            raw_role = ""
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
                dramatic_role=raw_role,
                suggested_keyframes=sk,
                dialogue=dlg,
            )
        )
    return VideoProject(
        title=data["title"],
        idea=idea,
        style=style,
        character_anchor=data["character_anchor"],
        is_dialogue_heavy=is_dialogue_heavy if dialogue_mode != "off" else False,
        voice_notes=data.get("voice_notes", "") if dialogue_mode != "off" else "",
        keyframes_mode=keyframes_mode,
        language=language,
        dialogue_mode=dialogue_mode,
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
    language: str = "auto",
    dialogue_mode: str = "auto",
) -> VideoProject:
    system = (PROMPTS_DIR / "system_script.md").read_text(encoding="utf-8")
    user = _script_user(idea, style, scenes_count, is_dialogue_heavy,
                        clarifications, keyframes_mode, language, dialogue_mode)
    data = ask_json(system, user)
    return _build_project(data, idea, style, is_dialogue_heavy, clarifications,
                          keyframes_mode, language, dialogue_mode)


async def generate_script_async(
    idea: str,
    style: str,
    scenes_count: int,
    is_dialogue_heavy: bool,
    clarifications: dict,
    keyframes_mode: str = "auto",
    language: str = "auto",
    dialogue_mode: str = "auto",
) -> VideoProject:
    system = (PROMPTS_DIR / "system_script.md").read_text(encoding="utf-8")
    user = _script_user(idea, style, scenes_count, is_dialogue_heavy,
                        clarifications, keyframes_mode, language, dialogue_mode)
    data = await ask_json_async(system, user)
    return _build_project(data, idea, style, is_dialogue_heavy, clarifications,
                          keyframes_mode, language, dialogue_mode)
