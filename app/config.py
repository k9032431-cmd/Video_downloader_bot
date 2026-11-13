import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
BOT_API_URL = os.environ.get("BOT_API_URL") or None
COOKIES_FILE = os.environ.get("COOKIES_FILE") or None
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "3"))
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "downloads"))

# Официальный Bot API позволяет загружать файлы до 50 МБ,
# локальный сервер telegram-bot-api — до 2000 МБ.
MAX_UPLOAD_BYTES = (2000 if BOT_API_URL else 50) * 1024 * 1024
# Фото больше 10 МБ Telegram не принимает через sendPhoto — шлём документом.
MAX_PHOTO_BYTES = 10 * 1024 * 1024
