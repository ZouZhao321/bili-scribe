---
name: pi-uninstall-fix
description: 修复 pi 卸载 npm 插件后启动报错的问题。当用户说"pi 启动报错"、"npm ENOTEMPTY"、"卸载插件后报错"、"pi 无法启动"、"npm rename error" 时使用。诊断并修复 pi 包卸载后 npm 目录损坏导致的启动失败问题。
---

# Pi NPM 插件卸载修复指南

## 问题现象

执行 `pi remove npm:@xxx/yyy` 卸载插件后，下次启动 pi 时报错：

```
npm error code ENOTEMPTY
npm error syscall rename
npm error path /root/.pi/agent/npm/node_modules/<package-name>
npm error dest /root/.pi/agent/npm/node_modules/.<package-name>-<random>
npm error errno -39
npm error ENOTEMPTY: directory not empty, rename ...
```

随后 pi 退出，无法正常启动。

## 原因

卸载过程中 npm 清理某个依赖包时被中断，导致 `node_modules/<package-name>` 目录处于损坏状态。下次 pi 启动时触发其它包的自动安装（如 `pi-lens`），npm 的 `rename` 操作在该损坏目录上失败。

## 修复步骤

### 1. 查找损坏的目录

根据报错信息中的 `path` 确定损坏的目录名：

```
npm error path /root/.pi/agent/npm/node_modules/<package-name>
```

### 2. 删除损坏目录

```bash
rm -rf /root/.pi/agent/npm/node_modules/<package-name>
```

### 3. 验证修复

```bash
pi --version
# 应正常输出版本号，如 0.81.1

pi -p "hello"
# 应正常响应
```

## 验证标准

- [ ] `pi --version` 正常输出版本号
- [ ] `pi -p "hello"` 正常响应
- [ ] `pi list` 查看已安装包无异常
