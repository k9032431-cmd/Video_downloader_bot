FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /bot
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# При обновлении передаётся новое значение — слой пересобирается и yt-dlp/gallery-dl
# подтягиваются в последней версии (сайты часто меняются).
ARG DEPS_REFRESH=0
RUN pip install --no-cache-dir -U yt-dlp gallery-dl
COPY app ./app
CMD ["python", "-m", "app"]
