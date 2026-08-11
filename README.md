# bili-scribe

Bilibili video subtitle extraction + local Whisper speech transcription tool with **three-tier fallback strategy**.

## Features

- **Smart Subtitle Extraction** — Three-tier fallback: CC subtitles → AI-generated subtitles → Whisper local transcription
- **Whisper Transcription** — Local speech-to-text via [faster-whisper](https://github.com/SYSTRAN/faster-whisper), supports `tiny` / `base` / `small` / `medium` / `large-v3` models
- **CLI Interface** — Unified command-line tool for transcription, queue management, batch processing, and more
- **Persistent Queue** — Task queue with cron scheduling, resumes interrupted tasks after restart
- **Web API + Dashboard** — FastAPI-powered REST API with a built-in SPA frontend, Docker-ready
- **Model Flexibility** — Per-task model selection, from lightweight `tiny` to accurate `large-v3`

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- FFmpeg (for audio extraction)

### Installation

```bash
git clone https://github.com/ZouZhao321/bili-scribe.git
cd bili-scribe
uv venv && uv pip install -e ".[dev]"
```

### Basic Usage

```bash
# Transcribe a single video
.venv/bin/bili-scribe transcribe "https://www.bilibili.com/video/BV1xx411c7mD"

# Batch download an entire collection
.venv/bin/bili-scribe batch "https://space.bilibili.com/123456/channel/collectiondetail?sid=789"

# Add to queue (processed by cron scheduler)
.venv/bin/bili-scribe queue add "https://www.bilibili.com/video/BV1xx411c7mD"

# Check queue status
.venv/bin/bili-scribe queue status

# Start the web API server
.venv/bin/bili-scribe serve
```

## Commands

| Command | Description |
|---------|-------------|
| `transcribe <url>` | Transcribe a single video |
| `batch <url>` | Batch download all videos in a collection |
| `queue add <url>` | Add a video to the persistent queue |
| `queue status` | Display queue status and progress |
| `queue list` | List all tasks in the queue |
| `serve` | Start the FastAPI web server |
| `info <url>` | Fetch video metadata |
| `version` | Show version information |

### CLI Options

```
bili-scribe transcribe <url> [--model MODEL] [--language LANG]
bili-scribe batch <url> [--model MODEL] [--language LANG]
bili-scribe queue add <url> [--model MODEL]
bili-scribe serve [--host HOST] [--port PORT]
```

## Three-Tier Fallback

```
1. CC Subtitles (uploader-provided)
   ↓ not available
2. AI Subtitles (Bilibili auto-generated)
   ↓ not available
3. Whisper Local Transcription (CPU)
   → always works, most reliable
```

## Web Dashboard

Start the server and visit `http://localhost:8000`:

```bash
.venv/bin/bili-scribe serve
```

Or deploy with Docker:

```bash
docker compose up -d
```

The dashboard provides:
- One-click video transcription
- Real-time queue monitoring
- Transcript browsing and download
- Health check endpoint at `/api/v1/health`

## Docker

```bash
# Build and start
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

Configuration via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BILI_SCRIBE_OUTPUT_DIR` | `/app/out` | Transcript output directory |
| `BILI_SCRIBE_TASKS_DIR` | `/app/tasks` | Task queue persistence directory |
| `BILI_SCRIBE_PASSWORD` | (none) | HTTP Basic Auth password (set for public exposure) |

## Whisper Models

| Model | Size | RAM | Speed | Use Case |
|-------|------|-----|-------|----------|
| `tiny` | ~75MB | ~1GB | Fastest | Quick draft |
| `base` | ~145MB | ~1GB | Fast | **Default** — good balance |
| `small` | ~488MB | ~2GB | Medium | Better accuracy |
| `medium` | ~1.5GB | ~4GB | Slow | High quality |
| `large-v3` | ~3GB | ~6GB | Slowest | Best accuracy |

## Output Structure

Each video produces a directory under `out/`:

```
out/
└── BV1xx411c7mD_视频标题/
    ├── 转录文稿.txt          # Full transcript
    ├── 视频信息.txt           # Video metadata
    ├── 音频.wav               # Extracted audio
    └── 书面文稿.txt           # Polished written version (optional)
```

## Project Structure

```
bili-scribe/
├── src/
│   ├── core/          # Core engine: Bilibili API, Whisper, queue
│   ├── cli/           # CLI entry point and subcommands
│   └── web/           # FastAPI server + SPA frontend
├── docs/
│   ├── agents/        # Agent operation guides
│   ├── adr/           # Architecture Decision Records
│   └── experiments/   # Whisper benchmark experiments
├── script/            # Utility scripts
├── out/               # Transcript output (gitignored)
├── tests/             # Test suite (pytest)
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## License

MIT

---

> [中文文档](README.zh.md)