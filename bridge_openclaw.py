#!/usr/bin/env python3
"""
bridge_openclaw.py — рендер VideoProject через OpenClaw (image) + xAI API (video).

Usage:
    python bridge_openclaw.py output/<slug>.json [--dry-run]

Примечание: openclaw infer video generate не имеет флага --input для картинки,
поэтому image-to-video вызывается напрямую через xAI REST API.
OAuth-токен читается из ~/.openclaw/agents/main/agent/openclaw-agent.sqlite.
"""

import argparse
import base64
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bridge")

PAUSE = 3
IMAGE_MODEL = "xai/grok-imagine-image-quality"      # для openclaw CLI
IMAGE_DIRECT_MODEL = "grok-imagine-image-quality"   # для прямого xAI API
VIDEO_MODEL = "grok-imagine-video"
XAI_BASE_URL = "https://api.x.ai/v1"
AGENT_SQLITE = Path.home() / ".openclaw/agents/main/agent/openclaw-agent.sqlite"
XAI_OAUTH_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
POLL_INTERVAL = 5
MAX_POLL = 120

# draft = быстрый черновик; hd = финальное качество
QUALITY = {
    "draft": {"image_resolution": None,  "video_resolution": "480p", "suffix": ""},
    "hd":    {"image_resolution": "2k",  "video_resolution": "720p", "suffix": "_hd"},
}

NVM_WRAP = (
    'export NVM_DIR="$HOME/.nvm"; '
    '. "$NVM_DIR/nvm.sh"; '
    'nvm use 22 --silent; '
    '{cmd}'
)


# ── Утилиты ──────────────────────────────────────────────────────────────────

