"""提纲校验器测试（Phase 3A 5.7/5.12）。"""
from models import BiographyChapterOutline, BiographyOutline, BiographyStyle

from biography_engine.compressor import compress_profile
from biography_engine.prompt_builder import MAX_CHAPTERS
from biography_engine.validators import validate_outline, validate_style

from factories import ev, make_profile

from models import EventType


def _outline(**kw) -> BiographyOutline:
    style = kw.get("style", BiographyStyle.SERIOUS_BIOGRAPHY)
    profile_id = kw.get("profile_id", "p1")
    chapters = kw.get("chapters")
    if chapters is None:
        chapters = [
            BiographyChapterOutline(id="c1", title="章一", eventIds=["e1"], summary="简介"),
        ]
    return BiographyOutline(profileId=profile_id, style=style, chapters=chapters)


def _chapter(ch_id: str, event_ids, *, title=None, summary=None):
    return BiographyChapterOutline(
        id=ch_id,
        title=title or f"章 {ch_id}",
        eventIds=event_ids,
        summary=summary or "简介",
    )


def _compressed(profile=None):
    p = profile or make_profile(
        timeline=[
            ev("e1", EventType.TITLE_GAIN, "701.1.1"),
            ev("e2", EventType.MARRIAGE, "711.1.1"),
            ev("e3", EventType.TRAVEL, "721.1.1"),
        ]
    )
    return compress_profile(p, max_events=40, include_inferred=True, include_uncertain=True)


def test_valid_outline_passes():
    outline = _outline(chapters=[_chapter("c1", ["e1"])])
    assert validate_outline(outline, ["e1"]) == []


def test_empty_chapters_rejected():
    outline = _outline(chapters=[])
    errs = validate_outline(outline, ["e1"])
    assert any("至少 1 章" in e for e in errs)


def test_too_many_chapters_rejected():
    chapters = [_chapter(f"c{i}", [f"e{i}"]) for i in range(MAX_CHAPTERS + 1)]
    outline = _outline(chapters=chapters)
    errs = validate_outline(outline, [f"e{i}" for i in range(MAX_CHAPTERS + 1)])
    assert any(f"超过上限 {MAX_CHAPTERS}" in e for e in errs)


def test_duplicate_chapter_id_rejected():
    outline = _outline(chapters=[_chapter("c1", ["e1"]), _chapter("c1", ["e2"])])
    errs = validate_outline(outline, ["e1", "e2"])
    assert any("章节 id 重复" in e for e in errs)


def test_empty_event_ids_rejected():
    # 用 model_construct 绕过 pydantic 的 min_length 校验，专测校验器本身。
    empty_chapter = BiographyChapterOutline.model_construct(
        id="c1", title="章一", eventIds=[], summary="简介"
    )
    outline = _outline(chapters=[empty_chapter])
    errs = validate_outline(outline, [])
    assert any("eventIds 为空" in e for e in errs)


def test_event_id_not_in_whitelist_rejected():
    outline = _outline(chapters=[_chapter("c1", ["e1", "ghost"])])
    errs = validate_outline(outline, ["e1"])
    assert any("ghost" in e and "不存在" in e for e in errs)


def test_chapter_time_order_enforced():
    """章节引用事件应随时间推进；顺序倒置 → 报错。"""
    compressed = _compressed()
    outline = _outline(
        chapters=[
            _chapter("later_first", ["e3"]),   # 721 年
            _chapter("earlier_second", ["e1"]),  # 701 年 → 倒置
        ]
    )
    errs = validate_outline(outline, compressed.sourceEventIds, compressed)
    assert any("顺序倒置" in e for e in errs)


def test_chapter_time_order_ok_when_ascending():
    compressed = _compressed()
    outline = _outline(
        chapters=[
            _chapter("earlier", ["e1"]),   # 701 年
            _chapter("later", ["e3"]),     # 721 年
        ]
    )
    assert validate_outline(outline, compressed.sourceEventIds, compressed) == []


def test_style_valid():
    assert validate_style(BiographyStyle.VERNACULAR_ANNALS.value) is None


def test_style_invalid():
    assert "非法 BiographyStyle" in (validate_style("not_a_style") or "")
