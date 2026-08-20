# bili-scribe — Pi Agent 配置

项目概述：B 站视频字幕提取 + Whisper 本地语音转录工具，三级降级策略。

> 本项目设计为 **Agent 间接使用**：用户通过 Pi Agent 下达指令，Agent 通过 HTTP API / CLI 完成转录、队列管理等操作。用户不直接操作 CLI，也不直接调用内部 API。

## 架构现状（2026-08 迁移后）

> **以 HTTP API + Worker 为主**。`src/web/` 是当前主架构：FastAPI 服务 + 后台 Worker + SPA 前端。
> CLI 的 `transcribe` / `batch` 为**同步直跑不入队**；队列调度已迁移到 Worker（30s 轮询 + CPU/内存感知自调度），`queue`、`cron` 命令已废弃/删除。

| 操作 | 入口 |
| ------ | ------ |
| 提交转录任务（入队） | `POST /api/v1/transcribe` |
| 查看服务状态 | `GET /api/v1/health` |
| 列出任务 | `GET /api/v1/tasks` |
| 查询单个任务 | `GET /api/v1/transcribe/{task_id}` |
| 重试任务 | `POST /api/v1/tasks/{task_id}/retry` |
| 删除任务 | `DELETE /api/v1/tasks/{task_id}` |
| 取消任务 | `POST /api/v1/tasks/{task_id}/cancel` |
| 启动服务 | `bili-scribe serve` |
| 前端 SPA | `http://localhost:8000` |
| API 文档 | `http://localhost:8000/docs` |

## 约束规则

- **GitHub 推送**：经 git 已配置的代理直连（无需额外操作）
- **凭证管理**：本地开发默认免密（`BILI_SCRIBE_PASSWORD` 为空则 serve 跳过 auth）；生产环境通过环境变量设置密码
- **API 调用规范**：禁止直接调用内部 API（如 `TaskStore.add()`、`queue_store` 等）。必须通过 HTTP API（`POST /api/v1/transcribe` 等）或封装后的 CLI 命令提交任务
- **Git Worktree**：所有 git worktree 必须放在 `.worktree/` 目录下，禁止在其他位置创建。命名格式：`.worktree/<分支名>`（斜杠替换为短横线，如 `feat/docker-frontend` → `.worktree/feat-docker-frontend`）

## 用户偏好（默认值）

| 偏好项 | 默认值 | 说明 |
| -------- | :------: | ------ |
| 转录模型 | **base** | 非 small |
| 合集链接 | 全部入队 | 通过 HTTP API 逐个入队，由 Worker 调度 |
| 单个视频 | 默认入队 | 同上 |
| 回复语言 | 中文 | 所有回复使用中文 |

## 标准化动作

### 收到 B 站链接 → 转录

1. 解析 URL → 提取 BV ID
2. 检查 `out/` 目录是否已有该 BV 的转录结果
3. 如有 → 展示已有文稿路径
4. 如无 → 确认 `serve` 服务在运行，通过 `POST /api/v1/transcribe` 入队（base 模型）
5. 输出队列状态（`GET /api/v1/tasks`）

### 收到合集链接 → 批量下载

1. 解析合集 URL → 获取合集内所有视频 BV 号
2. 全部视频通过 `POST /api/v1/transcribe` 逐个入队
3. 默认使用 base 模型

### 收到状态查询

1. 先读 `docs/agents/cli.md` 确认命令
2. 确认 `serve` 服务在运行，调用 `GET /api/v1/tasks`（或 `GET /api/v1/health`）
3. 展示结果

### 创建并行开发环境（Git Worktree）

1. `git worktree add .worktree/<分支名> -b <新分支名>`（已有分支不加 `-b`）
2. 在 worktree 中初始化环境
3. 后续在该 worktree 中开发，与原工作区完全隔离（各自拥有独立的依赖、`out/`、未提交修改）

## 项目目录结构

> 仅记录目录，文件易变不在此列。

| 目录 | 作用 |
| ------ | ------ |
| `src/core/` | 核心引擎：B 站 API 交互、Whisper 转录、队列持久化 |
| `src/cli/` | CLI 命令行入口，`bili-scribe` 多子命令实现 |
| `src/web/` | 当前主架构：HTTP API 服务 + Worker 调度 + SPA 前端 |
| `tests/` | 测试套件（pytest） |
| `docs/` | 项目文档入口 |
| `docs/agents/` | Pi Agent 操作文档：架构、CLI、工作流、调度、输出、内存 |
| `docs/adr/` | 架构决策记录（ADR） |
| `docs/experiments/` | Whisper 实验记录，每个实验独立子目录 |
| `docs/plan/` | 规划文档 |
| `script/` | 辅助脚本：推送中转、输出迁移、作者映射 |
| `out/` | 转录结果输出，每个视频一个子目录 `{BV号}_{标题}/` |
| `notes/` | 卡片盒子笔记，按日期命名 |
| `.pi/` | Pi 代理配置：settings.json、扩展、npm 包、会话记忆 |
| `.agents/` | Pi Agent skills 技能定义 |
| `.worktree/` | Git worktree 隔离目录，每个子目录对应一个分支的独立工作区 |

## 工具使用规则

- **bili-scribe 命令**：必须通过项目的 CLI 入口执行（如 `python -m src.cli.main`），系统 PATH 中无此命令
- **服务运行**：调用 HTTP API 前，先确认 `bili-scribe serve` 在运行

## 文档索引（必读规则）

> 只要有任何相关性（哪怕 1%），必须先阅读对应文档，再执行操作。

| 关键词 | 入口 | 说明 |
| -------- | ------ | ------ |
| 架构、目录结构、核心引擎、分层 | `docs/agents/architecture.md` | 项目代码布局 |
| CLI 命令、队列管理、模型选择 | `docs/agents/cli.md` | 命令用法、参数说明 |
| 转录流程、降级策略、注意事项 | `docs/agents/workflow.md` | 转录流程与环境配置 |
| 调度策略、CPU 感知、内存需求 | `docs/agents/scheduling.md` | Worker 调度规则 |
| 输出目录、out、文件结构 | `docs/agents/output.md` | 转录结果存放位置 |
| 内存管理、mmap、Swap、卡死分析 | `docs/agents/memory.md` | Whisper 内存排查 |
| 并行开发、worktree、隔离 | `docs/agents/worktree.md` | Git worktree 并行开发规范 |
| ADR、架构决策、决策记录、技术选型 | `docs/adr/README.md` | 架构决策记录 |
| 会话记忆、历史决策、排查记录 | `.pi/memory/README.md` | 历史记忆 |
