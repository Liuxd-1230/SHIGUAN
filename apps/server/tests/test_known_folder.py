"""Known Folder API 测试（规范七）：可注入解析函数，不依赖真实 Windows 用户目录。

所有用例只在 pytest tmp_path 下造目录，绝不写真实个人目录（C:\\Users\\...）。
"""
from __future__ import annotations

from pathlib import Path

from app.services.known_folder import resolve_ck3_user_dir, resolve_documents_dir


def _clear_env(monkeypatch):
    for k in ("OneDrive", "OneDriveConsumer", "USERPROFILE", "HOME"):
        monkeypatch.delenv(k, raising=False)


def test_inject_known_folder(monkeypatch, tmp_path):
    """注入的 Known Folder 目录存在时优先采用，来源标记 known_folder。"""
    _clear_env(monkeypatch)
    docs_dir = tmp_path / "Documents"
    docs_dir.mkdir()

    docs, source = resolve_documents_dir(inject=lambda: str(docs_dir))
    assert Path(docs) == docs_dir
    assert source == "known_folder"


def test_known_folder_missing_falls_through(monkeypatch, tmp_path):
    """Known Folder 返回不存在的路径 → 不采用，继续回退链（绝不伪造）。"""
    _clear_env(monkeypatch)
    up = tmp_path / "profile"
    (up / "Documents").mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(up))

    docs, source = resolve_documents_dir(inject=lambda: str(tmp_path / "does-not-exist"))
    assert source == "userprofile"
    assert Path(docs) == up / "Documents"


def test_setting_wins_over_known_folder(monkeypatch, tmp_path):
    """用户已保存的设置目录优先级最高。"""
    _clear_env(monkeypatch)
    saved = tmp_path / "user-chosen"
    saved.mkdir()
    kf = tmp_path / "Documents"
    kf.mkdir()

    docs, source = resolve_documents_dir(inject=lambda: str(kf), settings_dir=str(saved))
    assert Path(docs) == saved
    assert source == "setting"


def test_fallback_userprofile(monkeypatch, tmp_path):
    """无 inject、无 Known Folder、无 OneDrive 时回退 USERPROFILE/Documents。"""
    _clear_env(monkeypatch)
    up = tmp_path / "profile"
    (up / "Documents").mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(up))

    docs, source = resolve_documents_dir(inject=lambda: None)
    assert source == "userprofile"
    assert Path(docs) == up / "Documents"


def test_onedrive_fallback(monkeypatch, tmp_path):
    """OneDrive 接管 Documents 时优先于 USERPROFILE 拼接。"""
    _clear_env(monkeypatch)
    od = tmp_path / "OneDrive"
    (od / "Documents").mkdir(parents=True)
    up = tmp_path / "profile"
    (up / "Documents").mkdir(parents=True)
    monkeypatch.setenv("OneDrive", str(od))
    monkeypatch.setenv("USERPROFILE", str(up))

    docs, source = resolve_documents_dir(inject=lambda: None)
    assert source == "onedrive"
    assert Path(docs) == od / "Documents"


def test_no_source_returns_none(monkeypatch, tmp_path):
    """全部来源缺失时返回 (None, 'none')，绝不编造路径。"""
    _clear_env(monkeypatch)
    docs, source = resolve_documents_dir(inject=lambda: None)
    assert docs is None
    assert source == "none"


def test_ck3_user_dir_requires_save_games(monkeypatch, tmp_path):
    """Documents 下没有 CK3 目录 → 返回 None，不伪造路径。"""
    _clear_env(monkeypatch)
    docs_dir = tmp_path / "Documents"
    docs_dir.mkdir()

    ck3, source = resolve_ck3_user_dir(inject=lambda: str(docs_dir))
    assert ck3 is None
    assert source == "known_folder"


def test_ck3_user_dir_found(monkeypatch, tmp_path):
    """Documents/Paradox Interactive/Crusader Kings III 存在时返回它。"""
    _clear_env(monkeypatch)
    docs_dir = tmp_path / "Documents"
    ck3_dir = docs_dir / "Paradox Interactive" / "Crusader Kings III"
    (ck3_dir / "save games").mkdir(parents=True)

    ck3, source = resolve_ck3_user_dir(inject=lambda: str(docs_dir))
    assert Path(ck3) == ck3_dir
    assert source == "known_folder"
