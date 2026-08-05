"""biography-engine 数据模型（Phase 3C.4：CompressedProfile v3）。

`CompressedProfile` 是传给模型的唯一人物数据载体：
  - 完全由确定性代码从 CharacterProfile 压缩生成；
  - v3 结构化重构：identity / dynasticIdentity / territorialDomain /
    personalOffices / realmInstitutions / religiousOffices / honors / claims /
    family / relationships / wars / historicalEvents / selectedEvents /
    facts / narrativeConstraints / warnings；
  - unresolved 数字人物名不进入自然语言摘要（见 compressor / llm_input_filter）；
  - 每条事件保留 `eventId`，供提纲引用与白名单校验；
  - v1/v2 结构不再产出（COMPRESSION_VERSION="3"，store 侧按版本号标记 stale）。
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from models import (
    Confidence,
    FactRef,
    HistoricalSemanticEvent,
)  # save-schema 契约（Python 侧）

COMPRESSION_VERSION = "3"


class CompressedEvent(BaseModel):
    """压缩后保留的一条时间线事件（供提纲引用）。"""

    eventId: str
    date: Optional[str] = None
    endDate: Optional[str] = None
    type: str
    title: str
    # 事实性摘要（不伪造：仅由描述/证据的确定性清洗而来）。
    factualSummary: str
    confidence: Confidence
    # 可安全写入自然语言的人物名（已过滤 unresolved 数字占位名）。
    relatedNames: List[str] = Field(default_factory=list)
    evidenceCount: int = 0
    mergedCount: Optional[int] = None


class CompressedIdentity(BaseModel):
    """v3 结构化身份（确定性提炼，含主要身份与基本档案）。"""

    displayName: str = ""
    nickname: Optional[str] = None
    sex: Optional[str] = None
    birthDate: Optional[str] = None
    deathDate: Optional[str] = None
    lifeSpan: Optional[str] = None
    deathReason: Optional[str] = None
    # PrimaryIdentityResolver 产出（headline 用游戏原生名，无 tier 爵位词）。
    headlineIdentity: Optional[str] = None
    realmStatus: Optional[str] = None
    primaryRealmTitle: Optional[str] = None
    primaryOffice: Optional[str] = None
    secondaryIdentities: List[str] = Field(default_factory=list)
    traits: List[str] = Field(default_factory=list)


class CompressedDynasticIdentity(BaseModel):
    """v3 世系身份（姓/家族）。"""

    house: Optional[str] = None
    dynasty: Optional[str] = None


class CompressedTerritorialDomain(BaseModel):
    """v3 领土域（现任主要领地 + 从属数量 + 历史得失计数）。"""

    currentMajorTerritories: List[str] = Field(default_factory=list)
    currentMinorCount: int = 0
    historicalGainCount: int = 0
    historicalLossCount: int = 0


class CompressedProfile(BaseModel):
    """传给模型的确定性压缩档案（v3）。"""

    profileId: str
    displayName: str
    # ---- v3 结构化身份 / 世系 / 领土 ----
    identity: CompressedIdentity = Field(default_factory=CompressedIdentity)
    dynasticIdentity: CompressedDynasticIdentity = Field(
        default_factory=CompressedDynasticIdentity
    )
    territorialDomain: CompressedTerritorialDomain = Field(
        default_factory=CompressedTerritorialDomain
    )
    # ---- v3 官职 / 机构 / 宗教 / 荣誉 / 宣称 ----
    personalOffices: List[str] = Field(default_factory=list)
    realmInstitutions: List[str] = Field(default_factory=list)
    religiousOffices: List[str] = Field(default_factory=list)
    honors: List[str] = Field(default_factory=list)
    claims: List[str] = Field(default_factory=list)
    # ---- v3 家庭 / 关系 / 战争 ----
    # 父母/子女/兄弟姐妹/配偶等自然语言事实（确定性，仅可解析名）。
    family: List[str] = Field(default_factory=list)
    # 扩展亲属（结构化，全部推断）。
    relatives: List[CompressedRelative] = Field(default_factory=list)
    # 好友/宿敌/恋人/君主（确定性，仅可解析名）。
    relationships: List[str] = Field(default_factory=list)
    # 战争叙事（WarNarrativeNormalizer）：每条一场战争。
    wars: List[str] = Field(default_factory=list)
    # ---- v3 历史语义事件（3C.3，同日按语义类型拆分，不推断因果）----
    historicalEvents: List[HistoricalSemanticEvent] = Field(default_factory=list)
    # ---- 事件 / 事实 / 约束 ----
    selectedEvents: List[CompressedEvent] = Field(default_factory=list)
    # 3C.5：确定性提炼的事实集（BiographyChapter.factIds 引用；LLM 不得超出）。
    facts: List[FactRef] = Field(default_factory=list)
    # 叙事约束（如「存档未记录获得途径，不得推断继承/征服/册封」）。
    narrativeConstraints: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    unresolvedCount: int = 0
    sourceEventIds: List[str] = Field(default_factory=list)
    compressionVersion: str = COMPRESSION_VERSION


class CompressedRelative(BaseModel):
    """扩展亲属（v2 保留）：按血缘/姻亲分类的确定性限量条目。

    全部来自 `derive_extended_relations`（基于父系反推链），均为推断而非存档直述，
    故 `inferred` 恒为 True；每组（祖辈/叔伯姑舅/堂表亲/侄甥/姻亲）限量展示。
    """

    relation: str  # grandparent / aunt_uncle / cousin / nephew / in_law
    relationLabel: str  # 中文标签
    name: str
    id: str
    inferred: bool = True
