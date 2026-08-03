"""EntityIndexBuilder + ReferenceResolver（M2.5）。

把 Rust ck3-reader 产出的 entities.json（仅存档内部键，未本地化）与
GameDefLoader（游戏定义键→本地化键）+ LocalizationLoader（本地化键→可读名）合并，
产出带可读名的 EntityIndex，并对人物档案里的裸 id 做引用解析。

诚实性原则（贯穿 M2）：
  - resolved=False 时 name 就是原始 id，绝不为其编造可读名。
  - 既无 key 也无 save_name 的实体 → resolved=False（未命名实体）。
  - def 键若游戏定义缺失 → 标 unresolved，不假装本地化命中。
  - 占位 token 表下 enum 字段为数字 id：loc 通常查不到 → 显示为数字并 resolved=False，
    这**不是** unknown_token_count=0 所能掩盖的"完整性"。
"""
from __future__ import annotations

from typing import Optional

from models import (
    EntityIndex,
    EntityIndexEntry,
    EntityKind,
    EntityKeyKind,
    EntityNameSource,
    EntityRef,
)

from app.services.game_def_loader import GameDefLoader
from app.services.localization import LocalizationLoader


def _resolve_name(
    kind: str,
    eid: str,
    key: Optional[str],
    key_kind: Optional[str],
    save_name: Optional[str],
    game_def: Optional[GameDefLoader],
    loc: Optional[LocalizationLoader],
    literal_keys: bool,
) -> tuple[str, EntityNameSource, bool]:
    """返回 (name, name_source, resolved)。"""
    # 1) 存档成品名（玩家自定义头衔/混合文化/战争名）：已是可读文本，免查 loc。
    if save_name:
        return save_name, EntityNameSource.SAVE, True

    # 2) 有内部键
    if key:
        if key_kind == "def":
            name_loc = game_def.lookup(kind, key) if game_def else None
            if name_loc:
                readable = loc.resolve(name_loc) if loc else None
                if readable:
                    return readable, EntityNameSource.LOC, True
                # 游戏定义给了 loc 键，但本地化未命中 → 退化为 loc 键，仍比 def 键好。
                return name_loc, EntityNameSource.GAME_DEF, True
            # 游戏定义缺失 → 无法命名
            return key, EntityNameSource.UNRESOLVED, False
        # key_kind == "loc" 或缺省：直接查本地化
        readable = loc.resolve(key) if loc else None
        if readable:
            return readable, EntityNameSource.LOC, True
        if literal_keys:
            # 明文存档：字段名本身即可读（无 token 表）。
            return key, EntityNameSource.LITERAL, True
        return key, EntityNameSource.UNRESOLVED, False

    # 3) 既无 key 也无 save_name → 退化为原始 id
    return eid, EntityNameSource.UNRESOLVED, False


class EntityIndexBuilder:
    """合并 entities.json + GameDefLoader + LocalizationLoader → EntityIndex。"""

    def __init__(
        self,
        game_def: Optional[GameDefLoader] = None,
        loc: Optional[LocalizationLoader] = None,
        literal_keys: bool = False,
    ) -> None:
        self.game_def = game_def
        self.loc = loc
        self.literal_keys = literal_keys

    def build(self, raw: dict) -> EntityIndex:
        kinds_out: dict[EntityKind, object] = {}
        for kind_str, kind_raw in (raw.get("kinds") or {}).items():
            try:
                kind = EntityKind(kind_str)
            except ValueError:
                # 未知类别：跳过（向前兼容，不崩）。
                continue
            entries_out: dict[str, EntityIndexEntry] = {}
            unresolved = 0
            for eid, e in (kind_raw.get("entries") or {}).items():
                key = e.get("key")
                key_kind = e.get("key_kind")
                save_name = e.get("save_name")
                name, name_source, resolved = _resolve_name(
                    kind_str, eid, key, key_kind, save_name,
                    self.game_def, self.loc, self.literal_keys,
                )
                if not resolved:
                    unresolved += 1
                entries_out[eid] = EntityIndexEntry(
                    id=eid,
                    key=key,
                    keyKind=EntityKeyKind(key_kind) if key_kind else None,
                    prefix=e.get("prefix"),
                    parent=e.get("parent"),
                    saveName=save_name,
                    startDate=e.get("start_date"),
                    name=name,
                    nameSource=name_source,
                    resolved=resolved,
                )
            kinds_out[kind] = _kind_index(kind, kind_raw, entries_out, unresolved)
        return EntityIndex(
            schemaVersion=int(raw.get("schema_version", 1)),
            readerVersion=raw.get("reader_version", ""),
            scanMs=float(raw.get("scan_ms", 0.0)),
            kinds=kinds_out,  # type: ignore[arg-type]
            warnings=list(raw.get("warnings") or []),
        )


def _kind_index(kind, kind_raw, entries_out, unresolved) -> "object":
    from models import EntityKindIndex

    return EntityKindIndex(
        kind=kind,
        source=kind_raw.get("source", ""),
        containerFound=bool(kind_raw.get("container_found", True)),
        count=int(kind_raw.get("count", 0)),
        unresolvedCount=unresolved,
        entries=entries_out,
    )


class ReferenceResolver:
    """把人物档案里的裸 id 解析为轻量 EntityRef（解析不到名时 name=原 id、resolved=False）。

    绝不使用"未知父亲"之类的占位掩盖未命名引用。
    """

    def __init__(self, index: EntityIndex) -> None:
        # kind -> { id: EntityIndexEntry }
        self._by_kind: dict[str, dict[str, EntityIndexEntry]] = {
            k.value: {iid: e for iid, e in kind_idx.entries.items()}
            for k, kind_idx in index.kinds.items()
        }

    def resolve(self, kind: str, ref_id) -> EntityRef:
        entry = self._by_kind.get(kind, {}).get(str(ref_id))
        if entry is None:
            return EntityRef(id=str(ref_id), name=str(ref_id), type=kind, resolved=False)
        return EntityRef(id=entry.id, name=entry.name, type=kind, resolved=entry.resolved)
