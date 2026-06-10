"""
Модуль рекомендаций.

Анализирует решения юзера и предлагает улучшения.
Никогда не настаивает — предлагает и ждёт ответа.
Юзер всегда главный.
"""

from .models import VideoProject, Scene


def check_scene_duration(scene_sec: int, scene_summary: str) -> str | None:
    """Предупреждает если длительность сцены выглядит странно."""
    if scene_sec < 3:
        return (
            f"Сцена '{scene_summary}' — {scene_sec} сек очень мало, "
            "зритель не успеет воспринять. Рекомендую минимум 4-5 сек. Изменить?"
        )
    if scene_sec > 30:
        return (
            f"Сцена '{scene_summary}' — {scene_sec} сек довольно долго для одной сцены. "
            "Рекомендую разбить на две или сократить. Оставить или изменить?"
        )
    return None


def check_keyframes_for_scene(n_keyframes: int, scene_summary: str, action: str) -> str | None:
    """Рекомендует количество кадров исходя из типа сцены."""
    action_lower = (action or "").lower()
    is_dynamic = any(w in action_lower for w in [
        "бежит", "прыгает", "летит", "падает", "дерётся", "танцует",
        "гонится", "взрывается", "быстро", "мчится"
    ])
    is_calm = any(w in action_lower for w in [
        "стоит", "смотрит", "сидит", "думает", "спит", "разговаривает"
    ])

    if is_dynamic and n_keyframes == 1:
        return (
            f"Сцена '{scene_summary}' динамичная. "
            "С 1 кадром движение будет резким. "
            "Рекомендую 2-3 кадра для плавности. Изменить?"
        )
    if is_calm and n_keyframes == 3:
        return (
            f"Сцена '{scene_summary}' спокойная — 3 кадра здесь избыточно. "
            "Рекомендую 1-2 кадра. Оставить или изменить?"
        )
    return None


def recommend_duration_split(total_sec: int, n_scenes: int, summaries: list[str]) -> list[int]:
    """
    Рекомендует разбивку секунд по сценам.
    Первая и последняя сцены чуть длиннее (вступление и финал).
    """
    if n_scenes == 0:
        return []
    base = total_sec // n_scenes
    remainder = total_sec % n_scenes
    durations = [base] * n_scenes
    # Добавляем остаток к первой и последней сценам
    if remainder > 0:
        durations[0] += remainder // 2 + remainder % 2
    if remainder > 1:
        durations[-1] += remainder // 2
    return durations


def check_total_duration(total_sec: int, n_scenes: int) -> str | None:
    """Предупреждает о нереалистичных параметрах."""
    avg = total_sec / max(n_scenes, 1)
    if avg < 3:
        return (
            f"При {n_scenes} сценах и {total_sec} сек общей длины "
            f"на каждую сцену выходит {avg:.0f} сек — очень мало. "
            "Рекомендую увеличить длину или уменьшить количество сцен. Изменить?"
        )
    if total_sec > 300:
        return (
            f"{total_sec} сек ({total_sec//60} мин) — это большой мультфильм. "
            "Генерация займёт очень долго. Рекомендую до 2-3 минут для начала. Оставить?"
        )
    return None


def check_script_scene(summary: str, action: str, setting: str) -> list[str]:
    """Возвращает список рекомендаций по сцене сценария."""
    tips = []
    if len(summary) < 10:
        tips.append(
            f"Сцена описана очень коротко: '{summary}'. "
            "Добавить детали что именно происходит?"
        )
    if not setting or len(setting) < 5:
        tips.append("Не указано место действия — добавить фон? (лес, город, дом...)")
    if not action or len(action) < 5:
        tips.append("Не описано действие персонажа — что он делает в этой сцене?")
    return tips


def check_user_preference(preference_text: str) -> str | None:
    """Проверяет не конфликтует ли предпочтение со стилем Pixar."""
    text_lower = preference_text.lower()
    conflicts = [
        ("реалистично", "Фотореализм плохо совместим с Pixar стилем. Уточнить что имеется в виду?"),
        ("аниме", "Аниме стиль и Pixar — разные направления. Остаёмся в Pixar?"),
        ("хоррор", "Хоррор элементы сложно совместить с Pixar стилем. Рекомендую мягкое напряжение. Оставить как есть?"),
    ]
    for keyword, warning in conflicts:
        if keyword in text_lower:
            return warning
    return None


def format_project_summary(project: VideoProject) -> str:
    """Формирует читаемую сводку проекта перед генерацией промтов."""
    lines = [
        f"📋 *Сводка проекта*",
        f"",
        f"🎬 Название: {project.session_name}",
        f"💡 Идея: {project.idea}",
        f"🎨 Стиль: Pixar 3D",
        f"📐 Формат: {project.aspect_ratio}",
        f"⏱ Общая длина: {project.total_duration_sec} сек",
        f"🎭 Сцен: {len(project.scenes)}",
        f"",
        f"👥 Персонажи:",
    ]
    for ch in project.characters:
        lines.append(f"  • {ch.anchor()}")

    lines.append("")
    lines.append("🎬 Сцены:")
    for s in project.scenes:
        lines.append(
            f"  Сцена {s.number}: {s.summary} "
            f"— {s.duration_sec} сек, {s.suggested_keyframes} кадр(а)"
        )

    if project.user_preferences:
        lines.append("")
        lines.append("⚙️ Твои предпочтения:")
        for p in project.user_preferences:
            lines.append(f"  • {p.description}")

    lines.append("")
    lines.append("Всё верно? Или что-то изменить?")
    return "\n".join(lines)
