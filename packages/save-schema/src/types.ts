/**
 * SHIGUAN — 标准化人物数据契约（canonical data contract）
 *
 * 这些类型描述了"存档解析 + 索引"阶段产出的标准人物档案与时间线。
 * 它们被传记引擎与 Web 前端共同消费。
 *
 * 设计铁律（来自产品规范第十、十一条）：
 *  - 严格分离"原始数据层"（存档里真实存在的东西）与"传记展示层"
 *    （模型生成的东西）。本文件描述前者（Profile / Timeline），后者
 *    的轮廓与正文引用本文件中的事件 ID。
 *  - 每一条进入时间线的信息都必须带有 `confidence`：
 *      confirmed  —— 存档中明确存在的事实
 *      inferred   —— 由数据合理推断，但存档未直接陈述
 *      uncertain  —— 无法确定的事项，必须在 UI 中标红/提示
 *  - 任何 `sourcePath` 都是为了让"史料依据"面板能回溯到存档原始位置，
 *    不得空缺到无法追溯的程度（至少标注数据来源类别）。
 *
 * 本文件是前后端共享的唯一事实来源（single source of truth）。
 * 修改字段前请同步更新 packages/save-schema/py/models.py 与
 * docs/architecture.md 中的模型说明。
 */

// ----------------------------------------------------------------------------
// 基础枚举与值对象
// ----------------------------------------------------------------------------

/** 证据置信度：确认 / 推断 / 不确定。传记中不得把推断写成确定事实。 */
export type Confidence = "confirmed" | "inferred" | "uncertain";

export type Sex = "male" | "female" | "other";

/** CK3 头衔等级（由低到高）。 */
export type TitleTier =
  | "barony"
  | "county"
  | "duchy"
  | "kingdom"
  | "empire";

/** 时间线事件类型。可按真实存档结构扩展，但不要随意新增语义模糊的类型。 */
export type EventType =
  | "birth"
  | "death"
  | "marriage"
  | "divorce"
  | "child_birth"
  | "succession"
  | "title_gain"
  | "title_loss"
  | "war"
  | "imprisonment"
  | "exile"
  | "travel"
  | "court_position"
  | "conversion"
  | "trait_gain"
  | "success"
  | "failure"
  | "other";

/** 对任意游戏内实体（头衔 / 郡 / 文化 / 信仰 / 王朝 / 家族）的轻量引用。 */
export interface EntityRef {
  id: string;
  name: string;
  /** 实体类别，如 "title" | "county" | "culture" | "faith" | "dynasty" | "house"。 */
  type?: string;
  /** 在解析后存档数据中的来源路径，用于史料溯源。 */
  sourcePath?: string;
  /** resolved=false 表示该引用当前只能以原始 id / 键表示（占位 token 表下 enum 字段为数字/token-id，或本地化未命中），未伪造可读名。 */
  resolved?: boolean;
}

/** 对人物的轻量引用，用于关系网与列表，避免嵌套整份档案。 */
export interface CharacterRef {
  id: string;
  name: string;
  sex?: Sex;
  birthDate?: string;
  deathDate?: string;
  dynasty?: EntityRef;
  /** 该人物的最高级别（或主要）头衔，用于卡片摘要。 */
  primaryTitle?: EntityRef;
  /** 该引用在存档中的来源路径（如 character/1/child/2），用于史料依据面板回溯。 */
  sourcePath?: string;
  /**
   * 姓名是否已解析为可读姓名（M5.1）。
   * - true：已从人物索引 / 本地化数据得到可读姓名，可安全用于自然语言展示。
   * - false / 缺省：仅保留原始人物 id 或内部 key，不得当作真实姓名写入 LLM 摘要。
   * 注意：与关系事实的 confidence 是两回事（父母可能是 child_backref 推断，但名字仍可解析）。
   */
  resolved?: boolean;
}

// ----------------------------------------------------------------------------
// 个人属性与履历片段
// ----------------------------------------------------------------------------

export interface TraitRecord {
  id: string;
  name: string;
  /** 如 "personality" | "health" | "education" | "congenital" 等，可为空。 */
  category?: string;
  sourcePath?: string;
}

/** 一段持有头衔的经历。合并连续任期后形成。 */
export interface TitlePeriod {
  titleId: string;
  name: string;
  tier?: TitleTier;
  /** 获得头衔的日期（YYYY.MM.DD 或 YYYY）。 */
  start?: string;
  /** 失去头衔的日期；缺失表示截至存档时仍持有。 */
  end?: string;
  isCurrent?: boolean;
  /** 政体类型（如 feudal / clan / tribal），可选。 */
  government?: string;
  sourcePath?: string;
}

