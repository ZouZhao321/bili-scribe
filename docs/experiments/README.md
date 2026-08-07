# 实验记录目录

本目录存放 Whisper 转录相关的实验记录，每个实验独立子目录，包含完整记录和可复用的验证脚本。

## 实验列表

| 日期 | 实验 | 摘要 | 可复用 |
|------|------|------|:------:|
| 2026-07-30 | [Whisper 内存压力测试](./2026-07-30_whisper-memory-benchmark/) | 在 3.6GB RAM 机器上测试 small/medium/large-v3 模型，验证 Swap 对稳定性的影响 | ✅ `verify.sh` |

## 实验模板

如果要新建实验，复制以下目录结构：

```
experiments/YYYY-MM-DD_实验名称/
├── README.md       # 实验目的、环境、方法、结论
├── results.md       # 详细数据、对比表格
└── verify.sh        # 可复用的验证脚本
```
