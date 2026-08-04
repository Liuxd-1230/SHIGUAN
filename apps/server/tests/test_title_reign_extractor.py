"""TitleReignExtractor 单测（M3）。

验证：现任头衔 / 过往任职段聚合（Format A/B 混合）/ 头衔名解析顺序 /
未知日期诚实置空 / 占位表下 key 回退 / 契约字段完整。
"""
from models import TitleTier

from app.services.entity_index_builder import ReferenceResolver
from app.services.localization import LocalizationLoader
from app.services.title_reign_extractor import TitleReignExtractor, _date_key, _reign_runs


def _raw_titles() -> dict:
    return {
        "schema_version": 1,
        "reader_version": "0.1.0",
        "scan_ms": 1.0,
        "title_count": 2,
        "titles": [
            {
                "key": "k_papal_state",
                "name": "教宗国",
                "name_source": "save",
                "tier": "kingdom",
                "holder_id": "5371",
                "de_facto_liege_id": "123",
                "history": [
                    {"date": "30.1.1", "holder_id": "26", "kind": "holder"},
                    {"date": "64.10.13", "holder_id": "38", "kind": "holder"},
                    {"date": "311.12.3", "holder_id": "5371", "kind": "holder"},
                ],
            },
            {
                "key": "d_iconoclast",
                "name": "d_iconoclast",
                "name_source": "key",
                "tier": "duchy",
                "holder_id": None,
                "de_facto_liege_id": None,
                "history": [
                    {"date": "867.1.1", "holder_id": "5371", "kind": "holder"},
                    {"date": "900.5.20", "holder_id": "9999", "kind": "holder"},
                    {"date": "905.2.2", "holder_id": "5371", "kind": "holder"},
                ],
            },
        ],
        "warnings": [],
    }


def test_current_holder_is_current_title():
    ex = TitleReignExtractor()
    periods = ex.extract(_raw_titles(), "5371")
    papal = [p for p in periods if p.titleId == "k_papal_state"]
    assert len(papal) == 1
    assert papal[0].isCurrent is True
    assert papal[0].end is None
    assert papal[0].start == "311.12.3"
    assert papal[0].name == "教宗国"
    assert papal[0].tier == TitleTier.KINGDOM
    assert papal[0].sourcePath == "landed_titles/k_papal_state"


def test_past_reign_runs_closed_and_multiple():
    ex = TitleReignExtractor()
    periods = ex.extract(_raw_titles(), "5371")
    icon = sorted(
        (p for p in periods if p.titleId == "d_iconoclast"),
        key=lambda p: p.start or "",
    )
    # 两段：867.1.1→900.5.20、905.2.2→开放（但现任 holder 非 5371 → isCurrent=False）
    assert len(icon) == 2
    first, second = icon
    assert first.start == "867.1.1"
    assert first.end == "900.5.20"
    assert first.isCurrent is False
    assert second.start == "905.2.2"
    assert second.end is None  # 存档 history 末尾仍持有，但顶层 holder 不是他 → 不标现任
    assert second.isCurrent is False


def test_unlocalized_key_falls_back_to_key_not_fabricated():
    ex = TitleReignExtractor()
    periods = ex.extract(_raw_titles(), "9999")
    d = [p for p in periods if p.titleId == "d_iconoclast"]
    assert len(d) == 1
    # name_source=key → 不伪造名，name 即 key。
    assert d[0].name == "d_iconoclast"
    assert d[0].tier == TitleTier.DUCHY


def test_localization_resolves_key_name():
    loader = LocalizationLoader()
    loader._ingest_text("l_simp_chinese:\n d_iconoclast: \"反圣像派\"\n")
    ex = TitleReignExtractor(loc=loader)
    periods = ex.extract(_raw_titles(), "9999")
    d = [p for p in periods if p.titleId == "d_iconoclast"]
    assert d[0].name == "反圣像派"


def test_character_with_no_titles_returns_empty():
    ex = TitleReignExtractor()
    assert ex.extract(_raw_titles(), "404") == []


def test_reign_runs_empty_history_and_breaks():
    assert _reign_runs([], "1") == []
    history = [
        {"date": "1.1.1", "holder_id": "1", "kind": "holder"},
        {"date": "2.2.2", "holder_id": "2", "kind": "holder"},
        {"date": "3.3.3", "holder_id": "1", "kind": "holder"},
    ]
    runs = _reign_runs(history, "1")
    assert runs == [["1.1.1", "2.2.2"], ["3.3.3", None]]


def test_reign_runs_destroyed_breaks_run():
    history = [
        {"date": "1.1.1", "holder_id": "1", "kind": "holder"},
        {"date": "2.2.2", "holder_id": None, "kind": "destroyed"},
    ]
    assert _reign_runs(history, "1") == [["1.1.1", "2.2.2"]]


