"""事件重要度评分（Phase 3A 5.5）—— 纯函数、可测试、可解释。

规则全部确定性，不依赖随机数 / LLM，不改变事件事实。
强制保留规则（出生/死亡/最高等级头衔/人生阶段代表）在 compressor 中执行；
此处只产出可累加的评分分解。
"""
from __future__ import annotations

from typing import Dict, Optional, Union

from models import CharacterProfile, Confidence, EventType, TimelineEvent

# 高优先级事件类型（人生大事 / 头衔 / 战争等）。
_HIGH_PRIORITY_TYPES = {
    EventType.BIRTH,
    EventType.DEATH,
    EventType.SUCCESSION,
    EventType.TITLE_GAIN,
    EventType.TITLE_LOSS,
    EventType.MARRIAGE,
    EventType.CHILD_BIRTH,
    EventType.WAR,
    EventType.IMPRISONMENT,
    EventType.CONVERSION,
}

# 技术性状态（纯记录，不做人生节点突出展示）。
_TECHNICAL_TYPES = {
    EventType.TRAVEL,
    EventType.COURT_POSITION,
    EventType.OTHER,
}

# 类型基础分。
_TYPE_BASE: Dict[EventType, float] = {
    EventType.BIRTH: 40,
    EventType.DEATH: 40,
    EventType.SUCCESSION: 40,
    EventType.TITLE_GAIN: 40,
    EventType.TITLE_LOSS: 40,
    EventType.MARRIAGE: 30,
    EventType.CHILD_BIRTH: 30,
    EventType.WAR: 25,
    EventType.IMPRISONMENT: 25,
    EventType.CONVERSION: 25,
    EventType.DIVORCE: 18,
    EventType.EXILE: 20,
    EventType.TRAIT_GAIN: 12,
    EventType.SUCCESS: 12,
    EventType.FAILURE: 10,
    EventType.TRAVEL: 8,
    EventType.COURT_POSITION: 8,
    EventType.OTHER: 5,
}

# 头衔等级数值（用于最高等级头衔加权）。
_TIER_VALUE = {
    "empire": 5,
    "kingdom": 4,
    "duchy": 3,
    "county": 2,
    "barony": 1,
}


def highest_title_tier_value(profile: CharacterProfile) -> int:
    """profile 的最高头衔等级数值（无头衔 → 0）。"""
    best = 0
    for t in profile.titles or []:
        tier = getattr(t, "tier", None)
        if tier is None:
            continue
        # TitleTier 是 (str, Enum)：str(枚举) 返回 "TitleTier.KINGDOM" 而非 "kingdom"。
        v = _TIER_VALUE.get(getattr(tier, "value", str(tier)), 0)
        if v > best:
            best = v
    return best


def score_event_breakdown(
    event: TimelineEvent, profile: CharacterProfile
) -> Dict[str, float]:
    """返回该事件的评分分解（便于测试 / 解释）。"""
    b: Dict[str, float] = {}
    # 1) 类型权重：高优先级 > 技术性 > 一般。
    b["type"] = _TYPE_BASE.get(event.type, 5)
    # 2) confidence：confirmed 加分，uncertain 减分。
    if event.confidence == Confidence.CONFIRMED:
        b["confidence"] = 10
    elif event.confidence == Confidence.UNCERTAIN:
        b["confidence"] = -5
    else:  # inferred
        b["confidence"] = 0
    # 3) 证据：多条证据更可信；无证据大减分。
    n = len(event.evidence or [])
    b["evidence"] = 5 if n >= 2 else (2 if n >= 1 else -10)
    # 4) mergedCount>1：合并事件承载更多记录。
    b["merged"] = 3 if (event.mergedCount or 0) > 1 else 0
    # 5) 缺日期降权。
    b["date"] = 5 if event.date else -10
    # 6) 最高等级头衔相关事件加权（title_gain/loss/succession 且人物有高等级头衔）。
    if event.type in (EventType.TITLE_GAIN, EventType.TITLE_LOSS, EventType.SUCCESSION):
        top = highest_title_tier_value(profile)
        b["top_title"] = 10 if top >= 3 else 5 if top > 0 else 0
    else:
        b["top_title"] = 0
    # 7) unresolved 相关实体降权：事件引用的相关人物含 unresolved 数字名。
    if _has_unresolved_related(event):
        b["unresolved"] = -8
    else:
        b["unresolved"] = 0
    return b


def score_event(event: TimelineEvent, profile: CharacterProfile) -> float:
    """事件总重要度（sum of breakdown）。"""
    return float(sum(score_event_breakdown(event, profile).values()))


def _has_unresolved_related(event: TimelineEvent) -> bool:
    for ref in event.relatedCharacters or []:
        resolved = getattr(ref, "resolved", None)
        name = getattr(ref, "name", "") or ""
        if resolved is not True and name.isdigit():
            return True
    return False


def is_mandatory_keep(event: TimelineEvent) -> bool:
    """必须保留的事件（compressor 强约束）：出生 / 死亡。"""
    return event.type in (EventType.BIRTH, EventType.DEATH)
