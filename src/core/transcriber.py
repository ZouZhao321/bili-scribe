"""Whisper 转录引擎 — 调用 faster-whisper 进行语音转文字。

这是项目中唯一与 faster-whisper 交互的模块，不包含任何 B 站 API 逻辑。
"""
from typing import Optional


def whisper_transcribe(audio_path: str, language: str = "zh", model_size: str = "small") -> Optional[list]:
    """Transcribe an audio file using faster-whisper.

    Args:
        audio_path: Path to the audio file to transcribe.
        language: Language hint for Whisper (e.g. "zh", "en", "ja").
        model_size: Whisper model size — "tiny", "base", "small",
            "medium", or "large-v3".

    Returns:
        A list of segment dicts with keys "from", "to", and "content",
        or None if transcription failed.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("Error: faster-whisper not installed.", file=__import__('sys').stderr)
        print("Install: uv pip install faster-whisper", file=__import__('sys').stderr)
        return None

    try:
        print(f"Loading Whisper model ({model_size}, CPU)...", file=__import__('sys').stderr)
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        print("Transcribing...", file=__import__('sys').stderr)
        segments, info = model.transcribe(audio_path, language=language, beam_size=5)
        print(f"Detected language: {info.language} (prob: {info.language_probability:.2f})", file=__import__('sys').stderr)

        result = []
        for seg in segments:
            result.append({
                "from": seg.start,
                "to": seg.end,
                "content": seg.text.strip()
            })
        return result
    except Exception as e:
        print(f"Whisper error: {e}", file=__import__('sys').stderr)
        return None


def format_timestamp(seconds: float) -> str:
    """Convert a duration in seconds to HH:MM:SS format.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted timestamp string (e.g. "05:11" or "01:05:11").
    """
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"