def test_date_key_numeric_order():
    # CK3 日期未零填充：字符串 "9.1.1" > "10.1.1" 但数值 9 < 10。
    assert _date_key("9.1.1") < _date_key("10.1.1")
    assert _date_key(None) > _date_key("9998.12.31")
    assert _date_key("bad") == (9999, 1, 1)


def test_resolver_fallback_used_for_name():
    # 无 loader、无 resolver 时 key 名不被伪造（已在 test_unlocalized 覆盖）；
    # 此处验证 resolver 命中时采用实体索引名。
    from models import (
        EntityIndex,
        EntityIndexEntry,
        EntityKeyKind,
        EntityKind,
        EntityKindIndex,
        EntityNameSource,
    )

    idx = EntityIndex(
        schemaVersion=1,
        readerVersion="0.1.0",
        scanMs=0.0,
        kinds={
            EntityKind.TITLE: EntityKindIndex(
                kind=EntityKind.TITLE,
                source="save:landed_titles.landed_titles",
                containerFound=True,
                count=1,
                unresolvedCount=0,
                entries={
                    "d_iconoclast": EntityIndexEntry(
                        id="d_iconoclast",
                        key="d_iconoclast",
                        keyKind=EntityKeyKind.LOC,
                        name="反圣像派",
                        nameSource=EntityNameSource.LOC,
                        resolved=True,
                    )
                },
            )
        },
        warnings=[],
    )
    ex = TitleReignExtractor(resolver=ReferenceResolver(idx))
    periods = ex.extract(_raw_titles(), "9999")
    d = [p for p in periods if p.titleId == "d_iconoclast"]
    assert d[0].name == "反圣像派"


# =============================================================================
# M3 追加：TitleProfileIndex（列表摘要位）+ 头衔时间线事件 + 告警
# =============================================================================

def test_index_primary_bits_picks_highest_tier_current():
    """primaryTitle 只依据“当前持有”：取等级最高者，isRuler=True、highestTitleTier 正确。"""
    from app.services.title_reign_extractor import TitleProfileIndex

    raw = {
        "titles": [
            {
                "key": "c_low",
                "name": "低级伯国",
                "name_source": "save",
                "tier": "county",
                "holder_id": "7",
                "history": [{"date": "750.1.1", "holder_id": "7", "kind": "holder"}],
            },
            {
                "key": "k_high",
                "name": "高级王国",
                "name_source": "save",
                "tier": "kingdom",
                "holder_id": "7",
                "history": [{"date": "760.1.1", "holder_id": "7", "kind": "holder"}],
            },
        ],
        "warnings": [],
    }
    idx = TitleProfileIndex(raw)
    bits = idx.primary_bits("7")
    assert bits.isRuler is True
    assert bits.highestTier == TitleTier.KINGDOM
    assert bits.primary is not None
    assert bits.primary.id == "k_high"
    assert bits.primary.name == "高级王国"
    assert bits.primary.resolved is True
    assert idx.periods("7") and idx.periods("7")[0].isCurrent
    # 无关人物没有头衔 → 非统治者、无主头衔。
    nobody = idx.primary_bits("404")
    assert nobody.primary is None and nobody.highestTier is None and nobody.isRuler is False


def test_index_multiple_same_tier_primary_inferred_warning():
    """多个同级当前头衔：按 id 稳定顺序取主头衔，并产生 inferred warning。"""
    from app.services.title_reign_extractor import TitleProfileIndex

    raw = {
        "titles": [
            {
                "key": "d_bbb",
                "name": "伯国乙",
                "name_source": "save",
                "tier": "duchy",
                "holder_id": "9",
                "history": [],
            },
            {
                "key": "d_aaa",
                "name": "伯国甲",
                "name_source": "save",
                "tier": "duchy",
                "holder_id": "9",
                "history": [],
            },
        ],
        "warnings": [],
    }
    idx = TitleProfileIndex(raw)
    bits = idx.primary_bits("9")
    # 稳定顺序：d_aaa < d_bbb。
    assert bits.primary.id == "d_aaa"
    assert bits.highestTier == TitleTier.DUCHY
    # warningCount 计入多同级推断；warnings 含 primary_title_inferred。
    assert bits.warningCount == 1
    codes = {w.code for w in idx.warnings("9")}
    assert "primary_title_inferred" in codes


