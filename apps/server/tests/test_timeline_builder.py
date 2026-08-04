"""TimelineBuilder（M5）去重合并规则单元测试。

覆盖：同 child+date 双记忆记录合并、不同日期/人物不合并、无日期不合并、
证据按 id 聚合、mergedCount、排序稳定、空输入、跨来源（title+记忆）不误合并。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from models import (
    CharacterRef,
    Confidence,
    EntityRef,
    EvidenceRef,
    EventType,
    TimelineEvent,
)

from app.services.timeline_builder import merge_timeline


def _ev(
    eid: str,
    etype: EventType,
    date: str | None = None,
    rel: str | None = None,
    ev_id: str | None = None,
    loc: str | None = None,
    title: str | None = None,
) -> TimelineEvent:
    related = [CharacterRef(id=rel, name=rel)] if rel else []
    location = EntityRef(id=loc, name=loc, type="province", resolved=False) if loc else None
    titles = [EntityRef(id=title, name=title, type="title", resolved=True)] if title else []
    evid = ev_id or f"{eid}-ev"
    return TimelineEvent(
        id=eid,
        date=date,
        type=etype,
        title=etype.value,
        description=f"事件 {eid}",
        relatedCharacters=related,
        relatedTitles=titles,
        location=location,
        confidence=Confidence.CONFIRMED,
        evidence=[
            EvidenceRef(
                id=evid,
                sourceType="memory",
                sourcePath=f"mem/{eid}",
                rawKey=str(etype.value),
                description=f"证据 {eid}",
                confidence=Confidence.CONFIRMED,
            )
        ],
    )


def test_merge_duplicate_child_birth_same_child_date():
    """M5 核心：同一孩子同日出生的双记忆记录（child_born + first_born）合并为一条。"""
    a = _ev("c1-memory-1", EventType.CHILD_BIRTH, "758.4.11", rel="kid1", ev_id="ev-mem1")
    b = _ev("c1-memory-2", EventType.CHILD_BIRTH, "758.4.11", rel="kid1", ev_id="ev-mem2")
    r = merge_timeline([a, b])
    assert len(r.timeline) == 1
    assert r.merged_count == 1
    merged = r.timeline[0]
    # 主事件 = id 最小
    assert merged.id == "c1-memory-1"
    assert merged.mergedCount == 2
    # 证据按 id 聚合（两条都保留）
    assert {ev.id for ev in merged.evidence} == {"ev-mem1", "ev-mem2"}
    assert "1 条重复记录" in merged.description


def test_merge_keeps_zero_missing_evidence():
    """合并后证据完整：0 事件缺证据。"""
    a = _ev("c1-memory-1", EventType.CHILD_BIRTH, "758.4.11", rel="kid1", ev_id="ev-mem1")
    b = _ev("c1-memory-2", EventType.CHILD_BIRTH, "758.4.11", rel="kid1", ev_id="ev-mem2")
    r = merge_timeline([a, b])
    assert all(len(e.evidence) >= 1 for e in r.timeline)


def test_no_merge_different_date_or_person():
    """不同日期或不同孩子不合并（各自保留）。"""
    a = _ev("c1-memory-1", EventType.CHILD_BIRTH, "758.4.11", rel="kid1")
    b = _ev("c1-memory-2", EventType.CHILD_BIRTH, "758.4.11", rel="kid2")
    c = _ev("c1-memory-3", EventType.CHILD_BIRTH, "759.1.1", rel="kid1")
    r = merge_timeline([a, b, c])
    assert len(r.timeline) == 3
    assert r.merged_count == 0


def test_no_merge_without_date():
    """无日期事件不参与合并（日期不确定就不冒险合并）。"""
    a = _ev("c1-memory-1", EventType.MARRIAGE, None, rel="spouse1")
    b = _ev("c1-memory-2", EventType.MARRIAGE, None, rel="spouse1")
    r = merge_timeline([a, b])
    assert len(r.timeline) == 2
    assert r.merged_count == 0
    assert all(e.mergedCount is None or e.mergedCount == 1 for e in r.timeline)


def test_no_cross_source_merge_different_types():
    """跨来源不同事件类型不误合并：birth + title_gain 同日也不合并。"""
    birth = _ev("c1-birth", EventType.BIRTH, "750.1.1", rel=None)
    gain = _ev("c1-title-gain", EventType.TITLE_GAIN, "750.1.1", rel=None)
    r = merge_timeline([birth, gain])
    assert len(r.timeline) == 2
    assert r.merged_count == 0


def test_title_gain_same_title_same_date_merged():
    """同一头衔同一日期两条 gain 记录合并（relatedTitles 锚点）。"""
    a = _ev("c1-tg-1", EventType.TITLE_GAIN, "752.3.22", rel=None)
    b = _ev("c1-tg-2", EventType.TITLE_GAIN, "752.3.22", rel=None)
    # 用 relatedTitles 锚定
    for e in (a, b):
        e.relatedTitles = [EntityRef(id="k_foo", name="foo", type="title", resolved=True)]
    r = merge_timeline([a, b])
    assert len(r.timeline) == 1
    assert r.merged_count == 1
    assert r.timeline[0].mergedCount == 2


def test_sorted_by_ck3_date_numeric():
    """排序沿用 CK3 日期数值比较（未零填充），未知日期排最后。"""
    a = _ev("a", EventType.OTHER, "760.1.1")
    b = _ev("b", EventType.OTHER, "758.4.11")
    c = _ev("c", EventType.OTHER, None)
    r = merge_timeline([a, b, c])
    ids = [e.id for e in r.timeline]
    assert ids == ["b", "a", "c"]


def test_empty_input():
    r = merge_timeline([])
    assert r.timeline == []
    assert r.merged_count == 0


# ---------------------------------------------------------------------------
# M5.1：无可靠实体锚点 → 绝不自动合并（防同日同类不同事件误并）
# ---------------------------------------------------------------------------


def test_no_merge_same_type_date_without_anchor():
    """同类型 + 同日期 + 无实体锚点 → 不合并（两个不同事件各有各的独立记录）。"""
    a = _ev("e-imp-1", EventType.IMPRISONMENT, "770.1.1")
    b = _ev("e-imp-2", EventType.IMPRISONMENT, "770.1.1")
    r = merge_timeline([a, b])
    assert len(r.timeline) == 2
    assert r.merged_count == 0
    assert all(e.mergedCount is None or e.mergedCount == 1 for e in r.timeline)


def test_no_merge_same_type_date_different_person():
    """同类型 + 同日期 + 不同人物锚点 → 不合并。"""
    a = _ev("m1", EventType.MARRIAGE, "750.1.1", rel="spouse_a")
    b = _ev("m2", EventType.MARRIAGE, "750.1.1", rel="spouse_b")
    r = merge_timeline([a, b])
    assert len(r.timeline) == 2
    assert r.merged_count == 0


def test_no_merge_same_type_date_different_title():
    """同类型 + 同日期 + 不同头衔锚点 → 不合并。"""
    a = _ev("tg1", EventType.TITLE_GAIN, "752.3.22", title="k_a")
    b = _ev("tg2", EventType.TITLE_GAIN, "752.3.22", title="k_b")
    r = merge_timeline([a, b])
    assert len(r.timeline) == 2
    assert r.merged_count == 0


def test_no_merge_same_type_date_different_location():
    """同类型 + 同日期 + 不同地点锚点 → 不合并。"""
    a = _ev("w1", EventType.WAR, "760.6.1", loc="prov_1")
    b = _ev("w2", EventType.WAR, "760.6.1", loc="prov_2")
    r = merge_timeline([a, b])
    assert len(r.timeline) == 2
    assert r.merged_count == 0


def test_merge_same_type_date_same_anchor():
    """同类型 + 同日期 + 相同可靠锚点 → 合并（M5 既有行为不回归）。"""
    a = _ev("m1", EventType.MARRIAGE, "750.1.1", rel="spouse_x", ev_id="ev1")
    b = _ev("m2", EventType.MARRIAGE, "750.1.1", rel="spouse_x", ev_id="ev2")
    r = merge_timeline([a, b])
    assert len(r.timeline) == 1
    assert r.merged_count == 1
    assert r.timeline[0].mergedCount == 2
    # 合并后所有 EvidenceRef 保留
    assert {ev.id for ev in r.timeline[0].evidence} == {"ev1", "ev2"}


def test_merge_result_order_stable():
    """合并结果顺序稳定：同输入多次调用输出一致（不依赖哈希/字典顺序）。"""
    events = [
        _ev("m2", EventType.MARRIAGE, "750.1.1", rel="spouse_x"),
        _ev("b1", EventType.BIRTH, "726.1.1"),
        _ev("m1", EventType.MARRIAGE, "750.1.1", rel="spouse_x"),
        _ev("d1", EventType.DEATH, None),
    ]
    r1 = merge_timeline(events)
    r2 = merge_timeline(events)
    assert [e.id for e in r1.timeline] == [e.id for e in r2.timeline]
    assert r1.merged_count == r2.merged_count
    assert [e.id for e in r1.timeline] == ["b1", "m1", "d1"]
