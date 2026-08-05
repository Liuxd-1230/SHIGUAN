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
    """关系类型（替换原先退化的任意字符串字段）。

    M4：新增 betrothed（婚约）与 concubine（妾室），与 spouse 并列——
    CK3 存档分别以 primary_spouse / former_spouses / betrothed / concubine 字段直述。
    """
    SPOUSE = "spouse"
    LOVER = "lover"
    FRIEND = "friend"
    RIVAL = "rival"
    MURDERER = "murderer"
    BETROTHED = "betrothed"
    CONCUBINE = "concubine"
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


class TitleStatus(str, Enum):
    """人物主头衔判定状态（P0：顶部头衔与 titles 列表同源后区分三种诚实降级）。

    前端据此区分「确认无头衔 / 持有头衔但主头衔未能确定 / 索引不可用」，
    不再把索引不可用误显示为「无头衔」。
    """
    RESOLVED = "resolved"              # 有现任头衔且主头衔可确定
    NO_TITLES = "no_titles"            # 确认无现任头衔（titles 列表为空）
    TIER_UNKNOWN = "tier_unknown"      # 持有现任头衔但等级未知，主头衔无法可靠判定
    INDEX_UNAVAILABLE = "index_unavailable"  # 头衔索引不可用，无法判定（不伪造）


class EntityKind(str, Enum):
    """实体类别，共 10 类，与 Rust scan_entities 的 EKind 一一对应。"""
    TRAIT = "trait"
    FAITH = "faith"
    RELIGION = "religion"
    CULTURE = "culture"
    HOUSE = "house"
    DYNASTY = "dynasty"
    TITLE = "title"
    WAR = "war"
    MEMORY_TYPE = "memoryType"
    COURT_POSITION_TYPE = "courtPositionType"


class EntityKeyKind(str, Enum):
    """内部键性质：缺省（未标注）即 loc，可直接查本地化；def 需先查游戏定义库。"""
    LOC = "loc"
    DEF = "def"


class EntityNameSource(str, Enum):
    """实体最终可读名的来源，用于可追溯与诚实性标注。"""
    SAVE = "save"                # 存档成品名（玩家自定义头衔/混合文化/战争名）
    GAME_DEF = "game_def"        # 游戏定义文件（game/common）反查得到的本地化键
    LOC = "loc"                  # 本地化表命中
    LITERAL = "literal"          # 明文存档，字段名本身即可读 key
    UNRESOLVED = "unresolved"    # 无法命名：name 退化为原始 id


class TokenSourceKind(str, Enum):
    """当前解析所用的令牌表来源。"""
    PLACEHOLDER = "placeholder"          # 占位全量 token 表（id→tXXXX），enum 保持数字
    BUILTIN_VALIDATED = "builtin_validated"  # 内置校验过的真实字段名映射
    USER_LOCAL = "user_local"            # 用户自备真实令牌表
    LITERAL_KEY = "literal_key"          # 明文存档，字段名即可读 key


class TokenCompatibility(str, Enum):
    """令牌表兼容性状态。"""
    OK = "ok"
    PARTIAL = "partial"
    INCOMPATIBLE = "incompatible"
    EXTERNAL_MISSING = "external_missing"


