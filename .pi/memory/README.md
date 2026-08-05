# .pi/memory — 会话记忆索引

本目录存放历史会话记忆，记录决策理由和排查过程。内容与 `docs/agents/` 有重叠，按需读取。

| 文件 | 何时读取 | 何时不读 |
|------|----------|----------|
| `2026-08-06-bili-scribe-cli-design.md` | 需要了解项目命名决策、仓库地址、CLI 设计历史、关键决策理由时 | 只需要查询当前 CLI 命令用法（→ `docs/agents/cli.md`）或架构（→ `docs/agents/architecture.md`）时 |
| `2026-08-06-whisper-memory.md` | 需要排查 Whisper 转录卡死/内存不足问题，需要了解 Swap 配置和 mmap 加载机制时 | 只需要查询模型内存需求进行调度决策（→ `docs/agents/scheduling.md`）或了解常规转录流程（→ `docs/agents/workflow.md`）时 |