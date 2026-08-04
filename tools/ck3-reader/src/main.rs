//! ck3-reader — SHIGUAN 本地 CK3 存档读取 helper（Rust sidecar）。
//!
//! 通过 subprocess 被 FastAPI 调用；向 stdout 输出版本化 JSON。
//!
//! 子命令（Phase 2A.1）：
//!   prepare <save.ck3> <cache-dir> [--with-melted]
//!       一次 melt，把受控索引产物写到 cache-dir（meta/mods/characters.ndjson/
//!       character-offsets/manifest），后续查询全部走缓存，不再重新 melt。
//!   meta <cache-dir>            读取 meta.json（版本/日期/玩家/Mod/计数/Token 指标）。
//!   entities <cache-dir>        读取 entities.json（实体索引：id -> 存档内部键）。
//!   characters <cache-dir> [--offset N] [--limit N] [--query Q]
//!       从 characters.ndjson 分页 + 搜索（不重新 melt）。
//!   character <cache-dir> <id>  从缓存随机读取单人物结构化档案（不重新 melt）。
//!   inspect <save.ck3>          兼容旧路径：编码/版本/日期/玩家/Mod/计数/样本（会 melt）。
//!   list-mods <save.ck3>        仅 Mod descriptor 列表。
//!   list-characters <save.ck3>  兼容旧路径：人物摘要索引（会 melt）。
//!   character-json <save.ck3> <id>  兼容旧路径：单人物结构化摘要（会 melt）。
//!   dump <save.ck3> <out.txt>   把 melt 明文整体写入文件（调试）。
//!
//! 解析设计（经 Spike 实测确定，CK3 1.19.0.6）：
//! - ck3save 检测编码并 melt（二进制→明文）。melt 需要的"token 表"我们提交一份
//!   **占位全量表** `tokens/ck3_tokens.txt`（65536 条 id -> tXXXX，由构建脚本生成，
//!   不依赖游戏安装），确保任何二进制存档都能完整 melt（实测 87MB / 1100 万 token），
//!   未知 key 由 FailedResolveStrategy::Ignore 跳过，不会崩溃。
//! - 解析只依赖 **token id**（稳定），不依赖可读名。FIELD_TOKENS 把关键语义字段
//!   映射到实测反推的 token-id（十六进制，如 t00ee=version）。
//! - 部分字段（father/mother/spouse/child/trait_/female/male/ruler）在 melt 中仍以
//!   **字面字符串键**出现（未 token 化），可直接可靠提取；faith/dynasty 等枚举值
//!   仍为 token-id 数字，需真实 token 表才能转可读名（当前标记 unresolved，不伪造）。

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::env;
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process;
use std::time::Instant;

use ck3save::models::HeaderOwned;
use ck3save::{Ck3File, EnvTokens};
use serde::Serialize;

// ----------------------------------------------------------------------------
// 语义字段 -> token 候选键（[可读名(若有真实 token 表), 占位 id]）。
// 占位 id 来自 tokens/ck3_tokens.txt 的全量映射，解析不依赖游戏安装。
// 这些 id 是针对 CK3 1.19.0.6 反推验证过的；新游戏版本若新增/改 token，
// 未知字段会被 Ignore 跳过（容错），关键字段若漂移需在 FIELD_TOKENS 校准。
// ----------------------------------------------------------------------------
// 每个键都写成 &[真实名, 占位 token]：
// - 用真实令牌表（tokens/ck3_tokens_real.txt）构建时，melt 明文输出可读字段名；
// - 用占位表（tokens/ck3_tokens.txt）构建时，输出 tXXXX。
// 两种构建产物都能被同一套扫描逻辑解析。
const ROOT: &[&str] = &["meta_data", "t3155"];
// 缓存 schema 版本：Python 侧 _cache_valid 要求 meta.json 的 cache_schema_version
// 与之一致。扫描/提取逻辑或 melt 行为变更时递增，强制旧缓存失效重建（防交叉复用）。
const CACHE_SCHEMA_VERSION: &str = "2";
const K_SAVE_VERSION: &[&str] = &["save_game_version", "t058f"];
const K_GAME_VERSION: &[&str] = &["version", "t00ee"];
const K_DATE: &[&str] = &["meta_date", "t3157"];
const K_PLAYER_NAME: &[&str] = &["meta_player_name", "t29e6"];
const K_MODS: &[&str] = &["mods", "t32c1"]; // Mod descriptor 数组容器

/// 人物容器：(真实名, 占位 token, 该容器内人物是否存活)。
/// CK3 把人物拆成三个容器；`dead_prunable` 嵌在顶层 `characters`(t06e3) 之下，
/// 因此容器探测不能假设深度为 0。
const K_CHAR_CONTAINERS: &[(&str, &str, bool)] = &[
    ("living", "t2ce6", true),
    ("dead_unprunable", "t2ce8", false),
    ("dead_prunable", "t2ce7", false),
];

// —— 人物块直接字段（相对容器 depth+2）——
const K_NAME: &[&str] = &["first_name", "t2755"];
const K_BIRTH: &[&str] = &["birth", "t27e9"];
const K_NICKNAME: &[&str] = &["nickname", "t2f68"];
const K_ETHNICITY: &[&str] = &["ethnicity", "t3b12"];
const K_CULTURE: &[&str] = &["culture", "t27f4"];
const K_FAITH: &[&str] = &["faith", "t2f2b"];
const K_DYNASTY_HOUSE: &[&str] = &["dynasty_house", "t2e5e"];
const K_FEMALE: &[&str] = &["female", "t0625"];
const K_SEXUALITY: &[&str] = &["sexuality", "t3334"];
const K_TRAITS: &[&str] = &["traits", "t0648"];

// —— family_data 子块 ——
const K_FAMILY_DATA: &[&str] = &["family_data", "t274f"];
const K_CHILD: &[&str] = &["child", "t2811"];
const K_SPOUSE: &[&str] = &["spouse", "t2810"];
const K_PRIMARY_SPOUSE: &[&str] = &["primary_spouse", "t332f"];
const K_REAL_FATHER: &[&str] = &["real_father", "t2a5b"];
// —— M4：婚姻历史（former_spouses=块列表；betrothed/concubine/concubinist=标量可多行；former_concubinists/former_concubines=块列表）——
const K_FORMER_SPOUSES: &[&str] = &["former_spouses", "t3241"];
const K_BETROTHED: &[&str] = &["betrothed", "t2bb9"];
const K_CONCUBINE: &[&str] = &["concubine", "t2bd3"];
const K_CONCUBINIST: &[&str] = &["concubinist", "t336e"];
const K_FORMER_CONCUBINISTS: &[&str] = &["former_concubinists", "t33a2"];
const K_FORMER_CONCUBINES: &[&str] = &["former_concubines", "t33a3"];

// —— M4：记忆条目内字段（character_memory_manager.database）——
// participants/creation_date/end_date/variables/identity 均可被 token 化（占位表形态），
// 角色名（loser/ruler/new_relation…）在 melt 中多为字面键，无需 token 候选。
const K_PARTICIPANTS: &[&str] = &["participants", "t282a"];
const K_CREATION_DATE: &[&str] = &["creation_date", "t347b"];
const K_END_DATE: &[&str] = &["end_date", "t0cd6"];
const K_VARIABLES: &[&str] = &["variables", "t0555"];
const K_IDENTITY: &[&str] = &["identity", "t00db"];

// —— dead_data 子块（存在即代表已死亡）——
const K_DEAD_DATA: &[&str] = &["dead_data", "t2750"];
const K_DEATH_DATE: &[&str] = &["date", "t06b5"];
const K_DEATH_REASON: &[&str] = &["reason", "t2b64"];
const K_KILLER: &[&str] = &["killer", "t2766"];
// 2C.1：君主（liege）。实测仅见于 dead_data 子块内（卒年记录其君主），真实令牌 10541。
const K_LIEGE: &[&str] = &["liege", "t292d"];

// —— 统治判定 ——
const K_LANDED_DATA: &[&str] = &["landed_data", "t2753"];

// ----------------------------------------------------------------------------
// Phase 2B M2：实体容器 token（真实名 + 占位 id 双候选）
//
// 占位 id 由 tokens/ck3_tokens_real.txt 的 `<十进制 id> <名称>` 反查得到
// （tXXXX 中的 XXXX 是该 id 的十六进制）。全部结构均在真实存档
// autosave.ck3（CK3 1.19.0.6，含 33 个 Mod）上逐条实测确认，
// 结构证据见 docs/entity-index-research.md。
// ----------------------------------------------------------------------------
const K_TRAITS_LOOKUP: &[&str] = &["traits_lookup", "t3561"];
const K_RELIGION_ROOT: &[&str] = &["religion", "t27fc"];
const K_FAITHS: &[&str] = &["faiths", "t2f2c"];
const K_RELIGIONS: &[&str] = &["religions", "t2b29"];
const K_CULTURE_MANAGER: &[&str] = &["culture_manager", "t2f92"];
const K_CULTURES: &[&str] = &["cultures", "t2d0a"];
/// `dynasties` 既是顶层容器，也是它自己的一个子容器（同名同 token）。
const K_DYNASTIES_ROOT: &[&str] = &["dynasties", "t2a35"];
const K_DYNASTY_HOUSES: &[&str] = &["dynasty_house", "t2e5e"];
/// `landed_titles` 同样是顶层容器 + 同名子容器。
const K_LANDED_TITLES_ROOT: &[&str] = &["landed_titles", "t27d6"];
const K_WARS_ROOT: &[&str] = &["wars", "t2b3e"];
const K_ACTIVE_WARS: &[&str] = &["active_wars", "t2b3d"];
const K_MEMORY_MANAGER: &[&str] = &["character_memory_manager", "t3604"];
const K_COURT_POSITIONS: &[&str] = &["court_positions", "t368c"];
const K_DATABASE: &[&str] = &["database", "t05ab"];

// —— 实体条目内字段 ——
const K_FAITH_TYPE: &[&str] = &["faith_type", "t3e50"];
const K_TAG: &[&str] = &["tag", "t27d8"];
const K_RELIGION_TYPE: &[&str] = &["religion_type", "t318b"];
const K_CULTURE_TEMPLATE: &[&str] = &["culture_template", "t2f93"];
const K_ENTITY_NAME: &[&str] = &["name", "t001b"];
/// 游戏内生成的家族/王朝写的是已本地化的成品名（如 localized_name="安条克"），不是 loc 键。
const K_LOCALIZED_NAME: &[&str] = &["localized_name", "t0cd3"];
const K_HOUSE_PREFIX: &[&str] = &["prefix", "t0ccd"];
const K_HOUSE_DYNASTY: &[&str] = &["dynasty", "t280e"];
const K_DEF_KEY: &[&str] = &["key", "t00dc"];
const K_TITLE_NAME_DATA: &[&str] = &["title_name_data", "t3e40"];
const K_CASUS_BELLI: &[&str] = &["casus_belli", "t289a"];
const K_TYPE: &[&str] = &["type", "t00e1"];
const K_WAR_START_DATE: &[&str] = &["start_date", "t0cd5"];
const K_COURT_POSITION_TYPE: &[&str] = &["court_position", "t3688"];

// 已在真实存档上验证过的字段 token 映射（用于 Token 指标）。
// 全部通过 tools/ck3-reader/extract_tokens.py 从本机 ck3.exe 反推的真实令牌表核对，
// 详见 docs/character-field-research.md。
const FIELD_MAPPINGS: &[(&str, &str)] = &[
    ("meta_data", "t3155"),
    ("save_game_version", "t058f"),
    ("version", "t00ee"),
    ("meta_date", "t3157"),
    ("meta_player_name", "t29e6"),
    ("mods", "t32c1"),
    ("living", "t2ce6"),
    ("dead_unprunable", "t2ce8"),
    ("dead_prunable", "t2ce7"),
    ("first_name", "t2755"),
    ("birth", "t27e9"),
    ("ethnicity", "t3b12"),
    ("culture", "t27f4"),
    ("faith", "t2f2b"),
    ("dynasty_house", "t2e5e"),
    ("female", "t0625"),
    ("sexuality", "t3334"),
    ("traits", "t0648"),
    ("family_data", "t274f"),
    ("child", "t2811"),
    ("spouse", "t2810"),
    ("primary_spouse", "t332f"),
    ("real_father", "t2a5b"),
    ("dead_data", "t2750"),
    ("dead_data.date", "t06b5"),
    ("dead_data.reason", "t2b64"),
    ("dead_data.killer", "t2766"),
    ("landed_data", "t2753"),
];

#[allow(dead_code)]
const VALIDATED_VERSION: &str = "1.19.0.6";

#[derive(Serialize)]
struct TokenMetrics {
    token_ids_seen: usize,
    placeholder_tokens_used: usize,
    semantic_fields_mapped: usize,
    unresolved_semantic_fields: Vec<String>,
    version_specific_field_mappings: Vec<FieldMapping>,
}

#[derive(Serialize)]
struct FieldMapping {
    field: String,
    token: String,
    status: String, // "placeholder_name" | "value_numeric" | "value_string_key"
}

/// 令牌表来源自报（M2.2）。
///
/// 关键：unknown_token_count=0 **不**表示已完整本地化——占位全量表即可让
/// unknown_token_count=0，却仍把 enum 字段（faith/dynasty/culture 等）显示为数字 id。
/// `enum_resolved` 才是枚举是否翻译为可读名的真实指标。
#[derive(Serialize)]
struct TokenSourceInfo {
    /// placeholder | builtin_validated | user_local | literal_key
    kind: String,
    /// 当前令牌表路径（若有）。
    path: Option<String>,
    /// 表规模（条目数）。
    token_count: Option<usize>,
    /// ok | partial | incompatible | external_missing
    compatibility: String,
    /// enum 字段（faith/dynasty/culture 等）是否已翻译为可读名。
    enum_resolved: bool,
    warnings: Vec<String>,
}

#[derive(Serialize)]
struct InspectOutput {
    path: String,
    encoding: String,
    save_version: Option<String>,
    game_version: Option<String>,
    date: Option<String>,
    player_name: Option<String>,
    mod_count: usize,
    mods: Vec<String>,
    character_count: usize,
    dead_character_count: usize,
    sample_characters: Vec<CharacterRecord>,
    unknown_token_count: usize,
    header_parse_ok: bool,
    melted_bytes: usize,
    parse_ms: f64,
    token_metrics: TokenMetrics,
    token_source: TokenSourceInfo,
    /// 写缓存的 reader 版本：Python 侧 _cache_valid 要求存在，
    /// 旧版（无此字段）缓存在升级后自动失效重建。
    reader_version: String,
    /// 缓存 schema 版本：Python 侧 _cache_valid 要求与 CACHE_SCHEMA_VERSION 一致，
    /// 防止扫描/提取行为变更后旧缓存被复用。
    cache_schema_version: String,
}

/// 单人物在缓存 / melt 明文中的完整记录（Phase 2B M1 重写）。
///
/// 关键事实（已在真实存档 1.19.0.6 上验证，见 docs/character-field-research.md）：
/// - 人物块**没有** father / mother 字段。亲子关系只能由父母的 `child` 列表反向建索引，
///   因此 `father` / `mother` 属于**推断**（parent_source 记录来源），不是存档直述事实。
/// - `real_father` 只在私生子上出现（本存档 48 例），是存档直述的生父，属**确定**事实。
/// - 存活与否由所在容器决定（living / dead_prunable / dead_unprunable），
///   `dead_data` 子块内的 `date` 才是死亡日期，`arrival_date` 与死亡无关。
/// - faith / culture / dynasty_house / traits 的值是**数字 id**，需要 M2 实体索引才能转可读名，
///   在此之前一律进 evidence_warnings，绝不伪造名称。
#[derive(Serialize, serde::Deserialize, Clone)]
struct CharacterRecord {
    id: String,
    name: Option<String>,
    birth: Option<String>,
    death: Option<String>,
    alive: bool,
    sex: Option<String>,
    culture: Option<String>,
    faith: Option<String>,
    dynasty: Option<String>,
    father: Option<String>,
    mother: Option<String>,
    spouses: Vec<String>,
    children: Vec<String>,
    traits: Vec<String>,
    ruler: bool,
    evidence_warnings: Vec<String>,
    // —— Phase 2B M1 新增（对旧缓存用 serde default 兼容）——
    #[serde(default)]
    nickname: Option<String>,
    #[serde(default)]
    ethnicity: Option<String>,
    #[serde(default)]
    sexuality: Option<String>,
    #[serde(default)]
    real_father: Option<String>,
    #[serde(default)]
    primary_spouse: Option<String>,
    #[serde(default)]
    death_reason: Option<String>,
    #[serde(default)]
    killer: Option<String>,
    /// 死亡容器归属：living / dead_prunable / dead_unprunable。
    #[serde(default)]
    container: Option<String>,
    /// father / mother 的证据来源：`child_backref`（由父母 child 列表反推）
    /// 或 `real_father`（存档直述）。为空表示未确定亲代。
    #[serde(default)]
    parent_source: Option<String>,
    // —— Phase 2B M4 新增：婚姻历史（对旧缓存用 serde default 兼容）——
    #[serde(default)]
    former_spouses: Vec<String>,
    #[serde(default)]
    betrothed: Option<String>,
    /// 可多行出现（一人可有多个妾室），也可能是块列表。
    #[serde(default)]
    concubines: Vec<String>,
    #[serde(default)]
    concubinist: Option<String>,
    #[serde(default)]
    former_concubinists: Vec<String>,
    #[serde(default)]
    former_concubines: Vec<String>,
    // —— Phase 2C.1 新增：君主（仅 dead_data 子块实测存在，卒年记录其君主）——
    #[serde(default)]
    liege: Option<String>,
}

impl CharacterRecord {
    fn new(id: String, container: &str, alive: bool) -> Self {
        CharacterRecord {
            id,
            name: None,
            birth: None,
            death: None,
            alive,
            sex: None,
            culture: None,
            faith: None,
            dynasty: None,
            father: None,
            mother: None,
            spouses: Vec::new(),
            children: Vec::new(),
            traits: Vec::new(),
            ruler: false,
            // 这些字段的值是数字 id，不是可读名 → 明确标记 unresolved，等 M2 实体索引解析。
            evidence_warnings: vec![
                "faith:numeric_id".into(),
                "culture:numeric_id".into(),
                "dynasty_house:numeric_id".into(),
                "traits:numeric_id".into(),
            ],
            nickname: None,
            ethnicity: None,
            sexuality: None,
            real_father: None,
            primary_spouse: None,
            death_reason: None,
            killer: None,
            container: Some(container.to_string()),
            parent_source: None,
            former_spouses: Vec::new(),
            betrothed: None,
            concubines: Vec::new(),
            concubinist: None,
            former_concubinists: Vec::new(),
            former_concubines: Vec::new(),
            liege: None,
        }
    }
}

