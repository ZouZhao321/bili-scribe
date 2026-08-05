# Bilibili Transcript API 接口设计

## 概述

为 B 站视频字幕提取和 Whisper 语音转录功能提供 HTTP API 接口，支持同步和异步两种模式。

## 设计决策

| 决策 | 选择 | 原因 |
| ------ | ------ | ------ |
| 协议 | HTTPS | 安全传输，支持生产部署 |
| 数据格式 | JSON | 通用性强，易于解析 |
| 任务模式 | 同步 + 异步 | 字幕提取秒出走同步，Whisper 转录耗时走异步 |
| 认证 | Bearer Token（可选） | 简单安全，可配置 |
| 并发 | 单进程 + 任务队列 | 避免 Whisper 模型多进程加载冲突 |

## 基础 URL

```
https://<host>:<port>/api/v1
```

## 接口列表

| 方法 | 路径 | 说明 |
| ------ | ------ | ------ |
| `GET` | `/api/v1/health` | 健康检查，含队列状态和组件检查 |
| `POST` | `/api/v1/transcribe` | **提交转录任务**，核心接口 |
| `GET` | `/api/v1/transcribe/:task_id` | 查询任务状态和结果 |
| `GET` | `/api/v1/tasks` | 列出所有任务（支持分页/过滤） |
| `GET` | `/api/v1/video/info` | 查询视频信息（不转录） |

### 1. 健康检查（获取队列状态）

```
GET /health
```

检查服务是否正常运行，返回队列状态。所有组件正常时返回 200，异常时返回 503。

**响应 200（服务正常）:**

```json
{
  "status": "ok",
  "version": "1.0.0",
  "uptime": 3600,
  "whisper_models": ["tiny", "base", "small", "medium", "large-v3"],
  "default_model": "small",
  "queue": {
    "pending": 0,
    "running": 0,
    "completed": 5,
    "failed": 0
  }
}
```

**响应 503（服务异常）:**

```json
{
  "status": "error",
  "error": "service_unhealthy",
  "message": "服务状态异常",
  "checks": {
    "queue_worker": {
      "status": "ok",
      "message": "队列工作者运行正常"
    },
    "whisper_model": {
      "status": "error",
      "message": "Whisper 模型加载失败，请检查模型文件"
    },
    "disk_space": {
      "status": "ok",
      "message": "磁盘空间充足"
    },
    "bilibili_api": {
      "status": "ok",
      "message": "B 站 API 可达"
    }
  }
}
```

| 检查项 | 说明 |
| -------- | ------ |
| `queue_worker` | 后台任务工作者是否在运行 |
| `whisper_model` | Whisper 模型是否已加载可用 |
| `disk_space` | 磁盘空间是否充足（低于 1GB 告警） |
| `bilibili_api` | B 站 API 是否可达 |

---

### 2. 提交转录任务

```
POST /transcribe
```

**请求体:**

```json
{
  "url": "https://www.bilibili.com/video/BV1Gm421W75K",
  "mode": "auto",
  "model": "small",
  "language": "zh",
  "page": 0,
  "output_format": "text",
  "cookie": "",
  "webhook": "https://my-server/callback"
}
```

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| ------ | ------ | ------ | -------- | ------ |
| `url` | string | 是 | - | B 站视频链接或 BV 号，支持 `BV1xxx`、`https://www.bilibili.com/video/BV1xxx`、`b23.tv/xxx`、`av12345` |
| `mode` | string | 否 | `"auto"` | 转录模式：`"auto"`（有字幕秒出，无字幕 Whisper 降级）、`"subtitle"`（仅字幕）、`"whisper"`（强制 Whisper）、`"both"`（字幕+Whisper 都返回） |
| `model` | string | 否 | `"small"` | Whisper 模型：`"tiny"`、`"base"`、`"small"`、`"medium"`、`"large-v3"` |
| `language` | string | 否 | `"zh"` | Whisper 语言提示，如 `"zh"`、`"en"`、`"ja"` |
| `page` | integer | 否 | `0` | 分 P 序号（0-indexed） |
| `output_format` | string | 否 | `"text"` | 输出格式：`"text"`（纯文本）、`"timestamps"`（带时间戳）、`"json"`（结构化 JSON） |
| `cookie` | string | 否 | `""` | B 站登录 Cookie（用于需要登录的视频） |
| `webhook` | string | 否 | `""` | 异步任务完成后的回调 URL（仅异步模式） |

