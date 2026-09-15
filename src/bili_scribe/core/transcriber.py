"""Whisper 转录引擎 — 调用 faster-whisper 进行语音转文字。

这是项目中唯一与 faster-whisper 交互的模块，不包含任何 B 站 API 逻辑。
"""

import gc
import math
import sys
from collections import OrderedDict
from typing import Any

# 模型实例上限：同时最多常驻 2 个（tiny 75MB ~ large-v3 2.9GB），
# 超出后按 LRU 淘汰最久未用实例，释放其内存。
_MODEL_CACHE_MAX = 2
# 键含模型类：本函数刻意接收 whisper_model_cls 以便替换实现/测试打桩，
# 若键里不含类，测试用的假类会占掉真实类的缓存槽（反之亦然），造成类型错配。
_MODEL_CACHE: OrderedDict[tuple[type, str, str, str], Any] = OrderedDict()


def clear_model_cache() -> int:
    """释放全部缓存的模型实例，返回被释放的个数。

    缓存实例常驻整个进程生命周期，而 web/worker.py 的准入检查只看当前可用内存：
    若空闲的缓存模型把可用内存压到阀值以下，Worker 会一直跳过任务，
    也就永远不会触发新的模型加载与 LRU 淘汰 —— 形成任务永久饥饿。
    内存吃紧时由调用方主动让路，代价仅是下次重新加载模型。
    """
    n = len(_MODEL_CACHE)
    _MODEL_CACHE.clear()
    # 强制回收：否则解释器不保证立即把原生内存还给操作系统，
    # 调用方随后重读的可用内存不会变化，让路就白做了。
    gc.collect()
    return n


def _get_model(whisper_model_cls: type, model_size: str, device: str = "cpu", compute_type: str = "int8") -> Any:
    """按 (模型类, 模型, 设备, 计算精度) 复用 WhisperModel 实例。

    Worker 串行转录多个任务时，避免每次都从磁盘重读模型文件。

    参数：
        whisper_model_cls: WhisperModel 类，由调用方导入，便于测试替换。
        model_size: Whisper 模型大小。
        device: 推理设备。
        compute_type: 计算精度。

    返回：
        缓存中的 WhisperModel 实例；未命中时构造并写入缓存。
    """
    # Worker 单线程串行转录（ADR-0005），缓存无需加锁；引入并发转录时需补锁。
    key = (whisper_model_cls, model_size, device, compute_type)
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        _MODEL_CACHE.move_to_end(key)  # 命中即刷新，使 LRU 顺序反映真实使用
        return cached

    # 先腾位再加载：否则加载期间会同时驻留 _MODEL_CACHE_MAX + 1 个实例，
    # large-v3（≈2.9GB）+ medium（≈1.5GB）场景下峰值逼近 9GB，
    # 正是本 issue 要压下去的内存压力。
    while _MODEL_CACHE and len(_MODEL_CACHE) >= _MODEL_CACHE_MAX:
        _MODEL_CACHE.popitem(last=False)

    print(f"正在加载 Whisper 模型 ({model_size}, {device.upper()})...", file=sys.stderr)
    model = whisper_model_cls(model_size, device=device, compute_type=compute_type)
    _MODEL_CACHE[key] = model
    return model


def whisper_transcribe(audio_path: str, language: str = "zh", model_size: str = "small") -> list | None:
    """使用 faster-whisper 转录音频文件。

    参数：
        audio_path: 要转录的音频文件路径。
        language: Whisper 语言提示（如 "zh"、"en"、"ja"）。
        model_size: Whisper 模型大小 — "tiny"、"base"、"small"、
            "medium" 或 "large-v3"。

    返回：
        包含 "from"、"to"、"content"、"avg_logprob"、
        "no_speech_prob" 键的片段字典列表，转录失败返回 None。
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("错误: 未安装 faster-whisper。", file=__import__("sys").stderr)
        print("安装: uv pip install faster-whisper", file=__import__("sys").stderr)
        return None

    try:
        model = _get_model(WhisperModel, model_size)
        print("正在转录...", file=__import__("sys").stderr)
        segments, info = model.transcribe(audio_path, language=language, beam_size=5)
        print(f"检测到语言: {info.language} (概率: {info.language_probability:.2f})", file=__import__("sys").stderr)

        result = []
        for seg in segments:
            result.append(
                {
                    "from": seg.start,
                    "to": seg.end,
                    "content": seg.text.strip(),
                    "avg_logprob": seg.avg_logprob,
                    "no_speech_prob": seg.no_speech_prob,
                }
            )
        return result
    except Exception as e:  # noqa: BLE001
        print(f"Whisper 错误: {e}", file=__import__("sys").stderr)
        return None


def format_transcript(segments: list[dict], model: str = "tiny", speaker: str = "说话人 A") -> str:
    """将转录片段格式化为带说话人、模型、置信度的文稿。

    格式：
        [说话人 A] [tiny] [0.82] 00:00:01,230 - 00:00:52,100
        大家好，今天我们来聊聊网文写作。首先……

    参数：
        segments: 转录片段列表（每段含 from/to/content/avg_logprob）。
        model: 转录使用的模型名称。
        speaker: 说话人标签（后续 diarize 阶段换为真实说话人）。

    返回：
        格式化后的文稿字符串。
    """
    lines = []
    for seg in segments:
        start = seg.get("from", 0)
        end = seg.get("to", 0)
        content = seg.get("content", "").strip()
        if not content:
            continue
        avg_logprob = seg.get("avg_logprob", 0)
        # 将 logprob 转换为 0~1 置信度
        conf = round(math.exp(avg_logprob), 2) if avg_logprob else 0.0
        conf = min(conf, 1.0)  # 截断到 1.0
        from_ts = format_srt_timestamp(start)
        to_ts = format_srt_timestamp(end)
        lines.append(f"[{speaker}] [{model}] [{conf:.2f}] {from_ts} - {to_ts}")
        lines.append(content)
        lines.append("")
    return "\n".join(lines)


def format_timestamp(seconds: float) -> str:
    """将秒数转换为 HH:MM:SS 格式。

    参数：
        seconds: 时长（秒）。

    返回：
        格式化后的时间戳字符串（如 "05:11" 或 "01:05:11"）。
    """
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_srt_timestamp(seconds: float) -> str:
    """将秒数转换为 SRT 标准时间戳格式（HH:MM:SS,mmm）。

    参数：
        seconds: 时长（秒）。

    返回：
        SRT 格式时间戳字符串（如 "00:05:11,000"）。
    """
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_srt(subtitles: list[dict]) -> str:
    """将字幕片段列表格式化为 SRT 字幕文本。

    参数：
        subtitles: 包含 "from"、"to" 和 "content" 键的片段字典列表。

    返回：
        SRT 格式的完整字幕字符串。
    """
    lines = []
    for i, item in enumerate(subtitles, 1):
        from_ts = format_srt_timestamp(item.get("from", 0))
        to_ts = format_srt_timestamp(item.get("to", 0))
        content = item.get("content", "").strip()
        lines.append(f"{i}")
        lines.append(f"{from_ts} --> {to_ts}")
        lines.append(content)
        lines.append("")
    return "\n".join(lines)
