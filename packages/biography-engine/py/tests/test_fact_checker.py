"""FactChecker（20 条确定性规则）测试（Phase 3B 第 8 步）。

全部确定性、不调用 LLM。构造压缩档案 + 单章/多章提纲，逐规则验证。
"""
import pytest
from models import (
    AcquisitionCause,
    AcquisitionTypeSource,
    Biography,
    BiographyChapter,
    BiographyChapterOutline,
    BiographyOutline,
    BiographyStyle,
    CharacterProfile,
    Confidence,
    EntityRef,
    EventType,
    FactCheckStatus,
    HistoricalSemanticEvent,
    HistoricalSemanticEventType,
    TitleHistoryActionKind,
    WarningSeverity,
)

from biography_engine.compressor import compress_profile
from biography_engine.fact_checker import FactChecker, check_biography

from factories import ev, make_profile


def _outline(event_ids_by_chapter):
    return BiographyOutline(
        profileId="p1",
        style=BiographyStyle.SERIOUS_BIOGRAPHY,
        chapters=[
            BiographyChapterOutline(
                id=f"c{i}",
                title=f"章{i}",
                summary="摘要",
                eventIds=ids,
            )
            for i, ids in enumerate(event_ids_by_chapter, start=1)
        ],
    )


def _chapter(ch_id, content, event_ids):
    return BiographyChapter(
        id=ch_id, title=ch_id, content=content, eventIds=event_ids
    )


def _backfill_facts(chapters, compressed):
    """与 BiographyGenerator 同一规则：身份事实 + 本章事件锚定事实。"""
    from biography_engine.chapter_prompts import facts_for_chapter

    for ch in chapters:
        cf = facts_for_chapter(compressed, ch.eventIds)
        ch.factIds = [f.id for f in cf]
        ch.claims = [f.text for f in cf]
    return chapters


def _check(chapters, outline, profile):
    compressed = compress_profile(
        profile, max_events=50, include_inferred=True, include_uncertain=True
    )
    chapters = _backfill_facts(list(chapters), compressed)
    return FactChecker().check(
        chapters=chapters,
        outline=outline,
        compressed=compressed,
        profile=profile,
    )


# ---------------------------------------------------------------------------
# 基线：合法正文通过
# ---------------------------------------------------------------------------

def test_clean_chapter_passes():
    profile = make_profile(
        timeline=[
            ev("b1", EventType.BIRTH, "700.1.1"),
            ev("d1", EventType.DEATH, "780.6.6"),
        ]
    )
    outline = _outline([["b1"], ["d1"]])
    chapters = [
        _chapter("c1", "他生于 700 年。", ["b1"]),
        _chapter("c2", "他卒于 780 年。", ["d1"]),
    ]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.PASS
    assert fc.issues == []


# ---------------------------------------------------------------------------
# 规则 1：event_id_not_allowed —— 每章只用该章允许的事件
# ---------------------------------------------------------------------------

