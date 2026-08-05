"""
SHIGUAN —— 数据契约运行时校验测试。

这些测试确保：
  1. 非法 relationship type / war role / fact-check status / encoding / save kind 被拒。
  2. BiographyChapterOutline / BiographyChapter 的 eventIds 为空被拒。
  3. 合法 CharacterProfile / ParsedSave 可序列化往返。
  4. Mock 包裹层（FixtureEnvelope）与真实 CharacterProfile 分离。
  5. 最小 JSON fixture 能被 Python 读取并按契约校验。

运行：在 packages/save-schema/py/ 下执行
  python -m pytest tests/ -q
"""
import json
import os
import sys

# 让测试能 import 到同级的 models.py（不依赖 pytest 的 rootdir 注入）。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from pydantic import ValidationError

from models import (  # noqa: E402
    AcquisitionCause,
    Biography,
    BiographyChapter,
    BiographyChapterOutline,
    BiographyOutline,
    BiographyStyle,
    CharacterIdentity,
    CharacterIndexEntry,
    CharacterRef,
    CharacterProfile,
    CharacterSummary,
    Confidence,
    Encoding,
    EntityIndex,
    EntityIndexEntry,
    EntityKind,
    EntityKindIndex,
    EntityKeyKind,
    EntityNameSource,
    EntityRef,
    EvidenceRef,
    EvidenceWarning,
    EventType,
    FactCheckIssue,
    FactCheckResult,
    FactCheckStatus,
    FactRef,
    FixtureEnvelope,
    HistoricalSemanticEvent,
    HistoricalSemanticEventType,
    LifeEvent,
    MissingComponent,
    MockDataset,
    MockDatasetPayload,
    ParsedSave,
    ParsedSaveMeta,
    PositionPeriod,
    RealmStatus,
    RelationshipPeriod,
    RelationshipType,
    ResidencePeriod,
    SaveInspection,
    SaveKind,
    Sex,
    TitleClassification,
    TitlePeriod,
    TitleSemanticType,
    TitleTier,
    TitleStatus,
    TimelineEvent,
    TokenCompatibility,
    TokenSourceInfo,
    TokenSourceKind,
    TraitRecord,
    WarParticipation,
    WarRole,
    WarningSeverity,
)


# ---------------------------------------------------------------------------
# 辅助构造
# ---------------------------------------------------------------------------

def _minimal_profile(char_id: str = "p1", name: str = "Arnulf") -> CharacterProfile:
    return CharacterProfile(
        id=char_id,
        name=name,
        sex=Sex.MALE,
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
        timeline=[
            TimelineEvent(
                id="ev_birth",
                type=EventType.BIRTH,
                title="诞生",
                description="出生于某年",
                confidence=Confidence.CONFIRMED,
                evidence=[
                    EvidenceRef(
                        id="evr1",
                        sourceType="save_block",
                        sourcePath="character/123/birth",
                        rawKey="birth",
                        description="存档记录出生日期",
                        confidence=Confidence.CONFIRMED,
                    )
                ],
            )
        ],
        evidenceWarnings=[],
    )


# ---------------------------------------------------------------------------
# 1. 非法枚举值被拒（核心：不得退化为任意字符串）
# ---------------------------------------------------------------------------

def test_invalid_relationship_type_rejected():
    with pytest.raises(ValidationError):
        RelationshipPeriod(
            characterId="x", name="y", type="not_a_type", confidence=Confidence.CONFIRMED
        )


def test_valid_relationship_type_accepted():
    rp = RelationshipPeriod(
        characterId="x", name="y", type=RelationshipType.SPOUSE, confidence=Confidence.CONFIRMED
    )
    assert rp.type == RelationshipType.SPOUSE


