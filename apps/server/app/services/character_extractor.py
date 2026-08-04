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
    RelationshipType,
    Sex,
    TimelineEvent,
    TitlePeriod,
    TraitRecord,
    WarningSeverity,
)

from app.services.localization import LocalizationLoader
from app.services.title_reign_extractor import TitleSummaryBits
from app.services.timeline_builder import merge_timeline

import re

# 拼音+汉字hex 名字段（如 "4EF2"）——4 位十六进制。
_HEX_SEG_RE = re.compile(r"^[0-9A-Fa-f]{4}$")


def _decode_hex_name(nk: str) -> Optional[str]:
    """拼音+汉字hex 形态（如 Zhongrong_4EF2_5BB9）→ 按 unicode 码点解码为汉字。

    本地化表未覆盖时的**确定性**兜底：游戏中文版即按名字生成器的码点渲染
    （4EF2=仲、5BB9=容），解码非编造。仅当解码结果全部落在 CJK 区才采用，
    防止把 Maurizio / O_zgul 这类拉丁名误判。
    """
    if not nk or "_" not in nk:
        return None
    segments = nk.split("_")
    hex_parts = [s for s in segments if _HEX_SEG_RE.match(s)]
    if not hex_parts:
        return None
    try:
        chars = "".join(chr(int(h, 16)) for h in hex_parts)
    except ValueError:
        return None
    if not chars or not all(
        "\u3400" <= c <= "\u9fff" or "\uf900" <= c <= "\ufaff" for c in chars
    ):
        return None
    return chars


def resolve_display_name(nk: str, loader: Optional[LocalizationLoader] = None) -> str:
    """把人物名字 key 解析为可读中文名（M5，与游戏中文显示一致）。

    解析顺序（诚实性优先，全部未命中才回退原 key，绝不编造）：
      1) 本地化表（zh-Hans → english）：loc key（max_chinese_male_name_117825→李瑀）
         与拉丁音译（Maurizio→毛里齐奥）都有精确条目；
      2) 拼音+汉字hex 形态（Zhongrong_4EF2_5BB9→仲容）确定性解码；
      3) 回退原 key（如纯拉丁字符串且本地化缺失时保留原文，不伪造）。
    """
    if not nk:
        return nk
    if loader is not None:
        resolved = loader.resolve(nk)
        if resolved:
            return resolved
    decoded = _decode_hex_name(nk)
    if decoded:
        return decoded
    return nk


def _resolve_char_name(cid, by_id=None, loader: Optional[LocalizationLoader] = None) -> str:
    """经会话人物索引把人物 id 解析为可读名；查不到 → 原 id（不伪造）。

    M4：人物索引里 name 是本地化键（如 max_chinese_male_name_117825），
    loader（含游戏本地化表）把它解析成真实人名；loader 缺失时回退为键本身，
    无论如何都比裸数字 id 可读。
    M5：名字解析统一走 resolve_display_name（本地化 → 拼音hex 解码 → 原 key）。
    M5.1：resolved 语义独立维护（见 _resolve_char_name_resolved）。
    """
    name, _ = _resolve_char_name_resolved(cid, by_id, loader)
    return name


def _resolve_char_name_resolved(
    cid, by_id=None, loader: Optional[LocalizationLoader] = None
) -> tuple[str, bool]:
    """解析人物 id → (可读名, resolved)。

    resolved=True 表示名字真正被「转换」过（本地化命中或拼音hex 解码成功），
    是可读姓名；False 表示仅保留原始 id / 内部 key（未伪造）。判定与
    `resolve_display_name` 一致：解析结果与原 key 不同即为成功转换。
    """
    stub = (by_id or {}).get(str(cid))
    if not stub:
        return str(cid), False
    nk = stub.get("name") or ""
    if not nk:
        return str(cid), False
    name = resolve_display_name(nk, loader)
    return name, name != nk


def _character_ref_for(
    cid, source_path: str, by_id=None, loader: Optional[LocalizationLoader] = None
) -> CharacterRef:
    """统一构建人物引用：by_id 人物索引 + loader 解析可读名，resolved 如实标注。

    M5.1：父母 / 子女 / 兄弟姐妹 / 好友 / 宿敌 / 恋人等一律经此构建；
    名字不可解析时 name=原始 id 且 resolved=False，绝不编造占位姓名。
    """
    cid_s = str(cid)
    name, resolved = _resolve_char_name_resolved(cid, by_id, loader)
    return CharacterRef(id=cid_s, name=name, sourcePath=source_path, resolved=resolved)


