# Bilibili Transcript

B 站视频字幕提取 + Whisper 本地语音转录工具。每次转录自动保存音频、文稿和视频链接。

## 功能

- 自动提取 B 站视频 CC/AI 字幕（秒出）
- 无字幕时自动降级到 Whisper 本地语音转录
- 支持标准链接、短链接（b23.tv）、av 号
- 输出纯文本、带时间戳、JSON 三种格式
- 全部本地完成，无需付费 API
- **自动保存音频 + 转录文稿 + 视频链接信息**

## 安装

```bash
# 创建 Python 虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install faster-whisper
```

## 使用

### 快速转录（输出到终端）

```bash
python3 fetch_transcript.py "URL" --text-only
```

### 完整流程（自动保存音频 + 文稿 + 链接）

```bash
./bili_save.sh "URL" [model]
```

输出目录 `~/bilibili-output/`：
```
bilibili-output/
├── audio/
│   └── BV1xxx_视频标题.m4s          # 音频文件
└── transcripts/
    ├── BV1xxx_视频标题.txt           # 转录文稿
    └── BV1xxx_视频标题_link.txt      # 视频链接信息
```

### 模型选择

```bash
./bili_save.sh "URL" tiny     # 最快，质量一般
./bili_save.sh "URL" small    # 默认，推荐日常使用
./bili_save.sh "URL" medium   # 更准，需要更多内存
```

| 模型 | 大小 | 速度 | 质量 | 适用场景 |
|------|------|------|------|---------|
| tiny | 75MB | ~1x | 一般 | 快速预览 |
| base | 141MB | ~1.5x | 可用 | 短视频 |
| small | 464MB | ~3x | 较好 | 日常使用（默认） |
| medium | 1.5GB | ~8x | 好 | 重要内容 |
| large-v3 | 3.1GB | ~15x | 最好 | 最高精度 |

### 其他选项

```bash
# 带时间戳
python3 fetch_transcript.py "URL" --timestamps

# JSON 输出
python3 fetch_transcript.py "URL" --json

# 保存音频到指定路径
python3 fetch_transcript.py "URL" --text-only --save-audio ./audio.m4s

# 强制使用 Whisper（即使有字幕）
python3 fetch_transcript.py "URL" --whisper
```

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

## 性能参考（small 模型，2 核 CPU）

| 视频时长 | 音频大小 | 转录耗时 | 内存峰值 |
|---------|---------|---------|---------|
| 10 分钟 | ~6MB | ~6 分钟 | ~1.6GB |
| 25 分钟 | ~18MB | ~15 分钟 | ~1.6GB |

## License

MIT
