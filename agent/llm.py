"""
Унифицированная обёртка над Claude.

Приоритет бэкендов:
1. Claude Agent SDK (claude_agent_sdk) — расход идёт с Pro/Max подписки
   через локальную авторизацию Claude Code. Нужно один раз залогиниться
   через CLI: `claude login`.
2. Anthropic SDK (anthropic) — fallback, биллинг с API-ключа из
   ANTHROPIC_API_KEY. Используется, если SDK подписки недоступен.

В обоих случаях модель — claude-opus-4-8 с extended thinking high.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path

MODEL = "claude-opus-4-8"
# "high" thinking budget — даём модели запас на размышление перед ответом
THINKING_BUDGET = 16000
MAX_TOKENS = 24000  # должно быть > THINKING_BUDGET + полезного ответа
MAX_JSON_RETRIES = 3

# ───────────────────────────── Логирование ──────────────────────────────────

_log = logging.getLogger("agent.llm")

_usage_log_path = Path(__file__).parent.parent / "agent_usage.log"
_usage_logger = logging.getLogger("agent.usage")
if not _usage_logger.handlers:
    _usage_handler = logging.FileHandler(_usage_log_path, encoding="utf-8")
    _usage_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _usage_logger.addHandler(_usage_handler)
    _usage_logger.setLevel(logging.INFO)
    _usage_logger.propagate = False


def _log_usage(label: str, input_tokens: int, output_tokens: int) -> None:
    _usage_logger.info("%s  in=%d out=%d total=%d", label, input_tokens, output_tokens,
                       input_tokens + output_tokens)


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
        # permission_mode НЕ ставим: bypassPermissions передаёт claude CLI
        # флаг --dangerously-skip-permissions, который CLI запрещает под root
        # (а наш systemd-сервис запускается от root). Нам этот режим и не
        # нужен — мы не вызываем никаких инструментов (allowed_tools=[]),
        # значит и обходить нечего.
        allowed_tools=[],
        extra_args={
            # CLI принимает только "enabled" / "adaptive" / "disabled".
            # Конкретный budget_tokens через CLI задать нельзя — он управляется
            # на стороне Claude Code. Для точного контроля нужен API-ключ
            # (там можно передать {"type": "enabled", "budget_tokens": N}).
            "thinking": "enabled",
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
    if hasattr(msg, "usage"):
        _log_usage("api-key", msg.usage.input_tokens, msg.usage.output_tokens)
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
    """Текстовый ответ от Claude. Opus 4.8 с extended thinking."""
    backend = _backend_name()
    if backend == "subscription":
        _log_usage("subscription", 0, 0)  # токены недоступны через SDK
        return _ask_subscription(system, user)
    return _ask_api_key(system, user)


def ask_json(system: str, user: str) -> dict:
    """Просит Claude вернуть JSON. До 3 попыток с авто-починкой при ошибке парсинга."""
    last_exc: Exception | None = None
    extra = ""
    for attempt in range(MAX_JSON_RETRIES):
        try:
            text = ask_text(system, user + extra)
            return _parse_json(text)
        except Exception as exc:
            last_exc = exc
            _log.warning("JSON parse failed (attempt %d/%d): %s", attempt + 1, MAX_JSON_RETRIES, exc)
            extra = (
                "\n\nIMPORTANT: Your previous response could not be parsed as JSON. "
                "Return ONLY valid JSON — no explanations, no markdown fences, no extra text."
            )
    raise last_exc  # type: ignore[misc]


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
    if hasattr(msg, "usage"):
        _log_usage("api-key-async", msg.usage.input_tokens, msg.usage.output_tokens)
    parts: list[str] = []
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


async def ask_text_async(system: str, user: str) -> str:
    """Async-версия для использования внутри event loop (например, телеграм-бота)."""
    backend = _backend_name()
    if backend == "subscription":
        _log_usage("subscription-async", 0, 0)
        return await _ask_subscription_async(system, user)
    return await _ask_api_key_async(system, user)


async def ask_json_async(system: str, user: str) -> dict:
    """Async-версия ask_json. До 3 попыток с авто-починкой при ошибке парсинга."""
    last_exc: Exception | None = None
    extra = ""
    for attempt in range(MAX_JSON_RETRIES):
        try:
            text = await ask_text_async(system, user + extra)
            return _parse_json(text)
        except Exception as exc:
            last_exc = exc
            _log.warning("JSON parse failed async (attempt %d/%d): %s",
                         attempt + 1, MAX_JSON_RETRIES, exc)
            extra = (
                "\n\nIMPORTANT: Your previous response could not be parsed as JSON. "
                "Return ONLY valid JSON — no explanations, no markdown fences, no extra text."
            )
    raise last_exc  # type: ignore[misc]


def backend_info() -> str:
    b = _backend_name()
    if b == "subscription":
        return "Claude Agent SDK (биллинг — Pro/Max подписка)"
    return "Anthropic API (биллинг — ANTHROPIC_API_KEY)"
