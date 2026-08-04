"""TimelineBuilder —— 统一构建去重合并后的契约时间线（M5）。

背景：`CharacterProfile.timeline` 由三处来源拼接（基础 birth/death 事件、
头衔 title_gain/loss/succession 事件、记忆 married/child_birth/death/war 事件），
此前仅按日期排序，**无去重合并**。真实存档抽样 400 人中 43 人（≈11%）时间线内
存在重复事件：同一孩子出生同时有 child_born + first_born/twins_born 双记忆记录
（同 child + 同 date），会在时间线里出现两条 child_birth。

本模块提供 `merge_timeline(events)` 纯函数：
  - 去重键 `(type, date, 首位 relatedCharacter/relatedTitle/location id)`；
    无日期的条目**不参与合并**（日期不确定就不冒险合并）。
  - 合并：保留组内 id 最小（稳定）的事件为主事件，其余并入；evidence 按 id
    聚合去重（合并后 0 事件缺证据保持不变）；mergedCount = 组大小。
  - 排序沿用 `_date_key`（CK3 日期数值比较，未知日期排最后），保持各页/章节稳定顺序。

诚实性原则：合并是"同一存档记录的多处重复呈现"归并，不新增任何事实；
被合并条目的全部证据仍保留，可完整追溯。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from models import TimelineEvent

from app.services.title_reign_extractor import _date_key


@dataclass
class TimelineMergeResult:
    """merge_timeline 的产出。"""

    timeline: list[TimelineEvent] = field(default_factory=list)
    # 合并的总条数（进入组但被并入主事件、不再单独呈现的事件数）。
    merged_count: int = 0
    # 每次合并的说明：{"key_type", "date", "primary", "merged_ids"}。
    merge_details: list[dict] = field(default_factory=list)


def _dedup_key(e: TimelineEvent) -> Optional[tuple]:
    """去重键：(type, date, 首位相关实体 id)。

    无日期 → None（不参与合并）。首相关实体：relatedCharacters[0] 优先
    （child_birth 的 child、marriage 的 spouse、death 的离世者），
    其次 relatedTitles[0]（title_gain/loss 的 titleId），再其次 location。
    对 date 无日期的战争事件也能靠 location 合并。
    """
    if not e.date:
        return None
    anchor = None
    if e.relatedCharacters:
        anchor = e.relatedCharacters[0].id
    elif e.relatedTitles:
        anchor = e.relatedTitles[0].id
    elif e.location:
        anchor = e.location.id
    return (e.type.value, str(e.date), anchor or "")


def _pick_primary(group: list[TimelineEvent]) -> TimelineEvent:
    """组内选主事件：id 最小（稳定），保证同一组多次调用选择一致。"""
    return min(group, key=lambda e: (e.id, e.date or ""))


def merge_timeline(events: list[TimelineEvent]) -> TimelineMergeResult:
    """把基础/头衔/记忆三来源事件去重合并并排序。

    规则：
      - 同 (type, date, 首相关实体) 且日期存在 → 归为一组；无日期不合并。
      - 组内保留 id 最小的事件为主事件，其余并入（evidence 按 id 聚合去重，
        mergedCount=组大小）；主事件 id 稳定可被前端/提纲引用。
      - 结果按 `_date_key` 排序（未知日期排最后），同键保持稳定顺序。
    """
    groups: dict[tuple, list[TimelineEvent]] = {}
    singles: list[TimelineEvent] = []
    for e in events:
        key = _dedup_key(e)
        if key is None:
            singles.append(e)
        else:
            groups.setdefault(key, []).append(e)

    out: list[TimelineEvent] = []
    merged_count = 0
    details: list[dict] = []
    for key, group in groups.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        primary = _pick_primary(group)
        merged_evidence: dict[str, object] = {}
        for ev in group:
            for ref in ev.evidence:
                merged_evidence.setdefault(ref.id, ref)
        # 描述里如实注明合并来源（不新增事实，只是归并重复呈现）。
        merged_ids = [e.id for e in group if e.id != primary.id]
        base_desc = primary.description
        if not primary.description.endswith("。"):
            base_desc += "。"
        primary = primary.model_copy(
            update={
                "evidence": list(merged_evidence.values()),
                "mergedCount": len(group),
                "description": (
                    f"{base_desc}（存档另有 {len(merged_ids)} 条重复记录，已合并，"
                    f"证据均已保留）"
                ),
            }
        )
        out.append(primary)
        merged_count += len(merged_ids)
        details.append(
            {
                "key_type": key[0],
                "date": key[1],
                "primary": primary.id,
                "merged_ids": sorted(merged_ids),
            }
        )
    out.extend(singles)
    out.sort(key=lambda e: (_date_key(e.date), e.type.value, e.id))
    return TimelineMergeResult(
        timeline=out, merged_count=merged_count, merge_details=details
    )
