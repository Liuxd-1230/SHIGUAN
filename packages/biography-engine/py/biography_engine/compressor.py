"""确定性档案压缩（Phase 3A 5.4）。

`compress_profile` 把 CharacterProfile 压缩成 CompressedProfile（唯一允许传给模型的载体）。
规则全部确定性（同输入同配置 → 同输出），**禁止调用 LLM**；
unresolved 数字人物名不进入自然语言摘要（走 llm_input_filter）。

强制保留（优先于 max_events）：
  - 出生 / 死亡事件（存在时）
  - 至少一个最高等级头衔事件（存在时）
  - 每个十年阶段（decade）的代表事件（保证人生各阶段都有呈现）
"""
from __future__ import annotations

from typing import Optional

from models import CharacterProfile, Confidence, TimelineEvent

from app.services.llm_input_filter import sanitize_character_ref_for_llm
from .title_semantics import _date_key  # 3C.3：解耦，避免 biography_engine ↔ app 循环导入（完整 v3 见 3C.4）

from .importance import highest_title_tier_value, is_mandatory_keep, score_event
from .models import COMPRESSION_VERSION, CompressedEvent, CompressedProfile, CompressedRelative
from .war_narrative import WarNarrativeNormalizer
from .warning_aggregator import aggregate_warnings

# 扩展亲属的分类与中文标签（顺序即展示顺序）。全部为推断（derive_extended_relations）。
RELATIVE_KINDS = ("grandparent", "aunt_uncle", "cousin", "nephew", "in_law")
RELATIVE_LABELS = {
    "grandparent": "祖辈",
    "aunt_uncle": "叔伯姑舅",
    "cousin": "堂表亲",
    "nephew": "侄甥",
    "in_law": "姻亲",
}
# 每组亲属在压缩档案中展示的数量上限（3A.1：确定性限量 4/6/6/6/6，超限在 warnings 如实计数）。
RELATIVE_MAX_PER_GROUP = {
    "grandparent": 4,
    "aunt_uncle": 6,
    "cousin": 6,
    "nephew": 6,
    "in_law": 6,
}
DEFAULT_MAX_RELATIVES_PER_GROUP = 5  # 向后兼容旧配置的默认值（v1 行为）
# traits 展示上限。
MAX_TRAITS = 10

# 头衔等级排序（reignSummary 的 majorTitles 排序用）。
_TIER_RANK = {
    "barony": 0,
    "county": 1,
    "duchy": 2,
    "kingdom": 3,
    "empire": 4,
}

# 一个事件用于"阶段代表"的最早可能日期分桶（按年份 decade）。
def _decade_of(date: Optional[str]) -> Optional[int]:
    if not date:
        return None
    try:
        return int(date.split(".")[0]) // 10
    except ValueError:
        return None


def _factual_summary(event: TimelineEvent) -> str:
    """事实性摘要：确定性取自事件描述（由解析层生成，全部基于存档事实）。"""
    return event.description or event.title or event.type.value


def _related_names(event: TimelineEvent) -> list[str]:
    out: list[str] = []
    for ref in event.relatedCharacters or []:
        name = sanitize_character_ref_for_llm(ref)
        if name is not None:
            out.append(name)
    return out


def _display_name_of_entity(ref) -> str:
    """实体的可读名：resolved / 非数字名才直接用；否则标注为 id（不编造）。"""
    if ref is None:
        return ""
    name = getattr(ref, "name", None) or ""
    resolved = getattr(ref, "resolved", None)
    if resolved is not True and str(name).isdigit():
        return f"未解析实体(id={getattr(ref, 'id', '')})"
    return str(name)


def _life_span(profile: CharacterProfile) -> Optional[str]:
    birth = profile.birthDate
    death = profile.deathDate
    if not birth and not death:
        return None
    return f"{birth or '?'} ~ {death or '在世'}"


def _identity_facts(profile: CharacterProfile) -> list[str]:
    facts: list[str] = []
    if profile.name:
        facts.append(f"姓名：{profile.name}")
    if profile.sex is not None:
        facts.append(f"性别：{profile.sex.value}")
    if profile.birthDate:
        facts.append(f"出生：{profile.birthDate}")
    if profile.deathDate:
        facts.append(f"逝世：{profile.deathDate}")
    if profile.deathReason:
        facts.append(f"逝世原因：{profile.deathReason}")
    for label, ref in (
        ("文化", profile.culture),
        ("信仰", profile.faith),
        ("王朝", profile.dynasty),
    ):
        name = _display_name_of_entity(ref)
        if name:
            facts.append(f"{label}：{name}")
    # 3A.1：主头衔（与 reignSummary 同一确定性规则，只取现任最高等级，同级稳定取一）。
    primary = _primary_title(profile)
    if primary:
        facts.append(f"主头衔：{primary}")
    return facts


