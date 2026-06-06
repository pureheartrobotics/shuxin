FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      ffmpeg \
      libsndfile1 \
      locales && \
    sed -i '/zh_CN.UTF-8/s/^# //g' /etc/locale.gen && \
    locale-gen && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com && \
    pip config set global.timeout 120 && \
    pip config set install.retries 5

ENV LANG=zh_CN.UTF-8 \
    LC_ALL=zh_CN.UTF-8 \
    LANGUAGE=zh_CN:zh \
    PYTHONIOENCODING=utf-8 \
    SHUXIN_HOME=/app/data/shuxin_home \
    VOICE_DEVICE_CONFIG=/app/data/devices.yaml

WORKDIR /app

# Tier 1 — heavy: torch / ASR stack (change rarely).
COPY requirements-voice-heavy.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    pip install -r requirements-voice-heavy.txt && \
    find /usr/local/lib/python3.11/site-packages -type d -name tests -prune -exec rm -rf {} + && \
    find /usr/local/lib/python3.11/site-packages -type d -name __pycache__ -prune -exec rm -rf {} +

# Tier 2 — app: server, memory, TTS, integrations (day-to-day changes).
COPY requirements-voice-app.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-voice-app.txt && \
    find /usr/local/lib/python3.11/site-packages -type d -name tests -prune -exec rm -rf {} + && \
    find /usr/local/lib/python3.11/site-packages -type d -name __pycache__ -prune -exec rm -rf {} +

COPY pyproject.toml README.md SOUL.md ./
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir --no-deps -e . \
 && mkdir -p /app/data /app/models /app/samples /app/outputs

CMD ["python", "-m", "shuxin.voice.cli", "--help"]
