"""CharacterExtractor —— 把 ck3-reader 的人物 stub 映射为 save-schema 契约。

Phase 2A.1（规范十一）：最小可信 Profile。
  - 能可靠确认的字段（name/sex/birth/death/alive/parents/spouses/children/traits/
    当前主要头衔线索）带来源路径（character/<id>/<field>）。
  - 无法解析的字段保持为空，并加 EvidenceWarning，绝不伪造可读名/关系。
  - 占位 token 表下：faith / dynasty 为数字或 token-id → 保留 EntityRef(resolved=False)；
    primary_title 未提取 → 留空 + EvidenceWarning。
  - timeline 至少包含可确认的出生/死亡事件，且各带 EvidenceRef（证据不为空）。

映射规则：
  - 字符串键字段优先用 loader 解析（zh-Hans → english → 原 key）；解析不到则保留原键。
  - 数字 id 字段保留 id，name 回退为原 id，resolved=False。
"""
from __future__ import annotations

from typing import Optional

from models import (
    CharacterProfile,
    CharacterRef,
    CharacterSummary,
    Confidence,
    EntityRef,
    EvidenceRef,
    EvidenceWarning,
    EventType,
    RelationshipPeriod,
    Sex,
    TimelineEvent,
    TraitRecord,
    WarningSeverity,
)

from app.services.localization import LocalizationLoader


def _entity(
    ref_id, ref_type: str, loader: Optional[LocalizationLoader] = None
) -> Optional[EntityRef]:
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


def _sex_of(stub: dict) -> Optional[Sex]:
    s = stub.get("sex")
    if s == "male":
        return Sex.MALE
    if s == "female":
        return Sex.FEMALE
    return None


def _entity_ref_for(rel_id: str, source_path: str, loader=None) -> CharacterRef:
    # 我们只知关联人物的 id（文件名/存档键），不知道其显示名；如实以 id 作为 name。
    return CharacterRef(id=str(rel_id), name=str(rel_id), sourcePath=source_path)


def _build_timeline_and_evidence(
    stub: dict, name: str
) -> tuple[list[TimelineEvent], list[EvidenceWarning]]:
    cid = str(stub.get("id"))
    warnings: list[EvidenceWarning] = []
    events: list[TimelineEvent] = []

    birth = stub.get("birth")
    if birth:
        events.append(
            TimelineEvent(
                id=f"{cid}-birth",
                type=EventType.BIRTH,
                title="出生",
                date=birth,
                description=f"{name} 出生于 {birth}。",
                confidence=Confidence.CONFIRMED,
                sourcePath=f"character/{cid}/birth",
                evidence=[
                    EvidenceRef(
                        id=f"{cid}-birth-ev",
                        sourceType="save_block",
                        sourcePath=f"character/{cid}/birth",
                        rawKey="birth",
                        description="存档 gamestate 记录的出生日期",
                        confidence=Confidence.CONFIRMED,
                    )
                ],
            )
        )
    else:
        warnings.append(
            EvidenceWarning(
                code="unresolved_birth",
                message="未能从存档确认出生日期（字段缺失）。",
                severity=WarningSeverity.WARNING,
                sourcePath=f"character/{cid}/birth",
            )
        )

    alive = stub.get("alive", True)
    death = stub.get("death")
    if not alive and death and death != "9999.1.1":
        events.append(
            TimelineEvent(
                id=f"{cid}-death",
                type=EventType.DEATH,
                title="逝世",
                date=death,
                description=f"{name} 于 {death} 逝世。",
                confidence=Confidence.CONFIRMED,
                sourcePath=f"character/{cid}/death",
                evidence=[
                    EvidenceRef(
                        id=f"{cid}-death-ev",
                        sourceType="save_block",
                        sourcePath=f"character/{cid}/death",
                        rawKey="death",
                        description="存档 gamestate 记录的死亡日期",
                        confidence=Confidence.CONFIRMED,
                    )
                ],
            )
        )

    # 占位 token 表下无法解析的字段：明确标记 unresolved，绝不伪造。
    for field_name in stub.get("evidence_warnings", []) or []:
        warnings.append(
            EvidenceWarning(
                code=f"unresolved_{field_name}",
                message=(
                    f"字段 {field_name} 在占位 token 表下无法解析为可读值"
                    f"（需真实 token 表，不伪造）。"
                ),
                severity=WarningSeverity.WARNING,
                sourcePath=f"character/{cid}/{field_name}",
            )
        )
    return events, warnings


