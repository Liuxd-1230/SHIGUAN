"""历史语义事件构建（Phase 3C.3 + 3C.7）。

解决的问题（来自真实存档）：一次征服/继承常常在同一天获得十几个头衔
（952.8.16 一天 13 条、955.1.22 约 30 条），旧逻辑把同日所有 title 变更
合并成一条「获得头衔」刷屏。本模块按**语义类型**拆分：

  - 主权领地 → identity_transition（成为最高统治者）；
  - 领地（王国/公国/伯爵领）→ territorial_gain / territorial_loss；
  - 个人官职 → office_appointment / office_dismissal；
  - 政权机构 → institution_transition（**机构归属/控制关系变化**，不表示个人任职）；
  - 宗教职务 → religious_appointment / religious_dismissal；
  - 荣誉 → honor_granted / honor_revoked；
  - 宣称 → claim_gained / claim_lost；
  - 领地被创建/消灭 → realm_created / realm_destroyed。

3C.7 聚合修复（P0）：同日同类 title 变更**不再**只取组内第一个 title 的 cause。
流程：逐条 title change → TitleHistoryActionNormalizer 逐条解析 raw_type /
规范化动作 / cause → 再按兼容语义分组。分组键含日期、语义类型、方向与
规范化动作（rawTypeGroup）；不同 cause 的 title 绝不合并
（conquest + granted + None 同日 → 三条独立事件）。证据描述逐条绑定自身 raw_type。

`AcquisitionCauseResolver` 是兼容旧 API 的薄封装（委托 TitleHistoryActionNormalizer）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from models import (
    AcquisitionCause,
    AcquisitionTypeSource,
    Confidence,
    EntityRef,
    EvidenceRef,
    EventType,
    HistoricalSemanticEvent,
    HistoricalSemanticEventType,
    TimelineEvent,
    TitleClassification,
    TitleHistoryActionKind,
    TitlePeriod,
    TitleSemanticType,
)

from .title_history_actions import (
    TitleHistoryAction,
    TitleHistoryActionNormalizer,
)
from .title_semantics import _date_key

# (semantic_type, direction) -> (EventType, 事件标题)。
# 政权机构不写「任职」语义（3C.7）：机构归入/脱离统治体系，不代表个人任职。
_EVENT_MAP: Dict[Tuple[HistoricalSemanticEventType, str], Tuple[EventType, str]] = {
    (HistoricalSemanticEventType.IDENTITY_TRANSITION, "gain"): (EventType.TITLE_GAIN, "身份转变"),
    (HistoricalSemanticEventType.TERRITORIAL_GAIN, "gain"): (EventType.TITLE_GAIN, "获得领地"),
    (HistoricalSemanticEventType.TERRITORIAL_LOSS, "loss"): (EventType.TITLE_LOSS, "失去领地"),
    (HistoricalSemanticEventType.OFFICE_APPOINTMENT, "gain"): (EventType.TITLE_GAIN, "就任官职"),
    (HistoricalSemanticEventType.OFFICE_DISMISSAL, "loss"): (EventType.TITLE_LOSS, "卸任官职"),
    (HistoricalSemanticEventType.INSTITUTION_TRANSITION, "gain"): (EventType.TITLE_GAIN, "机构归属变化"),
    (HistoricalSemanticEventType.INSTITUTION_TRANSITION, "loss"): (EventType.TITLE_LOSS, "机构归属变化"),
    (HistoricalSemanticEventType.RELIGIOUS_APPOINTMENT, "gain"): (EventType.TITLE_GAIN, "出任宗教职务"),
    (HistoricalSemanticEventType.RELIGIOUS_DISMISSAL, "loss"): (EventType.TITLE_LOSS, "卸任宗教职务"),
    (HistoricalSemanticEventType.CLAIM_GAINED, "gain"): (EventType.TITLE_GAIN, "获得宣称"),
    (HistoricalSemanticEventType.CLAIM_LOST, "loss"): (EventType.TITLE_LOSS, "失去宣称"),
    (HistoricalSemanticEventType.HONOR_GRANTED, "gain"): (EventType.TITLE_GAIN, "获授荣誉"),
    (HistoricalSemanticEventType.HONOR_REVOKED, "loss"): (EventType.TITLE_LOSS, "荣誉被夺"),
    (HistoricalSemanticEventType.REALM_CREATED, "gain"): (EventType.TITLE_GAIN, "领地被创建"),
    (HistoricalSemanticEventType.REALM_DESTROYED, "loss"): (EventType.TITLE_LOSS, "领地被消灭"),
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

# 3C-Audit：存档显式 type → AcquisitionCause 的确定性映射（仅当该 type 出现在
# 存档 history 条目中才成立；绝不从文件名或对照项目默认值推断）。
# 存档实测（593a2ec6…956.12.28）出现的 type：created / destroyed / granted /
# conquest / conquest_claim / conquest_populist / conquest_holy_war /
# appointment_succession / appointment / migration / revoked / stepped_down /
# abdication / faction_demand / swear_fealty / independency / leased_out / returned。
_RAW_TYPE_TO_CAUSE = {
    "conquest": AcquisitionCause.CONQUEST,
    "conquest_claim": AcquisitionCause.CONQUEST,
    "conquest_populist": AcquisitionCause.CONQUEST,
    "conquest_holy_war": AcquisitionCause.CONQUEST,
    "granted": AcquisitionCause.GRANT,
    "created": AcquisitionCause.CREATION,
    "usurped": AcquisitionCause.USURPATION,
}


@dataclass
class _Change:
    """一条任期起/止 → 语义变化。"""

    period: TitlePeriod
    classification: TitleClassification
    direction: str  # "gain" | "loss"
    semantic_type: HistoricalSemanticEventType
    date: str


class AcquisitionCauseResolver:
    """头衔获得原因解析（兼容旧 API；委托 TitleHistoryActionNormalizer）。

    3C.7 起真实解析逻辑在 TitleHistoryActionNormalizer（按 raw_type + 语义类型 +
    方向逐条判定）；本类保留 5 元组返回签名（cause, confidence, constraints,
    raw_type, type_source）供既有测试/调用方使用，方向按「获得」处理。
    """

    def __init__(self, normalizer: Optional[TitleHistoryActionNormalizer] = None) -> None:
        self.normalizer = normalizer or TitleHistoryActionNormalizer()

    def resolve(
        self, entry: Optional[dict], date: str
    ) -> Tuple[AcquisitionCause, Confidence, List[str], Optional[str], AcquisitionTypeSource]:
        """返回 (cause, confidence, narrative_constraints, raw_type, type_source)。

        entry 为 titles.json 中该头衔的原始条目（含 history）；缺失 → UNKNOWN。
        优先使用 history 条目里的 `raw_type`（3C-Audit 起 reader 原样保留的存档
        显式 type，如 conquest/granted/appointment_succession）；旧缓存无 raw_type
        时回退粗粒度 kind，type_source 标 reader_default。只有 holder 变更
        （无显式 type）→ UNKNOWN，绝不因时间相近推断继承/征服。
        """
        action = self.normalizer.normalize(
            entry=entry,
            date=date,
            direction="gain",
            semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE,
            title_id=str((entry or {}).get("key") or ""),
        )
        return (
            action.acquisitionCause or AcquisitionCause.UNKNOWN,
            action.confidence,
            action.narrativeConstraints,
            action.rawType,
            action.typeSource,
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

    3C.7 聚合规则（P0 修复）：
      逐条 title change → TitleHistoryActionNormalizer 逐条解析 → 按兼容语义分组。
      分组键 = (date, semanticType, direction, normalizedAction/rawTypeGroup)。
      不同 cause 的 title 绝不合并；同日多个 conquest（含 conquest_claim 等）因
      normalizedAction 相同可合并；created 与 granted 绝不合并；无显式 type 的
      unknown 组可合并但逐条保留 EvidenceRef。
    """

    def __init__(
        self,
        character_id: str,
        character_name: str,
        classifications: Dict[str, TitleClassification],
        entries: Optional[Dict[str, dict]] = None,
        cause_resolver: Optional[AcquisitionCauseResolver] = None,
        normalizer: Optional[TitleHistoryActionNormalizer] = None,
    ) -> None:
        self.cid = str(character_id)
        self.name = character_name
        self.classifications = classifications
        self.entries = entries or {}
        self.causes = cause_resolver or AcquisitionCauseResolver()
        self.actions = normalizer or TitleHistoryActionNormalizer()

    def _changes(self, periods: List[TitlePeriod]) -> List[_Change]:
        out: List[_Change] = []
        for p in periods:
            cls = self.classifications.get(p.titleId)
            if cls is None:
                continue
            if p.start:
                st = _semantic_type_for(cls, "gain")
                if st is not None:
                    out.append(_Change(p, cls, "gain", st, str(p.start)))
            if p.end:
                st = _semantic_type_for(cls, "loss")
                if st is not None:
                    out.append(_Change(p, cls, "loss", st, str(p.end)))
        out.sort(key=lambda c: (_date_key(c.date), c.semantic_type.value, c.period.titleId))
        return out

    def build(
        self, periods: List[TitlePeriod]
    ) -> Tuple[List[HistoricalSemanticEvent], List[TimelineEvent]]:
        changes = self._changes(periods)

        # 逐条解析动作（绝不取组内第一个 title 的 cause 覆盖整组）。
        enriched: List[Tuple[_Change, TitleHistoryAction]] = []
        for c in changes:
            entry = self.entries.get(c.period.titleId)
            action = self.actions.normalize(
                entry=entry,
                date=c.date,
                direction=c.direction,
                semantic_type=c.classification.semanticType,
                title_id=c.period.titleId,
            )
            enriched.append((c, action))

        # 按兼容语义分组：日期 + 语义类型 + 方向 + 规范化动作归并键。
        groups: Dict[
            Tuple[str, HistoricalSemanticEventType, str, str],
            List[Tuple[_Change, TitleHistoryAction]],
        ] = {}
        for c, action in enriched:
            key = (c.date, c.semantic_type, c.direction, action.rawTypeGroup)
            groups.setdefault(key, []).append((c, action))

        # 同一 (date, stype, direction) 下出现多个动作组 → 事件 id 追加动作后缀避免冲突。
        multi: Dict[Tuple[str, str, str], int] = {}
        for (date, stype, direction, _rg) in groups:
            multi[(date, stype.value, direction)] = multi.get((date, stype.value, direction), 0) + 1

        semantic_events: List[HistoricalSemanticEvent] = []
        timeline_events: List[TimelineEvent] = []
        for key in sorted(
            groups,
            key=lambda k: (_date_key(k[0]), k[1].value, k[2], k[3]),
        ):
            date, stype, direction, raw_group = key
            group = groups[key]
            title_ids = [c.period.titleId for c, _a in group]
            names = "、".join(c.period.name or c.period.titleId for c, _a in group)
            action0 = group[0][1]
            verb = action0.summaryVerb
            summary = f"{self.name} 于 {date} {verb}：{names}。"

            base_id = f"{self.cid}-{stype.value}-{date}"
            if multi.get((date, stype.value, direction), 1) > 1:
                base_id = f"{base_id}-{action0.rawTypeGroup}"
            title_id = base_id

            # 事件级 cause / raw_type / type_source：组内一致才上浮；混合
            # （如 conquest + conquest_claim 合并）则事件级留 None/保守值，
            # 由逐条 EvidenceRef 保留各自 raw_type（绝不复制第一个 title 的 type）。
            causes = {a.acquisitionCause for _c, a in group if a.acquisitionCause is not None}
            cause: Optional[AcquisitionCause] = next(iter(causes)) if len(causes) == 1 else None
            raw_types = {a.rawType for _c, a in group}
            raw_type: Optional[str] = next(iter(raw_types)) if len(raw_types) == 1 else None
            type_sources = {a.typeSource for _c, a in group}
            type_source = (
                next(iter(type_sources))
                if len(type_sources) == 1
                else AcquisitionTypeSource.SAVE_EXPLICIT
            )
            action_confs = {a.confidence for _c, a in group}
            action_conf = next(iter(action_confs)) if len(action_confs) == 1 else Confidence.CONFIRMED

            # 仅领土获得 / 主权身份转变记录 acquisitionCause：组内原因一致才上浮；
            # 无任何显式原因 → 显式标 UNKNOWN（供 FactChecker「因果推断」规则使用），
            # 绝不取组内第一个 title 的原因覆盖整组。
            if stype in _CAUSE_TYPES and direction == "gain":
                if len(causes) == 1:
                    cause = next(iter(causes))
                else:
                    cause = AcquisitionCause.UNKNOWN
            else:
                cause = None

            constraints = sorted({c for _ch, a in group for c in a.narrativeConstraints})

            # 证据逐条绑定自身 title 的 raw_type（不把第一个 title 的 type 复制给整组）。
            evidence = [
                EvidenceRef(
                    id=f"{self.cid}-{c.period.titleId}-{date}-ev",
                    sourceType="title",
                    sourcePath=f"{c.period.sourcePath}/history/{date}",
                    rawKey=f"history.{date}.holder",
                    description="landed_titles 历史记录中的持有者变更（该日" + (
                        "起持有" if c.direction == "gain" else "止不再持有") + (
                        f"；存档显式记录 type={a.rawType}" if a.rawType else ""),
                    confidence=Confidence.CONFIRMED,
                )
                for c, a in group
            ]

            # 事件置信度：领土获得/主权转变用动作置信度（未知→uncertain/inferred）；
            # 其余事件由 holder 变更本身证实。机构归属无法确认具体控制关系时降级。
            if stype in _CAUSE_TYPES and direction == "gain":
                confidence = action_conf
            else:
                confidence = Confidence.CONFIRMED
                if (
                    stype == HistoricalSemanticEventType.INSTITUTION_TRANSITION
                    and action0.normalizedAction == TitleHistoryActionKind.UNKNOWN
                ):
                    confidence = Confidence.UNCERTAIN

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
                    # 3C-Audit/3C.7：保留存档显式 type 原始字符串与证据来源，绝不丢弃。
                    acquisitionRawType=raw_type,
                    acquisitionTypeSource=type_source,
                    normalizedAction=action0.normalizedAction,
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
                        for c, _a in group
                    ],
                    sourcePath=f"{group[0][0].period.sourcePath}/history/{date}",
                    confidence=confidence,
                    evidence=evidence,
                )
            )

        return semantic_events, timeline_events