class TitleSemanticType(str, Enum):
    """头衔语义分类（Phase 3C.2，12 类）。

    分类依据为「该头衔对持有者的语义角色」，由确定性规则（config/title-semantics/
    规则注册表 + 键前缀/层级/封臣结构启发式）判定，**不**由 LLM 自行分类。
    与 tier（barony…empire）解耦：tier 只是技术属性，语义决定叙事写法。
    """
    SOVEREIGN_REALM_TITLE = "sovereign_realm_title"      # 独立王国/帝国（顶层，liege=None）
    TERRITORIAL_REALM_TITLE = "territorial_realm_title"  # 作为封臣领有的王国/公国/伯爵领等封地
    SUBORDINATE_TERRITORY = "subordinate_territory"      # 从属领地（伯/男爵领，隶属上级领地）
    PERSONAL_OFFICE = "personal_office"                  # 个人官职（某人担任的职务头衔）
    REALM_INSTITUTION = "realm_institution"              # 政权机构（朝廷常设机构，如政事堂/御史台）
    RELIGIOUS_OFFICE = "religious_office"                # 宗教职务（教宗/大主教等）
    DYNASTY_IDENTITY = "dynasty_identity"                # 家族/世系身份头衔（如 x_nf_ 家族名）
    HONORARY_TITLE = "honorary_title"                    # 荣誉头衔（无实权）
    TEMPORARY_TITLE = "temporary_title"                  # 临时性头衔（营地/居留等）
    CLAIM_ONLY = "claim_only"                            # 仅拥宣称、未实际持有（存档无法直接证明时不得虚构）
    SPECIAL_MOD_TITLE = "special_mod_title"              # 特定 Mod 明确命名、无法按基座规则归类
    UNKNOWN = "unknown"                                  # 无法确认，诚实留空


class RealmStatus(str, Enum):
    """人物当前的身份地位（Phase 3C.2，由现任头衔结构确定性推导）。

    只依据存档可证的现任头衔/君主/官职结构判定；无法判定时为 unknown，
    绝不把「无现任头衔」一律写成平民（还可能是前任君主/官员）。
    """
    INDEPENDENT_RULER = "independent_ruler"  # 独立最高统治者（持有 liege=None 的王国/帝国等）
    VASSAL_RULER = "vassal_ruler"            # 封臣统治者（作为他人封臣持有领地）
    LANDLESS_OFFICIAL = "landless_official"  # 无地官员（持官职但无领地）
    RELIGIOUS_LEADER = "religious_leader"    # 宗教领袖
    REGENT = "regent"                        # 摄政
    ADVENTURER = "adventurer"                # 冒险者（无地）
    COURTIER = "courtier"                    # 廷臣（无头衔无领地）
    FORMER_RULER = "former_ruler"            # 前统治者（无现任头衔，但存有历史任期）
    PRISONER = "prisoner"                    # 囚犯
    UNKNOWN = "unknown"                      # 无法判定，诚实留空


class HistoricalSemanticEventType(str, Enum):
    """历史语义事件类型（Phase 3C.3，14 类）。

    「同日大量 title 变更」按语义类型拆分（一次征服获多地、一日授多官不再
    混为一条），由 HistoricalEventSemanticBuilder 确定性生成，**不**推断因果。
    """
    IDENTITY_TRANSITION = "identity_transition"      # 身份转变（成为某主权领地的最高统治者）
    TERRITORIAL_GAIN = "territorial_gain"            # 获得领地
    TERRITORIAL_LOSS = "territorial_loss"            # 失去领地
    OFFICE_APPOINTMENT = "office_appointment"        # 就任个人官职
    OFFICE_DISMISSAL = "office_dismissal"            # 卸任个人官职
    INSTITUTION_TRANSITION = "institution_transition"  # 政权机构归属/控制关系变化（归入/脱离统治体系）
    RELIGIOUS_APPOINTMENT = "religious_appointment"  # 出任宗教职务
    RELIGIOUS_DISMISSAL = "religious_dismissal"      # 卸任宗教职务
    CLAIM_GAINED = "claim_gained"                    # 获得宣称
    CLAIM_LOST = "claim_lost"                        # 失去宣称
    HONOR_GRANTED = "honor_granted"                  # 获授荣誉
    HONOR_REVOKED = "honor_revoked"                  # 荣誉被剥夺
    REALM_CREATED = "realm_created"                  # 领地被创建（history kind=created）
    REALM_DESTROYED = "realm_destroyed"              # 领地被消灭（history kind=destroyed）