fn read_save_bytes(path: &Path) -> Result<Vec<u8>, String> {
    fs::read(path).map_err(|e| format!("无法读取存档 {}: {}", path.display(), e))
}

/// 验证 ck3save 能否解析存档头（typed 路径是否可用）。仅作信号，不序列化。
fn try_parse_metadata(data: &[u8]) -> bool {
    if let Ok(file) = Ck3File::from_slice(data)
        && let Ok(meta) = file.parse_metadata()
    {
        return meta
            .deserializer()
            .build::<HeaderOwned, _>(&EnvTokens)
            .is_ok();
    }
    false
}

/// 读取存档头部的 kind（SAV01XX 中 XX 两位十六进制）。
/// 头布局（ck3save SaveHeader）：`SAV` + 2 字节 unknown + 2 hex kind + 8 字节 random + 8 hex meta_len + \n。
/// kind：0=Text（完全明文）、1=Binary、2=UnifiedText（明文 meta + raw-deflate 压缩 gamestate）、
/// 3=UnifiedBinary、4=SplitText、5=SplitBinary。
fn save_kind(data: &[u8]) -> Result<u16, String> {
    if data.len() < 24 {
        return Err("存档头不完整".to_string());
    }
    let kind_hex =
        std::str::from_utf8(&data[5..7]).map_err(|_| "存档头 kind 非 ASCII".to_string())?;
    u16::from_str_radix(kind_hex, 16).map_err(|_| format!("存档头 kind 非法: {kind_hex}"))
}

/// 把 SAV0102 明文存档（kind 2/4：明文 meta + raw-deflate 压缩 gamestate）解压为明文文本。
/// 返回 (完整明文 = 头 + [未压缩 meta 若为 SplitText] + 解压后的 gamestate, 未知 token 数=0)。
fn inflate_text_save(data: &[u8], kind: u16) -> Result<Vec<u8>, String> {
    use std::io::Read;
    // gamestate 关键字在 meta 区之后；从 header_len + meta_len 起找，避开 meta 内同名引用。
    let meta_len = if data.len() >= 23 {
        std::str::from_utf8(&data[15..23])
            .ok()
            .and_then(|s| u64::from_str_radix(s, 16).ok())
            .unwrap_or(0) as usize
    } else {
        0
    };
    let header_len = if data.get(23) == Some(&b'\r') { 25 } else { 24 };
    let search_from = (header_len + meta_len).min(data.len());
    let gs = data[search_from..]
        .windows(b"gamestate".len())
        .position(|w| w == b"gamestate")
        .ok_or_else(|| "明文存档中未找到 gamestate 关键字".to_string())?
        + search_from;
    let blob_start = gs + b"gamestate".len();
    let mut decoder = flate2::read::DeflateDecoder::new(&data[blob_start..]);
    let mut out = Vec::with_capacity(meta_len * 2 + 8);
    decoder
        .read_to_end(&mut out)
        .map_err(|e| format!("明文 gamestate 解压失败: {e}"))?;
    // 头（24 字节：SAV01 + kind + random + meta_len + \n）原样保留，与 melt 产物结构一致。
    let mut full = Vec::with_capacity(header_len + out.len());
    full.extend_from_slice(&data[..header_len]);
    if kind == 4 {
        // SplitText：未压缩 meta 在文件头与 gamestate 之间，需拼回。
        full.extend_from_slice(&data[header_len..gs]);
    }
    full.extend_from_slice(&out);
    Ok(full)
}

/// 把存档规范化为明文 gamestate。返回 (明文, 未知 token 数)。
///
/// SAV0101/0103 二进制（kind 1/3/5）→ melt 转明文（token 表反查字段名）；
/// SAV0102 明文（kind 0/2/4）→ 无需 token 表，直接读取/解压 gamestate 文本，
/// 与 melt 产物结构一致（头 + gamestate），下游 scan_meta / scan_characters_full /
/// scan_entities / scan_titles / scan_memories 原样复用，token_source 走 literal_key 分支。
fn melt_save(data: &[u8]) -> Result<(Vec<u8>, usize), String> {
    let kind = save_kind(data)?;
    if kind == 0 {
        // Text：完全明文，文件内容即“头 + gamestate 文本”。
        return Ok((data.to_vec(), 0));
    }
    if kind == 2 || kind == 4 {
        // UnifiedText / SplitText：明文 meta + raw-deflate 压缩 gamestate。
        let text = inflate_text_save(data, kind)?;
        return Ok((text, 0));
    }
    let file = Ck3File::from_slice(data).map_err(|e| format!("Ck3File::from_slice 失败: {e}"))?;
    let mut zip_sink: Vec<u8> = Vec::new();
    let parsed = file
        .parse(&mut zip_sink)
        .map_err(|e| format!("parse 失败: {e}"))?;
    let binary = parsed
        .as_binary()
        .ok_or_else(|| "存档格式无法识别（非 SAV0101/0103 二进制，也非 SAV0102 明文）".to_string())?;
    let melter = binary.melter();
    let melted = melter
        .melt(&EnvTokens)
        .map_err(|e| format!("melt 失败（可能缺少 token 表）: {e}"))?;
    let unknown = melted.unknown_tokens().len();
    Ok((melted.into_data(), unknown))
}

/// 计算 Token 指标：扫描 melt 明文中的 tXXXX 占位 token。
fn compute_token_metrics(text: &str) -> TokenMetrics {
    let mut seen: HashSet<&str> = HashSet::new();
    let mut total: usize = 0;
    // 扫描形如 tXXXX（X 为十六进制）的 token。
    let bytes = text.as_bytes();
    let mut i = 0;
    while i + 4 < bytes.len() {
        if bytes[i] == b't' {
            let mut ok = true;
            let mut tok = String::from("t");
            for j in 1..5 {
                let c = bytes[i + j];
                if c.is_ascii_hexdigit() {
                    tok.push(c as char);
                } else {
                    ok = false;
                    break;
                }
            }
            if ok && tok.len() == 5 {
                total += 1;
                seen.insert(text[i..i + 5].into());
                i += 5;
                continue;
            }
        }
        i += 1;
    }
    // 枚举值类字段（faith/dynasty）在占位表下仍是数字 id，非可读名。
    let unresolved = vec!["faith".into(), "dynasty".into()];
    let mappings: Vec<FieldMapping> = FIELD_MAPPINGS
        .iter()
        .map(|(field, token)| {
            let status = if *field == "faith" || *field == "dynasty" {
                "value_numeric"
            } else {
                "placeholder_name"
            }
            .to_string();
            FieldMapping {
                field: (*field).to_string(),
                token: (*token).to_string(),
                status,
            }
        })
        .collect();
    TokenMetrics {
        token_ids_seen: seen.len(),
        placeholder_tokens_used: total,
        semantic_fields_mapped: FIELD_MAPPINGS.len(),
        unresolved_semantic_fields: unresolved,
        version_specific_field_mappings: mappings,
    }
}

/// 根据运行时令牌表使用情况自报来源与兼容性（M2.2）。
///
/// 判定依据：
/// - `placeholder_tokens_used > 0`（melt 明文里出现 tXXXX）→ 占位全量 token 表。
/// - 否则看 `CK3_IRONMAN_TOKENS` 环境变量是否设置：
///   - 指向仓库内置真实字段名表 `ck3_tokens_real.txt` → builtin_validated；
///   - 指向其它真实表（用户自备）→ user_local；
///   - 未设置（明文存档，无需 melt）→ literal_key。
///
/// 重要：enum 值（faith/dynasty/culture 等）即便在真实字段名表下仍为数字 id，
/// 故 enum_resolved 仅 literal_key 为 true；unknown_token_count=0 绝不意味着已本地化。
fn detect_token_source(metrics: &TokenMetrics) -> TokenSourceInfo {
    let env_path = std::env::var("CK3_IRONMAN_TOKENS").ok();
    let placeholder = metrics.placeholder_tokens_used > 0;

    let (kind, enum_resolved, compatibility): (&str, bool, &str) = if placeholder {
        ("placeholder", false, "partial")
    } else if let Some(p) = &env_path {
        let is_builtin = Path::new(p)
            .file_name()
            .and_then(|s| s.to_str())
            .map(|n| n == "ck3_tokens_real.txt")
            .unwrap_or(false);
        if is_builtin {
            ("builtin_validated", false, "partial")
        } else {
            ("user_local", false, "partial")
        }
    } else {
        ("literal_key", true, "ok")
    };

    let token_count = env_path.as_ref().and_then(|p| {
        fs::read_to_string(p)
            .ok()
            .map(|s| s.lines().filter(|l| !l.trim().is_empty()).count())
    });

    let mut warnings: Vec<String> = Vec::new();
    if placeholder {
        warnings.push(
            "占位 token 表：enum 字段（faith/dynasty/culture 等）仍为数字 id，未翻译为可读名；unknown_token_count=0 不表示已完整本地化。".into(),
        );
    } else if kind != "literal_key" {
        warnings.push(
            "真实字段名令牌表：字段名已可读，但 enum 值（faith/dynasty 等）仍为数字 id，未做 enum 值映射。".into(),
        );
    }

    TokenSourceInfo {
        kind: kind.to_string(),
        path: env_path,
        token_count,
        compatibility: compatibility.to_string(),
        enum_resolved,
        warnings,
    }
}

/// 从一行中按候选键提取字段值（先尝试带引号字符串，再尝试裸 token/数字/日期）。
///
/// **整词匹配**：trim 后行首键必须与候选全等，不能用子串 find——
/// 否则 `save_game_version=15` 会误命中 `version`（K_GAME_VERSION），
/// 把 game_version 填成存档格式版本 15 而非 "1.19.0.6"（真实存档实测踩坑）。
/// meta_data 顶层字段都是 `key=value` 行，行首整词匹配安全且正确。
fn extract_field(line: &str, keys: &[&str]) -> Option<String> {
    let t = line.trim_start();
    let eq = t.find('=')?;
    let key = &t[..eq];
    if !keys.contains(&key) {
        return None;
    }
    let rest = &t[eq + 1..];
    if let Some(stripped) = rest.strip_prefix('"') {
        return stripped.find('"').map(|e| stripped[..e].to_string());
    }
    let v: String = rest
        .chars()
        .take_while(|c| !c.is_whitespace() && *c != '}' && *c != '{')
        .collect();
    if !v.is_empty() {
        return Some(v);
    }
    None
}

/// 严格按「行首键」提取标量值（`key=value` / `key="value"`）。
///
/// 与 `extract_field` 的区别：`extract_field` 用 `find` 在整行任意位置搜子串，
/// 会把 `meta_date=` 误命中成 `date=`；扫描人物字段必须用这个严格版本。
fn extract_kv(t: &str, keys: &[&str]) -> Option<String> {
    for k in keys {
        if let Some(rest) = t.strip_prefix(k)
            && let Some(v) = rest.strip_prefix('=')
        {
            if v.starts_with('{') {
                return None;
            }
            if let Some(s) = v.strip_prefix('"') {
                return s.find('"').map(|e| s[..e].to_string());
            }
            let val = first_token(v);
            if !val.is_empty() {
                return Some(val);
            }
        }
    }
    None
}

/// 判断一行是否为 `key={`（块开头）。keys 同时接受真实名与占位 token。
fn line_opens_key(t: &str, keys: &[&str]) -> bool {
    keys.iter().any(|k| {
        t.strip_prefix(k)
            .and_then(|r| r.strip_prefix('='))
            .map(|v| v.trim_start().starts_with('{'))
            .unwrap_or(false)
    })
}

/// 判断一行是否为 `key=yes`。
fn line_is_yes(t: &str, keys: &[&str]) -> bool {
    keys.iter().any(|k| {
        t.strip_prefix(k)
            .and_then(|r| r.strip_prefix('='))
            .map(|v| v.starts_with("yes"))
            .unwrap_or(false)
    })
}

fn first_token(s: &str) -> String {
    s.split(|c: char| c.is_whitespace() || c == '{' || c == '}')
        .next()
        .unwrap_or("")
        .to_string()
}

/// 由父母的 `child` 列表反向建立亲子索引。
///
/// CK3 存档的人物块**不存在** father / mother 字段，只有父母侧的 `child` 列表，
/// 因此子女的父母必须反推：遍历每个人的 children，把自己按性别回填到子女的 father/mother。
/// 这是**推断**而非存档直述，统一用 parent_source="child_backref" 标注；
/// 若同时存在存档直述的 `real_father`（私生子），保留 real_father 字段并优先标注。
fn build_parent_index(records: &mut [CharacterRecord]) {
    use std::collections::HashMap;
    let mut pos: HashMap<String, usize> = HashMap::with_capacity(records.len());
    for (i, r) in records.iter().enumerate() {
        pos.insert(r.id.clone(), i);
    }
    // 先收集 (子索引, 亲代 id, 亲代是否为女性)，避免同时可变借用。
    let mut edges: Vec<(usize, String, bool)> = Vec::new();
    for r in records.iter() {
        let is_female = r.sex.as_deref() == Some("female");
        for child in &r.children {
            if let Some(&ci) = pos.get(child) {
                edges.push((ci, r.id.clone(), is_female));
            }
        }
    }
    drop(pos);
    for (ci, parent_id, is_female) in edges {
        let c = &mut records[ci];
        if is_female {
            if c.mother.is_none() {
                c.mother = Some(parent_id);
                c.parent_source = Some("child_backref".into());
            }
        } else if c.father.is_none() {
            c.father = Some(parent_id);
            c.parent_source = Some("child_backref".into());
        }
    }
}

fn quoted_strings(line: &str) -> Vec<String> {
    let mut out = Vec::new();
    let bytes = line.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'"' {
            let start = i + 1;
            let mut j = start;
            while j < bytes.len() && bytes[j] != b'"' {
                j += 1;
            }
            if j < bytes.len() {
                out.push(line[start..j].to_string());
                i = j + 1;
            } else {
                break;
            }
        } else {
            i += 1;
        }
    }
    out
}

/// 扫描元数据：save_version / game_version / date / player_name / mods。
/// scan_meta 返回类型别名（降低 clippy 复杂类型告警）。
type MetaTuple = (
    Option<String>,
    Option<String>,
    Option<String>,
    Option<String>,
    Vec<String>,
);
fn scan_meta(text: &str) -> MetaTuple {
    let mut depth: i64 = 0;
    let mut in_root = false;
    let mut in_mods = false;
    let mut save_version: Option<String> = None;
    let mut game_version: Option<String> = None;
    let mut date: Option<String> = None;
    let mut player_name: Option<String> = None;
    let mut mods: Vec<String> = Vec::new();

    for line in text.lines() {
        let opens = line.matches('{').count() as i64;
        let closes = line.matches('}').count() as i64;

        if !in_root && line_opens_key(line.trim(), ROOT) {
            in_root = true;
        }
        if in_root && depth == 1 {
            if save_version.is_none() {
                save_version = extract_field(line, K_SAVE_VERSION);
            }
            if game_version.is_none() {
                game_version = extract_field(line, K_GAME_VERSION);
            }
            if date.is_none() {
                date = extract_field(line, K_DATE);
            }
            if player_name.is_none() {
                player_name = extract_field(line, K_PLAYER_NAME);
            }
            if line_opens_key(line.trim(), K_MODS) {
                in_mods = true;
            }
        }
        if in_mods {
            for q in quoted_strings(line) {
                mods.push(q);
            }
        }

        let new_depth = depth + opens - closes;
        if in_mods && new_depth <= 1 {
            in_mods = false;
        }
        depth = new_depth;
        if depth < 0 {
            depth = 0;
        }

        if in_root
            && save_version.is_some()
            && game_version.is_some()
            && date.is_some()
            && player_name.is_some()
            && !mods.is_empty()
            && !in_mods
            && depth <= 1
        {
            break;
        }
    }
    (save_version, game_version, date, player_name, mods)
}

/// 当前所在的人物子块。
#[derive(Clone, Copy, PartialEq)]
enum SubBlock {
    Family,
    Dead,
}

/// 当前正在收集的列表容器。
#[derive(Clone, Copy, PartialEq)]
enum ListKind {
    Child,
    Spouse,
    Traits,
    FormerSpouse,
    FormerConcubinist,
    FormerConcubine,
    Concubine,
}

