"""initial_prompt 术语提示 — 从 CLI/HTTP API 到 model.transcribe() 的透传链路测试.

覆盖 issue #34 的要求：
1. 传入的提示语确实抵达 ``model.transcribe()``。
2. 不传提示时，调用形态与改动前完全一致（``initial_prompt`` 为 None，
   即 faster-whisper 的默认值）。

所有测试都用替身替换 ``WhisperModel``，绝不加载真实模型。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bili_scribe.web.models import TaskStatus

# ── 测试替身 ────────────────────────────────────────────────────────────────


class _FakeInfo:
    """替代 faster-whisper 返回的 TranscriptionInfo。"""

    language = "zh"
    language_probability = 0.99


class _FakeWhisperModel:
    """记录 transcribe() 收到的关键字参数，不做任何真实推理。"""

    last_kwargs: dict | None = None

    def __init__(self, model_size: str, device: str = "cpu", compute_type: str = "int8"):
        self.model_size = model_size

    def transcribe(self, audio_path: str, **kwargs):
        """记录调用参数并返回空片段列表。"""
        _FakeWhisperModel.last_kwargs = kwargs
        return [], _FakeInfo()


def _fake_audio(tmp_path: Path) -> Path:
    """在临时目录下造一个占位音频文件（内容不被读取）。"""
    audio = tmp_path / "audio.m4s"
    audio.write_bytes(b"not-a-real-audio")
    return audio


# ── 1. 核心层：提示语抵达 model.transcribe() ────────────────────────────────


class TestTranscriberPrompt:
    """whisper_transcribe() 对 initial_prompt 的处理。"""

    def _patch_model(self, monkeypatch):
        """把 faster_whisper.WhisperModel 换成记录参数的替身。"""
        import faster_whisper

        _FakeWhisperModel.last_kwargs = None
        monkeypatch.setattr(faster_whisper, "WhisperModel", _FakeWhisperModel)

    def test_prompt_reaches_model_transcribe(self, monkeypatch, tmp_path):
        """传入术语提示时，提示语必须出现在 transcribe() 的关键字参数里。"""
        from bili_scribe.core.transcriber import whisper_transcribe

        self._patch_model(monkeypatch)
        audio = _fake_audio(tmp_path)

        whisper_transcribe(str(audio), "zh", "base", initial_prompt="创作原则、小郎君")

        assert _FakeWhisperModel.last_kwargs["initial_prompt"] == "创作原则、小郎君"

    def test_no_prompt_keeps_previous_call_shape(self, monkeypatch, tmp_path):
        """不传提示时，调用形态与改动前一致：只有 language 与 beam_size 有值。"""
        from bili_scribe.core.transcriber import whisper_transcribe

        self._patch_model(monkeypatch)
        audio = _fake_audio(tmp_path)

        whisper_transcribe(str(audio), "zh", "base")

        assert _FakeWhisperModel.last_kwargs == {
            "language": "zh",
            "beam_size": 5,
            "initial_prompt": None,
        }

    def test_empty_prompt_normalizes_to_none(self, monkeypatch, tmp_path):
        """显式传空串与不传等价 —— 空串不得改变默认行为。"""
        from bili_scribe.core.transcriber import whisper_transcribe

        self._patch_model(monkeypatch)
        audio = _fake_audio(tmp_path)

        whisper_transcribe(str(audio), "zh", "base", initial_prompt="")

        assert _FakeWhisperModel.last_kwargs["initial_prompt"] is None


# ── 2. 编排层：runner 把提示语交给 Whisper ──────────────────────────────────


class TestRunnerPromptChain:
    """run_transcription() 对 initial_prompt 的透传。"""

    def _patch_runner(self, monkeypatch, tmp_path, captured: dict):
        """把 runner 的外部依赖全部替换为离线替身。"""
        from bili_scribe.core import runner

        def fake_whisper(audio_path, language, model_size, initial_prompt=""):
            captured["initial_prompt"] = initial_prompt
            captured["whisper_args"] = (language, model_size)
            return [{"from": 0.0, "to": 1.0, "content": "测试", "avg_logprob": -0.1, "no_speech_prob": 0.0}]

        def fake_download(audio_url, output_path, referer=""):
            Path(output_path).write_bytes(b"audio")
            return True

        monkeypatch.setattr(runner, "whisper_transcribe", fake_whisper)
        monkeypatch.setattr(runner, "OUTPUT_DIR", tmp_path)
        monkeypatch.setattr(
            runner,
            "get_video_info",
            lambda bvid: {"title": "测试标题", "duration": 10, "owner": {}, "stat": {}},
        )
        monkeypatch.setattr(runner, "get_cid", lambda bvid, page=0: ("123", "P1", 1))
        monkeypatch.setattr(runner, "get_audio_url", lambda bvid, cid: "https://example.invalid/a.m4s")
        monkeypatch.setattr(runner, "download_audio", fake_download)

    def test_runner_forwards_prompt_and_writes_transcript(self, monkeypatch, tmp_path):
        """mode=whisper 时，提示语抵达转录引擎且文稿仍正常写出。"""
        from bili_scribe.core import runner

        captured: dict = {}
        self._patch_runner(monkeypatch, tmp_path, captured)

        result = runner.run_transcription("BV1Gm421W75K", "base", mode="whisper", initial_prompt="术语A")

        assert result["success"] is True
        assert captured["initial_prompt"] == "术语A"
        assert captured["whisper_args"] == ("zh", "base")
        transcript = next(tmp_path.glob("*/转录文稿.txt"))
        assert "测试" in transcript.read_text(encoding="utf-8")

    def test_runner_defaults_prompt_to_empty(self, monkeypatch, tmp_path):
        """不传提示时，runner 传给转录引擎的是空串（保持默认）。"""
        from bili_scribe.core import runner

        captured: dict = {}
        self._patch_runner(monkeypatch, tmp_path, captured)

        result = runner.run_transcription("BV1Gm421W75K", "base", mode="whisper")

        assert result["success"] is True
        assert captured["initial_prompt"] == ""


# ── 3. HTTP API：请求字段 → 任务 → 持久化 ───────────────────────────────────


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """覆盖 conftest 的同名 fixture：在 lifespan 启动 worker **之前**先把它打桩掉。

    在测试体内 monkeypatch worker.start 是空操作：`with TestClient(app)` 在 fixture
    setup 阶段就执行了 lifespan（storage.recover + worker.start），真实 worker 线程
    已经起来，会去队列里抢任务并调真实的 run_transcription。
    同时把持久化目录指向 tmp_path，避免 process_task 里的 _progress() 往真实的
    ~/.bilibili-api/tasks 写文件（测试必须 hermetic）。
    """
    from bili_scribe.web import worker as worker_module
    from bili_scribe.web.queue import queue
    from bili_scribe.web.server import app
    from bili_scribe.web.storage import storage

    monkeypatch.setattr(storage, "_dir", str(tmp_path))
    monkeypatch.setattr(worker_module.worker, "start", lambda: None)
    with queue._lock:
        queue._tasks.clear()

    with TestClient(app) as client:
        yield client


class TestApiPrompt:
    """POST /api/v1/transcribe 的 initial_prompt 字段。"""

    def test_request_prompt_is_stored_on_task(self, api_client):
        """请求携带 initial_prompt 时，入队的任务必须保留它。"""
        from bili_scribe.web.queue import queue

        resp = api_client.post(
            "/api/v1/transcribe",
            json={
                "url": "BV1Gm421W75K",
                "mode": "whisper",
                "model": "tiny",
                "initial_prompt": "创作原则",
            },
        )

        assert resp.status_code == 202
        task_id = resp.json()["task_id"]
        task = queue.peek(task_id)
        assert task is not None
        assert task.initial_prompt == "创作原则"
        # 任务详情接口不因新字段而回归
        assert api_client.get(f"/api/v1/transcribe/{task_id}").status_code == 200

    def test_default_request_prompt_is_empty(self, api_client):
        """未携带该字段时默认为空串，不改变既有请求的语义。"""
        from bili_scribe.web.queue import queue

        resp = api_client.post(
            "/api/v1/transcribe",
            json={"url": "BV1Gm421W75K", "mode": "whisper", "model": "tiny"},
        )

        assert resp.status_code == 202
        assert queue.peek(resp.json()["task_id"]).initial_prompt == ""

    def test_worker_forwards_prompt_to_runner(self, monkeypatch, tmp_path):
        """worker 执行任务时把 initial_prompt 交给 run_transcription。"""
        from bili_scribe.web import worker as worker_module
        from bili_scribe.web.models import TranscriptMode, WhisperModel
        from bili_scribe.web.queue import Task, queue
        from bili_scribe.web.storage import storage

        # process_task 会经 _progress() 落盘，不隔离就会往真实的
        # ~/.bilibili-api/tasks 写 prompt_chain_001.json
        monkeypatch.setattr(storage, "_dir", str(tmp_path))

        captured: dict = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "bv": "BV1Gm421W75K",
                "title": "测试",
                "author": "作者",
                "duration": 10,
                "source": "whisper",
                "subtitles": [{"from": 0.0, "to": 1.0, "content": "内容"}],
                "lines": 1,
                # process_task 必须读这个键（worker.py 里 api_result["full_text"]
                # = result["full_text"]）。缺了它会抛 KeyError，被宽 except 吞掉后
                # 任务实际失败，而只断言 captured 的测试照样绿。
                "full_text": "内容",
            }

        monkeypatch.setattr(worker_module, "run_transcription", fake_run)

        task = Task(
            task_id="prompt_chain_001",
            url="BV1Gm421W75K",
            mode=TranscriptMode.whisper,
            model=WhisperModel.base,
            initial_prompt="术语B",
        )
        # 清空全局队列，避免同 BV 任务残留导致入队被去重拒绝（测试必须 hermetic）
        with queue._lock:
            queue._tasks.clear()
        assert queue.enqueue(task) is True
        try:
            # process_task 假定任务已被 worker 出队（complete/fail 只接受 processing
            # 状态，queue.py 里的幽灵任务守卫），必须先 dequeue，否则任务到不了终态。
            assert queue.dequeue() is not None
            worker_module.process_task(task.task_id)

            assert queue.peek(task.task_id).status == TaskStatus.completed, "任务应走到终态 completed"
        finally:
            queue.remove(task.task_id)

        assert captured["initial_prompt"] == "术语B"


# ── 4. 持久化：新旧任务文件都要能读 ─────────────────────────────────────────


class TestStoragePrompt:
    """TaskStorage 对 initial_prompt 的序列化兼容性。"""

    def test_roundtrip_preserves_prompt(self, temp_storage_dir):
        """保存后重新加载，提示语不丢。"""
        from bili_scribe.web.models import TranscriptMode, WhisperModel
        from bili_scribe.web.queue import Task
        from bili_scribe.web.storage import TaskStorage

        store = TaskStorage(temp_storage_dir)
        store.save(
            Task(
                task_id="t_prompt",
                url="BV1Gm421W75K",
                mode=TranscriptMode.whisper,
                model=WhisperModel.base,
                initial_prompt="创作原则",
            )
        )

        loaded = store.load("t_prompt")
        assert loaded is not None
        assert loaded.initial_prompt == "创作原则"

    def test_legacy_file_without_prompt_still_loads(self, temp_storage_dir):
        """旧任务的 JSON 没有该字段，加载后应回落为空串而非报错。"""
        from bili_scribe.web.storage import TaskStorage

        legacy = {
            "task_id": "t_legacy",
            "url": "BV1Gm421W75K",
            "mode": "whisper",
            "model": "base",
            "language": "zh",
            "page": 0,
            "output_format": "text",
            "status": "completed",
        }
        Path(temp_storage_dir, "t_legacy.json").write_text(
            json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
        )

        loaded = TaskStorage(temp_storage_dir).load("t_legacy")
        assert loaded is not None
        assert loaded.initial_prompt == ""


# ── 5. CLI：参数存在且被转发 ────────────────────────────────────────────────


class TestCliPrompt:
    """CLI --prompt 参数。"""

    def test_transcribe_accepts_prompt(self):
        """transcribe 子命令解析 --prompt。"""
        from bili_scribe.cli.main import build_parser

        args = build_parser().parse_args(["transcribe", "BV1Gm421W75K", "--prompt", "术语"])
        assert args.prompt == "术语"

    def test_transcribe_prompt_defaults_to_empty(self):
        """不传 --prompt 时默认空串。"""
        from bili_scribe.cli.main import build_parser

        assert build_parser().parse_args(["transcribe", "BV1Gm421W75K"]).prompt == ""

    def test_batch_accepts_prompt(self):
        """batch 子命令解析 --prompt。"""
        from bili_scribe.cli.main import build_parser

        assert build_parser().parse_args(["batch", "BV1Gm421W75K", "--prompt", "术语"]).prompt == "术语"

    def test_cmd_transcribe_forwards_prompt(self, monkeypatch):
        """cmd_transcribe 把 --prompt 交给 run_transcription。"""
        from bili_scribe.cli import main as cli

        captured: dict = {}

        def fake_run(url, model, **kwargs):
            captured["url"] = url
            captured["model"] = model
            captured.update(kwargs)
            return {"success": True, "srt": ""}

        monkeypatch.setattr(cli, "run_transcription", fake_run)

        args = cli.build_parser().parse_args(["transcribe", "BV1Gm421W75K", "-q", "--prompt", "术语"])
        cli.cmd_transcribe(args)

        assert captured["url"] == "BV1Gm421W75K"
        assert captured["initial_prompt"] == "术语"

    def test_cmd_batch_forwards_prompt(self, monkeypatch):
        """cmd_batch 对合集内每个视频都带上 --prompt。"""
        from bili_scribe.cli import main as cli

        captured: list[dict] = []

        def fake_run(bvid, **kwargs):
            captured.append({"bvid": bvid, **kwargs})
            return {"success": True, "lines": 1}

        monkeypatch.setattr(cli, "run_transcription", fake_run)
        monkeypatch.setattr(
            cli,
            "get_collection_info",
            lambda bvid: {"title": "测试合集", "ep_count": 1, "videos": [{"bvid": "BV1Gm421W75K", "title": "第一集"}]},
        )

        args = cli.build_parser().parse_args(["batch", "BV1Gm421W75K", "--prompt", "术语"])
        cli.cmd_batch(args)

        assert captured[0]["bvid"] == "BV1Gm421W75K"
        assert captured[0]["initial_prompt"] == "术语"