class AcquisitionCause(str, Enum):
    """领土/头衔获得原因（Phase 3C.3 + 3C.7）。

    存档 titles.json 记录 holder 变更（kind=created/holder/other）与显式 type
    （conquest/granted/…）。自 CACHE_SCHEMA_VERSION=3 起 reader 把显式 type 以
    `raw_type` 原样保留，`TitleHistoryActionNormalizer` 据此确认原因；仍没有显式
    type 的变更一律 unknown，绝不因时间相近而推断继承/征服/册封等因果。
    """
    INHERITANCE = "inheritance"                  # 继承（暂无字段直接证实，仅保留枚举位）
    GRANT = "grant"                              # 册封/赐予
    CONQUEST = "conquest"                        # 征服
    USURPATION = "usurpation"                    # 篡位
    CREATION = "creation"                        # 创建（history kind=created 可直接证实）
    ELECTION = "election"                        # 选举
    MARRIAGE = "marriage"                        # 联姻取得
    FACTION = "faction"                          # 派系拥立
    ADMINISTRATIVE_TRANSFER = "administrative_transfer"  # 行政转移（appointment_succession）
    APPOINTMENT = "appointment"                  # 任命取得（appointment）
    PURCHASE = "purchase"                        # 购买
    UNKNOWN = "unknown"                          # 存档未记录，诚实留空


class TitleHistoryActionKind(str, Enum):
    """CK3 title history 动作的规范化语义（Phase 3C.7 TitleHistoryActionNormalizer）。

    由存档显式 `type`（raw_type）→ 规范化动作；**raw_type 原样保留**，本枚举只提供
    统一语义供分组/文案/校验使用。unknown = 存档未记录 type 或暂无可信映射。
    """
    CREATED = "created"                          # 领地被创建
    DESTROYED = "destroyed"                      # 领地被消灭
    GRANTED = "granted"                          # 经授予获得
    CONQUERED = "conquered"                      # 经征服取得（含 conquest_claim/populist/holy_war）
    APPOINTED = "appointed"                      # 经任命（官职/统治权/机构归属，依语义类型）
    ADMINISTRATIVE_SUCCESSION = "administrative_succession"  # 行政任命体系下继任（≠世袭继承）
    MIGRATED = "migrated"                        # 因迁徙机制发生控制变化
    REVOKED = "revoked"                          # 被撤销/被免除/被收回
    STEPPED_DOWN = "stepped_down"                # 结束任期（主动卸任需另有证据）
    ABDICATED = "abdicated"                      # 退位（仅统治身份）
    FACTION_INSTALLED = "faction_installed"      # 因派系要求
    SWORE_FEALTY = "swore_fealty"                # 宣誓效忠
    BECAME_INDEPENDENT = "became_independent"    # 取得独立地位
    LEASED_OUT = "leased_out"                    # 租借或委托管理
    RETURNED = "returned"                        # 归还/恢复原属
    USURPATION = "usurpation"                    # 篡位（存档 type=usurped，本存档未出现）
    UNKNOWN = "unknown"                          # 未记录/未确认，诚实留空


class AcquisitionTypeSource(str, Enum):
    """获得原因的证据来源（3C-Audit，与 acquisitionRawType 配套）。

    严格区分「存档显式记录」与「工具默认推导」，绝不把默认值当存档事实。
    """
    SAVE_EXPLICIT = "save_explicit"   # 存档 history 条目显式记录 type（如 conquest/granted/created）
    READER_DEFAULT = "reader_default" # reader/旧缓存从 kind 映射（历史缓存无 raw_type 时）
    UNKNOWN = "unknown"               # 无任何显式 type，只能诚实留空


# ---------------------------------------------------------------------------
# 值对象
# ---------------------------------------------------------------------------

class EntityRef(BaseModel):
    id: str
    name: str
    type: Optional[str] = None
    sourcePath: Optional[str] = None
    # resolved=False 表示该引用当前只能以原始 id / 键表示（占位 token 表下 enum 字段
    # 为数字/token-id，或本地化未命中），未伪造可读名。
    resolved: bool = True