def _dedupe_by_id(refs: list[CharacterRef]) -> list[CharacterRef]:
    """按 id 去重并保持顺序（M5.1：父母/子女等列表不重复出现同一人物）。"""
    seen: set[str] = set()
    out: list[CharacterRef] = []
    for r in refs:
        if r.id in seen:
            continue
        seen.add(r.id)
        out.append(r)
    return out


def derive_siblings(
    stub: dict,
    by_id: Optional[dict] = None,
    loader: Optional[LocalizationLoader] = None,
) -> list[CharacterRef]:
    """由共享父母推导兄弟姐妹（M4）。

    CK3 存档没有直述的 sibling 字段；兄弟姐妹 = 与该人物共享父亲或母亲的其他人物。
    人物不在索引中 → 跳过（不伪造）；推断结果由调用方按需标注。
    M5.1：名字经 by_id + loader 解析（unresolved → 原 id + resolved=False）。
    """
    cid = str(stub.get("id"))
    if not by_id:
        return []
    father = stub.get("father")
    mother = stub.get("mother")
    out: list[CharacterRef] = []
    seen: set[str] = set()
    for other_id, other in by_id.items():
        if other_id == cid:
            continue
        if father and other.get("father") == father:
            pass
        elif mother and other.get("mother") == mother:
            pass
        else:
            continue
        if other_id in seen:
            continue
        seen.add(other_id)
        out.append(
            _character_ref_for(
                other_id,
                f"character/{cid}/siblings/{other_id}#inferred_from_shared_parent",
                by_id,
                loader,
            )
        )
    out.sort(key=lambda r: r.id)
    return out


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


def to_summary(
    stub: dict,
    loader: Optional[LocalizationLoader] = None,
    title_bits: Optional[TitleSummaryBits] = None,
) -> CharacterSummary:
    name_key = stub.get("name") or ""
    name = resolve_display_name(name_key, loader) if name_key else name_key
    warn_count = len(stub.get("evidence_warnings", []) or [])
    is_ruler = bool(stub.get("ruler", False))
    if title_bits is not None:
        # M3：由 landed_titles 反解的头衔摘要。isRuler 以“存在当前头衔”为权威补充
        # 人物块的 landed_data 判定；头衔相关告警计入 evidenceWarningCount。
        is_ruler = is_ruler or title_bits.isRuler
        warn_count += title_bits.warningCount
    return CharacterSummary(
        id=str(stub.get("id")),
        name=name or name_key,
        sex=_sex_of(stub),
        birthDate=stub.get("birth"),
        deathDate=None if stub.get("alive", True) else stub.get("death"),
        culture=_entity(stub.get("culture"), "culture", loader),
        faith=_entity(stub.get("faith"), "faith", loader),
        dynasty=_entity(stub.get("dynasty"), "dynasty", loader),
        # M3：主头衔由 landed_titles 的 holder/history 反解（见 TitleProfileIndex）。
        primaryTitle=title_bits.primary if title_bits is not None else None,
        highestTitleTier=title_bits.highestTier if title_bits is not None else None,
        isRuler=is_ruler,
        isAlive=bool(stub.get("alive", True)),
        isPlayerDynasty=False,
        evidenceWarningCount=warn_count,
    )


def _relationship_period(cid: str, rel_id, rtype: RelationshipType, source_path: str, by_id=None, loader=None, is_former: bool = False) -> RelationshipPeriod:
    """构造一段关系（M4：名字经会话索引解析，不再裸 id；former 关系带 isFormer）。"""
    return RelationshipPeriod(
        characterId=str(rel_id),
        name=_resolve_char_name(rel_id, by_id, loader),
        type=rtype,
        confidence=Confidence.CONFIRMED,
        sourcePath=source_path,
        isFormer=is_former,
    )


