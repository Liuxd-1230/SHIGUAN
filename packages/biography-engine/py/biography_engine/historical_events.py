"""历史语义事件构建（Phase 3C.3）。

解决的问题（来自真实存档）：一次征服/继承常常在同一天获得十几个头衔
（952.8.16 一天 13 条、955.1.22 约 30 条），旧逻辑把同日所有 title 变更
合并成一条「获得头衔」刷屏。本模块按**语义类型**拆分：

  - 主权领地 → identity_transition（成为最高统治者）；
  - 领地（王国/公国/伯爵领）→ territorial_gain / territorial_loss；
  - 个人官职 → office_appointment / office_dismissal；
  - 政权机构 → institution_transition；
  - 宗教职务 → religious_appointment / religious_dismissal；
  - 荣誉 → honor_granted / honor_revoked；
  - 宣称 → claim_gained / claim_lost；
  - 领地被创建/消灭 → realm_created / realm_destroyed。

`AcquisitionCauseResolver` 的诚实性原则：
  - titles.json 只记录 holder 变更（kind=created/destroyed/holder/other），
    **没有**战争→头衔、继承→头衔的关联字段；
  - 只有 kind=created 可直接证实「创建」，其余一律 AcquisitionCause.UNKNOWN，
    并输出 narrativeConstraint「不得推断因果」—— 时间相近绝不推断因果。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from models import (
    AcquisitionCause,
    Confidence,
    EntityRef,
    EvidenceRef,
    EventType,
    HistoricalSemanticEvent,
    HistoricalSemanticEventType,
    TimelineEvent,
    TitleClassification,
    TitlePeriod,
    TitleSemanticType,
)

from .title_semantics import _date_key

# (semantic_type, direction) -> (EventType, 事件标题)。
_EVENT_MAP: Dict[Tuple[HistoricalSemanticEventType, str], Tuple[EventType, str]] = {
    (HistoricalSemanticEventType.IDENTITY_TRANSITION, "gain"): (EventType.TITLE_GAIN, "身份转变"),
    (HistoricalSemanticEventType.TERRITORIAL_GAIN, "gain"): (EventType.TITLE_GAIN, "获得领地"),
    (HistoricalSemanticEventType.TERRITORIAL_LOSS, "loss"): (EventType.TITLE_LOSS, "失去领地"),
    (HistoricalSemanticEventType.OFFICE_APPOINTMENT, "gain"): (EventType.TITLE_GAIN, "就任官职"),
    (HistoricalSemanticEventType.OFFICE_DISMISSAL, "loss"): (EventType.TITLE_LOSS, "卸任官职"),
    (HistoricalSemanticEventType.INSTITUTION_TRANSITION, "gain"): (EventType.TITLE_GAIN, "机构任职"),
    (HistoricalSemanticEventType.INSTITUTION_TRANSITION, "loss"): (EventType.TITLE_LOSS, "离开机构"),
    (HistoricalSemanticEventType.RELIGIOUS_APPOINTMENT, "gain"): (EventType.TITLE_GAIN, "出任宗教职务"),
    (HistoricalSemanticEventType.RELIGIOUS_DISMISSAL, "loss"): (EventType.TITLE_LOSS, "卸任宗教职务"),
    (HistoricalSemanticEventType.CLAIM_GAINED, "gain"): (EventType.TITLE_GAIN, "获得宣称"),
    (HistoricalSemanticEventType.CLAIM_LOST, "loss"): (EventType.TITLE_LOSS, "失去宣称"),
    (HistoricalSemanticEventType.HONOR_GRANTED, "gain"): (EventType.TITLE_GAIN, "获授荣誉"),
    (HistoricalSemanticEventType.HONOR_REVOKED, "loss"): (EventType.TITLE_LOSS, "荣誉被夺"),
    (HistoricalSemanticEventType.REALM_CREATED, "gain"): (EventType.TITLE_GAIN, "领地被创建"),
    (HistoricalSemanticEventType.REALM_DESTROYED, "loss"): (EventType.TITLE_LOSS, "领地被消灭"),
}

# (semantic_type, direction) -> 摘要动词（名词连接用）。
_VERBS: Dict[Tuple[HistoricalSemanticEventType, str], str] = {
    (HistoricalSemanticEventType.IDENTITY_TRANSITION, "gain"): "成为以下主权领地的最高统治者",
    (HistoricalSemanticEventType.IDENTITY_TRANSITION, "loss"): "失去以下主权领地",
    (HistoricalSemanticEventType.TERRITORIAL_GAIN, "gain"): "获得以下领地",
    (HistoricalSemanticEventType.TERRITORIAL_LOSS, "loss"): "失去以下领地",
    (HistoricalSemanticEventType.OFFICE_APPOINTMENT, "gain"): "就任以下官职",
    (HistoricalSemanticEventType.OFFICE_DISMISSAL, "loss"): "卸任以下官职",
    (HistoricalSemanticEventType.INSTITUTION_TRANSITION, "gain"): "进入以下机构任职",
    (HistoricalSemanticEventType.INSTITUTION_TRANSITION, "loss"): "离开以下机构",
    (HistoricalSemanticEventType.RELIGIOUS_APPOINTMENT, "gain"): "出任以下宗教职务",
    (HistoricalSemanticEventType.RELIGIOUS_DISMISSAL, "loss"): "卸任以下宗教职务",
    (HistoricalSemanticEventType.CLAIM_GAINED, "gain"): "获得以下宣称",
    (HistoricalSemanticEventType.CLAIM_LOST, "loss"): "失去以下宣称",
    (HistoricalSemanticEventType.HONOR_GRANTED, "gain"): "获授以下荣誉",
    (HistoricalSemanticEventType.HONOR_REVOKED, "loss"): "以下荣誉被剥夺",
    (HistoricalSemanticEventType.REALM_CREATED, "gain"): "以下领地被创建",
    (HistoricalSemanticEventType.REALM_DESTROYED, "loss"): "以下领地被消灭",
}

# 需要因果解析的语义类型（领地获得 / 主权身份转变）。
_CAUSE_TYPES = {
    HistoricalSemanticEventType.TERRITORIAL_GAIN,
    HistoricalSemanticEventType.IDENTITY_TRANSITION,
    HistoricalSemanticEventType.REALM_CREATED,
}

# 不进入历史语义事件的类型（临时头衔/未知/Mod 类 —— 避免噪音，但仍出现在 titles 列表）。
_SKIP_TYPES = {
    TitleSemanticType.TEMPORARY_TITLE,
    TitleSemanticType.SPECIAL_MOD_TITLE,
    TitleSemanticType.UNKNOWN,
}

_CONSTRAINT_UNKNOWN_CAUSE = (
    "存档未记录该头衔获得的途径，不得推断为继承、征服、册封等具体原因。"
)


@dataclass
class _Change:
    """一条任期起/止 → 语义变化。"""

    period: TitlePeriod
    classification: TitleClassification
    direction: str  # "gain" | "loss"
    semantic_type: HistoricalSemanticEventType
    date: str


class AcquisitionCauseResolver:
    """头衔获得原因解析（诚实性：除 created 直接证实外一律 unknown）。"""

    def resolve(
        self, entry: Optional[dict], date: str
    ) -> Tuple[AcquisitionCause, Confidence, List[str]]:
        """返回 (cause, confidence, narrative_constraints)。

        entry 为 titles.json 中该头衔的原始条目（含 history）；缺失 → UNKNOWN。
        kind=created 的 history 记录可证实「创建」；其余一律 UNKNOWN。
        """
        if entry is None:
            return (
                AcquisitionCause.UNKNOWN,
                Confidence.UNCERTAIN,
                [_CONSTRAINT_UNKNOWN_CAUSE],
            )
        for h in entry.get("history") or []:
            if str(h.get("date")) != str(date):
                continue
            kind = h.get("kind")
            if kind == "created":
                return AcquisitionCause.CREATION, Confidence.CONFIRMED, []
            if kind == "destroyed":
                # 该日条目是销毁记录，不能作为“获得原因”。
                return (
                    AcquisitionCause.UNKNOWN,
                    Confidence.UNCERTAIN,
                    [_CONSTRAINT_UNKNOWN_CAUSE],
                )
        return (
            AcquisitionCause.UNKNOWN,
            Confidence.INFERRED,
            [_CONSTRAINT_UNKNOWN_CAUSE],
        )


def _semantic_type_for(
    cls: TitleClassification, direction: str
) -> Optional[HistoricalSemanticEventType]:
    """由头衔语义分类推导历史语义事件类型（direction: gain/loss）。"""
    st = cls.semanticType
    if st in _SKIP_TYPES:
        return None
    gain = direction == "gain"
    mapping = {
        TitleSemanticType.SOVEREIGN_REALM_TITLE: (
            HistoricalSemanticEventType.IDENTITY_TRANSITION,
            HistoricalSemanticEventType.TERRITORIAL_LOSS,
        ),
        TitleSemanticType.TERRITORIAL_REALM_TITLE: (
            HistoricalSemanticEventType.TERRITORIAL_GAIN,
            HistoricalSemanticEventType.TERRITORIAL_LOSS,
        ),
        TitleSemanticType.SUBORDINATE_TERRITORY: (
            HistoricalSemanticEventType.TERRITORIAL_GAIN,
            HistoricalSemanticEventType.TERRITORIAL_LOSS,
        ),
        TitleSemanticType.PERSONAL_OFFICE: (
            HistoricalSemanticEventType.OFFICE_APPOINTMENT,
            HistoricalSemanticEventType.OFFICE_DISMISSAL,
        ),
        TitleSemanticType.REALM_INSTITUTION: (
            HistoricalSemanticEventType.INSTITUTION_TRANSITION,
            HistoricalSemanticEventType.INSTITUTION_TRANSITION,
        ),
        TitleSemanticType.RELIGIOUS_OFFICE: (
            HistoricalSemanticEventType.RELIGIOUS_APPOINTMENT,
            HistoricalSemanticEventType.RELIGIOUS_DISMISSAL,
        ),
        TitleSemanticType.CLAIM_ONLY: (
            HistoricalSemanticEventType.CLAIM_GAINED,
            HistoricalSemanticEventType.CLAIM_LOST,
        ),
        TitleSemanticType.HONORARY_TITLE: (
            HistoricalSemanticEventType.HONOR_GRANTED,
            HistoricalSemanticEventType.HONOR_REVOKED,
        ),
        TitleSemanticType.DYNASTY_IDENTITY: (
            HistoricalSemanticEventType.REALM_CREATED,
            HistoricalSemanticEventType.REALM_DESTROYED,
        ),
    }
    pair = mapping.get(st)
    if pair is None:
        return None
    return pair[0] if gain else pair[1]


class HistoricalEventSemanticBuilder:
    """把任期聚合为「按语义类型拆分」的历史语义事件 + 时间线事件。

    build() 产出两样东西（同一批变更，两种视图）：
      - HistoricalSemanticEvent[]：结构化语义事件（供档案/前端分区展示）；
      - TimelineEvent[]：时间线事件（同日同类合并，标题按语义类型区分），
        取代旧版「同日全部头衔合并成一条 title_gain」的粗粒度聚合。
    """

    def __init__(
        self,
        character_id: str,
        character_name: str,
        classifications: Dict[str, TitleClassification],
        entries: Optional[Dict[str, dict]] = None,
        cause_resolver: Optional[AcquisitionCauseResolver] = None,
    ) -> None:
        self.cid = str(character_id)
        self.name = character_name
        self.classifications = classifications
        self.entries = entries or {}
        self.causes = cause_resolver or AcquisitionCauseResolver()

    def _changes(self, periods: List[TitlePeriod]) -> List[_Change]:
        out: List[_Change] = []
        for p in periods:
            cls = self.classifications.get(p.titleId)
            if cls is None:
                continue
            if p.start:
                st = _semantic_type_for(cls, "gain")
                if st is not None:
                    out.append(
                        _Change(p, cls, "gain", st, str(p.start))
                    )
            if p.end:
                st = _semantic_type_for(cls, "loss")
                if st is not None:
                    out.append(
                        _Change(p, cls, "loss", st, str(p.end))
                    )
        out.sort(key=lambda c: (_date_key(c.date), c.semantic_type.value, c.period.titleId))
        return out

    def build(
        self, periods: List[TitlePeriod]
    ) -> Tuple[List[HistoricalSemanticEvent], List[TimelineEvent]]:
        changes = self._changes(periods)
        groups: Dict[Tuple[str, HistoricalSemanticEventType, str], List[_Change]] = {}
        for c in changes:
            groups.setdefault((c.date, c.semantic_type, c.direction), []).append(c)

        semantic_events: List[HistoricalSemanticEvent] = []
        timeline_events: List[TimelineEvent] = []
        for key in sorted(
            groups,
            key=lambda k: (_date_key(k[0]), k[1].value, k[2]),
        ):
            date, stype, direction = key
            group = groups[key]
            title_ids = [c.period.titleId for c in group]
            names = "、".join(c.period.name or c.period.titleId for c in group)
            verb = _VERBS.get((stype, direction)) or ("获得" if direction == "gain" else "失去")
            summary = f"{self.name} 于 {date} {verb}：{names}。"
            title_id = f"{self.cid}-{stype.value}-{date}"

            # 因果解析（仅领地获得 / 主权身份转变）。
            cause: Optional[AcquisitionCause] = None
            constraints: List[str] = []
            cause_conf = Confidence.CONFIRMED
            if stype in _CAUSE_TYPES and direction == "gain":
                entry = self.entries.get(title_ids[0])
                cause, cause_conf, constraints = self.causes.resolve(entry, date)

            evidence = [
                EvidenceRef(
                    id=f"{self.cid}-{c.period.titleId}-{date}-ev",
                    sourceType="title",
                    sourcePath=f"{c.period.sourcePath}/history/{date}",
                    rawKey=f"history.{date}.holder",
                    description="landed_titles 历史记录中的持有者变更（该日" + (
                        "起持有" if c.direction == "gain" else "止不再持有") + "）",
                    confidence=Confidence.CONFIRMED,
                )
                for c in group
            ]
            confidence = cause_conf if cause is not None else Confidence.CONFIRMED

            semantic_events.append(
                HistoricalSemanticEvent(
                    eventId=title_id,
                    semanticType=stype,
                    date=date,
                    summary=summary,
                    relatedTitleIds=title_ids,
                    relatedEntityIds=title_ids,
                    confidence=confidence,
                    evidence=evidence,
                    sourceEventIds=[title_id],
                    narrativeConstraints=constraints,
                    acquisitionCause=cause,
                )
            )

            etype, label = _EVENT_MAP.get((stype, direction), (EventType.TITLE_GAIN, "头衔变更"))
            desc = summary
            if cause is not None and cause == AcquisitionCause.CREATION:
                desc += "（存档记载该领地为该日创建。）"
            timeline_events.append(
                TimelineEvent(
                    id=title_id,
                    type=etype,
                    date=date,
                    title=label,
                    description=desc,
                    relatedTitles=[
                        EntityRef(
                            id=c.period.titleId,
                            name=c.period.name,
                            type="title",
                            resolved=c.period.name != c.period.titleId,
                            sourcePath=c.period.sourcePath,
                        )
                        for c in group
                    ],
                    sourcePath=f"{group[0].period.sourcePath}/history/{date}",
                    confidence=confidence,
                    evidence=evidence,
                )
            )

        return semantic_events, timeline_events