/// 完整扫描人物容器：统计总数/死亡数，并提取每个角色的完整记录。
///
/// 会依次进入 living / dead_unprunable / dead_prunable 三个容器（dead_prunable 嵌在
/// 顶层 `characters` 之下），因此容器探测不限定深度。存活与否由容器决定，
/// 不再依赖任何 "9999.1.1" 哨兵值。
fn scan_characters_full(text: &str) -> (usize, usize, Vec<CharacterRecord>) {
    let mut depth: i64 = 0;
    let mut base: i64 = -1; // 当前人物容器所在深度；-1 表示不在容器内
    let mut container_name = "";
    let mut container_alive = true;
    let mut count = 0usize;
    let mut records: Vec<CharacterRecord> = Vec::new();
    let mut cur: Option<CharacterRecord> = None;
    let mut sub: Option<SubBlock> = None;
    let mut sub_depth: i64 = 0;
    let mut list: Option<ListKind> = None;
    let mut list_depth: i64 = 0;

    for line in text.lines() {
        let opens = line.matches('{').count() as i64;
        let closes = line.matches('}').count() as i64;
        let t = line.trim();

        if base < 0 {
            // 容器探测：living / dead_unprunable / dead_prunable
            for (name, tok, alive) in K_CHAR_CONTAINERS {
                if line_opens_key(t, &[name, tok]) {
                    base = depth;
                    container_name = name;
                    container_alive = *alive;
                    break;
                }
            }
        } else {
            let entry_depth = base + 1; // 数字 id 条目
            let field_depth = base + 2; // 条目内的直接字段

            // 新人物条目
            if depth == entry_depth
                && let Some(id) = capture_id_entry(t)
            {
                if let Some(c) = cur.take() {
                    records.push(c);
                }
                count += 1;
                cur = Some(CharacterRecord::new(id, container_name, container_alive));
                sub = None;
                list = None;
            }

            if let Some(c) = cur.as_mut() {
                if depth == field_depth {
                    // —— 直接标量字段 ——
                    if c.name.is_none() {
                        c.name = extract_kv(t, K_NAME);
                    }
                    if c.birth.is_none() {
                        c.birth = extract_kv(t, K_BIRTH);
                    }
                    if c.nickname.is_none() {
                        c.nickname = extract_kv(t, K_NICKNAME);
                    }
                    if c.ethnicity.is_none() {
                        c.ethnicity = extract_kv(t, K_ETHNICITY);
                    }
                    if c.culture.is_none() {
                        c.culture = extract_kv(t, K_CULTURE);
                    }
                    if c.faith.is_none() {
                        c.faith = extract_kv(t, K_FAITH);
                    }
                    if c.dynasty.is_none() {
                        c.dynasty = extract_kv(t, K_DYNASTY_HOUSE);
                    }
                    if c.sexuality.is_none() {
                        c.sexuality = extract_kv(t, K_SEXUALITY);
                    }
                    // 性别：存档只写 female=yes，缺省即男性（CK3 编码约定）。
                    if line_is_yes(t, K_FEMALE) {
                        c.sex = Some("female".into());
                    }
                    // 持有封地 → 统治者
                    if line_opens_key(t, K_LANDED_DATA) {
                        c.ruler = true;
                    }
                    // —— 子块进入 ——
                    if line_opens_key(t, K_FAMILY_DATA) {
                        sub = Some(SubBlock::Family);
                        sub_depth = depth;
                    } else if line_opens_key(t, K_DEAD_DATA) {
                        sub = Some(SubBlock::Dead);
                        sub_depth = depth;
                    } else if line_opens_key(t, K_TRAITS) {
                        list = Some(ListKind::Traits);
                        list_depth = depth;
                        if let Some(ids) = same_line_brace_ids(line) {
                            c.traits.extend(ids);
                            list = None;
                        }
                    }
                } else if sub == Some(SubBlock::Family) && depth == sub_depth + 1 {
                    // —— family_data 内 ——
                    let list_hit = if line_opens_key(t, K_CHILD) {
                        Some(ListKind::Child)
                    } else if line_opens_key(t, K_SPOUSE) {
                        Some(ListKind::Spouse)
                    } else if line_opens_key(t, K_FORMER_SPOUSES) {
                        Some(ListKind::FormerSpouse)
                    } else if line_opens_key(t, K_FORMER_CONCUBINISTS) {
                        Some(ListKind::FormerConcubinist)
                    } else if line_opens_key(t, K_FORMER_CONCUBINES) {
                        Some(ListKind::FormerConcubine)
                    } else if line_opens_key(t, K_CONCUBINE) {
                        Some(ListKind::Concubine)
                    } else {
                        None
                    };
                    if let Some(kind) = list_hit {
                        list = Some(kind);
                        list_depth = depth;
                        // 单行列表（child={ 49459 49846 }）：melt 输出常把列表写在同一行闭合。
                        if let Some(ids) = same_line_brace_ids(line) {
                            push_list_ids(c, kind, &ids);
                            list = None;
                        }
                    } else {
                        if let Some(v) = extract_kv(t, K_CHILD) {
                            c.children.push(v);
                        }
                        if let Some(v) = extract_kv(t, K_SPOUSE) {
                            c.spouses.push(v);
                        }
                        // concubine 也可写成标量多行（一人多妾），与块列表等价。
                        if let Some(v) = extract_kv(t, K_CONCUBINE) {
                            c.concubines.push(v);
                        }
                        if c.primary_spouse.is_none() {
                            c.primary_spouse = extract_kv(t, K_PRIMARY_SPOUSE);
                        }
                        if c.real_father.is_none()
                            && let Some(v) = extract_kv(t, K_REAL_FATHER)
                        {
                            c.real_father = Some(v);
                        }
                        if c.betrothed.is_none() {
                            c.betrothed = extract_kv(t, K_BETROTHED);
                        }
                        if c.concubinist.is_none() {
                            c.concubinist = extract_kv(t, K_CONCUBINIST);
                        }
                    }
                } else if sub == Some(SubBlock::Dead) && depth == sub_depth + 1 {
                    // —— dead_data 内：date 才是死亡日期 ——
                    if c.death.is_none() {
                        c.death = extract_kv(t, K_DEATH_DATE);
                    }
                    if c.death_reason.is_none() {
                        c.death_reason = extract_kv(t, K_DEATH_REASON);
                    }
                    if c.killer.is_none() {
                        c.killer = extract_kv(t, K_KILLER);
                    }
                    // 2C.1：君主仅实测于 dead_data 子块（卒年记录其君主）。
                    if c.liege.is_none() {
                        c.liege = extract_kv(t, K_LIEGE);
                    }
                }

                // —— 列表体：收集裸 id ——
                if let Some(kind) = list
                    && depth > list_depth
                {
                    for tok in bare_id_tokens(line) {
                        match kind {
                            ListKind::Child => c.children.push(tok),
                            ListKind::Spouse => c.spouses.push(tok),
                            ListKind::Traits => c.traits.push(tok),
                            ListKind::FormerSpouse => c.former_spouses.push(tok),
                            ListKind::FormerConcubinist => c.former_concubinists.push(tok),
                            ListKind::FormerConcubine => c.former_concubines.push(tok),
                            ListKind::Concubine => c.concubines.push(tok),
                        }
                    }
                }
            }
        }

        let new_depth = depth + opens - closes;
        if base >= 0 {
            if list.is_some() && new_depth <= list_depth {
                list = None;
            }
            if sub.is_some() && new_depth <= sub_depth {
                sub = None;
            }
            if new_depth <= base {
                // 容器结束
                if let Some(c) = cur.take() {
                    records.push(c);
                }
                base = -1;
                container_name = "";
                sub = None;
                list = None;
            }
        }
        depth = new_depth.max(0);
    }
    if let Some(c) = cur.take() {
        records.push(c);
    }

    // 亲子关系只能反推（存档无 father/mother 字段）。
    build_parent_index(&mut records);
    let dead = records.iter().filter(|r| !r.alive).count();
    (count, dead, records)
}

/// 收集行中的裸 id token（数字或 tXXXX），用于 spouse=/child= 列表。
fn bare_id_tokens(line: &str) -> Vec<String> {
    let mut out = Vec::new();
    for tok in line.split(|c: char| c.is_whitespace() || c == '{' || c == '}' || c == '"') {
        if tok.is_empty() {
            continue;
        }
        let is_num = tok.chars().all(|c| c.is_ascii_digit());
        let is_tok = tok.starts_with('t')
            && tok.len() == 5
            && tok[1..].chars().all(|c| c.is_ascii_hexdigit());
        if is_num || is_tok {
            out.push(tok.to_string());
        }
    }
    out
}

/// 若行是单行花括号列表（打开与闭合在同一行），返回 `{` 与 `}` 之间的裸 id。
/// melt 输出常把 child/spouse/former_spouses/traits 等列表写为
/// `child={ 49459 49846 50633 }` 的单行形态，与多行列表（`child={` 换行 id）并存。
fn same_line_brace_ids(line: &str) -> Option<Vec<String>> {
    let open = line.find('{')?;
    let close = line.rfind('}')?;
    if close < open {
        return None;
    }
    let ids = bare_id_tokens(&line[open + 1..close]);
    if ids.is_empty() {
        None
    } else {
        Some(ids)
    }
}

/// 把已收集的裸 id 列表按类型写入人物记录（与主循环的列表体收集共用同一分发）。
fn push_list_ids(c: &mut CharacterRecord, kind: ListKind, ids: &[String]) {
    match kind {
        ListKind::Child => c.children.extend(ids.iter().cloned()),
        ListKind::Spouse => c.spouses.extend(ids.iter().cloned()),
        ListKind::Traits => c.traits.extend(ids.iter().cloned()),
        ListKind::FormerSpouse => c.former_spouses.extend(ids.iter().cloned()),
        ListKind::FormerConcubinist => c.former_concubinists.extend(ids.iter().cloned()),
        ListKind::FormerConcubine => c.former_concubines.extend(ids.iter().cloned()),
        ListKind::Concubine => c.concubines.extend(ids.iter().cloned()),
    }
}

fn capture_id_entry(line: &str) -> Option<String> {
    let t = line.trim_start();
    if !t.contains("={") {
        return None;
    }
    let head = t.split('=').next().unwrap_or("").trim();
    if head.is_empty() {
        return None;
    }
    if head.chars().all(|c| c.is_ascii_digit()) {
        Some(head.to_string())
    } else {
        None
    }
}

fn encoding_name(e: ck3save::Encoding) -> String {
    format!("{e:?}")
}

// ----------------------------------------------------------------------------
// Phase 2B M2.1：实体索引扫描
//
// 职责边界（重要）：Rust 侧**只从存档里抄事实**——把每个实体的数字 id 映射到存档
// 自述的「内部键」（internal key，如 faith_type="akom_pagan"、name="dynn_Orsini"、
// key="h_roman_empire"）。**不做任何本地化、不查游戏目录、不猜名字**。
// 把内部键翻译成可读名（中文）是 Python 侧 EntityIndexBuilder 的事（M2.4/M2.5），
// 那里才有 LocalizationLoader 与游戏定义文件。
//
// 这样分层的原因：内部键是存档自带的确定事实（confirmed），本地化结果可能失败
// （缺游戏目录 / Mod 自定义键无 loc），失败时必须显式 unresolved，不能被伪造掩盖。
// ----------------------------------------------------------------------------

/// 单个实体条目。除 `key` 外全部可选，缺失即不序列化（不写 null 占位，避免伪装成"有值"）。
#[derive(Serialize, Default, Clone)]
struct EntityEntry {
    /// 存档自述的内部键。为 None 表示存档里这条没有键，Python 侧必须标 unresolved。
    #[serde(skip_serializing_if = "Option::is_none")]
    key: Option<String>,
    /// 内部键的性质。**缺省（不序列化）表示 "loc"**：`key` 本身就是本地化键，可直接查 loc。
    /// 取值 "def" 表示 `key` 是**游戏定义文件里的键**（如 house 的 `house_jerome_karling`、
    /// dynasty 的 `"2"`），必须先到 game/common/ 里查出它的 `name=dynn_xxx` 才能查 loc。
    /// 两种形态在同一个容器里混排（存档里静态定义与运行时生成的实体并存），不能假设只有一种。
    #[serde(skip_serializing_if = "Option::is_none")]
    key_kind: Option<String>,
    /// 家族前缀（如 dynnp_de），只有 house 有。
    #[serde(skip_serializing_if = "Option::is_none")]
    prefix: Option<String>,
    /// 上级实体 id：house→dynasty、faith→religion。
    #[serde(skip_serializing_if = "Option::is_none")]
    parent: Option<String>,
    /// 存档里**已经是可读文本**的名字（玩家自定义头衔名 / 混合文化名 / 战争名），
    /// 无需再查本地化；Python 侧优先采用它。
    #[serde(skip_serializing_if = "Option::is_none")]
    save_name: Option<String>,
    /// 战争开始日期（存档直述）。
    #[serde(skip_serializing_if = "Option::is_none")]
    start_date: Option<String>,
}

impl EntityEntry {
    fn from_key(key: String) -> Self {
        Self {
            key: Some(key),
            ..Default::default()
        }
    }
}

#[derive(Serialize)]
struct EntityKindIndex {
    /// 该索引的证据来源路径（存档内容器路径），用于可追溯性。
    source: String,
    /// 容器是否在本存档里找到。false 时 entries 为空且会有 warning。
    container_found: bool,
    count: usize,
    /// 既没有内部键、也没有存档成品名的条目数——这些实体**无法命名**，
    /// Python 侧必须标 resolved=false 并以原始 id 作为显示名，不得编名字。
    unresolved_key_count: usize,
    entries: BTreeMap<String, EntityEntry>,
}

#[derive(Serialize)]
struct EntitiesOutput {
    schema_version: u32,
    reader_version: String,
    /// 缓存 schema 版本（CACHE_SCHEMA_VERSION）：Python 侧 _cache_valid 校验，
    /// 防止扫描/提取行为变更后旧缓存被复用。
    cache_schema_version: String,
    /// 扫描耗时，便于评估 prepare 的额外开销。
    scan_ms: f64,
    kinds: BTreeMap<String, EntityKindIndex>,
    warnings: Vec<String>,
}

/// 实体类别（与 packages/save-schema 的 EntityKind 一一对应）。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum EKind {
    Faith,
    Religion,
    Culture,
    House,
    Dynasty,
    Title,
    War,
    MemoryType,
    CourtPositionType,
}

fn seg_matches(seg: &str, keys: &[&str]) -> bool {
    keys.contains(&seg)
}

/// 由容器路径（path[0]=顶层键, path[1]=子容器键）判定实体类别。
///
/// 注意顺序：`dynasties` 顶层下同时有 `dynasty_house` 与同名的 `dynasties`，
/// 必须先判 house 再判 dynasty。
fn classify_container(path: &[String]) -> Option<EKind> {
    if path.len() < 2 {
        return None;
    }
    let (a, b) = (path[0].as_str(), path[1].as_str());
    if seg_matches(a, K_RELIGION_ROOT) && seg_matches(b, K_FAITHS) {
        Some(EKind::Faith)
    } else if seg_matches(a, K_RELIGION_ROOT) && seg_matches(b, K_RELIGIONS) {
        Some(EKind::Religion)
    } else if seg_matches(a, K_CULTURE_MANAGER) && seg_matches(b, K_CULTURES) {
        Some(EKind::Culture)
    } else if seg_matches(a, K_DYNASTIES_ROOT) && seg_matches(b, K_DYNASTY_HOUSES) {
        Some(EKind::House)
    } else if seg_matches(a, K_DYNASTIES_ROOT) && seg_matches(b, K_DYNASTIES_ROOT) {
        Some(EKind::Dynasty)
    } else if seg_matches(a, K_LANDED_TITLES_ROOT) && seg_matches(b, K_LANDED_TITLES_ROOT) {
        Some(EKind::Title)
    } else if seg_matches(a, K_WARS_ROOT) && seg_matches(b, K_ACTIVE_WARS) {
        Some(EKind::War)
    } else if seg_matches(a, K_MEMORY_MANAGER) && seg_matches(b, K_DATABASE) {
        Some(EKind::MemoryType)
    } else if seg_matches(a, K_COURT_POSITIONS) && seg_matches(b, K_DATABASE) {
        Some(EKind::CourtPositionType)
    } else {
        None
    }
}

/// 取一行开块行的键（`key={` → `key`；裸 `{` → 空串）。
fn block_key(t: &str) -> String {
    match t.find('=') {
        Some(i) => t[..i].trim().to_string(),
        None => String::new(),
    }
}

/// 解析数组行里的元素。
///
/// 同一份存档在两种 token 表下形态不同，两种都要吃：
/// - 真实 token 表：`traits_lookup` 的元素是**裸标识符**（education_intrigue_1 ...）；
/// - 占位 token 表：元素是**带引号字符串**（"education_intrigue_1" ...）。
fn array_items(t: &str) -> Vec<String> {
    t.split_whitespace()
        .map(|s| s.trim_matches(|c| c == '"' || c == '{' || c == '}'))
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
        .collect()
}

/// 收集本行里的裸数字（用于 `religions.{id}.faiths={ 0 1 2 }` 这类 id 列表）。
fn bare_numbers(t: &str) -> Vec<String> {
    t.split(|c: char| c.is_whitespace() || c == '{' || c == '}')
        .filter(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()))
        .map(|s| s.to_string())
        .collect()
}

/// 累加器：各实体类别的条目表。
#[derive(Default)]
struct EntityAcc {
    traits: Vec<String>,
    faiths: BTreeMap<String, EntityEntry>,
    religions: BTreeMap<String, EntityEntry>,
    cultures: BTreeMap<String, EntityEntry>,
    houses: BTreeMap<String, EntityEntry>,
    dynasties: BTreeMap<String, EntityEntry>,
    titles: BTreeMap<String, EntityEntry>,
    wars: BTreeMap<String, EntityEntry>,
    memory_types: BTreeSet<String>,
    court_position_types: BTreeSet<String>,
    /// faith id -> religion id（由 religions.{id}.faiths 列表反查得到）。
    faith_religion: BTreeMap<String, String>,
    found: HashSet<&'static str>,
}

impl EntityAcc {
    fn map_of(&mut self, kind: EKind) -> Option<&mut BTreeMap<String, EntityEntry>> {
        match kind {
            EKind::Faith => Some(&mut self.faiths),
            EKind::Religion => Some(&mut self.religions),
            EKind::Culture => Some(&mut self.cultures),
            EKind::House => Some(&mut self.houses),
            EKind::Dynasty => Some(&mut self.dynasties),
            EKind::Title => Some(&mut self.titles),
            EKind::War => Some(&mut self.wars),
            EKind::MemoryType | EKind::CourtPositionType => None,
        }
    }
}

/// 单遍扫描 melt 明文，抽取全部实体容器。
///
/// 用「路径栈」定位：`path[i]` 是深度 i 处打开的块键。只在深度 < 4 时保留真实键
/// （更深的层级用空串占位，仅用于维持深度），避免在 2700 万行上做无谓分配。
// ----------------------------------------------------------------------------
// M3：头衔与统治经历 —— 从 landed_titles 反向解析头衔归属与历史
// ----------------------------------------------------------------------------

#[derive(Serialize)]
struct TitleHistoryEntry {
    date: String,
    holder_id: Option<String>,
    /// holder | created | destroyed | other
    kind: String,
}

#[derive(Serialize)]
struct TitleEntry {
    key: String,
    name: String,
    /// save（存档内直书）/ key（看起来像未本地化的键）/ unresolved
    name_source: String,
    /// barony | county | duchy | kingdom | empire | unknown（由 key 前缀推导）
    tier: String,
    /// 当前持有者（顶层 holder 字段，仅当仍持有存在）
    holder_id: Option<String>,
    de_facto_liege_id: Option<String>,
    history: Vec<TitleHistoryEntry>,
}

#[derive(Serialize)]
struct TitlesOutput {
    schema_version: u32,
    reader_version: String,
    /// 缓存 schema 版本（CACHE_SCHEMA_VERSION）：Python 侧 _cache_valid 校验。
    cache_schema_version: String,
    scan_ms: f64,
    title_count: usize,
    titles: Vec<TitleEntry>,
    warnings: Vec<String>,
}

/// 头衔等级由 key 前缀推导（CK3 约定；h_ 为历史帝号，按 empire 处理，属最佳推断）。
fn title_tier(key: &str) -> &'static str {
    match key.chars().next() {
        Some('b') => "barony",
        Some('c') => "county",
        Some('d') => "duchy",
        Some('k') => "kingdom",
        Some('e') => "empire",
        Some('h') => "empire",
        _ => "unknown",
    }
}

/// 头衔名来源：若 name 与 key 相同、或仅由 lowercase 字母数字下划线组成（像键），视为未本地化。
fn title_name_source(name: &str, key: &str) -> &'static str {
    if name == key {
        return "key";
    }
    if let Some(c) = name.chars().next()
        && c.is_ascii_lowercase()
        && name.chars().all(|x| x.is_ascii_alphanumeric() || x == '_')
    {
        return "key";
    }
    "save"
}

