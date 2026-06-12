"""
Управление состоянием сессии.

Шаги:
  naming          → юзер вводит название сессии
  char_count      → сколько персонажей
  char_build      → пошаговый сбор персонажей (field by field)
  chars_confirm   → подтверждение всех персонажей
  idea            → юзер описывает идею мультфильма
  scene_count     → сколько сцен
  total_duration  → общая длительность в секундах
  duration_split  → длительность каждой сцены
  keyframes       → сколько кадров на сцену
  aspect          → формат видео
  generating_script → генерация сценария
  script_review   → показываем сценарий, ждём правок
  summary_review  → показываем сводку, ждём подтверждения
  generating_prompts → генерация промтов
  prompt_review   → показываем промты, ждём правок
  done            → завершено
"""
import json
from dataclasses import dataclass, field
from typing import Optional

from .models import VideoProject, Character, UserPreference, Scene, Keyframe, DialogueLine
from .character_builder import QUESTIONS as CHAR_QUESTIONS


@dataclass
class SessionState:
    stage: str = "naming"
    project: Optional[VideoProject] = None
    char_total: int = 0
    char_index: int = 0
    char_field_index: int = 0
    char_current_data: dict = field(default_factory=dict)
    scenes_count: int = 4
    awaiting_input: bool = False
    pending_warning: Optional[tuple] = None
    busy: bool = False


SESSIONS: dict[str, SessionState] = {}


def get_session(session_id: str) -> SessionState:
    if session_id not in SESSIONS:
        SESSIONS[session_id] = SessionState()
    return SESSIONS[session_id]


def reset_session(session_id: str):
    SESSIONS.pop(session_id, None)


def current_char_question(state: SessionState) -> tuple[str, str] | None:
    if state.char_field_index < len(CHAR_QUESTIONS):
        return CHAR_QUESTIONS[state.char_field_index]
    return None


def finish_current_character(state: SessionState):
    data = state.char_current_data
    char = Character(
        name=data.get("name", "Персонаж"),
        age=data.get("age", ""),
        appearance=data.get("appearance", ""),
        clothing=data.get("clothing", ""),
        personality=data.get("personality", ""),
        speech_style=data.get("speech_style", ""),
        special_features=data.get("special_features", "нет"),
    )
    state.project.characters.append(char)
    state.project.character_anchor = state.project.build_character_anchor()
    state.char_index += 1
    state.char_field_index = 0
    state.char_current_data = {}


def all_chars_done(state: SessionState) -> bool:
    return state.char_index >= state.char_total


def add_preference(state: SessionState, description: str):
    key = f"pref_{len(state.project.user_preferences)}"
    pref = UserPreference(key=key, description=description)
    state.project.user_preferences.append(pref)


def serialize_state(st: SessionState) -> str:
    """Сериализует состояние сессии в JSON для хранения в БД."""
    project_dict = st.project.to_dict() if st.project else None
    return json.dumps(
        {
            "stage": st.stage,
            "project": project_dict,
            "char_total": st.char_total,
            "char_index": st.char_index,
            "char_field_index": st.char_field_index,
            "char_current_data": st.char_current_data,
            "scenes_count": st.scenes_count,
            "pending_script_edit": getattr(st, "_pending_script_edit", ""),
            "recommended_durations": getattr(st, "_recommended_durations", []),
        },
        ensure_ascii=False,
    )


def restore_state(session_id: str, state_json: str) -> SessionState:
    """Восстанавливает SessionState из JSON (при рестарте сервера)."""
    try:
        data = json.loads(state_json)
    except Exception:
        return SessionState()

    st = SessionState()
    st.stage = data.get("stage", "naming")
    st.char_total = data.get("char_total", 0)
    st.char_index = data.get("char_index", 0)
    st.char_field_index = data.get("char_field_index", 0)
    st.char_current_data = data.get("char_current_data", {})
    st.scenes_count = data.get("scenes_count", 4)
    st._pending_script_edit = data.get("pending_script_edit", "")
    st._recommended_durations = data.get("recommended_durations", [])

    proj_data = data.get("project")
    if proj_data:
        try:
            st.project = _restore_project(proj_data)
        except Exception:
            st.project = None

    SESSIONS[session_id] = st
    return st


def _restore_project(d: dict) -> VideoProject:
    chars = [
        Character(
            name=c.get("name", ""),
            age=c.get("age", ""),
            appearance=c.get("appearance", ""),
            clothing=c.get("clothing", ""),
            personality=c.get("personality", ""),
            speech_style=c.get("speech_style", ""),
            special_features=c.get("special_features", ""),
        )
        for c in d.get("characters", [])
    ]

    prefs = [
        UserPreference(key=p.get("key", ""), description=p.get("description", ""))
        for p in d.get("user_preferences", [])
    ]

    scenes = []
    for s in d.get("scenes", []):
        keyframes = [
            Keyframe(
                label=k.get("label", "only"),
                prompt=k.get("prompt", ""),
                negative=k.get("negative", ""),
            )
            for k in s.get("keyframes", [])
        ]
        dialogue = [
            DialogueLine(
                speaker=dl.get("speaker", ""),
                text=dl.get("text", ""),
                emotion=dl.get("emotion", ""),
            )
            for dl in s.get("dialogue", [])
        ]
        scenes.append(
            Scene(
                number=s.get("number", 1),
                summary=s.get("summary", ""),
                subject=s.get("subject", ""),
                action=s.get("action", ""),
                camera=s.get("camera", ""),
                setting=s.get("setting", ""),
                lighting=s.get("lighting", ""),
                mood=s.get("mood", ""),
                suggested_keyframes=s.get("suggested_keyframes", 1),
                keyframes=keyframes,
                animation_prompt=s.get("animation_prompt"),
                animation_negative=s.get("animation_negative"),
                dialogue=dialogue,
                duration_sec=s.get("duration_sec", 6),
                aspect_ratio=s.get("aspect_ratio", "9:16"),
            )
        )

    proj = VideoProject(
        session_name=d.get("session_name", ""),
        title=d.get("title", ""),
        idea=d.get("idea", ""),
        aspect_ratio=d.get("aspect_ratio", "9:16"),
        style=d.get("style", "pixar"),
        characters=chars,
        character_anchor=d.get("character_anchor", ""),
        total_duration_sec=d.get("total_duration_sec", 60),
        is_dialogue_heavy=d.get("is_dialogue_heavy", False),
        voice_notes=d.get("voice_notes", ""),
        keyframes_mode=d.get("keyframes_mode", "1"),
        scenes=scenes,
        clarifications=d.get("clarifications", {}),
        user_preferences=prefs,
    )
    return proj
