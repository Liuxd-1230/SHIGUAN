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


# ---- Phase 3A.1：CompressedProfile v2 ---------------------------------------

def _rel(rid, kind):
    return CharacterRef(
        id=rid,
        name=f"亲{rid}",
        resolved=True,
        sourcePath=f"character/p1/relatives/{rid}#inferred_from_{kind}",
    )


def _v2_profile(**kw):
    timeline = kw.pop("timeline", None)
    base = dict(
        nickname=None,
        house=None,
        liege=None,
        deathReason=None,
        traits=[],
        relatives=[],
    )
    base.update(kw)
    return make_profile(timeline=timeline or [ev("e1", EventType.BIRTH, "700.1.1")], **base)


def test_v2_nickname_house_death_reason_traits():
    from models import EntityRef

    cp = compress_profile(
        _v2_profile(
            nickname=EntityRef(id="n1", name="仁", resolved=True),
            house=EntityRef(id="h1", name="梁家族", resolved=True),
            deathReason="death_disease",
            traits=[
                {"id": "t1", "name": "英勇"},
                {"id": "t2", "name": "英勇"},  # 去重
                {"id": "t3", "name": "谦逊"},
                {"id": "t4", "name": "433"},
            ],
        ),
        max_events=40,
        include_inferred=True,
        include_uncertain=True,
    )
    assert cp.compressionVersion == COMPRESSION_VERSION == "2"
    assert cp.nickname == "仁"
    assert cp.house == "梁家族"
    assert cp.deathReason == "death_disease"
    # 去重 + 数字占位名过滤。
    assert cp.traits == ["英勇", "谦逊"]


def test_v2_liege_only_when_resolved():
    # resolved=False 的数字名 → 不写 liegeName（不编造）。
    cp = compress_profile(
        _v2_profile(liege=CharacterRef(id="99", name="99", resolved=False)),
        max_events=40,
        include_inferred=True,
        include_uncertain=True,
    )
    assert cp.liegeName is None
    # resolved=True → 写名字 + 进关系事实块。
    cp2 = compress_profile(
        _v2_profile(liege=CharacterRef(id="42", name="加吉克", resolved=True)),
        max_events=40,
        include_inferred=True,
        include_uncertain=True,
    )
    assert cp2.liegeName == "加吉克"
    assert any("君主：加吉克" in f for f in cp2.relationshipFacts)


def test_v2_relatives_classified_and_limited():
    # 7 个姻亲（3A.1 限量 6）+ 5 个祖辈（限量 4）+ 1 个未知 kind（应忽略）。
    rels = [_rel(f"10{i}", "in_law") for i in range(7)]
    rels += [_rel("20{}".format(i), "grandparent") for i in range(5)]
    rels += [CharacterRef(id="301", name="怪", resolved=True, sourcePath="character/p1/relatives/301#inferred_from_unknown")]
    cp = compress_profile(
        _v2_profile(relatives=rels),
        max_events=40,
        include_inferred=True,
        include_uncertain=True,
    )
    assert cp.relatives, "v2 应有扩展亲属条目"
    by_kind: dict[str, int] = {}
    for r in cp.relatives:
        assert r.inferred is True
        by_kind[r.relation] = by_kind.get(r.relation, 0) + 1
    assert by_kind.get("in_law") == 6, by_kind  # 3A.1 每组限量 4/6/6/6/6
    assert by_kind.get("grandparent") == 4, by_kind
    # 未知 kind 不进入（不编造关系）。
    assert all(r.relation != "unknown" for r in cp.relatives)
    # 超限在 warnings 如实提示。
    assert any("姻亲" in w and "7 人" in w for w in cp.warnings)


def test_v2_relatives_empty_when_none():
    cp = compress_profile(
        _v2_profile(),
        max_events=40,
        include_inferred=True,
        include_uncertain=True,
    )
    assert cp.relatives == []
    assert not any("扩展亲属" in w for w in cp.warnings)


# ---------------------------------------------------------------------------
# 3A.1：reignSummary / warSummary / warningSummary（确定性叙事摘要）
# ---------------------------------------------------------------------------


