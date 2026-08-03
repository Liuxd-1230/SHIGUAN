"""ModResolver —— 把存档里的 Mod 描述符解析为可读信息并产出兼容性报告。

CK3 存档的 mods 容器列出形如 `mod/ugc_3598735569.mod` 的引用（订阅型 Mod）。
真正的 `.mod` 描述符文件位于用户 CK3 数据目录的 `mod/`（Steam 创意工坊订阅或本地 Mod）。

Phase 2A.1 扩展（规范六）：
  - ResolvedMod 必须包含 descriptor_path / content_path / archive_path /
    source_type(workshop|local|archive|missing) / load_order / replace_path /
    dependencies / localization_paths / resolved。
  - 路径规范化并防止 descriptor 路径逃逸到非允许区域（路径穿越防护）。
  - 缺失只产生 warning，不阻断存档人物基础解析。
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
    descriptor_path: str | None = None
    content_path: str | None = None  # 实际 Mod 目录（workshop/local）或压缩包
    archive_path: str | None = None  # 压缩包路径（source_type=archive 时）
    source_type: str = "missing"  # workshop | local | archive | missing
    load_order: int = 0  # 在存档声明中的顺序（决定本地化覆盖顺序）
    replace_path: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    localization_paths: list[str] = field(default_factory=list)
    found_locally: bool = False
    corrupted: bool = False
    # resolved = 找到且未损坏且能定位到真实资源目录/压缩包
    resolved: bool = False


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
                "descriptor_path": m.descriptor_path,
                "content_path": m.content_path,
                "archive_path": m.archive_path,
                "source_type": m.source_type,
                "load_order": m.load_order,
                "replace_path": m.replace_path,
                "dependencies": m.dependencies,
                "localization_paths": m.localization_paths,
                "found_locally": m.found_locally,
                "corrupted": m.corrupted,
                "resolved": m.resolved,
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


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


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
        # 优先 Known Folder API 取 CK3 用户目录下的 mod/。
        try:
            from app.services.known_folder import resolve_ck3_user_dir

            ck3_user, _ = resolve_ck3_user_dir()
        except Exception:
            ck3_user = None
        if ck3_user:
            cand = Path(ck3_user) / "mod"
            if cand.exists():
                return cand
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
        # 真实 .mod 里 remote_file_id 常带引号（remote_file_id="3598735569"），
        # 少数手写描述符不带引号，两种都要认。
        m = re.search(r'remote_file_id\s*=\s*"?(\d+)"?', text)
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

    def _safe_resolve(self, descriptor_file: Path, rel: str | None) -> str | None:
        """把 .mod 中的 path/archive 解析为安全绝对路径。

        CK3 真实语义：descriptor 位于 `<CK3用户目录>/mod/xxx.mod`，其中的
        `path="mod/xxx"` 是相对 **CK3 用户目录**（descriptor 的上一级）而非 mod 目录；
        创意工坊订阅 Mod 则写绝对路径（`.../steamapps/workshop/content/1158310/<id>`）。

        允许根（超出即判定路径穿越，返回 None 不加载）：
          - mods_dir 自身及其子目录；
          - 任意包含 `steamapps/workshop` 的路径（创意工坊内容目录）。
        """
        if not rel:
            return None
        mods_root = (
            Path(self.mods_dir).resolve() if self.mods_dir else descriptor_file.parent.resolve()
        )
        cand = Path(rel)
        candidates: list[Path] = []
        if cand.is_absolute():
            candidates.append(cand.resolve())
        else:
            # 依次尝试：CK3 用户目录（mod 的上一级，CK3 的真实基准）、mods_dir 本身。
            bases = [mods_root.parent, mods_root]
            for b in bases:
                if b is None:
                    continue
                candidates.append((b / rel).resolve())

        allowed: list[Path] = []
        for c in candidates:
            flat = str(c).replace("\\", "/").lower()
            if "steamapps/workshop" in flat or _is_relative_to(c, mods_root):
                allowed.append(c)
        if not allowed:
            # 逃逸出允许区域：拒绝（路径穿越防护）。
            return None
        for c in allowed:
            if c.exists():
                return str(c)
        return str(allowed[0])

    @staticmethod
    def _localization_paths_for(content_path: str, is_archive: bool) -> list[str]:
        if is_archive:
            # 压缩包：由 LocalizationLoader.load_archive 直接读取，返回压缩包路径。
            return [content_path]
        loc_dir = Path(content_path) / "localization"
        if loc_dir.exists():
            return [str(loc_dir)]
        # 某些 Mod 把 yml 放在根（少见），作为回退。
        if (Path(content_path)).is_dir():
            return [content_path]
        return []

    def _resolve_name(self, raw_name: str | None) -> str:
        if not raw_name:
            return ""
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
        for idx, desc in enumerate(descriptors):
            base = desc.split("/")[-1]
            mod_id = base[:-4] if base.endswith(".mod") else base
            rfid = mod_id[4:] if mod_id.startswith("ugc_") and mod_id[4:].isdigit() else None

            descriptor_path: str | None = None
            name = mod_id
            path = archive = supported = None
            replace_path: list[str] = []
            deps: list[str] = []
            found = False
            corrupted = False
            content_path: str | None = None
            archive_path: str | None = None
            source_type = "missing"
            localization_paths: list[str] = []

            if self.mods_dir is not None:
                candidate = Path(self.mods_dir) / base
                if candidate.exists():
                    found = True
                    descriptor_path = str(candidate)
                    try:
                        parsed = self._parse_mod_file(
                            candidate.read_text(encoding="utf-8", errors="replace")
                        )
                        corrupted = bool(parsed.get("corrupted"))
                        name = parsed["name"] or mod_id
                        # descriptor 内显式声明的 remote_file_id 优先于从 mod_id 推断。
                        if parsed.get("remote_file_id"):
                            rfid = parsed["remote_file_id"]
                        path = parsed["path"]
                        archive = parsed["archive"]
                        supported = parsed["supported_version"]
                        replace_path = parsed["replace_path"]
                        deps = parsed["dependencies"]
                    except Exception:  # noqa: BLE001
                        corrupted = True

                    if not corrupted:
                        if archive:
                            ap = self._safe_resolve(candidate, archive)
                            if ap and Path(ap).exists():
                                archive_path = ap
                                content_path = ap
                                source_type = "archive"
                        elif path:
                            cp = self._safe_resolve(candidate, path)
                            if cp and Path(cp).exists():
                                content_path = cp
                                # 判定来源：内容真实落在 steamapps/workshop 下即创意工坊；
                                # 否则若 mod_id 形如 ugc_<id>（订阅但被链接到 mod/ 下）
                                # 也算创意工坊；其余为本地 Mod。
                                flat = cp.replace("\\", "/").lower()
                                if "steamapps/workshop" in flat or mod_id.startswith("ugc_"):
                                    source_type = "workshop"
                                else:
                                    source_type = "local"
                        if content_path is None:
                            # 回退：按 mod_id 目录猜测（如 workshop 链接目录）。
                            fb = Path(self.mods_dir) / mod_id
                            if fb.is_dir():
                                content_path = str(fb)
                                source_type = "local"
                        if content_path:
                            localization_paths = self._localization_paths_for(
                                content_path, source_type == "archive"
                            )

            resolved = ResolvedMod(
                mod_id=mod_id,
                remote_file_id=rfid,
                name=self._resolve_name(name),
                descriptor_path=descriptor_path,
                content_path=content_path,
                archive_path=archive_path,
                source_type=source_type,
                load_order=idx,
                replace_path=replace_path,
                dependencies=deps,
                localization_paths=localization_paths,
                found_locally=found,
                corrupted=corrupted,
                resolved=found and not corrupted and content_path is not None,
            )
            report.required.append(resolved)
            if found and not corrupted:
                report.found.append(resolved)
            if not found:
                report.missing.append(mod_id)
            if corrupted:
                report.corrupted.append(mod_id)
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
