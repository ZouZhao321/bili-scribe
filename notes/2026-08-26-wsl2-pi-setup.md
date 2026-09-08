# WSL2 + Pi 环境搭建经验

**日期**: 2026-08-26

## 问题

在 WSL2 Ubuntu 中搭建 Pi agent 开发环境，遇到网络代理、Node.js 安装、配置迁移等问题。

## 解决方案

### 1. 重置 WSL2 Ubuntu

```powershell
wsl --shutdown
wsl --unregister Ubuntu
wsl --install -d Ubuntu-22.04
```

**注意**: `wsl --install` 从微软商店下载，在国内极慢。解决方案：手动下载 appx 安装，或开启代理后重试。

### 2. 配置网络代理

WSL2 是独立 VM，`127.0.0.1` 不是 Windows 宿主机。需要通过虚拟网关 IP 连接 Windows 侧的 Clash Verge。

**关键步骤**:

1. Clash Verge 开启 **Allow LAN**（允许局域网连接）
2. 编辑 `~/.bashrc` 末尾添加：

```bash
_win_host=$(cat /etc/resolv.conf 2>/dev/null | grep nameserver | awk '{print $2}')
if [ -n "$_win_host" ]; then
  export http_proxy="http://${_win_host}:7897"
  export https_proxy="http://${_win_host}:7897"
  export ALL_PROXY="socks5://${_win_host}:7897"
  export NO_PROXY="localhost,127.0.0.1,::1,172.16.0.0/12,192.168.0.0/16,10.0.0.0/8"
fi
unset _win_host
```

**验证**: `curl -x http://172.31.16.1:7897 https://www.google.com`

### 3. 安装 Node.js (nvm)

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc
nvm install 22
npm config set registry https://registry.npmmirror.com  # 淘宝镜像
```

**重要**: 不要用 Windows 侧的 node（`/mnt/c/nvm4w/nodejs`），I/O 慢且路径混乱。

### 4. 安装 Pi 及扩展

```bash
npm install -g @earendil-works/pi-coding-agent
npm install -g @hypabolic/pi-hypa @ff-labs/pi-fff pi-web-access \
  @juicesharp/rpiv-todo pi-simplify @juicesharp/rpiv-ask-user-question pi-lens
```

### 5. 迁移 Pi 配置

从 GitHub 私有仓库 clone 配置（避免复制 Windows 侧的缓存和临时文件）：

```bash
git clone git@github.com:ZouZhao321/pi_conf.git ~/pi_conf
ln -sf ~/pi_conf/agent ~/.pi/agent
```

**认证**: Windows 用 HTTPS + credential manager，WSL2 需要用 token 或配置 SSH key。

### 6. Git 代理配置

```bash
git config --global http.proxy http://172.31.16.1:7897
git config --global https.proxy http://172.31.16.1:7897
```

## 关键发现

| 发现 | 说明 |
| ------ | ------ |
| WSL2 PATH 混入 Windows 路径 | 默认行为，通过 `[interop] appendWindowsPath = false` 可关闭 |
| 9p 协议慢 | `/mnt/c/` 是跨 VM 文件系统，I/O 性能差，开发文件放 `~/` 下 |
| Clash 必须开启 Allow LAN | 否则只监听 `127.0.0.1`，WSL2 无法连接 |
| 网关 IP 来自 resolv.conf | `/etc/resolv.conf` 中的 nameserver 就是 Windows 宿主机 IP |
| nvm 安装后 PATH 需手动配置 | `~/.bashrc` 中添加 node 路径，或使用 `source ~/.nvm/nvm.sh` |

## 文件清单

| 文件 | 改动 |
| ------ | ------ |
| `~/.bashrc` | 添加代理配置 + node 路径 |
| `~/.gitconfig` | 添加 git 代理 |
| `~/.pi/agent` | 软链接到 `~/pi_conf/agent` |
