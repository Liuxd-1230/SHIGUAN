"""Phase 3C.7 TitleHistoryActionNormalizer 测试。

覆盖存档实测的全部 18 类显式 history type，以及「同一 raw type 在不同语义类型下
文案必须不同」「appointment_succession ≠ 世袭继承」「realm_institution ≠ 个人任职」
等交接文档要求。
"""
from biography_engine.title_history_actions import (
    TitleHistoryActionNormalizer,
)
from models import (
    AcquisitionCause,
    AcquisitionTypeSource,
    Confidence,
    TitleHistoryActionKind,
    TitleSemanticType,
)

NORM = TitleHistoryActionNormalizer()


def _history(raw_type, date="953.11.18"):
    return [
        {
            "date": date,
            "holder_id": "p1",
            "kind": "other" if raw_type else "holder",
            **({"raw_type": raw_type} if raw_type else {}),
        }
    ]


def _entry(key, raw_type, date="953.11.18"):
    return {"key": key, "name": key, "name_source": "key", "tier": "county",
            "holder_id": "p1", "history": _history(raw_type, date)}


# ---------------------------------------------------------------------------
# 18 类显式 type 全覆盖
# ---------------------------------------------------------------------------

def test_all_18_real_types_map_with_raw_preserved():
    """存档实测的 18 类显式 type 全部有明确处理策略且 raw_type 原样保留。"""
    cases = {
        "created": (TitleHistoryActionKind.CREATED, AcquisitionCause.CREATION, Confidence.CONFIRMED),
        "destroyed": (TitleHistoryActionKind.DESTROYED, None, Confidence.CONFIRMED),
        "granted": (TitleHistoryActionKind.GRANTED, AcquisitionCause.GRANT, Confidence.CONFIRMED),
        "conquest": (TitleHistoryActionKind.CONQUERED, AcquisitionCause.CONQUEST, Confidence.CONFIRMED),
        "conquest_claim": (TitleHistoryActionKind.CONQUERED, AcquisitionCause.CONQUEST, Confidence.CONFIRMED),
        "conquest_populist": (TitleHistoryActionKind.CONQUERED, AcquisitionCause.CONQUEST, Confidence.CONFIRMED),
        "conquest_holy_war": (TitleHistoryActionKind.CONQUERED, AcquisitionCause.CONQUEST, Confidence.CONFIRMED),
        "appointment": (TitleHistoryActionKind.APPOINTED, AcquisitionCause.APPOINTMENT, Confidence.CONFIRMED),
        "appointment_succession": (TitleHistoryActionKind.ADMINISTRATIVE_SUCCESSION, AcquisitionCause.ADMINISTRATIVE_TRANSFER, Confidence.CONFIRMED),
        "migration": (TitleHistoryActionKind.MIGRATED, None, Confidence.INFERRED),
        "revoked": (TitleHistoryActionKind.REVOKED, None, Confidence.CONFIRMED),
        "stepped_down": (TitleHistoryActionKind.STEPPED_DOWN, None, Confidence.CONFIRMED),
        "abdication": (TitleHistoryActionKind.ABDICATED, None, Confidence.CONFIRMED),
        "faction_demand": (TitleHistoryActionKind.FACTION_INSTALLED, AcquisitionCause.FACTION, Confidence.CONFIRMED),
        "swear_fealty": (TitleHistoryActionKind.SWORE_FEALTY, None, Confidence.CONFIRMED),
        "independency": (TitleHistoryActionKind.BECAME_INDEPENDENT, None, Confidence.CONFIRMED),
        "leased_out": (TitleHistoryActionKind.LEASED_OUT, None, Confidence.CONFIRMED),
        "returned": (TitleHistoryActionKind.RETURNED, None, Confidence.CONFIRMED),
    }
    for raw, (action, cause, conf) in cases.items():
        direction = "loss" if raw in ("destroyed", "revoked", "stepped_down", "abdication", "leased_out") else "gain"
        a = NORM.normalize(
            entry=_entry("c_x", raw),
            date="953.11.18",
            direction=direction,
            semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE,
            title_id="c_x",
        )
        assert a.rawType == raw, f"{raw}: rawType={a.rawType}"
        assert a.normalizedAction == action, f"{raw}: action={a.normalizedAction}"
        assert a.acquisitionCause == cause, f"{raw}: cause={a.acquisitionCause}"
        assert a.confidence == conf, f"{raw}: confidence={a.confidence}"
        assert a.typeSource == AcquisitionTypeSource.SAVE_EXPLICIT, f"{raw}: source={a.typeSource}"
        # 已知动作不套「不得推断因果」；未知才套。
        assert not a.narrativeConstraints, f"{raw}: constraints={a.narrativeConstraints}"


