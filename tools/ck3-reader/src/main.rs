//! ck3-reader — SHIGUAN 本地 CK3 存档读取 helper（Rust sidecar）。
//!
//! 通过 subprocess 被 FastAPI 调用；向 stdout 输出版本化 JSON。
//! 子命令：
//!   inspect <save.ck3>            编码/游戏版本/日期/玩家/Mod 列表/存活人物数/样本
//!   list-mods <save.ck3>          仅 Mod descriptor 列表（快速）
//!   list-characters <save.ck3>    人物摘要索引（id/name/birth/death/culture/faith/dynasty）
//!   character <save.ck3> <id>     单个人物的原始文本块（来自 melt 明文）
//!   dump <save.ck3> <out.txt>     把 melt 明文整体写入文件（调试）
//!
//! 解析设计（经 Spike 实测确定，CK3 1.19.0.6）：
//! - ck3save 检测编码并 melt（二进制→明文）。melt 需要的"token 表"我们提交一份
//!   **占位全量表** `tokens/ck3_tokens.txt`（65536 条 id -> tXXXX，由构建脚本生成，
//!   不依赖游戏安装），确保任何二进制存档都能完整 melt（实测 87MB / 1100 万 token），
//!   未知 key 由 FailedResolveStrategy::Ignore 跳过，不会崩溃。
//! - 解析只依赖 **token id**（稳定），不依赖可读名。下面 FIELD_TOKENS 把
//!   关键语义字段映射到我们在实测中反推出的 token-id（十六进制，如 t00ee=version）。
//! - 若用户后续用 rakaly 从 Ck3.exe 导出真实 token 表（id->可读名），melt 会输出
//!   真实名（如 `version`、`character`）；届时把 FIELD_TOKENS 的候选键补上真实名即可
//!   （每字段已经是 [真实名, 占位id] 双候选，无需改解析逻辑）。

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
    sample_characters: Vec<CharacterStub>,
    unknown_token_count: usize,
    header_parse_ok: bool,
    melted_bytes: usize,
    parse_ms: f64,
}

#[derive(Serialize)]
struct CharacterStub {
    id: String,
    name: Option<String>,
    birth: Option<String>,
    death: Option<String>,
    alive: bool,
    culture: Option<String>,
    faith: Option<String>,
    dynasty: Option<String>,
}

/// 单个角色在 melt 明文中的字段收集（内部用）。
struct CharFields {
    id: String,
    name: Option<String>,
    birth: Option<String>,
    death: Option<String>,
    culture: Option<String>,
    faith: Option<String>,
    dynasty: Option<String>,
}

impl CharFields {
    fn alive(&self) -> bool {
        match &self.death {
            None => true,
            Some(d) => d == ALIVE_SENTINEL,
        }
    }
    fn to_stub(&self) -> CharacterStub {
        CharacterStub {
            id: self.id.clone(),
            name: self.name.clone(),
            birth: self.birth.clone(),
            death: self.death.clone(),
            alive: self.alive(),
            culture: self.culture.clone(),
            faith: self.faith.clone(),
            dynasty: self.dynasty.clone(),
        }
    }
}

fn read_save_bytes(path: &Path) -> Result<Vec<u8>, String> {
    fs::read(path).map_err(|e| format!("无法读取存档 {}: {}", path.display(), e))
}

/// 验证 ck3save 能否解析存档头（typed 路径是否可用）。仅作信号，不序列化。
fn try_parse_metadata(data: &[u8]) -> bool {
    if let Ok(file) = Ck3File::from_slice(data) {
        if let Ok(meta) = file.parse_metadata() {
            return meta.deserializer().build::<HeaderOwned, _>(&EnvTokens).is_ok();
        }
    }
    false
}

