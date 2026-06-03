from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class DialogueLine:
    speaker: str
    text: str
    emotion: str = ""

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
    image_prompt: Optional[str] = None
    image_negative: Optional[str] = None
    animation_prompt: Optional[str] = None
    animation_negative: Optional[str] = None
    dialogue: List[DialogueLine] = field(default_factory=list)
    duration_sec: int = 6
    aspect_ratio: str = "16:9"

    def to_dict(self):
        d = asdict(self)
        return d


@dataclass
class VideoProject:
    title: str
    idea: str
    style: str
    character_anchor: str
    is_dialogue_heavy: bool = False
    voice_notes: str = ""
    scenes: List[Scene] = field(default_factory=list)
    clarifications: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "title": self.title,
            "idea": self.idea,
            "style": self.style,
            "character_anchor": self.character_anchor,
            "is_dialogue_heavy": self.is_dialogue_heavy,
            "voice_notes": self.voice_notes,
            "clarifications": self.clarifications,
            "scenes": [s.to_dict() for s in self.scenes],
        }
