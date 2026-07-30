# Whisper 内存压力测试

## 实验目的

验证在 3.6GB RAM 云服务器上，faster-whisper 不同模型（small / medium / large-v3）的稳定性，以及 Swap 大小对系统稳定性的影响。

## 测试日期

2026-07-30

## 环境

| 项目 | 值 |
| ------ | ------ |
| CPU | 4 核 (x86_64) |
| 内存 | 3.6GB |
| 磁盘 | 40GB (6.9GB 可用) |
| 操作系统 | Linux |
| 背景进程 | VS Code Server, Gitea, n8n, Docker, 腾讯云监控 |
| Python | 3.10+ |
| faster-whisper | 最新版 (CTranslate2 后端) |
| 测试视频 | BV1DqKr6SEyo (5分11秒, 3.4MB 音频) |
| 视频内容 | 中文语音，Kimi K3 看板功能介绍 |

## 测试方法

1. 使用 `src/fetch_transcript.py` 直接调用 faster-whisper
2. 模型配置：`device="cpu"`, `compute_type="int8"`, `beam_size=5`
3. 三个模型各运行一次：small（464MB）、medium（1.5GB）、large-v3（2.9GB）
4. 记录：系统是否卡死、内存峰值、Swap 使用、转录分段数、关键词汇识别准确率

## 关键发现

### 模型加载机制

faster-whisper 基于 CTranslate2，使用 **mmap（内存映射文件）** 加载模型：

```python
self.model = ctranslate2.models.Whisper(model_path, device="cpu", compute_type="int8")
```

- 模型文件 **不是** 一次性全部读入物理内存（RSS）
- 而是映射到 **虚拟地址空间**，按需按页加载到物理内存
- 物理内存不够时，OS 自动将不常用的权重页换出到 Swap

### 音频处理

```python
audio = decode_audio(audio, sampling_rate=sampling_rate)           # 整个音频
features = self.feature_extractor(audio, chunk_length=chunk_length) # 整个转特征
segments = self.generate_segments(features, ...)                    # 30秒窗口分段处理
```

- 音频是 **全部加载到内存**，不是流式读取
- 但 5 分钟音频的特征仅 ~5MB，占比极小
- 长视频（1小时）特征约 60MB，依然不是瓶颈
- **模型权重是内存占用的绝对大头**

### 卡死原因

**卡死的根本原因不是模型太大，而是 Swap 太小。**

当物理内存不足时：

1. OS 需要将不常用的模型权重页换出到 Swap
2. 如果 Swap 已满 → 无法换出 → 内存分配失败
3. 系统进入 **thrashing（抖动）** 状态：反复尝试换页，I/O 占满
4. 所有进程（包括 SSH）都得不到响应 → 卡死

## 结论

- 加大 Swap 到 **4GB** 后，large-v3（2.9GB）稳定运行，系统全程响应正常
- 转录结束后可用内存恢复到 2.5GB+，Swap 使用约 2GB
- 模型使用 mmap 映射，不是流式加载；音频也不是流式处理
- **能稳定运行不是因为音频短（5分钟），而是 Swap 足够大**
- 即使换 1 小时长视频，同样能稳定运行（音频特征仅 ~60MB）

## 推荐配置

### 最低配置（small 模型）

- RAM: 2GB+
- Swap: 1GB+
- 适用：日常使用，5-10 分钟视频

### 推荐配置（medium 模型）

- RAM: 3GB+
- Swap: 4GB+
- 适用：高质量转录，10-30 分钟视频

### 最佳配置（large-v3 模型）

- RAM: 4GB+
- Swap: 4GB+
- 适用：最高精度，任意时长