def test_m4_relationship_type_values_and_is_former():
    """M4：betrothed/concubine 是合法枚举；isFormer 语义（前配偶/前妾室）可序列化往返。"""
    for kind in (RelationshipType.BETROTHED, RelationshipType.CONCUBINE, RelationshipType.OTHER):
        rp = RelationshipPeriod(
            characterId="x", name="y", type=kind, confidence=Confidence.CONFIRMED
        )
        assert rp.type == kind
    former = RelationshipPeriod(
        characterId="s",
        name="前夫",
        type=RelationshipType.SPOUSE,
        confidence=Confidence.CONFIRMED,
        isFormer=True,
    )
    data = former.model_dump()
    assert data["isFormer"] is True
    assert RelationshipPeriod(**data).isFormer is True


def test_invalid_war_role_rejected():
    with pytest.raises(ValidationError):
        WarParticipation(warId="w", name="war", role="general")


def test_valid_war_role_accepted():
    wp = WarParticipation(warId="w", name="war", role=WarRole.ATTACKER)
    assert wp.role == WarRole.ATTACKER


def test_invalid_factcheck_status_rejected():
    with pytest.raises(ValidationError):
        FactCheckResult(status="maybe_ok")


def test_valid_factcheck_status_accepted():
    fr = FactCheckResult(status=FactCheckStatus.PASS)
    assert fr.status == FactCheckStatus.PASS


def test_title_status_enum_values_and_roundtrip():
    """P0：TitleStatus 四个值可序列化往返，非法值被拒绝。"""
    for v in (
        TitleStatus.RESOLVED,
        TitleStatus.NO_TITLES,
        TitleStatus.TIER_UNKNOWN,
        TitleStatus.INDEX_UNAVAILABLE,
    ):
        data = CharacterSummary(id="c1", name="甲", isRuler=True, titleStatus=v)
        dumped = data.model_dump()
        assert dumped["titleStatus"] == v.value
        assert CharacterSummary(**dumped).titleStatus == v
    with pytest.raises(ValidationError):
        CharacterSummary(id="c1", name="甲", isRuler=False, titleStatus="holding_titles")


def test_invalid_encoding_rejected():
    with pytest.raises(ValidationError):
        SaveInspection(
            path="a.ck3",
            kind=SaveKind.TEXT,
            encoding="latin1",
            sizeBytes=1,
            isCompressed=False,
            isIronman=False,
            canParseLocally=True,
            needsExternal=False,
        )


def test_invalid_savekind_rejected():
    with pytest.raises(ValidationError):
        SaveInspection(
            path="a.ck3",
            kind="weird",
            encoding=Encoding.UTF8,
            sizeBytes=1,
            isCompressed=False,
            isIronman=False,
            canParseLocally=True,
            needsExternal=False,
        )


# ---------------------------------------------------------------------------
# 2. 空 eventIds 被拒
# ---------------------------------------------------------------------------

def test_empty_eventids_outline_rejected():
    with pytest.raises(ValidationError):
        BiographyChapterOutline(id="c1", title="t", eventIds=[], summary="s")


def test_empty_eventids_chapter_rejected():
    with pytest.raises(ValidationError):
        BiographyChapter(id="c1", title="t", content="x", eventIds=[])


def test_nonempty_eventids_accepted():
    o = BiographyChapterOutline(
        id="c1", title="t", eventIds=["ev_birth"], summary="s"
    )
    c = BiographyChapter(id="c1", title="t", content="x", eventIds=["ev_birth"])
    assert o.eventIds == ["ev_birth"]
    assert c.eventIds == ["ev_birth"]


# ---------------------------------------------------------------------------
# 3. 合法 CharacterProfile 序列化往返
# ---------------------------------------------------------------------------

def test_profile_roundtrip():
    p = _minimal_profile()
    dumped = p.model_dump(mode="json")
    p2 = CharacterProfile.model_validate(dumped)
    assert p2.id == p.id
    assert p2.timeline[0].id == "ev_birth"
    # evidence 集合在往返后保留
    assert p2.timeline[0].evidence[0].id == "evr1"


