"""GameDataResolver 测试：fixture 单测 + 真实安装目录（若存在）的验收。"""
from __future__ import annotations

import os
from pathlib import Path

from app.services.game_data_resolver import GameDataResolver

REAL_GAME_DIR = r"E:\SteamLibrary\steamapps\common\Crusader Kings III"
HAVE_REAL = Path(REAL_GAME_DIR).exists()


def _make_fake_game(root: Path) -> Path:
    dlc = root / "game" / "dlc" / "dlc002_sp_day1"
    dlc.mkdir(parents=True)
    (dlc / "dlc002.dlc").write_text(
        'name = "Test DLC Name"\npath = "dlc/dlc002_sp_day1"\n', encoding="utf-8"
    )
    # 非 dlc 文件夹应被忽略
    (root / "game" / "dlc" / "readme").mkdir(parents=True)
    return root


def test_list_dlc_from_fixture(tmp_path):
    gdir = _make_fake_game(tmp_path)
    r = GameDataResolver(game_dir=gdir)
    assert r.is_available()
    dlcs = r.list_dlc()
    assert len(dlcs) == 1
    assert dlcs[0]["id"] == "dlc002_sp_day1"
    assert dlcs[0]["name"] == "Test DLC Name"
    assert dlcs[0]["path"] == "dlc/dlc002_sp_day1"


def test_resolve_fixture(tmp_path):
    gdir = _make_fake_game(tmp_path)
    r = GameDataResolver(game_dir=gdir)
    out = r.resolve("1.19.0.6")
    assert out["available"] is True
    assert out["save_game_version"] == "1.19.0.6"
    # exe PE 版本资源只含启动器壳版本，不伪造真实游戏版本
    assert out["installed_game_version"] is None
    assert out["version_match"] is None
    assert out["dlc_count"] == 1


def test_unavailable_when_missing():
    r = GameDataResolver(game_dir=r"Z:\no\such\game")
    assert r.is_available() is False
    assert r.list_dlc() == []
    out = r.resolve("1.19.0.6")
    assert out["available"] is False
    assert out["dlc_count"] == 0


def test_real_install_dlc():
    if not HAVE_REAL:
        import pytest

        pytest.skip("本机未安装 CK3（E:\\SteamLibrary\\... 不可访问）")
    r = GameDataResolver(game_dir=REAL_GAME_DIR)
    assert r.is_available()
    dlcs = r.list_dlc()
    assert len(dlcs) > 0
    names = {d["name"] for d in dlcs}
    # 真实存档使用的是 1.19.0.6，对应多个官方 DLC；至少能解析出真实展示名
    assert any("Fashion of the Abbasid Court" == n for n in names)
    out = r.resolve("1.19.0.6")
    assert out["dlc_count"] == len(dlcs)
