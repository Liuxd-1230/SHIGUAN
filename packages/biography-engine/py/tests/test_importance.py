"""事件重要度评分测试（Phase 3A 5.5）。"""
from models import Confidence, EventType, TitleTier

from biography_engine.importance import score_event, score_event_breakdown

from factories import ev, make_profile, title_period


def test_high_priority_types_score_higher():
    p = make_profile()
    birth = ev("e-birth", EventType.BIRTH, "700.1.1")
    travel = ev("e-travel", EventType.TRAVEL, "710.1.1")
    assert score_event(birth, p) > score_event(travel, p)


def test_confirmed_beats_uncertain():
    p = make_profile()
    confirmed = ev("e1", EventType.TITLE_GAIN, "710.1.1", confidence=Confidence.CONFIRMED)
    uncertain = ev("e2", EventType.TITLE_GAIN, "710.1.1", confidence=Confidence.UNCERTAIN)
    assert score_event(confirmed, p) > score_event(uncertain, p)


def test_multiple_evidence_boosts():
    p = make_profile()
    one = ev("e1", EventType.CHILD_BIRTH, "730.1.1", evidence_count=1)
    two = ev("e2", EventType.CHILD_BIRTH, "730.1.1", evidence_count=2)
    assert score_event(two, p) > score_event(one, p)


def test_merged_boosts():
    p = make_profile()
    plain = ev("e1", EventType.CHILD_BIRTH, "730.1.1")
    merged = ev("e2", EventType.CHILD_BIRTH, "730.1.1", merged_count=2)
    assert score_event(merged, p) > score_event(plain, p)


def test_no_date_penalty():
    p = make_profile()
    dated = ev("e1", EventType.WAR, "740.1.1")
    undated = ev("e2", EventType.WAR, None)
    assert score_event(dated, p) > score_event(undated, p)


def test_top_title_boost():
    p = make_profile(titles=[title_period("k_x", "某王国", TitleTier.KINGDOM, "750.1.1")])
    gain_king = ev("e1", EventType.TITLE_GAIN, "750.1.1")
    p2 = make_profile(titles=[])
    gain_plain = ev("e2", EventType.TITLE_GAIN, "750.1.1")
    assert score_event(gain_king, p) > score_event(gain_plain, p2)


def test_unresolved_related_penalty():
    p = make_profile()
    resolved = ev("e1", EventType.MARRIAGE, "740.1.1", rel="spouse", rel_resolved=True)
    unresolved = ev("e2", EventType.MARRIAGE, "740.1.1", rel="7777", rel_resolved=False)
    assert score_event(resolved, p) > score_event(unresolved, p)


def test_score_deterministic():
    p = make_profile()
    e = ev("e1", EventType.SUCCESSION, "760.1.1", merged_count=2)
    assert score_event(e, p) == score_event(e, p)


def test_breakdown_explains_parts():
    p = make_profile()
    e = ev("e-birth", EventType.BIRTH, "700.1.1", confidence=Confidence.CONFIRMED)
    b = score_event_breakdown(e, p)
    assert b["type"] > 0
    assert b["confidence"] == 10
    assert b["date"] == 5
