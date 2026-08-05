"""Phase 3C.3 历史语义事件测试：同日按语义类型拆分 + 因果解析诚实性。

验收要点：
  - 同一日获得主权王国 + 官职 + 机构 → 拆分为多条语义事件（不再一条刷屏）；
  - territorial_gain 的因果：kind=created → creation；其余一律 unknown，
    且带「不得推断因果」叙事约束；
  - 时间相近（同日/同月）绝不推断继承/征服；
  - 主权领地获得 → identity_transition；官职 → office_appointment；
  - DYNASTY_IDENTITY 创建 → realm_created。
"""
from biography_engine.historical_events import (
    AcquisitionCauseResolver,
    HistoricalEventSemanticBuilder,
)
from biography_engine.title_semantics import (
    TitleDisplayResolver,
    TitleSemanticClassifier,
    TitleSemanticRuleRegistry,
)
from models import (
    AcquisitionCause,
    Confidence,
    EventType,
    HistoricalSemanticEventType,
    TitlePeriod,
)


def _period(key, name, start=None, end=None, current=False):
    return TitlePeriod(
        titleId=key,
        name=name,
        start=start,
        end=end,
        isCurrent=current,
        sourcePath=f"landed_titles/{key}",
    )


def _entry(key, tier=None, liege=None, name=None, name_source=None, history=None):
    return {
        "key": key,
        "name": name,
        "name_source": name_source,
        "tier": tier,
        "holder_id": "p1",
        "de_facto_liege_id": liege,
        "history": history or [],
    }


def _classifier():
    return TitleSemanticClassifier(
        TitleSemanticRuleRegistry(), TitleDisplayResolver(None)
    )


def _builder(entries, name="梁某"):
    classifier = _classifier()
    cls, _ = classifier.classify_all(entries)
    entries_by_key = {e["key"]: e for e in entries}
    return HistoricalEventSemanticBuilder("p1", name, cls, entries_by_key)


# ---------------------------------------------------------------------------
# 同日按语义类型拆分
# ---------------------------------------------------------------------------

def test_same_day_multi_semantic_types_split():
    entries = [
        _entry("k_dali", tier="kingdom", liege=None, name="大理", name_source="save",
               history=[{"date": "952.8.16", "holder_id": "p1", "kind": "holder"}]),
        _entry("e_minister_shizheng", name="政事堂", name_source="save",
               history=[{"date": "952.8.16", "holder_id": "p1", "kind": "holder"}]),
        _entry("x_nf_1486", name="梁家族", name_source="save",
               history=[{"date": "952.8.16", "holder_id": "p1", "kind": "created"}]),
    ]
    periods = [
        _period("k_dali", "大理", start="952.8.16", current=True),
        _period("e_minister_shizheng", "政事堂", start="952.8.16", current=True),
        _period("x_nf_1486", "梁家族", start="952.8.16", current=True),
    ]
    sem_events, timeline = _builder(entries).build(periods)

    # 三条语义事件（不是一条）。
    assert len(sem_events) == 3
    types = {e.semanticType for e in sem_events}
    assert types == {
        HistoricalSemanticEventType.IDENTITY_TRANSITION,
        HistoricalSemanticEventType.INSTITUTION_TRANSITION,
        HistoricalSemanticEventType.REALM_CREATED,
    }
    # 时间线同样拆分为 3 条。
    assert len(timeline) == 3
    assert {t.title for t in timeline} == {"身份转变", "机构任职", "领地被创建"}


def test_territorial_loss_has_cause_unknown_constraint():
    entries = [
        _entry("k_viet", tier="kingdom", liege="k_dali", name="安南", name_source="save",
               history=[{"date": "955.1.22", "holder_id": "other", "kind": "holder"}]),
    ]
    periods = [
        _period("k_viet", "安南", start="950.1.1", end="955.1.22", current=False),
    ]
    sem_events, _ = _builder(entries).build(periods)
    loss = [e for e in sem_events if e.semanticType == HistoricalSemanticEventType.TERRITORIAL_LOSS]
    assert len(loss) == 1
    # 失去事件不携带获得原因（避免张冠李戴）。
    assert loss[0].acquisitionCause is None