def test_index_all_unknown_tier_primary_none():
    """等级全部未知 → 主头衔留空（不强行推断），仅 isRuler 依“持有头衔”。"""
    from app.services.title_reign_extractor import TitleProfileIndex

    raw = {
        "titles": [
            {
                "key": "zz_custom",
                "name": "自定义头衔",
                "name_source": "save",
                "tier": "unknown",
                "holder_id": "5",
                "history": [],
            }
        ],
        "warnings": [],
    }
    idx = TitleProfileIndex(raw)
    bits = idx.primary_bits("5")
    assert bits.isRuler is True
    assert bits.primary is None
    assert bits.highestTier is None
    codes = {w.code for w in idx.warnings("5")}
    assert "primary_title_unresolved" in codes


def test_index_holder_conflict_warning_not_silently_overwritten():
    """顶层 holder 与 history 末项 holder 冲突 → warning，且现任仍按顶层 holder。"""
    from app.services.title_reign_extractor import TitleProfileIndex

    raw = {
        "titles": [
            {
                "key": "k_conflict",
                "name": "冲突王国",
                "name_source": "save",
                "tier": "kingdom",
                "holder_id": "1",
                "history": [
                    {"date": "700.1.1", "holder_id": "2", "kind": "holder"},
                    {"date": "710.1.1", "holder_id": "3", "kind": "holder"},
                ],
            }
        ],
        "warnings": [],
    }
    idx = TitleProfileIndex(raw)
    bits = idx.primary_bits("1")
    assert bits.isRuler is True
    assert bits.primary.id == "k_conflict"
    codes = {w.code for w in idx.warnings("1")}
    assert "title_holder_conflict" in codes
    # 冲突不静默覆盖：人物 1 现任该头衔（按顶层 holder）。
    assert any(p.isCurrent for p in idx.periods("1"))


def test_index_ruler_ids_only_current_holders():
    from app.services.title_reign_extractor import TitleProfileIndex

    raw = {
        "titles": [
            {
                "key": "d_alpha",
                "name": "阿尔法",
                "name_source": "save",
                "tier": "duchy",
                "holder_id": "1",
                "history": [],
            },
            {
                "key": "c_beta",
                "name": "贝塔",
                "name_source": "save",
                "tier": "county",
                "holder_id": None,
                "history": [
                    {"date": "770.1.1", "holder_id": "2", "kind": "holder"},
                    {"date": "790.1.1", "holder_id": "3", "kind": "holder"},
                ],
            },
        ],
        "warnings": [],
    }
    idx = TitleProfileIndex(raw)
    assert idx.ruler_ids() == {"1"}  # 2/3 仅是历史 holder，不是现任。


def test_build_title_events_gain_loss_succession_with_evidence():
    """头衔事件：每段有起止日 → title_gain/title_loss；现任主头衔起点 → succession(inferred)。
    每条事件都带 EvidenceRef，sourcePath 均为 landed_titles/...（无本地绝对路径）。"""
    from app.services.title_reign_extractor import (
        TitleProfileIndex,
        build_title_events,
    )

    raw = {
        "titles": [
            {
                "key": "d_alpha",
                "name": "阿尔法公国",
                "name_source": "save",
                "tier": "duchy",
                "holder_id": "1",
                "history": [
                    {"date": "760.1.1", "holder_id": "9", "kind": "holder"},
                    {"date": "780.5.10", "holder_id": "1", "kind": "holder"},
                ],
            },
            {
                "key": "c_beta",
                "name": "贝塔伯国",
                "name_source": "save",
                "tier": "county",
                "holder_id": None,
                "history": [
                    {"date": "770.2.2", "holder_id": "1", "kind": "holder"},
                    {"date": "790.3.3", "holder_id": "3", "kind": "holder"},
                ],
            },
        ],
        "warnings": [],
    }
    idx = TitleProfileIndex(raw)
    periods = idx.periods("1")
    bits = idx.primary_bits("1")
    primary_period = next(
        (p for p in periods if p.isCurrent and p.titleId == bits.primary.id), None
    )
    events = build_title_events("1", "阿尔法", periods, primary_period)

    types = {e.type.value for e in events}
    assert "title_gain" in types and "title_loss" in types and "succession" in types
    gain = [e for e in events if e.type.value == "title_gain"]
    assert len(gain) == 2  # d_alpha@780.5.10 + c_beta@770.2.2
    for e in events:
        assert e.evidence, f"事件 {e.id} 缺 EvidenceRef"
        for ev in e.evidence:
            assert ev.sourcePath.startswith("landed_titles/")
            assert ":" not in ev.sourcePath and "\\" not in ev.sourcePath  # 无本地路径
    succ = [e for e in events if e.type.value == "succession"]
    assert len(succ) == 1
    assert succ[0].confidence.value == "inferred"
    assert succ[0].date == "780.5.10"
    assert succ[0].relatedTitles[0].id == "d_alpha"