def test_timeline_event_merged_count_roundtrip():
    """M5：mergedCount（>1 = 多条重复存档记录合并）在序列化往返后保留；
    缺省/单条记录不强制填写（可选字段）。"""
    ev = TimelineEvent(
        id="ev_multi",
        type=EventType.CHILD_BIRTH,
        title="孩子出生",
        description="双记录合并",
        date="758.4.11",
        confidence=Confidence.CONFIRMED,
        evidence=[EvidenceRef(id="e1", sourceType="memory", description="d1", confidence=Confidence.CONFIRMED)],
        mergedCount=2,
    )
    dumped = ev.model_dump(mode="json")
    assert dumped["mergedCount"] == 2
    ev2 = TimelineEvent.model_validate(dumped)
    assert ev2.mergedCount == 2
    # 缺省为 None（可选字段，不强制）
    ev3 = TimelineEvent(
        id="ev_single",
        type=EventType.BIRTH,
        title="诞生",
        description="d",
        confidence=Confidence.CONFIRMED,
        evidence=[],
    )
    assert ev3.mergedCount is None


def test_character_ref_resolved_roundtrip():
    """M5.1：CharacterRef.resolved（姓名是否解析为可读名）在序列化往返后保留；
    缺省为 None（可选字段，向后兼容）。"""
    ref = CharacterRef(
        id="9536",
        name="毛里齐奥",
        sourcePath="character/1/spouse/9536",
        resolved=True,
    )
    dumped = ref.model_dump(mode="json")
    assert dumped["resolved"] is True
    ref2 = CharacterRef.model_validate(dumped)
    assert ref2.resolved is True

    unresolved = CharacterRef(id="9536", name="9536", resolved=False)
    assert unresolved.resolved is False

    legacy = CharacterRef(id="9536", name="9536")
    assert legacy.resolved is None


# ---------------------------------------------------------------------------
# 4. 合法 SaveInspection / ParsedSave 可生成 + 索引/档案分离
# ---------------------------------------------------------------------------

def test_save_inspection_valid():
    insp = SaveInspection(
        path="a.ck3",
        kind=SaveKind.TEXT,
        encoding=Encoding.UTF8,
        sizeBytes=123,
        isCompressed=False,
        isIronman=False,
        canParseLocally=True,
        needsExternal=False,
    )
    assert insp.kind == SaveKind.TEXT

    insp2 = SaveInspection(
        path="ironman.ck3",
        kind=SaveKind.IRONMAN,
        encoding=Encoding.UNKNOWN,
        sizeBytes=999,
        isCompressed=True,
        isIronman=True,
        canParseLocally=False,
        needsExternal=True,
        missingComponent=MissingComponent(
            name="rakaly", hint="cargo install rakaly"
        ),
    )
    assert insp2.missingComponent.name == "rakaly"


def test_parsed_save_index_and_profiles_separated():
    meta = ParsedSaveMeta(gameVersion="1.12")
    idx = CharacterSummary(
        id="p1",
        name="Arnulf",
        isRuler=True,
        isAlive=False,
        isPlayerDynasty=True,
        evidenceWarningCount=0,
    )
    prof = _minimal_profile()
    ps = ParsedSave(meta=meta, characterIndex=[idx], profiles={"p1": prof})
    assert len(ps.characterIndex) == 1
    assert ps.profiles["p1"].name == "Arnulf"

    dumped = ps.model_dump(mode="json")
    ps2 = ParsedSave.model_validate(dumped)
    assert ps2.profiles["p1"].name == "Arnulf"
    assert ps2.characterIndex[0].isRuler is True


# ---------------------------------------------------------------------------
# 5. Mock 包裹层与 CharacterProfile 分离
# ---------------------------------------------------------------------------

def test_mock_envelope_separates_metadata():
    prof = _minimal_profile()
    env = FixtureEnvelope[CharacterProfile](
        schemaVersion="0.5.0", generatedFor="contract-test", data=prof
    )
    assert env.isMock is True
    assert env.source == "fixtures/mock"
    # 真实 CharacterProfile 不携带 Mock 元数据字段
    assert "isMock" not in CharacterProfile.model_fields
    assert "source" not in CharacterProfile.model_fields

    dumped = env.model_dump(mode="json")
    env2 = FixtureEnvelope[CharacterProfile].model_validate(dumped)
    assert env2.data.id == "p1"