def to_profile(
    stub: dict,
    loader: Optional[LocalizationLoader] = None,
    title_periods: Optional[list[TitlePeriod]] = None,
    title_events: Optional[list[TimelineEvent]] = None,
    title_warnings: Optional[list[EvidenceWarning]] = None,
    by_id: Optional[dict] = None,
    memory_index=None,
) -> CharacterProfile:
    """由缓存人物记录构建最小可信 CharacterProfile（带来源路径与证据）。

    M3：title_periods 为 landed_titles 反解的任期（CharacterProfile.titles）；
    title_events 为头衔时间线事件（title_gain/loss/succession，均带 EvidenceRef）；
    title_warnings 为头衔相关告警（冲突 / 多同级推断），合并进 evidenceWarnings。
    M4：by_id 为会话人物索引（名字解析 + 兄弟推导）；memory_index 为
    MemoryTimelineIndex（memories / friends / rivals / lovers / 记忆时间线事件）。
    """
    cid = str(stub.get("id"))
    name_key = stub.get("name") or ""
    name = resolve_display_name(name_key, loader) if name_key else name_key
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
            _character_ref_for(
                stub["father"], f"character/{cid}/father{suffix}", by_id, loader
            )
        )
    if stub.get("mother"):
        parents.append(
            _character_ref_for(
                stub["mother"], f"character/{cid}/mother{suffix}", by_id, loader
            )
        )
    if stub.get("real_father"):
        parents.append(
            _character_ref_for(
                stub["real_father"],
                f"character/{cid}/family_data/real_father",
                by_id,
                loader,
            )
        )
    parents = _dedupe_by_id(parents)

    # M4：婚姻历史语义化 —— spouse（现任）/ former_spouses（前任，isFormer）/
    # betrothed（婚约）/ concubine+concubinist（妾室，含前任 isFormer）。
    spouses: list[RelationshipPeriod] = []
    for s in stub.get("spouses", []) or []:
        spouses.append(
            _relationship_period(
                cid, s, RelationshipType.SPOUSE, f"character/{cid}/spouse/{s}",
                by_id, loader,
            )
        )
    for s in stub.get("former_spouses", []) or []:
        spouses.append(
            _relationship_period(
                cid, s, RelationshipType.SPOUSE, f"character/{cid}/former_spouses/{s}",
                by_id, loader, is_former=True,
            )
        )
    betrothed = stub.get("betrothed")
    if betrothed:
        spouses.append(
            _relationship_period(
                cid, betrothed, RelationshipType.BETROTHED,
                f"character/{cid}/betrothed", by_id, loader,
            )
        )
    for s in stub.get("concubines", []) or []:
        spouses.append(
            _relationship_period(
                cid, s, RelationshipType.CONCUBINE,
                f"character/{cid}/concubine/{s}", by_id, loader,
            )
        )
    if stub.get("concubinist"):
        spouses.append(
            _relationship_period(
                cid, stub["concubinist"], RelationshipType.CONCUBINE,
                f"character/{cid}/concubinist", by_id, loader,
            )
        )
    for s in stub.get("former_concubines", []) or []:
        spouses.append(
            _relationship_period(
                cid, s, RelationshipType.CONCUBINE,
                f"character/{cid}/former_concubines/{s}", by_id, loader, is_former=True,
            )
        )
    for s in stub.get("former_concubinists", []) or []:
        spouses.append(
            _relationship_period(
                cid, s, RelationshipType.CONCUBINE,
                f"character/{cid}/former_concubinists/{s}", by_id, loader, is_former=True,
            )
        )

    children: list[CharacterRef] = []
    for c in stub.get("children", []) or []:
        children.append(
            _character_ref_for(c, f"character/{cid}/child/{c}", by_id, loader)
        )
    children = _dedupe_by_id(children)

    traits: list[TraitRecord] = []
    for t in stub.get("traits", []) or []:
        traits.append(
            TraitRecord(
                id=str(t),
                # 本地化查不到 → 回退原 id（不伪造名称，与 _entity_ref_for 一致）。
                name=(loader.resolve(t) if loader else None) or str(t),
                sourcePath=f"character/{cid}/trait_{t}",
            )
        )

    events, warnings = _build_timeline_and_evidence(stub, name or name_key)
    timeline = list(events)
    if title_events:
        timeline.extend(title_events)

    # M4：记忆时间线 + 关系列表（记忆索引缺失时保持空，绝不伪造）。
    memories: list = []
    friends: list = []
    rivals: list = []
    lovers: list = []
    if memory_index is not None:
        memories = memory_index.memories(cid)
        timeline.extend(memory_index.timeline_events(cid))
        rel = memory_index.relationships(cid)
        friends = rel.friends
        rivals = rel.rivals
        lovers = rel.lovers
        warnings = list(warnings) + list(memory_index.warnings(cid))

    # M5：三来源事件统一去重合并 + 排序（TimelineBuilder）。
    # 同一存档记录的多处重复呈现（如 child_born + first_born 双记忆同 child+date）
    # 合并为一条并聚合证据，0 事件缺证据保持不变。
    merged = merge_timeline(timeline)
    timeline = merged.timeline
    if title_warnings:
        warnings = list(warnings) + list(title_warnings)

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
        titles=title_periods or [],  # M3：由 landed_titles 反解（见 TitleProfileIndex）
        residences=[],
        courtPositions=[],
        parents=parents,
        spouses=spouses,
        children=children,
        siblings=derive_siblings(stub, by_id, loader),  # M4：共享父母推导（含推断标注）
        friends=friends,
        rivals=rivals,
        lovers=lovers,
        wars=[],
        imprisonments=[],
        travels=[],
        memories=memories,
        timeline=timeline,
        evidenceWarnings=warnings,
    )
