#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从本机 Crusader Kings III 可执行文件中提取二进制存档的 token 表（id -> 名称）。

背景
----
CK3 的二进制（铁人 / SAV0101）存档把所有字段名压缩成 16 位 token id。
把它们还原成可读名称需要一张 id -> name 映射表。这张表属于 Paradox 的
游戏资产，**不允许随第三方项目分发**，因此 SHIGUAN 仓库里只提交一份
占位表（tokens/ck3_tokens.txt，65536 条 id -> tXXXX），保证任何存档都能
完整 melt，但字段名不可读。

本脚本让用户从**自己已购买、已安装**的游戏可执行文件中生成真实令牌表，
输出文件默认落在 tokens/ck3_tokens_real.txt（已被 .gitignore 排除）。

表结构（CK3 1.19 实测）
-----------------------
.rdata 段中存在一段连续的 16 字节条目数组：

    struct Entry {          // 小端
        uint64_t token_id;  // 1 .. 0xFFFF
        const char* name;   // 指向 .rdata 里的 NUL 结尾 ASCII 标识符
    };

数组以稀疏方式排列（token id 递增但有空洞）。本脚本先用三元锚点
`living / dead_prunable / dead_unprunable`（人物容器，id 连续）定位数组，
再向两端扩展。

用法
----
    python extract_tokens.py                       # 自动定位游戏目录
    python extract_tokens.py --exe "D:/CK3/binaries/ck3.exe"
    python extract_tokens.py --out tokens/my.txt --verify

退出码
------
    0 成功；2 找不到可执行文件；3 锚点校验失败（游戏版本漂移）。
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import sys
from pathlib import Path

# 锚点：这三个 token 是人物容器，在所有 CK3 版本里都存在且 id 连续。
# 用它们定位数组并校验"id 在前、指针在后"的字段顺序。
ANCHOR_NAMES = ("living", "dead_prunable", "dead_unprunable")

# 提取后必须命中的字段名，用于验证表的正确性（版本漂移检测）。
SANITY_TOKENS = {
    "living": None,
    "dead_prunable": None,
    "dead_unprunable": None,
    "first_name": None,
    "birth": None,
    "traits": None,
    "family_data": None,
    "alive_data": None,
    "dead_data": None,
    "landed_data": None,
    "landed_titles": None,
    "culture": None,
    "faith": None,
    "dynasty_house": None,
}

_IDENT_RE = re.compile(rb"^[A-Za-z_][A-Za-z0-9_.\-]{0,63}$")
_MAX_TOKEN_ID = 0xFFFF
_ENTRY_SIZE = 16
_HOLE_TOLERANCE = 4  # 连续多少个无效槽位后认为数组结束


class PeImage:
    """最小可用的 PE32+ 只读视图，仅提供 VA <-> 文件偏移换算。"""

    def __init__(self, data: bytes) -> None:
        self.data = data
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        if data[e_lfanew : e_lfanew + 4] != b"PE\0\0":
            raise ValueError("不是有效的 PE 文件")
        coff = e_lfanew + 4
        n_sections = struct.unpack_from("<H", data, coff + 2)[0]
        opt_size = struct.unpack_from("<H", data, coff + 16)[0]
        opt = coff + 20
        if struct.unpack_from("<H", data, opt)[0] != 0x20B:
            raise ValueError("只支持 PE32+ (64 位) 可执行文件")
        self.image_base = struct.unpack_from("<Q", data, opt + 24)[0]
        self.sections = []
        for i in range(n_sections):
            off = opt + opt_size + i * 40
            name = data[off : off + 8].rstrip(b"\0").decode("ascii", "replace")
            vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", data, off + 8)
            self.sections.append((name, va, vsize, raw_ptr, raw_size))
        self._str_cache: dict[int, str | None] = {}

    def offset_to_va(self, offset: int) -> int | None:
        for _name, va, _vsize, raw_ptr, raw_size in self.sections:
            if raw_ptr <= offset < raw_ptr + raw_size:
                return self.image_base + va + (offset - raw_ptr)
        return None

    def va_to_offset(self, va: int) -> int | None:
        rva = va - self.image_base
        for _name, sec_va, _vsize, raw_ptr, raw_size in self.sections:
            if sec_va <= rva < sec_va + raw_size:
                return raw_ptr + (rva - sec_va)
        return None

    def read_identifier(self, va: int) -> str | None:
        """读取 VA 处的 NUL 结尾字符串；只接受标识符样式，避免误判。"""
        cached = self._str_cache.get(va)
        if cached is not None or va in self._str_cache:
            return cached
        result: str | None = None
        offset = self.va_to_offset(va)
        if offset is not None:
            end = self.data.find(b"\0", offset, offset + 80)
            if end > offset:
                raw = self.data[offset:end]
                if _IDENT_RE.match(raw):
                    try:
                        result = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        result = None
        self._str_cache[va] = result
        return result


def _find_anchor(pe: PeImage) -> tuple[int, int]:
    """返回 (锚点条目文件偏移, 锚点 token id)。

    先找 `living` 字符串的唯一指针，再确认其前 8 字节是一个合法 token id，
    且后续两个条目分别是 dead_prunable / dead_unprunable（id 连续 +1/+2）。
    """
    str_offset = pe.data.find(b"living\0")
    if str_offset < 0:
        raise LookupError("可执行文件里找不到 'living' 字符串")
    str_va = pe.offset_to_va(str_offset)
    if str_va is None:
        raise LookupError("'living' 字符串不在任何有效节区内")

    needle = struct.pack("<Q", str_va)
    pointer_locations = [m.start() for m in re.finditer(re.escape(needle), pe.data)]
    if not pointer_locations:
        raise LookupError("找不到指向 'living' 的指针，可能是不支持的游戏版本")

    for ptr_loc in pointer_locations:
        entry = ptr_loc - 8  # id 在指针之前
        if entry < 0 or entry % 8 != 0:
            continue
        token_id = struct.unpack_from("<Q", pe.data, entry)[0]
        if not 0 < token_id <= _MAX_TOKEN_ID:
            continue
        ok = True
        for step, expected in enumerate(ANCHOR_NAMES):
            probe = _read_entry(pe, entry + step * _ENTRY_SIZE)
            if probe is None or probe[0] != token_id + step or probe[1] != expected:
                ok = False
                break
        if ok:
            return entry, token_id
    raise LookupError("锚点校验失败：token 表布局与预期不符（游戏版本可能已变更）")


