# WSL2 迁移与配置计划

> 将 bili-scribe 开发环境从 Windows 原生迁移至 WSL2，与 Linux Docker 部署环境保持一致。
>
> 基础策略：丢弃本地 `fix/windows-compat` 分支，直接从远程 `main` 拉起。

---

## 阶段 0：Windows 侧准备

> 确保远程 main 是最新状态，本地脏改动丢弃。

| # | 操作 | 命令 | 备注 |
| --- | ------ | ------ | ------ |
| 0.1 | 确认远程 main 最新 | `git fetch origin && git log --oneline origin/main -5` | 已在 05d8801 |
| 0.2 | 丢弃本地 `fix/windows-compat` | `git checkout main && git branch -D fix/windows-compat` | 未推送，安全删除 |
| 0.3 | 丢弃未提交的改动 | `git checkout -- .` 或 `git clean -fd` | pyproject.toml、health.py 的修复不要了 |
| 0.4 | 确认工作区干净 | `git status` | `nothing to commit, working tree clean` |

---

## 阶段 1：安装 WSL2

| # | 操作 | 命令 | 预计耗时 |
| --- | ------ | ------ | ---------- |
| 1.1 | 管理员 PowerShell 执行 | `wsl --install` | 5 min |
| 1.2 | 重启 Windows | 手动重启 | 2 min |
| 1.3 | 设置 Ubuntu 用户名/密码 | 按提示输入 | 1 min |
| 1.4 | 验证 | `wsl --list --verbose` | 确认 Version 2 |

---

## 阶段 2：Ubuntu 基础环境

在 **Ubuntu 终端** 中执行：

```bash
# 基础工具
sudo apt update && sudo apt upgrade -y
sudo apt install -y build-essential ffmpeg git curl

# Node.js
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.0/install.sh | bash
source ~/.bashrc
nvm install 22

# Pi
npm install -g @earendil-works/pi-coding-agent

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

---

## 阶段 3：GitHub 认证

> 远程仓库是**私有仓库**，clone 前需要认证。

### 方案 A：复用 Windows 侧 Git 凭证（推荐）

WSL2 可以直接调用 Windows 侧的 `git-credential-manager.exe`，自动使用已保存的 GitHub 登录凭证。

```bash
# WSL2 中执行，配置 credential helper 指向 Windows 侧 GCM
git config --global credential.helper '/mnt/c/Program Files/Git/mingw64/bin/git-credential-manager.exe'

# 验证：会弹出 Windows 认证窗口
git ls-remote https://github.com/ZouZhao321/bili-scribe.git HEAD
```

> **前提**：Windows 侧已经通过 GitHub 登录过（VS Code / GitHub Desktop / git push 均可）。如果没有登录过，执行上述命令时会弹出浏览器要求登录。

### 方案 B：SSH Key 方式

```bash
# 1. 如果 Windows 侧已有 SSH key
cp /mnt/c/Users/ZouZhao/.ssh/id_ed25519.pub ~/.ssh/id_ed25519.pub
cat ~/.ssh/id_ed25519.pub  # 添加到 GitHub → Settings → SSH Keys

# 2. 没有就生成新的
ssh-keygen -t ed25519 -C "your@email.com"
cat ~/.ssh/id_ed25519.pub  # 添加到 GitHub

# 3. 用 SSH URL clone
git clone git@github.com:ZouZhao321/bili-scribe.git
```

### 方案 C：Personal Access Token（PAT）

```bash
# 1. GitHub → Settings → Developer settings → Tokens → 生成 token（repo 权限）
# 2. clone 时输入
git clone https://<token>@github.com/ZouZhao321/bili-scribe.git
```

### 认证验证

无论哪种方案，clone 前先验证：

```bash
# 应返回远程 HEAD 的 commit hash
git ls-remote https://github.com/ZouZhao321/bili-scribe.git HEAD
```

---

## 阶段 4：项目环境

```bash
# Clone（私有仓库，已通过阶段 3 认证）
cd ~/projects
git clone https://github.com/ZouZhao321/bili-scribe.git
cd bili-scribe