def _current_period(title_id: str, name: str, tier, start: str, is_current: bool = True):
    from models import TitlePeriod

    return TitlePeriod(
        titleId=title_id,
        name=name,
        tier=tier,
        start=start,
        end=None,
        isCurrent=is_current,
        sourcePath=f"landed_titles/{title_id}",
    )


def test_v2_reign_summary_counts_only_current_titles():
    from models import TitleTier

    titles = [
        _current_period("c_a", "甲县", TitleTier.COUNTY, "930.1.1"),
        _current_period("d_b", "乙公国", TitleTier.DUCHY, "952.8.16"),
        _current_period("k_c", "丙王国", TitleTier.KINGDOM, "952.8.16"),
        _current_period("d_old", "旧公国", TitleTier.DUCHY, "900.1.1", is_current=False),
    ]
    cp = compress_profile(
        _v2_profile(titles=titles),
        max_events=40,
        include_inferred=True,
        include_uncertain=True,
    )
    assert cp.reignSummary is not None
    assert "现任 3 个头衔" in cp.reignSummary
    assert "最高等级：kingdom" in cp.reignSummary
    # 主要头衔按等级降序（王国优先于公国/县）。
    assert "丙王国" in cp.reignSummary
    assert "乙公国" in cp.reignSummary
    assert "甲县" in cp.reignSummary
    assert "旧公国" not in cp.reignSummary  # 非现任不计入
    # 主头衔进 identityFacts（与 reignSummary 同一规则）。
    assert any("主头衔：丙王国" in f for f in cp.identityFacts)


def test_v2_reign_summary_empty_when_no_titles():
    cp = compress_profile(_v2_profile(), max_events=40, include_inferred=True, include_uncertain=True)
    assert cp.reignSummary == "无现任头衔"
    assert not any("主头衔：" in f for f in cp.identityFacts)


def test_v2_war_summary_normalized():
    from models import CharacterRef, Confidence, TimelineEvent

    def w_ev(eid, title, date, opp):
        return TimelineEvent(
            id=eid,
            type=EventType.WAR,
            title=title,
            description=f"事件 {eid}。",
            date=date,
            relatedCharacters=[CharacterRef(id=opp, name=opp, resolved=True)],
            confidence=Confidence.CONFIRMED,
            evidence=[],
        )

    cp = compress_profile(
        _v2_profile(
            timeline=[
                ev("b1", EventType.BIRTH, "700.1.1"),
                w_ev("w1", "卷入防御战争", "950.1.1", "入侵者"),
                w_ev("w2", "战争获胜", "952.8.16", "梁某"),
            ]
        ),
        max_events=40,
        include_inferred=True,
        include_uncertain=True,
    )
    assert cp.warSummary == [
        "950.1.1 卷入一场防御战争，对方：入侵者。",
        "952.8.16 赢得一场战争，对手：梁某。",
    ]


def test_v2_warning_summary_aggregated_and_sanitized():
    from models import CharacterProfile, EvidenceWarning, WarningSeverity

    profile = CharacterProfile(
        id="p1",
        name="测试人物",
        birthDate="700.1.1",
        timeline=[ev("e1", EventType.BIRTH, "700.1.1")],
        evidenceWarnings=[
            EvidenceWarning(
                code="title_holder_conflict",
                message="头衔 d_xiyuan 顶层 holder(20423) 与 history 末项 holder(2686) 不一致；以顶层 holder 认定现任，不静默覆盖。",
                severity=WarningSeverity.WARNING,
                sourcePath="landed_titles/d_xiyuan",
            ),
            EvidenceWarning(
                code="title_holder_conflict",
                message="另一处冲突。",
                severity=WarningSeverity.WARNING,
                sourcePath="landed_titles/c_yong",
            ),
        ],
    )
    cp = compress_profile(
        profile,
        max_events=40,
        include_inferred=True,
        include_uncertain=True,
    )
    assert len(cp.warningSummary) == 1
    assert "× 2" in cp.warningSummary[0]
    # 技术字段不进聚合结果。
    assert "d_xiyuan" not in cp.warningSummary[0]
    assert "20423" not in cp.warningSummary[0]
    assert "landed_titles" not in cp.warningSummary[0]
