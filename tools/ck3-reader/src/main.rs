//! ck3-reader — SHIGUAN 本地 CK3 存档读取 helper（Rust sidecar）。
//!
//! 通过 subprocess 被 FastAPI 调用；向 stdout 输出版本化 JSON。
//!
//! 子命令（Phase 2A.1）：
//!   prepare <save.ck3> <cache-dir> [--with-melted]
//!       一次 melt，把受控索引产物写到 cache-dir（meta/mods/characters.ndjson/
//!       character-offsets/manifest），后续查询全部走缓存，不再重新 melt。
//!   meta <cache-dir>            读取 meta.json（版本/日期/玩家/Mod/计数/Token 指标）。
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

use std::collections::HashSet;
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

// —— dead_data 子块（存在即代表已死亡）——
const K_DEAD_DATA: &[&str] = &["dead_data", "t2750"];
const K_DEATH_DATE: &[&str] = &["date", "t06b5"];
const K_DEATH_REASON: &[&str] = &["reason", "t2b64"];
const K_KILLER: &[&str] = &["killer", "t2766"];

// —— 统治判定 ——
const K_LANDED_DATA: &[&str] = &["landed_data", "t2753"];

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

/// melt 二进制存档为明文。返回 (明文, 未知 token 数)。
fn melt_save(data: &[u8]) -> Result<(Vec<u8>, usize), String> {
    let file = Ck3File::from_slice(data).map_err(|e| format!("Ck3File::from_slice 失败: {e}"))?;
    let mut zip_sink: Vec<u8> = Vec::new();
    let parsed = file
        .parse(&mut zip_sink)
        .map_err(|e| format!("parse 失败: {e}"))?;
    let binary = parsed
        .as_binary()
        .ok_or_else(|| "存档不是二进制格式（预期 SAV0101 二进制）".to_string())?;
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

/// 从一行中按候选键提取字段值（先尝试带引号字符串，再尝试裸 token/数字/日期）。
fn extract_field(line: &str, keys: &[&str]) -> Option<String> {
    for k in keys {
        let pat = format!("{k}=");
        if let Some(idx) = line.find(&pat) {
            let rest = &line[idx + pat.len()..];
            if let Some(stripped) = rest.strip_prefix('"')
                && let Some(end) = stripped.find('"')
            {
                return Some(stripped[..end].to_string());
            }
            let v: String = rest
                .chars()
                .take_while(|c| !c.is_whitespace() && *c != '}' && *c != '{')
                .collect();
            if !v.is_empty() {
                return Some(v);
            }
        }
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
                    }
                } else if sub == Some(SubBlock::Family) && depth == sub_depth + 1 {
                    // —— family_data 内 ——
                    if line_opens_key(t, K_CHILD) {
                        list = Some(ListKind::Child);
                        list_depth = depth;
                    } else if line_opens_key(t, K_SPOUSE) {
                        list = Some(ListKind::Spouse);
                        list_depth = depth;
                    } else {
                        if let Some(v) = extract_kv(t, K_CHILD) {
                            c.children.push(v);
                        }
                        if let Some(v) = extract_kv(t, K_SPOUSE) {
                            c.spouses.push(v);
                        }
                        if c.primary_spouse.is_none() {
                            c.primary_spouse = extract_kv(t, K_PRIMARY_SPOUSE);
                        }
                        if c.real_father.is_none()
                            && let Some(v) = extract_kv(t, K_REAL_FATHER)
                        {
                            c.real_father = Some(v);
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

    fs::create_dir_all(cache_dir).map_err(|e| format!("创建缓存目录失败: {e}"))?;

    // meta.json
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
    };
    write_json(cache_dir.join("meta.json"), &meta)?;
    write_json(
        cache_dir.join("mods.json"),
        &serde_json::json!({ "mod_count": mods.len(), "mods": mods }),
    )?;

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
        melted_bytes: melted.len(),
    };
    write_json(cache_dir.join("manifest.json"), &manifest)?;

    if with_melted {
        fs::write(cache_dir.join("melted.txt"), &melted)
            .map_err(|e| format!("写 melted 失败: {e}"))?;
    }

    eprintln!(
        "prepare 完成: {} 人物, {} 字节 melt, {:.0}ms",
        character_count,
        melted.len(),
        meta.parse_ms
    );
    Ok(())
}

fn write_json<P: AsRef<Path>, T: Serialize>(path: P, v: &T) -> Result<(), String> {
    let mut f = fs::File::create(path).map_err(|e| format!("写 JSON 失败: {e}"))?;
    serde_json::to_writer_pretty(&mut f, v).map_err(|e| e.to_string())?;
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
        "用法: ck3-reader <prepare|meta|characters|character|inspect|list-mods|list-characters|character-json|dump|inspect-character|inspect-token|find-references|sample-field> <args...>"
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
    if !path.exists() && cmd != "meta" && cmd != "characters" && cmd != "character" {
        eprintln!("文件不存在: {}", path.display());
        process::exit(1);
    }
    let result = match cmd {
        "prepare" => {
            let (_, _, _, with_melted) = parse_flags(&args[3..]);
            cmd_prepare(path, Path::new(&args[3]), with_melted)
        }
        "meta" => cmd_meta(path),
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
