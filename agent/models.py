from dataclasses import dataclass, field, asdict
from typing import List, Optional


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
    prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    duration_sec: int = 6
    aspect_ratio: str = "16:9"

    def to_dict(self):
        return asdict(self)


@dataclass
class VideoProject:
    title: str
    idea: str
    style: str
    character_anchor: str
    scenes: List[Scene] = field(default_factory=list)

    def to_dict(self):
        return {
            "title": self.title,
            "idea": self.idea,
            "style": self.style,
            "character_anchor": self.character_anchor,
            "scenes": [s.to_dict() for s in self.scenes],
        }
