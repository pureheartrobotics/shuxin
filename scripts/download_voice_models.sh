#!/usr/bin/env bash
# 下载语音 demo 需要的模型到挂载目录，避免把模型文件打进镜像。

if [[ -z "${BASH_VERSION:-}" ]]; then
  exec bash "$0" "$@"
fi

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODEL_KIND="${1:-streaming-stt}"

# streaming-stt 用于浏览器准实时测试台；sensevoice 保留给原有文件 STT 流程。
case "$MODEL_KIND" in
  streaming-stt)
    MODEL_ID="${MODEL_ID:-iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online}"
    LOCAL_DIR="${LOCAL_DIR:-models/paraformer-zh-streaming}"
    ;;
  sensevoice)
    MODEL_ID="${MODEL_ID:-iic/SenseVoiceSmall}"
    LOCAL_DIR="${LOCAL_DIR:-models/SenseVoiceSmall}"
    ;;
  -h|--help)
    echo "Usage: bash scripts/download_voice_models.sh [streaming-stt|sensevoice]"
    echo "Optional env: MODEL_ID=... LOCAL_DIR=..."
    exit 0
    ;;
  *)
    echo "Unknown model kind: $MODEL_KIND" >&2
    echo "Usage: bash scripts/download_voice_models.sh [streaming-stt|sensevoice]" >&2
    exit 1
    ;;
esac

mkdir -p "$LOCAL_DIR"

python -c "from modelscope import snapshot_download; snapshot_download('${MODEL_ID}', local_dir='${LOCAL_DIR}')"

echo "Downloaded ${MODEL_ID} to ${LOCAL_DIR}"
