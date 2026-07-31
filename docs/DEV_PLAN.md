# Bilibili Transcript API 开发计划

## 分支

```
feat/api-transcribe
```

基于 `feat/agents-config` 创建，所有提交都在此分支上完成。完成后 PR 合并回 `main`。

## 提交计划

### Commit 1: 项目骨架 + 依赖安装

```
chore(api): 初始化 API 项目结构和依赖

- 安装 fastapi, uvicorn, pydantic
- 创建 api/ 目录结构
- 创建 api/__init__.py
- 创建 api/server.py（最小 FastAPI 应用，仅返回 {"status": "ok"}）
- 添加 requirements-api.txt
```

**验收标准：** `uvicorn api.server:app` 启动成功，`curl localhost:8000` 返回 200。

---

### Commit 2: Pydantic 数据模型

```
feat(api): 定义请求和响应的 Pydantic 数据模型

- api/models.py: 所有请求体/响应体模型
  - TranscribeRequest: url, mode, model, language, page, output_format, cookie, webhook
  - TranscribeResponse: 同步/异步响应
  - TaskStatusResponse: 任务状态查询结果
  - TaskListResponse: 任务列表
  - VideoInfoResponse: 视频信息
  - HealthResponse: 健康检查
  - ErrorResponse: 统一错误
  - ProgressInfo: 进度信息
  - UsageInfo: 用量信息
  - SubtitleEntry: 字幕条目
```

**验收标准：** 模型定义完整，类型校验正确。

---

### Commit 3: In-memory 任务队列

```
feat(api): 实现内存任务队列

- api/queue.py:
  - TaskQueue 类，线程安全
  - 支持 enqueue / dequeue / peek / list / status 操作
  - 任务状态机: pending → processing → completed / failed
  - 任务去重（相同 BV 只允许一个 pending）
  - 最大排队数限制
  - 任务超时检测
```

**验收标准：** 单元测试覆盖队列的 enqueue/dequeue/status 转换。

---

### Commit 4: 任务存储层

```
feat(api): 实现任务持久化存储

- api/storage.py:
  - 基于 JSON 文件的任务存储
  - 每次状态变更写入 ~/.bilibili-api/tasks/<task_id>.json
  - 启动时恢复未完成的任务
  - 存储字段: task_id, status, url, model, request, result, progress, timestamps
```

**验收标准：** 创建任务后文件写入磁盘，重启后已完成的 task 可恢复查询。

---

### Commit 5: 后台转录工作者

```
feat(api): 实现后台转录工作者

- api/worker.py:
  - Worker 类，后台线程运行
  - 从队列取任务，调用 fetch_transcript.py 的核心逻辑
  - 更新任务进度（下载中 / 加载模型 / 转录中 / 完成）
  - 捕获异常，标记失败
  - 单工作者模式（避免 Whisper 多实例冲突）
  - 支持优雅退出
```

**验收标准：** 提交一个 B 站 URL 后，工作者能自动完成转录并标记完成。

---

### Commit 6: 健康检查接口

```
feat(api): 实现 GET /api/v1/health

- api/routes/health.py:
  - 检查工作者线程状态
  - 检查磁盘空间
  - 检查 B 站 API 可达性
  - 返回队列统计数据
  - 全部正常 → 200，任意异常 → 503
  - 挂载到 server.py
```

**验收标准：** `curl /api/v1/health` 返回 200 JSON，包含队列统计和组件状态。

---

### Commit 7: 视频信息接口

```
feat(api): 实现 GET /api/v1/video/info

- api/routes/video.py:
  - 解析 URL → BV ID
  - 调用 B 站 API 获取视频元数据
  - 检查字幕可用性
  - 返回结构化视频信息
  - 错误处理（无效 URL / 视频不存在）
```

**验收标准：** `curl "/api/v1/video/info?url=BV1xxx"` 返回标题、时长、分 P 列表。

---

### Commit 8: 提交转录任务接口（同步模式）

```
feat(api): 实现 POST /api/v1/transcribe（同步模式）

- api/routes/transcribe.py:
  - 同步分支：有字幕时秒出结果
  - 参数校验（url, model, page 等）
  - 复用 fetch_transcript.py 的 extract_bvid / get_cid / get_subtitle_url
  - 返回统一格式的 TranscribeResponse
  - 自动选择同步/异步（见设计文档的策略表）
```

**验收标准：** 有字幕的视频 POST 后直接返回 200 + 完整字幕结果。

---

### Commit 9: 提交转录任务接口（异步模式）