def slugify(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    return re.sub(r"[\s_-]+", "-", slug).strip("-") or "project"


def check_ffmpeg():
    if not shutil.which("ffmpeg"):
        log.error("ffmpeg не найден. Установи: apt install -y ffmpeg")
        sys.exit(1)
    log.info("ffmpeg: %s", shutil.which("ffmpeg"))


def load_project(json_path: Path) -> dict:
    if not json_path.exists():
        log.error("Файл не найден: %s", json_path)
        sys.exit(1)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if "scenes" not in data:
        log.error("Неверный формат JSON: нет поля 'scenes'")
        sys.exit(1)
    return data


def openclaw_cmd(args: list) -> str:
    cmd = "openclaw " + " ".join(
        f'"{a}"' if (" " in str(a) or not str(a)) else str(a) for a in args
    )
    return NVM_WRAP.format(cmd=cmd)


def run_shell(shell_cmd: str, dry_run: bool) -> bool:
    if dry_run:
        log.info("[DRY-RUN] %s", shell_cmd)
        return True
    log.info("RUN: %s", shell_cmd)
    result = subprocess.run(["bash", "-lc", shell_cmd])
    if result.returncode != 0:
        log.error("Команда завершилась с кодом %d", result.returncode)
        return False
    return True


# ── xAI OAuth токен ───────────────────────────────────────────────────────────

def _load_xai_profile() -> tuple[dict, str, dict]:
    """Возвращает (store, profile_key, profile) для xAI из SQLite."""
    if not AGENT_SQLITE.exists():
        raise FileNotFoundError(f"Не найден SQLite: {AGENT_SQLITE}")
    con = sqlite3.connect(str(AGENT_SQLITE))
    row = con.execute(
        "SELECT store_json FROM auth_profile_store WHERE store_key='primary'"
    ).fetchone()
    con.close()
    if not row:
        raise RuntimeError("auth_profile_store пуст")
    store = json.loads(row[0])
    for key, profile in store.get("profiles", {}).items():
        if profile.get("provider") == "xai":
            return store, key, profile
    raise RuntimeError("xAI профиль не найден в SQLite")


def refresh_xai_token() -> str:
    """Обновляет access token через refresh_token. Обновляет SQLite. Возвращает новый токен."""
    store, profile_key, profile = _load_xai_profile()
    refresh_tok = profile.get("refresh")
    token_endpoint = profile.get("tokenEndpoint", "https://auth.x.ai/oauth2/token")
    if not refresh_tok:
        raise RuntimeError("refresh_token не найден в профиле xAI")

    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_tok,
        "client_id": XAI_OAUTH_CLIENT_ID,
    }).encode()
    req = urllib.request.Request(
        token_endpoint,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    new_token = data["access_token"]
    expires_in = data.get("expires_in", 3600)

    # Обновляем SQLite
    profile["access"] = new_token
    profile["expires"] = int((time.time() + expires_in) * 1000)
    if "refresh_token" in data:
        profile["refresh"] = data["refresh_token"]
    store["profiles"][profile_key] = profile

    con = sqlite3.connect(str(AGENT_SQLITE))
    con.execute(
        "UPDATE auth_profile_store SET store_json=? WHERE store_key='primary'",
        (json.dumps(store),),
    )
    con.commit()
    con.close()

    log.info("xAI токен обновлён (истекает через %d сек)", expires_in)
    return new_token


def read_xai_token() -> str:
    """Читает токен из SQLite; автоматически обновляет если истёк (буфер 60 сек)."""
    _, _, profile = _load_xai_profile()
    token = profile.get("access")
    expires_ms = profile.get("expires", 0)

    if not token:
        raise RuntimeError("access token не найден в профиле xAI")

    if expires_ms and time.time() > (expires_ms / 1000) - 60:
        log.info("xAI токен истёк или истекает через 60 сек, обновляю...")
        token = refresh_xai_token()
    else:
        log.info("xAI OAuth токен актуален (profile: xai)")

    return token


# ── Утилита определения формата по байтам ────────────────────────────────────

def _detect_mime(data: bytes) -> str:
    """PNG или JPEG по сигнатуре файла — не по расширению."""
    return "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"


# ── xAI image-to-video (прямой API) ──────────────────────────────────────────

def _xai_request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    url = XAI_BASE_URL + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def xai_generate_image(
    prompt: str,
    output_path: Path,
    token: str,
    reference_image_paths: list | None = None,
    aspect_ratio: str = "16:9",
    image_resolution: str | None = None,
) -> bool:
    """
    Генерирует картинку через xAI /images/generations.
    image_resolution=None → дефолт API (1280×720 JPEG).
    image_resolution="2k" → 2816×1584 PNG (для HD).
    Если reference_image_paths — передаёт их как reference_images для консистентности персонажей.
    Fallback на openclaw происходит на уровне вызывающего кода.
    """
    body: dict = {
        "model": IMAGE_DIRECT_MODEL,
        "prompt": prompt,
        "n": 1,
        "response_format": "b64_json",   # картинка приходит в теле, без отдельного CDN URL
        "aspect_ratio": aspect_ratio,
    }
    if image_resolution:
        body["resolution"] = image_resolution

    if reference_image_paths:
        refs = []
        for ref_path in reference_image_paths:
            if not ref_path.exists():
                log.warning("Референс не найден, пропускаю: %s", ref_path)
                continue
            mime = "image/jpeg" if ref_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
            b64_ref = base64.b64encode(ref_path.read_bytes()).decode()
            refs.append({"url": f"data:{mime};base64,{b64_ref}"})
        if refs:
            body["reference_images"] = refs
            log.info("xAI /images/generations: %d референс(ов) персонажей", len(refs))

    log.info("xAI /images/generations: POST с промтом %s...", prompt[:60])
    try:
        # Повторная попытка с обновлённым токеном при 401
        for attempt in range(2):
            try:
                resp = _xai_request("POST", "/images/generations", token, body)
                break
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    log.warning("xAI 401, обновляю токен и повторяю...")
                    token = refresh_xai_token()
                else:
                    raise
    except Exception as e:
        log.error("xAI image generation error: %s", e)
        return False

    data_list = resp.get("data", [])
    if not data_list:
        log.error("xAI image: нет data в ответе: %s", resp)
        return False

    b64_data = data_list[0].get("b64_json")
    if not b64_data:
        log.error("xAI image: нет b64_json в ответе (keys: %s)", list(data_list[0].keys()))
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.write_bytes(base64.b64decode(b64_data))
        log.info("Картинка сохранена: %s (%d KB)", output_path, output_path.stat().st_size // 1024)
        return True
    except Exception as e:
        log.error("Ошибка сохранения картинки: %s", e)
        return False


def xai_image_to_video(
    prompt: str,
    image_path: Path,
    output_path: Path,
    token: str,
    aspect_ratio: str = "16:9",
    duration: int = 6,
    resolution: str = "480p",
) -> bool:
    # Определяем mime по байтам файла, а не по расширению (2k-картинки — PNG)
    raw_img = image_path.read_bytes()
    mime = _detect_mime(raw_img)
    b64 = base64.b64encode(raw_img).decode()
    data_url = f"data:{mime};base64,{b64}"

    body = {
        "model": VIDEO_MODEL,
        "prompt": prompt,
        "image": {"url": data_url},
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
    }

    log.info("xAI API: POST /videos/generations ...")
    try:
        resp = _xai_request("POST", "/videos/generations", token, body)
    except Exception as e:
        log.error("xAI submit error: %s", e)
        return False

    request_id = resp.get("request_id")
    if not request_id:
        log.error("xAI: нет request_id в ответе: %s", resp)
        return False
    log.info("xAI request_id: %s — жду готовности...", request_id)

    # Поллинг
    for attempt in range(MAX_POLL):
        time.sleep(POLL_INTERVAL)
        try:
            status = _xai_request("GET", f"/videos/{request_id}", token)
        except Exception as e:
            log.warning("Поллинг %d/%d: ошибка %s", attempt + 1, MAX_POLL, e)
            continue

        video = status.get("video")
        if video and video.get("url"):
            video_url = video["url"]
            log.info("Видео готово, скачиваю: %s", video_url[:60])
            try:
                req = urllib.request.Request(
                    video_url,
                    headers={"Authorization": f"Bearer {token}"},
                )
                with urllib.request.urlopen(req, timeout=120) as r:
                    output_path.write_bytes(r.read())
                log.info("Сохранено: %s (%d KB)", output_path, output_path.stat().st_size // 1024)
                return True
            except Exception as e:
                log.error("Ошибка скачивания: %s", e)
                return False

        state = status.get("state") or status.get("status", "?")
        log.info("Поллинг %d/%d: state=%s", attempt + 1, MAX_POLL, state)

    log.error("xAI: превышено время ожидания (%d попыток)", MAX_POLL)
    return False


# ── Рендер сцены ─────────────────────────────────────────────────────────────

def render_scene(
    scene: dict,
    render_dir: Path,
    token: str,
    dry_run: bool,
    char_refs: dict | None = None,
    suffix: str = "",
    video_resolution: str = "480p",
    image_resolution: str | None = None,
    image_only: bool = False,
    video_only: bool = False,
) -> bool:
    n = scene["number"]
    img_path = render_dir / f"scene_{n}{suffix}.jpg"
    mp4_path = render_dir / f"scene_{n}{suffix}.mp4"

    keyframes = scene.get("keyframes", [])
    if not keyframes:
        log.error("Сцена %d: нет keyframes, пропускаю", n)
        return False
    image_prompt = keyframes[0].get("prompt", "").strip()
    if not image_prompt:
        log.error("Сцена %d: пустой image_prompt, пропускаю", n)
        return False

    animation_prompt = (scene.get("animation_prompt") or "").strip()
    if not animation_prompt:
        log.warning("Сцена %d: пустой animation_prompt, использую image_prompt", n)
        animation_prompt = image_prompt

    aspect = scene.get("aspect_ratio", "16:9")
    duration = int(scene.get("duration_sec", 6))

    # Шаг 1: картинка
    if not video_only:
        if img_path.exists():
            log.info("Сцена %d [1/2]: картинка уже есть, пропускаю → %s", n, img_path)
        else:
            res_label = image_resolution or "default"
            log.info("Сцена %d [1/2]: генерирую картинку (%s) → %s", n, res_label, img_path)

            ref_paths = list((char_refs or {}).values())
            use_xai_direct = bool(ref_paths) and not dry_run

            if use_xai_direct:
                log.info("Сцена %d: xAI /images/generations с %d референсом персонажей", n, len(ref_paths))
                ok = xai_generate_image(
                    prompt=image_prompt,
                    output_path=img_path,
                    token=token,
                    reference_image_paths=ref_paths,
                    aspect_ratio=aspect,
                    image_resolution=image_resolution,
                )
                if not ok:
                    log.warning("Сцена %d: xAI image failed, fallback на openclaw", n)
                    use_xai_direct = False

            if not use_xai_direct:
                ok = run_shell(
                    openclaw_cmd([
                        "infer", "image", "generate",
                        "--prompt", image_prompt,
                        "--model", IMAGE_MODEL,
                        "--output", str(img_path),
                    ]),
                    dry_run,
                )

            if not ok:
                log.error("Сцена %d: ошибка генерации картинки, пропускаю сцену", n)
                return False

            log.info("Пауза %d сек...", PAUSE)
            if not dry_run:
                time.sleep(PAUSE)
    else:
        if not img_path.exists() and not dry_run:
            log.error("Сцена %d: картинка не найдена для генерации видео: %s", n, img_path)
            return False

    if image_only:
        return True

    # Шаг 2: image-to-video через xAI API напрямую
    log.info("Сцена %d [2/2]: генерирую видео %s → %s", n, video_resolution, mp4_path)
    if dry_run:
        log.info(
            "[DRY-RUN] xAI API POST /videos/generations prompt=%s... image=%s res=%s",
            animation_prompt[:60], img_path, video_resolution,
        )
        return True

    ok = xai_image_to_video(
        prompt=animation_prompt,
        image_path=img_path,
        output_path=mp4_path,
        token=token,
        aspect_ratio=aspect,
        duration=min(duration, 15),
        resolution=video_resolution,
    )
    if not ok:
        log.error("Сцена %d: ошибка генерации видео, пропускаю сцену", n)
        return False

    log.info("Пауза %d сек...", PAUSE)
    time.sleep(PAUSE)
    return True


def ask_accept(img_path: Path) -> bool:
    """Показывает путь к картинке и ждёт ввода. True = принять, False = перегенерить."""
    print(f"\n  {'─' * 50}")
    print(f"  Картинка: {img_path}")
    print(f"  {'─' * 50}")
    try:
        answer = input("  Enter = принять,  r = перегенерить: ").strip().lower()
    except EOFError:
        return True
    return answer != "r"


# ── ffmpeg concat ─────────────────────────────────────────────────────────────

def concat_videos(
    render_dir: Path,
    scenes: list,
    dry_run: bool,
    suffix: str = "",
    final_name: str = "final",
) -> Path | None:
    mp4_files = sorted(
        (render_dir / f"scene_{s['number']}{suffix}.mp4" for s in scenes),
        key=lambda p: int(p.stem.split("_")[1].rstrip("_hd").split("_")[0]),
    )
    existing = [p for p in mp4_files if dry_run or p.exists()]

    if not existing:
        log.error("Нет готовых mp4 для склейки")
        return None

    concat_list = render_dir / f"concat_list{suffix}.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in existing),
        encoding="utf-8",
    )
    log.info("concat_list%s.txt: %d файл(ов)", suffix, len(existing))

    final = render_dir / f"{final_name}.mp4"
    cmd = f"ffmpeg -y -f concat -safe 0 -i {concat_list} -c copy {final}"
    if dry_run:
        log.info("[DRY-RUN] %s", cmd)
        return final

    log.info("Склейка: %s", cmd)
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        log.error("ffmpeg concat завершился с ошибкой")
        return None
    return final


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Render VideoProject via OpenClaw + xAI")
    parser.add_argument("json_path", help="Путь к output/<slug>.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Печатать команды без выполнения")
    parser.add_argument("--scene", type=int, default=None,
                        help="Рендерить только одну сцену (по номеру, для тестов)")
    parser.add_argument(
        "--quality", choices=["draft", "hd"], default="draft",
        help="draft = 480p черновик → final.mp4 (по умолчанию); hd = 720p + картинка 2k → final_hd.mp4",
    )
    parser.add_argument("--step", action="store_true",
                        help="Сначала подтвердить все картинки, потом генерировать видео")
    args = parser.parse_args()

    q = QUALITY[args.quality]
    suffix          = q["suffix"]
    video_resolution = q["video_resolution"]
    image_resolution = q["image_resolution"]
    final_name      = f"final{suffix}"

    check_ffmpeg()

    token = ""
    if not args.dry_run:
        try:
            token = read_xai_token()
        except Exception as e:
            log.error("Не могу получить xAI токен: %s", e)
            sys.exit(1)

    json_path = Path(args.json_path)
    project = load_project(json_path)

    slug = slugify(project.get("title", json_path.stem))
    render_dir = Path("render") / slug
    render_dir.mkdir(parents=True, exist_ok=True)
    log.info("Папка рендера: %s  |  качество: %s (img=%s, video=%s)",
             render_dir, args.quality.upper(),
             image_resolution or "default", video_resolution)

    # ── Библиотека персонажей ─────────────────────────────────────────────────
    char_refs: dict = {}
    characters = project.get("characters", [])
    if characters:
        log.info("━━━ Библиотека персонажей (%d) ━━━", len(characters))
        try:
            from agent.character_library import generate_character_refs
            char_refs = generate_character_refs(
                characters=characters,
                render_chars_dir=render_dir / "characters",
                lib_dir=Path("characters_library"),
                dry_run=args.dry_run,
            )
            log.info("Эталоны готовы: %s", list(char_refs.keys()))
        except Exception as e:
            log.error("Ошибка генерации эталонов, продолжаю без них: %s", e)
    else:
        log.info("Поле 'characters' отсутствует — рендер без эталонов (старый проект)")
    # ─────────────────────────────────────────────────────────────────────────

    scenes = project["scenes"]
    if args.scene is not None:
        scenes = [s for s in scenes if s["number"] == args.scene]
        if not scenes:
            log.error("Сцена %d не найдена в проекте", args.scene)
            sys.exit(1)
        log.info("Тестовый режим: рендерим только сцену %d", args.scene)

    log.info("Проект: «%s», сцен: %d", project.get("title", slug), len(scenes))

    ok_count = 0
    fail_count = 0

    if args.step:
        # ── Фаза 1: генерация и подтверждение картинок ───────────────────────
        log.info("━━━ ФАЗА 1: картинки (%d сцен) ━━━", len(scenes))
        accepted_scenes = []
        for scene in scenes:
            n = scene["number"]
            img_path = render_dir / f"scene_{n}{suffix}.jpg"
            log.info("━━━ Сцена %d / %d [КАРТИНКА] ━━━", n, len(scenes))
            while True:
                ok = render_scene(
                    scene, render_dir, token, args.dry_run, char_refs,
                    suffix=suffix,
                    video_resolution=video_resolution,
                    image_resolution=image_resolution,
                    image_only=True,
                )
                if not ok:
                    log.error("Сцена %d: пропускаю (ошибка генерации)", n)
                    fail_count += 1
                    break
                if ask_accept(img_path):
                    accepted_scenes.append(scene)
                    break
                # Пользователь нажал r — удалить и перегенерировать
                if img_path.exists():
                    img_path.unlink()
                log.info("Сцена %d: перегенерирую...", n)

        # ── Фаза 2: генерация видео (только принятые сцены) ──────────────────
        log.info("")
        log.info("━━━ ФАЗА 2: видео (%d принятых сцен) ━━━", len(accepted_scenes))
        for scene in accepted_scenes:
            n = scene["number"]
            log.info("━━━ Сцена %d / %d [ВИДЕО] ━━━", n, len(accepted_scenes))
            if render_scene(
                scene, render_dir, token, args.dry_run, char_refs,
                suffix=suffix,
                video_resolution=video_resolution,
                image_resolution=image_resolution,
                video_only=True,
            ):
                ok_count += 1
            else:
                fail_count += 1

        concat_scenes = accepted_scenes
    else:
        for scene in scenes:
            n = scene["number"]
            log.info("━━━ Сцена %d / %d ━━━", n, len(scenes))
            if render_scene(
                scene, render_dir, token, args.dry_run, char_refs,
                suffix=suffix,
                video_resolution=video_resolution,
                image_resolution=image_resolution,
            ):
                ok_count += 1
            else:
                fail_count += 1

        concat_scenes = scenes

    log.info("━━━ Склейка ━━━")
    final = concat_videos(render_dir, concat_scenes, args.dry_run,
                          suffix=suffix, final_name=final_name)

    log.info("━━━ Итог ━━━")
    log.info("Сцен успешно: %d  |  ошибок: %d", ok_count, fail_count)
    if final:
        log.info("Финальное видео: %s", final)
    else:
        log.warning("final.mp4 не создан")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