/** 一段居住/驻留经历。地点能否定位直接决定 confidence。 */
export interface ResidencePeriod {
  locationId: string;
  name: string;
  start?: string;
  end?: string;
  /**
   * 居住地点往往只能由"首府 / 主要领地"推断，因此默认多为 inferred。
   * 仅当存档明确记录 residence 时才可为 confirmed。
   */
  confidence: Confidence;
  sourcePath?: string;
}

/** 一段宫廷任职经历（如大臣、顾问、宫廷职位）。 */
export interface PositionPeriod {
  /** 任职的宫廷 / 君主。 */
  courtId?: string;
  courtName?: string;
  positionId: string;
  name: string;
  start?: string;
  end?: string;
  /** 雇主人物 id，可选。 */
  employerId?: string;
  sourcePath?: string;
}

/**
 * 一段关系经历（配偶 / 情人 / 宿敌等）。
 * 用时间段表达，支持多次婚姻、离婚等复杂情况。
 */
export interface RelationshipPeriod {
  characterId: string;
  name: string;
  /** 含 M4 新增：betrothed（婚约）、concubine（妾室）。 */
  type: "spouse" | "lover" | "friend" | "rival" | "murderer" | "betrothed" | "concubine" | "other";
  start?: string;
  end?: string;
  /** 关系是否由数据确认；如仅能从子女反推则为 inferred。 */
  confidence: Confidence;
  sourcePath?: string;
  /** M4：存档直述的"前任"关系（former_spouses / former_concubines），与现任区分。 */
  isFormer?: boolean;
}

/** 战争参与记录。 */
export interface WarParticipation {
  warId: string;
  name: string;
  /** 主人物在此战中的角色：attacker / defender / participant / other。 */
  role: "attacker" | "defender" | "participant" | "other";
  /** 参战方标识，用于判断"谁发动了战争"。 */
  side?: string;
  start?: string;
  end?: string;
  outcome?: string;
  sourcePath?: string;
}

/**
 * 通用人生事件（囚禁、流亡、旅行、记忆等）。
 * 与 TimelineEvent 的区别：LifeEvent 是"原始抓取"，TimelineEvent 是
 * "经过排序/合并/压缩、准备喂给模型"的事件。
 */
export interface LifeEvent {
  id: string;
  type: EventType;
  date?: string;
  description: string;
  relatedCharacters?: CharacterRef[];
  location?: EntityRef;
  confidence: Confidence;
  sourcePath?: string;
}

// ----------------------------------------------------------------------------
// 时间线（传记的事实基底）
// ----------------------------------------------------------------------------

/**
 * 一条可溯源的证据引用。
 * 用于把 TimelineEvent 关联到存档中的具体出处（而非复制整段原始存档文本）。
 * confirmed 事件必须能追到具体证据；inferred 事件需记录推断依据。
 */
export interface EvidenceRef {
  id: string;
  /** 证据来源类别，如 "save_block" | "localization" | "memory" | "war" | "title"。 */
  sourceType: string;
  /** 在解析后存档数据中的来源路径，用于"史料依据"面板回溯。 */
  sourcePath?: string;
  /** 存档中的原始 key（如本地化 key、Clausewitz 对象键），便于精确溯源。 */
  rawKey?: string;
  /** 该证据说明了什么。 */
  description: string;
  confidence: Confidence;
  /** 关联的时间线事件 id（若此证据本身对应某个事件）。 */
  relatedEventId?: string;
}

/**
 * 统一的人生时间线事件。所有进入传记的事实都必须先成为 TimelineEvent。
 * `confidence` 决定它在 UI 中如何呈现，以及模型是否可将其当作确定事实。
 */
export interface TimelineEvent {
  id: string;
  date?: string;
  endDate?: string;
  type: EventType;
  title: string;
  description: string;
  location?: EntityRef;
  relatedCharacters?: CharacterRef[];
  relatedTitles?: EntityRef[];
  /** 在解析后存档数据中的来源路径，用于"史料依据"面板。 */
  sourcePath?: string;
  confidence: Confidence;
  /** 可溯源的证据引用集合（至少能关联一条 EvidenceRef）。 */
  evidence: EvidenceRef[];
  /** M5：该事件由 N 条重复存档记录合并而成（>1 表示已去重合并；缺省/1 = 单条记录）。 */
  mergedCount?: number;
}

// ----------------------------------------------------------------------------
// 证据与告警模型
// ----------------------------------------------------------------------------

export type WarningSeverity = "info" | "warning" | "error";

