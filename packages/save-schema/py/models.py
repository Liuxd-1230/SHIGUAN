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
from typing import Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, field_validator


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


class SaveKind(str, Enum):
    """存档编码形态（与 TS SaveKind 严格对齐；运行时校验，非法值被拒）。"""
    TEXT = "text"            # 调试明文 / 解压后的 gamestate / 纯文本存档
    TEXT_ZIP = "text_zip"    # 标准 .ck3：明文头 + zip 压缩明文 gamestate
    BINARY_ZIP = "binary_zip"  # 二进制 .ck3：二进制头 + zip 压缩二进制 gamestate
    BINARY = "binary"        # 自动存档的未压缩二进制 gamestate
    IRONMAN = "ironman"      # 铁人存档（二进制 + 需令牌表才能解码）


class Encoding(str, Enum):
    """文本编码（CK3 用 UTF-8，与 EU4 的 Windows-1252 不同）。"""
    UTF8 = "utf-8"
    WINDOWS_1252 = "windows-1252"
    UNKNOWN = "unknown"


class RelationshipType(str, Enum):
    """关系类型（替换原先退化的任意字符串字段）。"""
    SPOUSE = "spouse"
    LOVER = "lover"
    FRIEND = "friend"
    RIVAL = "rival"
    MURDERER = "murderer"
    OTHER = "other"


class WarRole(str, Enum):
    """主人物在某场战争中的角色。"""
    ATTACKER = "attacker"
    DEFENDER = "defender"
    PARTICIPANT = "participant"
    OTHER = "other"


class FactCheckStatus(str, Enum):
    """事实校验结论。"""
    PASS = "pass"
    NEEDS_REVISION = "needs_revision"


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
    type: RelationshipType
    start: Optional[str] = None
    end: Optional[str] = None
    confidence: Confidence
    sourcePath: Optional[str] = None


class WarParticipation(BaseModel):
    warId: str
    name: str
    role: WarRole
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


class EvidenceRef(BaseModel):
    """一条可溯源的证据引用。

    用于把 TimelineEvent 关联到存档中的具体出处（而非复制整段原始存档文本）。
    confirmed 事件必须能追到具体证据；inferred 事件需记录推断依据。
    """
    id: str
    # 证据来源类别，如 "save_block" | "localization" | "memory" | "war" | "title"。
    sourceType: str
    # 在解析后存档数据中的来源路径（用于"史料依据"面板回溯）。
    sourcePath: Optional[str] = None
    # 存档中的原始 key（如本地化 key、Clausewitz 对象键），便于精确溯源。
    rawKey: Optional[str] = None
    # 该证据说明了什么。
    description: str
    confidence: Confidence
    # 关联的时间线事件 id（若此证据本身对应某个事件）。
    relatedEventId: Optional[str] = None


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
    # 可溯源的证据引用集合（至少能关联一条 EvidenceRef）。
    evidence: List[EvidenceRef] = Field(default_factory=list)


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


class CharacterSummary(BaseModel):
    """人物列表摘要（用于人物选择页），由完整档案按需派生。

    只保留卡片/列表渲染所需的轻量字段，避免大型存档一次性生成全部
    完整 CharacterProfile。完整档案通过 ParsedSave.profiles 按需获取。
    """
    id: str
    name: str
    sex: Optional[Sex] = None
    birthDate: Optional[str] = None
    deathDate: Optional[str] = None
    dynasty: Optional[EntityRef] = None
    house: Optional[EntityRef] = None
    culture: Optional[EntityRef] = None
    faith: Optional[EntityRef] = None
    primaryTitle: Optional[EntityRef] = None
    highestTitleTier: Optional[TitleTier] = None
    isRuler: bool = False
    isAlive: bool = True
    isPlayerDynasty: bool = False
    portraitKey: Optional[str] = None
    evidenceWarningCount: int = 0


# 索引条目与摘要同形（保持两个命名同时存在，便于前后端引用）。
CharacterIndexEntry = CharacterSummary


# ---------------------------------------------------------------------------
# 传记展示层
# ---------------------------------------------------------------------------

