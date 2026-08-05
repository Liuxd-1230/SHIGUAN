"""确定性史料摘要（Phase 3C.4 NarrativeSummaryBuilder）。

页面「史料摘要」区、AI 提纲与 AI 正文**统一**使用同一个 CompressedProfile v3，
并由本模块生成确定性摘要文本（不调用 LLM、不推断因果、不出现技术字段）。

输出结构（前端分区展示顺序）：
  1. 一句话生平（姓名 + 生卒 + 主要身份 headline）
  2. 身份（realmStatus / 主要领地 / 官职机构 / 宗教 / 荣誉 / 宣称）
  3. 统治与领土（现任领地、从属数量、历史得失计数）
  4. 关键历史语义事件（3C.3，按日期排序，带语义类型与叙事约束）
  5. 战争（WarNarrativeNormalizer 已聚合）
  6. 家庭关系（家人 / 扩展亲属 / 好友宿敌恋人 / 君主）
  7. 证据告警（已聚合）
"""
from __future__ import annotations

from typing import List

from models import HistoricalSemanticEventType

from .models import CompressedProfile

_REALM_STATUS_LABELS = {
    "independent_ruler": "独立最高统治者",
    "vassal_ruler": "封臣领主",
    "landless_official": "无地官员",
    "religious_leader": "宗教领袖",
    "regent": "摄政",
    "adventurer": "冒险者",
    "courtier": "廷臣",
    "former_ruler": "前统治者",
    "prisoner": "囚犯",
    "unknown": "身份未明",
}

_SEMANTIC_LABELS = {
    "identity_transition": "身份转变",
    "territorial_gain": "获得领地",
    "territorial_loss": "失去领地",
    "office_appointment": "就任官职",
    "office_dismissal": "卸任官职",
    "institution_transition": "机构归属变化",  # 3C.7：政权机构归属/控制关系变化，不表示个人任职
    "religious_appointment": "出任宗教职务",
    "religious_dismissal": "卸任宗教职务",
    "claim_gained": "获得宣称",
    "claim_lost": "失去宣称",
    "honor_granted": "获授荣誉",
    "honor_revoked": "荣誉被夺",
    "realm_created": "领地被创建",
    "realm_destroyed": "领地被消灭",
}


