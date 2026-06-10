"""
Базовые тесты агента — не требуют API ключа и сетевых вызовов.
Проверяют: парсинг JSON, модели, формирование промтов, кадры.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from agent.models import VideoProject, Scene, Keyframe
from agent.llm import _parse_json, _strip_fences
from agent.prompt_builder import _ingest_keyframes, _resolve_keyframes_count, _scene_context

STYLE_PACK = {
    "look": "Pixar 3D, stylized",
    "lighting": "three-point lighting",
    "color": "saturated palette",
}


# ─────────────────── JSON парсинг ────────────────────────────────────────────

def test_parse_json_clean():
    assert _parse_json('{"key": "value"}') == {"key": "value"}


def test_parse_json_with_fences():
    assert _parse_json('```json\n{"key": "value"}\n```') == {"key": "value"}


def test_parse_json_with_preamble():
    data = _parse_json('Here is the result:\n{"key": "value"}\nDone.')
    assert data == {"key": "value"}


def test_parse_json_nested():
    raw = '{"scenes": [{"number": 1, "summary": "test"}]}'
    data = _parse_json(raw)
    assert data["scenes"][0]["number"] == 1


def test_parse_json_invalid_raises():
    with pytest.raises(Exception):
        _parse_json("not json at all, no braces here")


def test_strip_fences_plain():
    assert _strip_fences("hello") == "hello"


def test_strip_fences_removes_backticks():
    assert _strip_fences("```json\n{}\n```") == "{}"


# ─────────────────── Модели ──────────────────────────────────────────────────

def _make_project_and_scene():
    project = VideoProject(
        title="Тест",
        idea="Про люстры",
        style="3d",
        character_anchor="Люстра Светлана, золотая хрустальная, 12 свечей | Люстра Борис, бронзовый, 6 лампочек",
        keyframes_mode="2",
    )
    scene = Scene(
        number=1, summary="Люстры качаются", subject="Люстра Светлана и Борис",
        action="качаются синхронно", camera="wide shot", setting="большой зал",
        lighting="тёплый свет", mood="уютно",
        suggested_keyframes=2, duration_sec=6, aspect_ratio="16:9",
    )
    project.scenes = [scene]
    return project, scene


def test_video_project_to_dict():
    project, _ = _make_project_and_scene()
    d = project.to_dict()
    assert d["title"] == "Тест"
    assert d["character_anchor"] == project.character_anchor
    assert "scenes" in d


def test_scene_to_dict():
    _, scene = _make_project_and_scene()
    d = scene.to_dict()
    assert d["number"] == 1
    assert d["mood"] == "уютно"


# ─────────────────── Промт-билдер ────────────────────────────────────────────

def test_scene_context_has_anchor():
    project, scene = _make_project_and_scene()
    ctx = _scene_context(scene, project, STYLE_PACK)
    assert "Люстра Светлана" in ctx
    assert "Люстра Борис" in ctx


def test_scene_context_has_style():
    project, scene = _make_project_and_scene()
    ctx = _scene_context(scene, project, STYLE_PACK)
    assert "Pixar" in ctx


def test_scene_context_has_scene_fields():
    project, scene = _make_project_and_scene()
    ctx = _scene_context(scene, project, STYLE_PACK)
    assert "качаются синхронно" in ctx
    assert "большой зал" in ctx


def test_resolve_keyframes_fixed_mode():
    project = VideoProject(title="T", idea="i", style="3d",
                           character_anchor="x", keyframes_mode="2")
    scene = Scene(number=1, summary="", subject="", action="", camera="",
                  setting="", lighting="", mood="", suggested_keyframes=3)
    assert _resolve_keyframes_count(scene, project) == 2


def test_resolve_keyframes_auto_mode():
    project = VideoProject(title="T", idea="i", style="3d",
                           character_anchor="x", keyframes_mode="auto")
    scene = Scene(number=1, summary="", subject="", action="", camera="",
                  setting="", lighting="", mood="", suggested_keyframes=3)
    assert _resolve_keyframes_count(scene, project) == 3


def test_resolve_keyframes_auto_clamp():
    project = VideoProject(title="T", idea="i", style="3d",
                           character_anchor="x", keyframes_mode="auto")
    scene = Scene(number=1, summary="", subject="", action="", camera="",
                  setting="", lighting="", mood="", suggested_keyframes=5)
    assert _resolve_keyframes_count(scene, project) == 3  # max=3


# ─────────────────── Кадры: no duplication ───────────────────────────────────

def test_ingest_keyframes_exact_count():
    _, scene = _make_project_and_scene()
    data = {"keyframes": [
        {"label": "start", "prompt": "scene start", "negative": ""},
        {"label": "end",   "prompt": "scene end",   "negative": ""},
    ]}
    ok = _ingest_keyframes(scene, data, 2)
    assert ok is True
    assert len(scene.keyframes) == 2
    assert scene.keyframes[0].label == "start"
    assert scene.keyframes[1].label == "end"


def test_ingest_keyframes_too_few_returns_false():
    _, scene = _make_project_and_scene()
    data = {"keyframes": [
        {"label": "start", "prompt": "only one", "negative": ""},
    ]}
    ok = _ingest_keyframes(scene, data, 2)
    assert ok is False
    assert len(scene.keyframes) == 1  # NO duplication — только что есть


def test_ingest_keyframes_start_end_distinct():
    """start и end НЕ должны быть одинаковыми (старый баг с дублированием)."""
    _, scene = _make_project_and_scene()
    data = {"keyframes": [
        {"label": "start", "prompt": "frame one", "negative": ""},
    ]}
    _ingest_keyframes(scene, data, 2)
    # При старом коде было бы 2 одинаковых кадра. Теперь — 1.
    assert len(scene.keyframes) == 1


def test_ingest_keyframes_one_of_one():
    _, scene = _make_project_and_scene()
    data = {"keyframes": [
        {"label": "only", "prompt": "single keyframe", "negative": "no text"},
    ]}
    ok = _ingest_keyframes(scene, data, 1)
    assert ok is True
    assert scene.keyframes[0].label == "only"
    assert scene.keyframes[0].negative == "no text"


def test_ingest_keyframes_empty_data():
    _, scene = _make_project_and_scene()
    ok = _ingest_keyframes(scene, {}, 2)
    assert ok is False
    assert len(scene.keyframes) == 0
