"""Phase 3C.4/3C.5 测试：CompressedProfile v3 结构化 + 确定性事实 + 章节 factIds。

验收要点：
  - COMPRESSION_VERSION == "3"（v1/v2 结构不再产出，store 侧按版本号标记 stale）；
  - identity/dynasticIdentity/territorialDomain/personalOffices/realmInstitutions/
    religiousOffices/honors/claims/historicalEvents/facts/narrativeConstraints 齐备；
  - 事实集非空且每条事件被至少一条事实锚定（event→fact 可追溯）；
  - 章节 factIds = 身份事实 + 本章事件锚定事实（与提示给模型的一致）；
  - 页面「史料摘要」与 LLM 输入同源（NarrativeSummaryBuilder）；
  - headline 用游戏原生名，无 tier 爵位词。
"""
from models import (
    CharacterIdentity,
    CharacterProfile,
    Confidence,
    EntityRef,
    EventType,
    HistoricalSemanticEvent,
    HistoricalSemanticEventType,
    RealmStatus,
    TitlePeriod,
    TitleTier,
)

from biography_engine.chapter_prompts import facts_for_chapter
from biography_engine.compressor import compress_profile
from biography_engine.models import COMPRESSION_VERSION, CompressedProfile
from biography_engine.narrative_summary import NarrativeSummaryBuilder

from factories import ev, make_profile


def _semantic_profile() -> CharacterProfile:
    """带 3C 语义字段的档案（身份 + 机构 + 历史语义事件 + 领土）。"""
    return CharacterProfile(
        id="p1",
        name="梁克贞",
        birthDate="908.2.14",
        timeline=[
            ev("b1", EventType.BIRTH, "908.2.14"),
            ev("t1", EventType.TITLE_GAIN, "952.8.16"),
        ],
        identity=CharacterIdentity(
            headlineIdentity="大理的最高统治者",
            realmStatus=RealmStatus.INDEPENDENT_RULER,
            primaryRealmTitle=EntityRef(id="k_dali", name="大理", type="title"),
            secondaryIdentities=["安南的最高统治者"],
            confidence=Confidence.CONFIRMED,
            evidence=[],
        ),
        titles=[
            TitlePeriod(titleId="k_dali", name="大理", tier=TitleTier.KINGDOM, start="952.8.16", isCurrent=True),
        ],
        majorTerritories=[EntityRef(id="k_dali", name="大理", type="title")],
        realmInstitutions=[EntityRef(id="e_minister_shizheng", name="政事堂", type="title")],
        historicalEvents=[
            HistoricalSemanticEvent(
                eventId="p1-identity_transition-952.8.16",
                semanticType=HistoricalSemanticEventType.IDENTITY_TRANSITION,
                date="952.8.16",
                summary="梁克贞 于 952.8.16 成为以下主权领地的最高统治者：大理、安南。",
                relatedTitleIds=["k_dali", "k_viet"],
                confidence=Confidence.CONFIRMED,
                evidence=[],
                acquisitionCause=None,
            ),
            HistoricalSemanticEvent(
                eventId="p1-territorial_gain-955.1.22",
                semanticType=HistoricalSemanticEventType.TERRITORIAL_GAIN,
                date="955.1.22",
                summary="梁克贞 于 955.1.22 获得以下领地：幽蓟。",
                relatedTitleIds=["k_youji"],
                confidence=Confidence.CONFIRMED,
                evidence=[],
                acquisitionCause=None,
                narrativeConstraints=["存档未记录该头衔获得的途径，不得推断为继承、征服、册封等具体原因。"],
            ),
        ],
    )


def test_compression_version_is_3():
    cp = compress_profile(_semantic_profile(), max_events=50, include_inferred=True, include_uncertain=True)
    assert cp.compressionVersion == COMPRESSION_VERSION == "3"


def test_v3_structured_sections_present():
    cp = compress_profile(_semantic_profile(), max_events=50, include_inferred=True, include_uncertain=True)
    assert cp.identity.headlineIdentity == "大理的最高统治者"
    assert cp.identity.realmStatus == "independent_ruler"
    assert cp.identity.primaryRealmTitle == "大理"
    assert cp.identity.secondaryIdentities == ["安南的最高统治者"]
    assert cp.territorialDomain.currentMajorTerritories == ["大理"]
    assert cp.realmInstitutions == ["政事堂"]
    assert len(cp.historicalEvents) == 2
    assert cp.narrativeConstraints == ["存档未记录该头衔获得的途径，不得推断为继承、征服、册封等具体原因。"]
    # headline 用游戏原生名，无爵位词。
    assert "国王" not in cp.identity.headlineIdentity
    assert "皇帝" not in cp.identity.headlineIdentity


