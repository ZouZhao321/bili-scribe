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

使用 `bili_queue.py` 管理转录任务，支持 cron 定时调度、自动重试、CPU 感知调度 + 内存感知调度。

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

---

## 当前任务队列（2026-08-01）

已添加 27 个 B 站网文写作教学视频到队列，全部使用 `medium` 模型转录。

### 当前任务列表

| # | BVID | 描述 | 模型 |
| --- | ------ | ------ | ------ |
| 1 | BV15N4y1H7vd | 手把手教你写细纲，四行字细纲写法 | medium |
| 2 | BV1nYDWYKEc3 | 把网文写成填空题（网文大纲模板） | medium |
| 3 | BV1d34y1b7og | 手把手做小说大纲示范 | medium |
| 4 | BV1cMnEzpEc2 | 小说教学：怎么拆书，拆什么？ | medium |
| 5 | BV1t1Z4YgEWV | 白特慢啊：干货：如何做好剧情循环 | medium |
| 6 | BV1cz4y1q73f | 徐善良拆书《大奉打更人》 | medium |
| 7 | BV1ma4y1J7tY | 飞羽教你写网文【细纲拓展练习】 | medium |
| 8 | BV1op4y1g7UA | 细纲应该写多少字？细纲应该怎么写？ | medium |
| 9 | BV1mFc1eeEmJ | 小说作者日更万字的秘密——情节细纲 | medium |
| 10 | BV1YuTG6gEN4 | 万订干货：关于大纲的一切（一） | medium |
| 11 | BV11N41117iU | 网文大纲细纲支线设计思路 | medium |
| 12 | BV1hLfdBdEC1 | 将脑洞变成小说，小说大纲构思流程分享 | medium |
| 13 | BV11Z4y1H7ra | 老网文作者是如何做细纲的 | medium |
| 14 | BV1nbKP6hE45 | 万订干货：关于大纲的一切（二） | medium |
| 15 | BV1hBZbYXE7H | 蜜汁姬：如何从灵感构建完整故事主线框架 | medium |
| 16 | BV1UqCWB4EmG | 天蚕土豆教怎么写小说 | medium |
| 17 | BV1HC4y1V7ir | 新人作者必学技能：细纲实操 | medium |
| 18 | BV18zwXzWEmV | 如何写小说大纲 | medium |
| 19 | BV12L411i7km | 除了手速，细纲还有这些妙用 | medium |
| 20 | BV1yg411h7zy | 干货\| 大纲怎么写？ | medium |
| 21 | BV1tE411f7wZ | 从零开始的小说创作课程-03 | medium |
| 22 | BV1X44y1k7H4 | 从灵感到网文大纲/卷纲/章纲硬核构建全过程 | medium |
| 23 | BV12bKH6sE7c | 放弃边写边改！细纲+分段写作+存稿缓冲 | medium |
| 24 | BV1TxJhzvEtx | 新人写小说 三种大纲细纲的构建办法 | medium |
| 25 | BV1GnFyeMEPR | 什么是小纲？有啥用？怎么练？ | medium |
| 26 | BV1LG3p6XEPA | 什么是小说核心，什么是小说卖点 | medium |
| 27 | BV1uo3z6oE35 | 最适合网文新人的拆书模板，一本书搞定签约 | medium |

### 队列管理命令

```bash
# 查看队列状态（统计 + CPU 负载）
python3 src/cli/bili_queue.py status

# 列出所有待处理任务
python3 src/cli/bili_queue.py list

# 列出指定状态的任务
python3 src/cli/bili_queue.py list pending     # 待处理
python3 src/cli/bili_queue.py list running     # 运行中
python3 src/cli/bili_queue.py list done        # 已完成
python3 src/cli/bili_queue.py list failed      # 失败

# 重试失败任务
python3 src/cli/bili_queue.py retry <task_id>

# 删除任务
python3 src/cli/bili_queue.py remove <task_id>

# 取消当前运行的任务
python3 src/cli/bili_queue.py cancel

# 清空队列
python3 src/cli/bili_queue.py clear            # 交互式确认
python3 src/cli/bili_queue.py clear pending    # 清空待处理
python3 src/cli/bili_queue.py clear failed     # 清空失败
```

### 调度策略

- **CPU 感知**：CPU 使用率 < 50% 时自动取任务执行
- **内存感知**：可用内存 ≥ 模型需求的 90% 时才执行，避免 OOM
- **cron 触发**：每 10 分钟检查一次队列
- **自动重试**：失败最多重试 3 次
- **超时保护**：任务运行超过 6 小时视为僵死，放回队列重试

### 模型内存需求（队列调度用）

| 模型 | 最小可用内存 | 说明 |
| ------ | ------------- | ------ |
| tiny | 500 MB | 75MB 模型 + 开销 |
| base | 1.0 GB | 141MB 模型 + 开销 |
| small | 2.0 GB | 464MB 模型 + 开销 |
| medium | 3.5 GB | 1.5GB 模型，RSS ~3GB |
| large-v3 | 5.5 GB | 2.9GB 模型，RSS ~5GB |

### 输出位置

转录完成后，结果保存在项目根目录的 `out/` 下，每个视频一个子目录：

```
out/
├── BV15N4y1H7vd_标题/
│   ├── 视频链接.txt     # 视频元数据
│   ├── 转录文稿.txt     # 转录文本（纯文本）
│   └── audio.m4s        # 下载的音频文件
├── BV1nYDWYKEc3_标题/
│   └── ...  
└── ...
```
