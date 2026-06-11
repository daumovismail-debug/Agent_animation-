"""
Оценка тайминга диалогов и рекомендации по длительности сцен.

Логика:
  - estimated_sec = word_count / WORDS_PER_SEC
  - ok   : estimated_sec <= default_duration  → ничего не делаем
  - long : default_duration < estimated_sec <= CLIP_MAX_SEC
           → предложить увеличить сцену до ceil(estimated_sec)
  - split: estimated_sec > CLIP_MAX_SEC
           → предложить разбить на N клипов с одним и тем же ключевым кадром
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

WORDS_PER_SEC: float = 2.2   # ~130 слов/мин, консервативно для русского
CLIP_MAX_SEC: int = 10        # максимум на один клип


@dataclass
class TimingAdvice:
    scene_number: int
    scene_summary: str
    word_count: int
    estimated_sec: float
    status: str           # "long" | "split"
    recommended_duration: int
    split_count: int      # 1 для "long", ≥2 для "split"


def _count_words(dialogue_lines) -> int:
    return sum(len(d.text.split()) for d in dialogue_lines)


def estimate_speech_sec(dialogue_lines) -> float:
    return _count_words(dialogue_lines) / WORDS_PER_SEC


def advise_scene(scene, default_duration: int) -> Optional[TimingAdvice]:
    """Вернуть TimingAdvice если реплики сцены не укладываются в default_duration."""
    if not scene.dialogue:
        return None
    words = _count_words(scene.dialogue)
    estimated = words / WORDS_PER_SEC
    if estimated <= default_duration:
        return None
    if estimated <= CLIP_MAX_SEC:
        recommended = min(CLIP_MAX_SEC, math.ceil(estimated))
        return TimingAdvice(
            scene_number=scene.number,
            scene_summary=scene.summary,
            word_count=words,
            estimated_sec=round(estimated, 1),
            status="long",
            recommended_duration=recommended,
            split_count=1,
        )
    # Слишком длинная — нужно разбивать на клипы
    split_count = math.ceil(estimated / CLIP_MAX_SEC)
    per_clip = math.ceil(estimated / split_count)
    return TimingAdvice(
        scene_number=scene.number,
        scene_summary=scene.summary,
        word_count=words,
        estimated_sec=round(estimated, 1),
        status="split",
        recommended_duration=per_clip,
        split_count=split_count,
    )


def advise_project(project, default_duration: int) -> List[TimingAdvice]:
    """Советы по всем сценам с диалогом; пустой список = всё ок."""
    return [
        a for s in project.scenes
        if (a := advise_scene(s, default_duration)) is not None
    ]