def test_facts_non_empty_and_events_anchored():
    cp = compress_profile(_semantic_profile(), max_events=50, include_inferred=True, include_uncertain=True)
    assert len(cp.facts) > 0
    ids = [f.id for f in cp.facts]
    # 身份事实 + headline 事实 + 事件事实 + 领地事实 + 机构事实。
    assert any(f.id.startswith("f-identity-") for f in cp.facts)
    assert "f-headline" in ids
    # 每条 selectedEvent 都被至少一条事实锚定。
    fact_by_event = {}
    for f in cp.facts:
        for eid in f.sourceEventIds or []:
            fact_by_event.setdefault(eid, f.id)
    for e in cp.selectedEvents:
        assert e.eventId in fact_by_event, f"事件 {e.eventId} 未被事实锚定"
    # 身份事实的 sourceEventIds 指向出生/死亡事件。
    ident_fact = next(f for f in cp.facts if f.id == "f-identity-1")
    assert "b1" in (ident_fact.sourceEventIds or [])


def test_facts_for_chapter_identity_plus_event():
    cp = compress_profile(_semantic_profile(), max_events=50, include_inferred=True, include_uncertain=True)
    ch_facts = facts_for_chapter(cp, ["b1"])
    ids = [f.id for f in ch_facts]
    assert any(f.startswith("f-identity-") for f in ids)
    assert "f-headline" in ids
    assert "f-ev-b1" in ids
    assert "f-ev-t1" not in ids  # 不在本章事件集
    # 确定性：两次调用一致。
    assert facts_for_chapter(cp, ["b1"]) == ch_facts


def test_narrative_summary_uses_game_native_names():
    cp = compress_profile(_semantic_profile(), max_events=50, include_inferred=True, include_uncertain=True)
    builder = NarrativeSummaryBuilder()
    s = builder.sections(cp)
    assert any("大理" in x for x in s["oneLineLife"])
    assert any("独立最高统治者" in x for x in s["identity"])
    assert len(s["historicalEvents"]) == 2
    assert any("不得推断" in x for x in s["constraints"])
    block = builder.to_prompt_block(cp)
    assert "## 史料摘要（确定性，唯一事实来源）" in block
    assert "大理" in block


def test_narrative_summary_deterministic():
    cp = compress_profile(_semantic_profile(), max_events=50, include_inferred=True, include_uncertain=True)
    assert NarrativeSummaryBuilder().to_prompt_block(cp) == NarrativeSummaryBuilder().to_prompt_block(cp)


def test_bio_generator_backfills_fact_ids():
    """端到端：生成器产出的章节带 factIds，且事实集随 Biography 输出。"""
    from models import (
        BiographyChapterOutline,
        BiographyOutline,
        BiographyStyle,
    )
    from biography_engine.biography_generator import BiographyGenerator
    from biography_engine.providers.base import LlmProvider

    class EchoChapterProvider(LlmProvider):
        model = "echo"

        def health(self):
            return {"ok": True}

        def generate_json(self, **kwargs):
            return {
                "id": "c1",
                "title": "早年",
                "content": "他生于 908 年，据档案记载，早年并无大事。",
                "eventIds": ["b1"],
            }

    outline = BiographyOutline(
        profileId="p1",
        style=BiographyStyle.SERIOUS_BIOGRAPHY,
        chapters=[BiographyChapterOutline(id="c1", title="早年", summary="出生与早年。", eventIds=["b1"])],
    )
    result = BiographyGenerator(provider=EchoChapterProvider()).generate(
        _semantic_profile(),
        outline,
        max_events=50,
        include_inferred=True,
        include_uncertain=True,
    )
    assert result.biography is not None
    ch = result.biography.chapters[0]
    assert ch.factIds, "章节必须回填 factIds"
    assert all(fid in {f.id for f in result.biography.facts} for fid in ch.factIds)
    assert ch.claims, "章节必须回填 claims（事实文本）"
