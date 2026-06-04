import argparse
import json
import sys
from pathlib import Path

from .llm import backend_info
from .clarify import plan_questions, ask_user_interactively
from .script import generate_script
from .prompt_builder import build_image_prompts, build_animation_prompts
from .render import slugify, render_markdown


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Генератор промтов для ИИ-видео под Grok "
        "(картинка + анимация + диалоги)",
    )
    parser.add_argument("idea", help="Идея видео одной фразой")
    parser.add_argument(
        "--style",
        default="cinematic",
        choices=["cinematic", "anime", "3d", "realistic", "cartoon"],
        help="Визуальный стиль",
    )
    parser.add_argument("--scenes", type=int, default=4, help="Количество сцен")
    parser.add_argument("--duration", type=int, default=6, help="Сек на сцену")
    parser.add_argument("--aspect", default="16:9", help="Соотношение сторон")
    parser.add_argument(
        "--keyframes",
        default="auto",
        choices=["auto", "1", "2", "3"],
        help="Сколько ключевых кадров на сцену. auto = Claude решает сам.",
    )
    parser.add_argument(
        "--language",
        default="auto",
        choices=["auto", "ru", "en", "kk"],
        help="Язык реплик. auto = Claude определит по идее.",
    )
    parser.add_argument(
        "--dialogue",
        default="auto",
        choices=["auto", "manual", "off"],
        help="Режим диалогов. manual в CLI работает как auto (ручная "
        "правка реализована только в Telegram-боте).",
    )
    parser.add_argument("--out", default="output", help="Папка для результатов")
    parser.add_argument(
        "--no-questions",
        action="store_true",
        help="Пропустить уточняющие вопросы (использовать дефолты)",
    )
    args = parser.parse_args(argv)

    print(f"Бэкенд: {backend_info()}")
    print(f"Модель: claude-opus-4-7 + extended thinking (high)\n")

    print(f"[1/4] Анализирую идею и решаю, что доспросить...")
    plan = plan_questions(args.idea, args.style)
    is_dialogue_heavy = bool(plan.get("is_dialogue_heavy", False))
    print(f"      {plan.get('reasoning', '')}")

    clarifications: dict = {}
    if not args.no_questions:
        clarifications = ask_user_interactively(plan)

    print(f"[2/4] Пишу сценарий из {args.scenes} сцен...")
    project = generate_script(
        idea=args.idea,
        style=args.style,
        scenes_count=args.scenes,
        is_dialogue_heavy=is_dialogue_heavy,
        clarifications=clarifications,
        keyframes_mode=args.keyframes,
        language=args.language,
        dialogue_mode=args.dialogue,
    )
    print(f"      «{project.title}» — {len(project.scenes)} сцен")

    print(f"[3/4] Генерирую промты для картинок (ключевые кадры)...")
    build_image_prompts(project)

    print(f"[4/4] Генерирую промты для анимации...")
    build_animation_prompts(project, args.duration, args.aspect)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(project.title)
    md_path = out_dir / f"{slug}.md"
    json_path = out_dir / f"{slug}.json"

    md_path.write_text(render_markdown(project), encoding="utf-8")
    json_path.write_text(
        json.dumps(project.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nГотово. Открой:")
    print(f"  {md_path}")
    print(f"  {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
