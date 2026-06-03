import json
import os
import re
from anthropic import Anthropic

MODEL = "claude-opus-4-7"

_client: Anthropic | None = None


def client() -> Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "Не задан ANTHROPIC_API_KEY. Экспортируй ключ: "
                "export ANTHROPIC_API_KEY=sk-ant-..."
            )
        _client = Anthropic()
    return _client


def ask_json(system: str, user: str, max_tokens: int = 2000) -> dict:
    """Отправляет запрос в Claude и парсит JSON-ответ."""
    msg = client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = msg.content[0].text.strip()
    # Срезаем markdown-обёртку, если модель её всё-таки добавила
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)