/**
 * 证据告警：当某一字段无法从存档确认、或存在潜在矛盾时出现。
 * 例如"无法定位死亡地点""父母死亡早于子女出生"等。
 */
export interface EvidenceWarning {
  code: string;
  message: string;
  severity: WarningSeverity;
  /** 关联的时间线事件 id（若有）。 */
  relatedEventId?: string;
  sourcePath?: string;
}

// ----------------------------------------------------------------------------
// 标准人物档案（原始数据层）
// ----------------------------------------------------------------------------

/**
 * 标准人物档案。这是"原始数据层"的核心产出，由存档解析 + 索引构建。
 * 字段可根据真实存档结构微调，但须始终保持原始数据与传记展示层分离。
 */
export interface CharacterProfile {
  id: string;
  name: string;
  sex?: Sex;
  birthDate?: string;
  deathDate?: string;
  deathReason?: string;

  dynasty?: EntityRef;
  house?: EntityRef;
  culture?: EntityRef;
  faith?: EntityRef;

  traits: TraitRecord[];
  titles: TitlePeriod[];
  residences: ResidencePeriod[];
  courtPositions: PositionPeriod[];

  parents: CharacterRef[];
  spouses: RelationshipPeriod[];
  children: CharacterRef[];
  siblings: CharacterRef[];

  friends: CharacterRef[];
  rivals: CharacterRef[];
  lovers: CharacterRef[];

  wars: WarParticipation[];
  imprisonments: LifeEvent[];
  travels: LifeEvent[];
  memories: LifeEvent[];

  /** 经过排序/合并/压缩、准备呈现与喂给模型的时间线。 */
  timeline: TimelineEvent[];
  /** 证据层面的告警与不确定项。 */
  evidenceWarnings: EvidenceWarning[];
}

/**
 * 人物列表摘要（用于人物选择页），由完整档案按需派生。
 * 只保留卡片/列表渲染所需的轻量字段，避免大型存档一次性生成全部完整档案。
 * 完整档案通过 ParsedSave.profiles 按 id 按需获取。
 */
export interface CharacterSummary {
  id: string;
  name: string;
  sex?: Sex;
  birthDate?: string;
  deathDate?: string;
  dynasty?: EntityRef;
  house?: EntityRef;
  culture?: EntityRef;
  faith?: EntityRef;
  primaryTitle?: EntityRef;
  highestTitleTier?: TitleTier;
  isRuler: boolean;
  isAlive: boolean;
  isPlayerDynasty: boolean;
  portraitKey?: string;
  evidenceWarningCount: number;
}

/** 索引条目与摘要同形。 */
export type CharacterIndexEntry = CharacterSummary;

// ----------------------------------------------------------------------------
// 传记展示层（模型生成，引用上面的事件 ID）
// ----------------------------------------------------------------------------

/** 提纲章节：每一节必须引用至少一个 TimelineEvent.id。 */
export interface BiographyChapterOutline {
  id: string;
  title: string;
  /** 本章所依据的时间线事件 id 列表，不得为空。 */
  eventIds: string[];
  /** 该阶段的叙事摘要（由模型给出，非存档数据）。 */
  summary: string;
}

/** 传记提纲（第一次模型调用的产出）。 */
export interface BiographyOutline {
  profileId: string;
  style: BiographyStyle;
  chapters: BiographyChapterOutline[];
}

/** 正文章节（第二次模型调用的产出）。 */
export interface BiographyChapter {
  id: string;
  title: string;
  content: string;
  /** 本章正文所追溯的时间线事件 id。 */
  eventIds: string[];
}

export type BiographyStyle =
  | "vernacular_annals" // 白话纪传体（默认）
  | "serious_biography" // 严肃历史传记
  | "medieval_chronicle" // 中世纪编年史
  | "family_memoir" // 家族回忆录
  | "concise_profile" // 简洁人物小传
  | "cold_historian"; // 带少量冷峻评价的史家笔法

/** 单条事实校验问题。 */
export interface FactCheckIssue {
  rule: string;
  severity: WarningSeverity;
  message: string;
  /** 建议的修正方向（交给模型二次生成时使用）。 */
  suggestedFix?: string;
}

export interface FactCheckResult {
  status: "pass" | "needs_revision";
  issues: FactCheckIssue[];
}

/** 完整传记产物。 */
export interface Biography {
  profileId: string;
  style: BiographyStyle;
  chapters: BiographyChapter[];
  generatedAt: string;
  modelName: string;
  /** 事实校验结果（第八步）。 */
  factCheck?: FactCheckResult;
  /** 任一时点使用的压缩后档案指纹，便于复现。 */
  profileDigest?: string;
}

