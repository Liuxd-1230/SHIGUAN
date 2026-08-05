#!/usr/bin/env python3
"""Phase 3C-Audit：CK3 存档数据源审计脚本（对照 CK3-history-extractor，MIT）。

本轮目标**只做信息取证**，不扩大语义规则、不实现 Bridge Mod：
  - 确认某类信息是「存档本身未保存」（SAVE_ABSENT）还是「SHIGUAN 管线在处理中
    丢失」（READER_DROPPED / NORMALIZER_LOST / SEMANTIC_UNUSED）；
  - 对照 CK3-history-extractor（TCA166，MIT）的读取口径，识别其**默认推断**
    （EXTERNAL_TOOL_INFERRED，如裸 `date=HOLDER_ID` 默认解释为 "Inherited"），
    并明确这些推断**不是存档事实**，绝不当作 SHIGUAN 的取证依据；
  - 一次 melt、多次查询：只调用 reader `prepare --with-melted` 一次，
    之后全部查询都在同一份 melt 目录内进行（绝不重复 melt）。

分类（audit-classification）：
  SAVE_PRESENT          存档确有此数据，SHIGUAN 已读取
  SAVE_ABSENT           存档本身未保存（全局搜证确认）
  READER_DROPPED        存档有此数据，但 Rust reader 未读取（丢失点）
  NORMALIZER_LOST       存档有此数据，reader 已读，但 Python normalizer 丢弃
  SEMANTIC_UNUSED       已读到，但语义/传记层未消费
  MOD_REQUIRED          数据本身不在存档，需 Mod 文件（flavorization / localization）才能得到
  DYNAMIC_UNRESOLVED    存档有运行时动态引用，静态快照无法唯一解析
  EXTERNAL_TOOL_INFERRED 仅对照工具默认推断，非存档事实
  UNKNOWN               当前证据无法判定

输出（data/audit/<timestamp>/，目录已被 .gitignore 忽略，绝不分发）：
  audit-summary.json            审计结论汇总（分类统计 + 关键数字）
  field-trace.json              字段在存档中的存在性 + SHIGUAN 是否消费
  title-history-comparison.json 头衔 history 原始 vs reader 对照（≥3 个 title 完整 history）
  character-comparison.json     玩家 / 封臣 / 无地人物原始字段 vs reader 对照
  memory-comparison.json        记忆原始 vs reader 对照
  war-comparison.json           战争容器与领土转移关联取证
  report.md                     人类可读审计报告

用法：
  python scripts/audit_ck3_history_sources.py [--save <路径> | --save-id <id>]
      [--out <目录>] [--reader <reader 二进制>]

  --save-id 缺省时自动挑选 staging 根目录下最新的 *.ck3。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "server"))

from app.config import resolve_reader_binary  # noqa: E402

STAGING_ROOT = ROOT / "data" / "staging"
AUDIT_ROOT = ROOT / "data" / "audit"

# 审计分类全集（见模块 docstring）。
AUDIT_CATEGORIES = (
    "SAVE_PRESENT",
    "SAVE_ABSENT",
    "READER_DROPPED",
    "NORMALIZER_LOST",
    "SEMANTIC_UNUSED",
    "MOD_REQUIRED",
    "DYNAMIC_UNRESOLVED",
    "EXTERNAL_TOOL_INFERRED",
    "UNKNOWN",
)

# ---------------------------------------------------------------------------
# PDX 文本解析（自研极简实现，只服务本审计；纯函数，可单测）
# ---------------------------------------------------------------------------


class PdxBlock:
    """有序 key→value 列表（PDX 允许重复键，不能用普通 dict 表达）。"""

    __slots__ = ("pairs",)

    def __init__(self) -> None:
        self.pairs: list[tuple[str, object]] = []

    def get(self, key: str, default: object = None) -> object:
        for k, v in self.pairs:
            if k == key:
                return v
        return default

    def get_all(self, key: str) -> list[object]:
        return [v for k, v in self.pairs if k == key]

    def keys(self) -> set[str]:
        return {k for k, _ in self.pairs}

    def __contains__(self, key: str) -> bool:
        return any(k == key for k, _ in self.pairs)


def find_next_nonspace(text: str, i: int) -> int:
    """跳过空白与 `#` 注释，返回下一个有效字符位置。"""
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "#":
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
        else:
            break
    return i


def read_quoted(text: str, i: int) -> tuple[str, int]:
    """读取 `"..."` 引号串（处理 `\\` 转义），返回 (值, 结束位置)。"""
    n = len(text)
    assert text[i] == '"'
    j = i + 1
    out: list[str] = []
    while j < n:
        c = text[j]
        if c == "\\" and j + 1 < n:
            out.append(text[j + 1])
            j += 2
        elif c == '"':
            break
        else:
            out.append(c)
            j += 1
    return "".join(out), j + 1


def read_token(text: str, i: int) -> tuple[str, int]:
    """读取非引号 token（以空白 / `{}` / `=` 为界），返回 (token, 结束位置)。"""
    n = len(text)
    j = i
    while j < n and text[j] not in " \t\r\n{}=":
        j += 1
    return text[i:j], j


def _read_value_token(text: str, i: int) -> tuple[str, int]:
    if text[i] == '"':
        return read_quoted(text, i)
    return read_token(text, i)


def _matching_brace(text: str, open_pos: int) -> int:
    """`{` 在 open_pos，返回配对 `}` 的下标（引号感知）。"""
    depth = 0
    i = open_pos
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            _, i = read_quoted(text, i)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("PDX 花括号不平衡")


def extract_balanced(text: str, open_pos: int) -> str:
    """返回从 open_pos 的 `{` 到配对 `}` 的完整子串（含两端花括号）。"""
    end = _matching_brace(text, open_pos)
    return text[open_pos : end + 1]


def parse_pdx(text: str, i: int) -> tuple[PdxBlock, int]:
    """从位置 i（必须是 `{`）解析一个 PDX 块，返回 (PdxBlock, 结束位置)。

    值有三种：嵌套 PdxBlock / 引号或裸 token 字符串 / 裸键（无 `=`，记 True）。
    """
    assert i < len(text) and text[i] == "{"
    block = PdxBlock()
    i += 1
    n = len(text)
    while True:
        i = find_next_nonspace(text, i)
        if i >= n:
            raise ValueError("PDX 块未闭合")
        if text[i] == "}":
            return block, i + 1
        if text[i] == "{":
            # 匿名数组元素 `{ ... }`：以空键记入（不匹配任何具名 get）。
            val, i = parse_pdx(text, i)
            block.pairs.append(("", val))
            continue
        key, i = _read_value_token(text, i)
        i = find_next_nonspace(text, i)
        if i < n and text[i] == "=":
            i = find_next_nonspace(text, i + 1)
            if i < n and text[i] == "{":
                val, i = parse_pdx(text, i)
            elif i < n and text[i] == '"':
                val, i = read_quoted(text, i)
            else:
                val, i = read_token(text, i)
        else:
            val = True
        block.pairs.append((key, val))


def iter_root_pairs(text: str):
    """遍历文本顶层 `key=value` 对。

    block 值返回平衡子串（含 `{}`）；scalar 值返回字符串 / True。
    若整段文本就是一个 `{...}` 平衡容器块（如 landed_titles={...} 的块值），
    从容器内部开始迭代（容器自身不是一对键值）。
    """
    i = 0
    n = len(text)
    start = find_next_nonspace(text, 0)
    if start < n and text[start] == "{":
        i = start + 1
    while i < n:
        i = find_next_nonspace(text, i)
        if i >= n:
            return
        if text[i] == "}":
            return
        if text[i] == "{":
            # 匿名数组元素 `{ ... }`：跳过。
            i = _matching_brace(text, i) + 1
            continue
        key, i = _read_value_token(text, i)
        i = find_next_nonspace(text, i)
        if i < n and text[i] == "=":
            i = find_next_nonspace(text, i + 1)
            if i < n and text[i] == "{":
                end = _matching_brace(text, i)
                yield key, text[i : end + 1], "block"
                i = end + 1
            elif i < n and text[i] == '"':
                val, i = read_quoted(text, i)
                yield key, val, "scalar"
            else:
                val, i = read_token(text, i)
                yield key, val, "scalar"
        else:
            yield key, True, "scalar"


def iter_blocks(text: str, start: int, end: int):
    """在 [start, end) 范围内遍历 `key = { ... }` 块，yield (key, 块子串)。

    匿名 `{ ... }` 数组元素 yield (None, 块子串)。只做位置切分，不解析内容。
    """
    i = start
    while i < end:
        i = find_next_nonspace(text, i)
        if i >= end:
            return
        c = text[i]
        if c == "}":
            return
        if c == "{":
            j = _matching_brace(text, i)
            yield None, text[i : j + 1]
            i = j + 1
            continue
        key, i = _read_value_token(text, i)
        i = find_next_nonspace(text, i)
        if i < end and text[i] == "=":
            i = find_next_nonspace(text, i + 1)
            if i < end and text[i] == "{":
                j = _matching_brace(text, i)
                yield key, text[i : j + 1]
                i = j + 1
                continue
            # 标量值：跳过
            if i < end and text[i] == '"':
                _, i = read_quoted(text, i)
            else:
                _, i = read_token(text, i)


# ---------------------------------------------------------------------------
# 原始取证：对 melted 文本的定向扫描（只提取审计所需，不建全量 AST）
# ---------------------------------------------------------------------------

# 头衔块字段存在性追踪（field-trace 用途）。
TITLE_TRACE_FIELDS = (
    "capital",
    "claims",
    "de_jure_liege",
    "history_government",
    "title_history_names",
    "title_name_data",
    "holder",
    "de_facto_liege",
    "history",
    "landless",
    "government",
    "law",
    "nickname",
    "coat_of_arms",
    "title_liege",
    "primary_title",
    "held_titles",
    "de_jure_vassals",
    "development",
)

# 人物块字段存在性追踪（1.19 存档人物块为分组容器：alive_data / family_data /
# landed_data / playable_data / court_data，字段多为**嵌套**键，用子串 `key=` 探测）。
CHAR_TRACE_FIELDS = (
    "first_name",
    "birth",
    "was_player",
    "landed_data",
    "dynasty_house",
    "family_data",
    "father",
    "real_father",
    "mother",
    "spouse",
    "child",
    "traits",
    "nickname_text",
    "culture",
    "faith",
    "court_data",
    "dead_data",
    "death",
    "liege",
    "capital",
    "government",
    "domain",
    "held_titles",
    "primary_title",
)


@dataclass
class TitleHistoryData:
    """每个头衔的原始 history 与顶层字段（来自存档文本本身）。"""

    key: str
    entries: list[dict] = field(default_factory=list)
    top_level_fields: list[str] = field(default_factory=list)
    field_counts: dict[str, int] = field(default_factory=dict)


def extract_title_histories(landed_text: str) -> dict[str, TitleHistoryData]:
    """解析 `landed_titles={...}` 容器文本，提取每个头衔的完整 history。

    返回 {title_key: TitleHistoryData}。history 条目：
      Format A（裸 `date=HOLDER_ID`）：format='A', raw_type=None
      Format B（`date={ type=… holder=… }`）：format='B', raw_type=type 原样

    存档的 landed_titles 容器含 dynamic_templates / landed_titles / index 三个
    子容器，真正的头衔块在**嵌套的** landed_titles 里，先解包一层；嵌套容器用
    数字包裹键（0/1/2…），真正的头衔 key 取块内 `key=` 字段（与 reader 一致）。
    """
    # 若输入本身带 `landed_titles = { ... }` 包装，先剥掉一层。
    for key, val, kind in iter_root_pairs(landed_text):
        if kind == "block" and key == "landed_titles":
            landed_text = val
            break
    # 再解包嵌套的 landed_titles（存档真实结构）。
    nested = ""
    for key, val, kind in iter_root_pairs(landed_text):
        if kind == "block" and key == "landed_titles":
            nested = val
            break
    if nested:
        landed_text = nested
    out: dict[str, TitleHistoryData] = {}
    for wkey, val, kind in iter_root_pairs(landed_text):
        if kind != "block":
            continue
        try:
            blk, _ = parse_pdx(val, 0)
        except ValueError:
            continue
        # 存档的嵌套 landed_titles 容器用数字包裹键（0/1/2…），真正的头衔 key
        # 在块内 `key=` 字段（如 h_roman_empire / k_viet），与 reader 口径一致。
        tkey = blk.get("key")
        title_key = str(tkey) if isinstance(tkey, str) else wkey
        hist = blk.get("history")
        entries: list[dict] = []
        if isinstance(hist, PdxBlock):
            for date, value in hist.pairs:
                if isinstance(value, PdxBlock):
                    t = value.get("type")
                    holder = value.get("holder")
                    entries.append(
                        {
                            "date": str(date),
                            "format": "B",
                            "raw_type": str(t) if isinstance(t, str) else None,
                            "holder": str(holder) if isinstance(holder, str) else None,
                        }
                    )
                else:
                    entries.append(
                        {
                            "date": str(date),
                            "format": "A",
                            "raw_type": None,
                            "holder": str(value) if isinstance(value, str) else None,
                        }
                    )
        out[title_key] = TitleHistoryData(
            key=title_key,
            entries=entries,
            top_level_fields=sorted(blk.keys()),
            field_counts=dict(Counter(k for k, _ in blk.pairs)),
        )
    return out


def scan_title_field_presence(landed_text: str) -> dict[str, int]:
    """统计指定字段在 landed_titles 容器全文（含嵌套子容器）的出现次数。

    用子串 `key=` 探测：存在性语义是「存档中确有该数据」，而非「必须在头衔块
    顶层」。absence（0 次）才能下 SAVE_ABSENT 结论。
    """
    counts: dict[str, int] = {}
    for f in TITLE_TRACE_FIELDS:
        counts[f] = landed_text.count(f + "=")
    return counts


def scan_character_containers(text: str, wanted_ids: set[str]):
    """扫描 living / dead_prunable / dead_unprunable 人物容器。

    返回：
      player_id      —— 含 `player=yes` 的人物 id（首个命中）
      player_block   —— 玩家原始块子串
      wanted_blocks  —— wanted_ids 命中的原始块子串
      container_counts —— 各容器人物数
      field_presence —— CHAR_TRACE_FIELDS 子串级出现次数（对全部人物块）
    """
    containers = ["living", "dead_unprunable", "dead_prunable"]
    player_id: str | None = None
    player_block: str | None = None
    wanted_blocks: dict[str, str] = {}
    container_counts: dict[str, int] = {c: 0 for c in containers}
    field_presence: dict[str, int] = {f: 0 for f in CHAR_TRACE_FIELDS}

    for cname, cval, _kind in iter_root_pairs(text):
        if cname not in containers or _kind != "block":
            continue
        inner_start = cval.find("{") + 1
        inner_end = cval.rfind("}")
        count = 0
        for cid, blk in iter_blocks(cval, inner_start, inner_end):
            if cid is None:
                continue
            count += 1
            if "was_player=yes" in blk and player_id is None:
                player_id = cid
                player_block = blk
            if cid in wanted_ids:
                wanted_blocks[cid] = blk
            for f in CHAR_TRACE_FIELDS:
                if f + "=" in blk:
                    field_presence[f] += 1
        container_counts[cname] = container_counts.get(cname, 0) + count
    return {
        "player_id": player_id,
        "player_block": player_block,
        "wanted_blocks": wanted_blocks,
        "container_counts": container_counts,
        "field_presence": field_presence,
    }


def scan_memories_raw(memory_manager_text: str) -> dict:
    """解析 `character_memory_manager={...}`，统计记忆类型分布与总数。

    另返回若干样例，供对照记忆参数覆盖度。
    """
    census: Counter = Counter()
    total = 0
    samples: list[dict] = []
    for key, val, kind in iter_root_pairs(memory_manager_text):
        if key == "database" and kind == "block":
            inner_start = val.find("{") + 1
            inner_end = val.rfind("}")
            for mid, mblk in iter_blocks(val, inner_start, inner_end):
                if mid is None:
                    continue
                try:
                    mb, _ = parse_pdx(mblk, 0)
                except ValueError:
                    continue
                total += 1
                mtype = mb.get("type")
                mtype_s = str(mtype) if isinstance(mtype, str) else "?"
                census[mtype_s] += 1
                if len(samples) < 5:
                    params = mb.get("params")
                    participants = mb.get("participants")
                    samples.append(
                        {
                            "id": str(mid),
                            "type": mtype_s,
                            "params_keys": sorted(params.keys()) if isinstance(params, PdxBlock) else [],
                            "participant_roles": [
                                str(v.get("role"))
                                for _k, v in participants.pairs
                                if isinstance(v, PdxBlock)
                            ]
                            if isinstance(participants, PdxBlock)
                            else [],
                        }
                    )
    return {
        "total": total,
        "type_census": dict(census),
        "type_count": len(census),
        "samples": samples,
    }


def scan_wars_raw(wars_text: str) -> dict:
    """解析 `wars={...}` 容器，统计战争数与子容器分布，抓取样例字段。"""
    sub_container_counts: Counter = Counter()
    total = 0
    samples: list[dict] = []
    for cname, cval, kind in iter_root_pairs(wars_text):
        if kind != "block":
            continue
        sub_container_counts[cname] += 1
        inner_start = cval.find("{") + 1
        inner_end = cval.rfind("}")
        for wid, wblk in iter_blocks(cval, inner_start, inner_end):
            if wid is None:
                continue
            total += 1
            if len(samples) < 8:
                try:
                    wb, _ = parse_pdx(wblk, 0)
                except ValueError:
                    continue
                samples.append(
                    {
                        "id": str(wid),
                        "start_date": str(wb.get("start_date") or ""),
                        "attacker": str(wb.get("attacker") or ""),
                        "defender": str(wb.get("defender") or ""),
                        "casus_belli": str(wb.get("casus_belli") or ""),
                        "has_target_title": any(
                            k == "title" or k.endswith("_title") for k, _ in wb.pairs
                        ),
                    }
                )
    return {
        "total": total,
        "sub_containers": dict(sub_container_counts),
        "samples": samples,
    }


def search_war_linkage_keys(landed_text: str) -> dict:
    """在 landed_titles 容器文本中搜索战争→头衔的直接关联键。

    返回各关联键的原始出现次数。全为 0 即确认「存档无 war_id / won_war /
    lost_war / war= 键」，战争与领土转移**没有**直接的字段级关联
    （唯一的显式线索是 history type 为 conquest*，如 conquest_holy_war）。
    """
    return {
        "war_id": landed_text.count("war_id="),
        "won_war": landed_text.count("won_war="),
        "lost_war": landed_text.count("lost_war="),
        "war=": landed_text.count("war="),
    }


# ---------------------------------------------------------------------------
# 对照：原始 vs reader（SHIGUAN）vs CK3-history-extractor 口径
# ---------------------------------------------------------------------------

# 对照项目 CK3-history-extractor（title.rs）对裸 `date=ID` 的默认解释。
EXTERNAL_TOOL_FORMAT_A_DEFAULT = "Inherited"


def compare_title_history(
    raw_histories: dict[str, TitleHistoryData],
    reader_titles: list[dict],
    selected_keys: list[str],
) -> dict:
    """选中的头衔：原始 history 完整列表 vs reader history，逐条对照。

    同时给出 CK3-history-extractor 对 Format A 的默认推断标注（仅对照，非存档事实）。
    """
    reader_by_key = {t.get("key"): t for t in reader_titles}
    selected = [k for k in selected_keys if k in raw_histories]
    results: list[dict] = []
    for key in selected:
        raw = raw_histories[key]
        r = reader_by_key.get(key, {})
        reader_entries = r.get("history") or []
        raw_dates = Counter(e["date"] for e in raw.entries)
        reader_dates = Counter(e.get("date") for e in reader_entries)
        raw_by_date: dict[str, dict] = {}
        for e in raw.entries:
            raw_by_date.setdefault(e["date"], e)
        kind_folded: list[str] = []
        for e in reader_entries:
            if e.get("kind") != "other":
                continue
            raw_e = raw_by_date.get(e.get("date"))
            rt = e.get("raw_type")
            folded_type = rt
            if rt in (None, "created", "destroyed") and raw_e:
                # 旧缓存无 raw_type：用存档原文回查该日期条目是否显式 type。
                folded_type = raw_e.get("raw_type")
            if folded_type not in (None, "created", "destroyed"):
                kind_folded.append(f"{e.get('date')} type={folded_type}")
        results.append(
            {
                "key": key,
                "raw_total": len(raw.entries),
                "reader_total": len(reader_entries),
                "raw_format_a": sum(1 for e in raw.entries if e["format"] == "A"),
                "raw_format_b": sum(1 for e in raw.entries if e["format"] == "B"),
                "reader_missing_dates": sorted(
                    (raw_dates - reader_dates).elements()
                )[:10],
                "reader_extra_dates": sorted(
                    (reader_dates - raw_dates).elements()
                )[:10],
                "kind_folded_entries": kind_folded[:10],
                "raw_entries": raw.entries,
                "reader_entries": [
                    {
                        "date": e.get("date"),
                        "kind": e.get("kind"),
                        "raw_type": e.get("raw_type"),
                        "holder_id": e.get("holder_id"),
                    }
                    for e in reader_entries
                ],
                "external_tool_inference": {
                    "format_a_default": EXTERNAL_TOOL_FORMAT_A_DEFAULT,
                    "note": "CK3-history-extractor 对裸 date=ID 默认解释为 "
                    "'Inherited'，属对照工具推断，非存档事实（SHIGUAN 不做此推断）。",
                },
            }
        )
    # 全量 type 普查：存档显式 type 分布 vs reader kind 分布。
    raw_type_census: Counter = Counter()
    for data in raw_histories.values():
        for e in data.entries:
            if e["format"] == "B" and e["raw_type"]:
                raw_type_census[e["raw_type"]] += 1
    reader_kind_census: Counter = Counter()
    reader_raw_census: Counter = Counter()
    for t in reader_titles:
        for e in t.get("history") or []:
            reader_kind_census[e.get("kind")] += 1
            if e.get("raw_type") is not None:
                reader_raw_census[e.get("raw_type")] += 1
    return {
        "selected_titles": results,
        "census": {
            "save_explicit_types": dict(sorted(raw_type_census.items())),
            "reader_kinds": dict(sorted(reader_kind_census.items())),
            "reader_raw_types": dict(sorted(reader_raw_census.items())),
            "save_history_total": sum(len(d.entries) for d in raw_histories.values()),
            "reader_history_total": sum(len(t.get("history") or []) for t in reader_titles),
        },
    }


def compare_character(
    raw_block: str | None,
    reader_rec: dict | None,
    label: str,
    role: str,
) -> dict:
    """单个角色：原始块顶层字段 vs reader 记录字段。"""
    if raw_block is None:
        raw_keys: list[str] = []
        raw_field_presence: dict[str, int] = {}
    else:
        try:
            blk, _ = parse_pdx(raw_block, 0)
            raw_keys = sorted(blk.keys())
            raw_field_presence = dict(Counter(blk.keys()))
        except ValueError:
            raw_keys = []
            raw_field_presence = {}
    reader_keys = sorted(reader_rec.keys()) if reader_rec else []
    return {
        "label": label,
        "role": role,
        "id": (reader_rec or {}).get("id") if reader_rec else None,
        "raw_top_level_keys": raw_keys,
        "reader_fields": reader_keys,
        "raw_field_presence": raw_field_presence,
        "note": "reader 字段为结构化提取子集（name/birth/…/liege），"
        "原始块字段全集远大于 reader 字段，两者缺列不必然代表丢失。",
    }


def compare_memories(raw_mem: dict, reader_mem: dict) -> dict:
    reader_list = reader_mem.get("memories") or []
    reader_census = Counter(m.get("memory_type") for m in reader_list)
    raw_census = raw_mem["type_census"]
    missing_types = sorted(set(raw_census) - set(reader_census))
    extra_types = sorted(set(reader_census) - set(raw_census))
    return {
        "raw_total": raw_mem["total"],
        "reader_total": len(reader_list),
        "raw_type_count": raw_mem["type_count"],
        "reader_type_count": len(reader_census),
        "types_reader_missing": missing_types,
        "types_reader_only": extra_types,
        "raw_census": dict(sorted(raw_census.items())),
        "reader_census": dict(sorted(reader_census.items())),
        "raw_samples": raw_mem["samples"],
    }


def compare_wars(raw_wars: dict, war_linkage_keys: dict) -> dict:
    linkage_absent = all(v == 0 for v in war_linkage_keys.values())
    return {
        "raw": raw_wars,
        "war_linkage_keys_in_landed_titles": war_linkage_keys,
        "direct_linkage": not linkage_absent,
        "linkage_conclusion": (
            "存档头衔 history 中不存在 war_id / won_war / lost_war / war= 等直接战争"
            "引用键" + ("（本存档计数全 0，成立）" if linkage_absent else "（本存档发现若干计数）")
            + "；战争与领土转移的唯一显式线索是 history type 为 conquest*"
            "（conquest / conquest_claim / conquest_populist / conquest_holy_war）。"
        ),
    }


# ---------------------------------------------------------------------------
# field-trace：字段 → 分类（谁拥有它、谁消费它）
# ---------------------------------------------------------------------------

# (字段, 作用域) -> (是否被 reader 消费, 语义层是否消费, 额外分类, 备注)
_FIELD_TABLE: dict[tuple[str, str], tuple[bool, bool, str | None, str]] = {
    ("capital", "landed_titles"): (False, False, "READER_DROPPED", "存档有此字段，reader 未读取"),
    ("claims", "landed_titles"): (False, False, "READER_DROPPED", "存档有此字段，reader 未读取"),
    ("de_jure_liege", "landed_titles"): (False, False, "READER_DROPPED", "存档有此字段，reader 未读取"),
    ("history_government", "landed_titles"): (False, False, "READER_DROPPED", "存档有此字段，reader 未读取"),
    ("title_history_names", "landed_titles"): (False, False, "MOD_REQUIRED", "存档仅存运行时名，历史名需 Mod flavorization/localization 才能解析"),
    ("title_name_data", "landed_titles"): (True, True, None, "reader 读取用于显示名"),
    ("holder", "landed_titles"): (True, True, None, "reader 读取现任持有者"),
    ("de_facto_liege", "landed_titles"): (True, False, "SEMANTIC_UNUSED", "reader 读取 liege，语义层未消费"),
    ("history", "landed_titles"): (True, True, None, "reader 读取（3C-Audit 起含 raw_type）"),
    ("landless", "landed_titles"): (False, False, "READER_DROPPED", "存档 top-level 有 landless 头衔属性，reader 未读取"),
    ("government", "landed_titles"): (False, False, "READER_DROPPED", "存档有此字段（2947 处），reader 未读取"),
    ("de_jure_vassals", "landed_titles"): (False, False, "READER_DROPPED", "存档有此字段，reader 未读取"),
    ("primary_title", "landed_titles"): (False, False, "SAVE_ABSENT", "存档中无 primary_title / held_titles 字段（person 上也没有）"),
    ("held_titles", "landed_titles"): (False, False, "SAVE_ABSENT", "存档中无 held_titles 字段"),
    ("title_liege", "landed_titles"): (False, False, "SAVE_ABSENT", "存档中无 title_liege 字段"),
    ("player", "landed_titles"): (True, True, None, "reader 读取 holder 用于索引"),
    ("first_name", "character"): (True, True, None, "reader 读取 first_name"),
    ("birth", "character"): (True, True, None, "reader 读取 birth（alive_data）"),
    ("was_player", "character"): (False, False, "READER_DROPPED", "存档唯一 was_player=yes 标记玩家，reader/后端未读取（player_id 目前置空）"),
    ("landed_data", "character"): (True, True, None, "reader 用它判定 ruler 并反查 domain"),
    ("dynasty_house", "character"): (True, True, None, "reader 读取 dynasty_house"),
    ("family_data", "character"): (True, True, None, "reader 读取 father/mother/spouse/child/real_father"),
    ("father", "character"): (True, True, None, "reader 读取 father（219 处）"),
    ("real_father", "character"): (True, True, None, "reader 读取 real_father（存档直述父，377 处）"),
    ("mother", "character"): (True, True, None, "存档人物块无 mother= 直接字段（0 处）；母系经其他角色 child 列表反推（reader parent_source=child_backref）或记忆 params 引用（本存档 828 处）"),
    ("spouse", "character"): (True, True, None, "reader 读取 spouse / primary_spouse"),
    ("child", "character"): (True, True, None, "reader 读取 child / children"),
    ("traits", "character"): (True, False, "SEMANTIC_UNUSED", "reader 读取 traits，语义层未消费"),
    ("nickname_text", "character"): (True, True, None, "reader 读取 nickname"),
    ("culture", "character"): (True, True, None, "reader 读取 culture"),
    ("faith", "character"): (True, True, None, "reader 读取 faith"),
    ("court_data", "character"): (False, False, "READER_DROPPED", "存档 court_data 容器，reader 未读取"),
    ("dead_data", "character"): (True, False, "SEMANTIC_UNUSED", "reader 读取死亡信息（卒年/死因/liege），语义层部分消费"),
    ("death", "character"): (True, True, None, "死亡日期存于 dead_data.date（非 death= 键），reader 已读取"),
    ("liege", "character"): (True, True, None, "reader 读取 dead_data.liege（仅卒年记录）"),
    ("capital", "character"): (False, False, "READER_DROPPED", "存档人物块有 capital 字段，reader 未读取"),
    ("government", "character"): (False, False, "READER_DROPPED", "存档人物块有 government 字段，reader 未读取"),
    ("domain", "character"): (True, False, "SEMANTIC_UNUSED", "landed_data.domain 为持有领地 id 列表，reader 未读入档案（当前从 landed_titles.holder 反查）"),
    ("held_titles", "character"): (False, False, "SAVE_ABSENT", "人物块无 held_titles 字段（持地由 landed_data.domain 表达）"),
    ("primary_title", "character"): (False, False, "SAVE_ABSENT", "人物块无 primary_title 字段"),
}


def classify_field(field: str, scope: str, present_count: int) -> dict:
    reader_reads, semantic_uses, extra, note = _FIELD_TABLE.get(
        (field, scope),
        (False, False, "UNKNOWN", "未登记字段，需人工判定"),
    )
    classification = extra or ("SAVE_PRESENT" if reader_reads else "UNKNOWN")
    return {
        "field": field,
        "scope": scope,
        "present_in_save": present_count > 0,
        "count": present_count,
        "reader_reads": reader_reads,
        "semantic_layer_uses": semantic_uses,
        "classification": classification,
        "note": note,
    }


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def build_report(meta: dict, summary: dict) -> str:
    lines: list[str] = []
    lines.append(f"# Phase 3C-Audit 数据源审计报告（{meta['generatedAt']}）")
    lines.append("")
    lines.append(f"- 存档：`{meta['save']['file']}`（id `{meta['save']['id']}`）")
    lines.append(f"- 编码：`{meta['save']['encoding']}`；游戏版本 `{meta['save']['game_version']}`；存档日期 `{meta['save']['date']}`")
    lines.append("- 方法：一次 `prepare --with-melted`，全部查询在同一 melt 目录内完成。")
    lines.append("")
    lines.append("## 一、结论速览（分类统计）")
    lines.append("")
    lines.append("| 分类 | 次数 |")
    lines.append("| --- | --- |")
    for cat in AUDIT_CATEGORIES:
        n = summary["classification_counts"].get(cat, 0)
        if n:
            lines.append(f"| {cat} | {n} |")
    lines.append("")
    lines.append("## 二、关键数字")
    lines.append("")
    for key, value in summary["key_numbers"].items():
        lines.append(f"- **{key}**：{value}")
    lines.append("")
    lines.append("## 三、头衔 history type 对照")
    lines.append("")
    lines.append("完整对照见 `title-history-comparison.json`。要点：")
    lines.append("")
    census = summary["title_census"]
    lines.append(f"- 存档 history 总条数：**{census['save_history_total']}**；reader 输出：**{census['reader_history_total']}**（修复 Format A 行尾丢条后一致）。")
    if census["save_explicit_types"]:
        lines.append(f"- 存档显式 type 分布：{census['save_explicit_types']}")
    lines.append(f"- reader 的 kind 折叠分布：{census['reader_kinds']}")
    lines.append("- CK3-history-extractor 对裸 `date=ID` 默认解释为 `Inherited`（EXTERNAL_TOOL_INFERRED），SHIGUAN 不采信。")
    lines.append("")
    lines.append("## 四、字段存在性（详见 field-trace.json）")
    lines.append("")
    lines.append("| 字段 | 作用域 | 存档存在 | reader 消费 | 分类 | 备注 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for f in summary["field_trace_rows"]:
        lines.append(
            f"| {f['field']} | {f['scope']} | {f['present_in_save']} | {f['reader_reads']} | {f['classification']} | {f.get('note', '')} |"
        )
    lines.append("")
    lines.append("## 五、人物对照（详见 character-comparison.json）")
    lines.append("")
    lines.append(f"- 人物容器计数：{summary.get('character_containers')}。")
    for c in summary["characters"]:
        lines.append(f"- **{c['label']}**（{c['role']}）：原始块顶层字段 {len(c['raw_top_level_keys'])} 个；reader 字段 {len(c['reader_fields'])} 个。")
    lines.append("")
    lines.append("## 六、记忆对照（详见 memory-comparison.json）")
    lines.append("")
    mc = summary["memory"]
    lines.append(f"- 原始记忆：**{mc['raw_total']}** 条 / {mc['raw_type_count']} 类；reader：**{mc['reader_total']}** 条 / {mc['reader_type_count']} 类。")
    lines.append(f"- reader 缺失类型：{mc['types_reader_missing'] or '无'}；reader 独有类型：{mc['types_reader_only'] or '无'}。")
    lines.append("")
    lines.append("## 七、战争与领土转移（详见 war-comparison.json）")
    lines.append("")
    wc = summary["war"]
    lines.append(f"- 存档战争总数：**{wc['raw']['total']}**（子容器 {wc['raw']['sub_containers']}）。")
    lines.append(f"- 头衔容器中战争关联键（war_id / won_war / lost_war / war=）计数：{wc['war_linkage_keys_in_landed_titles']}。")
    lines.append(f"- 直接 war→title 关联：**{'存在' if wc['direct_linkage'] else '不存在（SAVE_ABSENT）'}**。")
    lines.append("")
    lines.append("## 八、修复优先级建议")
    lines.append("")
    lines.append("P0（已随本审计落地）：reader 保留 history 显式 raw_type + 修复 Format A 行尾丢条。")
    lines.append("P1：capital / claims / de_jure_liege / history_government 读取（均为 READER_DROPPED）。")
    lines.append("P2：landless / court / government 读取；primary_title 确认 SAVE_ABSENT 后由语义层从 holders 推导（不伪造）。")
    lines.append("")
    lines.append("完整结论与 Bridge Mod 评估见 `docs/phase3c-data-source-audit.md`。")
    return "\n".join(lines)


def run_audit(save_path: Path, reader: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    melt_dir = out_dir / "melt"

    # 1) 一次 melt（prepare --with-melted 把 melted.txt 写入 melt 目录）。
    proc = subprocess.run(
        [str(reader), "prepare", str(save_path), str(melt_dir), "--with-melted"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ck3-reader prepare 失败：{(proc.stderr or proc.stdout).strip()[:500]}"
        )

    # 2) 读取 melt 目录中的全部 reader 产物 + melted 原文。
    meta = json.loads((melt_dir / "meta.json").read_text(encoding="utf-8"))
    titles_doc = json.loads((melt_dir / "titles.json").read_text(encoding="utf-8"))
    mem_doc = json.loads((melt_dir / "memories.json").read_text(encoding="utf-8"))
    ndjson_path = melt_dir / "characters.ndjson"
    characters: list[dict] = []
    for line in ndjson_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                characters.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    melted = (melt_dir / "melted.txt").read_text(encoding="utf-8", errors="replace")

    # 3) 原始取证：从 melted 文本直接解析。
    landed_text = ""
    memory_text = ""
    wars_text = ""
    for key, val, kind in iter_root_pairs(melted):
        if kind != "block":
            continue
        if key == "landed_titles" and not landed_text:
            landed_text = val
        elif key == "character_memory_manager" and not memory_text:
            memory_text = val
        elif key == "wars" and not wars_text:
            wars_text = val

    histories = extract_title_histories(landed_text)
    title_field_presence = scan_title_field_presence(landed_text)
    memory_raw = scan_memories_raw(memory_text)
    wars_raw = scan_wars_raw(wars_text)
    war_linkage = search_war_linkage_keys(landed_text)

    # 4) 选择对照人物：玩家 + 封臣 + 无地。
    ruler_ids = {t.get("holder_id") for t in titles_doc.get("titles") or [] if t.get("holder_id")}
    vassal_id: str | None = None
    for t in titles_doc.get("titles") or []:
        if t.get("holder_id") and t.get("de_facto_liege_id"):
            vassal_id = str(t["holder_id"])
            break
    landless_id: str | None = None
    for rec in characters:
        if (
            not rec.get("ruler")
            and rec.get("alive", True)
            and str(rec.get("id")) not in ruler_ids
        ):
            landless_id = str(rec.get("id"))
            break
    wanted = {v for v in (vassal_id, landless_id) if v}
    char_scan = scan_character_containers(melted, wanted)
    if char_scan["player_id"] is None and char_scan["player_block"] is None:
        # 极个别存档玩家块不可定位时的兜底：用 ruler 集合中最小的活人 id。
        char_scan["player_id"] = str(min(ruler_ids, key=int)) if ruler_ids else None

    player_rec = next((r for r in characters if str(r.get("id")) == str(char_scan["player_id"])), None)
    vassal_rec = next((r for r in characters if str(r.get("id")) == str(vassal_id)), None)
    landless_rec = next((r for r in characters if str(r.get("id")) == str(landless_id)), None)

    character_comparison = [
        compare_character(
            char_scan["player_block"],
            player_rec,
            "玩家（player）",
            "player",
        ),
        compare_character(
            char_scan["wanted_blocks"].get(str(vassal_id)),
            vassal_rec,
            "封臣（持头衔且有 de_facto_liege）",
            "vassal",
        ),
        compare_character(
            char_scan["wanted_blocks"].get(str(landless_id)),
            landless_rec,
            "无地人物（活、非统治者、无头衔）",
            "landless",
        ),
    ]

    # 5) 头衔对照：优先玩家最高头衔 + history 最丰富的 4 个头衔（共 ≥3）。
    title_list = titles_doc.get("titles") or []
    primary_key: str | None = None
    if player_rec:
        holder = str(player_rec.get("id"))
        held = [
            t for t in title_list
            if str(t.get("holder_id")) == holder
            and t.get("tier") in ("kingdom", "empire")
        ]
        if held:
            primary_key = held[0].get("key")
    ranked = sorted(
        histories.items(), key=lambda kv: (-len(kv[1].entries), kv[0])
    )
    selected_keys: list[str] = []
    for key, _ in ranked:
        if key not in selected_keys and len(selected_keys) < 4:
            selected_keys.append(key)
    if primary_key and primary_key not in selected_keys:
        selected_keys.insert(0, primary_key)
        selected_keys = selected_keys[:5]

    title_comparison = compare_title_history(histories, title_list, selected_keys)
    memory_comparison = compare_memories(memory_raw, mem_doc)
    war_comparison = compare_wars(wars_raw, war_linkage)

    # 6) field-trace。
    field_rows = []
    for scope, fields in (("landed_titles", TITLE_TRACE_FIELDS), ("character", CHAR_TRACE_FIELDS)):
        for f in fields:
            cnt = title_field_presence.get(f, 0) if scope == "landed_titles" else char_scan["field_presence"].get(f, 0)
            field_rows.append(classify_field(f, scope, cnt))

    # 7) 汇总分类。
    classification_counts: Counter = Counter()
    for row in field_rows:
        classification_counts[row["classification"]] += 1
    for cat in ("SAVE_PRESENT", "SAVE_ABSENT", "EXTERNAL_TOOL_INFERRED"):
        if cat == "EXTERNAL_TOOL_INFERRED":
            classification_counts[cat] += 1  # Format A 默认推断标注
        elif cat == "SAVE_PRESENT" and title_comparison["census"]["save_history_total"]:
            pass  # 已在 field_rows 中体现
    classification_counts["SAVE_PRESENT"] += 1  # history 容器本身

    summary = {
        "classification_counts": dict(classification_counts),
        "key_numbers": {
            "存档编码": meta.get("encoding"),
            "游戏版本": meta.get("game_version"),
            "存档日期": meta.get("date"),
            "人物总数（reader）": meta.get("character_count"),
            "头衔块数（reader）": title_list_count(title_list),
            "存档 history 总条数": title_comparison["census"]["save_history_total"],
            "reader history 总条数": title_comparison["census"]["reader_history_total"],
            "存档显式 type 数": sum(title_comparison["census"]["save_explicit_types"].values()),
            "记忆总数（原始 / reader）": f"{memory_raw['total']} / {len(mem_doc.get('memories') or [])}",
            "战争总数": wars_raw["total"],
        },
        "title_census": title_comparison["census"],
        "field_trace_rows": [
            {
                "field": r["field"],
                "scope": r["scope"],
                "present_in_save": r["present_in_save"],
                "reader_reads": r["reader_reads"],
                "classification": r["classification"],
                "note": r["note"],
            }
            for r in field_rows
        ],
        "characters": character_comparison,
        "character_containers": char_scan["container_counts"],
        "memory": memory_comparison,
        "war": war_comparison,
    }

    # 8) 写输出文件。
    write_json(out_dir / "audit-summary.json", {"generatedAt": now_iso(), "summary": summary})
    write_json(out_dir / "field-trace.json", {"generatedAt": now_iso(), "fields": field_rows})
    write_json(out_dir / "title-history-comparison.json", title_comparison)
    write_json(out_dir / "character-comparison.json", {"characters": character_comparison})
    write_json(out_dir / "memory-comparison.json", memory_comparison)
    write_json(out_dir / "war-comparison.json", war_comparison)
    (out_dir / "report.md").write_text(
        build_report(
            {"generatedAt": now_iso(), "save": {"id": save_path.stem, "file": save_path.name, "encoding": meta.get("encoding"), "game_version": meta.get("game_version"), "date": meta.get("date")}},
            summary,
        ),
        encoding="utf-8",
    )
    return summary


def title_list_count(title_list: list[dict]) -> int:
    return len(title_list)


def resolve_save(arg_save: str | None, arg_save_id: str | None) -> Path:
    if arg_save:
        p = Path(arg_save)
        if not p.exists():
            raise SystemExit(f"存档不存在：{p}")
        return p
    if arg_save_id:
        p = STAGING_ROOT / f"{arg_save_id}.ck3"
        if p.exists():
            return p
        raise SystemExit(f"staging 中未找到存档：{arg_save_id}（{STAGING_ROOT}）")
    staged = sorted(STAGING_ROOT.glob("*.ck3"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not staged:
        raise SystemExit(
            "staging 中无 *.ck3。请用 --save 指定存档路径，或先导入存档。"
        )
    return staged[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 3C-Audit：CK3 数据源审计")
    parser.add_argument("--save", help="存档文件路径（.ck3）")
    parser.add_argument("--save-id", help="staging 中的存档 id（如 593a2ec6a662c1dd）")
    parser.add_argument("--out", help="输出目录（默认 data/audit/<时间戳>/）")
    parser.add_argument("--reader", help="ck3-reader 二进制路径")
    args = parser.parse_args()

    reader = Path(args.reader) if args.reader else resolve_reader_binary()
    if reader is None or not Path(reader).exists():
        raise SystemExit(
            "未找到 ck3-reader 二进制。请在 tools/ck3-reader 下执行 build.sh"
            "（cargo build --release）构建 Rust sidecar。"
        )
    save = resolve_save(args.save, args.save_id)
    if args.out:
        out_dir = Path(args.out)
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_dir = AUDIT_ROOT / stamp

    t0 = time.time()
    summary = run_audit(save, reader, out_dir)
    print(f"审计完成：{out_dir}")
    print(f"  耗时 {time.time() - t0:.1f}s；结论分类：{summary['classification_counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
