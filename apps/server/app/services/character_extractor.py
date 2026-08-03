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

    # 存活与否由所在容器决定（living / dead_prunable / dead_unprunable），
    # 死亡日期取自 dead_data.date。不再使用任何 "9999.1.1" 哨兵值。
    alive = stub.get("alive", True)
    death = stub.get("death")
    if not alive and death:
        reason = stub.get("death_reason")
        killer = stub.get("killer")
        desc = f"{name} 于 {death} 逝世。"
        if reason:
            # reason 是本地化键（如 death_disappearance），未本地化时如实展示原键。
            desc += f"（死因键：{reason}）"
        evidence = [
            EvidenceRef(
                id=f"{cid}-death-ev",
                sourceType="save_block",
                sourcePath=f"character/{cid}/dead_data/date",
                rawKey="dead_data.date",
                description="存档 gamestate 中 dead_data 块记录的死亡日期",
                confidence=Confidence.CONFIRMED,
            )
        ]
        if reason:
            evidence.append(
                EvidenceRef(
                    id=f"{cid}-death-reason-ev",
                    sourceType="save_block",
                    sourcePath=f"character/{cid}/dead_data/reason",
                    rawKey="dead_data.reason",
                    description="存档记录的死因键（未本地化时保留原键）",
                    confidence=Confidence.CONFIRMED,
                )
            )
        if killer:
            desc += f"（存档记录的加害者 id：{killer}）"
            evidence.append(
                EvidenceRef(
                    id=f"{cid}-death-killer-ev",
                    sourceType="save_block",
                    sourcePath=f"character/{cid}/dead_data/killer",
                    rawKey="dead_data.killer",
                    description="存档记录的加害者人物 id",
                    confidence=Confidence.CONFIRMED,
                )
            )
        events.append(
            TimelineEvent(
                id=f"{cid}-death",
                type=EventType.DEATH,
                title="逝世",
                date=death,
                description=desc,
                confidence=Confidence.CONFIRMED,
                sourcePath=f"character/{cid}/dead_data/date",
                evidence=evidence,
            )
        )
    elif not alive:
        warnings.append(
            EvidenceWarning(
                code="unresolved_death_date",
                message="该人物位于死者容器，但存档未记录死亡日期。",
                severity=WarningSeverity.WARNING,
                sourcePath=f"character/{cid}/dead_data/date",
            )
        )

    # 亲子关系在 CK3 存档中没有直述字段，只能由父母的 child 列表反推 → 属推断。
    if stub.get("parent_source") == "child_backref" and (
        stub.get("father") or stub.get("mother")
    ):
        warnings.append(
            EvidenceWarning(
                code="inferred_parent",
                message=(
                    "存档人物块不存在 father/mother 字段；此处的父母由其他人物的 "
                    "child 列表反向推断得出，属推断而非存档直述。"
                ),
                severity=WarningSeverity.INFO,
                sourcePath=f"character/{cid}/parents",
            )
        )

    # 值为数字 id、尚无实体索引可解析的字段：明确标记 unresolved，绝不伪造名称。
    for raw in stub.get("evidence_warnings", []) or []:
        # 读取器输出形如 "faith:numeric_id"；兼容旧格式（纯字段名）。
        field_name, _, kind = str(raw).partition(":")
        if kind == "numeric_id":
            message = (
                f"字段 {field_name} 的值是数字 id，尚未建立实体索引，"
                f"只能原样展示 id（不伪造名称）。"
            )
        else:
            message = f"字段 {field_name} 无法解析为可读值（不伪造）。"
        warnings.append(
            EvidenceWarning(
                code=f"unresolved_{field_name}",
                message=message,
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
        # 人物块中不存在 primary_title 字段（实测出现 0 次）；头衔归属须从
        # landed_titles 的 holder/history 反解，属 Phase 2B M3 范围。
        primaryTitle=None,
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

    # 父母：CK3 存档没有 father/mother 字段，这两项由父母侧的 child 列表反推，
    # 因此 sourcePath 显式带上推断来源，供史料依据面板如实展示。
    # real_father（私生子生父）是存档直述字段，与反推出的父亲**并存且语义不同**，
    # 任何一方都不得覆盖另一方。
    backref = stub.get("parent_source") == "child_backref"
    suffix = "#inferred_from_child_backref" if backref else ""
    parents: list[CharacterRef] = []
    if stub.get("father"):
        parents.append(
            _entity_ref_for(stub["father"], f"character/{cid}/father{suffix}")
        )
    if stub.get("mother"):
        parents.append(
            _entity_ref_for(stub["mother"], f"character/{cid}/mother{suffix}")
        )
    if stub.get("real_father"):
        parents.append(
            _entity_ref_for(
                stub["real_father"], f"character/{cid}/family_data/real_father"
            )
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
        titles=[],  # 头衔须从 landed_titles 反解（Phase 2B M3）
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