/// melt 二进制存档为明文。返回 (明文, 未知 token 数)。
fn melt_save(data: &[u8]) -> Result<(Vec<u8>, usize), String> {
    let file =
        Ck3File::from_slice(data).map_err(|e| format!("Ck3File::from_slice 失败: {e}"))?;
    let mut zip_sink: Vec<u8> = Vec::new();
    let parsed = file.parse(&mut zip_sink).map_err(|e| format!("parse 失败: {e}"))?;
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

/// 从一行中按候选键提取字段值（先尝试带引号字符串，再尝试裸 token/数字/日期）。
fn extract_field(line: &str, keys: &[&str]) -> Option<String> {
    for k in keys {
        let pat = format!("{k}=");
        if let Some(idx) = line.find(&pat) {
            let rest = &line[idx + pat.len()..];
            if let Some(stripped) = rest.strip_prefix('"') {
                if let Some(end) = stripped.find('"') {
                    return Some(stripped[..end].to_string());
                }
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
/// 这些都集中在 gamestate 顶部（root 之后几十行内），扫到即停，避免全文件扫描。
fn scan_meta(
    text: &str,
) -> (
    Option<String>,
    Option<String>,
    Option<String>,
    Option<String>,
    Vec<String>,
) {
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
        // 退出 mods 容器：深度回落到 root 直接子级（1）。
        if in_mods && new_depth <= 1 {
            in_mods = false;
        }
        depth = new_depth;
        if depth < 0 {
            depth = 0;
        }

        // 早期退出：四项元数据 + mods 已收集且离开了 mods 容器。
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

/// 扫描人物容器：统计总数、死亡数并采样前 N 个摘要。
fn scan_characters(text: &str, sample_limit: usize) -> (usize, usize, Vec<CharacterStub>) {
    let mut depth: i64 = 0;
    let mut in_chars = false;
    let mut char_base: i64 = 0; // t2ce6 父级深度
    let mut count = 0usize;
    let mut dead = 0usize;
    let mut samples: Vec<CharacterStub> = Vec::new();
    let mut cur: Option<CharFields> = None;

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

            if depth == child_depth {
                if let Some(id) = capture_id_entry(line) {
                    // 收尾上一个角色
                    if let Some(c) = cur.take() {
                        if c.alive() {
                            // 存活
                        } else {
                            dead += 1;
                        }
                        if samples.len() < sample_limit {
                            samples.push(c.to_stub());
                        }
                    }
                    count += 1;
                    cur = Some(CharFields {
                        id,
                        name: None,
                        birth: None,
                        death: None,
                        culture: None,
                        faith: None,
                        dynasty: None,
                    });
                }
            }
            if depth == field_depth {
                if let Some(c) = cur.as_mut() {
                    if c.name.is_none() {
                        c.name = extract_field(line, K_NAME);
                    }
                    if c.birth.is_none() {
                        c.birth = extract_field(line, K_BIRTH);
                    }
                    if c.death.is_none() {
                        c.death = extract_field(line, K_DEATH);
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
                }
            }
        }

        let new_depth = depth + opens - closes;
        if in_chars && new_depth <= char_base {
            in_chars = false;
            if let Some(c) = cur.take() {
                if !c.alive() {
                    dead += 1;
                }
                if samples.len() < sample_limit {
                    samples.push(c.to_stub());
                }
            }
        }
        depth = new_depth;
        if depth < 0 {
            depth = 0;
        }
    }
    if let Some(c) = cur.take() {
        if !c.alive() {
            dead += 1;
        }
        if samples.len() < sample_limit {
            samples.push(c.to_stub());
        }
    }
    (count, dead, samples)
}

/// 扫描并提取单个人物（数字 id）的摘要；找到即返回，找不到返回 None。
fn scan_one_character(text: &str, wanted_id: &str) -> Option<CharacterStub> {
    let mut depth: i64 = 0;
    let mut in_chars = false;
    let mut char_base: i64 = 0;
    let mut cur: Option<CharFields> = None;

    for line in text.lines() {
        let opens = line.matches('{').count() as i64;
        let closes = line.matches('}').count() as i64;
        if !in_chars && line.contains(&format!("{K_CHARACTERS}={{")) {
            in_chars = true;
            char_base = depth;
        }
        if in_chars {
            let child_depth = char_base + 1;
            let field_depth = char_base + 2;
            if depth == child_depth {
                if let Some(id) = capture_id_entry(line) {
                    if let Some(c) = cur.take() {
                        if c.id == wanted_id {
                            return Some(c.to_stub());
                        }
                    }
                    cur = Some(CharFields {
                        id,
                        name: None,
                        birth: None,
                        death: None,
                        culture: None,
                        faith: None,
                        dynasty: None,
                    });
                }
            }
            if depth == field_depth {
                if let Some(c) = cur.as_mut() {
                    if c.name.is_none() {
                        c.name = extract_field(line, K_NAME);
                    }
                    if c.birth.is_none() {
                        c.birth = extract_field(line, K_BIRTH);
                    }
                    if c.death.is_none() {
                        c.death = extract_field(line, K_DEATH);
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
                }
            }
        }
        let new_depth = depth + opens - closes;
        if in_chars && new_depth <= char_base {
            in_chars = false;
            if let Some(c) = cur.take() {
                if c.id == wanted_id {
                    return Some(c.to_stub());
                }
            }
        }
        depth = new_depth;
        if depth < 0 {
            depth = 0;
        }
    }
    if let Some(c) = cur.take() {
        if c.id == wanted_id {
            return Some(c.to_stub());
        }
    }
    None
}

/// 提取单个人物（数字 id）的完整 melt 文本块。
fn extract_character_block(text: &str, wanted_id: &str) -> Option<String> {
    let mut depth: i64 = 0;
    let mut in_chars = false;
    let mut char_base: i64 = 0;
    let mut capture = false;
    let mut collected: Vec<String> = Vec::new();
    for line in text.lines() {
        let opens = line.matches('{').count() as i64;
        let closes = line.matches('}').count() as i64;
        if !in_chars && line.contains(&format!("{K_CHARACTERS}={{")) {
            in_chars = true;
            char_base = depth;
        }
        if in_chars && depth == char_base + 1 {
            if let Some(id) = capture_id_entry(line) {
                if id == wanted_id {
                    capture = true;
                } else if capture {
                    capture = false;
                }
            }
        }
        if capture {
            collected.push(line.to_string());
        }
        let new_depth = depth + opens - closes;
        if in_chars && new_depth <= char_base {
            in_chars = false;
            capture = false;
        }
        depth = new_depth;
        if depth < 0 {
            depth = 0;
        }
        if capture && depth <= char_base + 1 && !collected.is_empty() {
            break;
        }
    }
    if collected.is_empty() {
        None
    } else {
        Some(collected.join("\n"))
    }
}

fn capture_id_entry(line: &str) -> Option<String> {
    let t = line.trim_start();
    // 对象条目形如 `6432={`；同时排除 `key=value`（值而非对象）。
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

fn cmd_inspect(path: &Path) -> Result<(), String> {
    let started = Instant::now();
    let data = read_save_bytes(path)?;

    let encoding = {
        let file = Ck3File::from_slice(&data)
            .map_err(|e| format!("Ck3File::from_slice 失败: {e}"))?;
        encoding_name(file.encoding())
    };
    let header_parse_ok = try_parse_metadata(&data);

    let (melted, unknown) = melt_save(&data)?;
    let text = String::from_utf8_lossy(&melted);
    let (save_version, game_version, date, player_name, mods) = scan_meta(&text);
    let (character_count, dead_count, sample) = scan_characters(&text, 8);

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
        sample_characters: sample,
        unknown_token_count: unknown,
        header_parse_ok,
        melted_bytes: melted.len(),
        parse_ms: started.elapsed().as_secs_f64() * 1000.0,
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
    // 返回完整人物索引（后端会缓存并分页），不再只采样前 N 个。
    let (character_count, dead_count, sample) = scan_characters(&text, usize::MAX);
    print_json(&serde_json::json!({
        "character_count": character_count,
        "dead_character_count": dead_count,
        "sample_count": sample.len(),
        "sample": sample,
        "parse_ms": started.elapsed().as_secs_f64() * 1000.0,
    }))
}

fn cmd_character(path: &Path, id: &str) -> Result<(), String> {
    let data = read_save_bytes(path)?;
    let (melted, _unknown) = melt_save(&data)?;
    let text = String::from_utf8_lossy(&melted);
    match extract_character_block(&text, id) {
        Some(block) => {
            let mut stdout = io::stdout().lock();
            stdout.write_all(block.as_bytes()).ok();
            stdout.write_all(b"\n").ok();
            Ok(())
        }
        None => {
            eprintln!("未找到人物 id={id}");
            process::exit(1);
        }
    }
}

/// 输出单个人物的结构化 JSON 摘要（供后端直接消费，避免解析原始文本块）。
fn cmd_character_json(path: &Path, id: &str) -> Result<(), String> {
    let data = read_save_bytes(path)?;
    let (melted, _unknown) = melt_save(&data)?;
    let text = String::from_utf8_lossy(&melted);
    match scan_one_character(&text, id) {
        Some(stub) => print_json(&stub),
        None => {
            eprintln!("未找到人物 id={id}");
            process::exit(1);
        }
    }
}

fn print_json<T: Serialize>(v: &T) -> Result<(), String> {
    let mut stdout = io::stdout().lock();
    serde_json::to_writer_pretty(&mut stdout, v).map_err(|e| e.to_string())?;
    stdout.write_all(b"\n").ok();
    Ok(())
}

/// 调试用：把 melt 明文整体写入文件，便于人工检视。
fn cmd_dump(path: &Path, out: &Path) -> Result<(), String> {
    let data = read_save_bytes(path)?;
    let (melted, unknown) = melt_save(&data)?;
    let n = melted.len();
    fs::write(out, &melted).map_err(|e| format!("写入 dump 失败: {e}"))?;
    eprintln!("dump 完成: {n} 字节, 未知 token={unknown}");
    Ok(())
}

fn usage() -> ! {
    eprintln!(
        "用法: ck3-reader <inspect|list-mods|list-characters|character|character-json|dump> <save.ck3> [character-id|out.txt]"
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
    if !path.exists() {
        eprintln!("文件不存在: {}", path.display());
        process::exit(1);
    }
    let result = match cmd {
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
        "character" => {
            if args.len() < 4 {
                eprintln!("character 子命令需要 <character-id>");
                process::exit(2);
            }
            cmd_character(path, &args[3])
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
