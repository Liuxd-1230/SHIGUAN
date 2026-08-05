"""章节正文 Prompt 构建测试（Phase 3B 第 6 步）。

验证：每章 prompt 只含该章允许事件；不含其他章事件；不含技术字段泄漏；
修复 prompt 追加修复要求。
"""
import json

from models import BiographyChapterOutline, BiographyStyle, EventType

from biography_engine.chapter_prompts import (
    CHAPTER_JSON_SCHEMA,
    CHAPTER_PROMPT_VERSION,
    build_chapter_prompts,
    build_chapter_repair_prompt,
    load_chapter_system_prompt,
)
from biography_engine.compressor import compress_profile

from factories import ev, make_profile


def _compressed():
    profile = make_profile(
        timeline=[
            ev("b1", EventType.BIRTH, "700.1.1"),
            ev("t1", EventType.TITLE_GAIN, "740.1.1"),
            ev("d1", EventType.DEATH, "780.6.6"),
        ]
    )
    return compress_profile(
        profile, max_events=20, include_inferred=True, include_uncertain=True
    )


def _chapter_outline(cid, event_ids, title="章"):
    return BiographyChapterOutline(id=cid, title=title, summary="摘要", eventIds=event_ids)


def test_version_and_system_prompt():
    assert CHAPTER_PROMPT_VERSION == "biography-chapter.zh-Hans.v2"
    sp = load_chapter_system_prompt()
    assert "硬性约束" in sp
    assert "不得生成对白" in sp


def test_build_chapter_prompts_only_includes_allowed_events():
    compressed = _compressed()
    # 第二章只允许 t1。
    ch = _chapter_outline("c2", ["t1"], "巅峰")
    system_prompt, user_prompt = build_chapter_prompts(
        compressed, ch, BiographyStyle.SERIOUS_BIOGRAPHY
    )
    assert "[t1]" in user_prompt
    assert "[b1]" not in user_prompt
    assert "[d1]" not in user_prompt
    # 章节摘要也在 prompt 中。
    assert "《巅峰》" in user_prompt
    assert "本章允许事件" in user_prompt
    # 不含技术泄漏字段。
    assert "sourcePath" not in user_prompt
    assert "landed_titles" not in user_prompt
    assert "rawKey" not in user_prompt


def test_build_chapter_prompts_schema_included():
    compressed = _compressed()
    ch = _chapter_outline("c1", ["b1"])
    _, user_prompt = build_chapter_prompts(
        compressed, ch, BiographyStyle.MEDIEVAL_CHRONICLE
    )
    # Schema 以 JSON 形式出现在 prompt 中，与 CHAPTER_JSON_SCHEMA 一致。
    assert json.dumps(CHAPTER_JSON_SCHEMA, ensure_ascii=False, indent=2) in user_prompt
    assert "medieval_chronicle" in user_prompt


def test_build_chapter_repair_prompt():
    base = "原始 prompt"
    repaired = build_chapter_repair_prompt(base, ["事件 id 不在允许列表", "正文为空"])
    assert repaired.startswith(base)
    assert "# 修复要求" in repaired
    assert "事件 id 不在允许列表" in repaired
    assert "正文为空" in repaired
