"""CK3 title history 动作语义化（Phase 3C.7 TitleHistoryActionNormalizer）。

背景（3C-Audit 已确认）：CK3 存档的 landed_titles.history 保存大量**显式** `type`
（created / destroyed / granted / conquest / conquest_claim / conquest_populist /
conquest_holy_war / appointment / appointment_succession / migration / revoked /
stepped_down / abdication / faction_demand / swear_fealty / independency /
leased_out / returned）。自 CACHE_SCHEMA_VERSION=3 起 reader 把这些 type 以
`raw_type` 原样保留进 titles.json。

本模块把 raw_type 规范化为统一动作语义（`TitleHistoryActionKind`），供三处消费：
  1. HistoricalEventSemanticBuilder 的**同日聚合分组**（不同 cause 绝不合并）；
  2. 叙事摘要 / 时间线事件的确定性动词（summaryVerb）；
  3. FactChecker 的语义误写拦截（appointment_succession 不得写成世袭继承等）。

诚实性原则（逐字遵循交接文档）：
  - `rawType` 必须**原样保留**，规范化动作只是统一语义，不替代原始证据；
  - 同一 raw type 在不同 semantic type 下文案必须不同（appointment+官职 vs
    appointment+领地 vs appointment+机构）；
  - appointment_succession ≠ 世袭继承；realm_institution 不表示个人任职；
  - 未知 type → normalizedAction=unknown，保留 raw type，加 warning，不猜测。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from models import (
    AcquisitionCause,
    AcquisitionTypeSource,
    Confidence,
    TitleHistoryActionKind,
    TitleSemanticType,
)

# 存档显式 type → 规范化动作（18 类全部有明确处理策略）。
# 注意：conquest* 四种子类统一为 conquered（subtype 保留各自差异），
# 其余逐一映射；不存在的 type（如 usurped 未出现在本存档）不在此表也无妨。
_RAW_TYPE_TO_ACTION: Dict[str, TitleHistoryActionKind] = {
    "created": TitleHistoryActionKind.CREATED,
    "destroyed": TitleHistoryActionKind.DESTROYED,
    "granted": TitleHistoryActionKind.GRANTED,
    "conquest": TitleHistoryActionKind.CONQUERED,
    "conquest_claim": TitleHistoryActionKind.CONQUERED,
    "conquest_populist": TitleHistoryActionKind.CONQUERED,
    "conquest_holy_war": TitleHistoryActionKind.CONQUERED,
    "appointment": TitleHistoryActionKind.APPOINTED,
    "appointment_succession": TitleHistoryActionKind.ADMINISTRATIVE_SUCCESSION,
    "migration": TitleHistoryActionKind.MIGRATED,
    "revoked": TitleHistoryActionKind.REVOKED,
    "stepped_down": TitleHistoryActionKind.STEPPED_DOWN,
    "abdication": TitleHistoryActionKind.ABDICATED,
    "faction_demand": TitleHistoryActionKind.FACTION_INSTALLED,
    "swear_fealty": TitleHistoryActionKind.SWORE_FEALTY,
    "independency": TitleHistoryActionKind.BECAME_INDEPENDENT,
    "leased_out": TitleHistoryActionKind.LEASED_OUT,
    "returned": TitleHistoryActionKind.RETURNED,
    "usurped": TitleHistoryActionKind.USURPATION,
}

# conquest 子类（raw type 明确时才允许写「通过战争取得」，仍不得写具体战争名/对手）。
_CONQUEST_SUBTYPES = {
    "conquest_claim": "claim",
    "conquest_populist": "populist",
    "conquest_holy_war": "holy_war",
    "conquest": "generic",
}

# 规范化动作 → 领地/统治权获得原因（仅对领土类获得有意义；官职/机构/归还等留 None）。
_ACTION_CAUSES: Dict[TitleHistoryActionKind, AcquisitionCause] = {
    TitleHistoryActionKind.CREATED: AcquisitionCause.CREATION,
    TitleHistoryActionKind.GRANTED: AcquisitionCause.GRANT,
    TitleHistoryActionKind.CONQUERED: AcquisitionCause.CONQUEST,
    TitleHistoryActionKind.FACTION_INSTALLED: AcquisitionCause.FACTION,
    TitleHistoryActionKind.ADMINISTRATIVE_SUCCESSION: AcquisitionCause.ADMINISTRATIVE_TRANSFER,
    TitleHistoryActionKind.APPOINTED: AcquisitionCause.APPOINTMENT,
    TitleHistoryActionKind.USURPATION: AcquisitionCause.USURPATION,
}

# 领土家族（appointment 在此语境表示「经任命获得统治权」，cause 为任命）。
_REALM_SEMANTIC_TYPES = {
    TitleSemanticType.SOVEREIGN_REALM_TITLE,
    TitleSemanticType.TERRITORIAL_REALM_TITLE,
    TitleSemanticType.SUBORDINATE_TERRITORY,
}

_CONSTRAINT_UNKNOWN_CAUSE = (
    "存档未记录该头衔获得的途径，不得推断为继承、征服、册封等具体原因。"
)
# 显式 type 存在但无法解释时的约束（保留原始字符串，不猜测语义）。
_CONSTRAINT_UNMAPPED_RAW = (
    "存档显式记录 type={raw}，但该语义暂未确认，不得推断为继承、征服、册封等具体原因。"
)
# realm_institution 固定叙事约束（机构归统治体系所有，不代表个人任职）。
_CONSTRAINT_INSTITUTION_OWNERSHIP = (
    "该记录表示政权机构的归属或控制关系，不代表人物本人在该机构任职。"
)


def _unknown_constraints(semantic_type: TitleSemanticType) -> List[str]:
    """未知原因事件的叙事约束；机构事件恒附加机构所有权约束。"""
    constraints = [_CONSTRAINT_UNKNOWN_CAUSE]
    if semantic_type == TitleSemanticType.REALM_INSTITUTION:
        constraints.append(_CONSTRAINT_INSTITUTION_OWNERSHIP)
    return constraints


@dataclass(frozen=True)
class TitleHistoryAction:
    """单条 title change 的规范化动作（TitleHistoryActionNormalizer 输出）。

    字段语义（供 HistoricalEventSemanticBuilder 分组/文案/事件回填）：
      - rawType：存档显式 type 原始字符串（None=未记录）；
      - normalizedAction：统一动作语义（TitleHistoryActionKind）；
      - acquisitionCause：仅领土获得类有意义；其余 None；
      - confidence：事件置信度（显式 type=confirmed；migration=inferred；无 type=uncertain）；
      - typeSource：证据来源（save_explicit / reader_default / unknown）；
      - summaryVerb：「：names」前的确定性动词短语（按 action + semantic type + direction）；
      - narrativeConstraints：叙事约束（未知 cause / 机构所有权等）；
      - subtype：conquest 子类（claim/populist/holy_war/generic）；
      - rawTypeGroup：同日聚合的**归并键**（已知动作=动作；未映射显式=原始串；无= none）。
    """

    rawType: Optional[str]
    normalizedAction: TitleHistoryActionKind
    acquisitionCause: Optional[AcquisitionCause]
    confidence: Confidence
    typeSource: AcquisitionTypeSource
    summaryVerb: str
    narrativeConstraints: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    subtype: Optional[str] = None
    rawTypeGroup: str = "none"


# ---------------------------------------------------------------------------
# 动词表（按 TitleSemanticType × direction × action 确定性产出）
# ---------------------------------------------------------------------------

def _gain_verb(st: TitleSemanticType, kind: TitleHistoryActionKind) -> str:
    """获得方向：同一 action 在不同语义类型下文案必须不同。"""
    if st == TitleSemanticType.SOVEREIGN_REALM_TITLE:
        base = "成为以下主权领地的最高统治者"
        if kind == TitleHistoryActionKind.CONQUERED:
            return "通过征服成为以下主权领地的最高统治者"
        if kind == TitleHistoryActionKind.GRANTED:
            return "经授予成为以下主权领地的最高统治者"
        if kind == TitleHistoryActionKind.APPOINTED:
            return "经任命成为以下主权领地的最高统治者"
        if kind == TitleHistoryActionKind.ADMINISTRATIVE_SUCCESSION:
            return "经任命继任，成为以下主权领地的最高统治者"
        if kind == TitleHistoryActionKind.MIGRATED:
            return "因迁徙机制成为以下主权领地的最高统治者"
        if kind == TitleHistoryActionKind.FACTION_INSTALLED:
            return "因派系要求成为以下主权领地的最高统治者"
        if kind == TitleHistoryActionKind.RETURNED:
            return "因归还重新成为以下主权领地的最高统治者"
        if kind == TitleHistoryActionKind.BECAME_INDEPENDENT:
            return "取得独立地位，成为以下主权领地的最高统治者"
        if kind == TitleHistoryActionKind.USURPATION:
            return "经篡位成为以下主权领地的最高统治者"
        if kind == TitleHistoryActionKind.CREATED:
            return base  # 描述后缀补「存档记载该领地为该日创建」
        if kind == TitleHistoryActionKind.UNKNOWN:
            return base
        return base
    if st in (
        TitleSemanticType.TERRITORIAL_REALM_TITLE,
        TitleSemanticType.SUBORDINATE_TERRITORY,
    ):
        if kind == TitleHistoryActionKind.CONQUERED:
            return "通过征服获得"
        if kind == TitleHistoryActionKind.GRANTED:
            return "经授予获得"
        if kind == TitleHistoryActionKind.APPOINTED:
            return "经任命获得"
        if kind == TitleHistoryActionKind.ADMINISTRATIVE_SUCCESSION:
            return "经任命继任"
        if kind == TitleHistoryActionKind.MIGRATED:
            return "因迁徙机制获得"
        if kind == TitleHistoryActionKind.FACTION_INSTALLED:
            return "因派系要求获得"
        if kind == TitleHistoryActionKind.RETURNED:
            return "因归还重新获得"
        if kind == TitleHistoryActionKind.BECAME_INDEPENDENT:
            return "取得独立地位并辖有"
        if kind == TitleHistoryActionKind.SWORE_FEALTY:
            return "经宣誓效忠获得"
        if kind == TitleHistoryActionKind.USURPATION:
            return "经篡位取得"
        if kind == TitleHistoryActionKind.UNKNOWN:
            return "取得方式未载"
        return "获得以下领地"
    if st == TitleSemanticType.PERSONAL_OFFICE:
        if kind == TitleHistoryActionKind.APPOINTED:
            return "经任命就任以下官职"
        if kind == TitleHistoryActionKind.ADMINISTRATIVE_SUCCESSION:
            return "经任命继任以下官职"
        if kind == TitleHistoryActionKind.REVOKED:
            return "就任以下官职"
        return "就任以下官职"
    if st == TitleSemanticType.REALM_INSTITUTION:
        # 机构归入统治体系：**不**表示个人任职。
        if kind in (TitleHistoryActionKind.UNKNOWN, TitleHistoryActionKind.MIGRATED):
            return "以下政权机构的归属发生变化"
        return "以下机构归入其统治体系"
    if st == TitleSemanticType.RELIGIOUS_OFFICE:
        return "出任以下宗教职务"
    if st == TitleSemanticType.CLAIM_ONLY:
        return "获得以下宣称"
    if st == TitleSemanticType.HONORARY_TITLE:
        return "获授以下荣誉"
    if st == TitleSemanticType.DYNASTY_IDENTITY:
        return "以下领地被创建"
    return "获得"


def _loss_verb(st: TitleSemanticType, kind: TitleHistoryActionKind) -> str:
    """失去方向：按动作给出确定性文案（revoked/stepped_down/abdicated/…）。"""
    if st == TitleSemanticType.SOVEREIGN_REALM_TITLE:
        if kind == TitleHistoryActionKind.ABDICATED:
            return "退位，不再持有以下主权领地"
        if kind == TitleHistoryActionKind.STEPPED_DOWN:
            return "卸下统治身份，不再持有以下主权领地"
        if kind == TitleHistoryActionKind.REVOKED:
            return "统治权被收回，失去以下主权领地"
        if kind == TitleHistoryActionKind.DESTROYED:
            return "以下主权领地被消灭"
        if kind == TitleHistoryActionKind.CONQUERED:
            return "因被征服而失去以下主权领地"
        return "失去以下主权领地"
    if st in (
        TitleSemanticType.TERRITORIAL_REALM_TITLE,
        TitleSemanticType.SUBORDINATE_TERRITORY,
    ):
        if kind == TitleHistoryActionKind.REVOKED:
            return "以下领地控制权被收回"
        if kind == TitleHistoryActionKind.STEPPED_DOWN:
            return "结束以下领地任期"
        if kind == TitleHistoryActionKind.LEASED_OUT:
            return "将以下领地租借或委托管理"
        if kind == TitleHistoryActionKind.RETURNED:
            return "以下领地归还原属"
        if kind == TitleHistoryActionKind.DESTROYED:
            return "以下领地被消灭"
        if kind == TitleHistoryActionKind.CONQUERED:
            return "因被征服而失去"
        return "失去以下领地"
    if st == TitleSemanticType.PERSONAL_OFFICE:
        if kind == TitleHistoryActionKind.REVOKED:
            return "被免去以下官职"
        if kind == TitleHistoryActionKind.STEPPED_DOWN:
            return "结束以下官职任期"
        return "卸任以下官职"
    if st == TitleSemanticType.REALM_INSTITUTION:
        if kind == TitleHistoryActionKind.UNKNOWN:
            return "以下政权机构的归属发生变化"
        return "以下机构不再属于其统治体系"
    if st == TitleSemanticType.RELIGIOUS_OFFICE:
        return "卸任以下宗教职务"
    if st == TitleSemanticType.CLAIM_ONLY:
        return "失去以下宣称"
    if st == TitleSemanticType.HONORARY_TITLE:
        return "以下荣誉被剥夺"
    if st == TitleSemanticType.DYNASTY_IDENTITY:
        return "以下领地被消灭"
    return "失去"


class TitleHistoryActionNormalizer:
    """把一条 title change（raw_type + direction + semantic type）规范化为动作语义。"""

    def normalize(
        self,
        *,
        entry: Optional[dict],
        date: str,
        direction: str,
        semantic_type: TitleSemanticType,
        title_id: str = "",
        context: Optional[dict] = None,
    ) -> TitleHistoryAction:
        """逐条 title change 解析。

        entry 为 titles.json 中该头衔的原始条目（含 history）；缺失 → unknown。
        从该条目 history 中找 date 对应记录：
          - raw_type 显式存在 → 按 _RAW_TYPE_TO_ACTION 映射（含 conquest 子类）；
          - 无 raw_type（旧缓存/Format A）→ 回退 kind（created/destroyed），
            type_source 标 reader_default；
          - 其余 → unknown（保留约束「不得推断因果」）。
        """
        if entry is None:
            return TitleHistoryAction(
                rawType=None,
                normalizedAction=TitleHistoryActionKind.UNKNOWN,
                acquisitionCause=None,
                confidence=Confidence.UNCERTAIN,
                typeSource=AcquisitionTypeSource.UNKNOWN,
                summaryVerb=self._verb(TitleHistoryActionKind.UNKNOWN, direction, semantic_type),
                narrativeConstraints=_unknown_constraints(semantic_type),
            )

        for h in entry.get("history") or []:
            if str(h.get("date")) != str(date):
                continue
            raw = h.get("raw_type")
            if raw is not None:
                return self._from_raw_type(str(raw), direction, semantic_type, title_id)
            kind = h.get("kind")
            if kind == "created":
                # 旧缓存（无 raw_type）：reader 从存档 type=created 映射而来。
                return self._from_raw_type(
                    "created", direction, semantic_type, title_id,
                    type_source=AcquisitionTypeSource.READER_DEFAULT,
                )
            if kind == "destroyed":
                # 该日条目是销毁记录：对「获得」而言不能作为原因（销毁与获得矛盾）。
                if direction != "loss":
                    return TitleHistoryAction(
                        rawType="destroyed",
                        normalizedAction=TitleHistoryActionKind.UNKNOWN,
                        acquisitionCause=None,
                        confidence=Confidence.UNCERTAIN,
                        typeSource=AcquisitionTypeSource.READER_DEFAULT,
                        summaryVerb=self._verb(TitleHistoryActionKind.UNKNOWN, direction, semantic_type),
                        narrativeConstraints=_unknown_constraints(semantic_type),
                        rawTypeGroup="none",
                    )
                return TitleHistoryAction(
                    rawType="destroyed",
                    normalizedAction=TitleHistoryActionKind.DESTROYED,
                    acquisitionCause=None,
                    confidence=Confidence.CONFIRMED,
                    typeSource=AcquisitionTypeSource.READER_DEFAULT,
                    summaryVerb=self._verb(TitleHistoryActionKind.DESTROYED, direction, semantic_type),
                )
            # kind=holder（Format A 裸持有者变更）→ unknown。
            return TitleHistoryAction(
                rawType=None,
                normalizedAction=TitleHistoryActionKind.UNKNOWN,
                acquisitionCause=None,
                confidence=Confidence.UNCERTAIN,
                typeSource=AcquisitionTypeSource.UNKNOWN,
                summaryVerb=self._verb(TitleHistoryActionKind.UNKNOWN, direction, semantic_type),
                narrativeConstraints=_unknown_constraints(semantic_type),
            )
        # 该日期无对应 history 记录（如 title 索引缺该日）→ unknown。
        return TitleHistoryAction(
            rawType=None,
            normalizedAction=TitleHistoryActionKind.UNKNOWN,
            acquisitionCause=None,
            confidence=Confidence.INFERRED,
            typeSource=AcquisitionTypeSource.UNKNOWN,
            summaryVerb=self._verb(TitleHistoryActionKind.UNKNOWN, direction, semantic_type),
            narrativeConstraints=_unknown_constraints(semantic_type),
        )

    # -- 内部 ---------------------------------------------------------------
    def _from_raw_type(
        self,
        raw: str,
        direction: str,
        semantic_type: TitleSemanticType,
        title_id: str,
        type_source: AcquisitionTypeSource = AcquisitionTypeSource.SAVE_EXPLICIT,
    ) -> TitleHistoryAction:
        action = _RAW_TYPE_TO_ACTION.get(raw)
        warnings: List[str] = []
        subtype = None
        if action is None:
            # 显式 type 但无可信映射：保留原始字符串，标 inferred，不擅自归并。
            return TitleHistoryAction(
                rawType=raw,
                normalizedAction=TitleHistoryActionKind.UNKNOWN,
                acquisitionCause=None,
                confidence=Confidence.INFERRED,
                typeSource=type_source,
                summaryVerb=self._verb(TitleHistoryActionKind.UNKNOWN, direction, semantic_type),
                narrativeConstraints=[_CONSTRAINT_UNMAPPED_RAW.format(raw=raw)],
                warnings=[f"显式 type={raw} 暂无可信语义映射（title={title_id or '?'}）。"],
                rawTypeGroup=f"unknown:{raw}",
            )
        if action == TitleHistoryActionKind.DESTROYED and direction != "loss":
            # 销毁记录不能解释「获得」；保留原始字符串但归 unknown 原因。
            return TitleHistoryAction(
                rawType=raw,
                normalizedAction=TitleHistoryActionKind.UNKNOWN,
                acquisitionCause=None,
                confidence=Confidence.UNCERTAIN,
                typeSource=type_source,
                summaryVerb=self._verb(TitleHistoryActionKind.UNKNOWN, direction, semantic_type),
                narrativeConstraints=_unknown_constraints(semantic_type),
                rawTypeGroup="none",
            )
        if action == TitleHistoryActionKind.CONQUERED:
            subtype = _CONQUEST_SUBTYPES.get(raw, "generic")
        # 领地/主权语义的「经任命获得统治权」→ 任命原因；个人官职任命不属领土获得。
        cause = _ACTION_CAUSES.get(action)
        if cause is AcquisitionCause.APPOINTMENT and semantic_type not in _REALM_SEMANTIC_TYPES:
            cause = None
        # migration 属机制解释（inferred）；其余显式 type 为 confirmed。
        confidence = (
            Confidence.INFERRED
            if action == TitleHistoryActionKind.MIGRATED
            else Confidence.CONFIRMED
        )
        # realm_institution：无论动作如何，都附机构所有权约束（不表示个人任职）。
        constraints: List[str] = []
        if semantic_type == TitleSemanticType.REALM_INSTITUTION:
            constraints.append(_CONSTRAINT_INSTITUTION_OWNERSHIP)
        return TitleHistoryAction(
            rawType=raw,
            normalizedAction=action,
            acquisitionCause=cause,
            confidence=confidence,
            typeSource=type_source,
            summaryVerb=self._verb(action, direction, semantic_type),
            narrativeConstraints=constraints,
            warnings=warnings,
            subtype=subtype,
            rawTypeGroup=action.value,
        )

    def _verb(
        self,
        action: TitleHistoryActionKind,
        direction: str,
        semantic_type: TitleSemanticType,
    ) -> str:
        if direction == "loss":
            return _loss_verb(semantic_type, action)
        return _gain_verb(semantic_type, action)
