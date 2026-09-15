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
        limit = transcriber._MODEL_CACHE_MAX
        assert limit >= 2, "本用例假定缓存上限不小于 2"

        oldest = transcriber._get_model(fake, "tiny")
        others = [transcriber._get_model(fake, f"m{i}") for i in range(limit - 1)]
        transcriber._get_model(fake, "tiny")  # 命中 tiny，使 others[0] 成为最久未使用
        transcriber._get_model(fake, "overflow")  # 触发淘汰

        assert transcriber._get_model(fake, "tiny") is oldest, "被刷新过的实例不应被淘汰"
        assert transcriber._get_model(fake, "m0") is not others[0], "最久未使用的实例应被淘汰并重新构造"

    def test_淘汰后只保留最新的N个(self):
        created = []
        fake = _make_fake_model(created)
        limit = transcriber._MODEL_CACHE_MAX

        for i in range(limit + 2):
            transcriber._get_model(fake, f"m{i}")

        assert len(transcriber._MODEL_CACHE) == limit
        # 缓存键包含模型类（见 _MODEL_CACHE 注释），因此期望值也必须带上 fake
        expected = [(fake, f"m{i}", "cpu", "int8") for i in range(2, limit + 2)]
        assert list(transcriber._MODEL_CACHE) == expected


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

        second = transcriber.whisper_transcribe(str(audio), "zh", "base")
        # 先确认第二次真的成功了：whisper_transcribe 吞掉一切异常并返回 None，
        # 若它失败了，「不打印加载日志」也会成立，断言就成了空过。
        assert second is not None, "第二次转录必须成功，否则下面的否定断言没有意义"
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


class TestCachePeakAndIsolation:
    """缓存上限的“峰值”语义与缓存键隔离（ocr 审查 4b6f66c 报出）。"""

    def test_加载前先淘汰_构造时驻留数低于上限(self):
        """先腾位再加载：否则加载瞬间会同时驻留 MAX+1 个实例（large-v3 场景峰值近 9GB）。"""
        created = []
        base_fake = _make_fake_model(created)
        sizes_at_construct: list[int] = []

        class Recording(base_fake):  # type: ignore[misc, valid-type]
            def __init__(self, *args, **kwargs):
                sizes_at_construct.append(len(transcriber._MODEL_CACHE))
                super().__init__(*args, **kwargs)

        limit = transcriber._MODEL_CACHE_MAX
        for i in range(limit + 2):
            transcriber._get_model(Recording, f"m{i}")

        assert max(sizes_at_construct) < limit, (
            f"构造新模型时缓存里已有 {max(sizes_at_construct)} 个实例（上限 {limit}），"
            "说明是先加载后淘汰，峰值会超过上限"
        )

    def test_不同模型类不共用缓存槽(self):
        """缓存键含模型类 —— 否则测试用的假类会占掉真实类的槽位（类型错配）。"""
        created_a: list = []
        created_b: list = []
        fake_a = _make_fake_model(created_a)
        fake_b = _make_fake_model(created_b)

        a = transcriber._get_model(fake_a, "base")
        b = transcriber._get_model(fake_b, "base")

        assert a is not b
        assert len(created_a) == 1 and len(created_b) == 1

    def test_clear_model_cache_释放全部实例(self):
        created = []
        fake = _make_fake_model(created)
        transcriber._get_model(fake, "base")

        assert transcriber.clear_model_cache() == 1
        assert len(transcriber._MODEL_CACHE) == 0
        # 再次调用无实例可释放
        assert transcriber.clear_model_cache() == 0


class TestWorkerMemoryRelease:
    """Worker 的内存准入必须与模型缓存协同，否则会任务永久饥饿（issue #33）。

    缓存的空闲模型常驻内存，而准入检查只看可用内存：若缓存把可用内存压到阀值
    以下，任务因不达标而永不出队，就不会触发新的模型加载与 LRU 淘汰 —— 死锁。
    """

    def _patch(self, monkeypatch, readings):
        from bili_scribe.web import worker as worker_module

        released: list[bool] = []

        def _fake_clear() -> int:
            released.append(True)
            return 1

        monkeypatch.setattr(worker_module, "clear_model_cache", _fake_clear)
        iterator = iter(readings)
        monkeypatch.setattr(worker_module, "get_available_memory_mb", lambda: next(iterator))
        monkeypatch.setattr(worker_module, "get_cpu_usage", lambda: 0)
        return worker_module, released

    def test_内存不足时先释放缓存再复查(self, monkeypatch):
        # 首次读内存严重不足，释放缓存后充足
        worker_module, released = self._patch(monkeypatch, [100, 999_999])

        ok, reason = worker_module.Worker()._check_resources("large-v3")

        assert released, "内存不足时应先释放模型缓存"
        assert ok, f"释放缓存后复查应放行，实际: {reason}"

    def test_释放后仍不足则拒绝(self, monkeypatch):
        worker_module, released = self._patch(monkeypatch, [100, 100])

        ok, reason = worker_module.Worker()._check_resources("large-v3")

        assert released
        assert not ok and "内存不足" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
