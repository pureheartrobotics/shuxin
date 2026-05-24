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

COPY pyproject.toml ./
COPY requirements-voice-demo.txt ./

# 先安装体积较大的语音依赖，最大化复用 Docker 缓存。
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements-voice-demo.txt

COPY requirements-voice-extra.txt ./

# WebSocket demo 的轻量 Web 依赖单独分层，避免改核心依赖时重装语音模型栈。
RUN pip install --no-cache-dir -r requirements-voice-extra.txt

COPY requirements-shuxin-core.txt ./

# ShuXin 核心运行依赖放在最后，便于独立调整 Agent 侧依赖。
RUN pip install --no-cache-dir -r requirements-shuxin-core.txt

COPY README.md SOUL.md ./
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir --no-deps -e .
RUN mkdir -p /app/data /app/models /app/samples /app/outputs

CMD ["python", "-m", "shuxin.voice.cli", "--help"]