def test_mock_dataset_payload():
    idx = CharacterSummary(id="p1", name="Arnulf")
    payload = MockDatasetPayload(characterIndex=[idx])
    env = MockDataset(schemaVersion="0.5.0", generatedFor="test", data=payload)
    assert env.data.characterIndex[0].name == "Arnulf"


def test_is_mock_literal_enforced():
    # isMock 必须为 true，source 必须为 "fixtures/mock"
    with pytest.raises(ValidationError):
        FixtureEnvelope[CharacterProfile](
            isMock=False, source="fixtures/mock",
            schemaVersion="0.5.0", generatedFor="t",
            data=_minimal_profile(),
        )


# ---------------------------------------------------------------------------
# 6. 最小 JSON fixture 被 Python 读取验证
# ---------------------------------------------------------------------------

def test_json_fixture_loaded():
    fixture_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample_envelope.json"
    )
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    env = FixtureEnvelope[CharacterProfile].model_validate(data)
    assert env.isMock is True
    assert env.data.id == "char_test_1"
    assert env.data.timeline[0].evidence[0].sourceType == "save_block"


# ---------------------------------------------------------------------------
# 7. 同步一致性：CharacterIndexEntry 与 CharacterSummary 同形
# ---------------------------------------------------------------------------

def test_index_entry_alias():
    assert CharacterIndexEntry is CharacterSummary


# ---------------------------------------------------------------------------
# 8. 实体索引契约（M2）：EntityKind / EntityIndexEntry / EntityKindIndex / EntityIndex
# ---------------------------------------------------------------------------

def test_entity_kind_has_ten_members():
    # 与 TS union EntityKind 严格对齐（10 类）。
    assert {k.value for k in EntityKind} == {
        "trait", "faith", "religion", "culture", "house", "dynasty",
        "title", "war", "memoryType", "courtPositionType",
    }


def test_entity_index_entry_resolved_true_when_key_present():
    e = EntityIndexEntry(
        id="house_antioch", key="dynn_antioch",
        keyKind=EntityKeyKind.LOC, name="安条克家族",
        nameSource=EntityNameSource.LOC, resolved=True,
    )
    dumped = e.model_dump(mode="json")
    e2 = EntityIndexEntry.model_validate(dumped)
    assert e2.resolved is True
    assert e2.keyKind == EntityKeyKind.LOC


def test_entity_index_entry_resolved_false_when_unnameable():
    # 既无 key 也无 saveName：不得伪造名字，name 退化为原始 id。
    e = EntityIndexEntry(
        id="house_ghost", name="house_ghost",
        nameSource=EntityNameSource.UNRESOLVED, resolved=False,
    )
    dumped = e.model_dump(mode="json")
    e2 = EntityIndexEntry.model_validate(dumped)
    assert e2.resolved is False
    assert e2.name == "house_ghost"
    assert e2.key is None
    assert e2.saveName is None


def test_entity_index_roundtrip():
    faith = EntityKindIndex(
        kind=EntityKind.FAITH,
        source="save:religion.faiths",
        containerFound=True,
        count=2,
        unresolvedCount=0,
        entries={
            "0": EntityIndexEntry(
                id="0", key="orthodox", name="东正教",
                nameSource=EntityNameSource.LOC, resolved=True,
            ),
        },
    )
    idx = EntityIndex(
        schemaVersion=1,
        readerVersion="0.1.0",
        scanMs=12.3,
        kinds={EntityKind.FAITH: faith},
        warnings=[],
    )
    dumped = idx.model_dump(mode="json")
    idx2 = EntityIndex.model_validate(dumped)
    assert idx2.kinds[EntityKind.FAITH].count == 2
    assert idx2.kinds[EntityKind.FAITH].entries["0"].name == "东正教"
    # kind 反序列化为枚举
    assert idx2.kinds[EntityKind.FAITH].kind == EntityKind.FAITH


# ---------------------------------------------------------------------------
# 9. Token 来源自报契约（M2.2）
# ---------------------------------------------------------------------------

