"""正文生成编排测试（Phase 3B 第 7 步）。

全部使用 FakeLlmProvider —— CI 禁止访问真实模型服务。
覆盖：逐章生成（每章仅该章事件）、非法 JSON 有限修复、FactCheck 问题修复、
重试耗尽 → needs_revision（不伪装成功）、Provider 级错误直接失败、未配置。
"""
import pytest
from models import (
    BiographyChapterOutline,
    BiographyOutline,
    BiographyStyle,
    EventType,
    FactCheckStatus,
)

from biography_engine.biography_generator import BiographyGenerator
from biography_engine.providers.fake import FakeLlmProvider

from factories import ev, make_profile


def _profile():
    return make_profile(
        timeline=[
            ev("b1", EventType.BIRTH, "700.1.1"),
            ev("t1", EventType.TITLE_GAIN, "740.1.1"),
            ev("d1", EventType.DEATH, "780.6.6"),
        ]
    )


def _outline():
    return BiographyOutline(
        profileId="p1",
        style=BiographyStyle.SERIOUS_BIOGRAPHY,
        chapters=[
            BiographyChapterOutline(id="c1", title="出身", summary="出生。", eventIds=["b1"]),
            BiographyChapterOutline(id="c2", title="巅峰", summary="获头衔。", eventIds=["t1"]),
            BiographyChapterOutline(id="c3", title="落幕", summary="去世。", eventIds=["d1"]),
        ],
    )


def _ch(cid, title, content, event_ids):
    return {"id": cid, "title": title, "content": content, "eventIds": event_ids}


def test_generate_success():
    fake = FakeLlmProvider(
        script=[
            {"json": _ch("c1", "出身", "他生于 700 年。", ["b1"])},
            {"json": _ch("c2", "巅峰", "他于 740 年获得头衔。", ["t1"])},
            {"json": _ch("c3", "落幕", "他卒于 780 年。", ["d1"])},
        ]
    )
    res = BiographyGenerator(provider=fake).generate(_profile(), _outline())
    assert res.valid is True
    assert res.errorCode is None
    assert res.retryCount == 0
    assert res.biography is not None
    assert len(res.biography.chapters) == 3
    assert res.biography.factCheck.status == FactCheckStatus.PASS
    # 每章一次调用：只传该章允许事件。
    assert len(fake.calls) == 3
    assert "[b1]" in fake.calls[0]["user_prompt"]
    assert "[b1]" not in fake.calls[1]["user_prompt"]
    assert "[t1]" in fake.calls[1]["user_prompt"]


def test_chapter_event_id_outside_allowed_repair():
    """章节引用了该章不允许的事件 → 修复后成功。"""
    fake = FakeLlmProvider(
        script=[
            # c1 引用了不属于本章的 d1。
            {"json": _ch("c1", "出身", "他生于 700 年。", ["b1", "d1"])},
            {"json": _ch("c1", "出身", "他生于 700 年。", ["b1"])},
            {"json": _ch("c2", "巅峰", "他于 740 年获得头衔。", ["t1"])},
            {"json": _ch("c3", "落幕", "他卒于 780 年。", ["d1"])},
        ]
    )
    res = BiographyGenerator(provider=fake).generate(_profile(), _outline())
    assert res.valid is True
    assert res.retryCount == 1
    assert "# 修复要求" in fake.calls[1]["user_prompt"]


def test_factcheck_issue_repair():
    """头衔变更写成「继承」→ FactCheck 拦截 → 修复后成功。"""
    fake = FakeLlmProvider(
        script=[
            {"json": _ch("c1", "出身", "他生于 700 年。", ["b1"])},
            {"json": _ch("c2", "巅峰", "他继承了头衔。", ["t1"])},
            {"json": _ch("c2", "巅峰", "他于 740 年获得头衔。", ["t1"])},
            {"json": _ch("c3", "落幕", "他卒于 780 年。", ["d1"])},
        ]
    )
    res = BiographyGenerator(provider=fake).generate(_profile(), _outline())
    assert res.valid is True
    assert res.retryCount == 1
    assert res.biography.factCheck.status == FactCheckStatus.PASS


def test_retries_exhausted_needs_revision():
    """章节始终含虚构对白 → 重试耗尽 → 仍产出但标 needs_revision。"""
    bad = _ch("c1", "出身", "他说：「此战必胜。」", ["b1"])
    fake = FakeLlmProvider(
        script=[
            {"json": bad}, {"json": bad}, {"json": bad},
            {"json": _ch("c2", "巅峰", "他于 740 年获得头衔。", ["t1"])},
            {"json": _ch("c3", "落幕", "他卒于 780 年。", ["d1"])},
        ]
    )
    res = BiographyGenerator(provider=fake, max_repair=2).generate(_profile(), _outline())
    # 不伪装成功：valid=False 且 factCheck=needs_revision；但正文仍可保存为草稿。
    assert res.valid is False
    assert res.biography is not None
    assert res.biography.factCheck.status == FactCheckStatus.NEEDS_REVISION
    assert any(i.rule == "fabricated_dialogue" for i in res.biography.factCheck.issues)
    assert len(res.biography.chapters) == 3  # 三章正文都已产出，只是 c1 需修订
    assert len(fake.calls) == 5  # c1 原始1+修复2；c2、c3 各 1


def test_provider_unreachable_fails():
    fake = FakeLlmProvider(script=[{"unreachable": True}])
    res = BiographyGenerator(provider=fake).generate(_profile(), _outline())
    assert res.valid is False
    assert res.biography is None
    assert res.errorCode == "provider_unreachable"


def test_provider_not_configured():
    res = BiographyGenerator(provider=None).generate(_profile(), _outline())
    assert res.valid is False
    assert res.errorCode == "provider_not_configured"


def test_outline_event_missing():
    outline = BiographyOutline(
        profileId="p1",
        style=BiographyStyle.SERIOUS_BIOGRAPHY,
        chapters=[BiographyChapterOutline(id="c1", title="章", summary="s", eventIds=["ghost"])],
    )
    fake = FakeLlmProvider(script=[])
    res = BiographyGenerator(provider=fake).generate(_profile(), outline)
    assert res.valid is False
    assert res.errorCode == "outline_event_missing"
    assert fake.calls == []  # 未调用模型


def test_invalid_json_repair_limit():
    """非法 JSON 且修复后仍非法 → 有限次数后失败，不无限重试。"""
    fake = FakeLlmProvider(
        script=[
            {"invalid_json": "x"}, {"invalid_json": "x"}, {"invalid_json": "x"},
            {"json": _ch("c1", "出身", "他生于 700 年。", ["b1"])},
            {"json": _ch("c2", "巅峰", "他于 740 年获得头衔。", ["t1"])},
            {"json": _ch("c3", "落幕", "他卒于 780 年。", ["d1"])},
        ]
    )
    res = BiographyGenerator(provider=fake, max_repair=2).generate(_profile(), _outline())
    assert res.valid is False
    assert res.biography is None
    assert res.errorCode == "invalid_model_output"
    # c1 原始1 + 修复2 = 3 次，之后停止（不碰 c2/c3）。
    assert len(fake.calls) == 3
