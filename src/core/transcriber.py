"""Whisper 转录引擎 — 调用 faster-whisper 进行语音转文字。

这是项目中唯一与 faster-whisper 交互的模块，不包含任何 B 站 API 逻辑。
"""


def whisper_transcribe(audio_path: str, language: str = "zh", model_size: str = "small") -> list | None:
    """使用 faster-whisper 转录音频文件。

    参数：
        audio_path: 要转录的音频文件路径。
        language: Whisper 语言提示（如 "zh"、"en"、"ja"）。
        model_size: Whisper 模型大小 — "tiny"、"base"、"small"、
            "medium" 或 "large-v3"。

    返回：
        包含 "from"、"to" 和 "content" 键的片段字典列表，
        转录失败返回 None。
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("错误: 未安装 faster-whisper。", file=__import__("sys").stderr)
        print("安装: uv pip install faster-whisper", file=__import__("sys").stderr)
        return None

    try:
        print(f"正在加载 Whisper 模型 ({model_size}, CPU)...", file=__import__("sys").stderr)
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        print("正在转录...", file=__import__("sys").stderr)
        segments, info = model.transcribe(audio_path, language=language, beam_size=5)
        print(f"检测到语言: {info.language} (概率: {info.language_probability:.2f})", file=__import__("sys").stderr)

        result = []
        for seg in segments:
            result.append({"from": seg.start, "to": seg.end, "content": seg.text.strip()})
        return result
    except Exception as e:  # noqa: BLE001
        print(f"Whisper 错误: {e}", file=__import__("sys").stderr)
        return None


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
