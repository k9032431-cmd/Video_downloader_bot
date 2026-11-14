import asyncio
import html
import logging
import re
import secrets
import shutil
import time
from collections import OrderedDict
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)

from . import config
from .downloader import DownloadError, DownloadResult, MediaFile, download, split_media
from .share import share_file, start_web_server

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"']+")

HELP_TEXT = (
    "👋 Пришли мне ссылку — я скачаю видео, фото или музыку.\n\n"
    "Поддерживаются TikTok, Instagram, YouTube, Pinterest, X/Twitter, VK, "
    "Reddit, SoundCloud и ещё сотни сайтов.\n\n"
    "Под каждым видео есть кнопка «🎵 Аудио» — она пришлёт звук в mp3.\n"
    "Команда /audio &lt;ссылка&gt; — сразу скачать mp3.\n\n"
    "Большие видео (фильмы) я присылаю частями или ссылкой на скачивание."
)

dp = Dispatcher()
semaphore = asyncio.Semaphore(config.MAX_CONCURRENT)
user_busy: set[int] = set()

# Короткие ключи для callback_data (у Telegram лимит 64 байта).
_url_store: OrderedDict[str, str] = OrderedDict()
_URL_STORE_LIMIT = 5000


def remember_url(url: str) -> str:
    key = secrets.token_urlsafe(8)
    _url_store[key] = url
    while len(_url_store) > _URL_STORE_LIMIT:
        _url_store.popitem(last=False)
    return key


def audio_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🎵 Аудио", callback_data=f"a:{remember_url(url)}")]]
    )


def short_title(result: DownloadResult, limit: int = 200) -> str | None:
    if not result.title:
        return None
    title = result.title.strip()
    return title if len(title) <= limit else title[: limit - 1] + "…"


def human_size(n: float) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.2f} ГБ"
    return f"{n / 1024**2:.1f} МБ"


def input_file(path: Path) -> FSInputFile | str:
    # Локальный сервер Bot API читает файл прямо с диска — без загрузки по HTTP.
    if config.BOT_API_LOCAL_FILES:
        return path.resolve().as_uri()
    return FSInputFile(path)


# ---------------------------------------------------------------- ошибки

_ERROR_HINTS = [
    (("sign in", "log in", "login", "cookies", "confirm you"),
     "Сайт требует вход в аккаунт. Добавь cookies: <code>sudo videobot cookies</code>"),
    (("private", "not available", "unavailable", "removed", "does not exist", "404"),
     "Видео удалено, приватное или недоступно в стране сервера."),
    (("unsupported url",), "Этот сайт не поддерживается."),
    (("http error 403", "http error 474", "http error 429", "blocked", "too many requests", "rate limit"),
     "Сайт не пускает сервер (блокировка по IP или слишком много запросов). "
     "Попробуй позже или обнови: <code>sudo videobot update</code>"),
    (("geo",), "Видео недоступно в стране сервера."),
]


def explain_error(raw: str) -> str:
    if "слишком большой" in raw:
        return f"❌ {html.escape(raw)}"
    low = raw.lower()
    hint = next((h for keys, h in _ERROR_HINTS if any(k in low for k in keys)), None)
    # Первая строка от yt-dlp без служебного префикса «ERROR: [site] id:».
    reason = raw.strip().splitlines()[0] if raw.strip() else "неизвестная ошибка"
    reason = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*[^:]+:\s*)?", "", reason)
    reason = re.sub(r"\s*;?\s*please report this issue.*$", "", reason, flags=re.I)[:300]
    text = "❌ Не получилось скачать по этой ссылке."
    if hint:
        text += f"\n\n💡 {hint}"
    return text + f"\n\n<i>Причина: {html.escape(reason)}</i>"


# ---------------------------------------------------------------- статус и прогресс