**响应 200（同步模式，字幕秒出或 Whisper 快速完成）:**

```json
{
  "task_id": "20250330_143000_BV1Gm421W75K",
  "status": "completed",
  "mode": "sync",
  "result": {
    "bvid": "BV1Gm421W75K",
    "title": "赘X的白金作者直播课",
    "author": "作者名",
    "duration": 1530,
    "source": "subtitle",
    "total_pages": 1,
    "current_page": 0,
    "entries": 42,
    "subtitles": [
      {
        "from": 0.0,
        "to": 3.5,
        "content": "大家好，欢迎来到今天的直播课"
      },
      {
        "from": 3.5,
        "to": 8.2,
        "content": "今天我们来讲讲如何塑造人物"
      }
    ],
    "full_text": "大家好，欢迎来到今天的直播课\n今天我们来讲讲如何塑造人物\n..."
  },
  "audio": {
    "size_bytes": 6291456,
    "duration_seconds": 1530
  },
  "usage": {
    "source": "subtitle",
    "model": "",
    "duration_seconds": 0.8
  }
}
```

**响应 202（异步模式，Whisper 转录后台执行）:**

```json
{
  "task_id": "20250330_143000_BV1Gm421W75K",
  "status": "processing",
  "mode": "async",
  "estimated_seconds": 900,
  "result": null,
  "_links": {
    "self": "/api/v1/transcribe/20250330_143000_BV1Gm421W75K"
  }
}
```

---

### 3. 查询任务状态

```
GET /transcribe/:task_id
```

**响应 200（任务完成）:**

```json
{
  "task_id": "20250330_143000_BV1Gm421W75K",
  "status": "completed",
  "mode": "async",
  "created_at": "2025-03-30T14:30:00+08:00",
  "completed_at": "2025-03-30T14:45:30+08:00",
  "progress": {
    "phase": "transcribing",
    "percent": 100,
    "message": "转录完成"
  },
  "request": {
    "url": "https://www.bilibili.com/video/BV1Gm421W75K",
    "model": "small",
    "output_format": "text"
  },
  "result": {
    "bvid": "BV1Gm421W75K",
    "title": "赘X的白金作者直播课",
    "author": "作者名",
    "duration": 1530,
    "source": "whisper",
    "total_pages": 1,
    "current_page": 0,
    "entries": 120,
    "subtitles": [
      { "from": 0.0, "to": 3.5, "content": "大家好" },
      { "from": 3.5, "to": 8.2, "content": "今天我们来讲讲如何塑造人物" }
    ],
    "full_text": "大家好\n今天我们来讲讲如何塑造人物\n..."
  },
  "usage": {
    "source": "whisper",
    "model": "small",
    "duration_seconds": 930,
    "audio_duration": 1530,
    "real_time_factor": 0.61
  }
}
```

**响应 200（任务处理中）:**

```json
{
  "task_id": "20250330_143000_BV1Gm421W75K",
  "status": "processing",
  "mode": "async",
  "created_at": "2025-03-30T14:30:00+08:00",
  "progress": {
    "phase": "downloading_audio",
    "percent": 30,
    "message": "正在下载音频流...",
    "bytes_downloaded": 2097152,
    "bytes_total": 6291456
  },
  "request": {
    "url": "https://www.bilibili.com/video/BV1Gm421W75K",
    "model": "small",
    "output_format": "text"
  },
  "result": null
}
```

**进度阶段说明:**

| phase | 说明 |
| ------- | ------ |
| `queued` | 任务已加入队列，等待处理 |
| `fetching_info` | 正在获取视频信息 |
| `downloading_audio` | 正在下载音频流 |
| `loading_model` | 正在加载 Whisper 模型 |
| `transcribing` | 正在转录中 |
| `completed` | 已完成 |
| `failed` | 失败 |

