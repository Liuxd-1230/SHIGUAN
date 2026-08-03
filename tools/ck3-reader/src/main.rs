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
use std::path::Path;
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
const ROOT: &str = "t3155"; // gamestate 根
const K_SAVE_VERSION: &[&str] = &["save_version", "t058f"];
const K_GAME_VERSION: &[&str] = &["version", "t00ee"];
const K_DATE: &[&str] = &["date", "t3157"];
const K_PLAYER_NAME: &[&str] = &["player_name", "t29e6"];
const K_MODS: &str = "t32c1"; // Mod descriptor 数组容器
const K_CHARACTERS: &str = "t2ce6"; // 人物容器（数字 id 键）
const K_NAME: &[&str] = &["name", "t2755"];
const K_BIRTH: &[&str] = &["birth", "t27e9"];
const K_DEATH: &[&str] = &["death", "t2c68"]; // 有值=死亡日期；缺失或 9999.1.1=存活
const K_CULTURE: &[&str] = &["culture", "t3b12"];
const K_FAITH: &[&str] = &["faith", "t2f2b"];
const K_DYNASTY: &[&str] = &["dynasty", "t2e5e"];
const ALIVE_SENTINEL: &str = "9999.1.1";

// 验证过的字段 token 映射（用于 Token 指标 version_specific_field_mappings）。
const FIELD_MAPPINGS: &[(&str, &str)] = &[
    ("save_version", "t058f"),
    ("game_version", "t00ee"),
    ("date", "t3157"),
    ("player_name", "t29e6"),
    ("mods", "t32c1"),
    ("characters", "t2ce6"),
    ("name", "t2755"),
    ("birth", "t27e9"),
    ("death", "t2c68"),
    ("culture", "t3b12"),
    ("faith", "t2f2b"),
    ("dynasty", "t2e5e"),
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

/// 单人物在缓存 / melt 明文中的完整记录（Phase 2A.1 扩展）。
/// 字面可提取字段：father/mother/spouse/child/trait_/female/male/ruler。
/// 需要真实 token 表才能转可读名的枚举值（faith/dynasty）保留原始 id 并标记 unresolved。
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
}

impl CharacterRecord {
    fn alive_from_death(death: &Option<String>) -> bool {
        match death {
            None => true,
            Some(d) => d == ALIVE_SENTINEL,
        }
    }