/// 在 text 中定位内层 landed_titles 容器的内容（去掉外层花括号）。
fn find_landed_titles_inner(text: &str) -> Option<&str> {
    let first = text.find("landed_titles={")?;
    let rest = &text[first + 1..];
    let inner_off = rest.find("landed_titles={")?;
    let inner = first + 1 + inner_off;
    let open = inner + "landed_titles=".len();
    let (block, _) = extract_balanced(text, open)?;
    if block.len() >= 2 {
        Some(&block[1..block.len() - 1])
    } else {
        None
    }
}

/// 从一段文本里，从 open_idx（指向 '{'）起提取配平的花括号块，返回块与块后位置。
fn extract_balanced(text: &str, open_idx: usize) -> Option<(&str, usize)> {
    let bytes = text.as_bytes();
    if bytes.get(open_idx) != Some(&b'{') {
        return None;
    }
    let mut depth = 0i64;
    let mut i = open_idx;
    while i < bytes.len() {
        match bytes[i] {
            b'{' => depth += 1,
            b'}' => {
                depth -= 1;
                if depth == 0 {
                    return Some((&text[open_idx..=i], i + 1));
                }
            }
            _ => {}
        }
        i += 1;
    }
    None
}

/// 提取顶层（深度 0）的 {…} 块列表。
fn extract_top_level_blocks(s: &str) -> Vec<&str> {
    let bytes = s.as_bytes();
    let mut blocks = Vec::new();
    let mut depth = 0i64;
    let mut start: Option<usize> = None;
    for i in 0..bytes.len() {
        match bytes[i] {
            b'{' => {
                if depth == 0 {
                    start = Some(i);
                }
                depth += 1;
            }
            b'}' => {
                depth -= 1;
                if depth == 0 {
                    if let Some(st) = start {
                        blocks.push(&s[st..=i]);
                    }
                    start = None;
                }
            }
            _ => {}
        }
    }
    blocks
}

/// 在 block 中查找独立键 key（前导为空白/‘{’/‘=’/行首），返回 ‘key=’ 之后（等号后）的位置。
fn find_kv(block: &str, key: &str) -> Option<usize> {
    let bytes = block.as_bytes();
    let mut from = 0;
    loop {
        let idx = block[from..].find(key)? + from;
        let prev_ok = idx == 0
            || matches!(
                bytes.get(idx - 1),
                Some(b' ') | Some(b'\t') | Some(b'\n') | Some(b'\r') | Some(b'{') | Some(b'=')
            );
        if prev_ok {
            let after = idx + key.len();
            let mut j = after;
            while j < bytes.len() && (bytes[j] == b' ' || bytes[j] == b'\t') {
                j += 1;
            }
            if j < bytes.len() && bytes[j] == b'=' {
                return Some(j + 1);
            }
        }
        from = idx + key.len();
    }
}

fn grab_quoted(block: &str, key: &str) -> Option<String> {
    let pos = find_kv(block, key)?;
    let s = &block[pos..];
    // 等号后可能有空格（key = "value"）；兼容引号与非引号两种值形态。
    let s = s.trim_start();
    if let Some(inner) = s.strip_prefix('"') {
        inner.find('"').map(|e| inner[..e].to_string())
    } else {
        // 非引号值（如 key=h_roman_empire）：读到空白 / 右花括号 / 等号为止。
        let end = s
            .find(|c: char| c.is_ascii_whitespace() || c == '}' || c == '=' || c == '{')
            .unwrap_or(s.len());
        if end == 0 {
            None
        } else {
            Some(s[..end].to_string())
        }
    }
}

fn grab_num(block: &str, key: &str) -> Option<String> {
    let pos = find_kv(block, key)?;
    let s = &block[pos..];
    let digits: String = s.chars().take_while(|c| c.is_ascii_digit()).collect();
    if digits.is_empty() {
        None
    } else {
        Some(digits)
    }
}

/// 在 s 的 i 位置尝试解析 YYYY.MM.DD，返回 (日期串, 日期后位置)。
fn parse_date_at(s: &str, i: usize) -> Option<(String, usize)> {
    let b = s.as_bytes();
    let mut j = i;
    while j < b.len() && b[j].is_ascii_digit() {
        j += 1;
    }
    if j == i || j >= b.len() || b[j] != b'.' {
        return None;
    }
    let d1 = &s[i..j];
    j += 1;
    let m0 = j;
    while j < b.len() && b[j].is_ascii_digit() {
        j += 1;
    }
    if j == m0 || j >= b.len() || b[j] != b'.' {
        return None;
    }
    let d2 = &s[m0..j];
    j += 1;
    let d0 = j;
    while j < b.len() && b[j].is_ascii_digit() {
        j += 1;
    }
    if j == d0 {
        return None;
    }
    let d3 = &s[d0..j];
    Some((format!("{}.{}.{}", d1, d2, d3), j))
}

/// 由日期串生成可排序的 (年,月,日) 键（CK3 日期未零填充，必须数值排序）。
fn ck3_date_key(s: &str) -> (i64, i64, i64) {
    let p: Vec<&str> = s.split('.').collect();
    if p.len() == 3 {
        (
            p[0].parse().unwrap_or(0),
            p[1].parse().unwrap_or(0),
            p[2].parse().unwrap_or(0),
        )
    } else {
        (0, 0, 0)
    }
}

fn read_token(s: &str, pos: usize) -> Option<String> {
    let b = s.as_bytes();
    let mut j = pos;
    while j < b.len() && (b[j] == b' ' || b[j] == b'\t') {
        j += 1;
    }
    let start = j;
    while j < b.len() && !b[j].is_ascii_whitespace() && b[j] != b'}' && b[j] != b'"' {
        j += 1;
    }
    if j > start {
        Some(s[start..j].to_string())
    } else {
        None
    }
}

/// 解析单个头衔块的 history 内容，提取每次持有者变更。
fn parse_title_history(inner: &str) -> Vec<TitleHistoryEntry> {
    let bytes = inner.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if let Some((date, after_date)) = parse_date_at(inner, i)
            && after_date < inner.len()
            && bytes[after_date] == b'='
        {
            let vstart = after_date + 1;
            if vstart < inner.len() && bytes[vstart] == b'{' {
                // Format B：date={ type=... holder=... }
                if let Some((blk, end)) = extract_balanced(inner, vstart) {
                    let t = find_kv(blk, "type").and_then(|p| read_token(blk, p));
                    let holder = find_kv(blk, "holder").and_then(|p| {
                        let ds: String = blk[p..]
                            .chars()
                            .take_while(|c| c.is_ascii_digit())
                            .collect();
                        if ds.is_empty() { None } else { Some(ds) }
                    });
                    let kind = match t.as_deref() {
                        Some("created") => "created",
                        Some("destroyed") => "destroyed",
                        _ => "other",
                    };
                    out.push(TitleHistoryEntry {
                        date,
                        holder_id: holder,
                        kind: kind.to_string(),
                    });
                    i = end;
                    continue;
                }
            } else {
                // Format A：date=HOLDER_ID
                let ds: String = inner[vstart..]
                    .chars()
                    .take_while(|c| c.is_ascii_digit())
                    .collect();
                if !ds.is_empty() {
                    out.push(TitleHistoryEntry {
                        date,
                        holder_id: Some(ds),
                        kind: "holder".to_string(),
                    });
                }
                let step = inner[vstart..]
                    .chars()
                    .take_while(|c| c.is_ascii_digit())
                    .count();
                i = vstart + step;
                while i < bytes.len() && bytes[i] != b'\n' {
                    i += 1;
                }
                continue;
            }
        }
        i += 1;
    }
    out.sort_by_key(|a| ck3_date_key(&a.date));
    out
}
fn parse_title_block(block: &str) -> Option<TitleEntry> {
    let key = grab_quoted(block, "key")?;
    // holder / de_facto_liege 只应取自 history 块**之前**的顶层字段：
    // history 内（Format B 的 date={type=created holder=ID}）也会出现 holder=，
    // 若顶层无现任持有者，全块搜索会误抓历史 holder。
    let history_off = block.find("history={").unwrap_or(block.len());
    let head = &block[..history_off];
    let holder = grab_num(head, "holder");
    let liege = grab_num(head, "de_facto_liege");
    let name = block
        .find("title_name_data={")
        .and_then(|off| {
            let open = off + "title_name_data=".len();
            extract_balanced(block, open).and_then(|(nd, _)| grab_quoted(nd, "name"))
        })
        .unwrap_or_else(|| key.clone());
    let history = block
        .find("history={")
        .and_then(|off| {
            let open = off + "history=".len();
            extract_balanced(block, open).map(|(b, _)| &b[1..b.len() - 1])
        })
        .map(parse_title_history)
        .unwrap_or_default();
    let name_source = title_name_source(&name, &key).to_string();
    let tier = title_tier(&key).to_string();
    Some(TitleEntry {
        key: key.clone(),
        name,
        name_source,
        tier,
        holder_id: holder,
        de_facto_liege_id: liege,
        history,
    })
}

fn scan_titles(text: &str) -> TitlesOutput {
    let started = Instant::now();
    let mut titles = Vec::new();
    let mut warnings = Vec::new();
    match find_landed_titles_inner(text) {
        Some(inner) => {
            for block in extract_top_level_blocks(inner) {
                if let Some(entry) = parse_title_block(block) {
                    titles.push(entry);
                }
            }
        }
        None => {
            warnings.push("container_not_found: landed_titles.landed_titles 未找到".into());
        }
    }
    let scan_ms = started.elapsed().as_secs_f64() * 1000.0;
    TitlesOutput {
        schema_version: 1,
        reader_version: env!("CARGO_PKG_VERSION").to_string(),
        cache_schema_version: CACHE_SCHEMA_VERSION.to_string(),
        scan_ms,
        title_count: titles.len(),
        titles,
        warnings,
    }
}

// ----------------------------------------------------------------------------
// M4：记忆 —— character_memory_manager.database（存档级全局库）
//
// 条目形如 `16777233={ type="battle_won_memory" participants={ ruler=10433 } … }`：
// id 是全局计数器（非连续，含 `28674=none` 之类已清除槽位）；记忆归属不能从 id
// 解码，只忠实抄录 type / participants / 日期 / battle 位置，归属交由 Python 侧
// 按「主体角色表」判定。容器缺失时给出告警，不伪造。
// ----------------------------------------------------------------------------

#[derive(Serialize)]
struct RoleRef {
    /// 参与角色（如 ruler/spouse/child；占位表构建下可能是 tXXXX，原样保留）。
    role: String,
    character_id: String,
}

#[derive(Serialize)]
struct MemoryEntry {
    id: String,
    memory_type: String,
    participants: Vec<RoleRef>,
    creation_date: Option<String>,
    end_date: Option<String>,
    /// battle 记忆的战场省 id（由 variables 内 flag=="battle_location" 提取）。
    battle_location_id: Option<String>,
}

#[derive(Serialize)]
struct MemoriesOutput {
    schema_version: u32,
    reader_version: String,
    /// 缓存 schema 版本（CACHE_SCHEMA_VERSION）：Python 侧 _cache_valid 校验。
    cache_schema_version: String,
    scan_ms: f64,
    memory_count: usize,
    memories: Vec<MemoryEntry>,
    warnings: Vec<String>,
}

/// 在块中查找任一候选键（真实名 / 占位 token），返回第一个命中的值起点。
fn find_kv_any(block: &str, keys: &[&str]) -> Option<usize> {
    keys.iter().find_map(|k| find_kv(block, k))
}

/// 取 `key={ ... }` 块的内部文本（去掉外层花括号）。找不到或非块则 None。
fn extract_kv_block_any<'a>(block: &'a str, keys: &[&str]) -> Option<&'a str> {
    let pos = find_kv_any(block, keys)?;
    let s = &block[pos..];
    let open = s.find('{')?;
    let (b, _) = extract_balanced(s, open)?;
    if b.len() >= 2 {
        Some(&b[1..b.len() - 1])
    } else {
        None
    }
}

/// 取 `key="value"` 的引号值（先尝试真实名，再试占位 token）。
fn grab_quoted_any(block: &str, keys: &[&str]) -> Option<String> {
    for k in keys {
        if let Some(pos) = find_kv(block, k)
            && let Some(inner) = block[pos..].strip_prefix('"')
            && let Some(e) = inner.find('"')
        {
            return Some(inner[..e].to_string());
        }
    }
    None
}

/// 取 `key=YYYY.MM.DD` 的日期值（两种 token 形态都试）。
fn grab_date_any(block: &str, keys: &[&str]) -> Option<String> {
    keys.iter().find_map(|k| {
        let pos = find_kv(block, k)?;
        parse_date_at(block, pos).map(|(d, _)| d)
    })
}

/// 解析 participants 块内全部 `role=character_id` 行。
fn parse_participants(inner: &str) -> Vec<RoleRef> {
    let mut out = Vec::new();
    for line in inner.lines() {
        let t = line.trim();
        if t.is_empty() || t.starts_with('{') || t.starts_with('}') {
            continue;
        }
        if let Some(eq) = t.find('=') {
            let role = t[..eq].trim().trim_matches('"').to_string();
            let val = t[eq + 1..].trim().trim_matches('"').to_string();
            if !role.is_empty() && !val.is_empty() {
                out.push(RoleRef {
                    role,
                    character_id: val,
                });
            }
        }
    }
    out
}

/// 从 variables 中提取战场省 id：查找 `flag="battle_location"`（占位表形态 t0384=）后的
/// `identity=NUMBER`。
fn grab_battle_location(blk: &str) -> Option<String> {
    let vars = extract_kv_block_any(blk, K_VARIABLES)?;
    let flag_off = vars
        .find("flag=\"battle_location\"")
        .or_else(|| vars.find("t0384=\"battle_location\""))?;
    let rest = &vars[flag_off..];
    let pos = find_kv_any(rest, K_IDENTITY)?;
    let digits: String = rest[pos..]
        .chars()
        .take_while(|c| c.is_ascii_digit())
        .collect();
    if digits.is_empty() {
        None
    } else {
        Some(digits)
    }
}

/// 解析单条记忆块。type 缺失视为异常条目（返回 None 跳过，不伪造）。
fn parse_memory_block(id: &str, blk: &str) -> Option<MemoryEntry> {
    let memory_type = grab_quoted_any(blk, K_TYPE)
        .or_else(|| find_kv_any(blk, K_TYPE).and_then(|p| read_token(blk, p)))?;
    let participants = extract_kv_block_any(blk, K_PARTICIPANTS)
        .map(parse_participants)
        .unwrap_or_default();
    Some(MemoryEntry {
        id: id.to_string(),
        memory_type,
        participants,
        creation_date: grab_date_any(blk, K_CREATION_DATE),
        end_date: grab_date_any(blk, K_END_DATE),
        battle_location_id: grab_battle_location(blk),
    })
}

/// 定位 character_memory_manager.database 容器的内部文本。
fn find_memory_database_inner(text: &str) -> Option<&str> {
    // 顶层 container 只出现一次（实测确认）；database 是其直接子容器。
    let (mm_block, _) = find_container_block(text, K_MEMORY_MANAGER)?;
    let (db_block, _) = find_container_block(mm_block, K_DATABASE)?;
    if db_block.len() >= 2 {
        Some(&db_block[1..db_block.len() - 1])
    } else {
        None
    }
}

/// 在 text 中查找第一个 `key={` 容器（真实名 / 占位 token 双候选），返回配平块。
fn find_container_block<'a>(text: &'a str, keys: &[&str]) -> Option<(&'a str, usize)> {
    let bytes = text.as_bytes();
    for key in keys {
        let mut from = 0;
        while let Some(off) = text[from..].find(key) {
            let idx = from + off;
            let after = idx + key.len();
            // 独立键：前导字符不是标识符字符。
            let prev_ok = idx == 0
                || !matches!(
                    bytes.get(idx - 1),
                    Some(b) if b.is_ascii_alphanumeric() || *b == b'_'
                );
            let mut j = after;
            while j < bytes.len() && (bytes[j] == b' ' || bytes[j] == b'\t') {
                j += 1;
            }
            if prev_ok && j < bytes.len() && bytes[j] == b'=' {
                let mut k2 = j + 1;
                while k2 < bytes.len() && (bytes[k2] == b' ' || bytes[k2] == b'\t') {
                    k2 += 1;
                }
                if k2 < bytes.len()
                    && bytes[k2] == b'{'
                    && let Some((block, end)) = extract_balanced(text, k2)
                {
                    return Some((block, end));
                }
            }
            from = after;
        }
    }
    None
}

fn scan_memories(text: &str) -> MemoriesOutput {
    let started = Instant::now();
    let mut memories = Vec::new();
    let mut warnings = Vec::new();
    match find_memory_database_inner(text) {
        Some(inner) => {
            let bytes = inner.as_bytes();
            let mut i = 0;
            while i < bytes.len() {
                // 条目：NUMBER={ ... }（id 为全局计数器，非连续；`NUMBER=none` 是已清除槽位）。
                if !bytes[i].is_ascii_digit() {
                    i += 1;
                    continue;
                }
                let start = i;
                while i < bytes.len() && bytes[i].is_ascii_digit() {
                    i += 1;
                }
                let id = &inner[start..i];
                let mut j = i;
                while j < bytes.len()
                    && (bytes[j] == b' '
                        || bytes[j] == b'\t'
                        || bytes[j] == b'\n'
                        || bytes[j] == b'\r')
                {
                    j += 1;
                }
                if j < bytes.len() && bytes[j] == b'=' {
                    let mut k2 = j + 1;
                    while k2 < bytes.len()
                        && (bytes[k2] == b' '
                            || bytes[k2] == b'\t'
                            || bytes[k2] == b'\n'
                            || bytes[k2] == b'\r')
                    {
                        k2 += 1;
                    }
                    if k2 < bytes.len()
                        && bytes[k2] == b'{'
                        && let Some((blk, end)) = extract_balanced(inner, k2)
                    {
                        if let Some(entry) = parse_memory_block(id, blk) {
                            memories.push(entry);
                        }
                        i = end;
                        continue;
                    }
                }
                i = j.max(start + 1);
            }
        }
        None => {
            warnings.push("container_not_found: character_memory_manager.database 未找到".into());
        }
    }
    let scan_ms = started.elapsed().as_secs_f64() * 1000.0;
    MemoriesOutput {
        schema_version: 1,
        reader_version: env!("CARGO_PKG_VERSION").to_string(),
        cache_schema_version: CACHE_SCHEMA_VERSION.to_string(),
        scan_ms,
        memory_count: memories.len(),
        memories,
        warnings,
    }
}