---

### 4. 列出所有任务

```
GET /tasks
```

**查询参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
| ------ | ------ | ------ | -------- | ------ |
| `status` | string | 否 | 全部 | 过滤：`pending`、`processing`、`completed`、`failed` |
| `limit` | integer | 否 | `20` | 每页数量，最大 100 |
| `offset` | integer | 否 | `0` | 分页偏移 |

**响应 200:**

```json
{
  "total": 25,
  "limit": 20,
  "offset": 0,
  "tasks": [
    {
      "task_id": "20250330_143000_BV1Gm421W75K",
      "status": "processing",
      "mode": "async",
      "url": "https://www.bilibili.com/video/BV1Gm421W75K",
      "model": "small",
      "created_at": "2025-03-30T14:30:00+08:00",
      "progress": {
        "phase": "transcribing",
        "percent": 60
      }
    },
    {
      "task_id": "20250330_142000_BV1xx",
      "status": "completed",
      "mode": "sync",
      "url": "https://www.bilibili.com/video/BV1xx",
      "model": "small",
      "created_at": "2025-03-30T14:20:00+08:00",
      "completed_at": "2025-03-30T14:20:05+08:00",
      "progress": {
        "phase": "completed",
        "percent": 100
      }
    }
  ]
}
```

---

### 5. 获取视频信息（不转录）

```
GET /video/info
```

**查询参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `url` | string | 是 | B 站视频链接或 BV 号 |

**响应 200:**

```json
{
  "bvid": "BV1Gm421W75K",
  "title": "赘X的白金作者直播课",
  "author": "作者名",
  "duration": 1530,
  "duration_formatted": "25:30",
  "cover": "https://i0.hdslb.com/bfs/archive/xxx.jpg",
  "description": "视频简介...",
  "total_pages": 1,
  "pages": [
    {
      "page": 1,
      "part": "正片",
      "cid": 123456789
    }
  ],
  "has_subtitle": true,
  "subtitle_languages": ["zh-Hans", "en"]
}
```

---

## 错误处理

所有错误统一返回 JSON 格式：

```json
{
  "error": "error_code",
  "message": "人类可读的错误描述",
  "details": {}
}
```

| HTTP 状态码 | error_code | 说明 |
| ------------- | ----------- | ------ |
| 400 | `invalid_url` | URL 格式无效或无法解析 |
| 400 | `invalid_model` | 模型名称无效 |
| 400 | `invalid_page` | 分 P 序号超出范围 |
| 400 | `invalid_format` | 输出格式无效 |
| 404 | `task_not_found` | 任务 ID 不存在 |
| 404 | `video_not_found` | 视频不存在或已删除 |
| 429 | `rate_limited` | 请求过于频繁 |
| 500 | `internal_error` | 服务器内部错误 |
| 503 | `model_not_loaded` | Whisper 模型加载失败 |
| 504 | `transcription_timeout` | 转录超时 |

---

## 任务生命周期

```
         ┌──────────────┐
         │   pending    │  ← 任务刚提交，排队等待
         └──────┬───────┘
                │
         ┌──────▼───────┐
         │  processing  │  ← 正在处理中
         └──────┬───────┘
                │
          ┌─────┴─────┐
          │           │
          ▼           ▼
      ┌──────┐   ┌──────┐
      │ done │   │ fail │
      └──────┘   └──────┘
```

---

## 同步 vs 异步模式选择策略

| 条件 | 模式 | 说明 |
| ------ | ------ | ------ |
| 有 CC/AI 字幕 | 同步 | 秒出，直接返回 JSON |
| 强制 `mode=subtitle` | 同步 | 仅字幕，必然秒出 |
| 强制 `mode=whisper` | 异步 | 返回 202，task_id 轮询 |
| Whisper 模型 small 以下 | 同步 | 快速模型可等待 |
| Whisper 模型 medium 以上 | 异步 | 重型模型必须异步 |
| 提供了 `webhook` | 异步 | 显式要求异步回调 |

---

## 速率限制

