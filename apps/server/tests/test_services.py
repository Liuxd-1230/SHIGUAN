"""DirectoryWatcher / GameDataResolver / SaveRegistry / settings_store 单测。"""
import time
from pathlib import Path

from app.services.directory_watcher import DirectoryWatcher
from app.services.game_data_resolver import GameDataResolver
from app.services.save_registry import SaveRegistry, wait_until_stable


def test_watcher_detects_add_change_remove(tmp_path):
    watcher = DirectoryWatcher(tmp_path, interval=0.1)
    added, removed, changed = watcher.poll_once()
    assert added == [] and removed == [] and changed == []

    f = tmp_path / "autosave.ck3"
    f.write_bytes(b"SAV0101" + b"\x00" * 10)
    added, removed, changed = watcher.poll_once()
    assert len(added) == 1 and added[0].name == "autosave.ck3"
    assert removed == [] and changed == []

    time.sleep(0.01)
    f.write_bytes(b"SAV0101" + b"\x00" * 20)
    added, removed, changed = watcher.poll_once()
    assert len(changed) == 1 and changed[0].name == "autosave.ck3"

    f.unlink()
    added, removed, changed = watcher.poll_once()
    assert len(removed) == 1 and removed[0].name == "autosave.ck3"


def test_watcher_callback(tmp_path):
    events = []
    watcher = DirectoryWatcher(
        tmp_path, interval=0.1, on_change=lambda a, r, c: events.append((a, r, c))
    )
    (tmp_path / "x.ck3").write_bytes(b"data")
    watcher.poll_once()
    assert len(events) == 1
    assert len(events[0][0]) == 1


def test_game_data_resolver_unavailable(monkeypatch):
    monkeypatch.setattr(
        "app.services.game_data_resolver.GameDataResolver._find_game_dir",
        staticmethod(lambda: None),
    )
    r = GameDataResolver()
    assert r.is_available() is False
    info = r.resolve("1.19.0.6")
    assert info["available"] is False
    assert info["save_game_version"] == "1.19.0.6"
    assert info["installed_game_version"] is None
    assert info["dlc_count"] == 0


def test_game_data_resolver_with_dir(tmp_path):
    r = GameDataResolver(game_dir=str(tmp_path))
    assert r.is_available() is True
    info = r.resolve("1.19.0.6")
    assert info["available"] is True
    assert info["game_dir"] == str(tmp_path)
    assert info["save_game_version"] == "1.19.0.6"
    assert info["dlc_count"] == 0


def test_wait_until_stable_static_file(tmp_path):
    f = tmp_path / "s.ck3"
    f.write_bytes(b"x" * 100)
    assert wait_until_stable(f, poll=0.05, stable_for=0.1, timeout=3) is True


def test_save_registry_register_and_stage(tmp_path):
    src = tmp_path / "autosave.ck3"
    src.write_bytes(b"SAV0101" + b"\x00" * 50)
    staging = tmp_path / "staging"
    reg = SaveRegistry(staging)
    rec = reg.register(src)
    assert rec.save_id
    assert rec.staging_path is None  # 列出时不复制
    # 按需复制稳定副本
    rec2 = reg.ensure_staged(rec.save_id)
    assert rec2.staging_path and Path(rec2.staging_path).exists()
    # 原文件未被修改
    assert src.exists()
    assert src.read_bytes() == b"SAV0101" + b"\x00" * 50
    # 副本大小一致
    assert Path(rec2.staging_path).stat().st_size == src.stat().st_size
    # 删除清理副本
    assert reg.remove(rec.save_id) is True
    assert not Path(rec2.staging_path).exists()


def test_save_registry_unknown_id(tmp_path):
    reg = SaveRegistry(tmp_path / "staging")
    import pytest

    with pytest.raises(KeyError):
        reg.ensure_staged("deadbeef")


def test_settings_store_roundtrip(tmp_path, monkeypatch):
    import app.services.settings_store as ss

    monkeypatch.setattr(ss, "SETTINGS_PATH", tmp_path / "server-settings.json")
    # 不存在的目录应被拒绝
    import pytest

    with pytest.raises(ValueError):
        ss.save_settings({"saves_dir": str(tmp_path / "nope")})
    # 存在的目录可保存并读回
    d = tmp_path / "ok"
    d.mkdir()
    saved = ss.save_settings({"saves_dir": str(d)})
    assert saved["saves_dir"] == str(d)
    assert ss.load_settings()["saves_dir"] == str(d)
