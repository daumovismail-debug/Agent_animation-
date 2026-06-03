"""
Стадия уточнений: Claude смотрит идею и решает, что нужно доспросить
у пользователя перед генерацией сценария.
"""
from pathlib import Path
from .llm import ask_json

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def plan_questions(idea: str, style: str) -> dict:
    """
    Возвращает:
    {
      "is_dialogue_heavy": bool,
      "reasoning": str,
      "questions": [{"key": str, "question": str, "suggestions": [str, ...]}, ...]
    }
    """
    system = (PROMPTS_DIR / "system_clarify.md").read_text(encoding="utf-8")
    user = f"Идея пользователя: {idea}\nВыбранный стиль: {style}\n"
    return ask_json(system, user)


def ask_user_interactively(plan: dict) -> dict:
    """
    Запускает интерактивный диалог в терминале по списку вопросов.
    Возвращает {key: answer, ...}.
    """
    answers: dict[str, str] = {}
    questions = plan.get("questions", [])
    if not questions:
        print("  Уточнений не нужно, иду генерировать сценарий.")
        return answers

    print(f"\n  Нужно уточнить {len(questions)} момент(ов):")
    if plan.get("is_dialogue_heavy"):
        print("  (видео разговорное — будут вопросы про голос и реплики)")
    print()

    for i, q in enumerate(questions, 1):
        print(f"  [{i}/{len(questions)}] {q['question']}")
        suggestions = q.get("suggestions", [])
        for j, s in enumerate(suggestions, 1):
            print(f"      {j}) {s}")
        if suggestions:
            print(f"      0) свой вариант (ввести текст)")
        raw = input("  > ").strip()

        if suggestions and raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(suggestions):
                answers[q["key"]] = suggestions[n - 1]
                print()
                continue
            if n == 0:
                raw = input("  свой ответ: ").strip()
        if not raw and suggestions:
            # пустой ввод = первый вариант (рекомендованный)
            answers[q["key"]] = suggestions[0]
        else:
            answers[q["key"]] = raw
        print()
    return answers
