import argparse
import json
import re
import sys
from pathlib import Path

from .llm import backend_info
from .clarify import plan_questions, ask_user_interactively
from .script import generate_script
from .prompt_builder import build_image_prompts, build_animation_prompts
from .models import VideoProject


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s-]+", "-", text)
    return text[:60] or "project"


def _render_markdown(project: VideoProject) -> str:
    lines = [
        f"# {project.title}",
        "",
        f"**Идея:** {project.idea}",
        f"**Стиль:** {project.style}",
        f"**Сцен:** {len(project.scenes)}",
        f"**Разговорное видео:** {'да' if project.is_dialogue_heavy else 'нет'}",
        "",
        f"**Главный герой (anchor):** {project.character_anchor}",
        "",
    ]
    if project.voice_notes:
        lines += [f"**Голос:** {project.voice_notes}", ""]
    if project.clarifications:
        lines += ["**Уточнения от пользователя:**", ""]
        for k, v in project.clarifications.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
    lines += ["---", ""]

    for s in project.scenes:
        lines += [
            f"## Сцена {s.number}: {s.summary}",
            "",
            f"- Длительность: {s.duration_sec} сек | {s.aspect_ratio} | "
            f"настроение: {s.mood}",
            "",
            "### 1. Промт для картинки (ключевой кадр)",
            "",
            "```",
            s.image_prompt or "",
            "```",
            "",
            "Negative:",
            "```",
            s.image_negative or "",
            "```",
            "",
            "### 2. Промт для анимации (image-to-video)",
            "",
            "```",
            s.animation_prompt or "",
            "```",
            "",
            "Negative:",
            "```",
            s.animation_negative or "",
            "```",
            "",
        ]
        if s.dialogue:
            lines += ["### 3. Реплики", ""]
            for d in s.dialogue:
                emo = f" _({d.emotion})_" if d.emotion else ""
                lines.append(f"- **{d.speaker}**{emo}: {d.text}")
            lines.append("")
        lines += ["---", ""]
    return "\n".join(lines)


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
    parser.add_argument("--out", default="output", help="Папка для результатов")
    parser.add_argument(
        "--no-questions",
        action="store_true",
        help="Пропустить уточняющие вопросы (использовать дефолты)",
    )
    args = parser.parse_args(argv)

    print(f"Бэкенд: {backend_info()}")
    print(f"Модель: claude-opus-4-7 + extended thinking (high)\n")

    # 1. Уточняющие вопросы
    clarifications: dict = {}
    print(f"[1/4] Анализирую идею и решаю, что доспросить...")
    plan = plan_questions(args.idea, args.style)
    is_dialogue_heavy = bool(plan.get("is_dialogue_heavy", False))
    print(f"      {plan.get('reasoning', '')}")

    if not args.no_questions:
        clarifications = ask_user_interactively(plan)

    # 2. Сценарий
    print(f"[2/4] Пишу сценарий из {args.scenes} сцен...")
    project = generate_script(
        idea=args.idea,
        style=args.style,
        scenes_count=args.scenes,
        is_dialogue_heavy=is_dialogue_heavy,
        clarifications=clarifications,
    )
    print(f"      «{project.title}» — {len(project.scenes)} сцен")

    # 3. Image prompts
    print(f"[3/4] Генерирую промты для картинок (ключевые кадры)...")
    build_image_prompts(project)

    # 4. Animation prompts
    print(f"[4/4] Генерирую промты для анимации...")
    build_animation_prompts(project, args.duration, args.aspect)

    # Сохранение
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(project.title)
    md_path = out_dir / f"{slug}.md"
    json_path = out_dir / f"{slug}.json"

    md_path.write_text(_render_markdown(project), encoding="utf-8")
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
