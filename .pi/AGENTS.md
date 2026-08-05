# Bilibili Transcript — Pi Agent 配置

## 项目概述

B 站视频字幕提取 + Whisper 本地语音转录工具。支持 CC 字幕、AI 字幕、Whisper 本地转录三级降级策略。

## 项目架构

项目按 **核心引擎 → 使用方式** 分层组织：

```
bilibili-transcript/
├── src/core/       # 核心引擎 — faster-whisper 封装 + B 站 API 交互
├── cli/            # 命令行工具集 — 持久化队列 + cron 调度
├── src/web/        # FastAPI 服务使用方式 — 异步队列 + 持久化 + Webhook
├── tests/          # 测试套件
└── experiments/    # 实验记录
```

| 层级 | 说明 |
| ------ | ------ |
| `src/core/` | faster-whisper 为核心的转录引擎，B 站 API 封装，三级降级策略 |
| `cli/` | Python 命令行工具，实现持久化队列 + cron 调度 |
| `src/web/` | FastAPI 服务，提供 RESTful HTTP API，支持同步/异步模式 |

## 核心用法

### 持久化队列（推荐）

使用 `bili_queue.py` 管理转录任务，支持 cron 定时调度、自动重试、CPU 感知调度。

```bash
# 添加任务到队列
python3 src/cli/bili_queue.py add "BV1xxx"

# 查看队列状态
python3 src/cli/bili_queue.py status

# 安装 cron 定时调度（每10分钟自动检查）
python3 src/cli/bili_queue.py install-cron

# 列出所有任务
python3 src/cli/bili_queue.py list

# 重试失败任务
python3 src/cli/bili_queue.py retry <task_id>
```

### 直接调用 Python 脚本

```bash
python3 fetch_transcript.py "视频URL" [options]
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
4. **保存结果**：音频 → `out/audio/`，文稿 → `out/transcripts/`

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
# 直接启动（默认端口 8000）
uvicorn src.web.server:app --host 0.0.0.0 --port 8000

# 或使用 Python 模块
python3 -m uvicorn src.web.server:app --host 0.0.0.0 --port 8000
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

### 项目结构

```
bilibili-transcript/
├── src/
│   ├── core/                  # 核心引擎
│   │   ├── transcriber.py     #   faster-whisper + B站 API + CLI 入口
│   │   └── download_audio.py  #   批量音频下载
│   ├── cli/                   # 命令行工具
│   │   ├── __init__.py
│   │   └── bili_queue.py       #   持久化队列 + cron 调度
│   └── web/                   # FastAPI 服务
│       ├── server.py          #   FastAPI 应用入口
│       ├── models.py          #   Pydantic 数据模型
│       ├── queue.py           #   内存任务队列
│       ├── worker.py          #   后台转录工作者
│       ├── storage.py         #   任务持久化 (JSON)
│       └── routes/
│           ├── health.py      #   GET /api/v1/health
│           ├── transcribe.py  #   POST + GET /api/v1/transcribe
│           ├── tasks.py       #   GET /api/v1/tasks
│           └── video.py       #   GET /api/v1/video/info
├── docs/API_DESIGN.md         # 完整接口设计文档
├── fetch_transcript.py        # 兼容入口（委派到 src.core.transcriber）
└── pyproject.toml             # 依赖定义（uv）
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
