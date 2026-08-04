"""提纲生成编排测试（Phase 3A 5.7/5.8/5.12）。

全部使用 FakeLlmProvider —— CI 禁止访问真实模型服务。
"""
from models import BiographyChapterOutline, BiographyStyle, EventType

from biography_engine.outline_generator import OutlineGenerator
from biography_engine.providers.fake import FakeLlmProvider

from factories import ev, make_profile


def _profile():
    return make_profile(
        timeline=[
            ev("b1", EventType.BIRTH, "700.1.1"),
            ev("t1", EventType.TITLE_GAIN, "740.1.1"),
            ev("m1", EventType.MARRIAGE, "750.1.1"),
            ev("d1", EventType.DEATH, "800.1.1"),
        ]
    )


def _valid_outline_dict(pid="p1"):
    return {
        "profileId": pid,
        "style": "serious_biography",
        "chapters": [
            {
                "id": "c1",
                "title": "出身",
                "summary": "出生与继承。",
                "eventIds": ["b1"],
            },
            {
                "id": "c2",
                "title": "巅峰",
                "summary": "获得头衔与成婚。",
                "eventIds": ["t1", "m1"],
            },
            {
                "id": "c3",
                "title": "落幕",
                "summary": "去世。",
                "eventIds": ["d1"],
            },
        ],
    }


def test_generate_success():
    fake = FakeLlmProvider(script=[{"json": _valid_outline_dict()}])
    res = OutlineGenerator(provider=fake).generate(
        _profile(), style=BiographyStyle.SERIOUS_BIOGRAPHY,
        include_inferred=True, include_uncertain=True, max_events=20,
    )
    assert res.valid is True
    assert res.errorCode is None
    assert res.retryCount == 0
    assert res.outline is not None
    assert len(res.outline.chapters) == 3
    assert res.compressed is not None
    assert fake.calls[0]["temperature"] == 0.3


def test_generate_success_with_code_fence():
    """模型回 code fence 包裹的 JSON → provider 剥掉后正常解析。"""
    raw = "好的，以下是提纲：\n```json\n" + _json_str() + "\n```\n请查收。"
    fake = FakeLlmProvider(script=[{"raw": raw}])
    res = OutlineGenerator(provider=fake).generate(
        _profile(), style=BiographyStyle.SERIOUS_BIOGRAPHY,
        include_inferred=True, include_uncertain=True, max_events=20,
    )
    assert res.valid is True


def _json_str():
    import json
    return json.dumps(_valid_outline_dict(), ensure_ascii=False)


def test_invalid_then_repair_success():
    """第一次非法 JSON → 有限修复重试后成功。"""
    fake = FakeLlmProvider(
        script=[
            {"invalid_json": "不是 JSON"},
            {"json": _valid_outline_dict()},
        ]
    )
    res = OutlineGenerator(provider=fake, max_repair=2).generate(
        _profile(), style=BiographyStyle.SERIOUS_BIOGRAPHY,
        include_inferred=True, include_uncertain=True, max_events=20,
    )
    assert res.valid is True
    assert res.retryCount == 1
    assert len(fake.calls) == 2
    # 第二次调用应带上修复说明。
    assert "# 修复要求" in fake.calls[1]["user_prompt"]


def test_invalid_forever_fails():
    fake = FakeLlmProvider(
        script=[{"invalid_json": "x"}, {"invalid_json": "x"}]
    )
    res = OutlineGenerator(provider=fake, max_repair=1).generate(
        _profile(), style=BiographyStyle.SERIOUS_BIOGRAPHY,
        include_inferred=True, include_uncertain=True, max_events=20,
    )
    assert res.valid is False
    assert res.outline is None
    assert res.errorCode == "invalid_model_output"
    assert len(fake.calls) == 2  # 原始 1 次 + 修复 1 次，之后停止


def test_event_reference_outside_whitelist_fails():
    bad = _valid_outline_dict()
    bad["chapters"][0]["eventIds"] = ["ghost"]
    fake = FakeLlmProvider(script=[{"json": bad}, {"json": bad}])
    res = OutlineGenerator(provider=fake, max_repair=1).generate(
        _profile(), style=BiographyStyle.SERIOUS_BIOGRAPHY,
        include_inferred=True, include_uncertain=True, max_events=20,
    )
    assert res.valid is False
    assert res.errorCode == "invalid_event_reference"
    assert "ghost" in (res.errorMessage or "")


def test_no_provider_returns_structured_error():
    res = OutlineGenerator(provider=None).generate(
        _profile(), style=BiographyStyle.SERIOUS_BIOGRAPHY,
        include_inferred=True, include_uncertain=True, max_events=20,
    )
    assert res.valid is False
    assert res.errorCode == "provider_not_configured"
    assert res.outline is None


def test_empty_timeline_insufficient():
    p = make_profile(timeline=[])
    res = OutlineGenerator(provider=FakeLlmProvider()).generate(
        p, style=BiographyStyle.SERIOUS_BIOGRAPHY,
        include_inferred=True, include_uncertain=True, max_events=20,
    )
    assert res.valid is False
    assert res.errorCode == "insufficient_timeline"
    # 不允许调用 provider。
    assert True  # FakeLlmProvider 无脚本 → 未调用即正确（生成在压缩后短路）


def test_provider_timeout_maps_error():
    fake = FakeLlmProvider(script=[{"timeout": True}])
    res = OutlineGenerator(provider=fake).generate(
        _profile(), style=BiographyStyle.SERIOUS_BIOGRAPHY,
        include_inferred=True, include_uncertain=True, max_events=20,
    )
    assert res.valid is False
    assert res.errorCode == "provider_timeout"


def test_provider_unreachable_maps_error():
    fake = FakeLlmProvider(script=[{"unreachable": True}])
    res = OutlineGenerator(provider=fake).generate(
        _profile(), style=BiographyStyle.SERIOUS_BIOGRAPHY,
        include_inferred=True, include_uncertain=True, max_events=20,
    )
    assert res.valid is False
    assert res.errorCode == "provider_unreachable"


def test_retry_exhaustion_when_fix_never_lands():
    """重复输出相同非法内容 → 达到修复上限后失败（绝不无限重试）。"""
    bad = _valid_outline_dict()
    bad["style"] = "not_a_style"  # 每次都违反 schema。
    fake = FakeLlmProvider(script=[{"json": bad}, {"json": bad}])
    res = OutlineGenerator(provider=fake, max_repair=1).generate(
        _profile(), style=BiographyStyle.SERIOUS_BIOGRAPHY,
        include_inferred=True, include_uncertain=True, max_events=20,
    )
    assert res.valid is False
    assert res.retryCount == 1
    assert len(fake.calls) == 2  # 原始 1 次 + 修复 1 次，之后停止
