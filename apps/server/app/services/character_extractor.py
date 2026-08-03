"""CharacterExtractor —— 把 ck3-reader 的人物 stub 映射为 save-schema 契约。

当前 reader 提取的字段（占位 token 表下）：
  - name / culture 为**本地化字符串键**（如 "Hua_83EF" / "asian_han_chinese"），
    可由 LocalizationLoader 解析为可读中文名。
  - faith / dynasty 为**数字/ token-id**（如 41 / 9067），占位表下无法解析为可读名，
    保留为 EntityRef(id=原值)，并标记 resolved=False；绝不伪造名称。
  - sex / 关系 / 头衔 / 特质（完整对象）为 Phase-2 扩展，留默认值，绝不伪造。

映射规则：
  - 字符串键字段优先用 loader 解析（zh-Hans → english → 原 key）；解析不到则保留原键。
  - 数字 id 字段保留 id，name 回退为原 id，resolved=False。
  - isAlive 直接来自 reader 的 alive 判定。
"""
from __future__ import annotations

from typing import Optional

from models import CharacterProfile, CharacterSummary, EntityRef

from app.services.localization import LocalizationLoader


def _entity(ref_id, ref_type: str, loader: Optional[LocalizationLoader] = None) -> Optional[EntityRef]:
    if not ref_id:
        return None
    sid = str(ref_id)
    # 数字/token-id（如 "41"、"9067"、"t2ea6"）→ 无法本地化，保留 id 并标记未解析
    if sid.isdigit() or (sid.startswith("t") and sid[1:].isdigit()):
        return EntityRef(id=sid, name=sid, type=ref_type, resolved=False)
    # 字符串键（如 "asian_han_chinese"）→ 尝试本地化
    if loader is not None:
        resolved = loader.resolve(sid)
        if resolved:
            return EntityRef(id=sid, name=resolved, type=ref_type, resolved=True)
    return EntityRef(id=sid, name=sid, type=ref_type, resolved=False)


def to_summary(stub: dict, loader: Optional[LocalizationLoader] = None) -> CharacterSummary:
    name_key = stub.get("name") or ""
    name = loader.resolve(name_key) if (loader and name_key) else name_key
    return CharacterSummary(
        id=str(stub.get("id")),
        name=name or name_key,
        birthDate=stub.get("birth"),
        deathDate=stub.get("death"),
        culture=_entity(stub.get("culture"), "culture", loader),
        faith=_entity(stub.get("faith"), "faith", loader),
        dynasty=_entity(stub.get("dynasty"), "dynasty", loader),
        isAlive=bool(stub.get("alive", True)),
        isRuler=False,
        isPlayerDynasty=False,
        evidenceWarningCount=0,
    )


def to_profile(stub: dict, loader: Optional[LocalizationLoader] = None) -> CharacterProfile:
    """由基础 stub 构建部分 CharacterProfile（基础字段 + 本地化；其余 Phase-2 扩展）。"""
    name_key = stub.get("name") or ""
    name = loader.resolve(name_key) if (loader and name_key) else name_key
    return CharacterProfile(
        id=str(stub.get("id")),
        name=name or name_key,
        birthDate=stub.get("birth"),
        deathDate=stub.get("death"),
        culture=_entity(stub.get("culture"), "culture", loader),
        faith=_entity(stub.get("faith"), "faith", loader),
        dynasty=_entity(stub.get("dynasty"), "dynasty", loader),
        traits=[],
        titles=[],
        residences=[],
        courtPositions=[],
        parents=[],
        spouses=[],
        children=[],
        siblings=[],
        friends=[],
        rivals=[],
        lovers=[],
        wars=[],
        imprisonments=[],
        travels=[],
        memories=[],
        timeline=[],
        evidenceWarnings=[],
    )
