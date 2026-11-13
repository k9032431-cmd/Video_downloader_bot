"""Раздача больших файлов по ссылке через встроенный веб-сервер.

Нужна, когда файл больше лимита Telegram, а своего сервера Bot API нет:
бот присылает ссылку, фильм смотрится в браузере (с перемоткой) или скачивается.
"""

import asyncio
import logging
import re
import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from . import config

log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_UNSAFE_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _safe_name(title: str | None, suffix: str) -> str:
    name = _UNSAFE_RE.sub(" ", title or "").strip(" .")[:120] or "file"
    return name + suffix


def share_file(path: Path, title: str | None) -> str:
    """Переносит файл в папку раздачи и возвращает публичную ссылку на него."""
    token = secrets.token_urlsafe(24)
    target_dir = config.SHARE_DIR / token
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _safe_name(title, path.suffix.lower())
    shutil.move(str(path), target)
    return f"{config.PUBLIC_URL}/f/{token}/{quote(target.name)}"


async def _handle_file(request: web.Request) -> web.StreamResponse:
    token = request.match_info["token"]
    if not _TOKEN_RE.match(token):
        raise web.HTTPNotFound()
    folder = config.SHARE_DIR / token
    files = [p for p in folder.iterdir() if p.is_file()] if folder.is_dir() else []
    if not files:
        raise web.HTTPNotFound(text="Ссылка устарела или не существует")
    file = files[0]
    disposition = "attachment" if request.query.get("dl") else "inline"
    # FileResponse поддерживает Range — видео можно перематывать в браузере.
    return web.FileResponse(file, headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(file.name)}",
        "Cache-Control": "private, max-age=3600",
    })


async def _handle_root(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _cleanup_loop() -> None:
    ttl = config.LINK_TTL_HOURS * 3600
    while True:
        now = time.time()
        if config.SHARE_DIR.is_dir():
            for folder in config.SHARE_DIR.iterdir():
                try:
                    if now - folder.stat().st_mtime > ttl:
                        shutil.rmtree(folder, ignore_errors=True)
                        log.info("Expired shared file %s", folder.name)
                except FileNotFoundError:
                    pass
        await asyncio.sleep(600)


async def start_web_server() -> None:
    config.SHARE_DIR.mkdir(parents=True, exist_ok=True)
    app = web.Application()
    app.router.add_get("/", _handle_root)
    app.router.add_get("/f/{token}/{name}", _handle_file)
    app.router.add_get("/f/{token}", _handle_file)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.WEB_PORT).start()
    asyncio.create_task(_cleanup_loop())
    log.info("File links enabled: %s (port %s, TTL %sh)", config.PUBLIC_URL, config.WEB_PORT, config.LINK_TTL_HOURS)
