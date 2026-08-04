"""biography-engine 数据模型（Phase 3A 5.4）。

`CompressedProfile` 是传给模型的唯一人物数据载体：
  - 完全由确定性代码从 CharacterProfile 压缩生成；
  - unresolved 数字人物名不进入自然语言摘要（见 compressor / llm_input_filter）；
  - 每条事件保留 `eventId`，供提纲引用与白名单校验。
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from models import Confidence  # save-schema 契约（Python 侧）

COMPRESSION_VERSION = "2"


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


class CompressedProfile(BaseModel):
    """传给模型的确定性压缩档案。"""

    profileId: str
    displayName: str
    lifeSpan: Optional[str] = None
    identityFacts: List[str] = Field(default_factory=list)
    familyFacts: List[str] = Field(default_factory=list)
    titleFacts: List[str] = Field(default_factory=list)
    relationshipFacts: List[str] = Field(default_factory=list)
    selectedEvents: List[CompressedEvent] = Field(default_factory=list)
    omittedEventCount: int = 0
    warnings: List[str] = Field(default_factory=list)
    unresolvedCount: int = 0
    sourceEventIds: List[str] = Field(default_factory=list)
    compressionVersion: str = COMPRESSION_VERSION
    # ---- v2 新增（Phase 3A.1）----
    # 绰号（如「仁」）：已解析中文才写入。
    nickname: Optional[str] = None
    # 君主名（存于死亡记录，resolved 才写）。
    liegeName: Optional[str] = None
    # 家族名（house，resolved 才写）。
    house: Optional[str] = None
    # 逝世原因（death_reason，raw key 可能为英文模板键，原样保留不翻译）。
    deathReason: Optional[str] = None
    # 特质名（去重、限量）。
    traits: List[str] = Field(default_factory=list)
    # 扩展亲属（分类 + 确定性限量，全部标 inferred）。
    relatives: List[CompressedRelative] = Field(default_factory=list)
    # ---- v2 叙事摘要（3A.1：确定性整理，非 AI）----
    # 统治摘要：现任头衔总数 + 最高等级 + 3-5 个主要头衔（确定性，不出现内部枚举）。
    reignSummary: Optional[str] = None
    # 战争叙事（WarNarrativeNormalizer）：每条一场战争；defender/unknown 绝不写成主动宣战。
    warSummary: List[str] = Field(default_factory=list)
    # 聚合告警约束（WarningAggregator）：按 code 聚合，只传解析策略，不含 sourcePath/数字 id。
    warningSummary: List[str] = Field(default_factory=list)


class CompressedRelative(BaseModel):
    """扩展亲属（v2）：按血缘/姻亲分类的确定性限量条目。

    全部来自 `derive_extended_relations`（基于父系反推链），均为推断而非存档直述，
    故 `inferred` 恒为 True；每组（祖辈/叔伯姑舅/堂表亲/侄甥/姻亲）限量展示。
    """

    relation: str  # grandparent / aunt_uncle / cousin / nephew / in_law
    relationLabel: str  # 中文标签
    name: str
    id: str
    inferred: bool = True
