# bili-scribe — Pi Agent 配置

项目概述：B 站视频字幕提取 + Whisper 本地语音转录工具，三级降级策略。

## 约束规则

- **GitHub 推送**：当前服务器无法直连 GitHub，必须使用 `temp/push.sh` 中转，禁止自行编写推送脚本
- **PR 操作**：所有 PR 创建/更新必须通过 `temp/push.sh pr-update`，禁止直接 git push
- **凭证管理**：所有凭证存储在 `.env` 中，禁止在代码中硬编码
- **API 调用规范**：禁止直接调用内部 API（如 `TaskStore.add()`、`queue_store` 等），必须使用封装后的 CLI 命令（`bili-scribe queue add`、`bili-scribe batch` 等）

## 文档索引（必读规则）

> 只要有任何相关性（哪怕 1%），必须先阅读对应文档，再执行操作。

| 关键词 | 入口 | 说明 |
|--------|------|------|
| 架构、目录结构、核心引擎、分层 | `docs/agents/architecture.md` | 项目代码布局 |
| CLI 命令、队列管理、模型选择 | `docs/agents/cli.md` | 命令用法、参数说明 |
| 转录流程、降级策略、注意事项 | `docs/agents/workflow.md` | 转录流程与环境配置 |
| 调度策略、CPU 感知、内存需求 | `docs/agents/scheduling.md` | 队列调度规则 |
| 输出目录、out、文件结构 | `docs/agents/output.md` | 转录结果存放位置 |
| 内存管理、mmap、Swap、卡死分析 | `docs/agents/memory.md` | Whisper 内存排查 |
| ADR、架构决策、决策记录、技术选型 | `docs/adr/README.md` | 架构决策记录 |
| 会话记忆、历史决策、排查记录 | `.pi/memory/README.md` | 历史记忆 |