fn scan_entities(text: &str) -> EntitiesOutput {
    let started = Instant::now();
    let mut acc = EntityAcc::default();
    let mut path: Vec<String> = Vec::new();
    let mut in_traits_lookup = false;

    for line in text.lines() {
        let opens = line.matches('{').count() as i64;
        let closes = line.matches('}').count() as i64;
        let net = opens - closes;
        let t = line.trim();

        if net > 0 {
            // —— 开块行：压栈，并在这一刻识别"新实体条目" ——
            let seg = if path.len() < 4 {
                block_key(t)
            } else {
                String::new()
            };
            path.push(seg);
            for _ in 1..net {
                path.push(String::new());
            }

            if path.len() == 1 && seg_matches(&path[0], K_TRAITS_LOOKUP) {
                in_traits_lookup = true;
                acc.found.insert("trait");
            }
            if path.len() == 2
                && let Some(kind) = classify_container(&path)
            {
                acc.found.insert(kind_name(kind));
            }
            if path.len() == 3
                && let Some(kind) = classify_container(&path)
            {
                let id = path[2].clone();
                if !id.is_empty()
                    && let Some(map) = acc.map_of(kind)
                {
                    map.entry(id).or_default();
                }
            }
        } else {
            // —— 标量行 / 闭块行 ——
            if in_traits_lookup && path.len() == 1 {
                // traits_lookup 是一个字符串数组，**下标即 trait id**。
                // 末尾包含 Mod 自定义 trait，因此不能用任何硬编码表替代。
                acc.traits.extend(array_items(t));
            }
            if path.len() == 3
                && let Some(kind) = classify_container(&path)
            {
                let id = path[2].clone();
                collect_entry_field(&mut acc, kind, &id, t);
            } else if path.len() == 4
                && let Some(kind) = classify_container(&path)
            {
                let id = path[2].clone();
                let sub = path[3].clone();
                collect_sub_field(&mut acc, kind, &id, &sub, t);
            }

            if net < 0 {
                let target = (path.len() as i64 + net).max(0) as usize;
                if in_traits_lookup && target == 0 {
                    in_traits_lookup = false;
                }
                path.truncate(target);
            }
        }
    }

    build_entities_output(acc, started.elapsed().as_secs_f64() * 1000.0)
}

fn kind_name(kind: EKind) -> &'static str {
    match kind {
        EKind::Faith => "faith",
        EKind::Religion => "religion",
        EKind::Culture => "culture",
        EKind::House => "house",
        EKind::Dynasty => "dynasty",
        EKind::Title => "title",
        EKind::War => "war",
        EKind::MemoryType => "memoryType",
        EKind::CourtPositionType => "courtPositionType",
    }
}

/// 实体条目的直接字段（path.len()==3）。
fn collect_entry_field(acc: &mut EntityAcc, kind: EKind, id: &str, t: &str) {
    match kind {
        // 记忆 / 宫廷职位只取"类型集合"，不建 id 表（存档里有十万级条目，
        // 逐条建索引既无必要也会撑爆缓存；M4 需要实例时再按人物按需读取）。
        EKind::MemoryType => {
            if let Some(v) = extract_kv(t, K_TYPE) {
                acc.memory_types.insert(v);
            }
            return;
        }
        EKind::CourtPositionType => {
            if let Some(v) = extract_kv(t, K_COURT_POSITION_TYPE) {
                acc.court_position_types.insert(v);
            }
            return;
        }
        _ => {}
    }
    let Some(map) = acc.map_of(kind) else {
        return;
    };
    let entry = map.entry(id.to_string()).or_default();
    match kind {
        EKind::Faith => {
            if entry.key.is_none() {
                entry.key = extract_kv(t, K_FAITH_TYPE).or_else(|| extract_kv(t, K_TAG));
            }
        }
        EKind::Religion => {
            if entry.key.is_none() {
                entry.key = extract_kv(t, K_RELIGION_TYPE).or_else(|| extract_kv(t, K_TAG));
            }
        }
        EKind::Culture => {
            if entry.key.is_none() {
                entry.key = extract_kv(t, K_CULTURE_TEMPLATE);
            }
            // 玩家在游戏内融合/分化出的文化没有 culture_template，只有已本地化的 name（如 "惠循"）。
            if entry.save_name.is_none() {
                entry.save_name = extract_kv(t, K_ENTITY_NAME);
            }
        }
        // 家族与王朝：静态定义的条目写 key=<游戏定义键>，运行时生成的条目写 name=dynn_xxx。
        // 同一容器里两种混排，必须都吃，并标明 key 的性质。
        EKind::House | EKind::Dynasty => {
            if let Some(v) = extract_kv(t, K_ENTITY_NAME) {
                entry.key = Some(v);
                entry.key_kind = None; // 缺省即 "loc"
            } else if entry.key.is_none()
                && let Some(v) = extract_kv(t, K_DEF_KEY)
            {
                entry.key = Some(v);
                entry.key_kind = Some("def".into());
            }
            // 游戏内新建的家族/王朝没有 name/key，只有已本地化的成品名。
            if entry.save_name.is_none() {
                entry.save_name = extract_kv(t, K_LOCALIZED_NAME);
            }
            if kind == EKind::House {
                if entry.prefix.is_none() {
                    entry.prefix = extract_kv(t, K_HOUSE_PREFIX);
                }
                if entry.parent.is_none() {
                    entry.parent = extract_kv(t, K_HOUSE_DYNASTY);
                }
            }
        }
        EKind::Title => {
            if entry.key.is_none() {
                entry.key = extract_kv(t, K_DEF_KEY);
            }
        }
        EKind::War => {
            if entry.save_name.is_none() {
                entry.save_name = extract_kv(t, K_ENTITY_NAME);
            }
            if entry.start_date.is_none() {
                entry.start_date = extract_kv(t, K_WAR_START_DATE);
            }
        }
        EKind::MemoryType | EKind::CourtPositionType => {}
    }
}

/// 实体条目的子块字段（path.len()==4，path[3] 为子块键）。
fn collect_sub_field(acc: &mut EntityAcc, kind: EKind, id: &str, sub: &str, t: &str) {
    match kind {
        // religions.{id}.faiths = { 0 1 2 } —— 反查 faith→religion 归属。
        EKind::Religion if seg_matches(sub, K_FAITHS) => {
            for fid in bare_numbers(t) {
                acc.faith_religion.insert(fid, id.to_string());
            }
        }
        // landed_titles.{id}.title_name_data.name —— 玩家自定义头衔名（已是可读文本）。
        EKind::Title if seg_matches(sub, K_TITLE_NAME_DATA) => {
            if let Some(v) = extract_kv(t, K_ENTITY_NAME) {
                acc.titles.entry(id.to_string()).or_default().save_name = Some(v);
            }
        }
        // active_wars.{id}.casus_belli.type —— 战争的开战理由类型键。
        EKind::War if seg_matches(sub, K_CASUS_BELLI) => {
            if let Some(v) = extract_kv(t, K_TYPE) {
                let e = acc.wars.entry(id.to_string()).or_default();
                if e.key.is_none() {
                    e.key = Some(v);
                }
            }
        }
        _ => {}
    }
}

fn build_entities_output(acc: EntityAcc, scan_ms: f64) -> EntitiesOutput {
    let EntityAcc {
        traits,
        mut faiths,
        religions,
        cultures,
        houses,
        dynasties,
        titles,
        wars,
        memory_types,
        court_position_types,
        faith_religion,
        found,
    } = acc;

    // 回填 faith→religion 归属（来自 religions.{id}.faiths 列表，属存档直述）。
    for (fid, rid) in &faith_religion {
        if let Some(e) = faiths.get_mut(fid) {
            e.parent = Some(rid.clone());
        }
    }

    let mut warnings: Vec<String> = Vec::new();
    let mut kinds: BTreeMap<String, EntityKindIndex> = BTreeMap::new();

    let trait_entries: BTreeMap<String, EntityEntry> = traits
        .iter()
        .enumerate()
        .map(|(i, k)| (i.to_string(), EntityEntry::from_key(k.clone())))
        .collect();
    push_kind(
        &mut kinds,
        "trait",
        "save:traits_lookup",
        found.contains("trait"),
        trait_entries,
    );
    push_kind(
        &mut kinds,
        "faith",
        "save:religion.faiths",
        found.contains("faith"),
        faiths,
    );
    push_kind(
        &mut kinds,
        "religion",
        "save:religion.religions",
        found.contains("religion"),
        religions,
    );
    push_kind(
        &mut kinds,
        "culture",
        "save:culture_manager.cultures",
        found.contains("culture"),
        cultures,
    );
    push_kind(
        &mut kinds,
        "house",
        "save:dynasties.dynasty_house",
        found.contains("house"),
        houses,
    );
    push_kind(
        &mut kinds,
        "dynasty",
        "save:dynasties.dynasties",
        found.contains("dynasty"),
        dynasties,
    );
    push_kind(
        &mut kinds,
        "title",
        "save:landed_titles.landed_titles",
        found.contains("title"),
        titles,
    );
    push_kind(
        &mut kinds,
        "war",
        "save:wars.active_wars",
        found.contains("war"),
        wars,
    );
    push_kind(
        &mut kinds,
        "memoryType",
        "save:character_memory_manager.database[].type",
        found.contains("memoryType"),
        set_to_entries(memory_types),
    );
    push_kind(
        &mut kinds,
        "courtPositionType",
        "save:court_positions.database[].court_position",
        found.contains("courtPositionType"),
        set_to_entries(court_position_types),
    );

    for (name, idx) in &kinds {
        if !idx.container_found {
            warnings.push(format!(
                "container_not_found: {name} （来源 {}）—— 该类实体索引为空，引用只能标 unresolved",
                idx.source
            ));
        } else if idx.unresolved_key_count > 0 {
            warnings.push(format!(
                "unnameable_entities: {name} 有 {}/{} 条既无内部键也无成品名，这些引用必须标 unresolved",
                idx.unresolved_key_count, idx.count
            ));
        }
    }

    EntitiesOutput {
        schema_version: 1,
        reader_version: env!("CARGO_PKG_VERSION").to_string(),
        cache_schema_version: CACHE_SCHEMA_VERSION.to_string(),
        scan_ms,
        kinds,
        warnings,
    }
}

fn set_to_entries(set: BTreeSet<String>) -> BTreeMap<String, EntityEntry> {
    // memoryType / courtPositionType 的键是游戏定义区块键（如 became_soulmates /
    // travel_leader_court_position），必须经 GameDefLoader 反查 name 本地化键，
    // 因此标记 key_kind="def"，Python 侧据此走 GameDefLoader 而非直接查 loc。
    set.into_iter()
        .map(|k| {
            let mut e = EntityEntry::from_key(k.clone());
            e.key_kind = Some("def".into());
            (k, e)
        })
        .collect()
}

fn push_kind(
    kinds: &mut BTreeMap<String, EntityKindIndex>,
    name: &str,
    source: &str,
    container_found: bool,
    entries: BTreeMap<String, EntityEntry>,
) {
    let unresolved_key_count = entries
        .values()
        .filter(|e| e.key.is_none() && e.save_name.is_none())
        .count();
    kinds.insert(
        name.to_string(),
        EntityKindIndex {
            source: source.to_string(),
            container_found,
            count: entries.len(),
            unresolved_key_count,
            entries,
        },
    );
}

// ----------------------------------------------------------------------------
// prepare：一次 melt，写受控缓存目录
// ----------------------------------------------------------------------------
#[derive(Serialize)]
struct Manifest {
    signature: String,
    original_name: String,
    game_version: Option<String>,
    save_version: Option<String>,
    created_at: String,
    reader_version: String,
    /// 缓存 schema 版本（CACHE_SCHEMA_VERSION）：Python 侧 _cache_valid 校验。
    cache_schema_version: String,
    melted_bytes: usize,
}

fn cmd_prepare(save_path: &Path, cache_dir: &Path, with_melted: bool) -> Result<(), String> {
    let started = Instant::now();
    let data = read_save_bytes(save_path)?;
    let (melted, unknown) = melt_save(&data)?;
    let text = String::from_utf8_lossy(&melted);
    let (save_version, game_version, date, player_name, mods) = scan_meta(&text);
    let (character_count, dead_count, records) = scan_characters_full(&text);
    let token_metrics = compute_token_metrics(&text);
    let entities = scan_entities(&text);

    fs::create_dir_all(cache_dir).map_err(|e| format!("创建缓存目录失败: {e}"))?;

    // meta.json
    let token_source = detect_token_source(&token_metrics);
    let meta = InspectOutput {
        path: save_path
            .file_name()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_default(),
        encoding: {
            let file = Ck3File::from_slice(&data).map_err(|e| format!("Ck3File 失败: {e}"))?;
            encoding_name(file.encoding())
        },
        save_version,
        game_version,
        date,
        player_name,
        mod_count: mods.len(),
        mods: mods.clone(),
        character_count,
        dead_character_count: dead_count,
        sample_characters: records.iter().take(8).cloned().collect(),
        unknown_token_count: unknown,
        header_parse_ok: try_parse_metadata(&data),
        melted_bytes: melted.len(),
        parse_ms: started.elapsed().as_secs_f64() * 1000.0,
        token_metrics,
        token_source,
        reader_version: env!("CARGO_PKG_VERSION").to_string(),
        cache_schema_version: CACHE_SCHEMA_VERSION.to_string(),
    };
    write_json(cache_dir.join("meta.json"), &meta)?;
    write_json(
        cache_dir.join("mods.json"),
        &serde_json::json!({ "mod_count": mods.len(), "mods": mods }),
    )?;

    // entities.json（M2 实体索引：id -> 存档自述的内部键，不含任何本地化）
    // 条目量在真实存档上约 5 万，用紧凑 JSON 写，避免 pretty 把文件撑到十几 MB。
    let entity_total: usize = entities.kinds.values().map(|k| k.count).sum();
    let entity_warnings = entities.warnings.len();
    write_json_compact(cache_dir.join("entities.json"), &entities)?;

    // titles.json（M3 头衔与统治经历：每头衔的 key / 本地化名 / 等级 / 当前持有者 / history）
    let titles = scan_titles(&text);
    write_json_compact(cache_dir.join("titles.json"), &titles)?;

    // memories.json（M4 记忆库：character_memory_manager.database 的 id/type/participants/dates/battle 位置）
    let memories = scan_memories(&text);
    write_json_compact(cache_dir.join("memories.json"), &memories)?;

    // characters.ndjson + character-offsets.json
    let ndjson_path = cache_dir.join("characters.ndjson");
    let offsets_path = cache_dir.join("character-offsets.json");
    let mut ndjson_file =
        fs::File::create(&ndjson_path).map_err(|e| format!("写 ndjson 失败: {e}"))?;
    let mut offsets: std::collections::HashMap<String, u64> = std::collections::HashMap::new();
    let mut buf: Vec<u8> = Vec::new();
    for rec in &records {
        let line = serde_json::to_string(rec).map_err(|e| e.to_string())?;
        let offset = buf.len() as u64;
        offsets.insert(rec.id.clone(), offset);
        buf.extend_from_slice(line.as_bytes());
        buf.push(b'\n');
    }
    ndjson_file
        .write_all(&buf)
        .map_err(|e| format!("写 ndjson 失败: {e}"))?;
    drop(ndjson_file);
    write_json(&offsets_path, &offsets)?;

    // manifest.json（不含完整本地路径，仅文件名 + 签名）
    let manifest = Manifest {
        signature: cache_dir
            .file_name()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_default(),
        original_name: save_path
            .file_name()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_default(),
        game_version: meta.game_version.clone(),
        save_version: meta.save_version.clone(),
        created_at: now_rfc3339(),
        reader_version: env!("CARGO_PKG_VERSION").to_string(),
        cache_schema_version: CACHE_SCHEMA_VERSION.to_string(),
        melted_bytes: melted.len(),
    };
    write_json(cache_dir.join("manifest.json"), &manifest)?;

    if with_melted {
        fs::write(cache_dir.join("melted.txt"), &melted)
            .map_err(|e| format!("写 melted 失败: {e}"))?;
    }

    eprintln!(
        "prepare 完成: {} 人物, {} 实体（{} 条告警）, {} 字节 melt, {:.0}ms",
        character_count,
        entity_total,
        entity_warnings,
        melted.len(),
        meta.parse_ms
    );
    // 向 stdout 输出版本化 JSON 结果：adapter 以“非空合法 JSON”校验 prepare 成功
    // （此前仅 eprintln 摘要到 stderr，导致冷缓存首次 prepare 在 Python 侧误报
    // “输出非 JSON”而 500；缓存文件其实已写好，第二次访问才会成功——修复后首次即成功）。
    print_raw(
        &serde_json::json!({
            "ok": true,
            "character_count": character_count,
            "entity_count": entity_total,
            "melted_bytes": melted.len(),
        })
        .to_string(),
    )?;
    Ok(())
}

fn write_json<P: AsRef<Path>, T: Serialize>(path: P, v: &T) -> Result<(), String> {
    let mut f = fs::File::create(path).map_err(|e| format!("写 JSON 失败: {e}"))?;
    serde_json::to_writer_pretty(&mut f, v).map_err(|e| e.to_string())?;
    Ok(())
}

/// 紧凑 JSON（无缩进）——用于条目量大的缓存文件。
fn write_json_compact<P: AsRef<Path>, T: Serialize>(path: P, v: &T) -> Result<(), String> {
    let mut f = fs::File::create(path).map_err(|e| format!("写 JSON 失败: {e}"))?;
    serde_json::to_writer(&mut f, v).map_err(|e| e.to_string())?;
    Ok(())
}

fn now_rfc3339() -> String {
    // 不引入 chrono：用系统本地时间近似（缓存内部用，非对外契约关键字段）。
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("1970-01-01T00:00:00Z+{secs}")
}

// ----------------------------------------------------------------------------
// 缓存读取命令
// ----------------------------------------------------------------------------
fn cmd_meta(cache_dir: &Path) -> Result<(), String> {
    let p = cache_dir.join("meta.json");
    let text = fs::read_to_string(&p)
        .map_err(|e| format!("读取 meta.json 失败（缓存可能不存在）: {e}"))?;
    print_raw(&text)
}

/// 读取 prepare 生成的 entities.json（实体索引，不重新 melt）。
///
/// 正常链路里 Python 侧直接读缓存文件（避免几 MB 走 stdout）；
/// 这个子命令用于人工排查与 CI 冒烟。
fn cmd_entities(cache_dir: &Path) -> Result<(), String> {
    let p = cache_dir.join("entities.json");
    let text = fs::read_to_string(&p)
        .map_err(|e| format!("读取 entities.json 失败（缓存可能不存在）: {e}"))?;
    print_raw(&text)
}

