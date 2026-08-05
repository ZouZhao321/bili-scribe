# 实验结果数据

## 系统资源消耗对比

| 指标 | small (464MB) | medium (1.5GB) | large-v3 (2.9GB) |
| ------ | :---: | :---: | :---: |
| 转录结果 | ✅ 完成 | ✅ 完成 | ✅ 完成 |
| 系统卡死 | ❌ 否 | ❌ 否 | ❌ 否 |
| 转录分段数 | 128 | 144 | 147 |
| 结束后可用内存 | 2.1GB | 2.5GB | 2.7GB |
| 峰值 Swap 使用 | 极少 | 1.9GB | 2.0GB |
| 耗时（5分钟视频） | 约 2-3 分钟 | 约 5-8 分钟 | 约 10-15 分钟 |

## 内存状态变化

### large-v3 运行前后

```
运行前:  Mem: 3.6G (可用 1.1G)   Swap: 4.0G (已用 0B)
运行后:  Mem: 3.6G (可用 2.7G)   Swap: 4.0G (已用 2.0G)
```

### 卡死场景（Swap 1.9GB 时）

```
运行前:  Mem: 3.6G (可用 700MB)   Swap: 1.9G (已用 1.4G)
运行中:  → 卡死，SSH 无响应
```

## 模型质量对比

| 关键短语 | small | medium | large-v3 |
| --------- | :-----: | :------: | :--------: |
| "冰美式" | ❌ 冰美食 | ✅ 冰美式 | ✅ 冰美式 |
| "DIY" | ❌ D I Y | ✅ DIY | ✅ DIY |
| "K3 集群" | ❌ K3机群 | ✅ K3集群 | ✅ K3集群 |
| "挂件" | ❌ 挂键 | ✅ 挂件 | ✅ 挂件 |
| "拖拉拽" | ❌ 拖拉帅 | ✅ 拖拉拽 | ✅ 拖拉拽 |
| "待办事项" | ❌ Tutulis | ✅ to do list | ✅ to do list |
| "示例" | ❌ 视力 | ❌ 视力 | ✅ **示例** |
| "伪需求" | ❌ 委屈球 | ❌ 需求 | ✅ **伪需求** |
| "电子猫窝" | ❌ 电子毛窝 | ✅ 电子猫窝 | ❌ 电子毛窝 |
| "Fable" | ❌ fable | ❌ fable | ✅ **Fable**（大写） |

## 输出文件

```
~/bilibili-output/
├── audio/
│   ├── BV1DqKr6SEyo_small.m4s       (3.3MB)
│   ├── BV1DqKr6SEyo_medium.m4s      (3.3MB)
│   └── BV1DqKr6SEyo_large-v3.m4s    (3.3MB)
└── transcripts/
    ├── BV1DqKr6SEyo_..._small.txt      (4.7KB)
    ├── BV1DqKr6SEyo_..._medium.txt     (4.8KB)
    └── BV1DqKr6SEyo_..._large-v3.txt   (4.8KB)
```

## 原始日志

详见 `verify.sh` 的输出，或直接在项目根目录运行：

```bash
bash experiments/2026-07-30_whisper-memory-benchmark/verify.sh
```