def _primary_title(profile: CharacterProfile) -> Optional[str]:
    """现任头衔中最高等级者（同级按 titleId 稳定顺序取一个）；等级未知 → None。"""
    current = [t for t in profile.titles or [] if getattr(t, "isCurrent", False)]
    if not current:
        return None
    best_tier = max(
        (t.tier for t in current if t.tier is not None),
        key=lambda t: _TIER_RANK.get(t.value, -1),
        default=None,
    )
    if best_tier is None:
        return None
    ties = sorted(
        (t for t in current if t.tier == best_tier),
        key=lambda t: str(t.titleId),
    )
    if not ties:
        return None
    chosen = ties[0]
    return str(chosen.name or chosen.titleId)


def _nickname_of(profile: CharacterProfile) -> Optional[str]:
    """绰号解析名（resolved / 非数字才写）。"""
    nk = profile.nickname
    if nk is None:
        return None
    name = nk.name or ""
    if str(name).isdigit() and nk.resolved is not True:
        return None
    return str(name)


def _house_of(profile: CharacterProfile) -> Optional[str]:
    """家族名（resolved / 非数字才写）。"""
    h = profile.house
    if h is None:
        return None
    name = getattr(h, "name", None) or ""
    if str(name).isdigit() and getattr(h, "resolved", None) is not True:
        return None
    return str(name)


def _liege_name_of(profile: CharacterProfile) -> Optional[str]:
    """君主名（resolved 才写；无 → None）。"""
    lg = profile.liege
    if lg is None:
        return None
    name = sanitize_character_ref_for_llm(lg)
    return name


def _trait_facts(profile: CharacterProfile) -> list[str]:
    """特质名：去重 + 限量（MAX_TRAITS）。数字占位名不写入。"""
    out: list[str] = []
    seen: set[str] = set()
    for t in profile.traits or []:
        name = str(t.name or "").strip()
        if not name or name.isdigit():
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= MAX_TRAITS:
            break
    return out


def _relative_kind_of(ref) -> Optional[str]:
    """从 sourcePath（character/{cid}/relatives/{rid}#inferred_from_{kind}）取关系分类。"""
    sp = getattr(ref, "sourcePath", None) or ""
    for kind in RELATIVE_KINDS:
        if f"inferred_from_{kind}" in sp:
            return kind
    return None


def _relative_facts(
    profile: CharacterProfile,
    unresolved_counter: list,
    max_per_group: Optional[dict[str, int]] = None,
) -> list[CompressedRelative]:
    """扩展亲属：按分类分组 + 组内确定性限量，返回（条目, 每组合计/展示计数）。

    全部为推断（inferred=True）；未解析数字名计入 unresolved 且不写入条目。
    组内按 id 数值升序（稳定可复现）；超限数量在返回值中如实报告，由 caller 写入 warnings。
    limits：3A.1 每组独立上限（默认 RELATIVE_MAX_PER_GROUP 4/6/6/6/6）。
    """
    max_per_group = max_per_group or RELATIVE_MAX_PER_GROUP
    out: list[CompressedRelative] = []
    groups: dict[str, list] = {k: [] for k in RELATIVE_KINDS}
    for r in profile.relatives or []:
        kind = _relative_kind_of(r)
        if kind is not None:
            groups[kind].append(r)
    stats: dict[str, tuple[int, int]] = {}  # kind -> (total, shown)
    for kind in RELATIVE_KINDS:
        items = groups[kind]
        if not items:
            continue
        items.sort(key=lambda r: (int(r.id) if str(r.id).isdigit() else 1 << 62, str(r.id)))
        total = len(items)
        shown = 0
        for r in items:
            if shown >= max_per_group.get(kind, DEFAULT_MAX_RELATIVES_PER_GROUP):
                break
            name = sanitize_character_ref_for_llm(r)
            if name is None:
                unresolved_counter[0] += 1
                continue
            out.append(
                CompressedRelative(
                    relation=kind,
                    relationLabel=RELATIVE_LABELS[kind],
                    name=name,
                    id=str(r.id),
                )
            )
            shown += 1
        stats[kind] = (total, shown)
    return out, stats