def test_gain_cause_creation_confirmed():
    entries = [
        _entry("k_dali", tier="kingdom", liege=None, name="大理", name_source="save",
               history=[{"date": "952.8.16", "holder_id": "p1", "kind": "created"}]),
    ]
    periods = [_period("k_dali", "大理", start="952.8.16", current=True)]
    sem_events, timeline = _builder(entries).build(periods)
    assert len(sem_events) == 1
    ev = sem_events[0]
    assert ev.acquisitionCause == AcquisitionCause.CREATION
    assert ev.narrativeConstraints == []
    # 时间线事件带「创建」说明。
    assert "创建" in timeline[0].description


def test_gain_cause_unknown_no_inference():
    entries = [
        _entry("k_viet", tier="kingdom", liege=None, name="安南", name_source="save",
               history=[{"date": "950.3.9", "holder_id": "p1", "kind": "holder"}]),
    ]
    periods = [_period("k_viet", "安南", start="950.3.9", current=True)]
    sem_events, _ = _builder(entries).build(periods)
    ev = sem_events[0]
    assert ev.semanticType == HistoricalSemanticEventType.IDENTITY_TRANSITION
    assert ev.acquisitionCause == AcquisitionCause.UNKNOWN
    assert any("不得推断" in c for c in ev.narrativeConstraints)


def test_close_dates_do_not_infer_causality():
    """时间相近（获得后 3 天另一头衔）绝不把后者的获得归因为前者的因果。"""
    entries = [
        _entry("k_dali", tier="kingdom", liege=None, name="大理", name_source="save",
               history=[{"date": "952.8.16", "holder_id": "p1", "kind": "created"}]),
        _entry("k_viet", tier="kingdom", liege=None, name="安南", name_source="save",
               history=[{"date": "952.8.19", "holder_id": "p1", "kind": "holder"}]),
    ]
    periods = [
        _period("k_dali", "大理", start="952.8.16", current=True),
        _period("k_viet", "安南", start="952.8.19", current=True),
    ]
    sem_events, _ = _builder(entries).build(periods)
    dali = [e for e in sem_events if "大理" in e.summary]
    anan = [e for e in sem_events if "安南" in e.summary]
    assert len(dali) == 1 and len(anan) == 1
    # 大理是创建（confirmed）；安南虽是 3 天后获得，但没有 war→title 关联 → UNKNOWN。
    assert dali[0].acquisitionCause == AcquisitionCause.CREATION
    assert dali[0].confidence == Confidence.CONFIRMED
    assert anan[0].acquisitionCause == AcquisitionCause.UNKNOWN
    assert any("不得推断" in c for c in anan[0].narrativeConstraints)


def test_office_appointment_event_mapping():
    entries = [_entry("e_minister_li", name="吏部", name_source="save")]
    periods = [_period("e_minister_li", "吏部", start="948.2.1", end="950.6.1")]
    sem_events, timeline = _builder(entries).build(periods)
    sem_types = {e.semanticType for e in sem_events}
    assert sem_types == {
        HistoricalSemanticEventType.INSTITUTION_TRANSITION,
        HistoricalSemanticEventType.INSTITUTION_TRANSITION,
    }  # 就任 + 离任同为 institution_transition
    assert len(sem_events) == 2
    assert timeline[0].type == EventType.TITLE_GAIN
    assert timeline[1].type == EventType.TITLE_LOSS
    assert "就任" in timeline[0].title or timeline[0].title == "机构任职"


def test_acquisition_cause_resolver_missing_entry():
    r = AcquisitionCauseResolver()
    cause, conf, constraints, raw, src = r.resolve(None, "950.1.1")
    assert cause == AcquisitionCause.UNKNOWN
    assert conf == Confidence.UNCERTAIN
    assert constraints
    assert raw is None
    assert src.value == "unknown"


def test_acquisition_cause_resolver_destroyed_not_cause():
    r = AcquisitionCauseResolver()
    entry = _entry("k_x", history=[{"date": "950.1.1", "holder_id": None, "kind": "destroyed"}])
    cause, conf, _, raw, src = r.resolve(entry, "950.1.1")
    assert cause == AcquisitionCause.UNKNOWN
    assert src.value == "reader_default"