// ----------------------------------------------------------------------------
// 存档解析层（适配器协议与产出）
// ----------------------------------------------------------------------------

export type SaveKind =
  | "text" // 调试明文存档（.ck3 解压后的 gamestate，或纯文本存档）
  | "text_zip" // 标准 .ck3：明文头 + zip 压缩明文 gamestate
  | "binary_zip" // 二进制 .ck3：二进制头 + zip 压缩二进制 gamestate
  | "binary" // 自动存档的未压缩二进制 gamestate
  | "ironman"; // 铁人存档（二进制 + 需要令牌表才能解码）

/** 文本编码（CK3 使用 UTF-8，与 EU4 的 Windows-1252 不同）。 */
export type Encoding = "utf-8" | "windows-1252" | "unknown";

/** 缺失的外部解析组件（如 Rakaly CLI）及其安装提示。 */
export interface MissingComponent {
  name: string;
  hint: string;
}

/** 文件初检结果。由 SaveParserAdapter.inspect() 产出，绝不解析内容本身。 */
export interface SaveInspection {
  path: string;
  kind: SaveKind;
  /** 编码：CK3 使用 UTF-8（与 EU4 的 Windows-1252 不同）。 */
  encoding: Encoding;
  sizeBytes: number;
  isCompressed: boolean;
  isIronman: boolean;
  /** 是否可不依赖外部组件、在本地直接解析。 */
  canParseLocally: boolean;
  /** 是否需要外部解析器（如 Rakaly CLI）。 */
  needsExternal: boolean;
  /** 缺失的外部组件名称与安装提示（若有）。 */
  missingComponent?: MissingComponent;
}

/** 解析后存档的元信息。 */
export interface ParsedSaveMeta {
  saveVersion?: string;
  gameVersion?: string;
  date?: string;
  playerId?: string;
  campaignId?: string;
}

/** 解析后的存档索引与人物档案。 */
export interface ParsedSave {
  meta: ParsedSaveMeta;
  /**
   * 人物摘要索引（轻量，用于选择页）。与 profiles 分离，
   * 避免大型存档一次性生成全部完整 CharacterProfile。
   */
  characterIndex: CharacterIndexEntry[];
  /** 按需完整档案，按人物 id 取用。 */
  profiles: Record<string, CharacterProfile>;
  dynasties: Record<string, EntityRef>;
  houses: Record<string, EntityRef>;
  titles: Record<string, EntityRef>;
  counties: Record<string, EntityRef>;
  cultures: Record<string, EntityRef>;
  faiths: Record<string, EntityRef>;
  relationships: Record<string, RelationshipPeriod[]>;
  wars: Record<string, WarParticipation>;
  memories: LifeEvent[];
  /** 本地化文本表：key -> 可读名称。 */
  localization: Record<string, string>;
}

// ----------------------------------------------------------------------------
// 实体索引（M2：存档内全部实体类别的轻量索引 + 引用解析）
// ----------------------------------------------------------------------------

/** 实体类别，共 10 类，与 Rust scan_entities 的 EKind 一一对应。 */
export type EntityKind =
  | "trait"
  | "faith"
  | "religion"
  | "culture"
  | "house"
  | "dynasty"
  | "title"
  | "war"
  | "memoryType"
  | "courtPositionType";

/** 内部键性质：缺省（未标注）即 "loc"，可直接查本地化；"def" 需先查游戏定义库。 */
export type EntityKeyKind = "loc" | "def";

/** 实体最终可读名的来源，用于可追溯与诚实性标注。 */
export type EntityNameSource =
  | "save" // 存档成品名（玩家自定义头衔/混合文化/战争名），免查 loc
  | "game_def" // 游戏定义文件（game/common）反查得到的本地化键
  | "loc" // 本地化表命中
  | "literal" // 明文存档，字段名本身即可读 key
  | "unresolved"; // 无法命名：name 退化为原始 id，绝不为其编造可读名

/**
 * 单条实体索引条目（合并 Rust entities.json 的原始内部键 + Python 侧解析出的可读名）。
 * 诚实性原则：resolved=false 时 name 就是原始 id，不得伪造。
 */
export interface EntityIndexEntry {
  /** 实体 id（即存档容器内 map 的 key）。 */
  id: string;
  /** 存档自述的内部键（存档容器的 id→key，用于溯源）。 */
  key?: string;
  /** 内部键性质；缺省即 "loc"。 */
  keyKind?: EntityKeyKind;
  /** 家族前缀（仅 house）。 */
  prefix?: string;
  /** 上级实体 id：house→dynasty、faith→religion。 */
  parent?: string;
  /** 存档成品名（玩家自定义头衔/混合文化/战争名），免查 loc。 */
  saveName?: string;
  /** 战争开始日期（存档直述）。 */
  startDate?: string;
  /** 解析后的可读名；resolved=false 时为原始 id。 */
  name: string;
  /** 名称来源，用于溯源与 UI 标注。 */
  nameSource: EntityNameSource;
  /** resolved=false 表示该实体当前无法命名，name 退化为原始 id。 */
  resolved: boolean;
}

