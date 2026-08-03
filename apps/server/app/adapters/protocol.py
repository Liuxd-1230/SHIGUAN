"""存档初检（SaveInspection）—— 只读文件头，绝不解析内容本身。

检测逻辑来自 docs/save-format-notes.md：
  1. 探测文件尾部 ZIP EOCD 签名（50 4B 05 06）或头部 PK\\x03\\x04 → zip 容器。
  2. zip 内 gamestate 头第 3、4 字节为 01 00 → ironman；否则按二进制/明文特征区分。
  3. 无 zip → 未压缩自动存档 gamestate：尝试 UTF-8 解码 + Clausewitz 结构 → text；
     含 null 字节（二进制特征）或解码失败 → binary。

本模块不调用 ck3-reader，仅做廉价头检测；真正的 melt/解析由 Ck3ReaderAdapter 完成。
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

from models import Encoding, MissingComponent, SaveInspection, SaveKind

from app.config import resolve_reader_binary

_ZIP_EOCD = b"PK\x05\x06"
_ZIP_LOCAL = b"PK\x03\x04"
_ZIP_CENTRAL = b"PK\x01\x02"
_SAV_MAGIC = b"SAV0101"


def _peek_zip_gamestate_kind(data: bytes) -> tuple[SaveKind, bool]:
    """根据 zip 内首段的字节特征区分 ironman / binary_zip / text_zip。"""
    # bytes[2:4] == 01 00 → ironman（来自 ck3save 头结构）
    if len(data) >= 4 and data[2:4] == b"\x01\x00":
        return SaveKind.IRONMAN, True
    # 含大量 null 字节 → 二进制 gamestate
    sample = data[:4096]
    if b"\x00" in sample:
        return SaveKind.BINARY_ZIP, True
    # 否则当作明文 zip
    return SaveKind.TEXT_ZIP, True


def _inspect_zip(path: Path) -> tuple[SaveKind, bool]:
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if not names:
                return SaveKind.BINARY_ZIP, True
            # gamestate 通常在压缩包内；取第一个条目头部探测
            with zf.open(names[0]) as fh:
                head = fh.read(8192)
            return _peek_zip_gamestate_kind(head)
    except zipfile.BadZipFile:
        # 头部像 zip 但打不开：保守归为二进制 zip
        return SaveKind.BINARY_ZIP, True


def _inspect_raw_gamestate(path: Path) -> tuple[SaveKind, Encoding]:
    """未压缩自动存档 gamestate：区分 text / binary。"""
    with open(path, "rb") as f:
        head = f.read(8192)
    if _SAV_MAGIC in head[:16]:
        # SAV0101 头之后的 gamestate 可能仍是二进制或明文
        body = head.split(_SAV_MAGIC, 1)[-1]
    else:
        body = head
    if b"\x00" in body[:4096]:
        return SaveKind.BINARY, Encoding.UNKNOWN
    # 尝试按 UTF-8 解码；成功且无替换字符 → 明文
    try:
        text = body.decode("utf-8")
        if "\ufffd" in text:
            return SaveKind.BINARY, Encoding.UNKNOWN
        return SaveKind.TEXT, Encoding.UTF8
    except UnicodeDecodeError:
        return SaveKind.BINARY, Encoding.UNKNOWN


def inspect_save(path: str | Path) -> SaveInspection:
    """廉价头检测，产出 SaveInspection。不 melt、不解析内容。"""
    p = Path(path)
    size = p.stat().st_size

    with open(p, "rb") as f:
        header = f.read(8)
    with open(p, "rb") as f:
        f.seek(max(0, size - 65536))
        tail = f.read(65536)

    is_compressed = False
    is_ironman = False
    kind: SaveKind

    if header[:4] == _ZIP_LOCAL or _ZIP_EOCD in tail or _ZIP_CENTRAL in tail:
        is_compressed = True
        kind, _ = _inspect_zip(p)
        is_ironman = kind == SaveKind.IRONMAN
    elif header[:7] == _SAV_MAGIC:
        kind, enc = _inspect_raw_gamestate(p)
        is_ironman = False
    else:
        # 既非 zip 也非 SAV0101：最后尝试明文检测，失败则视为不支持。
        kind, enc = _inspect_raw_gamestate(p)
        is_ironman = False
        if kind != SaveKind.TEXT:
            return SaveInspection(
                path=str(p),
                kind=SaveKind.BINARY,
                encoding=Encoding.UNKNOWN,
                sizeBytes=size,
                isCompressed=False,
                isIronman=False,
                canParseLocally=False,
                needsExternal=False,
            )

    # 二进制/铁人需要外部解析组件（ck3-reader sidecar）
    reader = resolve_reader_binary()
    needs_external = kind in (
        SaveKind.BINARY,
        SaveKind.BINARY_ZIP,
        SaveKind.IRONMAN,
    )
    can_local = (not needs_external) or (reader is not None)
    missing = None
    if needs_external and reader is None:
        missing = MissingComponent(
            name="ck3-reader",
            hint="在 tools/ck3-reader 下执行 build.sh（cargo build --release）构建 Rust sidecar 二进制",
        )

    encoding = Encoding.UTF8 if kind in (SaveKind.TEXT, SaveKind.TEXT_ZIP) else Encoding.UNKNOWN

    return SaveInspection(
        path=str(p),
        kind=kind,
        encoding=encoding,
        sizeBytes=size,
        isCompressed=is_compressed,
        isIronman=is_ironman,
        canParseLocally=can_local,
        needsExternal=needs_external,
        missingComponent=missing,
    )