def test_acquisition_cause_resolver_save_explicit_conquest():
    """3C-Audit：存档显式 type=conquest → 确认征服（save_explicit），不再一律 unknown。"""
    r = AcquisitionCauseResolver()
    entry = _entry(
        "c_mayo",
        history=[
            {
                "date": "953.11.18",
                "holder_id": "25990",
                "kind": "other",
                "raw_type": "conquest",
            }
        ],
    )
    cause, conf, constraints, raw, src = r.resolve(entry, "953.11.18")
    assert cause == AcquisitionCause.CONQUEST
    assert conf == Confidence.CONFIRMED
    assert not constraints  # 显式 type 不再套「不得推断因果」约束
    assert raw == "conquest"
    assert src.value == "save_explicit"


def test_acquisition_cause_resolver_save_explicit_granted_and_usurped():
    r = AcquisitionCauseResolver()
    for raw, want in (
        ("granted", AcquisitionCause.GRANT),
        ("conquest_holy_war", AcquisitionCause.CONQUEST),
        ("conquest_claim", AcquisitionCause.CONQUEST),
        ("conquest_populist", AcquisitionCause.CONQUEST),
        ("usurped", AcquisitionCause.USURPATION),
    ):
        entry = _entry(
            "c_x",
            history=[{"date": "950.1.1", "holder_id": "p2", "kind": "other", "raw_type": raw}],
        )
        cause, conf, constraints, rraw, src = r.resolve(entry, "950.1.1")
        assert cause == want, f"{raw} → {cause}"
        assert conf == Confidence.CONFIRMED
        assert rraw == raw
        assert src.value == "save_explicit"


def test_acquisition_cause_resolver_save_explicit_unmapped_keeps_raw():
    """3C-Audit：显式 type 但暂无映射（appointment_succession）→ 保留 raw，不擅自归并。"""
    r = AcquisitionCauseResolver()
    entry = _entry(
        "k_viet",
        history=[
            {
                "date": "955.1.22",
                "holder_id": "20423",
                "kind": "other",
                "raw_type": "appointment_succession",
            }
        ],
    )
    cause, conf, constraints, raw, src = r.resolve(entry, "955.1.22")
    assert cause == AcquisitionCause.UNKNOWN
    assert raw == "appointment_succession"
    assert src.value == "save_explicit"
    assert any("不得推断" in c for c in constraints)


def test_acquisition_cause_resolver_legacy_created_is_reader_default():
    """旧缓存（无 raw_type）：kind=created 仍可证创建，但标记 reader_default。"""
    r = AcquisitionCauseResolver()
    entry = _entry("k_x", history=[{"date": "950.1.1", "holder_id": "p2", "kind": "created"}])
    cause, conf, constraints, raw, src = r.resolve(entry, "950.1.1")
    assert cause == AcquisitionCause.CREATION
    assert conf == Confidence.CONFIRMED
    assert raw == "created"
    assert src.value == "reader_default"


def test_builder_passes_raw_type_into_semantic_event():
    """3C-Audit：语义事件带出 acquisitionRawType / acquisitionTypeSource（契约可追溯）。"""
    entries = [
        _entry(
            "c_mayo",
            tier="county",
            liege=None,
            name="梅奥",
            name_source="save",
            history=[
                {"date": "953.11.18", "holder_id": "p1", "kind": "other", "raw_type": "conquest"}
            ],
        )
    ]
    periods = [_period("c_mayo", "梅奥", start="953.11.18", current=True)]
    sem_events, _ = _builder(entries).build(periods)
    gain = [e for e in sem_events if e.semanticType.value == "territorial_gain"]
    assert len(gain) == 1
    assert gain[0].acquisitionCause == AcquisitionCause.CONQUEST
    assert gain[0].acquisitionRawType == "conquest"
    assert gain[0].acquisitionTypeSource.value == "save_explicit"
    # 证据描述如实提及存档显式 type。
    assert any("type=conquest" in ev.description for ev in gain[0].evidence)
