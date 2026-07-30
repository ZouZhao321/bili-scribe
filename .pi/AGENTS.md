# Bilibili Transcript — Pi Agent 配置

## 项目概述

B 站视频字幕提取 + Whisper 本地语音转录工具。支持 CC 字幕、AI 字幕、Whisper 本地转录三级降级策略。

## 默认工作流

**所有下载和转录操作默认使用 `bili_save.sh` 保存模式**，即自动保存音频、文稿和视频链接信息到 `~/bilibili-output/` 目录。

### 核心命令

```bash
# 后台队列模式：自动排队，可同时提交多个（推荐）
./bili_bg.sh "视频URL1" "视频URL2" ... [model]

# 默认流程：下载 + 转录 + 保存（前台运行）
./bili_save.sh "视频URL" [model]

# 快速查看（不保存文件）
./bili.sh "视频URL" [model]

# 直接调用 Python 脚本
python3 fetch_transcript.py "视频URL" [options]
```

### 队列管理

```bash
# 查看队列状态（运行中/已完成/失败）
./bili_bg.sh --status

# 查看某个任务的详细日志
./bili_bg.sh --log <task_id>

# 从文件批量提交（每行一个URL）
./bili_bg.sh urls.txt [model]
```

### 输出目录结构

```
~/bilibili-output/
├── {BV号}_{适配名字}/
│   ├── 转录文稿.txt          # 原始转录文本
│   └── 适配分析.md           # 内容分析总结
├── audio/                    # 音频文件（旧格式）
└── transcripts/              # 文稿文件（旧格式）
```

### 模型选择

| 模型 | 大小 | 速度 | 质量 | 适用场景 |
| ------ | ------ | ------ | ------ | --------- |
| tiny | 75MB | ~1x | 一般 | 快速预览 |
| base | 141MB | ~1.5x | 可用 | 短视频 |
| small | 464MB | ~3x | 较好 | **日常使用（默认）** |
| medium | 1.5GB | ~8x | 好 | 重要内容 |
| large-v3 | 3.1GB | ~15x | 最好 | 最高精度 |

## 转录流程说明

1. **解析视频链接** — 支持 BV 号、av 号、短链接 (b23.tv)
2. **获取视频信息** — 标题、作者、时长
3. **三级降级获取字幕**：
   - 第 1 级：CC 字幕（UP 主上传）— 秒出
   - 第 2 级：AI 字幕（B 站自动生成）— 秒出
   - 第 3 级：Whisper 本地转录（CPU）— 较慢但最可靠
4. **保存结果**：音频 → `~/bilibili-output/audio/`，文稿 → `~/bilibili-output/transcripts/`

## 常见操作

### 后台排队转录（推荐）

```bash
# 单个视频后台运行
./bili_bg.sh "https://www.bilibili.com/video/BV1xxx"

# 多个视频自动排队
./bili_bg.sh "BV1xxx" "BV2xxx" "BV3xxx"

# 从文件批量提交
./bili_bg.sh urls.txt small

# 查看队列状态
./bili_bg.sh --status

# 查看任务日志
./bili_bg.sh --log BV1xxx_1234567890
```

### 下载并转录视频（前台）

```bash
./bili_save.sh "https://www.bilibili.com/video/BV1xxx"
./bili_save.sh "BV1xxx" tiny    # 快速
./bili_save.sh "BV1xxx" small   # 默认
./bili_save.sh "BV1xxx" medium  # 高质量
```

### 仅查看文稿（不保存）

```bash
./bili.sh "BV1xxx"
./bili.sh "BV1xxx" --timestamps  # 带时间戳
```

### JSON 格式输出

```bash
python3 fetch_transcript.py "BV1xxx" --json
```

## 注意事项

- Whisper 转录需要 CPU 资源，2 核 CPU 转录 10 分钟视频约需 6 分钟
- 首次使用 small 以上模型会自动下载模型文件
- 输出目录 `~/bilibili-output/` 由脚本自动创建
- 虚拟环境 Python 路径：`/opt/data/.venv-whisper/bin/python3`

## Whisper 内存管理

### 模型加载机制

faster-whisper 基于 CTranslate2，使用 **mmap（内存映射文件）** 加载模型：

```python
self.model = ctranslate2.models.Whisper(model_path, device="cpu", compute_type="int8")
```

- 模型文件 **不是** 一次性全部读入物理内存（RSS）
- 而是映射到 **虚拟地址空间**，按需按页加载到物理内存
- 物理内存不够时，OS 自动将不常用的权重页换出到 Swap

### 音频处理

```python
audio = decode_audio(audio, sampling_rate=sampling_rate)           # 整个音频
features = self.feature_extractor(audio, chunk_length=chunk_length) # 整个转特征
segments = self.generate_segments(features, ...)                    # 30秒窗口分段处理
```

- 音频是 **全部加载到内存**，不是流式读取
- 但 5 分钟音频的特征仅 ~5MB，占比极小
- 长视频（1小时）特征约 60MB，依然不是瓶颈

### 内存瓶颈

| 模型 | 磁盘大小 | 虚拟内存映射 | 实际物理内存需求 |
| ------ | :-------: | :----------: | :--------------: |
| tiny | 75MB | ~75MB | ~75MB |
| small | 464MB | ~464MB | ~464MB |
| medium | 1.5GB | ~1.5GB | ~1.5GB |
| large-v3 | 2.9GB | ~2.9GB | ~2.9GB |

**模型权重是内存占用的绝对大头**，音频特征占比可忽略。

### 卡死原因分析

系统配置：3.6GB RAM，云服务器（腾讯云），运行 VS Code Server + Gitea + n8n + Docker 等

