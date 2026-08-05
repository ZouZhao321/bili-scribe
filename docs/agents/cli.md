# CLI 命令

## 统一入口

```bash
bili-scribe transcribe <url>    # 转录单个视频
bili-scribe queue <subcommand>  # 持久化队列管理
bili-scribe batch <url>         # 批量下载合集
bili-scribe info <url>          # 查询视频信息
bili-scribe version             # 显示版本
```

## 队列管理

```bash
bili-scribe queue add "BV1xxx"                        # 添加任务
bili-scribe queue status                              # 查看队列状态
bili-scribe queue list [pending|running|done|failed]  # 列出任务
bili-scribe queue install-cron                        # 安装 cron 调度（每10分钟自动检查）
bili-scribe queue retry <task_id>                     # 重试失败任务
bili-scribe queue remove <task_id>                    # 删除任务
bili-scribe queue cancel                              # 取消当前运行的任务
bili-scribe queue clear [pending|failed]              # 清空队列
```

## GitHub 推送工作流

通过远程服务器中转推送到 GitHub，所有操作预定义在 `scripts/push.sh` 中：

```bash
./scripts/push.sh push <branch>           # 推送分支到 GitHub
./scripts/push.sh pr-update <pr-number> <body-file>  # 从文件读取内容更新 PR 描述
```

**流程**：`本地 → SSH → 服务器 bare repo → post-receive 钩子 → GitHub`

**凭证管理**：所有凭证存储在 `.env` 中，被 `.gitignore` 忽略，不上传。

## 模型选择

| 模型 | 大小 | 速度 | 质量 | 适用场景 |
|------|:----:|:----:|:----:|----------|
| tiny | 75MB | ~1x | 一般 | 快速预览 |
| base | 141MB | ~1.5x | 可用 | 短视频 |
| small | 464MB | ~3x | 较好 | **日常使用（默认）** |
| medium | 1.5GB | ~8x | 好 | 重要内容 |
| large-v3 | 3.1GB | ~15x | 最好 | 最高精度 |