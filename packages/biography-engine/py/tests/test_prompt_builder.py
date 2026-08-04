"""版本化 Prompt 构建测试（Phase 3A 5.6/5.12）。"""
import json

from models import BiographyStyle

from biography_engine.compressor import compress_profile
from biography_engine.prompt_builder import (
    MAX_CHAPTERS,
    MIN_CHAPTERS,
    OUTLINE_JSON_SCHEMA,
    PROMPT_VERSION,
    build_outline_prompts,
    build_repair_prompt,
    load_system_prompt,
)

from factories import ev, make_profile
from models import EventType


def _compressed(pid="p1"):
    p = make_profile(
        pid=pid,
        name="测试人物",
        timeline=[
            ev("e1", EventType.TITLE_GAIN, "701.1.1"),
            ev("e2", EventType.TRAVEL, "711.1.1"),
        ],
    )
    return compress_profile(p, max_events=40, include_inferred=True, include_uncertain=True)


def test_version_is_frozen():
    assert PROMPT_VERSION == "outline.zh-Hans.v1"


def test_system_prompt_loaded():
    text = load_system_prompt()
    assert len(text) > 100
    assert "事件" in text  # 系统提示含"只用给定事件"类约束


def test_user_prompt_contains_only_compressed_facts():
    system, user = build_outline_prompts(
        _compressed(), BiographyStyle.SERIOUS_BIOGRAPHY
    )
    # 压缩档案是唯一事实来源。
    assert "测试人物" in user
    assert "p1" in user
    assert "[e1]" in user  # 事件 id 列表
    assert "701.1.1" in user
    # 生成约束与 schema（与 build_outline_prompts 同一缩进格式）。
    assert "JSON Schema" in user or '"type": "object"' in user
    assert (
        json.dumps(OUTLINE_JSON_SCHEMA, ensure_ascii=False, indent=2) in user
    )
    # 章节数约束。
    assert str(MIN_CHAPTERS) in user and str(MAX_CHAPTERS) in user


def test_user_prompt_does_not_leak_raw_data():
    """user_prompt 绝不含：绝对路径 / API Key / 令牌表字样。"""
    _, user = build_outline_prompts(_compressed(), BiographyStyle.SERIOUS_BIOGRAPHY)
    assert "D:\\" not in user and "/Users" not in user and "C:" not in user
    assert "sk-" not in user  # API Key 形态
    assert "RAKALY_IRONMAN_TOKENS" not in user  # 铁人令牌表路径


def test_schema_style_enum_uses_values():
    enum_values = json.dumps(OUTLINE_JSON_SCHEMA, ensure_ascii=False)
    for s in BiographyStyle:
        assert s.value in enum_values


def test_repair_prompt_appends_fix_instructions():
    _, user = build_outline_prompts(_compressed(), BiographyStyle.VERNACULAR_ANNALS)
    repaired = build_repair_prompt(user, ["章节顺序倒置。", "eventIds 为空。"])
    assert repaired.startswith(user)
    assert "# 修复要求" in repaired
    assert "章节顺序倒置。" in repaired
    assert "重新输出完整 JSON" in repaired


def test_repair_prompt_preserves_original_facts():
    _, user = build_outline_prompts(_compressed(), BiographyStyle.VERNACULAR_ANNALS)
    repaired = build_repair_prompt(user, ["xxx"])
    assert "测试人物" in repaired  # 原事实仍在（修复不改变事实范围）