class CharacterRef(BaseModel):
    id: str
    name: str
    sex: Optional[Sex] = None
    birthDate: Optional[str] = None
    deathDate: Optional[str] = None
    dynasty: Optional[EntityRef] = None
    primaryTitle: Optional[EntityRef] = None
    # 该引用在存档中的来源路径（如 character/1/child/2），用于史料依据面板回溯。
    sourcePath: Optional[str] = None
    # M5.1：姓名是否已解析为可读姓名（True=可从人物索引/本地化得到可读名；
    # False/None=仅保留原始人物 id 或内部 key，不得当作真实姓名写入 LLM 摘要）。
    # 与关系事实的 confidence 无关（父母可能由 child_backref 推断，但名字仍可解析）。
    resolved: Optional[bool] = None


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
    # M4：存档直述的"前任"关系（former_spouses / former_concubines）语义——
    # 与现任区分，避免把前配偶显示成当前配偶。
    isFormer: Optional[bool] = None


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
    # M5：该事件由 N 条重复存档记录合并而成（>1 表示已去重合并；None/1 = 单条记录）。
    mergedCount: Optional[int] = None


class EvidenceWarning(BaseModel):
    code: str
    message: str
    severity: WarningSeverity
    relatedEventId: Optional[str] = None
    sourcePath: Optional[str] = None


# ---------------------------------------------------------------------------
# 历史语义层（Phase 3C：头衔语义分类 / 身份判定 / 历史语义事件 / 事实引用）
# ---------------------------------------------------------------------------

class TitleClassification(BaseModel):
    """单条头衔的语义分类结果（Phase 3C.2）。

    由确定性规则判定（不涉及 LLM）：semanticType 决定叙事角色（主权/领地/官职/
    机构/宗教/家族/荣誉/临时/Mod 类），与 tier 解耦。signals 记录判据
    （key_prefix / tier / de_facto_liege / name 等），warnings 记录降级与不确定性。
    """
    titleId: str
    semanticType: TitleSemanticType
    confidence: Confidence
    # 展示名（TitleDisplayResolver 产出：存档直书 → 本地化 → def → 原 key 回退）。
    displayName: str
    tier: Optional[TitleTier] = None
    # 霸权（hegemony）头衔：h_* 是 CK3 游戏自身的"霸权/超帝国"命名空间
    # （game_concept_hegemony，如 h_china 唐 / h_roman_empire 罗马帝国）。
    # 由 key 前缀确定性判定，任何 h_* 一律成立，不针对具体头衔。
    isHegemony: bool = False
    # 判据与来源规则（如 base-game.yml:vanilla_landed_k、heuristic:liege_adjust）。
    signals: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    sourceRule: Optional[str] = None


# ---------------------------------------------------------------------------
# 3C.7：头衔结构与玩家历史标记（reader P1 字段的结构化契约）
# ---------------------------------------------------------------------------

class TitleHistoryRecord(BaseModel):
    """单条 title history 记录（Phase 3C.7）。

    与 reader titles.json 的 history 条目一一对应：rawType 是存档显式 type 的
    原始字符串，normalizedAction/typeSource 由 TitleHistoryActionNormalizer 补充
    （Python 侧回填；reader 只抄原始字段）。
    """
    date: str
    holderId: Optional[str] = None
    # holder | created | destroyed | other
    kind: str = "holder"
    # 存档显式 type 原始字符串（conquest/granted/appointment_succession/…；无则 None）。
    rawType: Optional[str] = None
    # 规范化动作（conquered/administrative_succession/…；由 normalizer 回填）。
    normalizedAction: Optional[TitleHistoryActionKind] = None
    # 证据来源（save_explicit / reader_default / unknown）。
    typeSource: Optional[AcquisitionTypeSource] = None
    # 该记录在 landed_titles 中的来源路径（如 landed_titles/{titleId}/history/{date}）。
    sourcePath: Optional[str] = None


