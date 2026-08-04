"""测试数据工厂 —— 构造最小 CharacterProfile / TimelineEvent。"""
from models import (
    CharacterProfile,
    CharacterRef,
    Confidence,
    EntityRef,
    EvidenceRef,
    EventType,
    TimelineEvent,
    TitlePeriod,
    TitleTier,
)


def ev(
    eid: str,
    etype: EventType,
    date=None,
    *,
    confidence: Confidence = Confidence.CONFIRMED,
    evidence_count: int = 1,
    rel: str | None = None,
    rel_resolved: bool = True,
    merged_count: int | None = None,
) -> TimelineEvent:
    related = (
        [CharacterRef(id=rel, name=rel, resolved=rel_resolved)] if rel else []
    )
    return TimelineEvent(
        id=eid,
        type=etype,
        title=etype.value,
        description=f"事件 {eid} 发生于 {date}。",
        date=date,
        relatedCharacters=related,
        confidence=confidence,
        evidence=[
            EvidenceRef(
                id=f"{eid}-ev{i}",
                sourceType="save_block",
                sourcePath=f"c/{eid}",
                rawKey=etype.value,
                description=f"证据 {i}",
                confidence=Confidence.CONFIRMED,
            )
            for i in range(evidence_count)
        ],
        mergedCount=merged_count,
    )


def make_profile(
    *,
    pid: str = "p1",
    name: str = "测试人物",
    timeline: list[TimelineEvent] | None = None,
    titles: list[TitlePeriod] | None = None,
    parents: list[CharacterRef] | None = None,
    children: list[CharacterRef] | None = None,
    siblings: list[CharacterRef] | None = None,
    friends: list[CharacterRef] | None = None,
    birthDate: str | None = "700.1.1",
    deathDate: str | None = "780.6.6",
) -> CharacterProfile:
    return CharacterProfile(
        id=pid,
        name=name,
        birthDate=birthDate,
        deathDate=deathDate,
        titles=titles or [],
        parents=parents or [],
        children=children or [],
        siblings=siblings or [],
        friends=friends or [],
        timeline=timeline or [],
    )


def title_period(title_id: str, name: str, tier: TitleTier, start: str) -> TitlePeriod:
    return TitlePeriod(titleId=title_id, name=name, tier=tier, start=start, isCurrent=True)