def _family_facts(profile: CharacterProfile, unresolved_counter: list) -> list[str]:
    facts: list[str] = []

    # parents / children / siblings：只保留可解析名（数字占位计入 unresolved）。
    def _fmt(label: str, refs) -> list[str]:
        out: list[str] = []
        for r in refs:
            name = sanitize_character_ref_for_llm(r)
            if name is None:
                unresolved_counter[0] += 1
                continue
            out.append(f"{label}：{name}")
        return out

    facts += _fmt("父母", profile.parents)
    facts += _fmt("子女", profile.children)
    facts += _fmt("兄弟姐妹", profile.siblings)
    # 3A.1：配偶关系按类型区分（配偶/婚约对象/妾室），isFormer 如实标注。
    for period in profile.spouses or []:
        rname = period.name
        if rname.isdigit():
            unresolved_counter[0] += 1
            continue
        rtype = getattr(period, "type", None)
        rtype_value = rtype.value if rtype is not None else None
        if rtype_value == "betrothed":
            tag = "前任婚约对象" if period.isFormer else "婚约对象"
        elif rtype_value == "concubine":
            tag = "前任妾室" if period.isFormer else "妾室"
        elif period.isFormer:
            tag = "前任配偶"
        else:
            tag = "配偶"
        facts.append(f"{tag}：{rname}")
    return facts


def _title_facts(profile: CharacterProfile) -> list[str]:
    facts: list[str] = []
    for t in profile.titles or []:
        name = str(t.name) if t.name else str(t.titleId)
        span = ""
        if t.start:
            span = f"{t.start}"
            if t.end:
                span += f" ~ {t.end}"
            elif not getattr(t, "isCurrent", False):
                span += " ~ ?"
        tier = t.tier.value if t.tier is not None else "?"
        facts.append(f"头衔：{name}（{tier}）{('，' + span) if span else ''}".strip())
    return facts


def _reign_summary(profile: CharacterProfile) -> Optional[str]:
    """统治摘要（3A.1）：现任头衔总数 + 最高等级 + 3-5 个主要头衔（确定性）。

    - 只统计 isCurrent 的头衔（与 primary_bits 同源）；
    - 主要头衔按等级降序（同级按 titleId 稳定顺序）取前 5；
    - 不含内部枚举 / 头衔 key / sourcePath（技术字段不入自然语言）。
    """
    current = [t for t in profile.titles or [] if getattr(t, "isCurrent", False)]
    if not current:
        return "无现任头衔"
    ranked = sorted(
        current,
        key=lambda t: (
            _TIER_RANK.get(t.tier.value if t.tier is not None else "", -1),
            str(t.titleId),
        ),
        reverse=True,
    )
    highest = ranked[0].tier
    tier_label = highest.value if highest is not None else "未知"
    major = ranked[:5]
    names = "、".join(str(t.name or t.titleId) for t in major)
    suffix = "" if len(ranked) <= 5 else f"等共 {len(ranked)} 个头衔"
    return f"现任 {len(ranked)} 个头衔；最高等级：{tier_label}；主要头衔：{names}{suffix}"


def _relationship_facts(profile: CharacterProfile, unresolved_counter: list) -> list[str]:
    facts: list[str] = []
    for label, refs in (("好友", profile.friends), ("宿敌", profile.rivals), ("恋人", profile.lovers)):
        names = []
        for r in refs or []:
            name = sanitize_character_ref_for_llm(r)
            if name is None:
                unresolved_counter[0] += 1
                continue
            names.append(name)
        if names:
            facts.append(f"{label}：{'、'.join(names)}")
    return facts


def _select_events(
    events: list[TimelineEvent], profile: CharacterProfile, max_events: int
) -> tuple[list[TimelineEvent], int]:
    """确定性选择：强制保留 + 阶段代表 + 分数择优，返回 (selected, omitted_count)。

    优先级（都受 max_events 硬上限约束，强制事件优先占名额）：
      1. 出生 / 死亡（存在时）；
      2. 至少一个最高等级头衔事件（存在时）；
      3. 每个「无保留事件的十年阶段」的代表事件（仅在名额允许时补充）；
      4. 其余按重要度分数降序择优。
    """
    selected: list[TimelineEvent] = []
    selected_ids: set[str] = set()

    def _keep(e: TimelineEvent) -> None:
        if e.id not in selected_ids:
            selected.append(e)
            selected_ids.add(e.id)

    # 1) 出生 / 死亡。
    for e in events:
        if is_mandatory_keep(e):
            _keep(e)
    # 2) 最高等级头衔事件（取首个 gain/loss/succession）。
    if highest_title_tier_value(profile) > 0:
        for e in events:
            if e.type.value.startswith("title_") or e.type.value == "succession":
                _keep(e)
                break
    # 3) 阶段代表：每个 decade 桶，若桶内无保留事件且名额允许 → 补桶内最高分事件。
    if len(selected) < max_events:
        by_decade: dict[int, list[TimelineEvent]] = {}
        for e in events:
            d = _decade_of(e.date)
            if d is not None:
                by_decade.setdefault(d, []).append(e)
        for bucket in by_decade.values():
            if len(selected) >= max_events:
                break
            if any(e.id in selected_ids for e in bucket):
                continue
            best = max(
                bucket,
                key=lambda e: (score_event(e, profile), _date_key(e.date), e.id),
            )
            _keep(best)

    # 4) 分数降序择优填充剩余名额（确定性：分数 → 日期 → id）。
    # 日期必须数值比较（CK3 日期未零填充，"944.10.22" 不能按字符串排在 "944.4.20" 前）。
    rest = [e for e in events if e.id not in selected_ids]
    rest.sort(
        key=lambda e: (score_event(e, profile), _date_key(e.date), e.id),
        reverse=True,
    )
    room = max(0, max_events - len(selected))
    for e in rest[:room]:
        _keep(e)

    selected.sort(key=lambda e: (_date_key(e.date), e.type.value, e.id))
    return selected, len(events) - len(selected)


