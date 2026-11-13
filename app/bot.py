import asyncio
import html
import logging
import re
import secrets
from collections import OrderedDict

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
from .downloader import DownloadError, DownloadResult, MediaFile, download

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"']+")

HELP_TEXT = (
    "👋 Пришли мне ссылку — я скачаю видео, фото или музыку.\n\n"
    "Поддерживаются TikTok, Instagram, YouTube, Pinterest, X/Twitter, VK, "
    "Reddit, SoundCloud и ещё сотни сайтов.\n\n"
    "Под каждым видео есть кнопка «🎵 Аудио» — она пришлёт звук в mp3.\n"
    "Команда /audio &lt;ссылка&gt; — сразу скачать mp3."
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


def short_caption(result: DownloadResult) -> str | None:
    if not result.title:
        return None
    title = result.title.strip()
    title = title if len(title) <= 200 else title[:197] + "…"
    return html.escape(title)


def human_size(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} МБ"


# ---------------------------------------------------------------- отправка

async def send_result(message: Message, result: DownloadResult, url: str, audio: bool) -> None:
    caption = short_caption(result)
    too_big = [f for f in result.files if f.size > config.MAX_UPLOAD_BYTES]
    files = [f for f in result.files if f.size <= config.MAX_UPLOAD_BYTES]

    if not files:
        raise DownloadError(
            f"Файл слишком большой ({human_size(too_big[0].size)}), "
            f"лимит Telegram — {human_size(config.MAX_UPLOAD_BYTES)}."
        )

    groupable = [
        f for f in files
        if f.kind == "video" or (f.kind == "photo" and f.size <= config.MAX_PHOTO_BYTES)
    ]
    others = [f for f in files if f not in groupable]

    # Одиночное видео — с кнопкой «Аудио».
    if len(groupable) == 1 and groupable[0].kind == "video":
        f = groupable[0]
        await message.answer_chat_action(ChatAction.UPLOAD_VIDEO)
        await message.answer_video(
            FSInputFile(f.path),
            caption=caption,
            width=f.width,
            height=f.height,
            duration=f.duration,
            supports_streaming=True,
            reply_markup=audio_keyboard(url) if result.via_ytdlp else None,
        )
    elif len(groupable) == 1:
        await message.answer_chat_action(ChatAction.UPLOAD_PHOTO)
        await message.answer_photo(FSInputFile(groupable[0].path), caption=caption)
    elif groupable:
        await message.answer_chat_action(ChatAction.UPLOAD_PHOTO)
        for i in range(0, len(groupable), 10):
            chunk = groupable[i : i + 10]
            media = []
            for j, f in enumerate(chunk):
                cap = caption if i == 0 and j == 0 else None
                if f.kind == "video":
                    media.append(InputMediaVideo(
                        media=FSInputFile(f.path), caption=cap, width=f.width,
                        height=f.height, duration=f.duration, supports_streaming=True,
                    ))
                else:
                    media.append(InputMediaPhoto(media=FSInputFile(f.path), caption=cap))
            await message.answer_media_group(media)

    for f in others:
        if f.kind == "audio":
            await message.answer_chat_action(ChatAction.UPLOAD_VOICE)
            await message.answer_audio(
                FSInputFile(f.path),
                title=result.title[:64] if result.title else None,
                duration=f.duration,
            )
        elif f.kind == "animation":
            await message.answer_animation(FSInputFile(f.path))
        else:
            await message.answer_chat_action(ChatAction.UPLOAD_DOCUMENT)
            await message.answer_document(FSInputFile(f.path))

    if too_big:
        await message.answer(f"⚠️ Пропущено файлов из-за размера: {len(too_big)}")


async def process(message: Message, url: str, audio: bool) -> None:
    user_id = message.chat.id
    if user_id in user_busy:
        await message.answer("⏳ Подожди, предыдущая загрузка ещё идёт.")
        return

    user_busy.add(user_id)
    status = await message.answer("⏳ Скачиваю…")
    try:
        async with semaphore:
            # Если видео не влезает в лимит — пробуем качество ниже.
            heights = [1080] if audio else ([1080, 720] if config.BOT_API_URL else [720, 480, 360])
            result: DownloadResult | None = None
            for h in heights:
                if result:
                    result.cleanup()
                result = await download(url, audio=audio, max_height=h)
                videos = [f for f in result.files if f.kind == "video"]
                biggest = max((f.size for f in videos), default=0)
                if biggest <= config.MAX_UPLOAD_BYTES:
                    break
                # В разы больше лимита — понижение качества не поможет, не тратим время.
                if biggest > config.MAX_UPLOAD_BYTES * 4:
                    break
                log.info("Too big at %sp, retrying lower", h)

            assert result is not None
            try:
                await send_result(message, result, url, audio)
            finally:
                result.cleanup()
        await status.delete()
    except DownloadError as e:
        log.warning("Download failed: %s — %s", url, e)
        text = str(e)
        if "слишком большой" not in text:
            text = (
                "❌ Не получилось скачать по этой ссылке.\n"
                "Проверь, что пост публичный, или попробуй позже."
            )
        await status.edit_text(text)
    except TelegramBadRequest as e:
        log.exception("Telegram error for %s", url)
        await status.edit_text(f"❌ Telegram не принял файл: {e.message}")
    except Exception:
        log.exception("Unexpected error for %s", url)
        await status.edit_text("❌ Что-то пошло не так. Попробуй ещё раз.")
    finally:
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


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан (см. .env.example)")

    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    session = None
    if config.BOT_API_URL:
        session = AiohttpSession(api=TelegramAPIServer.from_base(config.BOT_API_URL, is_local=True))

    bot = Bot(
        config.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    log.info("Bot started, upload limit %s", human_size(config.MAX_UPLOAD_BYTES))
    await dp.start_polling(bot)
