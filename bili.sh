#!/bin/bash
# Bilibili video transcript extraction wrapper
# Usage: ./bili.sh "URL" [model]
#   model: tiny / base / small (default) / medium / large-v3

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="/opt/data/.venv-whisper/bin/python3"
TRANSCRIPT_SCRIPT="$SCRIPT_DIR/fetch_transcript.py"

URL="$1"
MODEL="${2:-small}"

if [ -z "$URL" ]; then
    echo "Usage: $0 \"B站链接\" [模型]"
    echo ""
    echo "模型选择："
    echo "  tiny    - 最快，质量一般（75MB）"
    echo "  base    - 较快，质量可用（141MB）"
    echo "  small   - 均衡，推荐日常使用（464MB）[默认]"
    echo "  medium  - 较慢，质量好（1.5GB，需手动下载）"
    echo "  large-v3 - 最慢，质量最好（3.1GB，需手动下载）"
    echo ""
    echo "示例："
    echo "  $0 \"https://www.bilibili.com/video/BV1xxx\""
    echo "  $0 \"https://b23.tv/xxx\" tiny"
    echo "  $0 \"BV1xxx\" --timestamps"
    exit 1
fi

exec "$VENV_PYTHON" "$TRANSCRIPT_SCRIPT" "$URL" --model "$MODEL" "${@:3}"
