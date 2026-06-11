from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Character:
    name: str
    age: str = ""
    appearance: str = ""
    clothing: str = ""
    personality: str = ""
    speech_style: str = ""
    special_features: str = ""

    def anchor(self) -> str:
        parts = [self.name]
        if self.age:
            parts.append(self.age + " лет")
        if self.appearance:
            parts.append(self.appearance)
        if self.clothing:
            parts.append(self.clothing)
        if self.special_features and self.special_features.lower() not in ("нет", "no", "none", "-"):
            parts.append(self.special_features)
        return ", ".join(parts)

    def to_dict(self):
        return asdict(self)


@dataclass
class UserPreference:
    key: str
    description: str

    def to_dict(self):
        return asdict(self)


@dataclass
class DialogueLine:
    speaker: str
    text: str
    emotion: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class Keyframe:
    """Один ключевой кадр сцены — промт для генератора картинок."""
    label: str       # "only" | "start" | "middle" | "end"
    prompt: str
    negative: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class Scene:
    number: int
    summary: str
    subject: str
    action: str
    camera: str
    setting: str
    lighting: str
    mood: str
    # "hook" | "development" | "cliffhanger"
    dramatic_role: str = ""
    # Claude-рекомендация сколько кадров надо именно этой сцене (1..3)
    suggested_keyframes: int = 1
    # Сгенерированные кадры (1, 2 или 3 штуки)
    keyframes: List[Keyframe] = field(default_factory=list)
    # Промт для image-to-video — оживить кадр(ы)
    animation_prompt: Optional[str] = None
    animation_negative: Optional[str] = None
    dialogue: List[DialogueLine] = field(default_factory=list)
    duration_sec: int = 6
    aspect_ratio: str = "16:9"
    timing_note: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class VideoProject:
    title: str
    idea: str
    style: str
    character_anchor: str
    is_dialogue_heavy: bool = False
    voice_notes: str = ""
    # "auto" | "1" | "2" | "3" — настройка пользователя
    keyframes_mode: str = "auto"
    # "auto" | "ru" | "en" | "kk" — язык реплик
    language: str = "auto"
    # "auto" — Claude сам пишет реплики в сценарии
    # "manual" — пользователь сам выбирает per-scene (Claude / ввод / пропуск)
    # "off" — никаких реплик
    dialogue_mode: str = "auto"
    scenes: List[Scene] = field(default_factory=list)
    clarifications: dict = field(default_factory=dict)
    characters: List[Character] = field(default_factory=list)
    user_preferences: List[UserPreference] = field(default_factory=list)
    session_name: str = ""
    aspect_ratio: str = "16:9"
    total_duration_sec: int = 0

    def to_dict(self):
        return {
            "title": self.title,
            "idea": self.idea,
            "style": self.style,
            "character_anchor": self.character_anchor,
            "is_dialogue_heavy": self.is_dialogue_heavy,
            "voice_notes": self.voice_notes,
            "keyframes_mode": self.keyframes_mode,
            "language": self.language,
            "dialogue_mode": self.dialogue_mode,
            "clarifications": self.clarifications,
            "scenes": [s.to_dict() for s in self.scenes],
            "characters": [c.to_dict() for c in self.characters],
        }
