# 项目架构

项目按 **核心引擎 → 使用方式** 分层组织：

```
bili-scribe/
├── src/
│   └── bili_scribe/               # 主包（src-layout，src/ 为纯容器）
│       ├── core/                  # 核心引擎 — faster-whisper 封装 + B 站 API 交互
│       ├── cli/                   # 统一 CLI 入口 — bili-scribe 命令
│       └── web/                   # FastAPI 服务（当前主架构：HTTP API + Worker + SPA）
├── tests/          # 测试套件
├── experiments/    # 实验记录
├── docs/           # 文档
├── scripts/        # 辅助脚本（本地，不上传）
└── .env            # 环境变量（本地，不上传）
```

| 层级 | 说明 |
| ------ | ------ |
| `src/bili_scribe/core/` | faster-whisper 为核心的转录引擎，B 站 API 封装，三级降级策略 |
| `src/bili_scribe/cli/` | 统一 CLI 入口 `bili-scribe`，多子命令结构 |
| `scripts/` | 本地辅助脚本，被 `.gitignore` 忽略 |
