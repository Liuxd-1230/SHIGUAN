"""WarNarrativeNormalizer 测试（Phase 3A.1）。"""
from models import CharacterRef, Confidence, EventType, TimelineEvent

from biography_engine.war_narrative import WarNarrativeNormalizer


def _war_ev(eid: str, title: str, date: str, opp: str | None = None, opp_resolved: bool = True):
    related = (
        [CharacterRef(id=opp, name=opp, resolved=opp_resolved)] if opp else []
    )
    return TimelineEvent(
        id=eid,
        type=EventType.WAR,
        title=title,
        description=f"事件 {eid}。",
        date=date,
        relatedCharacters=related,
        confidence=Confidence.CONFIRMED,
        evidence=[],
    )


def _ev(eid: str, etype: EventType, date: str, title: str):
    return TimelineEvent(
        id=eid,
        type=etype,
        title=title,
        description=f"事件 {eid}。",
        date=date,
        confidence=Confidence.CONFIRMED,
        evidence=[],
    )


def test_war_won_with_opponent():
    events = [_war_ev("w1", "战争获胜", "952.8.16", opp="梁某")]
    out = WarNarrativeNormalizer().to_text(events)
    assert out == ["952.8.16 赢得一场战争，对手：梁某。"]


def test_war_lost_with_opponent():
    events = [_war_ev("w1", "战争失利", "953.1.1", opp="某部落")]
    out = WarNarrativeNormalizer().to_text(events)
    assert out == ["953.1.1 在一场战争中失利，对方：某部落。"]


def test_defensive_war_not_written_as_declared():
    """defender 绝不写成主动宣战。"""
    events = [_war_ev("w1", "卷入防御战争", "954.2.2", opp="入侵者")]
    out = WarNarrativeNormalizer().to_text(events)
    assert out == ["954.2.2 卷入一场防御战争，对方：入侵者。"]


def test_offensive_war_is_participation_not_declaration():
    """attacker 不等于宣战方，写「卷入进攻战争」而非「发动战争」。"""
    events = [_war_ev("w1", "卷入进攻战争", "954.3.3", opp="邻国")]
    out = WarNarrativeNormalizer().to_text(events)
    assert out == ["954.3.3 卷入一场进攻战争，对方：邻国。"]


def test_battle_events_excluded():
    """battle_* 单场小战役不进叙事。"""
    events = [
        _ev("b1", EventType.WAR, "950.1.1", "战役获胜"),
        _war_ev("w1", "战争获胜", "952.8.16", opp="梁某"),
    ]
    out = WarNarrativeNormalizer().normalize(events)
    assert [n.text for n in out] == ["952.8.16 赢得一场战争，对手：梁某。"]


def test_unresolved_opponent_omitted():
    """对手为未解析数字名 → 不写占位名。"""
    events = [_war_ev("w1", "战争获胜", "952.8.16", opp="7777", opp_resolved=False)]
    out = WarNarrativeNormalizer().to_text(events)
    assert out == ["952.8.16 赢得一场战争。"]


def test_sorted_by_date():
    events = [
        _war_ev("w2", "战争获胜", "952.8.16", opp="乙"),
        _war_ev("w1", "战争获胜", "952.8.16", opp="甲"),
        _war_ev("w0", "卷入防御战争", "950.1.1", opp="丙"),
    ]
    out = WarNarrativeNormalizer().to_text(events)
    assert out[0] == "950.1.1 卷入一场防御战争，对方：丙。"
    # 同日按对手名升序（乙 U+4E59 < 甲 U+7532）。
    assert out[1] == "952.8.16 赢得一场战争，对手：乙。"
    assert out[2] == "952.8.16 赢得一场战争，对手：甲。"
