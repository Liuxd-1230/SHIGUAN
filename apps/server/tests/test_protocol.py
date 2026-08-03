"""SaveInspection 头检测单测（不 melt、不调用 ck3-reader）。

构造合成样本验证魔数/zip 判定逻辑。reader 可用性通过 monkeypatch 控制，
确保 missingComponent 逻辑也被覆盖。
"""
import zipfile
from pathlib import Path

import pytest

from app.adapters.protocol import inspect_save
from app.config import resolve_reader_binary
from models import SaveKind


def _write(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    return str(path)


def test_binary_autosave_header(tmp_path, monkeypatch):
    # SAV0101 头 + 含 null 字节的二进制体 → binary / 需外部组件
    monkeypatch.setattr("app.adapters.protocol.resolve_reader_binary", lambda: resolve_reader_binary())
    p = tmp_path / "autosave.ck3"
    _write(p, b"SAV0101" + b"\x00\x01\x02" + b"gamestate" + b"\x00" * 200)
    res = inspect_save(p)
    assert res.kind == SaveKind.BINARY
    assert res.isCompressed is False
    assert res.encoding.value == "unknown"
    assert res.needsExternal is True
    # reader 存在时本地可解析
    assert res.canParseLocally is True


def test_unsupported_file_without_reader(tmp_path, monkeypatch):
    # reader 缺失时，二进制需要外部组件 → 报 missingComponent
    monkeypatch.setattr("app.adapters.protocol.resolve_reader_binary", lambda: None)
    p = tmp_path / "autosave.ck3"
    _write(p, b"SAV0101" + b"\x00" * 200)
    res = inspect_save(p)
    assert res.kind == SaveKind.BINARY
    assert res.needsExternal is True
    assert res.canParseLocally is False
    assert res.missingComponent is not None
    assert res.missingComponent.name == "ck3-reader"


def test_zip_container_detected(tmp_path):
    # 构造一个最小 zip（非 CK3 内容），应被识别为压缩
    p = tmp_path / "save.ck3"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("gamestate", b"dummy")
    res = inspect_save(p)
    assert res.isCompressed is True
    assert res.kind in (SaveKind.TEXT_ZIP, SaveKind.BINARY_ZIP, SaveKind.IRONMAN)


def test_plaintext_save_detected(tmp_path, monkeypatch):
    # 明文 Clausewitz（无 SAV0101、无 zip、无 null 字节）→ text / 本地可解析
    monkeypatch.setattr("app.adapters.protocol.resolve_reader_binary", lambda: None)
    p = tmp_path / "debug.ck3"
    body = "CK3txt\nplayer=\"x\"\ngamestate={\n  date=762.1.1\n}\n".encode("utf-8")
    _write(p, body)
    res = inspect_save(p)
    assert res.kind == SaveKind.TEXT
    assert res.needsExternal is False
    assert res.canParseLocally is True
    assert res.encoding.value == "utf-8"


def test_non_ck3_binary_is_unsupported(tmp_path, monkeypatch):
    # 随机二进制、非 SAV0101、非 zip → 无法识别为明文 → 不支持
    monkeypatch.setattr("app.adapters.protocol.resolve_reader_binary", lambda: None)
    p = tmp_path / "random.bin"
    _write(p, b"\x00\x01\x02\x03" + b"\xff" * 100)
    res = inspect_save(p)
    assert res.canParseLocally is False
    assert res.needsExternal is False
