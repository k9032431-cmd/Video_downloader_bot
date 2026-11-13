# Video Downloader Bot

Telegram-бот, который скачивает видео, фото и музыку по ссылке:
TikTok, Instagram, YouTube, Pinterest, X/Twitter, VK, Reddit, SoundCloud
и сотни других сайтов (всё, что поддерживают [yt-dlp](https://github.com/yt-dlp/yt-dlp)
и [gallery-dl](https://github.com/mikf/gallery-dl)). Подходит и для фильмов.

## Как работает

1. Пользователь присылает ссылку.
2. Бот скачивает её через **yt-dlp** (видео/аудио) и показывает прогресс.
   Если видео нет (фото-пост, карусель, пин-картинка, слайдшоу TikTok),
   подключается **gallery-dl**.
3. Одно видео приходит с кнопкой **🎵 Аудио** (mp3), несколько фото/видео —
   альбомом.
4. Если файл больше лимита Telegram, бот режет его ffmpeg-ом на части
   (без перекодирования, каждая часть нормально проигрывается) и присылает
   «Часть 1/N», «Часть 2/N»…

Команды: `/start`, `/help`, `/audio <ссылка>`.

## Лимиты Telegram

| Режим | Один файл | Фильм 1080p (~4 ГБ) |
|---|---|---|
| Обычный `api.telegram.org` | 50 МБ | ~90 частей, качество снижается до 720/480p |
| **Свой сервер Bot API** (docker-compose) | **2 ГБ** | 2–3 части в полном качестве |

2 ГБ — жёсткий максимум для ботов в Telegram, больше нельзя никак.
Поэтому всё, что больше, приходит частями.

## Запуск с большими файлами (рекомендуется)

1. Создай бота у [@BotFather](https://t.me/BotFather), получи `BOT_TOKEN`.
2. Получи `api_id` и `api_hash` на [my.telegram.org](https://my.telegram.org)
   → *API development tools*.
3. Заполни `.env`:
   ```bash
   cp .env.example .env
   ```
4. Один раз выведи бота с официального сервера (иначе локальный его не примет):
   ```bash
   pip install -r requirements.txt
   python -m app.logout
   ```
5. Запусти:
   ```bash
   docker compose up -d --build
   ```

Бот и сервер Bot API используют общую папку `/downloads`, поэтому файлы
передаются по пути на диске, без повторной загрузки.

Места на диске нужно с запасом: фильм на время отправки лежит дважды
(целиком и нарезанный). Ограничение задаёт `MAX_DOWNLOAD_MB`.

## Запуск без своего сервера (лимит 50 МБ)

```bash
cp .env.example .env        # нужен только BOT_TOKEN
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m app
```

Нужен установленный `ffmpeg`.

## Важно

- **Cookies.** Instagram, YouTube (на серверах в дата-центрах) и некоторые
  другие сайты требуют вход. Экспортируй cookies из браузера в формате
  Netscape (например, расширением «Get cookies.txt LOCALLY») и укажи
  `COOKIES_FILE`. В Docker примонтируй файл в контейнер бота.
- **Обновляй yt-dlp.** Сайты часто меняются:
  `pip install -U yt-dlp gallery-dl` (или `docker compose build --no-cache`).
- Чтобы вернуть бота на официальный сервер, выключи свой сервер и подожди
  ~10 минут (или вызови `logOut` у локального сервера).
