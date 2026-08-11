# bili-scribe

B 站视频字幕提取 + Whisper 本地语音转录工具，采用**三级降级策略**确保转录成功率。

## 功能特性

- **智能字幕提取** — 三级降级：CC 字幕 → AI 字幕 → Whisper 本地转录，保证总能拿到文稿
- **Whisper 转录** — 基于 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 本地语音转文字，支持 `tiny` / `base` / `small` / `medium` / `large-v3` 模型
- **CLI 命令行** — 统一命令行工具，支持转录、队列管理、批量下载等操作
- **持久化队列** — 基于 JSON 的任务队列，配合 cron 定时调度，重启后自动恢复未完成任务
- **Web 界面 + API** — FastAPI 后端 + SPA 前端，一键 Docker 部署
- **模型灵活** — 支持按任务独立选择模型，从轻量 `tiny` 到高精度 `large-v3`

## 快速开始

### 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip
- FFmpeg（用于音频提取）

### 安装

```bash
git clone https://github.com/ZouZhao321/bili-scribe.git
cd bili-scribe
uv venv && uv pip install -e ".[dev]"
```

### 基本用法

```bash
# 转录单个视频
.venv/bin/bili-scribe transcribe "https://www.bilibili.com/video/BV1xx411c7mD"

# 批量下载整个合集
.venv/bin/bili-scribe batch "https://space.bilibili.com/123456/channel/collectiondetail?sid=789"

# 加入队列（由 cron 定时调度）
.venv/bin/bili-scribe queue add "https://www.bilibili.com/video/BV1xx411c7mD"

# 查看队列状态
.venv/bin/bili-scribe queue status

# 启动 Web API 服务
.venv/bin/bili-scribe serve
```

## 命令列表

| 命令 | 说明 |
|---------|-------------|
| `transcribe <url>` | 转录单个视频 |
| `batch <url>` | 批量下载合集内所有视频 |
| `queue add <url>` | 将视频加入持久化队列 |
| `queue status` | 查看队列状态和进度 |
| `queue list` | 列出队列中所有任务 |
| `serve` | 启动 FastAPI Web 服务 |
| `info <url>` | 查询视频元信息 |
| `version` | 显示版本号 |

### CLI 参数

```
bili-scribe transcribe <url> [--model MODEL] [--language LANG]
bili-scribe batch <url> [--model MODEL] [--language LANG]
bili-scribe queue add <url> [--model MODEL]
bili-scribe serve [--host HOST] [--port PORT]
```

## 三级降级策略

```
1. CC 字幕（UP 主上传）
   ↓ 不可用
2. AI 字幕（B 站自动生成）
   ↓ 不可用
3. Whisper 本地转录（CPU）
   → 始终可用，最可靠
```

## Web 控制台

启动服务后访问 `http://localhost:8000`：

```bash
.venv/bin/bili-scribe serve
```

或使用 Docker 部署：

```bash
docker compose up -d
```

功能包括：
- 一键视频转录
- 实时队列监控
- 文稿浏览与下载
- 健康检查端点 `/api/v1/health`

## Docker

```bash
# 构建并启动
docker compose up -d

# 查看日志
docker compose logs -f

# 停止
docker compose down
```

环境变量配置：

| 变量 | 默认值 | 说明 |
|----------|---------|-------------|
| `BILI_SCRIBE_OUTPUT_DIR` | `/app/out` | 转录文稿输出目录 |
| `BILI_SCRIBE_TASKS_DIR` | `/app/tasks` | 任务队列持久化目录 |
| `BILI_SCRIBE_PASSWORD` | 无 | HTTP Basic Auth 密码（暴露到公网务必设置） |

## Whisper 模型选择

| 模型 | 大小 | 内存 | 速度 | 适用场景 |
|-------|------|-----|-------|----------|
| `tiny` | ~75MB | ~1GB | 最快 | 快速草稿 |
| `base` | ~145MB | ~1GB | 快 | **默认推荐** — 平衡之选 |
| `small` | ~488MB | ~2GB | 中等 | 更好精度 |
| `medium` | ~1.5GB | ~4GB | 慢 | 高质量 |
| `large-v3` | ~3GB | ~6GB | 最慢 | 最高精度 |

## 输出结构

每个视频在 `out/` 下生成独立目录：

```
out/
└── BV1xx411c7mD_视频标题/
    ├── 转录文稿.txt          # 完整转录文本
    ├── 视频信息.txt           # 视频元信息
    ├── 音频.wav               # 提取的音频文件
    └── 书面文稿.txt           # 书面化版本（可选）
```

## 项目结构

```
bili-scribe/
├── src/
│   ├── core/          # 核心引擎：B 站 API、Whisper 转录、队列持久化
│   ├── cli/           # CLI 命令行入口与子命令
│   └── web/           # FastAPI 服务 + SPA 前端界面
├── docs/
│   ├── agents/        # Agent 操作文档
│   ├── adr/           # 架构决策记录
│   └── experiments/   # Whisper 实验记录
├── script/            # 辅助脚本
├── out/               # 转录输出（gitignore）
├── tests/             # 测试套件（pytest）
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## License

MIT

---

> [English Documentation](README.md)