def compress_profile(
    profile: CharacterProfile,
    *,
    max_events: int,
    include_inferred: bool,
    include_uncertain: bool,
) -> CompressedProfile:
    """把 CharacterProfile 确定性压缩为 CompressedProfile。

    - include_inferred=False → 丢弃 inferred 事件；include_uncertain 同理。
    - max_events 为 selectedEvents 数量上限（强制保留事件优先占名额）。
    """
    if max_events < 1:
        max_events = 1

    def _allowed(c: Confidence) -> bool:
        if c == Confidence.CONFIRMED:
            return True
        if c == Confidence.INFERRED:
            return include_inferred
        if c == Confidence.UNCERTAIN:
            return include_uncertain
        return True

    all_events = [e for e in profile.timeline if _allowed(e.confidence)]
    selected, omitted = _select_events(all_events, profile, max_events)

    unresolved_counter = [0]
    compressed_events: list[CompressedEvent] = []
    for e in selected:
        compressed_events.append(
            CompressedEvent(
                eventId=e.id,
                date=e.date,
                endDate=e.endDate,
                type=e.type.value,
                title=e.title,
                factualSummary=_factual_summary(e),
                confidence=e.confidence,
                relatedNames=_related_names(e),
                evidenceCount=len(e.evidence or []),
                mergedCount=e.mergedCount,
            )
        )
        unresolved_counter[0] += sum(
            1
            for ref in e.relatedCharacters or []
            if sanitize_character_ref_for_llm(ref) is None
        )

    warnings: list[str] = []
    if omitted > 0:
        warnings.append(
            f"共 {len(all_events)} 条时间线事件，按重要度省略 {omitted} 条"
            f"（max_events={max_events}）。"
        )

    # v2：分类亲属（确定性限量 4/6/6/6/6，超限如实计数进 warnings）。
    relatives, rel_stats = _relative_facts(profile, unresolved_counter)
    for kind, (total, shown) in rel_stats.items():
        limit = RELATIVE_MAX_PER_GROUP.get(kind, DEFAULT_MAX_RELATIVES_PER_GROUP)
        if total > shown:
            warnings.append(
                f"扩展亲属「{RELATIVE_LABELS[kind]}」共 {total} 人，"
                f"压缩档案仅展示前 {shown} 人（max_per_group={limit}）。"
            )

    # v2：君臣（liege，resolved 才写）并入关系事实块。
    relationship_facts = _relationship_facts(profile, unresolved_counter)
    liege_name = _liege_name_of(profile)
    if liege_name:
        relationship_facts.append(f"君主：{liege_name}（存于死亡记录）")

    # 3A.1 叙事摘要（确定性，非 AI）：统治 / 战争 / 告警聚合。
    reign_summary = _reign_summary(profile)
    war_summary = WarNarrativeNormalizer().to_text(all_events)
    warning_summary = aggregate_warnings(profile.evidenceWarnings)

    return CompressedProfile(
        profileId=profile.id,
        displayName=profile.name or profile.id,
        lifeSpan=_life_span(profile),
        identityFacts=_identity_facts(profile),
        familyFacts=_family_facts(profile, unresolved_counter),
        titleFacts=_title_facts(profile),
        relationshipFacts=relationship_facts,
        selectedEvents=compressed_events,
        omittedEventCount=omitted,
        warnings=warnings,
        unresolvedCount=unresolved_counter[0],
        sourceEventIds=[e.eventId for e in compressed_events],
        compressionVersion=COMPRESSION_VERSION,
        nickname=_nickname_of(profile),
        liegeName=liege_name,
        house=_house_of(profile),
        deathReason=profile.deathReason,
        traits=_trait_facts(profile),
        relatives=relatives,
        reignSummary=reign_summary,
        warSummary=war_summary,
        warningSummary=warning_summary,
    )
