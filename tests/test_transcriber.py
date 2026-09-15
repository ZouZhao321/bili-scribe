"""测试：Whisper 模型进程内缓存（issue #33）。

覆盖 transcriber._get_model 的复用与 LRU 淘汰，以及 whisper_transcribe
在连续转录时复用同一模型实例。全程使用假模型类，绝不加载真实 Whisper 模型。
"""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from bili_scribe.core import transcriber


def _make_fake_model(created: list) -> type:
    """构造假 WhisperModel 类：记录每个实例，不做任何真实模型加载。"""

    class FakeWhisperModel:
        def __init__(self, model_size: str, device: str = "cpu", compute_type: str = "int8"):
            self.model_size = model_size
            self.device = device
            self.compute_type = compute_type
            self.transcribe_calls = 0
            created.append(self)

        def transcribe(self, audio_path: str, language: str = "zh", beam_size: int = 5):
            self.transcribe_calls += 1
            segments = [SimpleNamespace(start=0.0, end=1.5, text=" 你好 ", avg_logprob=-0.2, no_speech_prob=0.01)]
            info = SimpleNamespace(language=language, language_probability=0.99)
            return segments, info

    return FakeWhisperModel


def _stub_faster_whisper(monkeypatch, model_cls: type) -> None:
    """把 faster_whisper 替换为只暴露假模型的桩模块，避免真实依赖被导入。"""
    stub = ModuleType("faster_whisper")
    stub.WhisperModel = model_cls
    monkeypatch.setitem(sys.modules, "faster_whisper", stub)


@pytest.fixture(autouse=True)
def _isolate_model_cache():
    """每个测试前后清空模型缓存，保证测试互不串扰。"""
    transcriber._MODEL_CACHE.clear()
    yield
    transcriber._MODEL_CACHE.clear()


class TestGetModelCache:
    """_get_model 的实例复用与 LRU 淘汰。"""

    def test_同参数复用同一实例(self):
        created = []
        fake = _make_fake_model(created)

        assert transcriber._get_model(fake, "base") is transcriber._get_model(fake, "base")
        assert len(created) == 1

    def test_不同参数各自构造实例(self):
        created = []
        fake = _make_fake_model(created)

        base = transcriber._get_model(fake, "base")
        small = transcriber._get_model(fake, "small")

        assert base is not small
        assert [m.model_size for m in created] == ["base", "small"]

    def test_不同计算精度不共用实例(self):
        created = []
        fake = _make_fake_model(created)

        int8_model = transcriber._get_model(fake, "base", "cpu", "int8")
        float16_model = transcriber._get_model(fake, "base", "cpu", "float16")

        assert int8_model is not float16_model
        assert len(created) == 2

    def test_超过上限淘汰最久未使用的实例(self):
        created = []
        fake = _make_fake_model(created)

        tiny = transcriber._get_model(fake, "tiny")
        base = transcriber._get_model(fake, "base")
        transcriber._get_model(fake, "tiny")  # 命中 tiny，使 base 成为最久未使用
        small = transcriber._get_model(fake, "small")  # 触发淘汰 base

        assert transcriber._get_model(fake, "tiny") is tiny
        assert transcriber._get_model(fake, "small") is small
        assert transcriber._get_model(fake, "base") is not base, "base 应已被淘汰并重新构造"
        assert len(created) == 4

    def test_淘汰后只保留最新的两个(self):
        created = []
        fake = _make_fake_model(created)

        for size in ("tiny", "base", "small", "medium"):
            transcriber._get_model(fake, size)

        assert len(transcriber._MODEL_CACHE) == transcriber._MODEL_CACHE_MAX
        assert list(transcriber._MODEL_CACHE) == [("small", "cpu", "int8"), ("medium", "cpu", "int8")]


class TestWhisperTranscribeCache:
    """whisper_transcribe 经缓存复用模型，且对外行为不变。"""

    def test_连续转录复用同一模型实例(self, tmp_path, monkeypatch):
        created = []
        _stub_faster_whisper(monkeypatch, _make_fake_model(created))
        audio = tmp_path / "audio.m4s"
        audio.write_bytes(b"fake-audio")

        transcriber.whisper_transcribe(str(audio), "zh", "base")
        transcriber.whisper_transcribe(str(audio), "zh", "base")

        assert len(created) == 1, "第二次转录不应重新加载模型"

    def test_第二次转录不再打印加载日志(self, tmp_path, monkeypatch, capsys):
        created = []
        _stub_faster_whisper(monkeypatch, _make_fake_model(created))
        audio = tmp_path / "audio.m4s"
        audio.write_bytes(b"fake-audio")

        transcriber.whisper_transcribe(str(audio), "zh", "base")
        assert "正在加载 Whisper 模型" in capsys.readouterr().err

        transcriber.whisper_transcribe(str(audio), "zh", "base")
        assert "正在加载 Whisper 模型" not in capsys.readouterr().err

    def test_返回结构保持不变(self, tmp_path, monkeypatch):
        created = []
        _stub_faster_whisper(monkeypatch, _make_fake_model(created))
        audio = tmp_path / "audio.m4s"
        audio.write_bytes(b"fake-audio")

        result = transcriber.whisper_transcribe(str(audio), "en", "base")

        assert result == [{"from": 0.0, "to": 1.5, "content": "你好", "avg_logprob": -0.2, "no_speech_prob": 0.01}]

    def test_不同模型各自加载一次(self, tmp_path, monkeypatch):
        created = []
        _stub_faster_whisper(monkeypatch, _make_fake_model(created))
        audio = tmp_path / "audio.m4s"
        audio.write_bytes(b"fake-audio")

        transcriber.whisper_transcribe(str(audio), "zh", "base")
        transcriber.whisper_transcribe(str(audio), "zh", "small")
        transcriber.whisper_transcribe(str(audio), "zh", "base")

        assert [m.model_size for m in created] == ["base", "small"]

    def test_未安装faster_whisper时返回None(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "faster_whisper", None)
        audio = tmp_path / "audio.m4s"
        audio.write_bytes(b"fake-audio")

        assert transcriber.whisper_transcribe(str(audio), "zh", "base") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
