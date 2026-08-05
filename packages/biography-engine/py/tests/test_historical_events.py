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
    assert {t.title for t in timeline} == {"身份转变", "机构归属变化", "领地被创建"}


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
    # 3C.7：政权机构不写「就任/任职」语义。
    assert timeline[0].title == "机构归属变化"
    assert "就任" not in timeline[0].title and "任职" not in timeline[0].title
    # 机构事件固定携带「不代表个人任职」叙事约束。
    for ev in sem_events:
        assert any("不代表人物本人在该机构任职" in c for c in ev.narrativeConstraints)


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


def test_acquisition_cause_resolver_save_explicit_appointment_succession():
    """3C.7：appointment_succession → 行政任命体系下继任（≠世袭继承，保留 raw）。"""
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
    assert cause == AcquisitionCause.ADMINISTRATIVE_TRANSFER
    assert conf == Confidence.CONFIRMED
    assert not constraints
    assert raw == "appointment_succession"
    assert src.value == "save_explicit"


def test_acquisition_cause_resolver_save_explicit_unmapped_keeps_raw():
    """3C-Audit：显式 type 但无映射（如 invented_action）→ 保留 raw，不擅自归并。"""
    r = AcquisitionCauseResolver()
    entry = _entry(
        "k_viet",
        history=[
            {
                "date": "955.1.22",
                "holder_id": "20423",
                "kind": "other",
                "raw_type": "invented_action",
            }
        ],
    )
    cause, conf, constraints, raw, src = r.resolve(entry, "955.1.22")
    assert cause == AcquisitionCause.UNKNOWN
    assert raw == "invented_action"
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


# ---------------------------------------------------------------------------
# 3C.7 P0：同日聚合必须按显式动作拆分，绝不取组内第一个 title 的原因
# ---------------------------------------------------------------------------

def _mixed_entries(*raws):
    """构造同日多条 county 变更（raw 为每条 history 的 raw_type/None）。"""
    return [
        _entry(
            f"c_{i}",
            tier="county",
            liege="k_x",
            name=f"县{i}",
            name_source="save",
            history=[
                {
                    "date": "953.11.18",
                    "holder_id": "p1",
                    "kind": "other" if raw else "holder",
                    **({"raw_type": raw} if raw else {}),
                }
            ],
        )
        for i, raw in enumerate(raws)
    ]


def test_same_day_mixed_causes_split_not_first_title():
    """同日 conquest / granted / None 三 title → 拆分为三条（不同 cause 绝不合并）。"""
    entries = _mixed_entries("conquest", "granted", None)
    periods = [_period(f"c_{i}", f"县{i}", start="953.11.18", current=True) for i in range(3)]
    sem_events, timeline = _builder(entries).build(periods)
    gains = [e for e in sem_events if e.semanticType.value == "territorial_gain"]
    assert len(gains) == 3, [e.summary for e in gains]
    causes = {e.acquisitionCause for e in gains}
    assert causes == {AcquisitionCause.CONQUEST, AcquisitionCause.GRANT, AcquisitionCause.UNKNOWN}
    # 事件 id 不冲突（同日同语义多组必须区分）。
    assert len({e.eventId for e in gains}) == 3
    assert len(timeline) == 3
    # 证据逐条绑定自身 raw_type（不把第一个 title 的 type 复制给整组）。
    by_cause = {e.acquisitionCause: e for e in gains}
    assert "type=conquest" in by_cause[AcquisitionCause.CONQUEST].evidence[0].description
    assert "type=granted" in by_cause[AcquisitionCause.GRANT].evidence[0].description
    unknown = by_cause[AcquisitionCause.UNKNOWN]
    assert "type=" not in unknown.evidence[0].description
    assert any("不得推断" in c for c in unknown.narrativeConstraints)


def test_same_day_multiple_conquest_merge():
    """同日多个 conquest 可以合并（同 normalizedAction + 同 cause）。"""
    entries = _mixed_entries("conquest", "conquest")
    periods = [_period(f"c_{i}", f"县{i}", start="953.11.18", current=True) for i in range(2)]
    sem_events, _ = _builder(entries).build(periods)
    gains = [e for e in sem_events if e.semanticType.value == "territorial_gain"]
    assert len(gains) == 1
    assert gains[0].acquisitionCause == AcquisitionCause.CONQUEST
    assert sorted(gains[0].relatedTitleIds) == ["c_0", "c_1"]
    assert gains[0].acquisitionRawType == "conquest"
    assert len(gains[0].evidence) == 2
    assert all("type=conquest" in ev.description for ev in gains[0].evidence)


