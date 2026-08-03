"""ModResolver —— 把存档里的 Mod 描述符解析为可读信息并产出兼容性报告。

CK3 存档的 mods 容器列出形如 `mod/ugc_3598735569.mod` 的引用（订阅型 Mod）。
真正的 `.mod` 描述符文件位于用户 CK3 数据目录的 `mod/`（Steam 创意工坊订阅或本地 Mod）。

设计（规范七）：
  - 从存档读取有序 Mod descriptor 列表。
  - 在用户 mod/ 目录查找对应 .mod 文件，解析 name/path/archive/supported_version/
    remote_file_id/replace_path/dependencies。
  - 缺失 Mod → MissingModWarning，不阻止人物数据解析。
  - 损坏 descriptor → corrupted 标记，不崩溃。
  - 当前 launcher-v2.sqlite 仅作辅助（当前 Playset 信息），只读，绝不修改。
  - 本地化：若提供 loader，尝试把 mod 名（可能为 loc key）解析为可读名。

所有读取均为只读元数据（.mod 文本、sqlite 只读），不复制/不修改游戏或 Mod 文件。
"""
from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.services.localization import LocalizationLoader


# 哨兵：区分「未传 mods_dir（用默认目录）」与「显式传入 None（无本地目录）」
_UNSET = object()


@dataclass
class ResolvedMod:
    mod_id: str
    remote_file_id: str | None
    name: str
    path: str | None = None
    archive: str | None = None
    supported_version: str | None = None
    replace_path: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    found_locally: bool = False
    corrupted: bool = False


@dataclass
class ModCompatibilityReport:
    required: list[ResolvedMod] = field(default_factory=list)
    found: list[ResolvedMod] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    version_mismatch: list[str] = field(default_factory=list)
    corrupted: list[str] = field(default_factory=list)
    localization_available: bool = False
    playset_diff: Optional[dict] = None  # {"save_mods":[...], "playset":[...], "only_in_save":[...], "only_in_playset":[...]}

    @property
    def required_count(self) -> int:
        return len(self.required)

    @property
    def found_count(self) -> int:
        return len(self.found)

    @property
    def missing_count(self) -> int:
        return len(self.missing)

    @property
    def version_mismatch_count(self) -> int:
        return len(self.version_mismatch)

    @property
    def corrupted_count(self) -> int:
        return len(self.corrupted)

    def to_dict(self) -> dict:
        def _m(m: ResolvedMod) -> dict:
            return {
                "mod_id": m.mod_id,
                "remote_file_id": m.remote_file_id,
                "name": m.name,
                "path": m.path,
                "archive": m.archive,
                "supported_version": m.supported_version,
                "replace_path": m.replace_path,
                "dependencies": m.dependencies,
                "found_locally": m.found_locally,
                "corrupted": m.corrupted,
            }

        return {
            "required_count": len(self.required),
            "found_count": len(self.found),
            "missing_count": len(self.missing),
            "version_mismatch_count": len(self.version_mismatch),
            "corrupted_count": len(self.corrupted),
            "localization_available": self.localization_available,
            "required": [_m(m) for m in self.required],
            "missing": self.missing,
            "version_mismatch": self.version_mismatch,
            "corrupted": self.corrupted,
            "playset_diff": self.playset_diff,
        }


