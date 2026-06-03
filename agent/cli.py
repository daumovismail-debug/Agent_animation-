import argparse
import json
import re
import sys
from pathlib import Path

from .script import generate_script
from .prompt_builder import build_prompts
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
        "",
        f"**Главный герой (anchor):** {project.character_anchor}",
        "",
        "---",
        "",
    ]
    for s in project.scenes:
        lines += [
            f"## Сцена {s.number}: {s.summary}",
            "",
            f"- Длительность: {s.duration_sec} сек",
            f"- Соотношение сторон: {s.aspect_ratio}",
            f"- Настроение: {s.mood}",
            "",
            "**Промт для Grok:**",
            "",
            "```",
            s.prompt or "",
            "```",
            "",
            "**Negative prompt:**",
            "",
            "```",
            s.negative_prompt or "",
            "```",
            "",
            "---",
            "",
        ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Генератор промтов для ИИ-видео (Grok)",
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
    args = parser.parse_args(argv)

    print(f"[1/3] Генерирую сценарий из идеи: {args.idea!r}")
    project = generate_script(args.idea, args.style, args.scenes)
    print(f"      Готово: {len(project.scenes)} сцен — «{project.title}»")

    print(f"[2/3] Строю промты под Grok для каждой сцены...")
    project = build_prompts(project, args.duration, args.aspect)
    print(f"      Готово.")

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

    print(f"[3/3] Сохранил:")
    print(f"      {md_path}")
    print(f"      {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
