"""GameDataResolver —— 关联存档与本地 CK3 游戏安装的真实数据。

职责：
  - 定位 CK3 安装目录（环境变量 SHIGUAN_CK3_GAME_DIR 优先；其次 Steam 默认路径；
    再退而扫描常见 Steam 库根目录）。绝不把个人本地路径硬编码进源码。
  - 从安装目录读取**真实 DLC 列表**（`game/dlc/dlcNNN_*/dlcNNN.dlc` 为 PDX 文本，
    首行 `name = "..."` 即真实展示名）。
  - 关联存档自报的 game_version，做版本一致性提示（本机 exe 的 PE 版本资源只含
    启动器壳版本 1.0.0.0，不含真实游戏版本，故 installed_game_version 通常取不到，
    version_match 可能为 None —— 绝不伪造）。

所有读取均为只读元数据（目录名、DLC 文本），不复制游戏文件、不读取用户存档内容。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from app.services.localization import LocalizationLoader


_DLC_ID_RE = re.compile(r"^dlc\d+")
_NAME_RE = re.compile(r'^\s*name\s*=\s*"(?P<name>[^"]*)"')
_PATH_RE = re.compile(r'^\s*path\s*=\s*"(?P<path>[^"]*)"')


class GameDataResolver:
    def __init__(self, game_dir: str | Path | None = None) -> None:
        self.game_dir = Path(game_dir) if game_dir else self._find_game_dir()

    # -- 目录定位 -------------------------------------------------------------
    @staticmethod
    def _find_game_dir() -> Optional[Path]:
        # 1) 显式环境变量（本地 .env 提供，不进仓库）
        env = os.environ.get("SHIGUAN_CK3_GAME_DIR")
        if env and Path(env).exists():
            return Path(env)
        # 2) Steam 默认安装（ProgramFiles）
        steam = os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles")
        if steam:
            cand = Path(steam) / "Steam" / "steamapps" / "common" / "Crusader Kings III"
            if cand.exists():
                return cand
        # 3) 常见 Steam 库根目录（通用启发式，非个人路径）
        for drive in ("C", "D", "E", "F"):
            cand = Path(f"{drive}:/SteamLibrary/steamapps/common/Crusader Kings III")
            if cand.exists():
                return cand
        return None

    def is_available(self) -> bool:
        return self.game_dir is not None and self.game_dir.exists()

    # -- DLC 列表（真实展示名） ------------------------------------------------
    def list_dlc(self) -> list[dict]:
        """读取 game/dlc/ 下每个 dlcNNN_*/dlcNNN.dlc 的首个 name 字段。"""
        if not self.is_available():
            return []
        dlc_root = self.game_dir / "game" / "dlc"  # type: ignore[union-attr]
        if not dlc_root.exists():
            return []
        out: list[dict] = []
        for folder in sorted(dlc_root.iterdir()):
            if not folder.is_dir() or not _DLC_ID_RE.match(folder.name):
                continue
            # 形如 dlc002.dlc
            dlc_file = folder / f"{folder.name}.dlc"
            if not dlc_file.exists():
                # 兜底：目录下任意 .dlc
                dlcs = list(folder.glob("*.dlc"))
                dlc_file = dlcs[0] if dlcs else None
            if not dlc_file:
                out.append({"id": folder.name, "name": folder.name, "path": f"dlc/{folder.name}"})
                continue
            name = folder.name
            rel_path = f"dlc/{folder.name}"
            try:
                with open(dlc_file, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        m = _NAME_RE.match(line)
                        if m:
                            name = m.group("name")
                        p = _PATH_RE.match(line)
                        if p:
                            rel_path = p.group("path")
                        if name != folder.name and "path" in line:
                            break
            except OSError:
                pass
            out.append({"id": folder.name, "name": name, "path": rel_path})
        return out

    # -- 版本交叉校验 ---------------------------------------------------------
    @staticmethod
    def _normalize_version(v: Optional[str]) -> Optional[tuple[int, ...]]:
        if not v:
            return None
        parts = re.findall(r"\d+", v)
        if not parts:
            return None
        return tuple(int(p) for p in parts[:4])

    def resolve(self, save_game_version: Optional[str]) -> dict:
        dlc = self.list_dlc()
        # 本机 exe PE 版本资源只含启动器壳版本，无法代表真实游戏版本；置 None 不伪造。
        installed = None
        match = None
        if installed is not None and save_game_version is not None:
            match = self._normalize_version(installed) == self._normalize_version(save_game_version)
        return {
            "available": self.is_available(),
            "game_dir": str(self.game_dir) if self.game_dir else None,
            "save_game_version": save_game_version,
            "installed_game_version": installed,
            "version_match": match,
            "dlc_count": len(dlc),
            "dlc": dlc,
        }

    # -- 本地化加载（基础游戏 → 按存档顺序叠加 Mod） --------------------------
    def build_localization(
        self, mod_descriptors: list[str] | None = None, mods_dir: str | Path | None = None
    ) -> LocalizationLoader:
        """加载基础游戏本地化，再按存档记录的 Mod 顺序叠加 Mod 本地化。

        回退链：zh-Hans → english → 原始 key（见 LocalizationLoader）。
        只读扫描 localization 目录，不复制/不修改游戏或 Mod 文件。
        """
        loader = LocalizationLoader()
        if self.is_available():
            loader.load_game(self.game_dir)  # type: ignore[arg-type]
        mod_root = Path(mods_dir) if mods_dir else None
        if mod_root is not None and mod_descriptors:
            for desc in mod_descriptors:
                base = desc.split("/")[-1]
                mod_id = base[:-4] if base.endswith(".mod") else base
                # 优先按 .mod 的 path 定位（通常是 "mod/ugc_xxx"）；否则按 mod_id 目录猜测
                cand = mod_root / mod_id
                if cand.is_dir():
                    loader.load_mod(cand)
        return loader