class BiographyChapterOutline(BaseModel):
    id: str
    title: str
    # 本章依据的时间线事件 id 列表，不得为空（运行时校验）。
    eventIds: List[str] = Field(min_length=1)
    summary: str

    @field_validator("eventIds")
    @classmethod
    def _non_empty_event_ids(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("eventIds 不得为空：每章必须至少引用一个时间线事件")
        return v


class BiographyOutline(BaseModel):
    profileId: str
    style: BiographyStyle
    chapters: List[BiographyChapterOutline]


class BiographyChapter(BaseModel):
    id: str
    title: str
    content: str
    # 本章正文所追溯的时间线事件 id，不得为空（运行时校验）。
    eventIds: List[str] = Field(min_length=1)

    @field_validator("eventIds")
    @classmethod
    def _non_empty_event_ids(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("eventIds 不得为空：每章必须至少引用一个时间线事件")
        return v


class FactCheckIssue(BaseModel):
    rule: str
    severity: WarningSeverity
    message: str
    suggestedFix: Optional[str] = None


class FactCheckResult(BaseModel):
    status: FactCheckStatus
    issues: List[FactCheckIssue] = Field(default_factory=list)


class Biography(BaseModel):
    profileId: str
    style: BiographyStyle
    chapters: List[BiographyChapter]
    generatedAt: str
    modelName: str
    factCheck: Optional[FactCheckResult] = None
    profileDigest: Optional[str] = None


# ---------------------------------------------------------------------------
# 存档解析层（适配器协议与产出）
# ---------------------------------------------------------------------------

class MissingComponent(BaseModel):
    """缺失的外部解析组件（如 Rakaly CLI）及其安装提示。"""
    name: str
    hint: str


class SaveInspection(BaseModel):
    """文件初检结果。由 SaveParserAdapter.inspect() 产出，绝不解析内容本身。"""
    path: str
    kind: SaveKind
    # 编码：CK3 使用 UTF-8（与 EU4 的 Windows-1252 不同）。
    encoding: Encoding
    sizeBytes: int
    isCompressed: bool
    isIronman: bool
    # 是否可不依赖外部组件、在本地直接解析。
    canParseLocally: bool
    # 是否需要外部解析器（如 Rakaly CLI）。
    needsExternal: bool
    # 缺失的外部组件名称与安装提示（若有）。
    missingComponent: Optional[MissingComponent] = None


class ParsedSaveMeta(BaseModel):
    """解析后存档的元信息。"""
    saveVersion: Optional[str] = None
    gameVersion: Optional[str] = None
    date: Optional[str] = None
    playerId: Optional[str] = None
    campaignId: Optional[str] = None


class ParsedSave(BaseModel):
    """解析后的存档索引与人物档案。

    设计要点：把"人物摘要索引"（characterIndex，轻量、用于选择页）
    与"按需完整档案"（profiles，按 id 取用）分离，避免大型存档一次性
    生成全部完整 CharacterProfile。
    """
    meta: ParsedSaveMeta = Field(default_factory=ParsedSaveMeta)
    characterIndex: List[CharacterIndexEntry] = Field(default_factory=list)
    profiles: Dict[str, CharacterProfile] = Field(default_factory=dict)
    dynasties: Dict[str, EntityRef] = Field(default_factory=dict)
    houses: Dict[str, EntityRef] = Field(default_factory=dict)
    titles: Dict[str, EntityRef] = Field(default_factory=dict)
    counties: Dict[str, EntityRef] = Field(default_factory=dict)
    cultures: Dict[str, EntityRef] = Field(default_factory=dict)
    faiths: Dict[str, EntityRef] = Field(default_factory=dict)
    relationships: Dict[str, List[RelationshipPeriod]] = Field(default_factory=dict)
    wars: Dict[str, WarParticipation] = Field(default_factory=dict)
    memories: List[LifeEvent] = Field(default_factory=list)
    # 本地化文本表：key -> 可读名称。
    localization: Dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Mock / 测试数据包裹层
# ---------------------------------------------------------------------------

class MockDatasetPayload(BaseModel):
    """FixtureEnvelope 的默认 data 载体：一组 Mock 人物摘要与按需档案。"""
    characterIndex: List[CharacterIndexEntry] = Field(default_factory=list)
    profiles: Dict[str, CharacterProfile] = Field(default_factory=dict)
    # 其余索引数据（dynasties/houses/...）按需扩展。
    extra: Dict[str, object] = Field(default_factory=dict)


class MockIndexPayload(BaseModel):
    """索引包的 data 载体（Phase 1B 起用于真正的"按需加载"）。

    只携带轻量摘要与档案定位符（profileIds），**不**内联完整
    CharacterProfile，避免大型存档初始化时一次性把所有完整档案打进 bundle。
    """
    meta: ParsedSaveMeta = Field(default_factory=ParsedSaveMeta)
    characterIndex: List[CharacterIndexEntry] = Field(default_factory=list)
    profileIds: List[str] = Field(default_factory=list)


T = TypeVar("T")


class FixtureEnvelope(BaseModel, Generic[T]):
    """Mock / 测试数据的包裹结构。

    元数据（isMock / source / schemaVersion / generatedFor）与真实业务
    模型隔离：真实 CharacterProfile 等不携带这些字段，避免污染。
    """
    isMock: Literal[True] = True
    source: Literal["fixtures/mock"] = "fixtures/mock"
    schemaVersion: str
    generatedFor: str
    data: T


# 常用具名实例：包裹一份 MockDatasetPayload。
MockDataset = FixtureEnvelope[MockDatasetPayload]

# 常用具名实例：包裹一份 MockIndexPayload（仅摘要 + 档案定位符）。
MockIndex = FixtureEnvelope[MockIndexPayload]
