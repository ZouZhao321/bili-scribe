# CLI 命令

> **当前主架构是 HTTP API + Worker**（见 `AGENTS.md`）。
> CLI 的 `transcribe` / `batch` 为**同步直跑、不入队**；队列调度已迁至 Worker。
> 需要排队/并发调度时，走 HTTP API 而非 CLI。

## 统一入口

```bash
bili-scribe transcribe <url>          # 转录单个视频（同步直跑，不入队）
bili-scribe batch <url>               # 批量转录合集内所有视频（同步直跑）
bili-scribe serve                     # 启动 HTTP API 服务 + 后台 Worker
bili-scribe info <url>                # 查询视频信息（不转录）
bili-scribe transcript-to-srt <file>  # 转录文稿 .txt 转 SRT 字幕
bili-scribe version                   # 显示版本信息
```

项目未安装到系统 PATH，统一用模块入口调用：

```bash
.venv/bin/python -m bili_scribe.cli.main <子命令>
```

## transcribe

```bash
bili-scribe transcribe <url> [-m MODEL] [-l LANG] [-p PAGE] [-f FORMAT] [-w] [-o DIR] [-c COOKIE] [-q]
```

| 参数 | 默认 | 说明 |
| ------ | :----: | ------ |
| `url` | — | B 站视频链接或 BV 号 |
| `-m, --model` | **base** | `tiny`/`base`/`small`/`medium`/`large-v3` |
| `-l, --language` | `zh` | Whisper 语言提示，如 `zh`/`en`/`ja` |
| `-p, --page` | `0` | 分 P 序号（从 0 开始） |
| `-f, --format` | `text` | `text`/`srt`/`json` |
| `-w, --force-whisper` | 关 | 强制走 Whisper，跳过 CC/AI 字幕 |
| `-o, --output` | `./out/` | 输出目录 |
| `-c, --cookie` | 空 | B 站登录 Cookie |
| `-q, --quiet` | 关 | 静默模式，只输出结果路径 |

**输出目录结构**：`out/{BV号}_{标题}/`，内含 `视频信息.txt`、`转录文稿.txt`、`audio.m4s`。

> ⚠️ 目录名**不含模型标识**，且以 `exist_ok=True` 复用。用不同模型转录**同一视频会静默覆盖** `转录文稿.txt`。
> 需要保留多模型结果时，转录后手动改名（如 `..._base` / `..._small`）。

## batch

```bash
bili-scribe batch <url> [-m MODEL] [-n] [-o DIR]
```

| 参数 | 默认 | 说明 |
| ------ | :----: | ------ |
| `url` | — | 合集内任意视频链接或 BV 号 |
| `-m, --model` | **base** | 同 transcribe |
| `-n, --dry-run` | 关 | 仅列出合集内视频，不下载 |
| `-o, --output` | `./out/` | 输出目录 |

> `batch` **无** `-l` / `-p` / `-c` 参数，合集内逐条同步处理。
> 需要排队与 CPU/内存感知调度时，改用 HTTP API 逐个入队。

## serve

```bash
bili-scribe serve [--host HOST] [-p PORT] [-w WORKERS]
```

| 参数 | 默认 | 说明 |
| ------ | :----: | ------ |
| `--host` | `0.0.0.0` | 监听地址 |
| `-p, --port` | `8000` | 监听端口 |
| `-w, --workers` | `1` | 工作进程数 |

启动后同时拉起后台 Worker（30s 轮询 + CPU/内存感知自调度）。

| 入口 | 地址 |
|------|------|
| 前端 SPA | `http://localhost:8000` |
| API 文档 | `http://localhost:8000/docs` |

凭证：`BILI_SCRIBE_PASSWORD` 为空则跳过 auth（本地开发默认免密）；生产环境通过环境变量注入。

## info

```bash
bili-scribe info <url> [-j]
```

查询标题、作者、时长、分 P 数等，不触发转录。`-j` 输出 JSON。

## transcript-to-srt

```bash
bili-scribe transcript-to-srt <input.txt> [output.srt]
```

省略 `output` 时默认与输入同目录、后缀 `.srt`。

## HTTP API（任务提交的推荐入口）

> 禁止直接调用内部 API（`TaskStore.add()`、`queue_store` 等），必须走 HTTP 或 CLI。