def test_token_source_kind_four_states():
    assert {k.value for k in TokenSourceKind} == {
        "placeholder", "builtin_validated", "user_local", "literal_key",
    }
    assert {c.value for c in TokenCompatibility} == {
        "ok", "partial", "incompatible", "external_missing",
    }


def test_token_source_info_roundtrip():
    info = TokenSourceInfo(
        kind=TokenSourceKind.PLACEHOLDER,
        tokenCount=65536,
        compatibility=TokenCompatibility.PARTIAL,
        enumResolved=False,
        warnings=["placeholder token 表：enum 字段保持为数字 id"],
    )
    dumped = info.model_dump(mode="json")
    info2 = TokenSourceInfo.model_validate(dumped)
    assert info2.kind == TokenSourceKind.PLACEHOLDER
    assert info2.enumResolved is False
    assert info2.compatibility == TokenCompatibility.PARTIAL


# ---------------------------------------------------------------------------
# Phase 3C：历史语义层契约（头衔语义 / 身份 / 历史语义事件 / 事实引用）
# ---------------------------------------------------------------------------

def test_title_semantic_type_enum_values():
    values = [t.value for t in TitleSemanticType]
    assert values == [
        "sovereign_realm_title",
        "territorial_realm_title",
        "subordinate_territory",
        "personal_office",
        "realm_institution",
        "religious_office",
        "dynasty_identity",
        "honorary_title",
        "temporary_title",
        "claim_only",
        "special_mod_title",
        "unknown",
    ]


def test_realm_status_enum_values():
    values = [s.value for s in RealmStatus]
    assert "independent_ruler" in values
    assert "vassal_ruler" in values
    assert "landless_official" in values
    assert "former_ruler" in values
    assert "unknown" in values
    assert len(values) == 10


def test_historical_semantic_event_type_enum_values():
    values = [e.value for e in HistoricalSemanticEventType]
    assert len(values) == 14
    assert "territorial_gain" in values
    assert "office_appointment" in values
    assert "institution_transition" in values
    assert "identity_transition" in values


def test_acquisition_cause_enum_values():
    values = [c.value for c in AcquisitionCause]
    assert "creation" in values
    assert "unknown" in values
    assert len(values) == 11


def test_title_classification_roundtrip():
    tc = TitleClassification(
        titleId="h_china",
        semanticType=TitleSemanticType.SOVEREIGN_REALM_TITLE,
        confidence=Confidence.CONFIRMED,
        displayName="唐",
        tier=TitleTier.EMPIRE,
        isHegemony=True,
        signals=["key_prefix", "de_facto_liege"],
        sourceRule="base-game.yml:vanilla_super_empire",
    )
    dumped = tc.model_dump(mode="json")
    tc2 = TitleClassification.model_validate(dumped)
    assert tc2.semanticType == TitleSemanticType.SOVEREIGN_REALM_TITLE
    assert tc2.displayName == "唐"
    assert tc2.sourceRule == "base-game.yml:vanilla_super_empire"
    assert tc2.isHegemony is True


def test_title_classification_hegemony_default_false():
    tc = TitleClassification(
        titleId="k_dali",
        semanticType=TitleSemanticType.SOVEREIGN_REALM_TITLE,
        confidence=Confidence.CONFIRMED,
        displayName="大理",
    )
    assert tc.isHegemony is False
    assert "isHegemony" in tc.model_dump(mode="json")


def test_character_identity_roundtrip():
    ident = CharacterIdentity(
        headlineIdentity="唐的最高统治者",
        realmStatus=RealmStatus.INDEPENDENT_RULER,
        primaryRealmTitle=EntityRef(id="h_china", name="唐", type="title"),
        isHegemony=True,
        secondaryIdentities=["罗马帝国的最高统治者"],
        confidence=Confidence.CONFIRMED,
        evidence=[
            EvidenceRef(
                id="ev1",
                sourceType="title",
                description="landed_titles 顶层 holder",
                confidence=Confidence.CONFIRMED,
            )
        ],
    )
    dumped = ident.model_dump(mode="json")
    ident2 = CharacterIdentity.model_validate(dumped)
    assert ident2.realmStatus == RealmStatus.INDEPENDENT_RULER
    assert ident2.primaryRealmTitle.name == "唐"
    assert ident2.headlineIdentity == "唐的最高统治者"
    assert ident2.isHegemony is True


