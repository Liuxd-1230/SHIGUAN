"""FactChecker（20 条确定性规则）测试（Phase 3B 第 8 步）。

全部确定性、不调用 LLM。构造压缩档案 + 单章/多章提纲，逐规则验证。
"""
import pytest
from models import (
    Biography,
    BiographyChapter,
    BiographyChapterOutline,
    BiographyOutline,
    BiographyStyle,
    CharacterProfile,
    Confidence,
    EventType,
    FactCheckStatus,
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


def _check(chapters, outline, profile):
    compressed = compress_profile(
        profile, max_events=50, include_inferred=True, include_uncertain=True
    )
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