```
feat(api): 实现 POST /api/v1/transcribe（异步模式）

- api/routes/transcribe.py（续）:
  - 异步分支：入队后返回 202 + task_id
  - 支持 mode=whisper 强制异步
  - 支持 webhook 参数
  - 大型模型（medium+）自动走异步
```

**验收标准：** `mode=whisper` 时返回 202，task_id 可用于后续轮询。

---

### Commit 10: 查询任务状态接口

```
feat(api): 实现 GET /api/v1/transcribe/:task_id

- api/routes/transcribe.py（续）:
  - 查任务状态返回详细进度
  - 已完成返回完整结果
  - 处理中返回进度 phase + percent
  - 任务不存在 → 404
```

**验收标准：** 异步提交后轮询此接口，最终返回 completed 结果。

---

### Commit 11: 任务列表接口

```
feat(api): 实现 GET /api/v1/tasks

- api/routes/tasks.py:
  - 支持 status 过滤（pending/processing/completed/failed）
  - 支持 limit/offset 分页
  - 返回任务摘要列表，不含完整字幕内容
  - 按创建时间倒序
```

**验收标准：** `curl "/api/v1/tasks?status=completed&limit=5"` 返回正确分页结果。

---

### Commit 12: Webhook 回调

```
feat(api): 实现异步任务完成后的 Webhook 回调

- api/worker.py（增强）:
  - 任务完成后，如果请求有 webhook 参数，POST 结果到该 URL
  - 失败时也回调
  - 超时重试 3 次
  - 非阻塞（异步 HTTP 请求）
```

**验收标准：** 提供 webhook 参数的异步任务，完成后目标 URL 收到回调。

---

### Commit 13: 启动脚本 + README 更新

```
docs(api): 添加 API 启动脚本和 README 文档

- api.sh: start / stop / status / restart / logs 命令（**已移除，改用 uvicorn 直接启动**）
- README.md: 新增 API 使用章节
- 包括 curl 示例
- 包括环境变量说明
```

**验收标准：** `uvicorn src.web.server:app` 启动服务。

> **注：** `api.sh` 已于后续清理中移除，仅保留 `bili_queue.sh` 作为 Shell 脚本入口。API 服务直接通过 `uvicorn src.web.server:app --host 0.0.0.0 --port 8000` 启动。

---

## 提交顺序总览

| # | 提交类型 | 内容 | 依赖 |
| --- | --------- | ------ | ------ |
| 1 | chore | 项目骨架 + 依赖 | — |
| 2 | feat | 数据模型 | 1 |
| 3 | feat | 任务队列 | 2 |
| 4 | feat | 任务存储 | 3 |
| 5 | feat | 后台工作者 | 3, 4 |
| 6 | feat | 健康检查接口 | 5 |
| 7 | feat | 视频信息接口 | 1 |
| 8 | feat | 提交转录（同步） | 2, 5 |
| 9 | feat | 提交转录（异步） | 5, 8 |
| 10 | feat | 查询任务状态 | 5, 9 |
| 11 | feat | 任务列表 | 3 |
| 12 | feat | Webhook 回调 | 5, 9 |
| 13 | docs | 启动脚本 + README | 全部 |

## 项目最终目录结构

```
bilibili-transcript/
├── api/
│   ├── __init__.py
│   ├── server.py          # FastAPI 应用入口，路由注册
│   ├── models.py          # Pydantic 数据模型
│   ├── queue.py           # 内存任务队列
│   ├── storage.py         # 任务持久化
│   ├── worker.py          # 后台转录工作者
│   └── routes/
│       ├── __init__.py
│       ├── health.py      # GET /api/v1/health
│       ├── transcribe.py  # POST /api/v1/transcribe + GET /api/v1/transcribe/:id
│       ├── tasks.py       # GET /api/v1/tasks
│       └── video.py       # GET /api/v1/video/info
├── fetch_transcript.py    # 核心转录（不变）
├── download_audio.py      # 批量下载音频（不变）
├── api.sh                 # 启动脚本（已移除，改用 uvicorn 直接启动）
├── API_DESIGN.md          # 接口设计文档
├── DEV_PLAN.md            # 本开发计划
└── requirements-api.txt   # API 依赖（新增）
```

## 测试策略

- 每个提交后手动验证验收标准
- 最终阶段用真实 B 站 URL 全链路测试
- 测试场景：
  - 有字幕的视频同步返回
  - 无字幕的视频异步 Whisper 转录
  - 无效 URL 返回 400
  - 不存在的 task_id 返回 404
  - Webhook 回调送达
