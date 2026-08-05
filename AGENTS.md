# bili-scribe — Pi Agent 配置

项目概述：B 站视频字幕提取 + Whisper 本地语音转录工具，三级降级策略。

## 约束规则

- **GitHub 推送**：当前服务器无法直连 GitHub，必须使用 `temp/push.sh` 中转，禁止自行编写推送脚本
- **PR 操作**：所有 PR 创建/更新必须通过 `temp/push.sh pr-update`，禁止直接 git push
- **凭证管理**：所有凭证存储在 `.env` 中，禁止在代码中硬编码

## 文档索引

| 关键词 | 入口 |
|--------|------|
| 架构、CLI、转录、调度、输出、内存 | `docs/agents/README.md` |
| ADR、架构决策、决策记录、技术选型 | `docs/adr/README.md` |
| 会话记忆、历史决策、排查记录 | `.pi/memory/README.md` |