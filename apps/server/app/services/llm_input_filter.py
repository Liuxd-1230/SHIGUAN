"""LLM 输入层的人物引用过滤（M5.1，为 Phase 3 传记管线做准备）。

背景：进入模型前，任何 unresolved 的人物名都不能被当作真实姓名写入自然语言摘要
（模型可能把数字 id 当人物姓名写进传记）。

规则（M5.1 4.3）：
  - `resolved` 为 false 且 `name` 是纯数字 → 该 name **不写入**自然语言摘要
    （保留 `id` 用于内部追踪，绝不把 unresolved 自动转换成「某人」等占位）；
  - 不删除原始 CharacterProfile 中的信息——前端普通档案页仍显示原始 id；
  - 这是 LLM 输入层的过滤，不是修改存档事实。
"""
from __future__ import annotations

from typing import Optional

from models import CharacterRef


def sanitize_character_ref_for_llm(ref) -> Optional[str]:
    """返回可安全写入自然语言摘要的人名；数字占位名 → None（不写入）。

    输入可以是 `CharacterRef` 模型或等价的 dict（压缩器 / 前端可能传 dict）。
    判定：`name` 为纯数字且 `resolved` 不是 True → 视为未解析占位，返回 None；
    其余情况（已解析名 / 非数字内部 key / 未标注但非数字）原样返回 `name`。
    """
    if ref is None:
        return None
    name = ref.get("name") if isinstance(ref, dict) else getattr(ref, "name", None)
    if not name:
        return None
    resolved = (
        ref.get("resolved") if isinstance(ref, dict) else getattr(ref, "resolved", None)
    )
    if str(name).isdigit() and resolved is not True:
        return None
    return str(name)


def sanitize_character_refs_for_llm(refs) -> list[str]:
    """批量过滤：只保留可安全写入摘要的人名（顺序不变）。"""
    out: list[str] = []
    for r in refs or []:
        name = sanitize_character_ref_for_llm(r)
        if name is not None:
            out.append(name)
    return out