class TitleStructure(BaseModel):
    """单条头衔的结构化信息（Phase 3C.7 P1 reader 字段的契约形态）。

    全部新增字段带安全默认值，旧 fixture/旧缓存（缺字段）仍可构造。
    """
    titleId: str
    name: str
    tier: Optional[TitleTier] = None
    # capital：title 顶层 capital= 字段（primary identity 候选/政权中心）。
    capitalTitleId: Optional[str] = None
    capitalSourcePath: Optional[str] = None
    capitalResolved: bool = False
    # 法理层级（de jure，与 de facto liege 分开）。
    deJureLiegeId: Optional[str] = None
    deJureVassalIds: List[str] = Field(default_factory=list)
    # 仅拥宣称者（claimants，与人物实际持有分开）。
    claimantIds: List[str] = Field(default_factory=list)
    # 政体历史（保留但不生成复杂传记文案）：[(date, government)]。
    historyGovernment: List[dict] = Field(default_factory=list)
    currentHolderId: Optional[str] = None
    history: List[TitleHistoryRecord] = Field(default_factory=list)


class CharacterDomain(BaseModel):
    """人物侧当前直接控制领地（landed_data.domain）。

    与 title 顶层 holder 反查互相校验：不一致时产生 warning 并降低 confidence，
    不得静默选择其中一边（Phase 3C.7 P1）。
    """
    titleIds: List[str] = Field(default_factory=list)
    sourcePath: Optional[str] = None
    # 与 title holder 反查结果：consistent（全部一致）/ mismatch（存在不一致）/
    # unresolved（无法反查，如 title 索引不可用）。
    holderCrossCheck: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class PlayerHistoryMarker(BaseModel):
    """历史玩家标记（Phase 3C.7 P1，playable_data.was_player=yes）。

    除 meta.player_id（当前玩家）外，保留全部曾被玩家控制的人物历史标记；
    isCurrentPlayer 由 meta.player_id 匹配决定。
    """
    wasPlayer: bool = False
    isCurrentPlayer: bool = False


class CharacterIdentity(BaseModel):
    """人物主要身份（Phase 3C.2 PrimaryIdentityResolver 确定性产出）。

    headlineIdentity 是人物页标题下的主要身份表述（基于头衔**语义**与
    **游戏原生展示名**，绝不按 tier 硬编码为男爵/伯爵/公爵/国王/皇帝）。
    realmStatus 由现任头衔结构判定；无法判定时 unknown（诚实留空）。
    """
    headlineIdentity: str
    realmStatus: RealmStatus
    primaryRealmTitle: Optional[EntityRef] = None
    primaryOffice: Optional[EntityRef] = None
    # 主身份头衔是否为霸权（h_* 超帝国）头衔；True 时前端展示「霸权」标识。
    isHegemony: bool = False
    # 次要看点（如多主权领地的其余领地、兼任的机构等），均为确定性文案。
    secondaryIdentities: List[str] = Field(default_factory=list)
    confidence: Confidence
    warnings: List[str] = Field(default_factory=list)
    evidence: List[EvidenceRef] = Field(default_factory=list)


class HistoricalSemanticEvent(BaseModel):
    """历史语义事件（Phase 3C.3 HistoricalEventSemanticBuilder 产出）。

    把 title_gain/loss 等原始记录按语义类型重组（同日多地获得→territorial_gain、
    同日多官→office_appointment 等分开），供时间线聚合与 LLM 输入。
    sourceEventIds 指向原始 TimelineEvent.id 以便追溯。
    """
    eventId: str
    semanticType: HistoricalSemanticEventType
    date: Optional[str] = None
    summary: str
    relatedTitleIds: List[str] = Field(default_factory=list)
    relatedEntityIds: List[str] = Field(default_factory=list)
    confidence: Confidence
    evidence: List[EvidenceRef] = Field(default_factory=list)
    sourceEventIds: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    # 叙事约束（如「存档未记录获得途径，不得推断继承/征服/册封」）。
    narrativeConstraints: List[str] = Field(default_factory=list)
    acquisitionCause: Optional[AcquisitionCause] = None
    # 3C-Audit：存档 history 条目显式记录的原始 type 字符串（conquest/granted/…；
    # 无显式 type 为 None）。绝不丢弃原始字符串，绝不把默认值当存档事实。
    acquisitionRawType: Optional[str] = None
    # 获得原因的证据来源（save_explicit / reader_default / unknown）。
    acquisitionTypeSource: Optional[AcquisitionTypeSource] = None
    # 3C.7：TitleHistoryActionNormalizer 产出的规范化动作（如 conquered /
    # administrative_succession / unknown）。与 acquisitionRawType 并存：
    # rawType 是存档原始字符串，normalizedAction 是统一语义（分组/文案/校验用）。
    normalizedAction: Optional[TitleHistoryActionKind] = None


