"""
Унифицированная обёртка над Claude.

Приоритет бэкендов:
1. Claude Agent SDK (claude_agent_sdk) — расход идёт с Pro/Max подписки
   через локальную авторизацию Claude Code. Нужно один раз залогиниться
   через CLI: `claude login`.
2. Anthropic SDK (anthropic) — fallback, биллинг с API-ключа из
   ANTHROPIC_API_KEY. Используется, если SDK подписки недоступен.

В обоих случаях модель — claude-opus-4-7 с extended thinking high.
"""

from __future__ import annotations

import asyncio
import json
import os
import re

MODEL = "claude-opus-4-7"
# "high" thinking budget — даём модели запас на размышление перед ответом
THINKING_BUDGET = 16000
MAX_TOKENS = 24000  # должно быть > THINKING_BUDGET + полезного ответа


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_json(text: str) -> dict:
    text = _strip_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Иногда модель добавляет преамбулу — берём первую JSON-фигуру
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


# ───────────────────────────── Backend 1: подписка ─────────────────────────────


def _try_subscription_backend():
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions  # type: ignore
    except ImportError:
        return None
    return (query, ClaudeAgentOptions)


async def _ask_subscription_async(system: str, user: str) -> str:
    sdk = _try_subscription_backend()
    assert sdk is not None
    query, ClaudeAgentOptions = sdk

    options = ClaudeAgentOptions(
        system_prompt=system,
        model=MODEL,
        max_turns=1,
        permission_mode="bypassPermissions",
        allowed_tools=[],
        extra_args={
            "thinking": json.dumps(
                {"type": "enabled", "budget_tokens": THINKING_BUDGET}
            ),
        },
    )

    chunks: list[str] = []
    async for message in query(prompt=user, options=options):
        content = getattr(message, "content", None)
        if not content:
            continue
        for block in content:
            text = getattr(block, "text", None)
            if text:
                chunks.append(text)
    return "".join(chunks)


def _ask_subscription(system: str, user: str) -> str:
    return asyncio.run(_ask_subscription_async(system, user))


# ───────────────────────────── Backend 2: API-key ──────────────────────────────


def _ask_api_key(system: str, user: str) -> str:
    from anthropic import Anthropic  # type: ignore

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "Не найден ни Claude Agent SDK (для подписки), ни ANTHROPIC_API_KEY.\n"
            "Варианты:\n"
            "  1) pip install claude-agent-sdk  + `claude login` "
            "(расход с твоей Pro-подписки)\n"
            "  2) export ANTHROPIC_API_KEY=sk-ant-... (расход с API-баланса)"
        )

    client = Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        thinking={"type": "enabled", "budget_tokens": THINKING_BUDGET},
        messages=[{"role": "user", "content": user}],
    )
    # Собираем только текстовые блоки, пропускаем thinking
    parts: list[str] = []
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


# ───────────────────────────── Публичный API ────────────────────────────────────


def _backend_name() -> str:
    if _try_subscription_backend() is not None:
        return "subscription"
    return "api-key"


def ask_text(system: str, user: str) -> str:
    """Текстовый ответ от Claude. Опус 4.7 с extended thinking high."""
    backend = _backend_name()
    if backend == "subscription":
        return _ask_subscription(system, user)
    return _ask_api_key(system, user)


def ask_json(system: str, user: str) -> dict:
    """Просит Claude вернуть JSON и парсит его."""
    text = ask_text(system, user)
    return _parse_json(text)


async def _ask_api_key_async(system: str, user: str) -> str:
    from anthropic import AsyncAnthropic  # type: ignore

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "Нет ANTHROPIC_API_KEY и нет Claude Agent SDK — не могу обратиться к Claude."
        )
    client = AsyncAnthropic()
    msg = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        thinking={"type": "enabled", "budget_tokens": THINKING_BUDGET},
        messages=[{"role": "user", "content": user}],
    )
    parts: list[str] = []
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


async def ask_text_async(system: str, user: str) -> str:
    """Async-версия для использования внутри event loop (например, телеграм-бота)."""
    backend = _backend_name()
    if backend == "subscription":
        return await _ask_subscription_async(system, user)
    return await _ask_api_key_async(system, user)


async def ask_json_async(system: str, user: str) -> dict:
    text = await ask_text_async(system, user)
    return _parse_json(text)


def backend_info() -> str:
    b = _backend_name()
    if b == "subscription":
        return "Claude Agent SDK (биллинг — Pro/Max подписка)"
    return "Anthropic API (биллинг — ANTHROPIC_API_KEY)"
