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

COPY requirements-voice-local.txt ./

# Install the large local voice stack first so Docker can reuse this layer.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    pip install -r requirements-voice-local.txt

COPY requirements-shuxin-core.txt ./

# Core ShuXin runtime dependencies are separate from voice feature packages.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-shuxin-core.txt

COPY requirements-voice-web.txt ./

# Voice server and database dependencies.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-voice-web.txt

COPY requirements-voice-integrations.txt ./

# External provider dependencies change more often than the local voice stack.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-voice-integrations.txt

COPY requirements-voice-barcode.txt ./

# Device binding barcode dependencies are isolated in the final dependency layer.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-voice-barcode.txt

COPY pyproject.toml README.md SOUL.md ./
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir --no-deps -e .
RUN mkdir -p /app/data /app/models /app/samples /app/outputs

CMD ["python", "-m", "shuxin.voice.cli", "--help"]