# Python 环境
uv venv && uv pip install -e .

# 验证
bili-scribe version          # → bili-scribe 1.0.0
bili-scribe serve            # 启动服务
# 新终端：
curl localhost:8000/api/v1/health  # → {"status":"ok"}
```

> **注意**：远程 main 缺少 `[build-system]` 配置，editable install 可能失败。
> 如果报 `No module named 'src'`，先修复 pyproject.toml（见阶段 4.1）。

### 阶段 4.1：修复远程 main 的 bug（如需要）

如果 clone 后 `bili-scribe` 命令报错，需要先提交修复：

```bash
# 修复 pyproject.toml：添加 build-system
# 修复 src/web/routes/health.py：os.statvfs → shutil.disk_usage
# 修复 src/core/queue_store.py：get_available_memory_mb 加 Windows 兼容（可选，Linux 不需要）

git add -A && git commit -m "fix: 修复构建配置和跨平台兼容性"
git push origin main
```

---

## 阶段 5：迁移 Pi 配置

```bash
# 一键迁移
SRC=/mnt/c/Users/ZouZhao/.pi/agent
DST=~/.pi/agent

mkdir -p ~/.pi/.claude "$DST"

# 核心配置
cp "$SRC/settings.json"     "$DST/"
cp "$SRC/auth.json"         "$DST/"
cp "$SRC/models.json"       "$DST/"
cp "$SRC/trust.json"        "$DST/"
cp "$SRC/APPEND_SYSTEM.md"  "$DST/"

# 目录
cp -r "$SRC/skills"         "$DST/"
cp -r "$SRC/extensions"     "$DST/"
cp -r "$SRC/npm"            "$DST/"
cp -r "$SRC/prompts"        "$DST/"

# Claude 权限
cp /mnt/c/Users/ZouZhao/.pi/.claude/settings.local.json ~/.pi/.claude/

# 安全
chmod 600 "$DST/auth.json"

# 验证
pi --version
cat "$DST/settings.json"
```

---

## 阶段 6：VS Code Remote-WSL

| # | 操作 | 位置 |
| --- | ------ | ------ |
| 6.1 | 安装 WSL 扩展 | VS Code 扩展市场 → `ms-vscode-remote.remote-wsl` |
| 6.2 | 打开项目 | Ubuntu 终端 → `code ~/projects/bili-scribe` |
| 6.3 | 选择 Python 解释器 | VS Code 右下角 → `.venv` 中的 Python |

---

## 阶段 7：Docker 环境（可选）

```bash
sudo apt install docker.io docker-compose-v2
sudo service docker start
sudo usermod -aG docker $USER
newgrp docker

cd ~/projects/bili-scribe
docker compose up --build
curl localhost:8000/api/v1/health
```

---

## 验证清单

- [ ] `wsl --list --verbose` → Ubuntu, VERSION 2
- [ ] `git ls-remote https://github.com/ZouZhao321/bili-scribe.git HEAD` → 返回 hash（认证通过）
- [ ] `git clone ...` 成功（私有仓库可访问）
- [ ] `pi --version` → 输出版本号
- [ ] `bili-scribe version` → `bili-scribe 1.0.0`
- [ ] `bili-scribe serve` → 服务启动无报错
- [ ] `curl localhost:8000/api/v1/health` → `"status":"ok"`
- [ ] VS Code Remote-WSL 连接正常
- [ ] 浏览器 `http://localhost:8000` → 前端页面正常

---

## 时间估算

| 阶段 | 耗时 |
| ------ | ------ |
| 0：准备 | 5 min |
| 1：WSL2 安装 + 重启 | 10 min |
| 2：基础环境 | 15 min |
| 3：GitHub 认证 | 5 min |
| 4：项目环境 | 10 min |
| 5：Pi 配置 | 5 min |
| 6：VS Code | 5 min |
| 7：Docker | 15 min |
| **总计** | **~65 min** |