    fn new(id: String) -> Self {
        CharacterRecord {
            id,
            name: None,
            birth: None,
            death: None,
            alive: true,
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
            // faith/dynasty 在占位 token 表下为数字 id，非可读名 → 明确标记 unresolved。
            // primary_title（头衔）在占位表下被 token 化且无 id → 无法提取。
            evidence_warnings: vec!["faith".into(), "dynasty".into(), "primary_title".into()],
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

/// 提取字面键字段（father=/mother=/female=yes/male=yes/ruler=yes 等）。
/// 返回 (father, mother, sex, ruler)。
fn extract_literal_scalars(line: &str) -> (Option<String>, Option<String>, Option<String>, bool) {
    let mut father = None;
    let mut mother = None;
    let mut sex = None;
    let mut ruler = false;
    let t = line.trim_start();
    if let Some(rest) = t.strip_prefix("father=") {
        father = Some(first_token(rest));
    }
    if let Some(rest) = t.strip_prefix("mother=") {
        mother = Some(first_token(rest));
    }
    if t == "female=yes" || t.starts_with("female=yes") {
        sex = Some("female".into());
    } else if t == "male=yes" || t.starts_with("male=yes") {
        sex = Some("male".into());
    }
    if t == "ruler=yes" || t.starts_with("ruler=yes") {
        ruler = true;
    }
    (father, mother, sex, ruler)
}

fn first_token(s: &str) -> String {
    s.split(|c: char| c.is_whitespace() || c == '{' || c == '}')
        .next()
        .unwrap_or("")
        .to_string()
}

/// 在一行里收集 trait_XXX=yes 形式的特质键（XXX 为字面字符串）。
fn extract_traits(line: &str, out: &mut Vec<String>) {
    let t = line.trim_start();
    if let Some(rest) = t.strip_prefix("trait_") {
        // trait_genius=yes / trait_X={...}
        let key: String = rest
            .chars()
            .take_while(|c| *c != '=' && *c != ' ' && *c != '{' && *c != '\t')
            .collect();
        if !key.is_empty()
            && (rest.starts_with(&format!("{key}=")) || rest.starts_with(&format!("{key}{{")))
        {
            out.push(key);
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

        if !in_root && line.contains(&format!("{ROOT}={{")) {
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
            if line.contains(&format!("{K_MODS}={{")) {
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

/// 完整扫描人物容器：统计总数/死亡数，并提取每个角色的完整记录（含字面可提取字段）。
fn scan_characters_full(text: &str) -> (usize, usize, Vec<CharacterRecord>) {
    let mut depth: i64 = 0;
    let mut in_chars = false;
    let mut char_base: i64 = 0;
    let mut count = 0usize;
    let mut dead = 0usize;
    let mut records: Vec<CharacterRecord> = Vec::new();
    let mut cur: Option<CharacterRecord> = None;

    // 列表字段收集状态（spouse=/child= 可能是 { id id } 形式）。
    let mut collecting: Option<&str> = None;

    for line in text.lines() {
        let opens = line.matches('{').count() as i64;
        let closes = line.matches('}').count() as i64;

        if !in_chars && line.contains(&format!("{K_CHARACTERS}={{")) {
            in_chars = true;
            char_base = depth;
        }
        if in_chars {
            let child_depth = char_base + 1; // 数字 id 条目
            let field_depth = char_base + 2; // 条目内的字段

            if depth == child_depth
                && let Some(id) = capture_id_entry(line)
            {
                if let Some(c) = cur.take() {
                    if !c.alive {
                        dead += 1;
                    }
                    records.push(c);
                }
                count += 1;
                cur = Some(CharacterRecord::new(id));
            }
            if depth == field_depth
                && let Some(c) = cur.as_mut()
            {
                if c.name.is_none() {
                    c.name = extract_field(line, K_NAME);
                }
                if c.birth.is_none() {
                    c.birth = extract_field(line, K_BIRTH);
                }
                if c.death.is_none() {
                    c.death = extract_field(line, K_DEATH);
                    c.alive = CharacterRecord::alive_from_death(&c.death);
                }
                if c.culture.is_none() {
                    c.culture = extract_field(line, K_CULTURE);
                }
                if c.faith.is_none() {
                    c.faith = extract_field(line, K_FAITH);
                }
                if c.dynasty.is_none() {
                    c.dynasty = extract_field(line, K_DYNASTY);
                }
                let (father, mother, sex, ruler) = extract_literal_scalars(line);
                if father.is_some() {
                    c.father = father;
                }
                if mother.is_some() {
                    c.mother = mother;
                }
                if sex.is_some() {
                    c.sex = sex;
                }
                if ruler {
                    c.ruler = true;
                }
                extract_traits(line, &mut c.traits);
                // spouse=/child= 标量形式
                let t = line.trim_start();
                if let Some(rest) = t.strip_prefix("spouse=") {
                    let tok = first_token(rest);
                    if !tok.is_empty() && !rest.trim_start().starts_with('{') {
                        c.spouses.push(tok);
                    } else if rest.trim_start().starts_with('{') {
                        collecting = Some("spouse");
                    }
                }
                if let Some(rest) = t.strip_prefix("child=") {
                    let tok = first_token(rest);
                    if !tok.is_empty() && !rest.trim_start().starts_with('{') {
                        c.children.push(tok);
                    } else if rest.trim_start().starts_with('{') {
                        collecting = Some("child");
                    }
                }
            }
            // 列表字段收集：在列表容器内（depth > field_depth）收集裸 id token。
            if collecting.is_some() && depth > field_depth {
                for tok in bare_id_tokens(line) {
                    if let Some(c) = cur.as_mut() {
                        match collecting {
                            Some("spouse") => c.spouses.push(tok),
                            Some("child") => c.children.push(tok),
                            _ => {}
                        }
                    }
                }
            }
        }

        let new_depth = depth + opens - closes;
        if in_chars && new_depth <= char_base {
            in_chars = false;
            collecting = None;
            if let Some(c) = cur.take() {
                if !c.alive {
                    dead += 1;
                }
                records.push(c);
            }
        }
        // 列表收集结束：深度回落到 field_depth。
        if collecting.is_some() && new_depth <= char_base + 2 {
            collecting = None;
        }
        depth = new_depth;
        if depth < 0 {
            depth = 0;
        }
    }
    if let Some(c) = cur.take() {
        if !c.alive {
            dead += 1;
        }
        records.push(c);
    }
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
        "用法: ck3-reader <prepare|meta|characters|character|inspect|list-mods|list-characters|character-json|dump> <args...>"
    );
    process::exit(2);
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