class NarrativeSummaryBuilder:
    """把 CompressedProfile v3 整理为确定性史料摘要。"""

    def one_line_life(self, c: CompressedProfile) -> str:
        """一句话生平：姓名（生卒）· 主要身份。"""
        name = c.displayName
        span = c.identity.lifeSpan or "生卒不详"
        headline = c.identity.headlineIdentity or ""
        parts = [f"{name}（{span}）"]
        if headline:
            parts.append(headline)
        return "；".join(parts)

    def sections(self, c: CompressedProfile) -> dict[str, List[str]]:
        """确定性摘要各分区（前端展示 / LLM 输入共用）。"""
        identity: List[str] = []
        if c.identity.realmStatus:
            label = _REALM_STATUS_LABELS.get(c.identity.realmStatus, c.identity.realmStatus)
            identity.append(f"身份：{label}")
        if c.identity.primaryRealmTitle:
            identity.append(f"主要领地：{c.identity.primaryRealmTitle}")
        for s in c.identity.secondaryIdentities:
            identity.append(f"次要身份：{s}")
        if c.identity.primaryOffice:
            identity.append(f"主要官职：{c.identity.primaryOffice}")
        if c.identity.nickname:
            identity.append(f"绰号：{c.identity.nickname}")
        if c.identity.deathReason:
            identity.append(f"逝世原因：{c.identity.deathReason}")
        if c.identity.traits:
            identity.append(f"特质：{'、'.join(c.identity.traits)}")
        if c.dynasticIdentity.house:
            identity.append(f"家族：{c.dynasticIdentity.house}")
        if c.dynasticIdentity.dynasty:
            identity.append(f"王朝：{c.dynasticIdentity.dynasty}")

        territory: List[str] = []
        if c.territorialDomain.currentMajorTerritories:
            territory.append(
                "现任主要领地：" + "、".join(c.territorialDomain.currentMajorTerritories)
            )
        if c.territorialDomain.currentMinorCount > 0:
            territory.append(f"从属领地共 {c.territorialDomain.currentMinorCount} 处")
        if c.territorialDomain.historicalGainCount or c.territorialDomain.historicalLossCount:
            territory.append(
                f"历史领地得失：获得 {c.territorialDomain.historicalGainCount} 次，"
                f"失去 {c.territorialDomain.historicalLossCount} 次"
            )

        offices: List[str] = []
        offices += [f"个人官职：{n}" for n in c.personalOffices]
        offices += [f"政权机构：{n}" for n in c.realmInstitutions]
        offices += [f"宗教职务：{n}" for n in c.religiousOffices]
        offices += [f"荣誉：{n}" for n in c.honors]
        offices += [f"宣称：{n}" for n in c.claims]

        history = self.historical_events_text(c)

        family: List[str] = list(c.family)
        family += [
            f"扩展亲属（推断）：{r.relationLabel}·{r.name}"
            for r in c.relatives
        ]
        relationships: List[str] = list(c.relationships)

        warnings = list(c.warnings)
        constraints = list(c.narrativeConstraints)

        return {
            "oneLineLife": [self.one_line_life(c)],
            "identity": identity,
            "territory": territory,
            "offices": offices,
            "historicalEvents": history,
            "wars": list(c.wars),
            "family": family,
            "relationships": relationships,
            "constraints": constraints,
            "warnings": warnings,
        }

    def historical_events_text(self, c: CompressedProfile) -> List[str]:
        """历史语义事件 → 文本行（按日期数值排序；带叙事约束提示）。"""
        out: List[str] = []
        events = list(c.historicalEvents)
        events.sort(
            key=lambda e: (
                tuple(int(p) for p in (e.date or "9999.1.1").split(".")[:3]),
                e.semanticType.value,
            )
        )
        for e in events:
            label = _SEMANTIC_LABELS.get(e.semanticType.value, e.semanticType.value)
            cause = ""
            if e.acquisitionCause is not None:
                cause = f"（原因：{e.acquisitionCause.value}）"
            line = f"{e.date or '日期未知'}｜{label}：{e.summary}{cause}"
            out.append(line)
        return out

    def to_prompt_block(self, c: CompressedProfile) -> str:
        """把摘要整理为传给模型的 Markdown 块（不含技术字段）。"""
        s = self.sections(c)
        blocks = ["## 史料摘要（确定性，唯一事实来源）"]
        blocks.append("### 一句话生平")
        blocks.extend(f"- {x}" for x in s["oneLineLife"])
        blocks.append("### 身份")
        blocks.extend(f"- {x}" for x in s["identity"] or ["（无记录）"])
        if s["territory"]:
            blocks.append("### 领土")
            blocks.extend(f"- {x}" for x in s["territory"])
        if s["offices"]:
            blocks.append("### 官职与机构")
            blocks.extend(f"- {x}" for x in s["offices"])
        if s["historicalEvents"]:
            blocks.append("### 关键历史语义事件")
            blocks.extend(f"- {x}" for x in s["historicalEvents"])
        if s["wars"]:
            blocks.append("### 战争")
            blocks.extend(f"- {x}" for x in s["wars"])
        if s["family"]:
            blocks.append("### 家庭")
            blocks.extend(f"- {x}" for x in s["family"])
        if s["relationships"]:
            blocks.append("### 关系")
            blocks.extend(f"- {x}" for x in s["relationships"])
        if s["constraints"]:
            blocks.append("### 叙事约束（必须遵守）")
            blocks.extend(f"- {x}" for x in s["constraints"])
        return "\n".join(blocks)
