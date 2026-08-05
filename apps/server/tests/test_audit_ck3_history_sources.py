"""Phase 3C-Audit 审计脚本链路测试：PDX 解析 + 对照分类（不依赖真实存档/reader）。

覆盖：
  - PDX 极简解析器（parse_pdx / extract_balanced / iter_blocks / iter_root_pairs）；
  - extract_title_histories 对 Format A / B 的还原，以及「同行多条不吞条」回归
    （v2 reader 的 Format A 行尾跳跃 bug 曾把 34,713 条 history 吞成 13,173 条）；
  - scan_character_containers 的玩家定位与字段存在性；
  - scan_memories_raw / scan_wars_raw / search_war_refs_in_title_history；
  - compare_title_history 的 kind 折叠对照与外部工具默认推断标注；
  - classify_field 的分类正确性。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from audit_ck3_history_sources import (  # noqa: E402
    PdxBlock,
    classify_field,
    compare_title_history,
    extract_balanced,
    extract_title_histories,
    iter_blocks,
    iter_root_pairs,
    parse_pdx,
    scan_character_containers,
    scan_memories_raw,
    scan_wars_raw,
    search_war_linkage_keys,
)


# ---------------------------------------------------------------------------
# PDX 解析器
# ---------------------------------------------------------------------------


def test_parse_pdx_nested_and_quoted():
    text = 'key = { a = 1 b = "你好 \\"世界\\"" c = { d = x } }'
    blk, _ = parse_pdx(text, text.find("{"))
    assert isinstance(blk, PdxBlock)
    assert blk.get("a") == "1"
    assert blk.get("b") == '你好 "世界"'
    assert isinstance(blk.get("c"), PdxBlock)
    assert blk.get("c").get("d") == "x"  # type: ignore[union-attr]


def test_parse_pdx_repeated_keys_preserved():
    text = "{ x = 1 x = 2 y = 3 }"
    blk, _ = parse_pdx(text, 0)
    assert blk.get_all("x") == ["1", "2"]
    assert blk.keys() == {"x", "y"}


def test_extract_balanced_handles_quotes():
    text = '{ a = "}{" b = 2 } tail'
    assert extract_balanced(text, 0) == '{ a = "}{" b = 2 }'
    assert text[extract_balanced(text, 0).__len__() :] == " tail"


def test_iter_blocks_skips_scalars_and_anonymous():
    text = "a = { b = 1 c = { d = 2 } { x = 3 } } tail"
    blk = extract_balanced(text, text.find("{"))
    inner_start, inner_end = 1, len(blk) - 1
    got = list(iter_blocks(blk, inner_start, inner_end))
    assert got == [("c", "{ d = 2 }"), (None, "{ x = 3 }")]


def test_iter_root_pairs_top_level():
    text = "meta = { a = 1 } landed_titles = { k_x = { } } tail"
    pairs = list(iter_root_pairs(text))
    assert [p[0] for p in pairs] == ["meta", "landed_titles", "tail"]
    assert pairs[1][2] == "block"
    assert pairs[2][1] is True  # 裸键（无 =）记 True


# ---------------------------------------------------------------------------
# 头衔 history 提取（含 Format A 同行不吞条回归）
# ---------------------------------------------------------------------------


def test_extract_title_histories_format_a_b_on_same_line():
    # 明文存档常把多条 history 写在同一行：Format A 的 `618.1.1=2068` 后面
    # 紧跟 Format B 的 `755.1.1={ type=created holder=2069 }`。
    # extract_title_histories 接收的是 landed_titles 容器**内部**文本。
    landed = (
        'k_test = { key="k_test" holder=2068 history={ 618.1.1=2068 '
        '755.1.1={ type=created holder=2069 } 760.1.1=2070 } }'
    )
    histories = extract_title_histories(landed)
    assert set(histories) == {"k_test"}
    entries = histories["k_test"].entries
    assert len(entries) == 3, "同行三条必须全部捕获（v2 reader 曾吞掉后续条目）"
    assert entries[0] == {"date": "618.1.1", "format": "A", "raw_type": None, "holder": "2068"}
    assert entries[1]["date"] == "755.1.1"
    assert entries[1]["format"] == "B"
    assert entries[1]["raw_type"] == "created"
    assert entries[1]["holder"] == "2069"
    assert entries[2] == {"date": "760.1.1", "format": "A", "raw_type": None, "holder": "2070"}


def test_extract_title_histories_preserves_raw_types():
    landed = (
        "k_a = { history = { 900.1.1={ type=granted holder=5 } "
        "900.2.2={ type=conquest holder=6 } 900.3.3={ type=created holder=7 } } }"
    )
    histories = extract_title_histories(landed)
    types = [e["raw_type"] for e in histories["k_a"].entries]
    assert types == ["granted", "conquest", "created"]


def test_extract_title_histories_field_counts():
    landed = (
        "k_b = { capital=1 holder=2 law=3 law=4 } "
        "k_c = { holder=8 de_facto_liege=9 }"
    )
    histories = extract_title_histories(landed)
    assert histories["k_b"].field_counts == {"capital": 1, "holder": 1, "law": 2}
    assert "de_facto_liege" in histories["k_c"].field_counts


def test_extract_title_histories_numeric_wrapper_uses_inner_key():
    # 存档嵌套 landed_titles 容器用数字包裹键，真正的头衔 key 在块内 key= 字段。
    landed = (
        "landed_titles = { dynamic_templates = {} "
        "landed_titles = { "
        "0 = { key=h_roman_empire date=285.7.1 history={ 3.1.27=27 100.1.1={ type=created holder=5 } } } "
        "1 = { key=k_viet holder=7 history={ 950.1.1=7 } } } "
        "index = 2 }"
    )
    histories = extract_title_histories(landed)
    assert set(histories) == {"h_roman_empire", "k_viet"}
    assert len(histories["h_roman_empire"].entries) == 2
    assert histories["h_roman_empire"].entries[1]["raw_type"] == "created"
    assert histories["k_viet"].entries[0] == {"date": "950.1.1", "format": "A", "raw_type": None, "holder": "7"}


# ---------------------------------------------------------------------------
# 人物容器 / 记忆 / 战争 原始扫描
# ---------------------------------------------------------------------------


def test_scan_character_containers_finds_player():
    text = (
        "living = { 10 = { first_name=\"甲\" was_player=yes landed_data={} dynasty_house=20 } "
        "11 = { first_name=\"乙\" family_data={} } } "
        "dead_unprunable = { 12 = { first_name=\"丙\" dead_data={ death=930.1.1 } } }"
    )
    scan = scan_character_containers(text, {"11"})
    assert scan["player_id"] == "10"
    assert "was_player=yes" in (scan["player_block"] or "")
    assert "11" in scan["wanted_blocks"]
    assert scan["container_counts"] == {"living": 2, "dead_unprunable": 1, "dead_prunable": 0}
    assert scan["field_presence"]["first_name"] >= 3
    assert scan["field_presence"]["was_player"] == 1
    assert scan["field_presence"]["dead_data"] == 1


def test_scan_memories_raw_census():
    text = (
        "database = { "
        "1={ type=war_won participants={ { role=winner character_id=9 } } } "
        '2={ type=became_friends params={ character=3 } } '
        "3={ type=war_won } }"
    )
    out = scan_memories_raw(text)
    assert out["total"] == 3
    assert out["type_census"] == {"war_won": 2, "became_friends": 1}
    assert out["type_count"] == 2


def test_scan_wars_raw_and_no_war_ref_in_title_history():
    wars = (
        "active_wars = { "
        "1={ start_date=950.1.1 attacker=10 defender=20 "
        'casus_belli={ type=conquest_war } } '
        "2={ start_date=951.1.1 attacker=11 defender=21 } }"
    )
    out = scan_wars_raw(wars)
    assert out["total"] == 2
    assert out["sub_containers"] == {"active_wars": 1}

    # 头衔 history 里只有 conquest* 显式 type，没有 war_id 之类的战争引用键。
    landed = "k_x = { history = { 950.2.2={ type=conquest holder=10 } } }"
    keys = search_war_linkage_keys(landed)
    assert all(v == 0 for v in keys.values())
    assert keys["war_id"] == 0


# ---------------------------------------------------------------------------
# 对照与分类
# ---------------------------------------------------------------------------


def _raw_histories():
    # 传 landed_titles 容器**内部**文本。
    landed = (
        "k_x = { history = { 618.1.1=2068 "
        '755.1.1={ type=created holder=2069 } 900.1.1={ type=granted holder=2070 } } }'
    )
    return extract_title_histories(landed)


def test_compare_title_history_kind_folding_detected():
    raw = _raw_histories()
    reader_titles = [
        {
            "key": "k_x",
            "history": [
                {"date": "618.1.1", "holder_id": "2068", "kind": "holder"},
                {"date": "755.1.1", "holder_id": "2069", "kind": "created"},
                {"date": "900.1.1", "holder_id": "2070", "kind": "other"},
            ],
        }
    ]
    cmp = compare_title_history(raw, reader_titles, ["k_x"])
    assert cmp["selected_titles"][0]["raw_total"] == 3
    assert cmp["selected_titles"][0]["reader_total"] == 3
    # granted 被 v2 折叠成 other → 标记为 kind_folded。
    folded = cmp["selected_titles"][0]["kind_folded_entries"]
    assert any("type=granted" in f for f in folded)
    assert cmp["selected_titles"][0]["reader_missing_dates"] == []
    assert (
        cmp["selected_titles"][0]["external_tool_inference"]["format_a_default"]
        == "Inherited"
    )


def test_classify_field_categories():
    row = classify_field("capital", "landed_titles", 5)
    assert row["present_in_save"] is True
    assert row["classification"] == "READER_DROPPED"
    row2 = classify_field("primary_title", "landed_titles", 0)
    assert row2["present_in_save"] is False
    assert row2["classification"] == "SAVE_ABSENT"
    row3 = classify_field("holder", "landed_titles", 3)
    assert row3["classification"] == "SAVE_PRESENT"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
