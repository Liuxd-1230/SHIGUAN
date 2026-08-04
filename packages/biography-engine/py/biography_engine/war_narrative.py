"""WarNarrativeNormalizer —— 战争叙事归一（Phase 3A.1）。

把时间线里的主要战争事件归一为确定性中文叙事摘要，供 LLM prompt 使用。
全部确定性（同输入同输出），**不调用 LLM**。

规则（诚实性）：
  - 只处理主要战争语义的 WAR 事件（war_won / war_lost / defensive_war /
    offensive_war）；battle_* 单场小战役不进叙事。
  - role / outcome 由事件标题确定性推导：
      war_won           → outcome=won，role 未知（存档不记录宣战方）
      war_lost          → outcome=lost，role 未知
      defensive_war     → role=defender，outcome 未知 →「卷入防御战争」
      offensive_war     → role=attacker，outcome 未知 →「卷入进攻战争」
  - 绝不把 defender / unknown 写成主动宣战，不编造战争原因（存档无 war→cause 关联字段）。
  - 对手名只写已解析名（数字占位名经 sanitize 后跳过，不写占位）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from models import EventType, TimelineEvent

from app.services.llm_input_filter import sanitize_character_ref_for_llm

# 事件标题（由 memory_timeline_extractor 生成）→ 语义。
_WAR_TITLES = {
    "战争获胜": ("won", "unknown"),
    "战争失利": ("lost", "unknown"),
    "卷入防御战争": ("unknown", "defender"),
    "卷入进攻战争": ("unknown", "attacker"),
}


@dataclass(frozen=True)
class WarNarrative:
    """单场战争的归一化叙事摘要。"""

    date: Optional[str]
    outcome: str  # won / lost / unknown
    role: str     # attacker / defender / unknown
    opponent: Optional[str]
    text: str


def _opponent_name(event: TimelineEvent) -> Optional[str]:
    """取首个可安全写入自然语言的对手名（unresolved 数字占位跳过）。"""
    for ref in event.relatedCharacters or []:
        name = sanitize_character_ref_for_llm(ref)
        if name is not None:
            return name
    return None


def _normalize_one(event: TimelineEvent) -> Optional[WarNarrative]:
    if event.type != EventType.WAR:
        return None
    title = event.title or ""
    if title not in _WAR_TITLES:
        return None
    outcome, role = _WAR_TITLES[title]
    opponent = _opponent_name(event)
    date = event.date or "日期未知"
    if title == "战争获胜":
        text = f"{date} 赢得一场战争" + (f"，对手：{opponent}。" if opponent else "。")
    elif title == "战争失利":
        text = f"{date} 在一场战争中失利" + (f"，对方：{opponent}。" if opponent else "。")
    elif title == "卷入防御战争":
        # defender：如实写「卷入防御战争」，绝不写「主动宣战」。
        text = f"{date} 卷入一场防御战争" + (f"，对方：{opponent}。" if opponent else "。")
    else:  # 卷入进攻战争
        # attacker 不等于宣战方（可能是随盟友参战），如实写「卷入进攻战争」。
        text = f"{date} 卷入一场进攻战争" + (f"，对方：{opponent}。" if opponent else "。")
    return WarNarrative(
        date=event.date,
        outcome=outcome,
        role=role,
        opponent=opponent,
        text=text,
    )


class WarNarrativeNormalizer:
    """从时间线事件提取主要战争并归一为中文叙事（确定性）。"""

    def normalize(self, events: list[TimelineEvent]) -> list[WarNarrative]:
        out: list[WarNarrative] = []
        for e in events:
            n = _normalize_one(e)
            if n is not None:
                out.append(n)
        # 确定性排序：日期数值升序 → 对手名。
        out.sort(
            key=lambda n: (
                tuple(int(p) for p in (n.date or "").split(".")[:3])
                if n.date
                else (9999, 1, 1),
                n.opponent or "",
            )
        )
        return out

    def to_text(self, events: list[TimelineEvent]) -> list[str]:
        return [n.text for n in self.normalize(events)]