def test_historical_semantic_event_roundtrip():
    ev = HistoricalSemanticEvent(
        eventId="p1-1-title-gain-952.8.16",
        semanticType=HistoricalSemanticEventType.TERRITORIAL_GAIN,
        date="952.8.16",
        summary="梁某 于 952.8.16 获得以下领地：大理、安南。",
        relatedTitleIds=["k_dali", "k_viet"],
        confidence=Confidence.CONFIRMED,
        sourceEventIds=["p1-title-gain-952.8.16"],
        narrativeConstraints=["存档未记录获得途径，不得推断继承/征服/册封。"],
        acquisitionCause=AcquisitionCause.UNKNOWN,
    )
    dumped = ev.model_dump(mode="json")
    ev2 = HistoricalSemanticEvent.model_validate(dumped)
    assert ev2.semanticType == HistoricalSemanticEventType.TERRITORIAL_GAIN
    assert ev2.acquisitionCause == AcquisitionCause.UNKNOWN
    assert ev2.date == "952.8.16"


def test_fact_ref_roundtrip():
    fact = FactRef(
        id="f1",
        text="梁某 于 952.8.16 成为「大理」的持有者。",
        confidence=Confidence.CONFIRMED,
        evidenceRefIds=["p1-k_dali-952.8.16-ev"],
        sourceEventIds=["p1-title-gain-952.8.16"],
    )
    dumped = fact.model_dump(mode="json")
    fact2 = FactRef.model_validate(dumped)
    assert fact2.id == "f1"
    assert fact2.confidence == Confidence.CONFIRMED


def test_profile_3c_fields_roundtrip():
    p = _minimal_profile("p1", "梁克贞")
    p.titleClassifications = {
        "k_dali": TitleClassification(
            titleId="k_dali",
            semanticType=TitleSemanticType.SOVEREIGN_REALM_TITLE,
            confidence=Confidence.CONFIRMED,
            displayName="大理",
        )
    }
    p.identity = CharacterIdentity(
        headlineIdentity="大理的最高统治者",
        realmStatus=RealmStatus.INDEPENDENT_RULER,
        primaryRealmTitle=EntityRef(id="k_dali", name="大理", type="title"),
        confidence=Confidence.CONFIRMED,
        evidence=[],
    )
    p.personalOffices = [EntityRef(id="e_minister_li", name="吏部尚书", type="title")]
    p.realmInstitutions = [EntityRef(id="e_minister_shizheng", name="政事堂", type="title")]
    p.majorTerritories = [EntityRef(id="k_dali", name="大理", type="title")]
    dumped = p.model_dump(mode="json")
    p2 = CharacterProfile.model_validate(dumped)
    assert p2.identity.realmStatus == RealmStatus.INDEPENDENT_RULER
    assert p2.titleClassifications["k_dali"].displayName == "大理"
    assert p2.realmInstitutions[0].name == "政事堂"
    assert p2.personalOffices[0].id == "e_minister_li"


def test_chapter_fact_ids_and_biography_facts():
    ch = BiographyChapter(id="c1", title="早年", content="生于大理。", eventIds=["p1-birth"])
    ch.factIds = ["f1"]
    ch.claims = ["梁克贞出生于大理。"]
    bio = Biography(
        profileId="p1",
        style=BiographyStyle.SERIOUS_BIOGRAPHY,
        chapters=[ch],
        generatedAt="2026-01-01T00:00:00Z",
        modelName="fake",
        facts=[
            FactRef(
                id="f1",
                text="梁克贞出生于大理。",
                confidence=Confidence.CONFIRMED,
            )
        ],
    )
    dumped = bio.model_dump(mode="json")
    bio2 = Biography.model_validate(dumped)
    assert bio2.chapters[0].factIds == ["f1"]
    assert bio2.facts[0].id == "f1"
