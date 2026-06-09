FROM python:3.11-slim

# 常见编译依赖（部分包可能需要；尽量保持精简）
RUN if [ -f /etc/apt/sources.list ]; then \
      sed -i 's@http://deb.debian.org/debian@https://mirrors.tuna.tsinghua.edu.cn/debian@g' /etc/apt/sources.list; \
      sed -i 's@http://security.debian.org/debian-security@https://mirrors.tuna.tsinghua.edu.cn/debian-security@g' /etc/apt/sources.list; \
      sed -i 's@http://deb.debian.org/debian-security@https://mirrors.tuna.tsinghua.edu.cn/debian-security@g' /etc/apt/sources.list; \
    elif [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's@http://deb.debian.org/debian@https://mirrors.tuna.tsinghua.edu.cn/debian@g' /etc/apt/sources.list.d/debian.sources; \
      sed -i 's@http://deb.debian.org/debian-security@https://mirrors.tuna.tsinghua.edu.cn/debian-security@g' /etc/apt/sources.list.d/debian.sources; \
    else \
      echo "No APT sources file found" >&2; \
      exit 1; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

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
