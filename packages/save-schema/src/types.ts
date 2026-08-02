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
  type: "spouse" | "lover" | "friend" | "rival" | "murderer" | "other";
  start?: string;
  end?: string;
  /** 关系是否由数据确认；如仅能从子女反推则为 inferred。 */
  confidence: Confidence;
  sourcePath?: string;
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

/** 文件初检结果。由 SaveParserAdapter.inspect() 产出，绝不解析内容本身。 */
export interface SaveInspection {
  path: string;
  kind: SaveKind;
  /** 编码：CK3 使用 UTF-8（与 EU4 的 Windows-1252 不同）。 */
  encoding: "utf-8" | "windows-1252" | "unknown";
  sizeBytes: number;
  isCompressed: boolean;
  isIronman: boolean;
  /** 是否可不依赖外部组件、在本地直接解析。 */
  canParseLocally: boolean;
  /** 是否需要外部解析器（如 Rakaly CLI）。 */
  needsExternal: boolean;
  /** 缺失的外部组件名称与安装提示（若有）。 */
  missingComponent?: {
    name: string;
    hint: string;
  };
}

/** 解析后的存档索引。Phase 2 起逐步填充，Phase 0 仅定义形状。 */
export interface ParsedSave {
  meta: {
    saveVersion?: string;
    gameVersion?: string;
    date?: string;
    playerId?: string;
    campaignId?: string;
  };
  characters: Record<string, CharacterProfile>;
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
