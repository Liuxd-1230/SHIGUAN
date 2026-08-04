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
from app.services.title_reign_extractor import _date_key

from .importance import highest_title_tier_value, is_mandatory_keep, score_event
from .models import COMPRESSION_VERSION, CompressedEvent, CompressedProfile

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
    for label, ref in (
        ("文化", profile.culture),
        ("信仰", profile.faith),
        ("王朝", profile.dynasty),
    ):
        name = _display_name_of_entity(ref)
        if name:
            facts.append(f"{label}：{name}")
    return facts


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
    for period in profile.spouses or []:
        rname = period.name
        if rname.isdigit():
            unresolved_counter[0] += 1
            continue
        tag = "前任" if period.isFormer else "配偶"
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

    return CompressedProfile(
        profileId=profile.id,
        displayName=profile.name or profile.id,
        lifeSpan=_life_span(profile),
        identityFacts=_identity_facts(profile),
        familyFacts=_family_facts(profile, unresolved_counter),
        titleFacts=_title_facts(profile),
        relationshipFacts=_relationship_facts(profile, unresolved_counter),
        selectedEvents=compressed_events,
        omittedEventCount=omitted,
        warnings=warnings,
        unresolvedCount=unresolved_counter[0],
        sourceEventIds=[e.eventId for e in compressed_events],
        compressionVersion=COMPRESSION_VERSION,
    )
