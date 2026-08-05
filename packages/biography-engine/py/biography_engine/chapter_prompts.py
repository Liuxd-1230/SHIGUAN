"""版本化章节正文 Prompt（Phase 3B 第 6 步，Phase 3C.4 统一 v3 输入）。

正文按章节逐次调用模型：user_prompt 只含
  - 压缩档案 v3（NarrativeSummaryBuilder 确定性史料摘要）；
  - **本章允许的事件**（把 `compressed.selectedEvents` 过滤到 `chapter.eventIds`）；
  - **本章可用事实**（3C.5：身份事实 + 本章事件锚定的事实，供 factIds 校验）。
绝不传入：其他章节允许的事件、原始 .ck3 / melted.txt / 完整人物库 / 本地绝对路径 / API Key。
"""
from __future__ import annotations

import json
from importlib import resources
from typing import List

from models import BiographyChapterOutline, BiographyStyle

from .models import CompressedProfile
from .narrative_summary import NarrativeSummaryBuilder
from .prompt_builder import _events_block, _facts_block, _summary_block, _STYLE_LABELS, load_system_prompt

# 版本号即文件名（升级 prompt 就换新文件 + 新常量）。
CHAPTER_PROMPT_VERSION = "biography-chapter.zh-Hans.v2"
_CHAPTER_PROMPT_RESOURCE = "prompts/biography-chapter.zh-Hans.v2.txt"

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


def facts_for_chapter(
    compressed: CompressedProfile, event_ids: List[str]
) -> list:
    """本章可用事实（3C.5 确定性回填规则，与 BiographyGenerator 一致）。

    - 身份事实（f-identity-* / f-headline）：所有章节共用；
    - 事件锚定事实（f-ev-*）：仅覆盖本章 eventIds 的事件。
    返回按 (是否身份, id) 稳定排序的 FactRef 列表。
    """
    allowed = set(event_ids)
    out = []
    identity = []
    for f in compressed.facts:
        if f.id == "f-headline" or f.id.startswith("f-identity-"):
            identity.append(f)
        elif any(eid in allowed for eid in (f.sourceEventIds or [])):
            out.append(f)
    identity.sort(key=lambda f: f.id)
    out.sort(key=lambda f: f.id)
    return identity + out


def build_chapter_prompts(
    compressed: CompressedProfile,
    chapter_outline: BiographyChapterOutline,
    style: BiographyStyle,
) -> tuple[str, str]:
    """返回 (system_prompt, user_prompt)。user_prompt 只含该章允许的事件与事实。"""
    allowed = set(chapter_outline.eventIds)
    chapter_events = [e for e in compressed.selectedEvents if e.eventId in allowed]
    chapter_facts = facts_for_chapter(compressed, chapter_outline.eventIds)
    style_label = _STYLE_LABELS.get(style, style.value)

    user_parts = [
        "# 人物压缩档案（唯一事实来源，不得超出此范围）",
        f"人物：{compressed.displayName}（id={compressed.profileId}）",
        _summary_block(compressed),
        _facts_block(chapter_facts),
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
        "必须遵守「叙事约束」：头衔获得原因存档未记录时，不得写成继承/征服/册封。",
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
