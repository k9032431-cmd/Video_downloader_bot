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

## Установка одной командой

На чистом сервере с Ubuntu/Debian (или любом Linux с Docker):

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/k9032431-cmd/Video_downloader_bot/main/install.sh)"
```

Скрипт сам поставит Docker, скачает бота в `/opt/video-bot`, спросит токен
и режим работы, соберёт и запустит всё нужное.

Подготовь заранее:
- токен бота от [@BotFather](https://t.me/BotFather);
- для файлов до 2 ГБ (фильмы) — `api_id` и `api_hash` с
  [my.telegram.org](https://my.telegram.org) → *API development tools*.

## Управление

После установки на сервере есть команда `videobot`:

```
sudo videobot            # меню
sudo videobot update     # обновить бота и yt-dlp одной командой
sudo videobot logs       # логи
sudo videobot status     # состояние, режим, версия, свободное место
sudo videobot restart | start | stop
sudo videobot config     # изменить токен, режим, качество
sudo videobot cookies    # загрузить cookies.txt
sudo videobot autoupdate # обновляться каждую ночь автоматически
sudo videobot uninstall
```

## Лимиты Telegram

| Режим | Один файл | Фильм 1080p (~4 ГБ) |
|---|---|---|
| Обычный `api.telegram.org` | 50 МБ | ~90 частей, качество снижается до 720/480p |
| **Свой сервер Bot API** | **2 ГБ** | 2–3 части в полном качестве |

2 ГБ — жёсткий максимум для ботов в Telegram, больше нельзя никак.
Поэтому всё, что больше, приходит частями. Режим выбирается при установке
(и потом в `videobot config`).

Места на диске нужно с запасом: фильм на время отправки лежит дважды
(целиком и нарезанный). Ограничение задаёт `MAX_DOWNLOAD_MB` в `.env`.

## Ручной запуск (для разработки)

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
  Netscape (например, расширением «Get cookies.txt LOCALLY»), загрузи файл
  на сервер и выполни `sudo videobot cookies`.
- **Обновляй yt-dlp.** Сайты часто меняются — `sudo videobot update` или
  включи автообновление.