/** 单类别实体索引。 */
export interface EntityKindIndex {
  kind: EntityKind;
  /** 证据来源路径（存档内容器路径）。 */
  source: string;
  /** 容器是否在本存档里找到。false 时 entries 为空且会有 warning。 */
  containerFound: boolean;
  count: number;
  /** 既无内部键也无成品名的条目数——必须标 resolved=false。 */
  unresolvedCount: number;
  /** id -> 条目。 */
  entries: Record<string, EntityIndexEntry>;
}

/** 存档的完整实体索引（M2 产出，由后端 /saves/:saveId/entities 暴露）。 */
export interface EntityIndex {
  schemaVersion: number;
  readerVersion: string;
  scanMs: number;
  kinds: Partial<Record<EntityKind, EntityKindIndex>>;
  warnings: string[];
}

// ----------------------------------------------------------------------------
// Token 来源自报（M2.2：解析所用令牌表的来源与兼容性状态）
// ----------------------------------------------------------------------------

/** 当前解析所用的令牌表来源。 */
export type TokenSourceKind =
  | "placeholder" // 占位全量 token 表（id→tXXXX），enum 字段保持数字/token-id
  | "builtin_validated" // 内置校验过的真实字段名映射
  | "user_local" // 用户自备真实令牌表（RAKALY_IRONMAN_TOKENS_PATH）
  | "literal_key"; // 明文存档，字段名即可读 key，无需 token 表

/** 令牌表兼容性状态。 */
export type TokenCompatibility =
  | "ok" // 全量命中，enum 字段可翻译
  | "partial" // 部分枚举可翻译，其余保持数字（如仅有字段名表无 enum 表）
  | "incompatible" // 版本不匹配，存在未知 token
  | "external_missing"; // 需外部令牌表但缺失

/**
 * 令牌表来源自报。写入 meta.json，并由 API 暴露，
 * 让前端明确"当前显示的名称为何可能是数字/未翻译"。
 * 注意：unknown_token_count=0 绝不意味着"全部已本地化"——
 * 占位表即可让 unknown_token_count=0 却仍把 enum 显示为数字。
 */
export interface TokenSourceInfo {
  kind: TokenSourceKind;
  /** 当前令牌表路径（若有）。 */
  path?: string;
  /** 表规模（条目数）。 */
  tokenCount?: number;
  compatibility: TokenCompatibility;
  /** enum 字段（faith/dynasty/culture 等）是否已翻译为可读名。 */
  enumResolved: boolean;
  /** 告警（未知 token / 版本漂移 / 缺失组件等）。 */
  warnings: string[];
}

// ----------------------------------------------------------------------------
// Mock / 测试数据包裹层
// ----------------------------------------------------------------------------

/** FixtureEnvelope 的默认 data 载体：一组 Mock 人物摘要与按需档案。 */
export interface MockDataset {
  characterIndex: CharacterIndexEntry[];
  profiles: Record<string, CharacterProfile>;
  /** 其余索引数据（dynasties/houses/...）按需扩展。 */
  extra?: Record<string, unknown>;
}

/**
 * 索引包的 data 载体（Phase 1B 起用于真正的"按需加载"）。
 * 只携带轻量摘要与档案定位符（profileIds），**不**内联完整 CharacterProfile，
 * 避免大型存档初始化时一次性把所有完整档案打进 bundle。
 */
export interface MockIndexPayload {
  meta: ParsedSaveMeta;
  characterIndex: CharacterIndexEntry[];
  /** 可选完整档案的文件定位符（与 profiles/<id>.json 对应）。 */
  profileIds: string[];
}

/** 索引包类型：FixtureEnvelope<MockIndexPayload>。 */
export type MockIndex = FixtureEnvelope<MockIndexPayload>;

/**
 * Mock / 测试数据的包裹结构。
 * 元数据（isMock / source / schemaVersion / generatedFor）与真实业务模型隔离：
 * 真实 CharacterProfile 等不携带这些字段，避免污染。
 */
export interface FixtureEnvelope<T> {
  isMock: true;
  source: "fixtures/mock";
  schemaVersion: string;
  generatedFor: string;
  data: T;
}
