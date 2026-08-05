# bili-scribe CLI 设计

## 项目命名

- **项目名**: bili-scribe
- **仓库**: https://github.com/ZouZhao321/bili-scribe
- **描述**: B站视频字幕提取 + Whisper 本地语音转录工具

## CLI 结构（多子命令风格）

```
bili-scribe transcribe <url>    # 转录单个视频
bili-scribe queue <subcommand>  # 持久化队列管理
bili-scribe batch <url>         # 批量下载合集
bili-scribe info <url>          # 查询视频信息
bili-scribe version             # 显示版本
```

## 推送工作流

通过远程服务器中转推送到 GitHub，所有操作预定义在 `scripts/push.sh` 中。

```bash
./scripts/push.sh push <branch>           # 推送分支
./scripts/push.sh pr-update <n> <file>    # 从文件更新 PR 描述
```

**流程**: `本地 → SSH → 服务器 bare repo → post-receive 钩子 → GitHub`

## 凭证管理

- 所有凭证存储在 `.env` 中（GITHUB_TOKEN, SSH_HOST, SSH_USER, SSH_PASSWORD）
- `.env` 被 `.gitignore` 忽略，不上传
- 服务器 bare repo 的 post-receive 钩子读取 Token 自动推送到 GitHub

## 项目结构

```
bili-scribe/
├── src/core/       # 核心引擎
├── src/cli/        # CLI 入口
├── src/web/        # FastAPI 服务（备用）
├── scripts/        # 本地辅助脚本（不上传）
│   └── push.sh     # 推送中转脚本
├── memory/         # 记忆目录（本地，不上传）
├── temp/           # 临时文件（不上传）
├── .env            # 环境变量（不上传）
└── pyproject.toml  # 依赖定义
```

## 关键决策

| 决策 | 选择 |
| :--- | :--- |
| 项目名 | bili-scribe |
| CLI 结构 | 多子命令（git/docker 风格） |
| 输出方式 | 默认写文件到 out/ 目录 |
| 打包形式 | 单文件可执行文件（PyInstaller，待实施） |
| 代码托管 | GitHub（原 Gitee 已删除） |
| 推送方式 | SSH 中转服务器 → bare repo → post-receive → GitHub |
| 凭证管理 | .env 文件，gitignore 排除 |