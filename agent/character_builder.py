"""
Пошаговый сборщик персонажей.

Агент задаёт вопросы по одному, ничего не придумывает сам.
Если что-то выглядит странно или может плохо выйти в Pixar стиле —
предупреждает и рекомендует, но последнее слово за юзером.
"""

from .models import Character

QUESTIONS = [
    ("name",             "Как зовут персонажа?"),
    ("age",              "Сколько ему/ей лет (или примерный возраст)?"),
    ("appearance",       "Опиши внешность: цвет волос, глаз, рост, телосложение."),
    ("clothing",         "Во что одет персонаж? Опиши одежду и стиль."),
    ("personality",      "Какой у него/неё характер? (весёлый, серьёзный, смелый...)"),
    ("speech_style",     "Как говорит? (громко и уверенно, тихо, с юмором, важно...)"),
    ("special_features", "Есть особые детали? (шрам, аксессуар, необычная черта) — или напиши 'нет'"),
]

# Что может плохо выйти в Pixar 3D стиле — ключевые слова и рекомендации
WARNINGS = [
    (
        ["6 рук", "4 руки", "8 рук", "много рук", "лишние конечности"],
        "Нестандартное количество конечностей в Pixar стиле обычно выглядит перегруженно "
        "и генератор может исказить их. Рекомендую стандартную анатомию + добавить "
        "необычную деталь (цвет, аксессуар). Оставить как есть или изменить?"
    ),
    (
        ["50 персонажей", "100 персонажей", "толпа из", "много людей"],
        "Очень много персонажей в кадре теряют детализацию. Рекомендую "
        "3-5 главных на переднем плане, остальные размыто на фоне. Изменить?"
    ),
    (
        ["без лица", "нет лица", "без глаз", "без рта"],
        "Персонаж без черт лица сложен для Pixar стиля — эмоции передаются именно через лицо. "
        "Рекомендую минималистичное лицо. Оставить или добавить?"
    ),
    (
        ["реалистичный", "фотореалистичный", "как живой"],
        "Фотореализм и Pixar стиль плохо совместимы — это разные направления. "
        "Оставить Pixar или хочешь другой стиль?"
    ),
]


def check_warnings(text: str) -> str | None:
    """Возвращает предупреждение если в тексте есть потенциальная проблема."""
    text_lower = text.lower()
    for keywords, warning in WARNINGS:
        if any(kw in text_lower for kw in keywords):
            return warning
    return None


def build_characters_interactive() -> list[Character]:
    """CLI-версия: интерактивный сбор персонажей через терминал."""
    characters = []
    print("\n🎭 Создаём персонажей. Сколько главных персонажей в твоём мультфильме?")

    while True:
        try:
            count = int(input("Количество: ").strip())
            if count < 1:
                raise ValueError
            break
        except ValueError:
            print("Введи число от 1 и выше.")

    for i in range(count):
        print(f"\n── Персонаж {i + 1} из {count} ──")
        data = {}

        for field_name, question in QUESTIONS:
            while True:
                print(f"\n🤖 {question}")
                answer = input("Ты: ").strip()
                if not answer:
                    print("Пожалуйста, напиши ответ.")
                    continue

                warning = check_warnings(answer)
                if warning:
                    print(f"\n💡 Рекомендация: {warning}")
                    choice = input("Твой ответ (оставить/изменить): ").strip().lower()
                    if "изменить" in choice or "изменю" in choice or "нет" in choice:
                        continue

                data[field_name] = answer
                break

        char = Character(
            name=data.get("name", "Персонаж"),
            age=data.get("age", ""),
            appearance=data.get("appearance", ""),
            clothing=data.get("clothing", ""),
            personality=data.get("personality", ""),
            speech_style=data.get("speech_style", ""),
            special_features=data.get("special_features", ""),
        )

        print(f"\n✅ Персонаж создан: {char.anchor()}")
        print("💡 Всё верно? Если хочешь что-то изменить — напиши что именно, иначе 'ок'")
        feedback = input("Ты: ").strip().lower()

        if feedback and feedback != "ок" and feedback != "ok" and feedback != "да":
            print("🤖 Что изменить? Напиши поле и новое значение:")
            fix = input("Ты: ").strip()
            # Простая обработка правки
            for field_name, question in QUESTIONS:
                label = question.split(":")[0].lower().replace("?", "")
                if field_name in fix.lower() or label in fix.lower():
                    print(f"🤖 Новое значение для '{question}':")
                    new_val = input("Ты: ").strip()
                    setattr(char, field_name, new_val)
                    break

        characters.append(char)

    return characters


async def build_characters_from_answers(answers_per_char: list[dict]) -> list[Character]:
    """API-версия: собирает персонажей из словарей ответов (для бота/сайта)."""
    characters = []
    for data in answers_per_char:
        char = Character(
            name=data.get("name", "Персонаж"),
            age=data.get("age", ""),
            appearance=data.get("appearance", ""),
            clothing=data.get("clothing", ""),
            personality=data.get("personality", ""),
            speech_style=data.get("speech_style", ""),
            special_features=data.get("special_features", ""),
        )
        characters.append(char)
    return characters


def get_next_question(field_index: int) -> tuple[str, str] | None:
    """Возвращает (field_name, question) по индексу или None если вопросы кончились."""
    if field_index < len(QUESTIONS):
        return QUESTIONS[field_index]
    return None
