"""确定性压缩器测试（Phase 3A 5.4/5.12）。"""
from models import CharacterRef, Confidence, EventType, TitleTier

from biography_engine.compressor import compress_profile
from biography_engine.models import COMPRESSION_VERSION

from factories import ev, make_profile, title_period


def _busy_profile():
    return make_profile(
        timeline=[
            ev("b1", EventType.BIRTH, "700.1.1"),
            ev("d1", EventType.DEATH, "780.6.6"),
            ev("t1", EventType.TITLE_GAIN, "740.1.1"),
            ev("m1", EventType.MARRIAGE, "735.1.1"),
            ev("c1", EventType.CHILD_BIRTH, "738.1.1"),
            ev("w1", EventType.WAR, "760.1.1"),
            ev("tr1", EventType.TRAVEL, "750.1.1"),
        ],
        titles=[title_period("k_x", "某王国", TitleTier.KINGDOM, "740.1.1")],
        parents=[CharacterRef(id="f1", name="父亲甲", resolved=True)],
        children=[CharacterRef(id="k1", name="7777", resolved=False)],
        friends=[CharacterRef(id="fr1", name="好友乙", resolved=True)],
    )


def test_same_input_same_output():
    a = compress_profile(_busy_profile(), max_events=40, include_inferred=True, include_uncertain=False)
    b = compress_profile(_busy_profile(), max_events=40, include_inferred=True, include_uncertain=False)
    assert a.model_dump() == b.model_dump()


def test_max_events_enforced():
    p = _busy_profile()
    cp = compress_profile(p, max_events=3, include_inferred=True, include_uncertain=True)
    assert len(cp.selectedEvents) == 3
    assert cp.omittedEventCount == len(p.timeline) - 3


def test_birth_and_death_always_kept():
    cp = compress_profile(_busy_profile(), max_events=2, include_inferred=True, include_uncertain=True)
    ids = [e.eventId for e in cp.selectedEvents]
    assert "b1" in ids and "d1" in ids


def test_top_title_event_kept():
    cp = compress_profile(_busy_profile(), max_events=3, include_inferred=True, include_uncertain=True)
    ids = [e.eventId for e in cp.selectedEvents]
    assert "t1" in ids  # 最高等级头衔事件（王国）必须保留


def test_stage_representation():
    """每个十年阶段至少保留一个代表事件。"""
    p = make_profile(
        timeline=[
            ev("e1", EventType.TRAVEL, "701.1.1"),
            ev("e2", EventType.TRAVEL, "711.1.1"),
            ev("e3", EventType.TRAVEL, "721.1.1"),
        ]
    )
    cp = compress_profile(p, max_events=40, include_inferred=True, include_uncertain=True)
    dates = {e.eventId: e.date for e in cp.selectedEvents}
    assert set(dates.values()) >= {"701.1.1", "711.1.1", "721.1.1"}


def test_include_inferred_switch():
    p = make_profile(
        timeline=[
            ev("confirmed", EventType.TITLE_GAIN, "740.1.1"),
            ev("inferred", EventType.MARRIAGE, "735.1.1", confidence=Confidence.INFERRED),
        ]
    )
    cp = compress_profile(p, max_events=40, include_inferred=False, include_uncertain=True)
    ids = [e.eventId for e in cp.selectedEvents]
    assert "inferred" not in ids
    assert "confirmed" in ids


def test_include_uncertain_switch():
    p = make_profile(
        timeline=[
            ev("confirmed", EventType.TITLE_GAIN, "740.1.1"),
            ev("uncertain", EventType.MARRIAGE, "735.1.1", confidence=Confidence.UNCERTAIN),
        ]
    )
    cp = compress_profile(p, max_events=40, include_inferred=True, include_uncertain=False)
    ids = [e.eventId for e in cp.selectedEvents]
    assert "uncertain" not in ids
    assert "confirmed" in ids


def test_unresolved_digit_name_not_in_natural_language():
    """resolved=false 且 name 为纯数字 → 不写入 relatedNames / familyFacts。"""
    p = _busy_profile()  # children 含 7777（resolved=False）
    cp = compress_profile(p, max_events=40, include_inferred=True, include_uncertain=True)
    # relatedNames 里不得出现纯数字名。
    for e in cp.selectedEvents:
        assert not any(n.isdigit() for n in e.relatedNames)
    # familyFacts 里不得出现 7777。
    assert not any("7777" in f for f in cp.familyFacts)
    # 但 unresolved 计数如实反映。
    assert cp.unresolvedCount >= 1


def test_source_event_ids_complete():
    cp = compress_profile(_busy_profile(), max_events=40, include_inferred=True, include_uncertain=True)
    assert cp.sourceEventIds == [e.eventId for e in cp.selectedEvents]
    # 全部来自原 timeline。
    original = {e.id for e in _busy_profile().timeline}
    assert set(cp.sourceEventIds) <= original


def test_no_fabricated_events():
    cp = compress_profile(_busy_profile(), max_events=40, include_inferred=True, include_uncertain=True)
    original = {e.id for e in _busy_profile().timeline}
    assert set(cp.sourceEventIds) <= original


def test_compression_version_set():
    cp = compress_profile(_busy_profile(), max_events=10, include_inferred=True, include_uncertain=True)
    assert cp.compressionVersion == COMPRESSION_VERSION


def test_selected_events_sorted_by_numeric_date():
    """CK3 日期未零填充（944.10.22 / 944.4.20）→ 必须数值排序。

    回归：此前按字符串排序会把 944.10.22 排在 944.4.20 之前（"944.1" < "944.4"），
    与真实时间顺序相反，导致提纲章节顺序校验误报倒置。
    """
    p = make_profile(
        timeline=[
            ev("late", EventType.TRAVEL, "944.10.22"),
            ev("early", EventType.TRAVEL, "944.4.20"),
            ev("first", EventType.TRAVEL, "919.1.1"),
        ]
    )
    cp = compress_profile(p, max_events=40, include_inferred=True, include_uncertain=True)
    dates = [e.date for e in cp.selectedEvents]
    assert dates == ["919.1.1", "944.4.20", "944.10.22"], dates