class Status:
    """Сообщение «Скачиваю…», которое обновляется не чаще раза в несколько секунд."""

    def __init__(self, message: Message):
        self.message = message
        self.downloaded = 0
        self.total: int | None = None
        self._last_text = ""
        self._task: asyncio.Task | None = None

    def on_progress(self, downloaded: int, total: int | None) -> None:
        # Вызывается из потока yt-dlp — только сохраняем значения.
        self.downloaded, self.total = downloaded, total

    async def set(self, text: str) -> None:
        if text == self._last_text:
            return
        self._last_text = text
        try:
            await self.message.edit_text(text)
        except TelegramBadRequest:
            pass

    async def _loop(self) -> None:
        start = time.monotonic()
        while True:
            await asyncio.sleep(4)
            if not self.downloaded:
                continue
            text = f"⏬ Скачиваю… {human_size(self.downloaded)}"
            if self.total:
                pct = min(100, self.downloaded * 100 // self.total)
                text += f" из {human_size(self.total)} ({pct}%)"
            speed = self.downloaded / max(1, time.monotonic() - start)
            text += f"\n⚡ {human_size(speed)}/с"
            await self.set(text)

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()


# ---------------------------------------------------------------- отправка

async def split_big_files(result: DownloadResult, status: Status) -> None:
    files: list[MediaFile] = []
    for f in result.files:
        if f.size > config.MAX_UPLOAD_BYTES and f.kind in ("video", "audio"):
            await status.set(f"✂️ Файл {human_size(f.size)} — режу на части…")
            files.extend(await split_media(f, config.MAX_UPLOAD_BYTES))
            result.split = True
        else:
            files.append(f)
    result.files = files


def share_big_files(result: DownloadResult) -> list[tuple[str, int]]:
    """Файлы больше лимита уходят в раздачу по ссылке, остальные — в Telegram."""
    links, keep = [], []
    for f in result.files:
        if f.size > config.MAX_UPLOAD_BYTES:
            size = f.size
            links.append((share_file(f.path, result.title), size))
        else:
            keep.append(f)
    result.files = keep
    return links


async def send_video(message: Message, f: MediaFile, caption: str | None, markup=None) -> None:
    await message.answer_chat_action(ChatAction.UPLOAD_VIDEO)
    await message.answer_video(
        input_file(f.path),
        caption=caption,
        width=f.width,
        height=f.height,
        duration=f.duration,
        supports_streaming=True,
        reply_markup=markup,
    )


async def send_audio(message: Message, f: MediaFile, title: str | None, caption: str | None) -> None:
    await message.answer_chat_action(ChatAction.UPLOAD_VOICE)
    await message.answer_audio(
        input_file(f.path),
        title=title[:64] if title else None,
        caption=caption,
        duration=f.duration,
    )


async def send_parts(message: Message, result: DownloadResult, files: list[MediaFile]) -> None:
    """Фильм/длинное аудио, разрезанное на части: шлём по одной с подписью «Часть N/M»."""
    title = short_title(result, 150)
    total = len(files)
    for i, f in enumerate(files, 1):
        caption = f"🎞 Часть {i}/{total}"
        if title:
            caption = f"{html.escape(title)}\n{caption}"
        if f.kind == "video":
            await send_video(message, f, caption)
        else:
            await send_audio(message, f, f"{title or 'audio'} ({i}/{total})", caption)


async def send_result(message: Message, result: DownloadResult, url: str) -> None:
    title = short_title(result)
    caption = html.escape(title) if title else None
    too_big = [f for f in result.files if f.size > config.MAX_UPLOAD_BYTES]
    files = [f for f in result.files if f.size <= config.MAX_UPLOAD_BYTES]

    if not files:
        raise DownloadError(
            f"Файл слишком большой ({human_size(too_big[0].size)}), "
            f"лимит Telegram — {human_size(config.MAX_UPLOAD_BYTES)}."
        )

    if result.split:
        await send_parts(message, result, files)
        return

    groupable = [
        f for f in files
        if f.kind == "video" or (f.kind == "photo" and f.size <= config.MAX_PHOTO_BYTES)
    ]
    others = [f for f in files if f not in groupable]

    if len(groupable) == 1 and groupable[0].kind == "video":
        # Одиночное видео — с кнопкой «Аудио».
        markup = audio_keyboard(url) if result.via_ytdlp else None
        await send_video(message, groupable[0], caption, markup)
    elif len(groupable) == 1:
        await message.answer_chat_action(ChatAction.UPLOAD_PHOTO)
        await message.answer_photo(input_file(groupable[0].path), caption=caption)
    elif groupable:
        await message.answer_chat_action(ChatAction.UPLOAD_PHOTO)
        for i in range(0, len(groupable), 10):
            media = []
            for j, f in enumerate(groupable[i : i + 10]):
                cap = caption if i == 0 and j == 0 else None
                if f.kind == "video":
                    media.append(InputMediaVideo(
                        media=input_file(f.path), caption=cap, width=f.width,
                        height=f.height, duration=f.duration, supports_streaming=True,
                    ))
                else:
                    media.append(InputMediaPhoto(media=input_file(f.path), caption=cap))
            await message.answer_media_group(media)

    for f in others:
        if f.kind == "audio":
            await send_audio(message, f, result.title, None)
        elif f.kind == "animation":
            await message.answer_animation(input_file(f.path))
        else:
            await message.answer_chat_action(ChatAction.UPLOAD_DOCUMENT)
            await message.answer_document(input_file(f.path))

    if too_big:
        await message.answer(f"⚠️ Пропущено файлов из-за размера: {len(too_big)}")


async def process(message: Message, url: str, audio: bool) -> None:
    user_id = message.chat.id
    if user_id in user_busy:
        await message.answer("⏳ Подожди, предыдущая загрузка ещё идёт.")
        return

    user_busy.add(user_id)
    status = Status(await message.answer("⏳ Скачиваю…"))
    result: DownloadResult | None = None
    try:
        async with semaphore:
            status.start()
            # С обычным Bot API (50 МБ) и нарезкой сначала пробуем качество пониже.
            # Со своим сервером (2 ГБ) или раздачей ссылкой — сразу максимальное.
            full_quality = audio or config.BOT_API_URL or config.LARGE_FILE_MODE == "link"
            heights = [config.MAX_HEIGHT] if full_quality else [720, 480]
            for h in heights:
                if result:
                    result.cleanup()
                status.downloaded, status.total = 0, None
                result = await download(url, audio=audio, max_height=h, progress=status.on_progress)
                if all(f.size <= config.MAX_UPLOAD_BYTES for f in result.files):
                    break
                log.info("Too big at %sp", h)
            status.stop()

            assert result is not None
            links = share_big_files(result) if config.LARGE_FILE_MODE == "link" else []
            if not links:
                await split_big_files(result, status)
            await status.set("⏫ Отправляю…")
            if result.files:
                await send_result(message, result, url)
            for link, size in links:
                await message.answer(
                    f"🎬 <b>{html.escape(short_title(result) or 'Файл')}</b>\n"
                    f"Размер {human_size(size)} — больше лимита Telegram, поэтому ссылкой:\n\n"
                    f"▶️ <a href=\"{html.escape(link)}\">Смотреть</a>  ·  "
                    f"⬇️ <a href=\"{html.escape(link)}?dl=1\">Скачать</a>\n\n"
                    f"<i>Ссылка работает {config.LINK_TTL_HOURS:g} ч.</i>",
                    disable_web_page_preview=True,
                )
        await status.message.delete()
    except DownloadError as e:
        log.warning("Download failed: %s — %s", url, e)
        await status.set(explain_error(str(e)))
    except TelegramBadRequest as e:
        log.exception("Telegram error for %s", url)
        await status.set(f"❌ Telegram не принял файл: {html.escape(e.message)}")
    except Exception:
        log.exception("Unexpected error for %s", url)
        await status.set("❌ Что-то пошло не так. Попробуй ещё раз.")
    finally:
        status.stop()
        if result:
            result.cleanup()
        user_busy.discard(user_id)


# ---------------------------------------------------------------- хендлеры

@dp.message(CommandStart())
@dp.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await message.answer(HELP_TEXT)


@dp.message(Command("audio"))
async def cmd_audio(message: Message) -> None:
    match = URL_RE.search(message.text or "")
    if not match:
        await message.answer("Использование: /audio &lt;ссылка&gt;")
        return
    await process(message, match.group(0), audio=True)


@dp.message(F.text | F.caption)
async def on_link(message: Message) -> None:
    match = URL_RE.search(message.text or message.caption or "")
    if not match:
        if message.chat.type == "private":
            await message.answer("Пришли ссылку на видео, фото или музыку 🙂")
        return
    await process(message, match.group(0), audio=False)


@dp.callback_query(F.data.startswith("a:"))
async def on_audio_button(callback: CallbackQuery) -> None:
    url = _url_store.get(callback.data[2:])
    if not url:
        await callback.answer("Ссылка устарела, пришли её ещё раз.", show_alert=True)
        return
    await callback.answer("Скачиваю аудио…")
    await process(callback.message, url, audio=True)


def make_bot() -> Bot:
    if config.BOT_API_URL:
        session = AiohttpSession(
            api=TelegramAPIServer.from_base(config.BOT_API_URL, is_local=True),
            timeout=config.REQUEST_TIMEOUT,
        )
    else:
        session = AiohttpSession(timeout=config.REQUEST_TIMEOUT)
    return Bot(
        config.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан (см. .env.example)")

    # Остатки незавершённых загрузок после падения/перезапуска.
    # Раздаваемые по ссылке файлы (_shared) не трогаем — они удаляются по сроку.
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for item in config.DOWNLOAD_DIR.iterdir():
        if item != config.SHARE_DIR:
            shutil.rmtree(item, ignore_errors=True)
    if config.LARGE_FILE_MODE == "link":
        await start_web_server()
    bot = make_bot()
    log.info(
        "Bot started: api=%s, file limit %s, large files: %s",
        config.BOT_API_URL or "api.telegram.org", human_size(config.MAX_UPLOAD_BYTES),
        config.LARGE_FILE_MODE,
    )
    # Не обрабатываем ссылки, накопившиеся пока бот был выключен.
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
