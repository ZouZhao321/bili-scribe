# Whisper 内存管理

## 模型加载机制

faster-whisper 基于 CTranslate2，使用 **mmap（内存映射文件）** 加载模型：

```python
self.model = ctranslate2.models.Whisper(model_path, device="cpu", compute_type="int8")
```

- 模型文件 **不是** 一次性全部读入物理内存（RSS）
- 而是映射到 **虚拟地址空间**，按需按页加载到物理内存
- 物理内存不够时，OS 自动将不常用的权重页换出到 Swap

## 音频处理

```python
audio = decode_audio(audio, sampling_rate=sampling_rate)           # 整个音频
features = self.feature_extractor(audio, chunk_length=chunk_length) # 整个转特征
segments = self.generate_segments(features, ...)                    # 30秒窗口分段处理
```

- 音频是 **全部加载到内存**，不是流式读取
- 但 5 分钟音频的特征仅 ~5MB，占比极小
- 长视频（1小时）特征约 60MB，依然不是瓶颈

## 内存瓶颈

| 模型 | 磁盘大小 | 虚拟内存映射 | 实际物理内存需求 |
|------|:-------:|:----------:|:--------------:|
| tiny | 75MB | ~75MB | ~75MB |
| small | 464MB | ~464MB | ~464MB |
| medium | 1.5GB | ~1.5GB | ~1.5GB |
| large-v3 | 2.9GB | ~2.9GB | ~2.9GB |

**模型权重是内存占用的绝对大头**，音频特征占比可忽略。

## 卡死原因分析

系统配置：3.6GB RAM，云服务器（腾讯云），运行 VS Code Server + Gitea + n8n + Docker 等

| 状态 | 可用 RAM | Swap | 结果 |
|------|:-------:|:----:|:----:|
| 默认（Swap 1.9GB） | ~700MB | 被占满 | ❌ medium/large-v3 卡死 |
| 加大 Swap 到 4GB | ~700MB | 有 2GB+ 空闲 | ✅ large-v3 正常完成 |

**卡死的根本原因不是模型太大，而是 Swap 太小。**

当物理内存不足时：
1. OS 需要将不常用的模型权重页换出到 Swap
2. 如果 Swap 已满 → 无法换出 → 内存分配失败
3. 系统进入 **thrashing（抖动）** 状态：反复尝试换页，I/O 占满
4. 所有进程（包括 SSH）都得不到响应 → 卡死

## 验证结论

- 加大 Swap 到 **4GB** 后，large-v3（2.9GB）稳定运行，系统全程响应正常
- 转录结束后可用内存恢复到 2.5GB+，Swap 使用约 2GB
- 模型使用 mmap 映射，不是流式加载；音频也不是流式处理
- **能稳定运行不是因为音频短（5分钟），而是 Swap 足够大**
- 即使换 1 小时长视频，同样能稳定运行（音频特征仅 ~60MB）