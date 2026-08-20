# AGENTS.md 评审报告

> 评审方式：代码库实测 + grilling 访谈（一次一分叉，已锁定 6 个决定）。
> 日期：2026-08-13（代码库最新提交同日）。

## 结论

**AGENTS.md 已严重脱节**：它描述的是 8-13 架构迁移**之前**的状态。8-13 的提交把整套架构从「CLI + cron + 持久化队列」迁到了「HTTP API + Worker + SPA 前端」，并废弃/删除了 `queue`、`cron` 命令。AGENTS.md 的约束规则、用户偏好表、标准化动作、目录结构、工具使用规则、文档索引六大部分均与代码现状冲突。

**冲突根源**：`8f899e8 / 1be0a95` — `refactor(cli): 删除 cron 命令，废弃队列子命令`，随后 4 个 PR（`slice-1`~`slice-4`）建成了 HTTP API + Worker。AGENTS.md 没有跟进。

---

## 一、发现的问题（按严重度排序）

### P0 — 架构方向完全相反

- AGENTS.md：「以 CLI 为主」「src/web/ 已停更」
- 代码：`src/web/` 是最近几天最活跃的部分；`queue` 子命令只输出废弃提示就退出（`bili_queue._deprecated`）；`cron` 命令已删除。

### P0 — 标准化动作指向废弃命令

- AGENTS.md 的「收到链接→queue add」「状态查询→queue status」「合集→cron 调度」全部指向已废弃/已删除的命令。
- 代码：`queue add/status/list/...` 均打印 `_DEPRECATION_MSG` 后退出；CLI 的 `transcribe`/`batch` 是**同步直跑不入队**，只有 HTTP `POST /api/v1/transcribe` 才真正入队。

### P1 — 凭证 / 代理配置与现状不符

- AGENTS.md：Git 全局代理指向远端 `43.159.133.219:8888`（tinyproxy），凭证在 `.env` 的 `TINYPROXY_USER/PASS`。
- 实测：本机 git 代理是本地 `127.0.0.1:7897`；**项目里没有 `.env` 文件**（已 gitignore 但不存在）；`TINYPROXY` / `43.159` 仅在 AGENTS.md 出现，代码/文档其他处均无。

### P1 — 偏好表「由 cron 调度」已失效

- AGENTS.md：「合集/单个默认入队，由 cron 调度」
- 代码：cron 已删除；调度改为 Worker 内建（`POLL_INTERVAL = 30.0`，CPU/内存感知，见 `src/web/worker.py`）。

### P2 — 运行命令路径缺失

- AGENTS.md 工具使用规则：`必须通过 .venv/bin/bili-scribe` 执行。
- 实测：本仓库无 `.venv`（`docs/agents/workflow.md:18` 引用的是服务器路径 `/opt/data/.venv-whisper/bin/python3`）。文档命令在本机不可执行。

### P2 — 文档索引缺项

- `docs/agents/worktree.md` 存在但未进「必读规则」表；AGENTS.md 有「创建并行开发环境」章节却无对应索引。

### P2 — API 调用规范自相矛盾

- AGENTS.md：「禁止直接调用内部 API，必须用封装后的 CLI 命令（queue add、batch）」。但 queue add 已废弃，且新架构的「封装入口」其实是 HTTP API。这条约束本身需要重写。

---

## 二、已锁定的决定（grilling 结论）

| # | 分叉 | 决定 | 依据 |
| --- | ------ | ------ | ------ |
| 1 | 主入口 | **HTTP API + Worker 为主** | 代码现状（src/web 活跃、queue/cron 废弃） |
| 2 | 任务提交 | **HTTP 入队为主**：`POST /api/v1/transcribe`，Worker 异步转录 | 唯一真正入队的路径 |
| 3 | API 凭证 | **本地免密**：`BILI_SCRIBE_PASSWORD` 为空时 serve 跳过 auth | auth.py 逻辑 |
| 4 | 调度 | **Worker 自调度**：30s 轮询 + CPU/内存感知，cron 删除 | worker.py |
| 5 | 代理 | **本地 `127.0.0.1:7897`**，删 tinyproxy/43.159/.env 引用 | git config 实测 |
| 6 | 交付 | **先出评审报告**（本文件），暂不改 AGENTS.md | 用户选择 |

---

## 三、建议改写方案（待批准后执行）

> 用户选择「先出评审报告」，未授权改写。以下为改写的具体清单，供后续决策。

### 约束规则

- 「以 CLI 为主 / web 已停更」→ 「HTTP API + Worker 为主」。
- 代理规则 → 本地 `127.0.0.1:7897`，删 tinyproxy 凭证引用。
- 凭证管理 → 本地开发免密；删「凭证都在 .env」的表述（无 .env 文件）。
- API 调用规范 → 「禁止直接调内部 API；通过 HTTP API（POST /api/v1/transcribe 等）或 serve 提交任务」。
- 保留：Git Worktree 规则、PR 通过 GitHub API 操作。

### 用户偏好表

- 「由 cron 调度」→ 「由 Worker 自调度（30s 轮询）」。
- 新增「提交方式」维度：HTTP 入队为主；单个急用可 CLI `transcribe` 同步。

### 标准化动作

- 「收到链接 → 转录」：解析 BV → 查 `out/` → 有则展示，无则 `POST /api/v1/transcribe` 入队 → 查 `/api/v1/tasks` 状态。
- 「收到合集链接」：解析合集 → 逐个 `POST /api/v1/transcribe` 入队。
- 「状态查询」：先 `bili-scribe serve` 确认服务，再 `GET /api/v1/tasks` 或 `/api/v1/health`。
- 「创建并行开发环境」：保留，仅修正 `.venv` 初始化命令（本机无 .venv）。

### 目录结构

- `src/web/` 「已停更」→ 「当前主架构：HTTP API + Worker + SPA」。

### 工具使用规则

- 修正 `.venv/bin/bili-scribe` → 按实际运行环境（服务器 `/opt/data/.venv-whisper` 或 `uv run`）。

### 文档索引

- 新增 `docs/agents/worktree.md` 条目。

---

## 四、待澄清（阻塞项）

1. **`.venv` 在哪**：本机无 `.venv`，文档却强制用 `.venv/bin/bili-scribe`。项目实际跑在哪台机器（本机 / 服务器 `/opt/data`）？
2. **代理**：确认本机 `127.0.0.1:7897` 为唯一代理，还是本机 + 远端 tinyproxy 并存。
3. **工作区脏状态**：`main` 上有一批未提交的删除（`.agents/skills/*/SKILL.md`、`.pi/settings.json`、`.pi/extensions/...`），与本次评审无关，需单独处理。
