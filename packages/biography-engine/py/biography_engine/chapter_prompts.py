"""版本化章节正文 Prompt（Phase 3B 第 6 步）。

正文按章节逐次调用模型：user_prompt 只含
  - 压缩档案（身份/家庭/头衔/关系/亲属/统治/战争/告警摘要）；
  - **本章允许的事件**（把 `compressed.selectedEvents` 过滤到 `chapter.eventIds`）。
绝不传入：其他章节允许的事件、原始 .ck3 / melted.txt / 完整人物库 / 本地绝对路径 / API Key。
"""
from __future__ import annotations

import json
from importlib import resources
from typing import List

from models import BiographyChapterOutline, BiographyStyle

from .models import CompressedProfile
from .prompt_builder import (
    _events_block,
    _fact_block,
    _identity_extra_block,
    _relative_block,
    _STYLE_LABELS,
    _summary_blocks,
    load_system_prompt,
)

# 版本号即文件名（升级 prompt 就换新文件 + 新常量）。
CHAPTER_PROMPT_VERSION = "biography-chapter.zh-Hans.v1"
_CHAPTER_PROMPT_RESOURCE = "prompts/biography-chapter.zh-Hans.v1.txt"

# 单章输出 Schema（与 save-schema 的 BiographyChapter 对应）。
CHAPTER_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "content": {"type": "string"},
        "eventIds": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
    },
    "required": ["id", "title", "content", "eventIds"],
}


def load_chapter_system_prompt() -> str:
    """读取版本化章节 System Prompt（包资源）。"""
    text = resources.files("biography_engine").joinpath(_CHAPTER_PROMPT_RESOURCE).read_text(
        encoding="utf-8"
    )
    return text.strip()


def build_chapter_prompts(
    compressed: CompressedProfile,
    chapter_outline: BiographyChapterOutline,
    style: BiographyStyle,
) -> tuple[str, str]:
    """返回 (system_prompt, user_prompt)。user_prompt 只含该章允许的事件。"""
    allowed = set(chapter_outline.eventIds)
    chapter_events = [e for e in compressed.selectedEvents if e.eventId in allowed]
    style_label = _STYLE_LABELS.get(style, style.value)

    user_parts = [
        "# 人物压缩档案（唯一事实来源，不得超出此范围）",
        f"人物：{compressed.displayName}（id={compressed.profileId}）",
        f"生卒：{compressed.lifeSpan or '未知'}",
        _fact_block("身份", compressed.identityFacts),
        _identity_extra_block(compressed),
        _fact_block("家庭", compressed.familyFacts),
        _fact_block("头衔", compressed.titleFacts),
        _fact_block("关系", compressed.relationshipFacts),
        _relative_block(compressed.relatives),
        *_summary_blocks(compressed),
        "",
        "# 本章任务",
        f"章节：{chapter_outline.id}《{chapter_outline.title}》",
        f"章节摘要：{chapter_outline.summary}",
        "",
        f"# 本章允许事件（仅以下 {len(chapter_events)} 条，不得引用其外事件）",
        _events_block(chapter_events),
        "",
        "# 生成要求",
        f"文风：{style.value}（{style_label}）",
        "只依据本章允许事件撰写正文；绝不虚构事实/人物/对白/心理描写/战役细节。",
        "inferred（推断）内容必须带「据推断/可能」措辞；防御战争写「卷入/抵御」，绝不写「宣战」。",
        "正文不得出现：数字人物 id、tXXXX、存档路径、内部枚举（如 title_gain）、"
        "JSON/schema/prompt 等元信息、markdown 标记。",
        "输出必须符合 JSON Schema；eventIds 必须来自本章允许事件（可保留全部或子集，不得为空）。",
        json.dumps(CHAPTER_JSON_SCHEMA, ensure_ascii=False, indent=2),
    ]
    return load_chapter_system_prompt(), "\n".join(user_parts)


def build_chapter_repair_prompt(user_prompt: str, errors: List[str]) -> str:
    """在原 user_prompt 基础上追加修复说明（有限次数重试用）。"""
    fix = [
        "",
        "# 修复要求",
        "上一次输出未通过校验，原因如下：",
        *[f"- {e}" for e in errors],
        "请修正后重新输出完整 JSON（不要额外解释，不要改事实）。",
    ]
    return user_prompt + "\n" + "\n".join(fix)