def test_event_id_not_allowed():
    profile = make_profile(
        timeline=[
            ev("b1", EventType.BIRTH, "700.1.1"),
            ev("d1", EventType.DEATH, "780.6.6"),
        ]
    )
    outline = _outline([["b1"]])
    chapters = [_chapter("c1", "生于 700 年。", ["b1", "d1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "event_id_not_allowed" for i in fc.issues)


# ---------------------------------------------------------------------------
# 规则 2：event_after_death —— 死亡后事件
# ---------------------------------------------------------------------------

def test_event_after_death():
    profile = make_profile(
        timeline=[
            ev("b1", EventType.BIRTH, "700.1.1"),
            ev("d1", EventType.DEATH, "780.6.6"),
            ev("t1", EventType.TITLE_GAIN, "790.1.1"),
        ]
    )
    outline = _outline([["b1", "d1", "t1"]])
    chapters = [_chapter("c1", "一生经历颇多。", ["b1", "d1", "t1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "event_after_death" for i in fc.issues)


# ---------------------------------------------------------------------------
# 规则 3：time_reversal —— 正文日期与本章事件冲突
# ---------------------------------------------------------------------------

def test_time_reversal():
    profile = make_profile(
        timeline=[
            ev("t1", EventType.TITLE_GAIN, "740.1.1"),
        ]
    )
    outline = _outline([["t1"]])
    # 正文声称 700 年，早于本章最早事件 740 年过多。
    chapters = [_chapter("c1", "他在 700 年获得头衔。", ["t1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "time_reversal" for i in fc.issues)


# ---------------------------------------------------------------------------
# 规则 4/5/6/7/8：技术泄漏与标点
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "content, rule",
    [
        ("他与 90001 号人物并肩作战。", "numeric_id_leak"),
        ("战争以 token t1234 触发。", "token_id_leak"),
        ("依据 sourcePath 引用。", "source_path_leak"),
        ("事件类型为 title_gain。", "internal_enum_leak"),
        ("他死于此役。。", "punctuation_double"),
    ],
)
def test_leak_rules(content, rule):
    profile = make_profile(
        timeline=[ev("t1", EventType.TITLE_GAIN, "740.1.1")]
    )
    outline = _outline([["t1"]])
    chapters = [_chapter("c1", content, ["t1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == rule for i in fc.issues)


# ---------------------------------------------------------------------------
# 规则 9：inferred_as_fact —— 只依据推断事件却无推断措辞
# ---------------------------------------------------------------------------

def test_inferred_as_fact():
    profile = make_profile(
        timeline=[
            ev("r1", EventType.OTHER, "740.1.1", confidence=Confidence.INFERRED),
        ]
    )
    outline = _outline([["r1"]])
    chapters = [_chapter("c1", "他当年交游广阔。", ["r1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "inferred_as_fact" for i in fc.issues)


def test_inferred_with_hedge_passes():
    profile = make_profile(
        timeline=[
            ev("r1", EventType.OTHER, "740.1.1", confidence=Confidence.INFERRED),
        ]
    )
    outline = _outline([["r1"]])
    chapters = [_chapter("c1", "据推断，他当年交游广阔。", ["r1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.PASS


# ---------------------------------------------------------------------------
# 规则 10：conflict_as_succession —— 头衔变更写成继承
# ---------------------------------------------------------------------------

def test_conflict_as_succession():
    profile = make_profile(
        timeline=[ev("t1", EventType.TITLE_GAIN, "740.1.1")]
    )
    outline = _outline([["t1"]])
    chapters = [_chapter("c1", "他继承了安南之地。", ["t1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "conflict_as_succession" for i in fc.issues)


def test_succession_event_allows_inherit_word():
    profile = make_profile(
        timeline=[ev("s1", EventType.SUCCESSION, "740.1.1")]
    )
    outline = _outline([["s1"]])
    chapters = [_chapter("c1", "他继承了安南之地。", ["s1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.PASS


# ---------------------------------------------------------------------------
# 规则 11：defender_as_declared —— 防御战争写成宣战
# ---------------------------------------------------------------------------

def test_defender_as_declared():
    profile = make_profile(
        timeline=[
            ev("w1", EventType.WAR, "740.1.1", rel="敌方"),
        ]
    )
    # 把 w1 的标题改为防御战争字样。
    profile.timeline[0].title = "卷入防御战争"
    outline = _outline([["w1"]])
    chapters = [_chapter("c1", "他向敌方宣战。", ["w1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "defender_as_declared" for i in fc.issues)


# ---------------------------------------------------------------------------
# 规则 12：fabricated_dialogue —— 虚构对白/心理描写
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "content",
    ["他说：「此战必胜。」", "他心想：这一次定要雪耻。", "他低语道「天命在我」。"],
)
def test_fabricated_dialogue(content):
    profile = make_profile(
        timeline=[ev("t1", EventType.TITLE_GAIN, "740.1.1")]
    )
    outline = _outline([["t1"]])
    chapters = [_chapter("c1", content, ["t1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "fabricated_dialogue" for i in fc.issues)


# ---------------------------------------------------------------------------
# 规则 13/14：unverified_quoted_name / unverified_quoted_title
# ---------------------------------------------------------------------------

def test_unverified_quoted_name():
    profile = make_profile(
        timeline=[
            ev("t1", EventType.TITLE_GAIN, "740.1.1", rel="梁克贞"),
        ]
    )
    outline = _outline([["t1"]])
    # 「张无名」不在任何事实块 / relatedNames 中。
    chapters = [_chapter("c1", "他结识了「张无名」。", ["t1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "unverified_quoted_name" for i in fc.issues)


def test_verified_quoted_name_passes():
    profile = make_profile(
        timeline=[
            ev("t1", EventType.TITLE_GAIN, "740.1.1", rel="梁克贞"),
        ]
    )
    outline = _outline([["t1"]])
    chapters = [_chapter("c1", "他与「梁克贞」共事。", ["t1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.PASS


# ---------------------------------------------------------------------------
# 规则 15/16：death/birth year mismatch
# ---------------------------------------------------------------------------

def test_death_year_mismatch():
    profile = make_profile(
        timeline=[
            ev("b1", EventType.BIRTH, "700.1.1"),
            ev("d1", EventType.DEATH, "780.6.6"),
        ]
    )
    outline = _outline([["d1"]])
    chapters = [_chapter("c1", "他卒于 790 年。", ["d1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "death_year_mismatch" for i in fc.issues)


def test_birth_year_mismatch():
    profile = make_profile(
        timeline=[
            ev("b1", EventType.BIRTH, "700.1.1"),
            ev("d1", EventType.DEATH, "780.6.6"),
        ]
    )
    outline = _outline([["b1"]])
    chapters = [_chapter("c1", "他生于 710 年。", ["b1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "birth_year_mismatch" for i in fc.issues)


# ---------------------------------------------------------------------------
# 规则 17/18/19/20：profile id / 模型元信息 / 空章节 / markdown
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "content, rule",
    [
        # 规则 4 与 17 共用同一数字 id 检测（≥5 位连续数字）。
        ("人物 id 900000001 史载于册。", "numeric_id_leak"),
        ("这是符合 schema 的输出。", "model_meta_leak"),
        ("```json\n{}\n```", "markdown_leak"),
    ],
)
def test_meta_leak_rules(content, rule):
    profile = make_profile(
        timeline=[ev("t1", EventType.TITLE_GAIN, "740.1.1")]
    )
    outline = _outline([["t1"]])
    chapters = [_chapter("c1", content, ["t1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == rule for i in fc.issues)


def test_empty_chapter():
    profile = make_profile(
        timeline=[ev("t1", EventType.TITLE_GAIN, "740.1.1")]
    )
    outline = _outline([["t1"]])
    chapters = [_chapter("c1", "  ", ["t1"])]
    fc = _check(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "empty_chapter" for i in fc.issues)


# ---------------------------------------------------------------------------
# 便捷入口 check_biography
# ---------------------------------------------------------------------------

def test_check_biography_helper():
    profile = make_profile(
        timeline=[ev("t1", EventType.TITLE_GAIN, "740.1.1")]
    )
    outline = _outline([["t1"]])
    bio = Biography(
        profileId="p1",
        style=BiographyStyle.SERIOUS_BIOGRAPHY,
        chapters=[_chapter("c1", "他继承了头衔。", ["t1"])],
        generatedAt="2026-08-04T00:00:00Z",
        modelName="fake",
    )
    compressed = compress_profile(
        profile, max_events=50, include_inferred=True, include_uncertain=True
    )
    fc = check_biography(bio, outline=outline, compressed=compressed, profile=profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "conflict_as_succession" for i in fc.issues)


# ---------------------------------------------------------------------------
# 3C.7：历史动作语义误写（规则 25-30）
# ---------------------------------------------------------------------------

def _profile_with_hist(timeline_events, hist_events, *, realm_institutions=None):
    """构造带历史语义事件与政权机构的档案。"""
    return CharacterProfile(
        id="p1",
        name="梁某",
        birthDate="900.1.1",
        deathDate="980.1.1",
        timeline=timeline_events,
        historicalEvents=hist_events,
        realmInstitutions=[
            EntityRef(id=n, name=n, type="title", resolved=True)
            for n in (realm_institutions or [])
        ],
    )


def _hist_gain(eid, date, cause, raw_type=None, action=None):
    """构造一条 territorial_gain 历史语义事件（用于 rule 25-30）。"""
    return HistoricalSemanticEvent(
        eventId=eid,
        semanticType=HistoricalSemanticEventType.TERRITORIAL_GAIN,
        date=date,
        summary=f"梁某 于 {date} 获得领地。",
        relatedTitleIds=[f"c_{eid}"],
        confidence=Confidence.CONFIRMED,
        acquisitionCause=cause,
        acquisitionRawType=raw_type,
        acquisitionTypeSource=AcquisitionTypeSource.SAVE_EXPLICIT,
        normalizedAction=action,
    )


def _fc_for(chapters, outline, profile):
    compressed = compress_profile(
        profile, max_events=50, include_inferred=True, include_uncertain=True
    )
    chapters = _backfill_facts(list(chapters), compressed)
    return FactChecker().check(
        chapters=chapters, outline=outline, compressed=compressed, profile=profile
    )


def test_mixed_cause_group():
    """规则 25：本章引用不同获得原因的多地，正文却写成同一种原因。"""
    profile = _profile_with_hist(
        timeline_events=[
            ev("g1", EventType.TITLE_GAIN, "953.11.18"),
            ev("g2", EventType.TITLE_GAIN, "953.11.18"),
        ],
        hist_events=[
            _hist_gain("g1", "953.11.18", AcquisitionCause.CONQUEST, "conquest",
                       TitleHistoryActionKind.CONQUERED),
            _hist_gain("g2", "953.11.18", AcquisitionCause.GRANT, "granted",
                       TitleHistoryActionKind.GRANTED),
        ],
    )
    outline = _outline([["g1", "g2"]])
    chapters = [_chapter("c1", "他通过征服获得了这两处领地。", ["g1", "g2"])]
    fc = _fc_for(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "mixed_cause_group" for i in fc.issues)


def test_mixed_cause_group_respected_per_cause_text_passes():
    """规则 25 反面：正文分别说明各自原因则通过。"""
    profile = _profile_with_hist(
        timeline_events=[
            ev("g1", EventType.TITLE_GAIN, "953.11.18"),
            ev("g2", EventType.TITLE_GAIN, "953.11.18"),
        ],
        hist_events=[
            _hist_gain("g1", "953.11.18", AcquisitionCause.CONQUEST, "conquest",
                       TitleHistoryActionKind.CONQUERED),
            _hist_gain("g2", "953.11.18", AcquisitionCause.GRANT, "granted",
                       TitleHistoryActionKind.GRANTED),
        ],
    )
    outline = _outline([["g1", "g2"]])
    chapters = [
        _chapter(
            "c1",
            "甲地经征服获得，乙地经授予获得。",
            ["g1", "g2"],
        )
    ]
    fc = _fc_for(chapters, outline, profile)
    assert not any(i.rule == "mixed_cause_group" for i in fc.issues)


def test_institution_as_personal_office():
    """规则 26：政权机构写成「进入政事堂任职」被拦截。"""
    profile = _profile_with_hist(
        timeline_events=[ev("t1", EventType.TITLE_GAIN, "950.1.1")],
        hist_events=[],
        realm_institutions=["政事堂", "枢密院"],
    )
    outline = _outline([["t1"]])
    chapters = [_chapter("c1", "他进入政事堂任职，掌理国政。", ["t1"])]
    fc = _fc_for(chapters, outline, profile)
    assert fc.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "institution_as_personal_office" for i in fc.issues)


def test_institution_as_personal_office_suffix_form():
    """规则 26：兼任/担任机构名也被拦截。"""
    profile = _profile_with_hist(
        timeline_events=[ev("t1", EventType.TITLE_GAIN, "950.1.1")],
        hist_events=[],
        realm_institutions=["六部", "御史台"],
    )
    outline = _outline([["t1"]])
    chapters = [_chapter("c1", "他兼任六部，担任御史台。", ["t1"])]
    fc = _fc_for(chapters, outline, profile)
    hits = [i for i in fc.issues if i.rule == "institution_as_personal_office"]
    assert len(hits) >= 2


def test_institution_ownership_wording_passes():
    """规则 26 反面：机构归入统治体系写法通过。"""
    profile = _profile_with_hist(
        timeline_events=[ev("t1", EventType.TITLE_GAIN, "950.1.1")],
        hist_events=[],
        realm_institutions=["政事堂"],
    )
    outline = _outline([["t1"]])
    chapters = [
        _chapter("c1", "该年政事堂归入其统治体系。", ["t1"])
    ]
    fc = _fc_for(chapters, outline, profile)
    assert not any(i.rule == "institution_as_personal_office" for i in fc.issues)


def test_unsupported_succession_wording():
    """规则 27：appointment_succession 写成世袭继承被拦截。"""
    profile = _profile_with_hist(
        timeline_events=[ev("g1", EventType.TITLE_GAIN, "955.1.22")],
        hist_events=[
            _hist_gain("g1", "955.1.22", AcquisitionCause.ADMINISTRATIVE_TRANSFER,
                       "appointment_succession",
                       TitleHistoryActionKind.ADMINISTRATIVE_SUCCESSION),
        ],
    )
    outline = _outline([["g1"]])
    chapters = [_chapter("c1", "他世袭继承了父位。", ["g1"])]
    fc = _fc_for(chapters, outline, profile)
    assert any(i.rule == "unsupported_succession_wording" for i in fc.issues)


def test_unsupported_succession_wording_neutral_passes():
    """规则 27 反面：经任命继任的中性措辞通过。"""
    profile = _profile_with_hist(
        timeline_events=[ev("g1", EventType.TITLE_GAIN, "955.1.22")],
        hist_events=[
            _hist_gain("g1", "955.1.22", AcquisitionCause.ADMINISTRATIVE_TRANSFER,
                       "appointment_succession",
                       TitleHistoryActionKind.ADMINISTRATIVE_SUCCESSION),
        ],
    )
    outline = _outline([["g1"]])
    chapters = [_chapter("c1", "他在行政体系中经任命继任。", ["g1"])]
    fc = _fc_for(chapters, outline, profile)
    assert not any(i.rule == "unsupported_succession_wording" for i in fc.issues)


def test_conquest_overreach():
    """规则 28：conquest 证据被补写具体战争名/对手/战役过程。"""
    profile = _profile_with_hist(
        timeline_events=[ev("g1", EventType.TITLE_GAIN, "953.11.18")],
        hist_events=[
            _hist_gain("g1", "953.11.18", AcquisitionCause.CONQUEST, "conquest",
                       TitleHistoryActionKind.CONQUERED),
        ],
    )
    outline = _outline([["g1"]])
    chapters = [_chapter("c1", "他在梅奥之战中击败对手，夺取了该地。", ["g1"])]
    fc = _fc_for(chapters, outline, profile)
    assert any(i.rule == "conquest_overreach" for i in fc.issues)


def test_conquest_overreach_plain_wording_passes():
    """规则 28 反面：只写「通过战争取得」则通过。"""
    profile = _profile_with_hist(
        timeline_events=[ev("g1", EventType.TITLE_GAIN, "953.11.18")],
        hist_events=[
            _hist_gain("g1", "953.11.18", AcquisitionCause.CONQUEST, "conquest",
                       TitleHistoryActionKind.CONQUERED),
        ],
    )
    outline = _outline([["g1"]])
    chapters = [_chapter("c1", "他通过战争取得了该地。", ["g1"])]
    fc = _fc_for(chapters, outline, profile)
    assert not any(i.rule == "conquest_overreach" for i in fc.issues)


def test_lease_as_permanent_grant():
    """规则 29：leased_out 写成永久授封被拦截。"""
    profile = _profile_with_hist(
        timeline_events=[ev("l1", EventType.TITLE_LOSS, "953.11.18")],
        hist_events=[
            HistoricalSemanticEvent(
                eventId="l1",
                semanticType=HistoricalSemanticEventType.TERRITORIAL_LOSS,
                date="953.11.18",
                summary="梁某 于 953.11.18 将以下领地租借或委托管理：甲。",
                confidence=Confidence.CONFIRMED,
                acquisitionRawType="leased_out",
                acquisitionTypeSource=AcquisitionTypeSource.SAVE_EXPLICIT,
                normalizedAction=TitleHistoryActionKind.LEASED_OUT,
            ),
        ],
    )
    outline = _outline([["l1"]])
    chapters = [_chapter("c1", "该地被永久授封出去。", ["l1"])]
    fc = _fc_for(chapters, outline, profile)
    assert any(i.rule == "lease_as_permanent_grant" for i in fc.issues)


def test_realm_status_action_mismatch():
    """规则 30：swear_fealty/independency 写成普通领土获得被拦截。"""
    profile = _profile_with_hist(
        timeline_events=[ev("s1", EventType.TITLE_GAIN, "953.11.18")],
        hist_events=[
            HistoricalSemanticEvent(
                eventId="s1",
                semanticType=HistoricalSemanticEventType.TERRITORIAL_GAIN,
                date="953.11.18",
                summary="梁某 于 953.11.18 取得独立地位并辖有：甲。",
                confidence=Confidence.CONFIRMED,
                acquisitionRawType="independency",
                acquisitionTypeSource=AcquisitionTypeSource.SAVE_EXPLICIT,
                normalizedAction=TitleHistoryActionKind.BECAME_INDEPENDENT,
            ),
        ],
    )
    outline = _outline([["s1"]])
    chapters = [_chapter("c1", "他获得了大片领地。", ["s1"])]
    fc = _fc_for(chapters, outline, profile)
    assert any(i.rule == "realm_status_action_mismatch" for i in fc.issues)


def test_realm_status_action_written_as_independence_passes():
    """规则 30 反面：按地位关系变化书写则通过。"""
    profile = _profile_with_hist(
        timeline_events=[ev("s1", EventType.TITLE_GAIN, "953.11.18")],
        hist_events=[
            HistoricalSemanticEvent(
                eventId="s1",
                semanticType=HistoricalSemanticEventType.TERRITORIAL_GAIN,
                date="953.11.18",
                summary="梁某 于 953.11.18 取得独立地位并辖有：甲。",
                confidence=Confidence.CONFIRMED,
                acquisitionRawType="independency",
                acquisitionTypeSource=AcquisitionTypeSource.SAVE_EXPLICIT,
                normalizedAction=TitleHistoryActionKind.BECAME_INDEPENDENT,
            ),
        ],
    )
    outline = _outline([["s1"]])
    chapters = [_chapter("c1", "他取得独立地位，辖有该地。", ["s1"])]
    fc = _fc_for(chapters, outline, profile)
    assert not any(i.rule == "realm_status_action_mismatch" for i in fc.issues)
