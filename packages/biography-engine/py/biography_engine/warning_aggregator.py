"""WarningAggregator —— 证据告警聚合（Phase 3A.1）。

把一人的证据告警按 code 聚合为 LLM 可读的约束（不逐条刷屏）：
  - 同 code 告警合并为一条：计数 + 人话摘要 + 确定性解析策略；
  - **技术字段不进入聚合结果**：sourcePath / 数字 id / 内部枚举 / 头衔 key 一律不出现；
  - 未知 code 走通用摘要（去括号细节 + 去路径），策略默认为「如实标注，不推断」。

聚合键：code（告警已属于单个人物；sourcePath 中的角色/日期细节对外不必要）。
"""
from __future__ import annotations

import re
from typing import Optional

from models import EvidenceWarning

# code → (人话摘要, 解析策略)。策略描述数据层如何确定性化解该告警。
_GISTS: dict[str, tuple[str, str]] = {
    "title_holder_conflict": (
        "存在头衔现任持有者与历史记录不一致",
        "以存档头衔表的顶层持有者认定现任，不静默覆盖历史记录。",
    ),
    "primary_title_inferred": (
        "同时持有多个同级头衔，主头衔按稳定顺序取其一",
        "主头衔为推断选择，不得写成确定事实。",
    ),
    "primary_title_unresolved": (
        "持有头衔但等级未知，无法判定主头衔",
        "不强行推断主头衔，正文不得断言其主头衔。",
    ),
    "inferred_parent": (
        "父母由他人子女列表反向推断",
        "父母关系为推断而非存档直述，正文只能以「据推断」方式提及。",
    ),
    "memory_owner_unresolved": (
        "部分记忆无法确定归属人",
        "按条目中指名的人物记录，不伪造归属。",
    ),
    "relationship_inferred_from_memory": (
        "好友/宿敌/恋人关系由同日成对记忆推断",
        "关系为推断而非存档直述，正文只能以「据推断」方式提及。",
    ),
    "unresolved_birth": (
        "存档未记录出生日期",
        "不得虚构出生年份。",
    ),
    "unresolved_death_date": (
        "死者档案未记录死亡日期",
        "不得虚构死亡年份。",
    ),
}

# unresolved_{field}：字段名 → 人话（解析策略统一：不伪造名称）。
_FIELD_LABELS = {
    "primary_title": "主头衔",
    "culture": "文化",
    "faith": "信仰",
    "dynasty": "王朝",
    "house": "家族",
}

_DEFAULT_POLICY = "如实标注，不推断、不编造。"

# 去掉括号内的技术细节（头衔 key / 数字 id / 路径片段）。
_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")
# 去掉类路径片段（landed_titles/...、character/...）。
_PATH_RE = re.compile(r"\b(?:landed_titles|character|character_memory_manager)/[A-Za-z0-9_./{}()-]*")
# 去掉形如 d_xiyuan / x_mc_123 的内部 key。
_KEY_RE = re.compile(r"\b[a-z]_[a-zA-Z0-9_]+")
# 裸数字 id（不连中文的数字串）。
_NUM_RE = re.compile(r"(?<![0-9])[0-9]{2,}(?![0-9])")


def _sanitize_message(message: str) -> str:
    """去掉技术细节，保留人话大意（对未知 code 的兜底）。

    依次去除：类路径片段、内部 key（d_/x_ 前缀）、裸数字 id、括号细节、
    英文技术词（holder/history 等）。中文句意保留。
    """
    s = message or ""
    s = _PATH_RE.sub("", s)
    s = _KEY_RE.sub("", s)
    s = _NUM_RE.sub("", s)
    s = _PAREN_RE.sub("", s)
    s = re.sub(r"[A-Za-z_]+", "", s)  # 英文技术词不进自然语言
    s = re.sub(r"[ \t]+", " ", s).strip(" ；;。，,")
    return s


def _gist_for(code: str, message: str) -> tuple[str, str]:
    if code in _GISTS:
        return _GISTS[code]
    if code.startswith("unresolved_"):
        field = code[len("unresolved_") :]
        label = _FIELD_LABELS.get(field, field)
        return (
            f"字段「{label}」无法解析为可读值",
            "保留原始 id 展示，不伪造名称。",
        )
    gist = _sanitize_message(message)
    return (gist or "存在一条数据完整性告警", _DEFAULT_POLICY)


class WarningAggregator:
    """按 code 聚合 EvidenceWarning，输出 LLM 可读的约束文本。"""

    def aggregate(self, warnings: list[EvidenceWarning]) -> list[str]:
        groups: dict[str, list[EvidenceWarning]] = {}
        for w in warnings or []:
            groups.setdefault(w.code, []).append(w)
        out: list[str] = []
        for code in sorted(groups):
            ws = groups[code]
            gist, policy = _gist_for(code, ws[0].message)
            if len(ws) == 1:
                out.append(f"告警「{code}」：{gist}。解析策略：{policy}")
            else:
                out.append(
                    f"告警「{code}」× {len(ws)}：{gist}。解析策略：{policy}"
                )
        return out


def aggregate_warnings(warnings: list[EvidenceWarning]) -> list[str]:
    """便捷函数：单次聚合（供 compress_profile 使用）。"""
    return WarningAggregator().aggregate(warnings)