class FactRef(BaseModel):
    """一条可独立核验的事实（Phase 3C.5）。

    事实由确定性代码从存档证据提炼（不是模型产出）：含置信度与证据引用链。
    BiographyChapter.factIds 引用这些事实 id；FactChecker 校验正文与事实一致。
    """
    id: str
    text: str
    confidence: Confidence
    evidenceRefIds: List[str] = Field(default_factory=list)
    sourceEventIds: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 标准人物档案（原始数据层）
# ---------------------------------------------------------------------------

class CharacterProfile(BaseModel):
    id: str
    name: str
    # 2C.1：绰号（如 nick_the_peaceful→「仁」）。未解析时如实为空。
    nickname: Optional[EntityRef] = None
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
    # 2C.1：君主（仅 dead_data 子块实测存在，卒年记录其君主）；无则 None。
    liege: Optional[CharacterRef] = None
    # 2C.1：血缘远近 + 姻亲（祖辈/叔伯姑舅/堂表亲/侄甥/姻亲），均推断并如实标注。
    relatives: List[CharacterRef] = Field(default_factory=list)

    friends: List[CharacterRef] = Field(default_factory=list)
    rivals: List[CharacterRef] = Field(default_factory=list)
    lovers: List[CharacterRef] = Field(default_factory=list)

    wars: List[WarParticipation] = Field(default_factory=list)
    imprisonments: List[LifeEvent] = Field(default_factory=list)
    travels: List[LifeEvent] = Field(default_factory=list)
    memories: List[LifeEvent] = Field(default_factory=list)

    # ---- Phase 3C：历史语义层（由确定性规则产出，不涉及 LLM）----
    # 头衔语义分类（titleId -> 分类；仅包含该人物出现过的头衔）。
    titleClassifications: Dict[str, TitleClassification] = Field(default_factory=dict)
    # 主要身份（headline / realmStatus / primaryRealmTitle …）。
    identity: Optional[CharacterIdentity] = None
    # 现任个人官职 / 政权机构 / 宗教职务 / 荣誉 / 宣称（按语义分类聚合，均带显示名）。
    personalOffices: List[EntityRef] = Field(default_factory=list)
    realmInstitutions: List[EntityRef] = Field(default_factory=list)
    religiousOffices: List[EntityRef] = Field(default_factory=list)
    honors: List[EntityRef] = Field(default_factory=list)
    claims: List[EntityRef] = Field(default_factory=list)
    # 现任主要领地（主权/领地王国以上）与从属领地（伯/男爵领）。
    majorTerritories: List[EntityRef] = Field(default_factory=list)
    subordinateTerritories: List[EntityRef] = Field(default_factory=list)
    # 历史语义事件（同日大量 title 变更按语义类型拆分；不推断因果）。
    historicalEvents: List[HistoricalSemanticEvent] = Field(default_factory=list)

    # ---- Phase 3C.7 P1：玩家历史标记 + 直控领地（安全默认值，缺字段旧 fixture 可兼容）----
    # playable_data.was_player 历史标记；isCurrentPlayer 由 meta.player_id 匹配。
    playerHistory: Optional[PlayerHistoryMarker] = None
    # landed_data.domain 直控领地 + 与 title holder 反查互相校验结果。
    domain: Optional[CharacterDomain] = None

    timeline: List[TimelineEvent] = Field(default_factory=list)
    evidenceWarnings: List[EvidenceWarning] = Field(default_factory=list)


