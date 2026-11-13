#!/usr/bin/env bash
# Установка Video Downloader Bot одной командой:
#   sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/k9032431-cmd/Video_downloader_bot/main/install.sh)"
#
# Переменные (необязательно):
#   VIDEOBOT_DIR=/opt/video-bot   куда ставить
#   VIDEOBOT_BRANCH=main          какую ветку
#   VIDEOBOT_REPO=https://...     откуда (для приватного репо — URL с токеном)
set -euo pipefail

REPO="${VIDEOBOT_REPO:-https://github.com/k9032431-cmd/Video_downloader_bot.git}"
BRANCH="${VIDEOBOT_BRANCH:-main}"
DIR="${VIDEOBOT_DIR:-/opt/video-bot}"

[[ $EUID -eq 0 ]] || { echo "Запусти через sudo" >&2; exit 1; }

echo "🎬 Установка Video Downloader Bot в $DIR"

if ! command -v git >/dev/null || ! command -v curl >/dev/null; then
    if command -v apt-get >/dev/null; then
        apt-get update -qq && apt-get install -y -qq git curl ca-certificates
    elif command -v dnf >/dev/null; then
        dnf install -y -q git curl
    elif command -v yum >/dev/null; then
        yum install -y -q git curl
    else
        echo "Установи git и curl вручную" >&2; exit 1
    fi
fi

if [[ -d "$DIR/.git" ]]; then
    echo "Уже установлен — обновляю код"
    git -C "$DIR" fetch --quiet origin "$BRANCH"
    git -C "$DIR" checkout --quiet "$BRANCH" 2>/dev/null || git -C "$DIR" checkout --quiet -b "$BRANCH" "origin/$BRANCH"
    git -C "$DIR" reset --quiet --hard "origin/$BRANCH"
else
    git clone --quiet --branch "$BRANCH" "$REPO" "$DIR"
fi

chmod +x "$DIR/videobot"
exec "$DIR/videobot" install
