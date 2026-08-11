# Git Worktree 并行开发

## 为什么使用 Worktree？

### 痛点：单工作区的困境

在单工作区中切换分支时，每次 `git checkout` 都会带来以下问题：

```
分支 A (feat/docker-frontend)   →   git checkout feat/agent-docs
  ├── 未提交修改被迫 stash/pop
  ├── .venv/ 依赖可能不同，需要重装
  ├── node_modules/ 版本冲突
  ├── out/ 转录结果混在一起
  └── IDE 索引重建，切换成本高
```

**一次切换动辄数分钟，频繁切换则不断累积。**

### 方案：Worktree = 每个分支一个独立工作区

```
bilibili-transcript/                  ← 主仓库
├── .git/                             ← 共享的 git 数据库
├── src/ ...                          ← 当前分支的工作区
├── .worktree/
│   ├── feat-docker-frontend/         ← feat/docker-frontend 分支的独立工作区
│   │   ├── .venv/    (独立)
│   │   ├── out/      (独立)
│   │   └── src/      (该分支的代码)
│   ├── feat-agents-docs/             ← feat/agents-docs-api-rule 分支
│   │   ├── .venv/    (独立)
│   │   └── ...
│   └── main/                         ← main 分支（稳定参照）
│       ├── .venv/    (独立)
│       └── ...
```

### 收益对比

| 场景 | 单工作区 | Worktree 并行 |
|------|----------|---------------|
| 切换分支 | stash → checkout → pop（可能冲突） | 直接 `cd` 到另一个目录 |
| 依赖差异 | 每次切换重装 `.venv` | 各自独立 `.venv`，一次性安装 |
| 并行开发 | 不可能 | 两个终端各开一个 worktree |
| 参照 main | 需要切过去看，再切回来 | 始终在 `main/` worktree 中可见 |
| 未提交修改 | stash 污染，容易丢失 | 各自独立，互不干扰 |
| 临时实验 | 分支爆炸 | 用完即删 `git worktree remove` |
| CI 调试 | 切分支打断工作 | 独立 worktree 中调试，主工作区不受影响 |

### 核心原理

```
所有 worktree 共享同一个 .git/objects 数据库
         ↓
  git 历史、分支、标签全局可见
         ↓
  但每个 worktree 的 working tree 和 index 完全独立
         ↓
  .venv/ out/ node_modules/ 等非 git 管理的文件天然隔离
```

## 使用规范

### 命名约定

| 分支名 | Worktree 路径 |
|--------|--------------|
| `main` | `.worktree/main` |
| `feat/docker-frontend` | `.worktree/feat-docker-frontend` |
| `feat/agents-docs-api-rule` | `.worktree/feat-agents-docs-api-rule` |
| `fix/dash-flv-fallback` | `.worktree/fix-dash-flv-fallback` |

**规则**：斜杠 `/` → 短横线 `-`，保持分支名可读性。

### 创建 Worktree

```bash
# 基于已有分支创建
git worktree add .worktree/feat-docker-frontend feat/docker-frontend

# 创建新分支并同时创建 worktree
git worktree add .worktree/feat-xxx -b feat/xxx

# 初始化 Python 环境
cd .worktree/feat-xxx
uv venv
uv pip install -e ".[dev]"
```

### 查看所有 Worktree

```bash
git worktree list
# /root/bilibili-transcript             7d214d1 [feat/docker-frontend]
# /root/bilibili-transcript/.worktree/main  abc1234 [main]
```

### 删除 Worktree

```bash
# 删除 worktree + 清理元数据
git worktree remove .worktree/feat-xxx

# 如果分支已合并，可同时删除分支
git branch -d feat/xxx
```

### 约束

| 约束 | 说明 |
|------|------|
| 同一分支只能在一个 worktree 中 | git 硬限制，`git worktree add` 时会拒绝 |
| `.worktree/` 必须在 `.gitignore` 中 | 避免主仓库追踪 worktree 目录 |
| 主仓库不能是裸仓库状态 | 创建 worktree 前主仓库必须在某个分支上 |
| 删除 worktree 目录后需 `prune` | `git worktree prune` 清理残留元数据 |

## 典型场景

### 场景 1：功能开发中，需要紧急修 bug

```bash
# 当前在 feat/docker-frontend 开发中，有未提交修改
# 突然需要修 main 上的 bug

git worktree add .worktree/fix-urgent -b fix/urgent main
cd .worktree/fix-urgent
uv venv && uv pip install -e ".[dev]"
# 修复 bug → 提交 → PR
git worktree remove .worktree/fix-urgent
# 回到 feat/docker-frontend 继续开发，未提交修改完好无损
```

### 场景 2：同时开发两个独立功能

```bash
# 终端 1
cd /root/bilibili-transcript/.worktree/feat-docker-frontend
# 开发 Docker 前端...

# 终端 2
cd /root/bilibili-transcript/.worktree/feat-agents-docs
# 开发 Agent 文档...
```

### 场景 3：Review 代码时参照 main

```bash
# 始终保持 main 的 worktree 作为参照
git worktree add .worktree/main main

# 随时对比
diff -r .worktree/main/src/core/ src/core/
```