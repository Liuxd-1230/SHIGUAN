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

COMPRESSION_VERSION = "1"


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