def test_conquest_subtypes_preserved():
    a = NORM.normalize(
        entry=_entry("c_x", "conquest_claim"),
        date="953.11.18", direction="gain",
        semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="c_x",
    )
    assert a.subtype == "claim"
    a2 = NORM.normalize(
        entry=_entry("c_x", "conquest_populist"),
        date="953.11.18", direction="gain",
        semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="c_x",
    )
    assert a2.subtype == "populist"
    a3 = NORM.normalize(
        entry=_entry("c_x", "conquest_holy_war"),
        date="953.11.18", direction="gain",
        semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="c_x",
    )
    assert a3.subtype == "holy_war"
    a4 = NORM.normalize(
        entry=_entry("c_x", "conquest"),
        date="953.11.18", direction="gain",
        semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="c_x",
    )
    assert a4.subtype == "generic"


def test_unknown_raw_type_keeps_raw_with_warning():
    a = NORM.normalize(
        entry=_entry("c_x", "some_unknown_type"),
        date="953.11.18", direction="gain",
        semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="c_x",
    )
    assert a.normalizedAction == TitleHistoryActionKind.UNKNOWN
    assert a.rawType == "some_unknown_type"
    assert a.confidence == Confidence.INFERRED
    assert a.typeSource == AcquisitionTypeSource.SAVE_EXPLICIT
    assert a.warnings
    assert any("不得推断" in c for c in a.narrativeConstraints)
    # 不同未映射 raw type 的分组键不同（不互相合并）。
    assert a.rawTypeGroup == "unknown:some_unknown_type"


def test_no_raw_type_unknown_uncertain():
    a = NORM.normalize(
        entry=_entry("c_x", None),
        date="953.11.18", direction="gain",
        semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="c_x",
    )
    assert a.normalizedAction == TitleHistoryActionKind.UNKNOWN
    assert a.rawType is None
    assert a.confidence == Confidence.UNCERTAIN
    assert a.typeSource == AcquisitionTypeSource.UNKNOWN
    assert a.rawTypeGroup == "none"
    assert any("不得推断" in c for c in a.narrativeConstraints)


def test_legacy_kind_created_reader_default():
    a = NORM.normalize(
        entry={"key": "c_x", "history": [{"date": "953.11.18", "holder_id": "p1", "kind": "created"}]},
        date="953.11.18", direction="gain",
        semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="c_x",
    )
    assert a.normalizedAction == TitleHistoryActionKind.CREATED
    assert a.rawType == "created"
    assert a.typeSource == AcquisitionTypeSource.READER_DEFAULT


def test_legacy_kind_destroyed_gain_is_not_cause():
    a = NORM.normalize(
        entry={"key": "c_x", "history": [{"date": "953.11.18", "holder_id": None, "kind": "destroyed"}]},
        date="953.11.18", direction="gain",
        semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="c_x",
    )
    assert a.normalizedAction == TitleHistoryActionKind.UNKNOWN
    assert a.acquisitionCause is None
    assert a.confidence == Confidence.UNCERTAIN


def test_missing_entry_unknown():
    a = NORM.normalize(
        entry=None, date="953.11.18", direction="gain",
        semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="c_x",
    )
    assert a.normalizedAction == TitleHistoryActionKind.UNKNOWN
    assert a.confidence == Confidence.UNCERTAIN
    assert any("不得推断" in c for c in a.narrativeConstraints)


# ---------------------------------------------------------------------------
# 同一 raw type × 不同语义类型 → 文案必须不同
# ---------------------------------------------------------------------------

def test_appointment_wording_differs_by_semantic_type():
    kw = dict(entry=_entry("x", "appointment"), date="953.11.18", direction="gain")
    office = NORM.normalize(**kw, semantic_type=TitleSemanticType.PERSONAL_OFFICE, title_id="e_o")
    realm = NORM.normalize(**kw, semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="k_r")
    inst = NORM.normalize(**kw, semantic_type=TitleSemanticType.REALM_INSTITUTION, title_id="e_i")
    assert "就任" in office.summaryVerb
    assert "统治权" in realm.summaryVerb or "任命" in realm.summaryVerb
    assert "归入其统治体系" in inst.summaryVerb
    # 机构事件固定约束（不表示个人任职）。
    assert any("不代表人物本人在该机构任职" in c for c in inst.narrativeConstraints)
    # appointment 作为个人官职不是领土获得原因。
    assert office.acquisitionCause is None
    assert realm.acquisitionCause == AcquisitionCause.APPOINTMENT


