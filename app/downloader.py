"""Скачивание медиа: yt-dlp (видео/аудио) с запасным вариантом gallery-dl (фото, карусели)."""

import asyncio
import logging
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError as YtDlpError

from . import config

log = logging.getLogger(__name__)

VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav"}
GIF_EXT = {".gif"}
SKIP_EXT = {".part", ".ytdl", ".json", ".txt", ".temp"}

GALLERY_DL_TIMEOUT = 300
MAX_ITEMS = 20


class DownloadError(Exception):
    pass


@dataclass
class MediaFile:
    path: Path
    kind: str  # video | photo | audio | animation | document
    width: int | None = None
    height: int | None = None
    duration: int | None = None

    @property
    def size(self) -> int:
        return self.path.stat().st_size


@dataclass
class DownloadResult:
    workdir: Path
    files: list[MediaFile] = field(default_factory=list)
    title: str | None = None
    via_ytdlp: bool = False

    def cleanup(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)


def _classify(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in PHOTO_EXT:
        return "photo"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in GIF_EXT:
        return "animation"
    return "document"


def _collect_files(workdir: Path) -> list[MediaFile]:
    files = [
        p for p in sorted(workdir.rglob("*"))
        if p.is_file() and p.suffix.lower() not in SKIP_EXT and p.stat().st_size > 0
    ]
    return [MediaFile(path=p, kind=_classify(p)) for p in files[:MAX_ITEMS]]


# ---------------------------------------------------------------- yt-dlp

class _QuietLogger:
    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg)


def _ytdlp_opts(workdir: Path, audio: bool, max_height: int) -> dict:
    opts: dict = {
        "outtmpl": str(workdir / "%(id).60s_%(autonumber)s.%(ext)s"),
        "restrictfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _QuietLogger(),
        "playlistend": MAX_ITEMS,
        "socket_timeout": 30,
        "retries": 3,
        "concurrent_fragment_downloads": 4,
        "max_filesize": config.MAX_UPLOAD_BYTES * 3,
    }
    if config.COOKIES_FILE:
        opts["cookiefile"] = config.COOKIES_FILE

    if audio:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
            {"key": "FFmpegMetadata"},
        ]
    else:
        # Предпочитаем h264 + m4a в mp4: такие видео Telegram проигрывает прямо в чате.
        opts["format"] = "bv*+ba/b"
        opts["format_sort"] = [f"res:{max_height}", "vcodec:h264", "ext:mp4:m4a"]
        opts["merge_output_format"] = "mp4"
    return opts


def _meta_by_id(info: dict) -> dict[str, dict]:
    entries = info.get("entries") or [info]
    return {str(e.get("id")): e for e in entries if e}


def _run_ytdlp(url: str, workdir: Path, audio: bool, max_height: int) -> DownloadResult:
    with YoutubeDL(_ytdlp_opts(workdir, audio, max_height)) as ydl:
        info = ydl.extract_info(url, download=True)
    if not info:
        raise DownloadError("yt-dlp ничего не вернул")

    result = DownloadResult(workdir=workdir, title=info.get("title"), via_ytdlp=True)
    meta = _meta_by_id(info)
    for f in _collect_files(workdir):
        if audio and f.kind != "audio":
            continue
        entry = next((m for vid, m in meta.items() if f.path.name.startswith(vid[:60])), None)
        if entry:
            f.width = entry.get("width")
            f.height = entry.get("height")
            if entry.get("duration"):
                f.duration = int(entry["duration"])
        result.files.append(f)
    if not result.files:
        raise DownloadError("yt-dlp не скачал ни одного файла")
    return result


# ---------------------------------------------------------------- gallery-dl

async def _run_gallery_dl(url: str, workdir: Path) -> DownloadResult:
    cmd = [sys.executable, "-m", "gallery_dl", "-D", str(workdir), "--range", f"1-{MAX_ITEMS}", "--no-mtime"]
    if config.COOKIES_FILE:
        cmd += ["--cookies", config.COOKIES_FILE]
    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), GALLERY_DL_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise DownloadError("gallery-dl: превышено время ожидания")

    files = _collect_files(workdir)
    if not files:
        raise DownloadError(f"gallery-dl: {stderr.decode(errors='ignore').strip()[-300:]}")
    return DownloadResult(workdir=workdir, files=files)


# ---------------------------------------------------------------- public API

def _new_workdir() -> Path:
    path = config.DOWNLOAD_DIR / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


async def download(url: str, audio: bool = False, max_height: int = 1080) -> DownloadResult:
    """Скачивает медиа по ссылке. Сначала yt-dlp, при неудаче — gallery-dl (только не для аудио)."""
    workdir = _new_workdir()
    try:
        try:
            return await asyncio.to_thread(_run_ytdlp, url, workdir, audio, max_height)
        except (YtDlpError, DownloadError) as e:
            log.info("yt-dlp failed for %s: %s", url, e)
            if audio:
                raise DownloadError(str(e)) from e
            ytdlp_error = e

        # Фото, карусели, пины-картинки и т.п.
        shutil.rmtree(workdir, ignore_errors=True)
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            return await _run_gallery_dl(url, workdir)
        except DownloadError as e:
            log.info("gallery-dl failed for %s: %s", url, e)
            raise DownloadError(f"{ytdlp_error}\n{e}") from e
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