class CharacterSummary(BaseModel):
    """人物列表摘要（用于人物选择页），由完整档案按需派生。

    只保留卡片/列表渲染所需的轻量字段，避免大型存档一次性生成全部
    完整 CharacterProfile。完整档案通过 ParsedSave.profiles 按需获取。
    """
    id: str
    name: str
    # 2C.1：绰号（如 nick_the_peaceful→「仁」）。未解析时如实为空。
    nickname: Optional[EntityRef] = None
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
    # P0：主头衔判定状态（resolved / no_titles / tier_unknown / index_unavailable）。
    # 与 CharacterProfile.titles 同源（都由 TitleProfileIndex.primary_bits 反解），
    # 前端据此区分「确认无头衔 / 未能确定 / 索引不可用」，不误显示为无头衔。
    titleStatus: Optional[TitleStatus] = None
    isAlive: bool = True
    isPlayerDynasty: bool = False
    portraitKey: Optional[str] = None
    evidenceWarningCount: int = 0
    # ---- Phase 3C：身份摘要（PrimaryIdentityResolver 确定性产出；无法判定时留空）----
    headlineIdentity: Optional[str] = None
    realmStatus: Optional[RealmStatus] = None


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
    # 3C.5：本章正文所依赖的事实 id（确定性回填：由本章 eventIds 对应事件所锚定的事实推导）。
    factIds: List[str] = Field(default_factory=list)
    # 3C.5：本章正文中的确定性主张（由模型依据事实撰写，经 FactChecker 校验）。
    claims: List[str] = Field(default_factory=list)

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
    # 3C.5：全文所用的事实集（确定性提炼，供 factIds 与校验追溯）。
    facts: List[FactRef] = Field(default_factory=list)


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
# 实体索引（M2：存档内全部实体类别的轻量索引 + 引用解析）
# ---------------------------------------------------------------------------

class EntityIndexEntry(BaseModel):
    """单条实体索引条目（合并 Rust entities.json 原始内部键 + Python 解析出的可读名）。

    诚实性原则：resolved=False 时 name 就是原始 id（id 字段值），不得伪造。
    """
    id: str
    key: Optional[str] = None
    # 内部键性质；缺省即 "loc"。
    keyKind: Optional[EntityKeyKind] = None
    # 家族前缀（仅 house）。
    prefix: Optional[str] = None
    # 上级实体 id：house→dynasty、faith→religion。
    parent: Optional[str] = None
    # 存档成品名（玩家自定义头衔/混合文化/战争名），免查 loc。
    saveName: Optional[str] = None
    # 战争开始日期（存档直述）。
    startDate: Optional[str] = None
    # 解析后的可读名；resolved=False 时为原始 id。
    name: str
    # 名称来源，用于溯源与 UI 标注。
    nameSource: EntityNameSource
    # resolved=False 表示该实体无法命名，name 退化为原始 id。
    resolved: bool = True


class EntityKindIndex(BaseModel):
    """单类别实体索引。"""
    kind: EntityKind
    # 证据来源路径（存档内容器路径）。
    source: str
    # 容器是否在本存档里找到。
    containerFound: bool = True
    count: int = 0
    # 既无内部键也无成品名的条目数——必须标 resolved=False。
    unresolvedCount: int = 0
    # id -> 条目。
    entries: Dict[str, EntityIndexEntry] = Field(default_factory=dict)


class EntityIndex(BaseModel):
    """存档的完整实体索引（M2 产出，由后端 /saves/:saveId/entities 暴露）。"""
    schemaVersion: int = 1
    readerVersion: str = ""
    scanMs: float = 0.0
    kinds: Dict[EntityKind, EntityKindIndex] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Token 来源自报（M2.2：解析所用令牌表的来源与兼容性状态）
# ---------------------------------------------------------------------------

class TokenSourceInfo(BaseModel):
    """令牌表来源自报。写入 meta.json 并由 API 暴露。

    注意：unknown_token_count=0 绝不意味着"全部已本地化"——
    占位表即可让 unknown_token_count=0 却仍把 enum 显示为数字。
    """
    kind: TokenSourceKind
    path: Optional[str] = None
    tokenCount: Optional[int] = None
    compatibility: TokenCompatibility
    # enum 字段（faith/dynasty/culture 等）是否已翻译为可读名。
    enumResolved: bool = False
    warnings: List[str] = Field(default_factory=list)


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