def to_summary(stub: dict, loader: Optional[LocalizationLoader] = None) -> CharacterSummary:
    name_key = stub.get("name") or ""
    name = loader.resolve(name_key) if (loader and name_key) else name_key
    return CharacterSummary(
        id=str(stub.get("id")),
        name=name or name_key,
        sex=_sex_of(stub),
        birthDate=stub.get("birth"),
        deathDate=None if stub.get("alive", True) else stub.get("death"),
        culture=_entity(stub.get("culture"), "culture", loader),
        faith=_entity(stub.get("faith"), "faith", loader),
        dynasty=_entity(stub.get("dynasty"), "dynasty", loader),
        primaryTitle=None,  # 占位 token 表下头衔未提取
        isRuler=bool(stub.get("ruler", False)),
        isAlive=bool(stub.get("alive", True)),
        isPlayerDynasty=False,
        evidenceWarningCount=len(stub.get("evidence_warnings", []) or []),
    )


def to_profile(stub: dict, loader: Optional[LocalizationLoader] = None) -> CharacterProfile:
    """由缓存人物记录构建最小可信 CharacterProfile（带来源路径与证据）。"""
    cid = str(stub.get("id"))
    name_key = stub.get("name") or ""
    name = loader.resolve(name_key) if (loader and name_key) else name_key
    alive = stub.get("alive", True)
    death = stub.get("death")

    parents: list[CharacterRef] = []
    if stub.get("father"):
        parents.append(
            _entity_ref_for(stub["father"], f"character/{cid}/father")
        )
    if stub.get("mother"):
        parents.append(
            _entity_ref_for(stub["mother"], f"character/{cid}/mother")
        )

    spouses: list[RelationshipPeriod] = []
    for s in stub.get("spouses", []) or []:
        spouses.append(
            RelationshipPeriod(
                characterId=str(s),
                name=str(s),
                type="spouse",  # type: ignore[arg-type]
                confidence=Confidence.CONFIRMED,
                sourcePath=f"character/{cid}/spouse/{s}",
            )
        )

    children: list[CharacterRef] = []
    for c in stub.get("children", []) or []:
        children.append(_entity_ref_for(c, f"character/{cid}/child/{c}"))

    traits: list[TraitRecord] = []
    for t in stub.get("traits", []) or []:
        traits.append(
            TraitRecord(
                id=str(t),
                name=loader.resolve(t) if loader else str(t),
                sourcePath=f"character/{cid}/trait_{t}",
            )
        )

    events, warnings = _build_timeline_and_evidence(stub, name or name_key)

    return CharacterProfile(
        id=cid,
        name=name or name_key,
        sex=_sex_of(stub),
        birthDate=stub.get("birth"),
        deathDate=None if alive else death,
        dynasty=_entity(stub.get("dynasty"), "dynasty", loader),
        culture=_entity(stub.get("culture"), "culture", loader),
        faith=_entity(stub.get("faith"), "faith", loader),
        traits=traits,
        titles=[],  # 占位 token 表下头衔未提取（Phase 2B）
        residences=[],
        courtPositions=[],
        parents=parents,
        spouses=spouses,
        children=children,
        siblings=[],
        friends=[],
        rivals=[],
        lovers=[],
        wars=[],
        imprisonments=[],
        travels=[],
        memories=[],
        timeline=events,
        evidenceWarnings=warnings,
    )