```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 58
X-RateLimit-Reset: 1680163200
```

| 限制项 | 上限 | 窗口 |
| -------- | ------ | ------ |
| 每分钟请求数 | 60 | 1 分钟 |
| 同时运行的任务数 | 1 | — |
| 排队任务数 | 100 | — |
| 单个任务超时 | 6 小时 | — |

---

## Webhook 回调

异步任务完成后，如果请求时提供了 `webhook` 参数，服务器会向该 URL 发送 POST 请求：

```json
{
  "event": "transcription.completed",
  "task_id": "20250330_143000_BV1Gm421W75K",
  "status": "completed",
  "result": {
    "bvid": "BV1Gm421W75K",
    "title": "视频标题",
    "source": "whisper",
    "entries": 120,
    "full_text": "..."
  },
  "usage": {
    "model": "small",
    "duration_seconds": 930
  }
}
```

失败时也会回调：

```json
{
  "event": "transcription.failed",
  "task_id": "20250330_143000_BV1Gm421W75K",
  "status": "failed",
  "error": "download_failed",
  "message": "音频下载失败"
}
```

---

## 技术选型建议

| 组件 | 推荐 | 原因 |
| ------ | ------ | ------ |
| Web 框架 | **FastAPI** | 异步支持好，自动生成 OpenAPI 文档，类型校验 |
| ASGI 服务器 | **Uvicorn** | 与 FastAPI 原生配套 |
| 任务队列 | 内存队列（单进程） | 简单可靠，避免外部依赖 |
| 持久化 | SQLite + 文件系统 | 零配置，任务状态 + 音频/文稿存储 |
| API 文档 | 自动生成 (Swagger/ReDoc) | FastAPI 内置 |

---

## 项目目录结构

```
bilibili-transcript/
├── api/                       # API 服务目录（新增）
│   ├── __init__.py
│   ├── server.py              # FastAPI 应用入口
│   ├── models.py              # Pydantic 数据模型
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── transcribe.py      # 转录接口
│   │   ├── tasks.py            # 任务管理接口
│   │   └── health.py          # 健康检查
│   ├── queue.py               # 任务队列
│   ├── worker.py              # 转录工作者
│   └── storage.py             # 任务状态持久化
├── fetch_transcript.py        # 核心转录逻辑（不变）
├── download_audio.py          # 音频下载（不变）
└── ...
```

## 启动方式

```bash
# 安装依赖
pip install fastapi uvicorn

# 启动 API 服务
uvicorn api.server:app --host 0.0.0.0 --port 8000

# 或通过项目脚本
./api.sh start
./api.sh stop
./api.sh status
```

---

## 示例用法

### 快速转录（同步，秒出）

```bash
curl -s -X POST http://localhost:8000/api/v1/transcribe \
  -H "Content-Type: application/json" \
  -d '{"url": "BV1Gm421W75K"}' | jq .
```

### 强制 Whisper（异步，轮询）

```bash
# 提交任务
TASK_ID=$(curl -s -X POST http://localhost:8000/api/v1/transcribe \
  -H "Content-Type: application/json" \
  -d '{"url": "BV1Gm421W75K", "mode": "whisper", "model": "small"}' | jq -r '.task_id')

# 轮询结果
while true; do
  STATUS=$(curl -s http://localhost:8000/api/v1/transcribe/$TASK_ID | jq -r '.status')
  echo "状态: $STATUS"
  [ "$STATUS" = "completed" ] && break
  [ "$STATUS" = "failed" ] && break
  sleep 10
done

# 获取结果
curl -s http://localhost:8000/api/v1/transcribe/$TASK_ID | jq '.result.full_text'
```

### 异步 + Webhook

```bash
curl -X POST http://localhost:8000/api/v1/transcribe \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.bilibili.com/video/BV1Gm421W75K",
    "mode": "whisper",
    "model": "medium",
    "webhook": "https://my-server/bilibili-callback"
  }'
```

### 只查视频信息

```bash
curl -s "http://localhost:8000/api/v1/video/info?url=BV1Gm421W75K" | jq .
```
