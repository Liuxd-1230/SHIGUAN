"""提纲校验器（Phase 3A 5.7/5.8）—— eventIds 白名单 / 章节约束 / 顺序。

返回错误列表（空 = 合法）。不修改任何事实，只做校验。
"""
from __future__ import annotations

from typing import List, Optional

from models import BiographyOutline, BiographyStyle

from .prompt_builder import MAX_CHAPTERS, MIN_CHAPTERS


def _event_date_map(allowed_event_ids: List[str], compressed) -> dict[str, Optional[str]]:
    """事件 id → 日期（用于章节时间大致有序校验）。"""
    m: dict[str, Optional[str]] = {}
    for e in compressed.selectedEvents:
        m[e.eventId] = e.date
    return m


def validate_outline(
    outline: BiographyOutline,
    allowed_event_ids: List[str],
    compressed=None,
) -> List[str]:
    """校验提纲是否可接受。返回错误列表（空 = 通过）。"""
    errors: List[str] = []
    allowed = set(allowed_event_ids)

    chapters = outline.chapters
    if not chapters:
        errors.append("提纲必须至少 1 章。")
    if len(chapters) > MAX_CHAPTERS:
        errors.append(f"章节数超过上限 {MAX_CHAPTERS}。")

    # 章节 id 唯一。
    ids = [c.id for c in chapters]
    if len(ids) != len(set(ids)):
        errors.append("章节 id 重复。")

    # eventIds 非空 + 全部在白名单内（不允许引用其他人物/存档事件）。
    referenced: List[str] = []
    for c in chapters:
        if not c.eventIds:
            errors.append(f"章节「{c.id}」的 eventIds 为空。")
        for eid in c.eventIds:
            if eid not in allowed:
                errors.append(f"章节「{c.id}」引用了不存在的或非本人物的事件 id：{eid}")
            referenced.append(eid)

    # 章节按时间大致有序：取每章引用事件的最早日期，要求非递减。
    if compressed is not None and len(chapters) > 1:
        dates = _event_date_map(allowed_event_ids, compressed)
        prev: Optional[tuple[int, ...]] = None
        for c in chapters:
            ds = [dates.get(eid) for eid in c.eventIds if dates.get(eid) is not None]
            if not ds:
                continue
            # 取本章最早日期（数值比较：Y.M.D → (Y,M,D)）。
            earliest = min(_parse_date(d) for d in ds)
            if prev is not None and earliest < prev:
                errors.append(
                    f"章节顺序倒置：章节「{c.id}」的最早事件早于上一章。"
                )
            if prev is None or earliest > prev:
                prev = earliest
    return errors


def _parse_date(d: str):
    parts = d.split(".")
    nums = []
    for p in parts[:3]:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def validate_style(style_value: str) -> Optional[str]:
    """style 必须为合法 BiographyStyle；非法返回错误信息。"""
    try:
        BiographyStyle(style_value)
        return None
    except ValueError:
        return f"非法 BiographyStyle：{style_value}"
