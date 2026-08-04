"""MemoryTimelineIndex —— 从 memories.json 聚合单个角色的记忆与关系（M4）。

Rust ck3-reader 的 prepare 已把 character_memory_manager.database 反解为
memories.json：每条含 id / memory_type / participants（role→人物id）/
creation_date / end_date / battle_location_id。记忆 key 是存档级全局计数器，
**无法从 id 解码归属**；本模块用「主体角色表 + 家族数据交叉核对」把它归属到人物，
并映射为契约的 LifeEvent[] / TimelineEvent[] / friends / rivals / lovers。

归属规则（诚实性优先）：
  - **family_data 交叉核对（owner 在条目外）**：married 记忆只列对方（spouse）；
    用人物索引交叉核对“谁的 spouse 列表含该 participant”，那个人就是 owner。
    实测真实存档 6543 条 married 记忆，6498 条（99.3%）可据此归属；
    child_born / first_born / twins_born 同理（谁的 children 列表含 child）。
  - **主体归属（owner 不可解）**：became_*（new_soulmate / new_relation / rival）
    与 *_died（dead_relation）、battle_*（ruler）、war_*、defensive/offensive_war
    （other_party）的“被点名者”就是主体，直接归属到该 participant。
  - **诚实跳过**：imprisoned / ascended_throne_memory / released_from_prison_memory /
    lost_title_memory 的 owner 不是 participant 且主体语义不明 → 不进时间线、
    不进个人归属，只计入 skipped 统计（不伪造归属）。
  - 时间线事件：仅「有日期 + 可归属 + 映射到契约事件类型」的条目生成，
    全部带 sourceType="memory" 的 EvidenceRef；无日期只进 memories 列表。

关系推导（好友/宿敌/恋人）：
  CK3 的 became_* 记忆按“事件双方各一条、互指对方”成对生成（实测 became_soulmates
  11 个日期中 10 个是成对）。因此同类型 + 同 creation_date + 恰好两条 + 主体互异
  → 推断两条主体互为好友/宿敌/恋人，名字可解析；该推断标 INFERRED 并附告警。
  配对不上的单条记忆只进 memories 列表（对方未指名，不伪造名字）。

名字解析：经会话人物索引（characters.ndjson）取 stub → 本地化名；
查不到 → name=原始 id、resolved=False（绝不编造可读名）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from models import (
    CharacterRef,
    Confidence,
    EntityRef,
    EvidenceRef,
    EvidenceWarning,
    EventType,
    LifeEvent,
    TimelineEvent,
    WarningSeverity,
)

from app.services.localization import LocalizationLoader
from app.services.title_reign_extractor import _date_key
from app.services.character_extractor import resolve_display_name

# 记忆类型 -> 主体角色（条目里“该记忆涉及的对象”的角色）。
# married / child_born 这类“owner 在条目外”：主体角色是对方，owner 需交叉核对。
SUBJECT_ROLES: dict[str, tuple[str, ...]] = {
    "married": ("spouse",),
    "child_born": ("child",),
    "first_born": ("child",),
    "twins_born": ("child", "child_2"),
    "child_premature": ("mother",),
    "child_stillborn": ("mother",),
    "relative_died": ("dead_relation",),
    "spouse_died": ("dead_relation",),
    "friend_died": ("dead_relation",),
    "lover_died": ("dead_relation",),
    "rival_died": ("dead_relation",),
    "soulmate_died": ("dead_relation",),
    "nemesis_died": ("dead_relation",),
    "battle_won_memory": ("ruler",),
    "battle_lost_memory": ("ruler",),
    "war_won": ("winner",),
    "war_lost": ("loser",),
    "defensive_war": ("other_party",),
    "offensive_war": ("other_party",),
    "became_soulmates": ("new_soulmate",),
    "became_lovers": ("new_relation",),
    "became_friends": ("new_relation",),
    "became_rivals": ("rival",),
}

# 时间线事件映射：记忆类型 -> (事件类型, 标题)。仅“事件型”记忆入时间线，
# became_* 关系型记忆只进 memories 列表 + 关系列表。
TIMELINE_MAPPING: dict[str, tuple[EventType, str]] = {
    "married": (EventType.MARRIAGE, "结婚"),
    "child_born": (EventType.CHILD_BIRTH, "孩子出生"),
    "first_born": (EventType.CHILD_BIRTH, "长子女出生"),
    "twins_born": (EventType.CHILD_BIRTH, "双胞胎出生"),
    "child_premature": (EventType.CHILD_BIRTH, "早产"),
    "child_stillborn": (EventType.CHILD_BIRTH, "死产"),
    "relative_died": (EventType.DEATH, "亲人离世"),
    "spouse_died": (EventType.DEATH, "配偶离世"),
    "friend_died": (EventType.DEATH, "友人离世"),
    "lover_died": (EventType.DEATH, "恋人离世"),
    "rival_died": (EventType.DEATH, "宿敌离世"),
    "soulmate_died": (EventType.DEATH, "灵魂伴侣离世"),
    "nemesis_died": (EventType.DEATH, "死敌离世"),
}

# battle / war 前缀映射（含 1000_knight / 3000_side_commander 等变体）。
_BATTLE_WON_PREFIX = "battle_won_memory"
_BATTLE_LOST_PREFIX = "battle_lost_memory"

# 关系型记忆：记忆类型 -> (关系列表键, 主体角色)。配对推导的名字进 friends/rivals/lovers。
RELATIONSHIP_MEMORY_TYPES: dict[str, tuple[str, str]] = {
    "became_soulmates": ("lovers", "new_soulmate"),
    "became_lovers": ("lovers", "new_relation"),
    "became_friends": ("friends", "new_relation"),
    "became_rivals": ("rivals", "rival"),
}

# 诚实跳过：owner 非 participant 且主体语义不明。
SKIPPED_TYPES = frozenset(
    {
        "imprisoned",
        "ascended_throne_memory",
        "released_from_prison_memory",
        "lost_title_memory",
    }
)


@dataclass
class RelationshipBits:
    """某人物由记忆推导的关系列表（名字可解析的部分）。"""

    friends: list[CharacterRef] = field(default_factory=list)
    rivals: list[CharacterRef] = field(default_factory=list)
    lovers: list[CharacterRef] = field(default_factory=list)
    # 配对不上、对方未指名的关系计数（只展示计数，不伪造名字）。
    friend_count: int = 0
    rival_count: int = 0
    lover_count: int = 0


def _participant_map(m: dict) -> dict[str, str]:
    return {
        str(p.get("role")): str(p.get("character_id"))
        for p in m.get("participants") or []
    }


def _battle_event_kind(mt: str) -> Optional[tuple[EventType, str]]:
    if mt == _BATTLE_WON_PREFIX or mt.startswith(_BATTLE_WON_PREFIX):
        return (EventType.WAR, "战役获胜")
    if mt == _BATTLE_LOST_PREFIX or mt.startswith(_BATTLE_LOST_PREFIX):
        return (EventType.WAR, "战役失利")
    if mt == "war_won":
        return (EventType.WAR, "战争获胜")
    if mt == "war_lost":
        return (EventType.WAR, "战争失利")
    if mt == "defensive_war":
        return (EventType.WAR, "卷入防御战争")
    if mt == "offensive_war":
        return (EventType.WAR, "卷入进攻战争")
    return None


class MemoryTimelineIndex:
    """从 memories.json 聚合记忆归属 / 时间线事件 / 关系列表（按需惰性计算）。"""

    def __init__(
        self,
        raw_memories: dict,
        by_id: Optional[dict[str, dict]] = None,
        loc: Optional[LocalizationLoader] = None,
    ) -> None:
        self._memories = list(raw_memories.get("memories") or [])
        self._raw_warnings = list(raw_memories.get("warnings") or [])
        self._by_id = by_id or {}
        self._loc = loc
        # family_data 交叉核对索引：spouse/child -> 谁把他们列为配偶/子女。
        self._spouse_to_chars: dict[str, list[str]] = {}
        self._child_to_chars: dict[str, list[str]] = {}
        self._name_cache: dict[str, str] = {}
        self._resolved_cache: dict[str, bool] = {}
        self._attrib_cache: dict[str, list[LifeEvent]] = {}
        self._timeline_cache: dict[str, list[TimelineEvent]] = {}
        self._rel_cache: dict[str, RelationshipBits] = {}
        self._warn_cache: dict[str, list[EvidenceWarning]] = {}
        # 关系配对：relationship kind -> cid -> 名字可解析的对方 id 集合。
        self._pairs: dict[str, dict[str, set[str]]] = {"friends": {}, "rivals": {}, "lovers": {}}
        # 单条（配对不上）计数：kind -> cid -> n。
        self._unpaired_counts: dict[str, dict[str, int]] = {"friends": {}, "rivals": {}, "lovers": {}}
        self.skipped_type_count: int = 0
        self._build()

    # -- 交叉核对与名字解析 ----------------------------------------------------
    def _build(self) -> None:
        for cid, stub in self._by_id.items():
            cid = str(cid)
            for s in stub.get("spouses") or []:
                self._spouse_to_chars.setdefault(str(s), []).append(cid)
            for ch in stub.get("children") or []:
                self._child_to_chars.setdefault(str(ch), []).append(cid)
        # 关系配对（同类型 + 同日期 + 恰两条 + 主体互异 → 互为关系人）。
        for mt, (kind, role) in RELATIONSHIP_MEMORY_TYPES.items():
            by_date: dict[str, list[str]] = {}
            for m in self._memories:
                if m.get("memory_type") != mt:
                    continue
                pm = _participant_map(m)
                sub = pm.get(role)
                date = m.get("creation_date")
                if sub and date:
                    by_date.setdefault(date, []).append(sub)
            for date, subs in by_date.items():
                if len(subs) == 2 and subs[0] != subs[1]:
                    a, b = subs
                    self._pairs[kind].setdefault(a, set()).add(b)
                    self._pairs[kind].setdefault(b, set()).add(a)
                elif len(subs) == 1:
                    # 单条孤儿记忆：对方（owner）未指名，只计数不伪造名字。
                    sub = subs[0]
                    self._unpaired_counts[kind][sub] = (
                        self._unpaired_counts[kind].get(sub, 0) + 1
                    )
                # 同一日期 >=3 条：存在关系但无法配对，也不作未配对计数（不误导）。
        # skipped 类型统计（不归属任何人物）。
        self.skipped_type_count = sum(
            1 for m in self._memories if m.get("memory_type") in SKIPPED_TYPES
        )

    def _char_name(self, cid) -> str:
        cid = str(cid)
        if cid in self._name_cache:
            return self._name_cache[cid]
        stub = self._by_id.get(cid)
        if not stub:
            self._name_cache[cid] = cid
            self._resolved_cache[cid] = False
            return cid
        nk = stub.get("name") or ""
        if nk:
            # M5：统一名字解析（本地化 → 拼音hex 解码 → 原 key）。
            name = resolve_display_name(nk, self._loc)
            resolved = name != nk
            self._resolved_cache[cid] = resolved
            self._name_cache[cid] = name
            return self._name_cache[cid]
        self._resolved_cache[cid] = False
        self._name_cache[cid] = cid
        return cid

    def _char_ref(self, cid, source_path: Optional[str] = None) -> CharacterRef:
        cid_s = str(cid)
        return CharacterRef(
            id=cid_s,
            name=self._char_name(cid),
            sourcePath=source_path,
            # M5.1：resolved 如实标注（名字被本地化/hex 转换过才算已解析）。
            resolved=self._resolved_cache.get(cid_s, False),
        )

    # -- 归属 ------------------------------------------------------------------
    def _attributions(self, m: dict) -> list[tuple[str, Optional[str]]]:
        """返回该记忆归属到的人物列表 [(cid, related_id), ...]。

        cid = 该人物档案里这条记忆出现的位置（owner 或主体）；
        related_id = 条目里可指名的对方（可能为 None，不伪造）。
        """
        mt = m.get("memory_type") or ""
        pm = _participant_map(m)
        if mt == "married":
            spouse = pm.get("spouse")
            owners = self._spouse_to_chars.get(spouse, [])
            if owners:
                return [(c, spouse) for c in owners]
            return [(spouse, None)] if spouse else []
        if mt in ("child_born", "first_born", "twins_born"):
            child = pm.get("child") or pm.get("child_2")
            owners = set(self._child_to_chars.get(child, []))
            # 补充：子嗣 stub 里存档直述的父/母（比仅靠对方 children 列表更完整）。
            cstub = self._by_id.get(str(child))
            if cstub:
                for key in ("father", "mother"):
                    if cstub.get(key):
                        owners.add(str(cstub[key]))
            if owners:
                return [(c, child) for c in sorted(owners)]
            return [(child, None)] if child else []
        if mt in SUBJECT_ROLES:
            role = SUBJECT_ROLES[mt][0]
            sub = pm.get(role)
            if not sub:
                return []
            # battle / war：对方角色（loser/winner/other_party）可指名。
            related = None
            if mt.startswith(_BATTLE_WON_PREFIX):
                loser = pm.get("loser")
                related = loser if loser and loser != sub else None
            elif mt.startswith(_BATTLE_LOST_PREFIX):
                winner = pm.get("winner")
                related = winner if winner and winner != sub else None
            elif mt == "war_won":
                loser = pm.get("loser")
                related = loser if loser and loser != sub else None
            elif mt == "war_lost":
                winner = pm.get("winner")
                related = winner if winner and winner != sub else None
            return [(sub, related)]
        return []

    # -- 记忆 / 事件 -----------------------------------------------------------
    def _describe(self, mt: str, related: Optional[str]) -> str:
        # 不伪造名字：related 存在时用解析后的名；否则不写“某人”这类占位。
        if mt == "married":
            return (
                f"由存档记忆记录的一次婚姻（对方：{self._char_name(related)}）。"
                if related
                else "由存档记忆记录的一次婚姻（对方未在条目中指名）。"
            )
        if mt in ("child_born", "first_born", "twins_born", "child_premature", "child_stillborn"):
            return (
                f"由存档记忆记录的孩子出生（孩子：{self._char_name(related)}）。"
                if related
                else "由存档记忆记录的一次子嗣出生。"
            )
        if mt in SUBJECT_ROLES and mt.endswith("_died"):
            return f"由存档记忆记录的人物离世（{self._char_name(related)}）。" if related else "由存档记忆记录的人物离世。"
        if mt.startswith(_BATTLE_WON_PREFIX) or mt == "war_won":
            return (
                f"由存档记忆记录的战役/战争胜利（对手：{self._char_name(related)}）。"
                if related
                else "由存档记忆记录的战役/战争胜利。"
            )
        if mt.startswith(_BATTLE_LOST_PREFIX) or mt == "war_lost":
            return (
                f"由存档记忆记录的战役/战争失利（对方：{self._char_name(related)}）。"
                if related
                else "由存档记忆记录的战役/战争失利。"
            )
        # became_* 等关系型记忆：对方未指名时如实说明。
        rel_key = {
            "became_soulmates": "结为灵魂伴侣",
            "became_lovers": "成为恋人",
            "became_friends": "结为好友",
            "became_rivals": "成为宿敌",
        }.get(mt)
        if rel_key:
            return f"由存档记忆记录的「{rel_key}」事件（对方未在条目中指名）。"
        return f"由存档记忆记录的事件（类型：{mt}）。"

    def _event_type_of(self, mt: str) -> EventType:
        hit = TIMELINE_MAPPING.get(mt)
        if hit:
            return hit[0]
        if _battle_event_kind(mt):
            return EventType.WAR
        if mt in RELATIONSHIP_MEMORY_TYPES:
            return EventType.OTHER
        return EventType.OTHER

    def _memory_evidence(self, m: dict) -> EvidenceRef:
        return EvidenceRef(
            id=f"memory-{m.get('id')}-ev",
            sourceType="memory",
            sourcePath=f"character_memory_manager/database/{m.get('id')}",
            rawKey=m.get("memory_type"),
            description="存档 character_memory_manager.database 中的记忆条目",
            confidence=Confidence.CONFIRMED,
        )

    def _build_character(self, cid: str) -> None:
        """惰性计算某人物：memories / timeline / relationships / warnings。"""
        cid = str(cid)
        if cid in self._attrib_cache:
            return
        life: list[LifeEvent] = []
        timeline: list[TimelineEvent] = []
        warnings: list[EvidenceWarning] = []
        name = self._char_name(cid)
        for m in self._memories:
            mt = m.get("memory_type") or ""
            attribs = self._attributions(m)
            for sub, related in attribs:
                if sub != cid:
                    continue
                date = m.get("creation_date")
                related_refs = (
                    [self._char_ref(related, f"character/{cid}/memory/{m.get('id')}")]
                    if related
                    else []
                )
                location = None
                if mt.startswith(_BATTLE_WON_PREFIX) or mt.startswith(_BATTLE_LOST_PREFIX):
                    loc_id = m.get("battle_location_id")
                    if loc_id:
                        location = EntityRef(
                            id=loc_id, name=loc_id, type="province", resolved=False
                        )
                life.append(
                    LifeEvent(
                        id=f"memory-{m.get('id')}",
                        type=self._event_type_of(mt),
                        date=date,
                        description=self._describe(mt, related),
                        relatedCharacters=related_refs,
                        location=location,
                        confidence=Confidence.CONFIRMED,
                        sourcePath=f"character_memory_manager/database/{m.get('id')}",
                    )
                )
                # 时间线事件：仅「有日期 + 事件型」条目。
                tl = TIMELINE_MAPPING.get(mt) or _battle_event_kind(mt)
                if tl and date:
                    event_type, title = tl
                    timeline.append(
                        TimelineEvent(
                            id=f"{cid}-memory-{m.get('id')}",
                            date=date,
                            endDate=m.get("end_date"),
                            type=event_type,
                            title=title,
                            description=self._describe(mt, related),
                            location=location,
                            relatedCharacters=related_refs,
                            sourcePath=f"character_memory_manager/database/{m.get('id')}",
                            confidence=Confidence.CONFIRMED,
                            evidence=[self._memory_evidence(m)],
                        )
                    )
                # married/child_born owner 交叉核对失败 → 提示归属受限。
                if mt in ("married", "child_born", "first_born", "twins_born") and not related:
                    warnings.append(
                        EvidenceWarning(
                            code="memory_owner_unresolved",
                            message=(
                                f"记忆 {m.get('id')}（{mt}）只列出了对方人物，"
                                "且人物索引中找不到对应的家庭关系，无法确定归属人；"
                                "已按条目中指名的人物记录（不伪造归属）。"
                            ),
                            severity=WarningSeverity.INFO,
                            sourcePath=f"character_memory_manager/database/{m.get('id')}",
                        )
                    )
        # 关系列表 + 配对推断告警。
        bits = RelationshipBits()
        for kind, pairs in self._pairs.items():
            mates = pairs.get(cid, set())
            if mates:
                refs = [
                    self._char_ref(x, f"character/{cid}/memory/{kind}")
                    for x in sorted(mates, key=int if all(str(x).isdigit() for x in mates) else str)
                ]
                setattr(bits, kind, refs)
                warnings.append(
                    EvidenceWarning(
                        code="relationship_inferred_from_memory",
                        message=(
                            f"{kind} 关系由同日期成对出现的 became_* 记忆推断"
                            f"（同类型同日期恰好两条、主体互异）；推断而非存档直述。"
                        ),
                        severity=WarningSeverity.INFO,
                        sourcePath=f"character/{cid}/memory/{kind}",
                    )
                )
        for kind, count_field in (("friends", "friend_count"), ("rivals", "rival_count"), ("lovers", "lover_count")):
            n = self._unpaired_counts[kind].get(cid, 0)
            if n:
                setattr(bits, count_field, n)
        timeline.sort(key=lambda e: (_date_key(e.date), e.type.value))
        life.sort(key=lambda e: (_date_key(e.date or ""), e.id))
        self._attrib_cache[cid] = life
        self._timeline_cache[cid] = timeline
        self._rel_cache[cid] = bits
        self._warn_cache[cid] = warnings

    # -- 对外 API ---------------------------------------------------------------
    def memories(self, character_id: str) -> list[LifeEvent]:
        self._build_character(character_id)
        return list(self._attrib_cache[character_id])

    def timeline_events(self, character_id: str) -> list[TimelineEvent]:
        self._build_character(character_id)
        return list(self._timeline_cache[character_id])

    def relationships(self, character_id: str) -> RelationshipBits:
        self._build_character(character_id)
        return self._rel_cache[character_id]

    def warnings(self, character_id: str) -> list[EvidenceWarning]:
        self._build_character(character_id)
        return list(self._warn_cache[character_id])

    def scanner_warnings(self) -> list[str]:
        return list(self._raw_warnings)

    def memory_total(self) -> int:
        return len(self._memories)