/// 读取 prepare 生成的 titles.json（头衔归属与统治经历，不重新 melt）。
///
/// 正常链路里 Python 侧直接读缓存文件；这个子命令用于人工排查与 CI 冒烟。
fn cmd_titles(cache_dir: &Path) -> Result<(), String> {
    let p = cache_dir.join("titles.json");
    let text = fs::read_to_string(&p)
        .map_err(|e| format!("读取 titles.json 失败（缓存可能不存在，请先 prepare）: {e}"))?;
    print_raw(&text)
}

/// 读取 prepare 生成的 memories.json（M4 记忆库，不重新 melt）。
///
/// 正常链路里 Python 侧直接读缓存文件；这个子命令用于人工排查与 CI 冒烟。
fn cmd_memories(cache_dir: &Path) -> Result<(), String> {
    let p = cache_dir.join("memories.json");
    let text = fs::read_to_string(&p)
        .map_err(|e| format!("读取 memories.json 失败（缓存可能不存在，请先 prepare）: {e}"))?;
    print_raw(&text)
}

fn cmd_characters(
    cache_dir: &Path,
    offset: usize,
    limit: usize,
    query: &str,
) -> Result<(), String> {
    let ndjson = cache_dir.join("characters.ndjson");
    let text = fs::read_to_string(&ndjson).map_err(|e| format!("读取缓存失败: {e}"))?;
    let q = query.trim().to_lowercase();
    let mut matched: Vec<&str> = Vec::new();
    for line in text.lines() {
        if line.is_empty() {
            continue;
        }
        if q.is_empty() || line.to_lowercase().contains(&q) {
            matched.push(line);
        }
    }
    let total = matched.len();
    let start = offset.min(total);
    let end = (start + limit).min(total);
    let items: Vec<&str> = matched[start..end].to_vec();
    let out = serde_json::json!({
        "total": total,
        "offset": start,
        "limit": limit,
        "hasMore": end < total,
        "items": items,
    });
    print_json(&out)
}

fn cmd_character_cache(cache_dir: &Path, id: &str) -> Result<(), String> {
    let offsets_path = cache_dir.join("character-offsets.json");
    let offsets_text =
        fs::read_to_string(&offsets_path).map_err(|e| format!("读取索引失败: {e}"))?;
    let offsets: std::collections::HashMap<String, u64> =
        serde_json::from_str(&offsets_text).map_err(|e| e.to_string())?;
    let off = offsets
        .get(id)
        .ok_or_else(|| format!("缓存中未找到人物 id={id}"))?;
    let ndjson = cache_dir.join("characters.ndjson");
    let f = fs::File::open(&ndjson).map_err(|e| format!("打开缓存失败: {e}"))?;
    use std::io::{BufRead, Seek};
    let mut reader = std::io::BufReader::new(f);
    reader
        .seek(std::io::SeekFrom::Start(*off))
        .map_err(|e| e.to_string())?;
    let mut line = String::new();
    reader.read_line(&mut line).map_err(|e| e.to_string())?;
    // 已是完整 CharacterRecord JSON（含 evidence_warnings）。
    print_raw(line.trim_end())
}

fn print_raw(s: &str) -> Result<(), String> {
    let mut stdout = io::stdout().lock();
    stdout.write_all(s.as_bytes()).map_err(|e| e.to_string())?;
    stdout.write_all(b"\n").ok();
    Ok(())
}

fn print_json<T: Serialize>(v: &T) -> Result<(), String> {
    let mut stdout = io::stdout().lock();
    serde_json::to_writer_pretty(&mut stdout, v).map_err(|e| e.to_string())?;
    stdout.write_all(b"\n").ok();
    Ok(())
}

// ----------------------------------------------------------------------------
// 兼容旧子命令（inspect / list-mods / list-characters / character-json / dump）
// ----------------------------------------------------------------------------
fn cmd_inspect(path: &Path) -> Result<(), String> {
    let started = Instant::now();
    let data = read_save_bytes(path)?;
    let encoding = {
        let file =
            Ck3File::from_slice(&data).map_err(|e| format!("Ck3File::from_slice 失败: {e}"))?;
        encoding_name(file.encoding())
    };
    let header_parse_ok = try_parse_metadata(&data);
    let (melted, unknown) = melt_save(&data)?;
    let text = String::from_utf8_lossy(&melted);
    let (save_version, game_version, date, player_name, mods) = scan_meta(&text);
    let (character_count, dead_count, records) = scan_characters_full(&text);
    let token_metrics = compute_token_metrics(&text);
    let token_source = detect_token_source(&token_metrics);
    let out = InspectOutput {
        path: path.display().to_string(),
        encoding,
        save_version,
        game_version,
        date,
        player_name,
        mod_count: mods.len(),
        mods,
        character_count,
        dead_character_count: dead_count,
        sample_characters: records.iter().take(8).cloned().collect(),
        unknown_token_count: unknown,
        header_parse_ok,
        melted_bytes: melted.len(),
        parse_ms: started.elapsed().as_secs_f64() * 1000.0,
        token_metrics,
        token_source,
        reader_version: env!("CARGO_PKG_VERSION").to_string(),
        cache_schema_version: CACHE_SCHEMA_VERSION.to_string(),
    };
    print_json(&out)
}

fn cmd_list_mods(path: &Path) -> Result<(), String> {
    let data = read_save_bytes(path)?;
    let (melted, _unknown) = melt_save(&data)?;
    let text = String::from_utf8_lossy(&melted);
    let (_sv, _gv, _dt, _pn, mods) = scan_meta(&text);
    print_json(&serde_json::json!({ "mod_count": mods.len(), "mods": mods }))
}

fn cmd_list_characters(path: &Path) -> Result<(), String> {
    let started = Instant::now();
    let data = read_save_bytes(path)?;
    let (melted, _unknown) = melt_save(&data)?;
    let text = String::from_utf8_lossy(&melted);
    let (character_count, dead_count, records) = scan_characters_full(&text);
    print_json(&serde_json::json!({
        "character_count": character_count,
        "dead_character_count": dead_count,
        "sample_count": records.len(),
        "sample": records,
        "parse_ms": started.elapsed().as_secs_f64() * 1000.0,
    }))
}

fn cmd_character_json(path: &Path, id: &str) -> Result<(), String> {
    let data = read_save_bytes(path)?;
    let (melted, _unknown) = melt_save(&data)?;
    let text = String::from_utf8_lossy(&melted);
    let (_count, _dead, records) = scan_characters_full(&text);
    match records.into_iter().find(|r| r.id == id) {
        Some(rec) => print_json(&rec),
        None => {
            eprintln!("未找到人物 id={id}");
            process::exit(1);
        }
    }
}

fn cmd_dump(path: &Path, out: &Path) -> Result<(), String> {
    let data = read_save_bytes(path)?;
    let (melted, unknown) = melt_save(&data)?;
    let n = melted.len();
    fs::write(out, &melted).map_err(|e| format!("写入 dump 失败: {e}"))?;
    eprintln!("dump 完成: {n} 字节, 未知 token={unknown}");
    Ok(())
}

fn parse_flags(args: &[String]) -> (usize, usize, String, bool) {
    let mut offset = 0usize;
    let mut limit = 50usize;
    let mut query = String::new();
    let mut with_melted = false;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--offset" => {
                if let Some(v) = args.get(i + 1) {
                    offset = v.parse().unwrap_or(0);
                }
                i += 2;
            }
            "--limit" => {
                if let Some(v) = args.get(i + 1) {
                    limit = v.parse().unwrap_or(50);
                }
                i += 2;
            }
            "--query" => {
                if let Some(v) = args.get(i + 1) {
                    query = v.clone();
                }
                i += 2;
            }
            "--with-melted" => {
                with_melted = true;
                i += 1;
            }
            _ => i += 1,
        }
    }
    (offset, limit, query, with_melted)
}

fn usage() -> ! {
    eprintln!(
        "用法: ck3-reader <prepare|meta|entities|characters|character|inspect|list-mods|list-characters|character-json|dump|inspect-character|inspect-token|find-references|sample-field> <args...>"
    );
    process::exit(2);
}

// ----------------------------------------------------------------------------
// 字段研究诊断工具（仅开发用，输出写入 data/debug，不进 Git、不泄露姓名/完整存档）
// ----------------------------------------------------------------------------

/// 在 args 中取 --out <dir>（默认 data/debug），并就地移除这两项。
fn take_out_dir(args: &mut Vec<String>) -> PathBuf {
    let mut out = PathBuf::from("data/debug");
    if let Some(pos) = args.iter().position(|a| a == "--out") {
        if let Some(v) = args.get(pos + 1) {
            out = PathBuf::from(v);
        }
        args.remove(pos + 1);
        args.remove(pos);
    }
    out
}

/// 在 args 中取 --limit <n>（默认 20），并就地移除。
fn take_limit(args: &mut Vec<String>, default: usize) -> usize {
    let mut limit = default;
    if let Some(pos) = args.iter().position(|a| a == "--limit") {
        if let Some(v) = args.get(pos + 1) {
            limit = v.parse().unwrap_or(default);
        }
        args.remove(pos + 1);
        args.remove(pos);
    }
    limit
}

/// 人物容器键前缀（同时覆盖真实 token 表与占位 token 表两种 melt 形态）。
const CHAR_CONTAINER_PREFIXES: &[&str] = &[
    "living={",
    "t2ce6={",
    "dead_unprunable={",
    "t2ce8={",
    "dead_prunable={",
    "t2ce7={",
];

/// 遍历 living / dead_unprunable / dead_prunable 三个容器内的每个顶级人物块，
/// 回调 (char_id, start_line, end_line_exclusive)。
///
/// 调用方需自行 `text.lines().collect()` 一次并复用该切片，
/// 避免在回调里对上百 MB 的明文重复切分。
fn walk_char_blocks(lines: &[&str], mut f: impl FnMut(&str, usize, usize)) {
    let n = lines.len();
    // depth = 进入 lines[i] 之前的花括号深度
    let mut depth: i64 = 0;
    let mut container_base: Option<i64> = None;
    let mut i = 0usize;
    while i < n {
        let line = lines[i];
        let trimmed = line.trim_start();

        // 必须先判断"是否已离开当前容器"，再判断"是否进入新容器"，
        // 否则两个容器紧邻时会漏掉后一个。
        if let Some(base) = container_base
            && depth <= base
        {
            container_base = None;
        }

        if container_base.is_none()
            && CHAR_CONTAINER_PREFIXES
                .iter()
                .any(|p| trimmed.starts_with(p))
        {
            container_base = Some(depth);
            depth += line.matches('{').count() as i64 - line.matches('}').count() as i64;
            i += 1;
            continue;
        }

        // 人物块位于容器的直接子层：`<数字>={`
        if let Some(base) = container_base
            && depth == base + 1
            && let Some(eq) = trimmed.find("={")
        {
            let head = &trimmed[..eq];
            if !head.is_empty() && head.chars().all(|c| c.is_ascii_digit()) {
                let start = i;
                let mut d = depth;
                let mut j = i;
                while j < n {
                    d += lines[j].matches('{').count() as i64;
                    d -= lines[j].matches('}').count() as i64;
                    j += 1;
                    // 人物块闭合后深度回到容器子层
                    if d <= base + 1 {
                        break;
                    }
                }
                f(head, start, j);
                i = j;
                depth = base + 1;
                continue;
            }
        }

        depth += line.matches('{').count() as i64 - line.matches('}').count() as i64;
        i += 1;
    }
}

/// 通用字段提取：返回 (字段键, 余值)。字段键可以是可读字段名或 token id
/// （真实 / 占位两种 melt 都适用），使诊断子命令在任一代币表下都能工作。
fn field_kv(line: &str) -> Option<(String, &str)> {
    let t = line.trim_start();
    if let Some(eq) = t.find('=') {
        let key = t[..eq].trim();
        if !key.is_empty() {
            return Some((key.to_string(), &t[eq + 1..]));
        }
    }
    None
}

/// 判断一行字段键是否匹配用户输入（支持 readable<->token id 双向，基于 FIELD_MAPPINGS）。
fn field_matches(key: &str, input: &str) -> bool {
    if key == input {
        return true;
    }
    for (real, tok) in FIELD_MAPPINGS {
        if *real == input && key == *tok {
            return true;
        }
        if *tok == input && key == *real {
            return true;
        }
    }
    false
}

/// 把值脱敏为类型标签 + 安全样本（字符串值折叠为 <str>，避免泄露姓名）。
/// 人物 id 的经验取值区间（**仅供诊断报告标注可读性使用**）。
///
/// 头衔 / 记忆 / 神器等使用各自独立的 id 空间且与人物 id 数值重叠，
/// 因此该判断可能误标（例：`dynasty_house=9067` 会被标成 `charid`）。
/// 正式提取链路按字段语义取值，**不依赖**此启发式。
/// 详见 `docs/character-field-research.md` §8。
const CHARID_HEURISTIC_RANGE: std::ops::RangeInclusive<i64> = 6000..=60000;

fn looks_like_charid(iv: i64) -> bool {
    CHARID_HEURISTIC_RANGE.contains(&iv)
}

fn classify_value(rest: &str) -> String {
    let v = rest.trim();
    if v.is_empty() {
        return "empty".into();
    }
    if v == "yes" || v == "no" {
        return format!("bool:{v}");
    }
    if v.starts_with('"') {
        // 字符串值（可能是姓名/本地化 key）：折叠长度，不输出原文
        return format!("str<{}>", v.trim_matches('"').chars().count());
    }
    if v.starts_with('{') {
        let inner = v.trim_start_matches('{').trim();
        if inner.is_empty() || inner.starts_with('{') {
            return "object".into();
        }
        let nums: Vec<&str> = inner
            .split_whitespace()
            .filter(|s| s.chars().all(|c| c.is_ascii_digit()))
            .collect();
        if !nums.is_empty() {
            // 判断是否为人物 id 数组
            let char_ids: Vec<&str> = nums
                .iter()
                .copied()
                .filter(|s| s.parse::<i64>().is_ok_and(looks_like_charid))
                .collect();
            if !char_ids.is_empty() {
                return format!("array_charid({})", char_ids.len());
            }
            return format!("array_num({})", nums.len());
        }
        return "object".into();
    }
    // 裸标量：数字（可能是人物 id 或数值）
    if let Ok(iv) = v.parse::<i64>() {
        if looks_like_charid(iv) {
            return format!("charid:{iv}");
        }
        return format!("num:{iv}");
    }
    format!("other:{v}")
}

/// inspect-character：输出某人物块的全部 token 结构（类型 + 脱敏样本）。
fn cmd_inspect_character(path: &Path, id: &str, out: &Path) -> Result<(), String> {
    let data = read_save_bytes(path)?;
    let (melted, _unknown) = melt_save(&data)?;
    let text = String::from_utf8_lossy(&melted);
    let lines: Vec<&str> = text.lines().collect();
    let mut found: Option<(usize, usize)> = None;
    walk_char_blocks(&lines, |cid, s, e| {
        if cid == id {
            found = Some((s, e));
        }
    });
    let (s, e) = found.ok_or_else(|| format!("未找到人物 {id}"))?;
    let mut report = String::new();
    report.push_str(&format!("character {id} (lines {s}-{e})\n"));
    for line in &lines[s..e] {
        if let Some((tok, rest)) = field_kv(line) {
            report.push_str(&format!("  {tok:6} {}\n", classify_value(rest)));
        }
    }
    fs::create_dir_all(out).map_err(|e| format!("创建调试目录失败: {e}"))?;
    let out_path = out.join(format!("inspect_{id}.txt"));
    fs::write(&out_path, &report).map_err(|e| format!("写 inspect 失败: {e}"))?;
    // 仅打印脱敏摘要到 stdout（不泄露姓名/完整存档）
    let tok_count = lines[s..e].iter().filter(|l| field_kv(l).is_some()).count();
    println!("人物 {id}: 块 {s}-{e}, token 行 {tok_count}");
    println!("结构报告已写入 {}", out_path.display());
    Ok(())
}

/// inspect-token：统计某 token 在所有人物块中的值类型分布 + 脱敏样本。
fn cmd_inspect_token(path: &Path, token: &str, out: &Path) -> Result<(), String> {
    let data = read_save_bytes(path)?;
    let (melted, _unknown) = melt_save(&data)?;
    let text = String::from_utf8_lossy(&melted);
    let lines: Vec<&str> = text.lines().collect();
    let mut types: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
    let mut samples: Vec<String> = Vec::new();
    walk_char_blocks(&lines, |_cid, s, e| {
        for line in &lines[s..e] {
            if let Some((tok, rest)) = field_kv(line)
                && field_matches(&tok, token)
            {
                let c = classify_value(rest);
                *types.entry(c.clone()).or_insert(0) += 1;
                if samples.len() < 8 {
                    samples.push(format!("{tok} -> {c}"));
                }
            }
        }
    });
    let mut report = format!("token {token} 值类型分布:\n");
    let mut keys: Vec<_> = types.iter().collect();
    keys.sort_by(|a, b| b.1.cmp(a.1));
    for (k, v) in keys {
        report.push_str(&format!("  {k:20} {v}\n"));
    }
    report.push_str("\n样本:\n");
    for s in &samples {
        report.push_str(&format!("  {s}\n"));
    }
    fs::create_dir_all(out).map_err(|e| format!("创建调试目录失败: {e}"))?;
    let out_path = out.join(format!("inspect_token_{token}.txt"));
    fs::write(&out_path, &report).map_err(|e| format!("写 inspect_token 失败: {e}"))?;
    println!("token {token} 报告已写入 {}", out_path.display());
    Ok(())
}