| 状态 | 可用 RAM | Swap | 结果 |
| ------ | :-------: | :----: | :----: |
| 默认（Swap 1.9GB） | ~700MB | 被占满 | ❌ medium/large-v3 卡死 |
| 加大 Swap 到 4GB | ~700MB | 有 2GB+ 空闲 | ✅ large-v3 正常完成 |

**卡死的根本原因不是模型太大，而是 Swap 太小。**

当物理内存不足时：

1. OS 需要将不常用的模型权重页换出到 Swap
2. 如果 Swap 已满 → 无法换出 → 内存分配失败
3. 系统进入 **thrashing（抖动）** 状态：反复尝试换页，I/O 占满
4. 所有进程（包括 SSH）都得不到响应 → 卡死

### 验证结论

- 加大 Swap 到 **4GB** 后，large-v3（2.9GB）稳定运行，系统全程响应正常
- 转录结束后可用内存恢复到 2.5GB+，Swap 使用约 2GB
- 模型使用 mmap 映射，不是流式加载；音频也不是流式处理
- **能稳定运行不是因为音频短（5分钟），而是 Swap 足够大**
- 即使换 1 小时长视频，同样能稳定运行（音频特征仅 ~60MB）

---

## HTTP API 服务

项目提供 RESTful API，通过 HTTP 调用转录功能。

### 启动服务

```bash
# 后台启动（默认端口 8000）
./script/api.sh start

# 查看服务状态
./script/api.sh status

# 查看实时日志
./script/api.sh logs

# 停止服务
./script/api.sh stop

# 自定义端口
API_PORT=8080 ./script/api.sh start
```

启动后访问 `http://localhost:8000/docs` 查看交互式 API 文档（Swagger UI）。

### 接口列表

| 方法 | 路径 | 说明 |
| ------ | ------ | ------ |
| `GET` | `/api/v1/health` | 健康检查 + 队列状态 + 组件检查 |
| `POST` | `/api/v1/transcribe` | 提交转录任务（同步秒出或异步 202） |
| `GET` | `/api/v1/transcribe/:task_id` | 查询任务状态和结果 |
| `GET` | `/api/v1/tasks` | 列出所有任务（分页/过滤） |
| `GET` | `/api/v1/video/info` | 查询视频信息（不转录） |

### 常用 API 调用

```bash
# 快速转录（有字幕秒出）
curl -X POST http://localhost:8000/api/v1/transcribe \
  -H "Content-Type: application/json" \
  -d '{"url": "BV1Gm421W75K"}'

# 强制 Whisper 转录（异步，返回 task_id）
curl -X POST http://localhost:8000/api/v1/transcribe \
  -H "Content-Type: application/json" \
  -d '{"url": "BV1Gm421W75K", "mode": "whisper", "model": "tiny"}'

# 轮询异步任务结果
curl http://localhost:8000/api/v1/transcribe/<task_id>

# 查询视频信息（不转录）
curl "http://localhost:8000/api/v1/video/info?url=BV1Gm421W75K"

# 健康检查
curl http://localhost:8000/api/v1/health
```

### 请求参数说明

```json
{
  "url": "BV1Gm421W75K",           // 必填，支持 BV/av/b23.tv
  "mode": "auto",                   // auto / subtitle / whisper / both
  "model": "small",                 // tiny / base / small / medium / large-v3
  "language": "zh",                 // Whisper 语言提示
  "page": 0,                         // 分 P 序号
  "output_format": "text",          // text / timestamps / json
  "webhook": "https://..."          // 异步完成回调（可选）
}
```

### 同步 vs 异步策略

| 条件 | 模式 | HTTP 状态码 |
| ------ | ------ | ----------- |
| 有 CC/AI 字幕 | 同步 | 200，立即返回结果 |
| 强制 `mode=whisper` | 异步 | 202，返回 task_id |
| 模型 medium 以上 | 异步 | 202，返回 task_id |
| 提供了 webhook | 异步 | 202，返回 task_id |

### 任务状态轮询

异步提交后，通过 `GET /api/v1/transcribe/:task_id` 轮询：

```json
// 处理中
{
  "status": "processing",
  "progress": {
    "phase": "downloading_audio",
    "percent": 50,
    "message": "正在下载音频流..."
  }
}

// 已完成
{
  "status": "completed",
  "result": {
    "bvid": "BV1xxx",
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

### 项目结构（API 相关）

```
bilibili-transcript/
├── api/                       # API 服务代码
│   ├── server.py              # FastAPI 应用入口
│   ├── models.py              # Pydantic 数据模型
│   ├── queue.py               # 内存任务队列
│   ├── storage.py             # 任务持久化 (JSON)
│   ├── worker.py              # 后台转录工作者
│   └── routes/
│       ├── health.py          # GET /api/v1/health
│       ├── transcribe.py      # POST + GET /api/v1/transcribe
│       ├── tasks.py           # GET /api/v1/tasks
│       └── video.py           # GET /api/v1/video/info
├── script/api.sh              # API 服务管理脚本
├── docs/API_DESIGN.md         # 完整接口设计文档
└── pyproject.toml             # 依赖定义（uv）
```

### 依赖安装

```bash
# 使用 uv 安装所有依赖（包含 API）
uv venv
uv pip install -e .
```

---

## 实验记录

Whisper 内存压力测试等实验记录保存在 `experiments/` 目录：

```bash
# 查看所有实验
ls experiments/

# 运行某个实验的验证脚本
bash experiments/2026-07-30_whisper-memory-benchmark/verify.sh check
```

详见 [experiments/README.md](../experiments/README.md)
