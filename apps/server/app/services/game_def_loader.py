"""GameDefLoader —— 读取 CK3 游戏定义文件（game/common），建立实体 def 键 → 本地化键 的映射。

职责（M2.4）：
  - 读 game/common/dynasties/*.txt 与 **/houses.txt：dynasty / house 的区块键 → name 本地化键。
  - 读 game/common/court_positions/**/*.txt：court position type → name 本地化键。
  - 读 game/common/character_memory_types/**/*.txt：memory type → name 本地化键。
  - 这些 def 键来自 Rust entities.json 里 key_kind="def" 的实体，或本身就是游戏定义区块键的
    类型集合（court position / memory type）。有了 name 本地化键后，LocalizationLoader 才能
    给出可读中文名。

设计：
  - 只读扫描 game/common；不复制、不修改游戏文件。
  - 游戏目录缺失（未安装 CK3 或未设 SHIGUAN_CK3_GAME_DIR）→ 全部返回空映射，优雅降级为 unresolved，
    绝不报错、绝不伪造名字。
  - 采用轻量栈式 PDX 文本解析：提取 depth-1 区块的区块键与其最近 name 字段，足够覆盖
    dynasty/house/court position/memory type 的定义结构（嵌套块不至于误吞 name）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional

# 区块开： key = {  （数字键如 "2" 也接受）
_BLOCK_OPEN_RE = re.compile(r'^\s*([A-Za-z0-9_.\-/]+)\s*=\s*\{')
# name 字段：name = "x" 或 name = x（允许出现在行内，如自包含块 key = { name = "x" }）
_NAME_RE = re.compile(r'(?:^|\s)name\s*=\s*(?:"([^"\r\n]*)"|([^\s\r\n"]+))')

# 需要建立映射的实体类别（与 EntityKind 对齐的子集）
_DEF_KINDS = ("dynasty", "house", "courtPositionType", "memoryType")


def _parse_name_map(text: str) -> Dict[str, str]:
    """从一段 PDX 文本提取 区块键 -> name(本地化键) 映射（栈式，支持任意嵌套）。"""
    out: Dict[str, str] = {}
    # 栈元素：[区块键, name 或 None]；None 键为占位（如 "= {" 续行），仅用于对齐深度。
    stack: list[list[Optional[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("@"):
            continue
        opens = line.count("{")
        closes = line.count("}")
        if opens > 0:
            m = _BLOCK_OPEN_RE.match(line)
            if m:
                stack.append([m.group(1), None])
            else:
                # 没有 key 的裸开块（如 "= {"）—— 推占位以保持深度对齐。
                stack.append([None, None])
            # 同一行内的 name（自包含块 key = { name = "x" }）：挂到栈顶。
            nm = _NAME_RE.search(line)
            if nm and stack and stack[-1][1] is None:
                val = nm.group(1) or nm.group(2)
                if val is not None:
                    stack[-1][1] = val.strip().strip('"')
        else:
            nm = _NAME_RE.search(line)
            if nm and stack and stack[-1][1] is None:
                val = nm.group(1) or nm.group(2)
                if val is not None:
                    stack[-1][1] = val.strip().strip('"')
        for _ in range(closes):
            if stack:
                key, name = stack.pop()
                if key and name:
                    out[key] = name
    return out


class GameDefLoader:
    """读取 game/common，建立 def 键 → name 本地化键 的映射。"""

    def __init__(self, game_dir: str | Path | None = None) -> None:
        self.game_dir = Path(game_dir) if game_dir else None
        # kind -> { def_key: name_loc_key }
        self._maps: Dict[str, Dict[str, str]] = {k: {} for k in _DEF_KINDS}

    def is_available(self) -> bool:
        return self.game_dir is not None and self.game_dir.exists()

    def load(self) -> Dict[str, Dict[str, str]]:
        """扫描 game/common，填充映射。缺失目录时返回空映射（优雅降级）。"""
        maps: Dict[str, Dict[str, str]] = {k: {} for k in _DEF_KINDS}
        if not self.is_available():
            self._maps = maps
            return maps

        common = self.game_dir / "game" / "common"  # type: ignore[union-attr]
        if common.exists():
            # dynasty：dynasties 下所有 .txt（排除 houses.txt）
            dyn_root = common / "dynasties"
            if dyn_root.exists():
                for f in dyn_root.rglob("*.txt"):
                    if f.name == "houses.txt":
                        continue
                    maps["dynasty"].update(self._read(f))
                # house：所有 houses.txt
                for f in dyn_root.rglob("houses.txt"):
                    maps["house"].update(self._read(f))
            # court position types
            cp_root = common / "court_positions"
            if cp_root.exists():
                for f in cp_root.rglob("*.txt"):
                    maps["courtPositionType"].update(self._read(f))
            # memory types
            mem_root = common / "character_memory_types"
            if mem_root.exists():
                for f in mem_root.rglob("*.txt"):
                    maps["memoryType"].update(self._read(f))

        self._maps = maps
        return maps

    @staticmethod
    def _read(path: Path) -> Dict[str, str]:
        try:
            return _parse_name_map(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return {}

    def lookup(self, kind: str, def_key: str | None) -> Optional[str]:
        """返回 def 键对应的 name 本地化键；未命中返回 None（调用方据此标 unresolved）。"""
        if not def_key:
            return None
        return self._maps.get(kind, {}).get(def_key)

    def merge(self, other: "GameDefLoader") -> None:
        """叠加另一个加载器（如 Mod 覆盖游戏定义）。后加载覆盖先加载。"""
        for k in _DEF_KINDS:
            self._maps.setdefault(k, {})
            self._maps[k].update(other._maps.get(k, {}))

    def stats(self) -> Dict[str, int]:
        return {k: len(v) for k, v in self._maps.items()}