/// find-references：找出所有把 <id> 作为引用值的人物块及所用 token。
fn cmd_find_references(path: &Path, id: &str, out: &Path) -> Result<(), String> {
    let data = read_save_bytes(path)?;
    let (melted, _unknown) = melt_save(&data)?;
    let text = String::from_utf8_lossy(&melted);
    let lines: Vec<&str> = text.lines().collect();
    let mut refs: Vec<(String, String)> = Vec::new();
    walk_char_blocks(&lines, |cid, s, e| {
        if cid == id {
            return; // 跳过自身
        }
        // key_stack 记录当前所在的嵌套键，用于给跨行数组元素定位归属字段
        let mut key_stack: Vec<String> = Vec::new();
        let mut hit: Option<String> = None;
        for line in &lines[s..e] {
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            if let Some((tok, rest)) = field_kv(trimmed) {
                let v = rest.trim();
                // 标量引用：<field>=<id>
                if v == id {
                    hit = Some(tok);
                    break;
                }
                if v.starts_with('{') {
                    // 单行数组：<field>={ a b c }
                    if v.trim_matches(|c| c == '{' || c == '}')
                        .split_whitespace()
                        .any(|t| t == id)
                    {
                        hit = Some(format!("{tok}(array)"));
                        break;
                    }
                    // 跨行块起始：<field>={
                    if v.ends_with('{') {
                        key_stack.push(tok);
                    }
                }
                continue;
            }
            if trimmed.starts_with('}') {
                key_stack.pop();
                continue;
            }
            // 跨行数组的元素行（纯数字序列）
            if trimmed.split_whitespace().any(|t| t == id) {
                let ctx = key_stack.last().cloned().unwrap_or_else(|| "?".to_string());
                hit = Some(format!("{ctx}(array)"));
                break;
            }
        }
        if let Some(k) = hit {
            refs.push((cid.to_string(), k));
        }
    });
    let mut report = format!("引用人物 {id} 的条目（共 {}）:\n", refs.len());
    for (cid, tok) in &refs {
        report.push_str(&format!("  char {cid} via {tok}\n"));
    }
    fs::create_dir_all(out).map_err(|e| format!("创建调试目录失败: {e}"))?;
    let out_path = out.join(format!("find_refs_{id}.txt"));
    fs::write(&out_path, &report).map_err(|e| format!("写 find_refs 失败: {e}"))?;
    println!(
        "引用 {id} 的条目 {} 个，报告写入 {}",
        refs.len(),
        out_path.display()
    );
    Ok(())
}

/// sample-field：对给定字段名或 token，抽样若干脱敏值。
fn cmd_sample_field(path: &Path, field: &str, limit: usize, out: &Path) -> Result<(), String> {
    let data = read_save_bytes(path)?;
    let (melted, _unknown) = melt_save(&data)?;
    let text = String::from_utf8_lossy(&melted);
    let lines: Vec<&str> = text.lines().collect();
    let mut samples: Vec<String> = Vec::new();
    let mut hit_chars = 0usize;
    walk_char_blocks(&lines, |cid, s, e| {
        let mut hit = false;
        for line in &lines[s..e] {
            if let Some((tok, rest)) = field_kv(line)
                && field_matches(&tok, field)
            {
                hit = true;
                if samples.len() < limit {
                    // classify_value 只输出值的类型/长度（字符串折叠为 str<N>），
                    // 从不输出原文，因此字符串字段同样可安全抽样。
                    samples.push(format!("char {cid}: {tok} -> {}", classify_value(rest)));
                }
            }
        }
        if hit {
            hit_chars += 1;
        }
    });
    let mut report =
        format!("字段 {field} 抽样（最多 {limit}）\n命中人物数: {hit_chars}\n\n样本:\n");
    for s in &samples {
        report.push_str(&format!("  {s}\n"));
    }
    fs::create_dir_all(out).map_err(|e| format!("创建调试目录失败: {e}"))?;
    let out_path = out.join(format!("sample_{field}.txt"));
    fs::write(&out_path, &report).map_err(|e| format!("写 sample_field 失败: {e}"))?;
    println!(
        "字段 {field}: 命中人物 {hit_chars}，抽样 {} 条，报告写入 {}",
        samples.len(),
        out_path.display()
    );
    Ok(())
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        usage();
    }
    let cmd = args[1].as_str();
    let path = Path::new(&args[2]);
    if !path.exists()
        && cmd != "meta"
        && cmd != "entities"
        && cmd != "titles"
        && cmd != "memories"
        && cmd != "characters"
        && cmd != "character"
    {
        eprintln!("文件不存在: {}", path.display());
        process::exit(1);
    }
    let result = match cmd {
        "prepare" => {
            let (_, _, _, with_melted) = parse_flags(&args[3..]);
            cmd_prepare(path, Path::new(&args[3]), with_melted)
        }
        "meta" => cmd_meta(path),
        "entities" => cmd_entities(path),
        "titles" => cmd_titles(path),
        "memories" => cmd_memories(path),
        "characters" => {
            let (offset, limit, query, _) = parse_flags(&args[3..]);
            cmd_characters(path, offset, limit, &query)
        }
        "character" => {
            if args.len() < 4 {
                eprintln!("character 子命令需要 <id>");
                process::exit(2);
            }
            cmd_character_cache(path, &args[3])
        }
        "inspect" => cmd_inspect(path),
        "list-mods" => cmd_list_mods(path),
        "list-characters" => cmd_list_characters(path),
        "character-json" => {
            if args.len() < 4 {
                eprintln!("character-json 子命令需要 <character-id>");
                process::exit(2);
            }
            cmd_character_json(path, &args[3])
        }
        "dump" => {
            if args.len() < 4 {
                eprintln!("dump 子命令需要 <out.txt>");
                process::exit(2);
            }
            cmd_dump(path, Path::new(&args[3]))
        }
        "inspect-character" => {
            if args.len() < 4 {
                eprintln!("inspect-character 需要 <character-id>");
                process::exit(2);
            }
            let mut rest: Vec<String> = args[3..].to_vec();
            let out = take_out_dir(&mut rest);
            cmd_inspect_character(path, &rest[0], &out)
        }
        "inspect-token" => {
            if args.len() < 4 {
                eprintln!("inspect-token 需要 <token>");
                process::exit(2);
            }
            let mut rest: Vec<String> = args[3..].to_vec();
            let out = take_out_dir(&mut rest);
            cmd_inspect_token(path, &rest[0], &out)
        }
        "find-references" => {
            if args.len() < 4 {
                eprintln!("find-references 需要 <character-id>");
                process::exit(2);
            }
            let mut rest: Vec<String> = args[3..].to_vec();
            let out = take_out_dir(&mut rest);
            cmd_find_references(path, &rest[0], &out)
        }
        "sample-field" => {
            if args.len() < 4 {
                eprintln!("sample-field 需要 <field-or-token>");
                process::exit(2);
            }
            let mut rest: Vec<String> = args[3..].to_vec();
            let out = take_out_dir(&mut rest);
            let limit = take_limit(&mut rest, 20);
            cmd_sample_field(path, &rest[0], limit, &out)
        }
        _ => {
            eprintln!("未知子命令: {cmd}");
            usage();
        }
    };
    if let Err(e) = result {
        eprintln!("ck3-reader 错误: {e}");
        process::exit(1);
    }
}

// ============================================================================
// 测试：M2 实体索引扫描器
// —— 直接用 melt 明文片段喂 scan_entities，验证容器定位 / key 形态 / 关联回填 /
// 缺失容器告警 / 字段省略(null) / 真实令牌表与占位令牌表双构建一致性。
// 这些测试不依赖真实存档，也不依赖 CK3_IRONMAN_TOKENS 环境变量。
// ============================================================================
#[cfg(test)]
mod tests {
    use super::*;

    /// 真实令牌表构建下的 melt 明文片段：容器键与字段键都是可读名。
    const SAMPLE_REAL: &str = r#"
traits_lookup={
  education_intrigue_1
  zhuge_ymbuff_01
}
religion={
  faiths={
    0={
      faith_type=orthodox
      tag=orthodox
    }
    1={
      faith_type=catholic
    }
  }
  religions={
    religion_christian={
      religion_type=christianity
      faiths={
        0
        1
      }
    }
  }
}
culture_manager={
  cultures={
    culture_swedish={
      culture_template=swedish
    }
    culture_hybrid={
      name=惠循
    }
  }
}
dynasties={
  dynasty_house={
    house_antioch={
      name=dynn_antioch
      prefix=dynnp_de
      dynasty=2
    }
    house_jerome={
      key=house_jerome_karling
      localized_name=安条克
      dynasty=5
    }
  }
  dynasties={
    2={
      key=2
    }
    dynn_capet={
      name=dynn_capet
    }
  }
}
landed_titles={
  landed_titles={
    e_byzantium={
      key=e_byzantium
      title_name_data={
        name=东罗马帝国
      }
    }
  }
}
wars={
  active_wars={
    war_123={
      name=声索吐蕃
      start_date=867.1.1
      casus_belli={
        type=cb_claim
      }
    }
  }
}
character_memory_manager={
  database={
    mem_1={
      type=became_soulmates
    }
  }
}
court_positions={
  database={
    cp_1={
      court_position=travel_leader_court_position
    }
  }
}
"#;

    /// 占位令牌表构建下的同一份片段：容器键与字段键都是 tXXXX，值保持不变。
    const SAMPLE_PLACEHOLDER: &str = r#"
t3561={
  education_intrigue_1
  zhuge_ymbuff_01
}
t27fc={
  t2f2c={
    0={
      t3e50=orthodox
      t27d8=orthodox
    }
    1={
      t3e50=catholic
    }
  }
  t2b29={
    religion_christian={
      t318b=christianity
      t2f2c={
        0
        1
      }
    }
  }
}
t2f92={
  t2d0a={
    culture_swedish={
      t2f93=swedish
    }
    culture_hybrid={
      t001b=惠循
    }
  }
}
t2a35={
  t2e5e={
    house_antioch={
      t001b=dynn_antioch
      t0ccd=dynnp_de
      t280e=2
    }
    house_jerome={
      t00dc=house_jerome_karling
      t0cd3=安条克
      t280e=5
    }
  }
  t2a35={
    2={
      t00dc=2
    }
    dynn_capet={
      t001b=dynn_capet
    }
  }
}
t27d6={
  t27d6={
    e_byzantium={
      t00dc=e_byzantium
      t3e40={
        t001b=东罗马帝国
      }
    }
  }
}
t2b3e={
  t2b3d={
    war_123={
      t001b=声索吐蕃
      t0cd5=867.1.1
      t289a={
        t00e1=cb_claim
      }
    }
  }
}
t3604={
  t05ab={
    mem_1={
      t00e1=became_soulmates
    }
  }
}
t368c={
  t05ab={
    cp_1={
      t3688=travel_leader_court_position
    }
  }
}
"#;

    fn scan(text: &str) -> EntitiesOutput {
        scan_entities(text)
    }

    #[test]
    fn traits_lookup_index_is_the_trait_id() {
        let out = scan(SAMPLE_REAL);
        let trait_kind = out.kinds.get("trait").expect("trait 索引应存在");
        assert_eq!(trait_kind.count, 2);
        assert_eq!(
            trait_kind.entries.get("0").and_then(|e| e.key.clone()),
            Some("education_intrigue_1".to_string())
        );
        // 末尾包含 Mod 自定义 trait，下标必为 1。
        assert_eq!(
            trait_kind.entries.get("1").and_then(|e| e.key.clone()),
            Some("zhuge_ymbuff_01".to_string())
        );
    }

    #[test]
    fn faith_and_religion_are_indexed_and_linked() {
        let out = scan(SAMPLE_REAL);
        let faiths = out.kinds.get("faith").expect("faith 索引应存在");
        assert_eq!(
            faiths.entries.get("0").and_then(|e| e.key.clone()),
            Some("orthodox".to_string())
        );
        assert_eq!(
            faiths.entries.get("1").and_then(|e| e.key.clone()),
            Some("catholic".to_string())
        );

        let religions = out.kinds.get("religion").expect("religion 索引应存在");
        assert_eq!(
            religions
                .entries
                .get("religion_christian")
                .and_then(|e| e.key.clone()),
            Some("christianity".to_string())
        );

        // religions.{id}.faiths 列表应反查回填 faith→religion 归属。
        assert_eq!(
            faiths.entries.get("0").and_then(|e| e.parent.clone()),
            Some("religion_christian".to_string())
        );
        assert_eq!(
            faiths.entries.get("1").and_then(|e| e.parent.clone()),
            Some("religion_christian".to_string())
        );
    }

    #[test]
    fn hybrid_culture_uses_save_name_not_a_template_key() {
        let out = scan(SAMPLE_REAL);
        let cultures = out.kinds.get("culture").expect("culture 索引应存在");
        // 静态定义文化：key 来自 culture_template。
        assert_eq!(
            cultures
                .entries
                .get("culture_swedish")
                .and_then(|e| e.key.clone()),
            Some("swedish".to_string())
        );
        assert_eq!(
            cultures
                .entries
                .get("culture_swedish")
                .and_then(|e| e.save_name.clone()),
            None
        );
        // 游戏内融合/分化文化：无 culture_template，只有已本地化的成品名 → save_name。
        let hybrid = cultures
            .entries
            .get("culture_hybrid")
            .expect("hybrid 文化应存在");
        assert_eq!(hybrid.save_name, Some("惠循".to_string()));
        assert_eq!(hybrid.key, None);
        // 有 save_name 即已可命名，不得算作 unnameable。
        assert_eq!(cultures.unresolved_key_count, 0);
    }

    #[test]
    fn houses_mix_loc_keys_def_keys_and_localized_names() {
        let out = scan(SAMPLE_REAL);
        let houses = out.kinds.get("house").expect("house 索引应存在");
        // 形态①：name=dynn_xxx（loc 键），key_kind 缺省（不序列化）。
        let antioch = houses
            .entries
            .get("house_antioch")
            .expect("house_antioch 应存在");
        assert_eq!(antioch.key, Some("dynn_antioch".to_string()));
        assert_eq!(antioch.key_kind, None);
        assert_eq!(antioch.prefix, Some("dynnp_de".to_string()));
        assert_eq!(antioch.parent, Some("2".to_string()));
        // 形态②：key=house_xxx（游戏定义键），key_kind="def"，另有成品名 localized_name。
        let jerome = houses
            .entries
            .get("house_jerome")
            .expect("house_jerome 应存在");
        assert_eq!(jerome.key, Some("house_jerome_karling".to_string()));
        assert_eq!(jerome.key_kind, Some("def".to_string()));
        assert_eq!(jerome.save_name, Some("安条克".to_string()));
        assert_eq!(jerome.parent, Some("5".to_string()));
    }

    #[test]
    fn dynasties_and_titles_are_indexed() {
        let out = scan(SAMPLE_REAL);
        let dynasties = out.kinds.get("dynasty").expect("dynasty 索引应存在");
        // 形态②：key="2"（游戏定义编号），key_kind="def"。
        let d2 = dynasties.entries.get("2").expect("dynasty 2 应存在");
        assert_eq!(d2.key, Some("2".to_string()));
        assert_eq!(d2.key_kind, Some("def".to_string()));
        // 形态①：name=dynn_capet（loc 键），key_kind 缺省。
        let capet = dynasties
            .entries
            .get("dynn_capet")
            .expect("dynasty capet 应存在");
        assert_eq!(capet.key, Some("dynn_capet".to_string()));
        assert_eq!(capet.key_kind, None);

        let titles = out.kinds.get("title").expect("title 索引应存在");
        let byz = titles
            .entries
            .get("e_byzantium")
            .expect("e_byzantium 应存在");
        assert_eq!(byz.key, Some("e_byzantium".to_string()));
        // 玩家自定义头衔名经 title_name_data 反查填入 save_name（已是可读文本）。
        assert_eq!(byz.save_name, Some("东罗马帝国".to_string()));
    }

    #[test]
    fn wars_memory_types_and_court_positions() {
        let out = scan(SAMPLE_REAL);
        let wars = out.kinds.get("war").expect("war 索引应存在");
        let w = wars.entries.get("war_123").expect("war_123 应存在");
        assert_eq!(w.save_name, Some("声索吐蕃".to_string()));
        assert_eq!(w.start_date, Some("867.1.1".to_string()));
        // 战争的 key 取 casus_belli.type。
        assert_eq!(w.key, Some("cb_claim".to_string()));

        let mem = out.kinds.get("memoryType").expect("memoryType 索引应存在");
        assert!(mem.entries.contains_key("became_soulmates"));
        let cp = out
            .kinds
            .get("courtPositionType")
            .expect("courtPositionType 索引应存在");
        assert!(cp.entries.contains_key("travel_leader_court_position"));
    }

    #[test]
    fn unnameable_entity_is_flagged_not_fabricated() {
        // 该 house 仅有父级 dynasty，既无 name/key 也无 localized_name → 无法命名。
        let text = r#"
dynasties={
  dynasty_house={
    house_ghost={
      dynasty=9
    }
  }
}
"#;
        let out = scan(text);
        let houses = out.kinds.get("house").expect("house 索引应存在");
        assert_eq!(houses.count, 1);
        assert_eq!(houses.unresolved_key_count, 1);
        let ghost = houses
            .entries
            .get("house_ghost")
            .expect("house_ghost 应存在");
        assert_eq!(ghost.key, None);
        assert_eq!(ghost.save_name, None);
    }

    #[test]
    fn placeholder_token_build_yields_the_same_index() {
        let real = scan(SAMPLE_REAL);
        let placeholder = scan(SAMPLE_PLACEHOLDER);
        assert_eq!(real.kinds.len(), placeholder.kinds.len());
        for (name, idx) in &real.kinds {
            let p = placeholder.kinds.get(name).expect("占位构建也应有同类索引");
            assert_eq!(idx.count, p.count, "类 {name} 条目数应一致");
            // 抽查 id 与内部键一致（值不受令牌表影响）。
            for (id, entry) in &idx.entries {
                assert_eq!(
                    entry.key,
                    p.entries.get(id).and_then(|e| e.key.clone()),
                    "类 {name} id {id} 内部键应一致"
                );
            }
        }
    }

    #[test]
    fn detect_token_source_placeholder_flags_partial_and_unresolved_enum() {
        // 占位全量表让 unknown_token_count=0，但 enum 字段仍为数字 id。
        let metrics = TokenMetrics {
            token_ids_seen: 10,
            placeholder_tokens_used: 5,
            semantic_fields_mapped: 0,
            unresolved_semantic_fields: vec![],
            version_specific_field_mappings: vec![],
        };
        let info = detect_token_source(&metrics);
        assert_eq!(info.kind, "placeholder");
        assert_eq!(info.compatibility, "partial");
        assert!(!info.enum_resolved, "占位表的 enum 未解析");
        assert!(
            !info.warnings.is_empty(),
            "占位表必须给出兼容性告警，提示 unknown_token_count=0 不表示已本地化"
        );
    }

    #[test]
    fn missing_container_is_reported_not_silently_empty() {
        let out = scan("");
        assert_eq!(out.kinds.len(), 10);
        for idx in out.kinds.values() {
            assert!(!idx.container_found, "空存档里所有容器都应报未找到");
        }
        assert_eq!(out.warnings.len(), 10);
        assert!(
            out.warnings
                .iter()
                .all(|w| w.contains("container_not_found"))
        );
    }

    #[test]
    fn entity_entry_omits_absent_fields_instead_of_writing_null() {
        let e = EntityEntry {
            key: Some("x".into()),
            ..Default::default()
        };
        let j = serde_json::to_string(&e).expect("序列化应成功");
        assert!(!j.contains("null"), "缺失字段不得写成 null，应直接省略");
        assert!(!j.contains("key_kind"));
        assert!(!j.contains("prefix"));
        assert!(!j.contains("parent"));
        assert!(!j.contains("save_name"));
        assert!(!j.contains("start_date"));
        assert!(j.contains("\"key\":\"x\""));
    }

