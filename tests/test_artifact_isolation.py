"""产品目录隔离测试 —— issue #31：多模型转录同一视频时静默覆盖产物.

全程 mock 网络与 Whisper，不加载真实模型、不发真实请求。
"""

import re

import pytest

from bili_scribe.core import runner

BVID = "BV15qbH6bEAG"


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """把 run_transcription 的网络与转录依赖全部替换为确定性桩."""
    monkeypatch.setattr(runner, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        runner,
        "get_video_info",
        lambda bvid: {"title": "测试标题", "duration": 60, "owner": {"name": "up"}},
    )
    monkeypatch.setattr(runner, "get_cid", lambda bvid, page: (12345, "P1", 1))
    monkeypatch.setattr(
        runner,
        "get_subtitle_url",
        lambda bvid, cid, cookie: [{"lan": "zh-CN", "subtitle_url": "https://example.invalid/s.json"}],
    )
    monkeypatch.setattr(
        runner,
        "download_subtitle_json",
        lambda url: {"body": [{"from": 0.0, "to": 1.0, "content": "你好"}]},
    )
    return tmp_path


def _run(offline, model):
    return runner.run_transcription(BVID, model=model, mode="subtitle")


def test_different_models_land_in_separate_dirs(offline):
    """核心回归：base 与 small 的产物必须并存，不是后者覆盖前者."""
    _run(offline, "base")
    _run(offline, "small")

    dirs = sorted(p.name for p in offline.iterdir() if p.is_dir())
    assert len(dirs) == 2, f"期望两个独立产物目录，实际: {dirs}"
    assert any(d.endswith("_base") for d in dirs)
    assert any(d.endswith("_small") for d in dirs)


def test_earlier_result_survives_later_model(offline):
    """复现 issue 的原始症状：先把旧产物改脏，用另一个模型转录后它必须原样保留."""
    _run(offline, "base")
    base_dir = next(p for p in offline.iterdir() if p.name.endswith("_base"))
    sentinel = base_dir / "转录文稿.txt"
    sentinel.write_text("SENTINEL-base", encoding="utf-8")

    _run(offline, "small")

    assert sentinel.read_text(encoding="utf-8") == "SENTINEL-base", "base 的产物被 small 覆盖了"
    small_dir = next(p for p in offline.iterdir() if p.name.endswith("_small"))
    assert small_dir != base_dir


def test_same_model_rerun_reuses_dir_and_overwrites(offline):
    """同模型重跑必须复用同一目录并刷新文稿 —— retry 依赖这个幂等语义."""
    _run(offline, "base")
    dirs_after_first = [p for p in offline.iterdir() if p.is_dir()]
    assert len(dirs_after_first) == 1

    (dirs_after_first[0] / "转录文稿.txt").write_text("STALE", encoding="utf-8")
    _run(offline, "base")

    dirs_after_second = [p for p in offline.iterdir() if p.is_dir()]
    assert len(dirs_after_second) == 1, "同模型重跑不应产生新目录"
    assert (dirs_after_second[0] / "转录文稿.txt").read_text(encoding="utf-8") != "STALE"


def test_dir_name_stays_parseable_for_downstream_scripts(offline):
    """update_author_map.py / migrate_*.py 用 re.match(r"BV[a-zA-Z0-9]+", name) 解析目录名."""
    _run(offline, "base")
    name = next(p.name for p in offline.iterdir() if p.is_dir())

    assert name.startswith(f"{BVID}_")
    assert name.endswith("_base")
    match = re.match(r"(BV[a-zA-Z0-9]+)", name)
    assert match is not None and match.group(1) == BVID


def test_超长中文标题不超目录名上限(offline, monkeypatch):
    """单级目录名上限是 255 **字节**（ext4/APFS），中文一字 3 字节。

    模型后缀是在已经接近上限的名字后面追加字节，必须靠字节预算兜住，
    否则 OSError: [Errno 36] File name too long 会冒泡成任务硬失败。
    """
    monkeypatch.setattr(
        runner,
        "get_video_info",
        lambda bvid: {"title": "测" * 120, "duration": 60, "owner": {"name": "up"}},
    )

    for model in ("base", "large-v3"):
        assert _run(offline, model)["success"] is True

    names = [p.name for p in offline.iterdir() if p.is_dir()]
    assert len(names) == 2, f"异模型应各自建目录，实际: {names}"
    for n in names:
        assert len(n.encode("utf-8")) <= 255, f"{n!r} 长度 {len(n.encode('utf-8'))} 字节超过上限"
    assert any(n.endswith("_base") for n in names)
    assert any(n.endswith("_large-v3") for n in names)