def test_same_day_conquest_and_conquest_claim_merge_by_normalized_action():
    """同日 conquest 与 conquest_claim 是否合并由 normalizedAction 规则决定（同为 conquered）。"""
    entries = _mixed_entries("conquest", "conquest_claim")
    periods = [_period(f"c_{i}", f"县{i}", start="953.11.18", current=True) for i in range(2)]
    sem_events, _ = _builder(entries).build(periods)
    gains = [e for e in sem_events if e.semanticType.value == "territorial_gain"]
    assert len(gains) == 1
    assert gains[0].acquisitionCause == AcquisitionCause.CONQUEST
    assert gains[0].normalizedAction.value == "conquered"
    # 组内 raw_type 混合 → 事件级不复制第一个 title 的 type；证据逐条保留。
    assert gains[0].acquisitionRawType is None
    descs = [ev.description for ev in gains[0].evidence]
    assert any("type=conquest" in d for d in descs)
    assert any("type=conquest_claim" in d for d in descs)


def test_same_day_created_and_granted_never_merge():
    """同日 created 与 granted 绝不合并（不同 normalizedAction + 不同 cause）。"""
    entries = _mixed_entries("created", "granted")
    periods = [_period(f"c_{i}", f"县{i}", start="953.11.18", current=True) for i in range(2)]
    sem_events, _ = _builder(entries).build(periods)
    gains = [e for e in sem_events if e.semanticType.value == "territorial_gain"]
    assert len(gains) == 2
    causes = {e.acquisitionCause for e in gains}
    assert causes == {AcquisitionCause.CREATION, AcquisitionCause.GRANT}


def test_same_day_two_unknown_merge_keep_individual_evidence():
    """同日两个 unknown（无显式 type）可以合并，但保留各自 EvidenceRef。"""
    entries = _mixed_entries(None, None)
    periods = [_period(f"c_{i}", f"县{i}", start="953.11.18", current=True) for i in range(2)]
    sem_events, _ = _builder(entries).build(periods)
    gains = [e for e in sem_events if e.semanticType.value == "territorial_gain"]
    assert len(gains) == 1
    assert gains[0].acquisitionCause == AcquisitionCause.UNKNOWN
    assert any("不得推断" in c for c in gains[0].narrativeConstraints)
    assert len(gains[0].evidence) == 2
    assert {ev.id for ev in gains[0].evidence} == {
        "p1-c_0-953.11.18-ev",
        "p1-c_1-953.11.18-ev",
    }


def test_same_day_mixed_cause_never_overridden_by_first_title():
    """组内任一 title 原因不同，不能被第一个 title 覆盖（顺序无关）。"""
    # 第一个是 conquest，第二、三是 granted/None —— 必须仍拆分为三组。
    entries = _mixed_entries("conquest", "granted", None)
    periods = [_period(f"c_{i}", f"县{i}", start="953.11.18", current=True) for i in range(3)]
    sem_events, _ = _builder(entries).build(periods)
    gains = [e for e in sem_events if e.semanticType.value == "territorial_gain"]
    assert len(gains) == 3
    by_id = {e.eventId: e for e in gains}
    for e in gains:
        if e.acquisitionCause == AcquisitionCause.CONQUEST:
            assert sorted(e.relatedTitleIds) == ["c_0"]
        elif e.acquisitionCause == AcquisitionCause.GRANT:
            assert sorted(e.relatedTitleIds) == ["c_1"]
        else:
            assert sorted(e.relatedTitleIds) == ["c_2"]


def test_same_day_unknown_never_merged_with_explicit_cause():
    """同日 unknown 与 conquest 绝不合并（一个原因已知、一个未载）。"""
    entries = _mixed_entries("conquest", None)
    periods = [_period(f"c_{i}", f"县{i}", start="953.11.18", current=True) for i in range(2)]
    sem_events, _ = _builder(entries).build(periods)
    gains = [e for e in sem_events if e.semanticType.value == "territorial_gain"]
    assert len(gains) == 2
    causes = {e.acquisitionCause for e in gains}
    assert causes == {AcquisitionCause.CONQUEST, AcquisitionCause.UNKNOWN}