| 操作 | 方法与路径 |
| ------ | ----------- |
| 服务状态 | `GET /api/v1/health` |
| 视频信息 | `GET /api/v1/video/info` |
| 提交转录（入队） | `POST /api/v1/transcribe` |
| 查询单个任务 | `GET /api/v1/transcribe/{task_id}` |
| 列出任务 | `GET /api/v1/tasks` |
| 重试任务 | `POST /api/v1/tasks/{task_id}/retry` |
| 取消任务 | `POST /api/v1/tasks/{task_id}/cancel` |
| 删除任务 | `DELETE /api/v1/tasks/{task_id}` |

提交转录的请求体（`TranscribeRequest`）：

| 字段 | 默认 | 说明 |
| ------ | :----: | ------ |
| `url` | **必填** | B 站链接 / BV 号 / av 号 / b23.tv 短链 |
| `mode` | `auto` | `auto`/`subtitle`/`whisper`/`both` |
| `model` | **small** | 见下方「模型默认值不一致」 |
| `language` | `zh` | Whisper 语言提示 |
| `page` | `0` | 分 P 序号（0-indexed） |
| `output_format` | `text` | `text`/`srt`/`json` |
| `cookie` | 空 | B 站登录 Cookie |
| `webhook` | 空 | 任务完成后的回调 URL |

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/transcribe \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.bilibili.com/video/BV1xxx/","model":"base","language":"zh"}'
```

任务记录持久化在 `~/.bilibili-api/tasks/<task_id>.json`，serve 重启后由 Worker 恢复。

## queue（已废弃）

`bili-scribe queue <add|status|list|retry|remove|cancel|clear>` 仅作为**兼容 shim** 保留，
调用会被拒绝并提示改用 HTTP API。`install-cron` 子命令已移除。

队列调度由 Worker 承担，不再需要 cron。

## 模型默认值不一致（已知）

| 入口 | 默认模型 |
| ------ | :--------: |
| CLI `transcribe` / `batch` | `base` |
| HTTP API `POST /api/v1/transcribe` | `small` |
| `GET /api/v1/health` 的 `default_model` | `small` |

项目偏好为 **base**；通过 HTTP API 提交时**必须显式传 `model`**，否则会得到 small。

## 模型选择

| 模型 | 体积 | 质量 | 适用场景 |
| ------ | :----: | :----: | ---------- |
| tiny | 75MB | 一般 | 快速预览 |
| base | 142MB | 可用 | 短视频；**专有名词易错** |
| small | 464MB | 较好 | 日常使用 |
| medium | ~1.5GB | 好 | 重要内容 |
| large-v3 | ~3.1GB | 最好 | 最高精度 |

模型经 **faster-whisper**（CTranslate2）加载，缓存在 `~/.cache/huggingface/hub/`。

> 国内网络注意：`huggingface.co` 不可达，需 `export HF_ENDPOINT=https://hf-mirror.com`；
> 且新版 `huggingface_hub` 默认走 Xet/CAS 协议（`cas-server.xethub.hf.co`，镜像不覆盖，会返回 401），
> 必须同时 `export HF_HUB_DISABLE_XET=1` 才会走可镜像的传统 HTTP 路径。

## GitHub 推送工作流

通过远程服务器中转推送到 GitHub，操作定义在 `script/push.sh`（注意是 `script/`，非 `scripts/`）：

```bash
./script/push.sh push <branch>                       # 推送分支到 GitHub
./script/push.sh pr-update <pr-number> <body-file>   # 从文件读取内容更新 PR 描述
```

**流程**：`本地 → SSH → 服务器 bare repo → post-receive 钩子 → GitHub`

**凭证管理**：所有凭证存储在 `.env` 中，被 `.gitignore` 忽略，不上传。

## 产物回传（WSL → Windows）

```bash
bash script/sync-to-win.sh [--date YYYY-MM-DD] [--win-root PATH] [--dry-run] [--keep]
```

归档到 `<win-root>/out/<日期>/`（产物目录 + `_tasks/` + `_logs/`），成功后清空 WSL 侧的
`out/`、`~/.bilibili-api/tasks/` 与 `logs/`。回传前做逐文件大小核对，校验不通过则中止且不清空。