    #[test]
    fn classify_container_routes_each_entity_kind() {
        assert_eq!(
            classify_container(&["religion".into(), "faiths".into()]),
            Some(EKind::Faith)
        );
        assert_eq!(
            classify_container(&["religion".into(), "religions".into()]),
            Some(EKind::Religion)
        );
        assert_eq!(
            classify_container(&["culture_manager".into(), "cultures".into()]),
            Some(EKind::Culture)
        );
        // 先判 house 再判 dynasty，防止串位。
        assert_eq!(
            classify_container(&["dynasties".into(), "dynasty_house".into()]),
            Some(EKind::House)
        );
        assert_eq!(
            classify_container(&["dynasties".into(), "dynasties".into()]),
            Some(EKind::Dynasty)
        );
        assert_eq!(
            classify_container(&["landed_titles".into(), "landed_titles".into()]),
            Some(EKind::Title)
        );
        assert_eq!(
            classify_container(&["wars".into(), "active_wars".into()]),
            Some(EKind::War)
        );
        assert_eq!(
            classify_container(&["character_memory_manager".into(), "database".into()]),
            Some(EKind::MemoryType)
        );
        assert_eq!(
            classify_container(&["court_positions".into(), "database".into()]),
            Some(EKind::CourtPositionType)
        );
        assert_eq!(classify_container(&["unknown".into(), "x".into()]), None);
    }

    // ========================================================================
    // 测试：M3 头衔与统治经历扫描器
    // —— 直接用 melt 明文片段喂 scan_titles，验证容器定位 / 头衔 key / 等级推导 /
    // 头衔名来源判定 / 当前持有者 / 宗主 / history 双格式(Format A: date=ID；
    // Format B: date={type=created/destroyed holder=ID}) / 按日期数值排序 /
    // 缺失容器告警。不依赖真实存档，也不依赖 CK3_IRONMAN_TOKENS 环境变量。
    // ========================================================================
    const SAMPLE_TITLES: &str = r#"
landed_titles={
  landed_titles={
    0={
      key="k_papal_state"
      holder=5371
      de_facto_liege=123
      date=752.3.22
      title_name_data={
        name="教宗国"
        adj="教宗国"
      }
      history={
        30.1.1=26
        64.10.13=38
        311.12.3={
          type=destroyed
        }
      }
    }
    1={
      key="e_byzantium"
      date=867.1.1
      title_name_data={
        name="东罗马帝国"
      }
      history={
        867.1.1=5371
        900.5.20={
          type=created
          holder=9999
        }
      }
    }
    2={
      key="h_roman_empire"
      title_name_data={
        name="罗马帝国"
      }
    }
  }
}
"#;

    #[test]
    fn scan_titles_finds_titles_and_derives_tier() {
        let out = scan_titles(SAMPLE_TITLES);
        assert!(out.warnings.is_empty(), "warnings: {:?}", out.warnings);
        assert_eq!(out.title_count, 3);
        let papal = out
            .titles
            .iter()
            .find(|t| t.key == "k_papal_state")
            .unwrap();
        assert_eq!(papal.tier, "kingdom");
        assert_eq!(papal.name, "教宗国");
        assert_eq!(papal.name_source, "save");
        assert_eq!(papal.holder_id.as_deref(), Some("5371"));
        assert_eq!(papal.de_facto_liege_id.as_deref(), Some("123"));
        let byz = out.titles.iter().find(|t| t.key == "e_byzantium").unwrap();
        assert_eq!(byz.tier, "empire");
        assert_eq!(byz.holder_id, None);
        assert_eq!(byz.de_facto_liege_id, None);
        // h_ 历史帝号按 empire 处理（最佳推断）
        let roman = out
            .titles
            .iter()
            .find(|t| t.key == "h_roman_empire")
            .unwrap();
        assert_eq!(roman.tier, "empire");
    }

    #[test]
    fn scan_titles_parses_history_format_a_and_b_sorted() {
        let out = scan_titles(SAMPLE_TITLES);
        let papal = out
            .titles
            .iter()
            .find(|t| t.key == "k_papal_state")
            .unwrap();
        // Format A: 30.1.1=26, 64.10.13=38 ；Format B: 311.12.3 destroyed
        assert_eq!(papal.history.len(), 3);
        assert_eq!(papal.history[0].date, "30.1.1");
        assert_eq!(papal.history[0].holder_id.as_deref(), Some("26"));
        assert_eq!(papal.history[0].kind, "holder");
        assert_eq!(papal.history[1].date, "64.10.13");
        assert_eq!(papal.history[1].holder_id.as_deref(), Some("38"));
        assert_eq!(papal.history[1].kind, "holder");
        // 已按日期数值排序：311.12.3 在最后（destroyed 无 holder）
        assert_eq!(papal.history[2].date, "311.12.3");
        assert_eq!(papal.history[2].kind, "destroyed");
        assert_eq!(papal.history[2].holder_id, None);

        let byz = out.titles.iter().find(|t| t.key == "e_byzantium").unwrap();
        // 867.1.1=5371 (A) 在前，900.5.20 created (B) 在后
        assert_eq!(byz.history.len(), 2);
        assert_eq!(byz.history[0].date, "867.1.1");
        assert_eq!(byz.history[0].kind, "holder");
        assert_eq!(byz.history[1].date, "900.5.20");
        assert_eq!(byz.history[1].kind, "created");
        assert_eq!(byz.history[1].holder_id.as_deref(), Some("9999"));
    }

    #[test]
    fn scan_titles_name_source_key_when_unlocalized() {
        let sample = r#"
landed_titles={
  landed_titles={
    0={
      key="c_rome"
      title_name_data={
        name=c_rome
      }
    }
  }
}
"#;
        let out = scan_titles(sample);
        let t = &out.titles[0];
        assert_eq!(t.name_source, "key");
        assert_eq!(t.tier, "county");
    }

    #[test]
    fn scan_titles_warns_when_container_missing() {
        let out = scan_titles("version=1.19.0.6\ncharacter_database={ }");
        assert_eq!(out.title_count, 0);
        assert!(
            out.warnings
                .iter()
                .any(|w| w.contains("container_not_found"))
        );
    }

    // ========================================================================
    // 测试：M4 记忆扫描器
    // —— 直接用 melt 明文片段喂 scan_memories，验证容器定位 / 条目 id（全局计数器、
    // 非连续、含 none 槽位）/ participants 多角色 / 日期 / battle_location 提取 /
    // 无日期容忍 / 占位 token 形态 / 缺失容器告警。不依赖真实存档。
    // ========================================================================
    const SAMPLE_MEMORIES: &str = r#"
character_memory_manager={
  database={
    0={
      type="became_soulmates"
      participants={
        new_soulmate=6039
      }
      creation_date=735.1.1
      end_date=890.1.1
    }
    16777233={
      type="battle_won_memory"
      participants={
        loser=10433
        ruler=10433
      }
      creation_date=757.2.18
      end_date=887.2.18
      variables={
        data={
          {
            flag="battle_location"
            data={
              type=prov
              identity=6473
            }
          }
        }
      }
    }
    28674=none
    28675={
      type="friend_died"
      participants={
        dead_relation=16785898
      }
    }
  }
}
"#;

    #[test]
    fn scan_memories_parses_entries_participants_dates_and_battle_location() {
        let out = scan_memories(SAMPLE_MEMORIES);
        assert!(out.warnings.is_empty(), "warnings: {:?}", out.warnings);
        // none 槽位 28674 被跳过，共 3 条有效记忆。
        assert_eq!(out.memory_count, 3);
        assert_eq!(out.memories.len(), 3);

        let soulmate = out
            .memories
            .iter()
            .find(|m| m.id == "0")
            .expect("entry 0 present");
        assert_eq!(soulmate.memory_type, "became_soulmates");
        assert_eq!(soulmate.creation_date.as_deref(), Some("735.1.1"));
        assert_eq!(soulmate.end_date.as_deref(), Some("890.1.1"));
        assert_eq!(soulmate.battle_location_id, None);
        assert_eq!(soulmate.participants.len(), 1);
        assert_eq!(soulmate.participants[0].role, "new_soulmate");
        assert_eq!(soulmate.participants[0].character_id, "6039");

        let battle = out
            .memories
            .iter()
            .find(|m| m.id == "16777233")
            .expect("battle entry present");
        assert_eq!(battle.memory_type, "battle_won_memory");
        // 多角色：loser 与 ruler 指向同一人，两个都保留（不合并）。
        assert_eq!(battle.participants.len(), 2);
        assert_eq!(battle.participants[0].role, "loser");
        assert_eq!(battle.participants[1].role, "ruler");
        assert_eq!(battle.participants[0].character_id, "10433");
        assert_eq!(battle.battle_location_id.as_deref(), Some("6473"));
    }

    #[test]
    fn scan_memories_tolerates_missing_dates() {
        let out = scan_memories(SAMPLE_MEMORIES);
        let died = out
            .memories
            .iter()
            .find(|m| m.id == "28675")
            .expect("entry 28675 present");
        assert_eq!(died.memory_type, "friend_died");
        assert_eq!(died.creation_date, None);
        assert_eq!(died.end_date, None);
        assert_eq!(died.participants[0].role, "dead_relation");
        assert_eq!(died.participants[0].character_id, "16785898");
    }

    #[test]
    fn scan_memories_warns_when_container_missing() {
        let out = scan_memories("version=1.19.0.6\ncharacter_database={ }");
        assert_eq!(out.memory_count, 0);
        assert!(
            out.warnings
                .iter()
                .any(|w| w.contains("container_not_found"))
        );
    }

    #[test]
    fn scan_memories_handles_placeholder_token_container() {
        let sample = r#"
t3604={
  t05ab={
    5={
      t00e1="became_friends"
      t282a={
        new_relation=7083
      }
      t347b=736.1.1
      t0cd6=891.1.1
    }
  }
}
"#;
        let out = scan_memories(sample);
        assert!(out.warnings.is_empty(), "warnings: {:?}", out.warnings);
        assert_eq!(out.memory_count, 1);
        let m = &out.memories[0];
        assert_eq!(m.id, "5");
        assert_eq!(m.memory_type, "became_friends");
        assert_eq!(m.participants[0].role, "new_relation");
        assert_eq!(m.creation_date.as_deref(), Some("736.1.1"));
        assert_eq!(m.end_date.as_deref(), Some("891.1.1"));
    }

    // -- SAV0102 明文存档（kind 0 Text / kind 2 UnifiedText）-----------------

    /// 构造存档头：SAV + unknown + kind + random + meta_len(hex) + \n。
    fn text_header(kind: u16, meta_len: u32) -> Vec<u8> {
        let mut h = Vec::new();
        h.extend_from_slice(b"SAV01");
        h.extend_from_slice(format!("{kind:02x}").as_bytes());
        h.extend_from_slice(b"12345678");
        h.extend_from_slice(format!("{meta_len:08x}").as_bytes());
        h.push(b'\n');
        h
    }

    /// 合成明文 gamestate（与 melt 产物同构：meta + character 容器）。
    fn sample_gamestate_text() -> String {
        format!(
            "{}\n{}",
            "meta_data={\n\tsave_game_version=15\n\tversion=\"1.19.0.6\"\n\tmeta_date=956.12.28\n\tmeta_player_name=\"梁克贞\"\n}",
            "character={\n\tliving={\n\t\t1={\n\t\t\tfirst_name=\"大悟\"\n\t\t\tbirth=900.1.1\n\t\t\tfemale=yes\n\t\t\tfamily_data={\n\t\t\t\tchild={ 20423 90 }\n\t\t\t}\n\t\t}\n\t\t20423={\n\t\t\tfirst_name=\"克贞\"\n\t\t\tbirth=890.1.1\n\t\t\tdynasty_house=11527\n\t\t\tfamily_data={\n\t\t\t\tspouse=2\n\t\t\t\tchild={ 3 4 5 }\n\t\t\t\tformer_spouses={ 11 12 }\n\t\t\t}\n\t\t}\n\t}\n\tdead_unprunable={\n\t\t2={\n\t\t\tfirst_name=\"埃尔薇拉\"\n\t\t\tbirth=1.6.2\n\t\t\tdeath=31.8.26\n\t\t\tdead_data={\n\t\t\t\tdate=31.8.26\n\t\t\t\treason=\"death_disease\"\n\t\t\t\tkiller=20423\n\t\t\t\tliege=7\n\t\t\t}\n\t\t}\n\t}\n}"
        )
    }

    #[test]
    fn save_kind_detects_header_kind() {
        assert_eq!(save_kind(b"SAV0101abcdefgh0000000c\n").unwrap(), 1);
        assert_eq!(save_kind(b"SAV0100abcdefgh0000000c\n").unwrap(), 0);
        assert_eq!(save_kind(b"SAV0102abcdefgh0000a324\n").unwrap(), 2);
        assert_eq!(save_kind(b"SAV0103abcdefgh0000a324\n").unwrap(), 3);
        assert!(save_kind(b"SAV").is_err());
    }

    #[test]
    fn melt_save_kind0_text_passes_through() {
        // kind 0（Text）：完全明文，无需解压。
        let text = sample_gamestate_text();
        let mut save = text_header(0, 0);
        save.extend_from_slice(text.as_bytes());
        let save_as_text = String::from_utf8_lossy(&save).to_string();
        let (melted, unknown) = melt_save(&save).expect("kind0 明文应直接通过");
        assert_eq!(unknown, 0);
        // 输出 = 头 + 完整明文（与 melt 产物结构一致）。
        assert_eq!(String::from_utf8_lossy(&melted), save_as_text);
    }

    #[test]
    fn melt_save_kind2_unified_text_inflates_gamestate() {
        use std::io::Write;
        // kind 2（UnifiedText）：明文 meta + raw-deflate 压缩的完整 gamestate。
        let text = sample_gamestate_text();
        let mut enc = flate2::write::DeflateEncoder::new(Vec::new(), flate2::Compression::default());
        enc.write_all(text.as_bytes()).unwrap();
        let compressed = enc.finish().unwrap();

        let meta = "meta_data={\n\tsave_game_version=15\n\tversion=\"1.19.0.6\"\n}";
        let mut save = text_header(2, meta.len() as u32);
        save.extend_from_slice(meta.as_bytes());
        save.extend_from_slice(b"\n");
        save.extend_from_slice(b"gamestate");
        save.extend_from_slice(&compressed);

        let (melted, unknown) = melt_save(&save).expect("kind2 明文应解压成功");
        assert_eq!(unknown, 0);
        // 解压结果 = 头 + 完整 gamestate（meta 被解压块包含）。
        let full = String::from_utf8_lossy(&melted);
        assert!(full.contains("meta_player_name=\"梁克贞\""), "应含 meta：{full}");
        assert!(full.contains("first_name=\"克贞\""), "应含人物：{full}");
        assert!(full.contains("dynasty_house=11527"));
    }

    #[test]
    fn cmd_prepare_on_plain_text_save_builds_cache() {
        use std::io::Write;
        // 端到端：明文（kind 2）走 cmd_prepare 全流程，缓存产物可被 meta/characters 读取。
        let text = sample_gamestate_text();
        let mut enc = flate2::write::DeflateEncoder::new(Vec::new(), flate2::Compression::default());
        enc.write_all(text.as_bytes()).unwrap();
        let compressed = enc.finish().unwrap();
        let meta = "meta_data={\n\tsave_game_version=15\n\tversion=\"1.19.0.6\"\n}";
        let mut save = text_header(2, meta.len() as u32);
        save.extend_from_slice(meta.as_bytes());
        save.extend_from_slice(b"\ngamestate");
        save.extend_from_slice(&compressed);

        let tmp = std::env::temp_dir().join(format!("ck3r_plain_{}", std::process::id()));
        let save_path = tmp.join("plain.ck3");
        let cache_dir = tmp.join("cache");
        fs::create_dir_all(&tmp).unwrap();
        fs::write(&save_path, &save).unwrap();
        cmd_prepare(&save_path, &cache_dir, false).expect("prepare 明文存档应成功");

        // meta.json：encoding 为 Text，player 名可读，字符计数正确（2 活 + 1 死）。
        let meta_json: serde_json::Value = {
            let raw = fs::read_to_string(cache_dir.join("meta.json")).unwrap();
            serde_json::from_str(&raw).unwrap()
        };
        assert_eq!(meta_json["character_count"], 3);
        assert_eq!(meta_json["dead_character_count"], 1);
        assert_eq!(meta_json["player_name"], "梁克贞");
        assert_eq!(meta_json["encoding"], "Text");
        assert_eq!(meta_json["unknown_token_count"], 0);

        // characters.ndjson：含 3 人，姓名字段可读；dead_data 的 liege 被扫出。
        let ndjson = fs::read_to_string(cache_dir.join("characters.ndjson")).unwrap();
        let lines: Vec<&str> = ndjson.lines().collect();
        assert_eq!(lines.len(), 3);
        assert!(ndjson.contains("克贞"), "人物名应可读：{ndjson}");
        let dead_line = lines.iter().find(|l| l.contains("\"id\":\"2\"")).expect("含死者记录");
        assert!(
            dead_line.contains("\"liege\":\"7\""),
            "dead_data.liege 应被扫出：{dead_line}"
        );
        // 2C.1 修复：family_data 内单行花括号列表（child={ 3 4 5 }）必须被收集。
        let live_line = lines
            .iter()
            .find(|l| l.contains("\"id\":\"20423\""))
            .expect("含玩家记录");
        assert!(
            live_line.contains("\"children\":[\"3\",\"4\",\"5\"]"),
            "family_data 单行 child 列表应被收集：{live_line}"
        );
        assert!(
            live_line.contains("\"former_spouses\":[\"11\",\"12\"]"),
            "单行 former_spouses 应被收集：{live_line}"
        );
        assert!(
            live_line.contains("\"spouses\":[\"2\"]"),
            "单行 spouse 应被收集：{live_line}"
        );
        // 父系反推：角色 1（大悟，female=yes）的 child 列表含 20423 → 20423.mother=1。
        let grand_line = lines
            .iter()
            .find(|l| l.contains("\"id\":\"1\""))
            .expect("含大悟记录");
        assert!(
            grand_line.contains("\"children\":[\"20423\",\"90\"]"),
            "角色1 的 child 列表应被收集：{grand_line}"
        );
        assert!(
            live_line.contains("\"mother\":\"1\""),
            "由 child 反推 mother：{live_line}"
        );
        fs::remove_dir_all(&tmp).ok();
    }
}
