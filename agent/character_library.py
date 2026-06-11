"""
Библиотека персонажей.

Генерирует эталонные изображения персонажей через openclaw и кэширует их
в characters_library/ для переиспользования в следующих сериях.
"""

import re
import shutil
import subprocess
import logging
from pathlib import Path

log = logging.getLogger("character_library")

IMAGE_MODEL = "xai/grok-imagine-image-quality"

NVM_WRAP = (
    'export NVM_DIR="$HOME/.nvm"; '
    '. "$NVM_DIR/nvm.sh"; '
    'nvm use 22 --silent; '
    '{cmd}'
)


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "-", slug).strip("-") or "character"


def build_character_prompt(char: dict) -> str:
    """Собирает Pixar-portrait промт из полей персонажа."""
    parts = [
        "Pixar 3D animated character, full body portrait, plain white background,",
        f"character named {char.get('name', 'unknown')},",
    ]
    if char.get("appearance"):
        parts.append(f"{char['appearance']},")
    if char.get("clothing"):
        parts.append(f"wearing {char['clothing']},")
    spec = char.get("special_features", "")
    if spec and spec.lower() not in ("нет", "no", "none", "-", ""):
        parts.append(f"{spec},")
    parts.append(
        "front-facing view, high quality render, expressive face, "
        "Pixar animation studio style, no background clutter"
    )
    return " ".join(parts)


def _openclaw_generate(prompt: str, output_path: Path, dry_run: bool) -> bool:
    cmd = NVM_WRAP.format(cmd=(
        f'openclaw infer image generate'
        f' --prompt "{prompt.replace(chr(34), chr(39))}"'
        f' --model {IMAGE_MODEL}'
        f' --output "{output_path}"'
    ))
    if dry_run:
        log.info("[DRY-RUN] openclaw portrait: %s...", prompt[:60])
        return True
    log.info("RUN openclaw portrait → %s", output_path)
    result = subprocess.run(["bash", "-lc", cmd])
    if result.returncode != 0:
        log.error("openclaw вернул код %d", result.returncode)
        return False
    return True


def generate_character_refs(
    characters: list,
    render_chars_dir: Path,
    lib_dir: Path,
    dry_run: bool,
) -> dict:
    """
    Генерирует или переиспользует эталонные портреты персонажей.

    Возвращает {character_name: Path} для каждого успешно подготовленного персонажа.
    Кэш хранится в lib_dir; render_chars_dir — копия для текущего проекта.
    """
    render_chars_dir.mkdir(parents=True, exist_ok=True)
    lib_dir.mkdir(parents=True, exist_ok=True)

    refs: dict = {}

    for char in characters:
        name = (char.get("name") or "").strip()
        if not name:
            continue

        slug = slugify(name)
        lib_path = lib_dir / f"{slug}.jpg"
        scene_path = render_chars_dir / f"{slug}.jpg"

        if lib_path.exists():
            log.info("Персонаж «%s»: эталон из кэша → %s", name, lib_path)
            shutil.copy2(lib_path, scene_path)
            refs[name] = scene_path
            continue

        prompt = build_character_prompt(char)
        log.info("Персонаж «%s»: генерирую эталон...", name)

        ok = _openclaw_generate(prompt, scene_path, dry_run)
        if not ok:
            log.error("Не удалось сгенерировать эталон для «%s», пропускаю", name)
            continue

        if not dry_run and scene_path.exists():
            shutil.copy2(scene_path, lib_path)
            log.info(
                "Эталон закэширован: %s (%d KB)",
                lib_path,
                lib_path.stat().st_size // 1024,
            )

        refs[name] = scene_path

    return refs
