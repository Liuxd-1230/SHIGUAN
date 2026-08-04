"""版本化 Prompt 构建（Phase 3A 5.6）。

传给模型的**只有** CompressedProfile + 允许的 BiographyStyle + JSON Schema + 生成限制。
绝不传入：原始 .ck3 / melted.txt / 完整人物库 / 本地绝对路径 / API Key / Mod 本地路径。
"""
from __future__ import annotations

import json
from importlib import resources
from typing import List

from models import BiographyStyle

from .models import CompressedProfile

PROMPT_VERSION = "outline.zh-Hans.v1"
_PROMPT_RESOURCE = "prompts/outline.zh-Hans.v1.txt"

_STYLE_LABELS = {
    BiographyStyle.VERNACULAR_ANNALS: "白话编年体（平实叙述一生大事，按时间顺序）",
    BiographyStyle.SERIOUS_BIOGRAPHY: "严肃传记体（客观凝练，突出政绩与成败）",
    BiographyStyle.MEDIEVAL_CHRONICLE: "中古编年史风（典雅庄重，按年记事）",
    BiographyStyle.FAMILY_MEMOIR: "家族回忆录风（侧重家庭与血脉传承）",
    BiographyStyle.CONCISE_PROFILE: "简明档案式（短小精悍，只列要点）",
    BiographyStyle.COLD_HISTORIAN: "冷峻史家笔法（克制、疏离、只陈述有据之事）",
}

OUTLINE_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "profileId": {"type": "string"},
        "style": {
            "type": "string",
            "enum": [s.value for s in BiographyStyle],
        },
        "chapters": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "eventIds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                },
                "required": ["id", "title", "summary", "eventIds"],
            },
        },
    },
    "required": ["profileId", "style", "chapters"],
}

# 章节数量合理上限。
MAX_CHAPTERS = 10
MIN_CHAPTERS = 1


def load_system_prompt() -> str:
    """读取版本化 System Prompt（包资源）。"""
    text = resources.files("biography_engine").joinpath(_PROMPT_RESOURCE).read_text(
        encoding="utf-8"
    )
    return text.strip()


def _fact_block(label: str, facts: List[str]) -> str:
    if not facts:
        return f"## {label}\n（无记录）"
    return "## " + label + "\n" + "\n".join(f"- {f}" for f in facts)


def _events_block(events) -> str:
    if not events:
        return "## 事件（无）"
    lines = ["## 事件（id 列表）"]
    for e in events:
        date = e.date or "日期未知"
        conf = e.confidence.value
        rel = "、".join(e.relatedNames) if e.relatedNames else ""
        lines.append(
            f"- [{e.eventId}] {date}｜{e.type}｜{e.title}｜{e.factualSummary}"
            f"{('｜相关：' + rel) if rel else ''}｜confidence={conf}"
            f"{('｜合并自N条记录') if (e.mergedCount or 0) > 1 else ''}"
        )
    return "\n".join(lines)


def build_outline_prompts(
    compressed: CompressedProfile,
    style: BiographyStyle,
) -> tuple[str, str]:
    """返回 (system_prompt, user_prompt)。user_prompt 只含压缩档案与生成约束。"""
    style_label = _STYLE_LABELS.get(style, style.value)
    user_parts = [
        "# 人物压缩档案（唯一事实来源，不得超出此范围）",
        f"人物：{compressed.displayName}（id={compressed.profileId}）",
        f"生卒：{compressed.lifeSpan or '未知'}",
        _fact_block("身份", compressed.identityFacts),
        _fact_block("家庭", compressed.familyFacts),
        _fact_block("头衔", compressed.titleFacts),
        _fact_block("关系", compressed.relationshipFacts),
        _events_block(compressed.selectedEvents),
        "",
        f"# 生成要求",
        f"文风：{style.value}（{style_label}）",
        f"章节数：{MIN_CHAPTERS}–{MAX_CHAPTERS} 章",
        "每章 eventIds 必须非空且全部来自上面「事件（id 列表）」中的 id。",
        "必须输出符合 JSON Schema 的 JSON，schema 如下：",
        json.dumps(OUTLINE_JSON_SCHEMA, ensure_ascii=False, indent=2),
    ]
    return load_system_prompt(), "\n".join(user_parts)


def build_repair_prompt(user_prompt: str, errors: List[str]) -> str:
    """在原 user_prompt 基础上追加修复说明（有限次数重试用）。"""
    fix = [
        "",
        "# 修复要求",
        "上一次输出未通过校验，原因如下：",
        *[f"- {e}" for e in errors],
        "请修正后重新输出完整 JSON（不要额外解释，不要改事实）。",
    ]
    return user_prompt + "\n" + "\n".join(fix)