def _read_entry(pe: PeImage, offset: int) -> tuple[int, str] | None:
    if offset < 0 or offset + _ENTRY_SIZE > len(pe.data):
        return None
    token_id, name_va = struct.unpack_from("<QQ", pe.data, offset)
    if not 0 < token_id <= _MAX_TOKEN_ID:
        return None
    if not pe.image_base < name_va < pe.image_base + 0x1000_0000:
        return None
    name = pe.read_identifier(name_va)
    if name is None:
        return None
    return token_id, name


def _scan_table(pe: PeImage, anchor: int) -> dict[int, str]:
    """从锚点向两端扩展，收集整张 token 表。"""
    start = anchor
    holes = 0
    while start - _ENTRY_SIZE >= 0:
        if _read_entry(pe, start - _ENTRY_SIZE) is None:
            holes += 1
            if holes > _HOLE_TOLERANCE:
                break
        else:
            holes = 0
        start -= _ENTRY_SIZE

    end = anchor
    holes = 0
    while end + _ENTRY_SIZE <= len(pe.data) - _ENTRY_SIZE:
        if _read_entry(pe, end + _ENTRY_SIZE) is None:
            holes += 1
            if holes > _HOLE_TOLERANCE:
                break
        else:
            holes = 0
        end += _ENTRY_SIZE

    table: dict[int, str] = {}
    offset = start
    while offset <= end:
        entry = _read_entry(pe, offset)
        if entry is not None:
            token_id, name = entry
            # 同 id 冲突时保留首次出现，避免相邻数据结构污染。
            table.setdefault(token_id, name)
        offset += _ENTRY_SIZE
    return table


def _default_exe() -> Path | None:
    game_dir = os.environ.get("SHIGUAN_CK3_GAME_DIR")
    candidates = []
    if game_dir:
        candidates.append(Path(game_dir) / "binaries" / "ck3.exe")
    exe_env = os.environ.get("CK3_EXE")
    if exe_env:
        candidates.insert(0, Path(exe_env))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="从本机 CK3 可执行文件提取二进制存档 token 表（不随仓库分发）"
    )
    parser.add_argument(
        "--exe",
        type=Path,
        default=None,
        help="ck3.exe 路径；缺省时读取 CK3_EXE 或 SHIGUAN_CK3_GAME_DIR 环境变量",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "tokens" / "ck3_tokens_real.txt",
        help="输出文件（默认 tokens/ck3_tokens_real.txt，已被 .gitignore 排除）",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="额外打印若干关键 token 以人工核对",
    )
    parser.add_argument(
        "--no-pad",
        action="store_true",
        help="不要用 tXXXX 占位补齐未提取到的 id（默认补齐，保证任何存档都不丢数据）",
    )
    args = parser.parse_args(argv)

    exe_path = args.exe or _default_exe()
    if exe_path is None or not Path(exe_path).is_file():
        print(
            "找不到 ck3.exe。请用 --exe 指定，或设置 SHIGUAN_CK3_GAME_DIR / CK3_EXE。",
            file=sys.stderr,
        )
        return 2

    data = Path(exe_path).read_bytes()
    pe = PeImage(data)
    try:
        anchor, anchor_id = _find_anchor(pe)
    except LookupError as exc:
        print(f"提取失败：{exc}", file=sys.stderr)
        print(
            "这通常意味着游戏版本更新导致 token 表布局变化；"
            "请提交 issue 并附上游戏版本号。",
            file=sys.stderr,
        )
        return 3

    table = _scan_table(pe, anchor)

    names = set(table.values())
    missing = sorted(name for name in SANITY_TOKENS if name not in names)
    if missing:
        print(
            f"警告：以下关键 token 未出现在提取结果中，表可能不完整：{missing}",
            file=sys.stderr,
        )

    extracted_count = len(table)
    id_lo, id_hi = min(table), max(table)

    # 补齐：未提取到的 id 回落成占位名 tXXXX。
    # 这样 melt 遇到任何 token 都能识别（不会跳过整段 value），
    # 既拿到真实字段名，又保留"绝不丢数据"的性质。
    written = table
    if not args.no_pad:
        written = {
            token_id: table.get(token_id, f"t{token_id:04x}")
            for token_id in range(_MAX_TOKEN_ID + 1)
        }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for token_id in sorted(written):
            handle.write(f"{token_id} {written[token_id]}\n")

    print(f"锚点 id=0x{anchor_id:04x} ('living') @ 文件偏移 0x{anchor:x}")
    print(f"提取 token 数：{extracted_count}（id 范围 0x{id_lo:x} .. 0x{id_hi:x}）")
    if not args.no_pad:
        print(f"占位补齐后总条目：{len(written)}（未知 id 记作 tXXXX）")
    print(f"已写入：{out_path}")
    if args.verify:
        reverse = {v: k for k, v in table.items()}
        for name in sorted(SANITY_TOKENS):
            token_id = reverse.get(name)
            shown = f"0x{token_id:04x}" if token_id is not None else "<缺失>"
            print(f"   {name:<18} {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
