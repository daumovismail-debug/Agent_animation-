"""
Обучение агентов твоими примерами (few-shot) и накопленными правилами.

Идея простая: у каждого агента есть папка с ЭТАЛОНАМИ (training/<agent>/*.md)
и файл ПРАВИЛ (training/rules/<agent>.md). Перед вызовом модели мы
подмешиваем их в system-промпт. Так агент учится на ТВОИХ работах и правках,
а не на абстрактных инструкциях.

Три слоя обучения (см. training/README.md):
  1. Конституция  — сам system-промпт (prompts/system_*.md)
  2. Эталоны      — training/<agent>/*.md          ← этот модуль
  3. Петля правок — training/rules/<agent>.md       ← этот модуль

Файлы читаются на КАЖДЫЙ вызов, поэтому обучение мгновенное: положил новый
пример / дописал правило → следующая генерация уже его учитывает. Перезапуск
сервиса не нужен.
"""

from __future__ import annotations

import re
from pathlib import Path

TRAINING_DIR = Path(__file__).parent.parent / "training"

# Сколько эталонов максимум подмешивать (чтобы не раздувать контекст).
# Берём самые свежие по имени файла (01, 02, ... — новые в конце).
MAX_EXAMPLES = 4


def _example_files(agent: str) -> list[Path]:
    folder = TRAINING_DIR / agent
    if not folder.is_dir():
        return []
    files = [
        p for p in folder.glob("*.md")
        # файлы, начинающиеся с "_", служебные (шаблон, заметки) — пропускаем
        if not p.name.startswith("_")
    ]
    return sorted(files)[-MAX_EXAMPLES:]


def _extract_section(text: str, heading: str) -> str:
    """Достаёт содержимое markdown-секции '## HEADING' до следующего '## '."""
    pattern = rf"^##\s*{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)"
    m = re.search(pattern, text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if not m:
        return ""
    body = m.group(1).strip()
    # убираем HTML-комментарии-инструкции (в примерах их могли не удалить)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip()
    # убираем markdown-обёртку ```json ... ``` если есть
    body = re.sub(r"^```(?:json|md|markdown)?\s*", "", body)
    body = re.sub(r"\s*```$", "", body)
    return body.strip()


def load_examples(agent: str) -> str:
    """
    Собирает эталоны агента в готовый для промпта блок.

    Каждый эталонный .md должен содержать секции:
        ## ИДЕЯ        — вход (что просили)
        ## ЭТАЛОН       — желаемый ответ агента (как ты хочешь чтобы он выдавал)
    Секция ## ЗАМЕТКИ (если есть) модели НЕ передаётся — она для тебя.
    """
    blocks: list[str] = []
    for i, path in enumerate(_example_files(agent), 1):
        text = path.read_text(encoding="utf-8")
        idea = _extract_section(text, "ИДЕЯ")
        gold = _extract_section(text, "ЭТАЛОН")
        if not gold:
            continue
        parts = [f"━━━ ЭТАЛОН {i} ━━━"]
        if idea:
            parts.append(f"Вход:\n{idea}")
        parts.append(f"Так надо (эталонный ответ):\n{gold}")
        blocks.append("\n".join(parts))

    if not blocks:
        return ""

    intro = (
        "НИЖЕ — ЭТАЛОНЫ АВТОРА. Это лучшие прошлые работы. Внимательно перейми "
        "их стиль, ритм, длину фраз, тон и структуру. Не копируй сюжет — "
        "копируй ПОЧЕРК. Твой ответ должен быть неотличим по качеству и стилю "
        "от этих эталонов.\n\n" + "\n\n".join(blocks)
    )
    return intro


def load_rules(agent: str) -> str:
    """Накопленные правила-правки автора (training/rules/<agent>.md)."""
    path = TRAINING_DIR / "rules" / f"{agent}.md"
    if not path.is_file():
        return ""
    body = path.read_text(encoding="utf-8")
    # убираем HTML-комментарии целиком (в т.ч. многострочные) — это инструкции для автора
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    # выкидываем markdown-заголовки
    lines = [ln for ln in body.splitlines() if not ln.strip().startswith("#")]
    body = "\n".join(lines).strip()
    if not body:
        return ""
    return "ДОПОЛНИТЕЛЬНЫЕ ПРАВИЛА АВТОРА (обязательны, важнее общих инструкций):\n" + body


def augment_system(system: str, agent: str) -> str:
    """
    Дополняет базовый system-промпт агента его эталонами и правилами.
    Порядок: конституция → правила автора → эталоны.
    """
    parts = [system]
    rules = load_rules(agent)
    if rules:
        parts.append(rules)
    examples = load_examples(agent)
    if examples:
        parts.append(examples)
    return "\n\n".join(parts)
