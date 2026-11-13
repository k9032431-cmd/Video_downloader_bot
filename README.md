# Video Downloader Bot

Telegram-бот, который скачивает видео, фото и музыку по ссылке:
TikTok, Instagram, YouTube, Pinterest, X/Twitter, VK, Reddit, SoundCloud
и сотни других сайтов (всё, что поддерживают [yt-dlp](https://github.com/yt-dlp/yt-dlp)
и [gallery-dl](https://github.com/mikf/gallery-dl)).

## Как работает

1. Пользователь присылает ссылку.
2. Бот пробует скачать через **yt-dlp** (видео/аудио). Если там нет видео
   (фото-пост, карусель, пин-картинка, слайдшоу TikTok), подключается **gallery-dl**.
3. Одно видео отправляется с кнопкой **🎵 Аудио** (mp3). Несколько фото/видео
   приходят альбомом.
4. Если видео больше лимита Telegram, бот перекачивает его в качестве пониже.

Команды: `/start`, `/help`, `/audio <ссылка>`.

## Запуск

```bash
cp .env.example .env        # впиши BOT_TOKEN от @BotFather
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m app
```

Нужен установленный `ffmpeg` (для склейки видео и конвертации в mp3).

Через Docker:

```bash
docker build -t video-bot .
docker run -d --env-file .env --name video-bot video-bot
```

## Важно

- **Лимит 50 МБ.** Обычный Bot API не даёт ботам загружать файлы больше 50 МБ.
  Для файлов до 2 ГБ подними свой сервер
  [telegram-bot-api](https://github.com/tdlib/telegram-bot-api) и укажи `BOT_API_URL`.
- **Cookies.** Instagram, YouTube (на серверах в дата-центрах) и некоторые другие
  сайты требуют вход. Экспортируй cookies из браузера в формате Netscape
  (например, расширением «Get cookies.txt LOCALLY») и укажи `COOKIES_FILE`.
- **Обновляй yt-dlp.** Сайты часто меняются: `pip install -U yt-dlp gallery-dl`.
