"""测试：CLI 参数透传回归（issue #32）。

CLI 声明了 -l/--language、-p/--page、-w/--force-whisper、-o/--output、
-c/--cookie，但此前只调用 run_transcription(args.url, args.model)，
其余参数静默落到函数默认值。

这些测试 monkeypatch bili_scribe.cli.main.run_transcription 并断言真实
调用参数，从而覆盖「参数确实到达核心引擎」这一契约 —— 端到端跑一遍
转录无法发现这类缺陷。
"""

from __future__ import annotations

from typing import Any

from bili_scribe.cli import main
from bili_scribe.core import runner


def _ok_result() -> dict[str, Any]:
    """cmd_transcribe 输出所需的最小成功结果。"""
    return {"success": True, "bv": "BV1Fsn4zCEhi", "title": "标题", "srt": "", "lines": 3}


class _Recorder:
    """记录 run_transcription 的调用参数，返回固定成功结果。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, model: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"url": url, "model": model, **kwargs})
        return _ok_result()


def _parse(argv: list[str]) -> Any:
    """按 CLI 真实路径解析参数（含子命令）。"""
    return main.build_parser().parse_args(argv)


class TestTranscribeArgsPassthrough:
    """transcribe 子命令的参数必须透传。"""

    def test_全部参数透传(self, monkeypatch, tmp_path):
        rec = _Recorder()
        monkeypatch.setattr(main, "run_transcription", rec)

        args = _parse(
            [
                "transcribe",
                "BV1Fsn4zCEhi",
                "-m",
                "small",
                "-l",
                "en",
                "-p",
                "2",
                "-w",
                "-o",
                str(tmp_path),
                "-c",
                "SESSDATA=abc",
            ]
        )
        main.cmd_transcribe(args)

        assert len(rec.calls) == 1
        call = rec.calls[0]
        assert call["url"] == "BV1Fsn4zCEhi"
        assert call["model"] == "small"
        assert call["language"] == "en"
        assert call["page"] == 2
        assert call["cookie"] == "SESSDATA=abc"
        assert call["output_dir"] == tmp_path

    def test_force_whisper_映射为_whisper_mode(self, monkeypatch):
        rec = _Recorder()
        monkeypatch.setattr(main, "run_transcription", rec)

        main.cmd_transcribe(_parse(["transcribe", "BV1Fsn4zCEhi", "-w"]))
        assert rec.calls[0]["mode"] == "whisper"

    def test_默认不指定_output_时为_None(self, monkeypatch):
        rec = _Recorder()
        monkeypatch.setattr(main, "run_transcription", rec)

        main.cmd_transcribe(_parse(["transcribe", "BV1Fsn4zCEhi"]))

        call = rec.calls[0]
        assert call["mode"] == "auto"
        assert call["language"] == "zh"
        assert call["page"] == 0
        assert call["cookie"] == ""
        assert call["output_dir"] is None


class TestBatchArgsPassthrough:
    """batch 子命令的 -o/--output 必须透传（batch 无 -l/-p/-c 参数）。"""

    def test_output_透传(self, monkeypatch, tmp_path):
        rec = _Recorder()
        monkeypatch.setattr(main, "run_transcription", rec)
        monkeypatch.setattr(
            main,
            "get_collection_info",
            lambda bvid: {"title": "合集", "ep_count": 1, "videos": [{"bvid": "BV1A3Kr6BEA5", "title": "标题"}]},
        )

        main.cmd_batch(_parse(["batch", "BV1Fsn4zCEhi", "-m", "small", "-o", str(tmp_path)]))

        assert len(rec.calls) == 1
        assert rec.calls[0]["url"] == "BV1A3Kr6BEA5"
        assert rec.calls[0]["model"] == "small"
        assert rec.calls[0]["output_dir"] == tmp_path

    def test_默认不指定_output_时为_None(self, monkeypatch):
        rec = _Recorder()
        monkeypatch.setattr(main, "run_transcription", rec)
        monkeypatch.setattr(
            main,
            "get_collection_info",
            lambda bvid: {"title": "合集", "ep_count": 1, "videos": [{"bvid": "BV1A3Kr6BEA5", "title": "标题"}]},
        )

        main.cmd_batch(_parse(["batch", "BV1Fsn4zCEhi"]))

        assert rec.calls[0]["output_dir"] is None


class TestRunTranscriptionOutputDir:
    """run_transcription 的 output_dir 形参必须真正决定产物落盘位置。"""

    @staticmethod
    def _stub_until_dir_created(monkeypatch) -> None:
        """让流程在写入视频信息后、触网之前中止，只验证目录归属。"""
        monkeypatch.setattr(runner, "get_video_info", lambda bvid: {"title": "标题", "duration": 10})

        def _boom(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("测试中止：不需要继续触网")

        monkeypatch.setattr(runner, "get_cid", _boom)

    def test_指定_output_dir_时产物写入该目录(self, monkeypatch, tmp_path):
        self._stub_until_dir_created(monkeypatch)

        result = runner.run_transcription("BV1Fsn4zCEhi", "base", output_dir=tmp_path)

        assert result["success"] is False
        video_dir = tmp_path / "BV1Fsn4zCEhi_标题"
        assert video_dir.is_dir()
        assert (video_dir / "视频信息.txt").is_file()

    def test_未指定时回退模块级_OUTPUT_DIR(self, monkeypatch, tmp_path):
        self._stub_until_dir_created(monkeypatch)
        monkeypatch.setattr(runner, "OUTPUT_DIR", tmp_path)

        result = runner.run_transcription("BV1Fsn4zCEhi", "base")

        assert result["success"] is False
        assert (tmp_path / "BV1Fsn4zCEhi_标题" / "视频信息.txt").is_file()
