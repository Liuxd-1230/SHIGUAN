"""
SHIGUAN —— Python 侧数据契约（与 packages/save-schema/src/types.ts 镜像）

本模块用 Pydantic v2 定义后端在 Phase 2 起需要的标准人物档案与时间线模型。
它是 TS 类型的 Python 版事实来源，二者字段必须保持同步。

注意：
  - 本文件在 Phase 0 仅作为契约定义，运行语法检查即可（py_compile），
    不要求此时已安装 pydantic。
  - 所有"证据"字段都带 confidence，区分 confirmed / inferred / uncertain。
  - CharacterProfile 是原始数据层；Biography 是展示层，且只引用事件 ID。
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------

class Confidence(str, Enum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    UNCERTAIN = "uncertain"


class Sex(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class TitleTier(str, Enum):
    BARONY = "barony"
    COUNTY = "county"
    DUCHY = "duchy"
    KINGDOM = "kingdom"
    EMPIRE = "empire"


class EventType(str, Enum):
    BIRTH = "birth"
    DEATH = "death"
    MARRIAGE = "marriage"
    DIVORCE = "divorce"
    CHILD_BIRTH = "child_birth"
    SUCCESSION = "succession"
    TITLE_GAIN = "title_gain"
    TITLE_LOSS = "title_loss"
    WAR = "war"
    IMPRISONMENT = "imprisonment"
    EXILE = "exile"
    TRAVEL = "travel"
    COURT_POSITION = "court_position"
    CONVERSION = "conversion"
    TRAIT_GAIN = "trait_gain"
    SUCCESS = "success"
    FAILURE = "failure"
    OTHER = "other"


class WarningSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class BiographyStyle(str, Enum):
    VERNACULAR_ANNALS = "vernacular_annals"
    SERIOUS_BIOGRAPHY = "serious_biography"
    MEDIEVAL_CHRONICLE = "medieval_chronicle"
    FAMILY_MEMOIR = "family_memoir"
    CONCISE_PROFILE = "concise_profile"
    COLD_HISTORIAN = "cold_historian"


# ---------------------------------------------------------------------------
# 值对象
# ---------------------------------------------------------------------------

class EntityRef(BaseModel):
    id: str
    name: str
    type: Optional[str] = None
    sourcePath: Optional[str] = None


class CharacterRef(BaseModel):
    id: str
    name: str
    sex: Optional[Sex] = None
    birthDate: Optional[str] = None
    deathDate: Optional[str] = None
    dynasty: Optional[EntityRef] = None
    primaryTitle: Optional[EntityRef] = None


class TraitRecord(BaseModel):
    id: str
    name: str
    category: Optional[str] = None
    sourcePath: Optional[str] = None


class TitlePeriod(BaseModel):
    titleId: str
    name: str
    tier: Optional[TitleTier] = None
    start: Optional[str] = None
    end: Optional[str] = None
    isCurrent: Optional[bool] = None
    government: Optional[str] = None
    sourcePath: Optional[str] = None


class ResidencePeriod(BaseModel):
    locationId: str
    name: str
    start: Optional[str] = None
    end: Optional[str] = None
    confidence: Confidence
    sourcePath: Optional[str] = None


class PositionPeriod(BaseModel):
    courtId: Optional[str] = None
    courtName: Optional[str] = None
    positionId: str
    name: str
    start: Optional[str] = None
    end: Optional[str] = None
    employerId: Optional[str] = None
    sourcePath: Optional[str] = None


class RelationshipPeriod(BaseModel):
    characterId: str
    name: str
    type: str = Field(description="spouse|lover|friend|rival|murderer|other")
    start: Optional[str] = None
    end: Optional[str] = None
    confidence: Confidence
    sourcePath: Optional[str] = None


class WarParticipation(BaseModel):
    warId: str
    name: str
    role: str = Field(description="attacker|defender|participant|other")
    side: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    outcome: Optional[str] = None
    sourcePath: Optional[str] = None


class LifeEvent(BaseModel):
    id: str
    type: EventType
    date: Optional[str] = None
    description: str
    relatedCharacters: List[CharacterRef] = Field(default_factory=list)
    location: Optional[EntityRef] = None
    confidence: Confidence
    sourcePath: Optional[str] = None


# ---------------------------------------------------------------------------
# 时间线与证据
# ---------------------------------------------------------------------------

class TimelineEvent(BaseModel):
    id: str
    date: Optional[str] = None
    endDate: Optional[str] = None
    type: EventType
    title: str
    description: str
    location: Optional[EntityRef] = None
    relatedCharacters: List[CharacterRef] = Field(default_factory=list)
    relatedTitles: List[EntityRef] = Field(default_factory=list)
    sourcePath: Optional[str] = None
    confidence: Confidence


class EvidenceWarning(BaseModel):
    code: str
    message: str
    severity: WarningSeverity
    relatedEventId: Optional[str] = None
    sourcePath: Optional[str] = None


# ---------------------------------------------------------------------------
# 标准人物档案（原始数据层）
# ---------------------------------------------------------------------------

class CharacterProfile(BaseModel):
    id: str
    name: str
    sex: Optional[Sex] = None
    birthDate: Optional[str] = None
    deathDate: Optional[str] = None
    deathReason: Optional[str] = None

    dynasty: Optional[EntityRef] = None
    house: Optional[EntityRef] = None
    culture: Optional[EntityRef] = None
    faith: Optional[EntityRef] = None

    traits: List[TraitRecord] = Field(default_factory=list)
    titles: List[TitlePeriod] = Field(default_factory=list)
    residences: List[ResidencePeriod] = Field(default_factory=list)
    courtPositions: List[PositionPeriod] = Field(default_factory=list)

    parents: List[CharacterRef] = Field(default_factory=list)
    spouses: List[RelationshipPeriod] = Field(default_factory=list)
    children: List[CharacterRef] = Field(default_factory=list)
    siblings: List[CharacterRef] = Field(default_factory=list)

    friends: List[CharacterRef] = Field(default_factory=list)
    rivals: List[CharacterRef] = Field(default_factory=list)
    lovers: List[CharacterRef] = Field(default_factory=list)

    wars: List[WarParticipation] = Field(default_factory=list)
    imprisonments: List[LifeEvent] = Field(default_factory=list)
    travels: List[LifeEvent] = Field(default_factory=list)
    memories: List[LifeEvent] = Field(default_factory=list)

    timeline: List[TimelineEvent] = Field(default_factory=list)
    evidenceWarnings: List[EvidenceWarning] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 传记展示层
# ---------------------------------------------------------------------------

class BiographyChapterOutline(BaseModel):
    id: str
    title: str
    eventIds: List[str]
    summary: str


class BiographyOutline(BaseModel):
    profileId: str
    style: BiographyStyle
    chapters: List[BiographyChapterOutline]


class BiographyChapter(BaseModel):
    id: str
    title: str
    content: str
    eventIds: List[str]


class FactCheckIssue(BaseModel):
    rule: str
    severity: WarningSeverity
    message: str
    suggestedFix: Optional[str] = None


class FactCheckResult(BaseModel):
    status: str = Field(description="pass|needs_revision")
    issues: List[FactCheckIssue] = Field(default_factory=list)


class Biography(BaseModel):
    profileId: str
    style: BiographyStyle
    chapters: List[BiographyChapter]
    generatedAt: str
    modelName: str
    factCheck: Optional[FactCheckResult] = None
    profileDigest: Optional[str] = None
