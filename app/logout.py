"""Одноразовый выход бота с официального сервера api.telegram.org.

Telegram требует это перед переходом на свой сервер telegram-bot-api,
иначе локальный сервер не сможет принять бота. Запуск:

    python -m app.logout
"""

import asyncio

from aiogram import Bot

from . import config


async def main() -> None:
    bot = Bot(config.BOT_TOKEN)  # официальный сервер
    try:
        ok = await bot.log_out()
        print("Готово, бот вышел с api.telegram.org" if ok else "Telegram ответил отказом")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