def test_build_title_events_no_fabricated_dates():
    """现任但无 history 段（start=None）→ 不生成无日期的事件（不伪造日期）。"""
    from app.services.title_reign_extractor import (
        TitleProfileIndex,
        build_title_events,
    )

    raw = {
        "titles": [
            {
                "key": "d_new",
                "name": "新公爵领",
                "name_source": "save",
                "tier": "duchy",
                "holder_id": "4",
                "history": [],
            }
        ],
        "warnings": [],
    }
    idx = TitleProfileIndex(raw)
    periods = idx.periods("4")
    bits = idx.primary_bits("4")
    assert periods and periods[0].start is None and periods[0].isCurrent
    primary_period = next(
        (p for p in periods if p.isCurrent and p.titleId == bits.primary.id), None
    )
    events = build_title_events("4", "某君", periods, primary_period)
    assert events == []  # 无日期 → 诚实不造事件


def test_index_periods_equal_extractor_extract():
    """TitleProfileIndex.periods 与 TitleReignExtractor.extract 输出一致（同一套逻辑）。"""
    from app.services.title_reign_extractor import TitleProfileIndex

    ex = TitleReignExtractor()
    idx = TitleProfileIndex(_raw_titles())
    for cid in ("5371", "9999", "404"):
        assert idx.periods(cid) == ex.extract(_raw_titles(), cid)


def test_index_two_saves_same_character_id_isolated():
    """两个存档含同一人物 id：索引按原始 titles 各自独立，不串数据。"""
    from app.services.title_reign_extractor import TitleProfileIndex

    raw_a = {
        "titles": [
            {
                "key": "d_a",
                "name": "存档甲公国",
                "name_source": "save",
                "tier": "duchy",
                "holder_id": "1",
                "history": [],
            }
        ],
        "warnings": [],
    }
    raw_b = {
        "titles": [
            {
                "key": "d_b",
                "name": "存档乙公国",
                "name_source": "save",
                "tier": "county",
                "holder_id": "1",
                "history": [],
            }
        ],
        "warnings": [],
    }
    idx_a, idx_b = TitleProfileIndex(raw_a), TitleProfileIndex(raw_b)
    assert idx_a.primary_bits("1").primary.id == "d_a"
    assert idx_b.primary_bits("1").primary.id == "d_b"
    assert [p.titleId for p in idx_a.periods("1")] == ["d_a"]
    assert [p.titleId for p in idx_b.periods("1")] == ["d_b"]


def test_build_title_events_aggregates_same_day_multi_title_gain():
    """M3 收口（2C.1）：同一天获得多个头衔 → 聚合为一条事件。

    一次战争/继承往往同日获多地；逐条刷屏会淹没叙事。聚合事件保留
    全部 relatedTitles 与 evidence，但不写战争原因（无关联字段），
    也不设 mergedCount（那是"重复记录去重"语义）。
    """
    from app.services.title_reign_extractor import TitleProfileIndex, build_title_events

    raw = {
        "titles": [
            {
                "key": "c_jia",
                "name": "甲伯爵领",
                "name_source": "save",
                "tier": "county",
                "holder_id": "1",
                "history": [
                    {"date": "950.8.16", "holder_id": "9", "kind": "holder"},
                    {"date": "952.8.16", "holder_id": "1", "kind": "holder"},
                ],
            },
            {
                "key": "c_yi",
                "name": "乙伯爵领",
                "name_source": "save",
                "tier": "county",
                "holder_id": "1",
                "history": [
                    {"date": "952.8.16", "holder_id": "1", "kind": "holder"},
                ],
            },
            {
                "key": "d_bing",
                "name": "丙公爵领",
                "name_source": "save",
                "tier": "duchy",
                "holder_id": "1",
                "history": [
                    {"date": "952.8.16", "holder_id": "1", "kind": "holder"},
                ],
            },
        ],
        "warnings": [],
    }
    idx = TitleProfileIndex(raw)
    events = build_title_events("1", "梁克贞", idx.periods("1"), None)

    gain = [e for e in events if e.type.value == "title_gain"]
    # 三个头衔同日获得 → 聚合为一条
    assert len(gain) == 1
    e = gain[0]
    assert e.date == "952.8.16"
    assert e.id == "1-title-gain-952.8.16"
    assert e.mergedCount is None  # 不污染"重复记录去重"语义
    assert [t.id for t in e.relatedTitles] == ["c_jia", "c_yi", "d_bing"]
    assert "甲伯爵领" in e.description and "乙伯爵领" in e.description and "丙公爵领" in e.description
    assert "战争" not in e.description  # 不编造战争原因
    assert len(e.evidence) == 3  # 组内全部证据可追溯
