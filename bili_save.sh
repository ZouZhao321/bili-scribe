#!/bin/bash
# Bilibili video transcript extraction - complete pipeline
# Saves: audio, transcript, video link
#
# Usage: ./bili_save.sh "URL" [model]
#   model: tiny / base / small (default) / medium / large-v3
#
# Output: ~/bilibili-output/
#   audio/        - audio files (.m4s)
#   transcripts/  - text transcripts (.txt) + link info (_link.txt)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3"

# 如果 venv 不存在，回退到系统 Python
if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

TRANSCRIPT_SCRIPT="$SCRIPT_DIR/fetch_transcript.py"
OUTPUT_DIR="$HOME/bilibili-output"

URL="$1"
MODEL="${2:-small}"

if [ -z "$URL" ]; then
    echo "Usage: $0 \"B站链接\" [模型]"
    echo ""
    echo "输出目录: ~/bilibili-output/"
    echo "  audio/        - 音频文件"
    echo "  transcripts/  - 转录文稿 + 视频链接信息"
    echo ""
    echo "示例："
    echo "  $0 \"https://www.bilibili.com/video/BV1xxx\""
    echo "  $0 \"https://b23.tv/xxx\" small"
    echo "  $0 \"BV1xxx\" tiny"
    exit 1
fi

# Ensure output directories exist
mkdir -p "$OUTPUT_DIR/audio" "$OUTPUT_DIR/transcripts"

# Resolve BV ID from URL
echo ">>> 解析链接..."
BV=$($VENV_PYTHON -c "
import sys, re, urllib.request, json

url = '$URL'
headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.bilibili.com'}

if 'b23.tv' in url:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            url = resp.url
    except: pass

m = re.search(r'(BV[\w]{10})', url)
if m:
    print(m.group(1))
    sys.exit(0)

m = re.search(r'av(\d+)', url)
if m:
    aid = m.group(1)
    data = json.loads(urllib.request.urlopen(urllib.request.Request(f'https://api.bilibili.com/x/web-interface/view?aid={aid}', headers=headers), timeout=15).read())
    if data.get('code') == 0:
        print(data['data']['bvid'])
        sys.exit(0)

print('ERROR', file=sys.stderr)
sys.exit(1)
" 2>/dev/null)

if [ -z "$BV" ] || [ "$BV" = "ERROR" ]; then
    echo "错误：无法解析链接: $URL"
    exit 1
fi

echo "BV ID: $BV"

# Get video info
echo ">>> 获取视频信息..."
INFO=$($VENV_PYTHON -c "
import urllib.request, json
headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.bilibili.com'}
data = json.loads(urllib.request.urlopen(urllib.request.Request('https://api.bilibili.com/x/web-interface/view?bvid=$BV', headers=headers), timeout=15).read())
if data.get('code') == 0:
    d = data['data']
    title = d.get('title', '').replace('/', '_').replace(chr(92), '_')
    duration = d.get('duration', 0)
    author = d.get('owner', {}).get('name', '')
    print(f'{title}|{duration}|{author}')
" 2>/dev/null)

TITLE=$(echo "$INFO" | cut -d'|' -f1)
DURATION=$(echo "$INFO" | cut -d'|' -f2 | tr -d '[:space:]')
AUTHOR=$(echo "$INFO" | cut -d'|' -f3)

# Validate duration is a number
if ! [[ "$DURATION" =~ ^[0-9]+$ ]]; then
    DURATION=0
fi

DURATION_MIN=$((DURATION / 60))
DURATION_SEC=$((DURATION % 60))

echo "标题: $TITLE"
echo "作者: $AUTHOR"
echo "时长: ${DURATION_MIN}分${DURATION_SEC}秒"

# Create safe filename
SAFE_TITLE=$(echo "$TITLE" | head -c 20 | tr ' /' '_')
FILENAME="${BV}_${SAFE_TITLE}"

# Save video link info
cat > "$OUTPUT_DIR/transcripts/${FILENAME}_link.txt" << EOF
视频链接: https://www.bilibili.com/video/$BV/
BV号: $BV
标题: $TITLE
作者: $AUTHOR
时长: ${DURATION_MIN}分${DURATION_SEC}秒
转录模型: $MODEL
转录时间: $(date '+%Y-%m-%d %H:%M:%S')
EOF

echo ""
echo ">>> 开始转录（模型: $MODEL）..."

# Run transcription, save audio and transcript
$VENV_PYTHON "$TRANSCRIPT_SCRIPT" "$BV" \
    --text-only \
    --model "$MODEL" \
    --save-audio "$OUTPUT_DIR/audio/${FILENAME}.m4s" \
    > "$OUTPUT_DIR/transcripts/${FILENAME}.txt" 2>&1

# Check results
echo ""
if [ -f "$OUTPUT_DIR/transcripts/${FILENAME}.txt" ] && [ -s "$OUTPUT_DIR/transcripts/${FILENAME}.txt" ]; then
    LINES=$(wc -l < "$OUTPUT_DIR/transcripts/${FILENAME}.txt")
    SIZE=$(du -h "$OUTPUT_DIR/transcripts/${FILENAME}.txt" | cut -f1)
    echo ">>> 转录完成！"
    echo "  链接信息: ~/bilibili-output/transcripts/${FILENAME}_link.txt"
    echo "  转录文稿: ~/bilibili-output/transcripts/${FILENAME}.txt ($LINES 行, $SIZE)"
    if [ -f "$OUTPUT_DIR/audio/${FILENAME}.m4s" ]; then
        AUDIO_SIZE=$(du -h "$OUTPUT_DIR/audio/${FILENAME}.m4s" | cut -f1)
        echo "  音频文件: ~/bilibili-output/audio/${FILENAME}.m4s ($AUDIO_SIZE)"
    fi
else
    echo ">>> 转录失败，请检查错误信息"
    cat "$OUTPUT_DIR/transcripts/${FILENAME}.txt"
fi