def test_revoked_wording_differs_by_semantic_type():
    kw = dict(entry=_entry("x", "revoked"), date="953.11.18", direction="loss")
    office = NORM.normalize(**kw, semantic_type=TitleSemanticType.PERSONAL_OFFICE, title_id="e_o")
    realm = NORM.normalize(**kw, semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="k_r")
    inst = NORM.normalize(**kw, semantic_type=TitleSemanticType.REALM_INSTITUTION, title_id="e_i")
    assert "免去" in office.summaryVerb
    assert "收回" in realm.summaryVerb
    assert "不再属于其统治体系" in inst.summaryVerb


def test_institution_gain_and_loss_wording():
    gain = NORM.normalize(
        entry=_entry("e_ss", "appointment"), date="953.11.18", direction="gain",
        semantic_type=TitleSemanticType.REALM_INSTITUTION, title_id="e_ss",
    )
    loss = NORM.normalize(
        entry=_entry("e_ss", "revoked"), date="953.11.18", direction="loss",
        semantic_type=TitleSemanticType.REALM_INSTITUTION, title_id="e_ss",
    )
    assert gain.summaryVerb == "以下机构归入其统治体系"
    assert loss.summaryVerb == "以下机构不再属于其统治体系"
    assert all("不代表人物本人在该机构任职" in c for c in gain.narrativeConstraints + loss.narrativeConstraints)


def test_institution_unknown_uses_uncertain_wording():
    a = NORM.normalize(
        entry=_entry("e_ss", None), date="953.11.18", direction="gain",
        semantic_type=TitleSemanticType.REALM_INSTITUTION, title_id="e_ss",
    )
    assert a.summaryVerb == "以下政权机构的归属发生变化"
    assert any("不代表人物本人在该机构任职" in c for c in a.narrativeConstraints)


def test_appointment_succession_is_not_hereditary():
    a = NORM.normalize(
        entry=_entry("k_x", "appointment_succession", date="955.1.22"), date="955.1.22", direction="gain",
        semantic_type=TitleSemanticType.SOVEREIGN_REALM_TITLE, title_id="k_x",
    )
    assert a.normalizedAction == TitleHistoryActionKind.ADMINISTRATIVE_SUCCESSION
    assert "继承" not in a.summaryVerb
    assert "任命" in a.summaryVerb or "继任" in a.summaryVerb


def test_stepped_down_wording_is_neutral():
    a = NORM.normalize(
        entry=_entry("e_o", "stepped_down"), date="953.11.18", direction="loss",
        semantic_type=TitleSemanticType.PERSONAL_OFFICE, title_id="e_o",
    )
    assert "结束" in a.summaryVerb  # 非「主动卸任」（需另有证据）


def test_swear_fealty_and_independency_are_realm_status_not_land_gain():
    fealty = NORM.normalize(
        entry=_entry("k_x", "swear_fealty"), date="953.11.18", direction="gain",
        semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="k_x",
    )
    assert "效忠" in fealty.summaryVerb
    indep = NORM.normalize(
        entry=_entry("k_x", "independency"), date="953.11.18", direction="gain",
        semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="k_x",
    )
    assert "独立" in indep.summaryVerb


def test_leased_out_is_not_permanent_grant():
    a = NORM.normalize(
        entry=_entry("c_x", "leased_out"), date="953.11.18", direction="loss",
        semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="c_x",
    )
    assert a.normalizedAction == TitleHistoryActionKind.LEASED_OUT
    assert "租借" in a.summaryVerb
    assert "授封" not in a.summaryVerb


def test_unknown_conquest_never_names_war_or_opponent():
    for raw in ("conquest", "conquest_claim", "conquest_populist", "conquest_holy_war"):
        a = NORM.normalize(
            entry=_entry("c_x", raw), date="953.11.18", direction="gain",
            semantic_type=TitleSemanticType.TERRITORIAL_REALM_TITLE, title_id="c_x",
        )
        assert "战争名" not in a.summaryVerb
        assert "对手" not in a.summaryVerb
        assert a.normalizedAction == TitleHistoryActionKind.CONQUERED
