# ════════════════════════════════════════════════════════════════════════
#  DEWIAR VOICES — живые голоса персонажей (Qwen3-TTS) для всех приложений
#  Путь на сервере: /app/src/vllm/tts/Dockerfile
#  Собирает и запускает панель: /vllm/voices.php → «Установить» (lib/ttsctl.php).
#  Модели держатся в памяти видеокарты → первая фраза звучит через доли секунды.
#
#  Какой torch ставить, задаёт TORCH_INDEX: …/whl/cu128 — видеокарта (RTX 3090 и новее), …/whl/cpu — процессор
#  (на процессоре голос будет очень медленным — только для проверки).
# ════════════════════════════════════════════════════════════════════════
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HUB_CACHE=/models

# ffmpeg — образцы голосов из mp3/m4a/ogg, темп речи, mp3 в ответе; sox — его просит qwen-tts
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg sox libsox-fmt-all curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG TORCH_INDEX=https://download.pytorch.org/whl/cu128
RUN pip install torch torchaudio --index-url ${TORCH_INDEX}

# Версия qwen-tts зафиксирована: обновление — осознанно, сменой здесь.
ARG QWEN_TTS_VERSION=0.1.1
RUN pip install "qwen-tts==${QWEN_TTS_VERSION}" numpy soundfile

WORKDIR /opt/voices
COPY app.py .

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["python", "app.py"]
