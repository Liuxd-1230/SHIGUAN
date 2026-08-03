"""Known Folder API 测试（规范七）：可注入解析函数，不依赖真实 Windows 用户目录。

所有用例只在 pytest tmp_path 下造目录，绝不写真实个人目录（C:\\Users\\...）。
仅 Windows 执行的 smoke test 直接调用真实 SHGetKnownFolderPath，验证 ctypes GUID 结构正确。
"""
from __future__ import annotations

import sys

import pytest
from pathlib import Path

from app.services.known_folder import (
    GUID,
    _known_folder_documents,
    resolve_ck3_user_dir,
    resolve_documents_dir,
)


def test_guid_struct_layout():
    """GUID 结构逐字节对齐 Windows KNOWNFOLDERID（16 字节，前 3 段与本机字节序一致）。"""
    g = GUID.from_string("FDD39AD0-238F-46AF-ADB4-6C85480369C7")
    assert g.Data1 == 0xFDD39AD0
    assert g.Data2 == 0x238F
    assert g.Data3 == 0x46AF
    assert bytes(g.Data4) == bytes.fromhex("ADB46C85480369C7")
    import ctypes

    assert ctypes.sizeof(g) == 16


# 仅 Windows 执行：真实调用 SHGetKnownFolderPath，验证修复后的 ctypes GUID 调用。
win32_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="仅 Windows：需真实 shell32.SHGetKnownFolderPath（已知文件夹 API）",
)



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


@win32_only
def test_real_shgetknownfolderpath_returns_documents():
    """真实调用：SHGetKnownFolderPath(FOLDERID_Documents) 返回存在的 Documents 目录。"""
    result = _known_folder_documents()
    assert result is not None
    assert Path(result).exists()


@win32_only
def test_real_resolve_documents_dir_without_inject():
    """无 inject 时真实走 Known Folder API（CI 在 ubuntu 自动跳过，本地 Windows 实际执行）。"""
    docs, source = resolve_documents_dir(inject=None)
    assert docs is not None
    assert source in ("known_folder", "onedrive", "userprofile", "setting")
    assert Path(docs).exists()
