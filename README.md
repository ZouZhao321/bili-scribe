# Bilibili Transcript

B 站视频字幕提取 + Whisper 本地语音转录工具。

## 功能

- 自动提取 B 站视频 CC/AI 字幕（秒出）
- 无字幕时自动降级到 Whisper 本地语音转录
- 支持标准链接、短链接（b23.tv）、av 号
- 输出纯文本、带时间戳、JSON 三种格式
- 全部本地完成，无需付费 API

## 安装

```bash
# 创建 Python 虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install faster-whisper
```

## 使用

```bash
# 纯文本输出（适合 AI 总结）
python3 fetch_transcript.py "https://www.bilibili.com/video/BV1xxx" --text-only

# 带时间戳
python3 fetch_transcript.py "BV1xxx" --timestamps

# JSON 输出
python3 fetch_transcript.py "BV1xxx" --json

# 选择模型
python3 fetch_transcript.py "BV1xxx" --model tiny    # 最快
python3 fetch_transcript.py "BV1xxx" --model small   # 默认，推荐
python3 fetch_transcript.py "BV1xxx" --model medium  # 更准

# 使用便捷脚本
./bili.sh "URL"              # 默认 small 模型
./bili.sh "URL" tiny         # 指定模型
./bili.sh "URL" --text-only  # 传额外参数
```

## 模型选择

| 模型 | 大小 | 速度 | 质量 | 适用场景 |
|------|------|------|------|---------|
| tiny | 75MB | ~1x | 一般 | 快速预览 |
| base | 141MB | ~1.5x | 可用 | 短视频 |
| small | 464MB | ~3x | 较好 | 日常使用（默认） |
| medium | 1.5GB | ~8x | 好 | 重要内容 |
| large-v3 | 3.1GB | ~15x | 最好 | 最高精度 |

## 三级降级策略

1. **CC 字幕**（UP 主上传）→ 调 B 站 API 直接拿 JSON，秒出
2. **AI 字幕**（B 站自动生成）→ 同上
3. **Whisper 本地转录** → API 下载音频流 → CPU 本地转录

## 支持的 URL 格式

- `https://www.bilibili.com/video/BV1xxx`
- `https://b23.tv/xxxxx`（短链接）
- `https://www.bilibili.com/video/av12345`（旧格式）
- `BV1xxx`（直接 BV 号）

## 依赖

- Python 3.10+
- faster-whisper（语音转录）
- 无需其他外部依赖，使用 Python 标准库

## License

MIT