class ModResolver:
    def __init__(
        self,
        mods_dir: str | Path | None = _UNSET,
        loader: LocalizationLoader | None = None,
    ) -> None:
        if mods_dir is _UNSET:
            self.mods_dir = self._default_mods_dir()
        else:
            self.mods_dir = Path(mods_dir) if mods_dir else None
        self.loader = loader

    @staticmethod
    def _default_mods_dir() -> Path | None:
        env = os.environ.get("SHIGUAN_CK3_MODS_DIR")
        if env:
            p = Path(env)
            return p if p.exists() else None
        userprofile = os.environ.get("USERPROFILE") or os.environ.get("HOME")
        if not userprofile:
            return None
        cand = (
            Path(userprofile)
            / "Documents"
            / "Paradox Interactive"
            / "Crusader Kings III"
            / "mod"
        )
        return cand if cand.exists() else None

    @staticmethod
    def _parse_mod_file(text: str) -> dict:
        out: dict = {
            "name": None,
            "path": None,
            "archive": None,
            "supported_version": None,
            "replace_path": [],
            "remote_file_id": None,
            "dependencies": [],
            "corrupted": False,
        }
        # 标量字符串字段：必须用「同号内闭合」的引号。若某 key=" 后到行尾都没有闭合引号，
        # 说明描述符损坏（漏了结尾引号），标记为 corrupted 而非吞掉异常。
        corrupted = False
        for key in ("name", "path", "archive", "supported_version"):
            m = re.search(key + r'\s*=\s*"([^"\n]*)"', text)
            if m:
                out[key] = m.group(1)
            elif re.search(key + r'\s*=\s*"[^"\n]*$', text, re.MULTILINE):
                # 行内有 key=" 开头却没有同号闭合引号 → 损坏
                corrupted = True
        out["corrupted"] = corrupted
        m = re.search(r'remote_file_id\s*=\s*(\d+)', text)
        if m:
            out["remote_file_id"] = m.group(1)
        rm = re.search(r'replace_path\s*=\s*\{([^}]*)\}', text)
        if rm:
            out["replace_path"] = re.findall(r'"([^"]+)"', rm.group(1))
        dm = re.search(r'dependencies\s*=\s*\{([^}]*)\}', text)
        if dm:
            out["dependencies"] = re.findall(r'"([^"]+)"', dm.group(1))
        return out

    @staticmethod
    def _normalize_version(v: str | None) -> Optional[tuple[int, ...]]:
        if not v:
            return None
        parts = re.findall(r"\d+", v)
        return tuple(int(p) for p in parts[:3]) if parts else None

    def _resolve_name(self, raw_name: str | None) -> str:
        if not raw_name:
            return ""
        # 若看起来是本地化键（无空格、含下划线）且 loader 可用，尝试解析
        if self.loader and re.fullmatch(r"[A-Za-z0-9_]+", raw_name or ""):
            loc = self.loader.resolve(raw_name)
            if loc:
                return loc
        return raw_name

    def resolve(
        self,
        descriptors: list[str],
        save_game_version: str | None = None,
        playset_mod_ids: list[str] | None = None,
    ) -> ModCompatibilityReport:
        report = ModCompatibilityReport()
        for desc in descriptors:
            base = desc.split("/")[-1]
            mod_id = base[:-4] if base.endswith(".mod") else base
            rfid = mod_id[4:] if mod_id.startswith("ugc_") and mod_id[4:].isdigit() else None

            found = False
            corrupted = False
            name = mod_id
            path = archive = supported = None
            replace_path: list[str] = []
            deps: list[str] = []

            if self.mods_dir is not None:
                candidate = Path(self.mods_dir) / base
                if candidate.exists():
                    try:
                        parsed = self._parse_mod_file(
                            candidate.read_text(encoding="utf-8", errors="replace")
                        )
                        found = True
                        corrupted = bool(parsed.get("corrupted"))
                        name = parsed["name"] or mod_id
                        path = parsed["path"]
                        archive = parsed["archive"]
                        supported = parsed["supported_version"]
                        replace_path = parsed["replace_path"]
                        deps = parsed["dependencies"]
                    except Exception:  # noqa: BLE001
                        corrupted = True
                        found = True  # 文件存在但损坏

            resolved = ResolvedMod(
                mod_id=mod_id,
                remote_file_id=rfid,
                name=self._resolve_name(name),
                path=path,
                archive=archive,
                supported_version=supported,
                replace_path=replace_path,
                dependencies=deps,
                found_locally=found,
                corrupted=corrupted,
            )
            report.required.append(resolved)
            if found and not corrupted:
                report.found.append(resolved)
            if not found:
                report.missing.append(mod_id)
            if corrupted:
                report.corrupted.append(mod_id)
            # 版本可能不匹配：descriptor 声明 supported_version 且低于存档版本
            sv = self._normalize_version(supported)
            gv = self._normalize_version(save_game_version)
            if sv and gv and sv < gv:
                report.version_mismatch.append(mod_id)

        report.localization_available = self.loader is not None and self.loader.count() > 0

        if playset_mod_ids is not None:
            save_ids = [r.mod_id for r in report.required]
            report.playset_diff = {
                "save_mods": save_ids,
                "playset": playset_mod_ids,
                "only_in_save": [m for m in save_ids if m not in playset_mod_ids],
                "only_in_playset": [m for m in playset_mod_ids if m not in save_ids],
            }
        return report


def read_launcher_playset(db_path: str | Path) -> list[str] | None:
    """只读读取 launcher-v2.sqlite 的当前 Playset Mod 列表（辅助信息）。不修改数据库。"""
    p = Path(db_path)
    if not p.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            cur = con.cursor()
            # 取当前激活 playset
            cur.execute("SELECT playlistid FROM playsets WHERE active=1 LIMIT 1")
            row = cur.fetchone()
            if not row:
                cur.execute("SELECT playlistid FROM playsets LIMIT 1")
                row = cur.fetchone()
            if not row:
                return []
            pid = row[0]
            cur.execute(
                "SELECT modid FROM playlist_mods WHERE playlistid=?", (pid,)
            )
            return [r[0] for r in cur.fetchall()]
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return None
