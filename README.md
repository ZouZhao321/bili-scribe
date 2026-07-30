# Bilibili Transcript

B 站视频字幕提取 + Whisper 本地语音转录工具。每次转录自动保存音频、文稿和视频链接。

## 项目架构

本项目按 **核心引擎 → 使用方式** 分层组织：

```
bilibili-transcript/
├── core/          # 核心引擎 — faster-whisper 封装 + B 站 API 交互
├── cli/           # 命令行入口
├── shell/         # Shell 脚本（一键保存、后台队列、cron 调度）
├── web/           # FastAPI 服务（HTTP API 远程调用）
├── tests/         # 测试套件
├── out/           # 输出目录
├── docs/          # 设计文档
├── fetch_transcript.py  # 兼容入口（委派到 cli/）
└── pyproject.toml
```

| 层级 | 说明 |
| ------ | ------ |
| `core/` | faster-whisper 为核心的转录引擎，B 站 API 封装，三级降级策略 |
| `cli/` | `python fetch_transcript.py` 的命令行入口，调用 core/ |
| `shell/` | Shell 脚本，封装 CLI 实现一键保存、后台队列、cron 调度 |
| `web/` | FastAPI 服务，提供 RESTful HTTP API，支持同步/异步模式 |

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
./shell/bili_save.sh "URL" [model]
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
./shell/bili_save.sh "URL" tiny     # 最快，质量一般
./shell/bili_save.sh "URL" small    # 默认，推荐日常使用
./shell/bili_save.sh "URL" medium   # 更准，需要更多内存
```

| 模型 | 大小 | 速度 | 质量 | 适用场景 |
| ------ | ------ | ------ | ------ | --------- |
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
| --------- | --------- | --------- | --------- |
| 10 分钟 | ~6MB | ~6 分钟 | ~1.6GB |
| 25 分钟 | ~18MB | ~15 分钟 | ~1.6GB |

## License

MIT

## HTTP API 服务

项目提供 RESTful API，可通过 HTTP 调用转录功能。

### 安装 API 依赖

```bash
source .venv/bin/activate
pip install -r requirements-api.txt
```

### 启动服务

```bash
# 后台启动
./shell/api.sh start

# 查看状态
./shell/api.sh status

# 查看日志
./shell/api.sh logs

# 停止服务
./shell/api.sh stop
```

### API 接口

| 方法 | 路径 | 说明 |
| ------ | ------ | ------ |
| `GET` | `/api/v1/health` | 健康检查 + 队列状态 |
| `POST` | `/api/v1/transcribe` | 提交转录任务 |
| `GET` | `/api/v1/transcribe/:task_id` | 查询任务状态 |
| `GET` | `/api/v1/tasks` | 列出所有任务 |
| `GET` | `/api/v1/video/info` | 查询视频信息 |

启动后访问 `http://localhost:8000/docs` 查看交互式 API 文档。

### 示例

```bash
# 快速转录（有字幕秒出）
curl -X POST http://localhost:8000/api/v1/transcribe \
  -H "Content-Type: application/json" \
  -d '{"url": "BV1Gm421W75K"}'

# 强制 Whisper 转录（异步）
curl -X POST http://localhost:8000/api/v1/transcribe \
  -H "Content-Type: application/json" \
  -d '{"url": "BV1Gm421W75K", "mode": "whisper", "model": "tiny"}'

# 查询任务状态
curl http://localhost:8000/api/v1/transcribe/<task_id>

# 查询视频信息（不转录）
curl "http://localhost:8000/api/v1/video/info?url=BV1Gm421W75K"

# 健康检查
curl http://localhost:8000/api/v1/health
```

详细接口文档见 [API_DESIGN.md](API_DESIGN.md)。
