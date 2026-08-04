"""CharacterExtractor 单测：reader stub → save-schema 契约映射（含本地化解析）。"""
from app.services.character_extractor import to_profile, to_summary
from app.services.localization import LocalizationLoader


def _stub():
    return {
        "id": "6432",
        "name": "Hua_83EF",
        "birth": "726.1.1",
        "death": None,
        "alive": True,
        "culture": "asian_han_chinese",
        "faith": "41",
        "dynasty": "9067",
        "evidence_warnings": ["faith", "dynasty", "primary_title"],
    }


def _loader_with_culture() -> LocalizationLoader:
    loader = LocalizationLoader()
    # 直接注入，模拟已加载的简中本地化
    loader._data["zh-Hans"] = {"asian_han_chinese": "汉文化"}
    loader._data["en"] = {"asian_han_chinese": "Han Chinese"}
    return loader


def test_to_summary_no_loader():
    s = to_summary(_stub())
    assert s.id == "6432"
    # M5：无 loader 时拼音hex 名（Hua_83EF）按 unicode 码点确定性解码为汉字（華）
    assert s.name == "華"
    assert s.culture.id == "asian_han_chinese"
    assert s.culture.resolved is False  # 无 loader，保留原键
    assert s.faith.id == "41"  # token-id，未解析
    assert s.faith.resolved is False
    assert s.dynasty.id == "9067"
    assert s.isAlive is True


def test_to_summary_with_loader_resolves_culture():
    s = to_summary(_stub(), _loader_with_culture())
    assert s.culture.name == "汉文化"
    assert s.culture.resolved is True
    # M5：名称键未在 loader 中 → 拼音hex 解码为汉字（華）；纯拉丁名才保留原键
    assert s.name == "華"
    # faith/dynasty 仍是 token-id，无法本地化
    assert s.faith.resolved is False
    assert s.dynasty.resolved is False


def test_to_summary_foreign_name_resolved_via_loader():
    """M5：外国人名经游戏本地化音译表解析（Maurizio→毛里齐奥），与游戏中文一致。"""
    loader = LocalizationLoader()
    loader._data["zh-Hans"] = {"Maurizio": "毛里齐奥"}
    s = to_summary({"id": "9", "name": "Maurizio", "alive": True}, loader)
    assert s.name == "毛里齐奥"


def test_to_summary_pinyin_hex_name_decoded():
    """M5：拼音hex 形态（Zhongrong_4EF2_5BB9）确定性解码为汉字（仲容）。"""
    loader = LocalizationLoader()
    s = to_summary({"id": "9", "name": "Zhongrong_4EF2_5BB9", "alive": True}, loader)
    assert s.name == "仲容"


def test_to_summary_dead():
    stub = _stub()
    stub["alive"] = False
    stub["death"] = "800.1.1"
    s = to_summary(stub)
    assert s.isAlive is False
    assert s.deathDate == "800.1.1"


def test_to_profile_partial():
    p = to_profile(_stub(), _loader_with_culture())
    assert p.id == "6432"
    assert p.culture.name == "汉文化"
    # 无法解析的字段保持为空，绝不伪造
    assert p.traits == []
    assert p.titles == []
    assert p.spouses == []
    # 最小可信内容（Phase 2A.1 十一）：至少包含可确认的出生事件，且带证据；
    # 未解析字段（faith/dynasty/primary_title）以 EvidenceWarning 标记，不伪造。
    assert len(p.timeline) == 1
    assert p.timeline[0].type.value == "birth"
    assert p.timeline[0].evidence
    assert any(w.code == "unresolved_faith" for w in p.evidenceWarnings)
    assert any(w.code == "unresolved_dynasty" for w in p.evidenceWarnings)
    assert any(w.code == "unresolved_primary_title" for w in p.evidenceWarnings)


# ---------------------------------------------------------------------------
# Phase 2B M1：亲子关系为推断、死亡取自 dead_data
# ---------------------------------------------------------------------------


def test_parents_from_child_backref_marked_inferred():
    """CK3 存档无 father/mother 字段，反推出的父母必须标注为推断。"""
    stub = _stub()
    stub["father"] = "1001"
    stub["mother"] = "1002"
    stub["parent_source"] = "child_backref"
    p = to_profile(stub)

    assert [x.id for x in p.parents] == ["1001", "1002"]
    # 来源路径显式带推断标记，供史料依据面板如实展示
    assert all("#inferred_from_child_backref" in x.sourcePath for x in p.parents)
    warning = next(w for w in p.evidenceWarnings if w.code == "inferred_parent")
    assert warning.severity.value == "info"
    assert "推断" in warning.message


def test_real_father_coexists_with_inferred_father():
    """real_father 是存档直述的生父，与反推出的父亲并存，互不覆盖。"""
    stub = _stub()
    stub["father"] = "1001"
    stub["real_father"] = "2002"
    stub["parent_source"] = "child_backref"
    p = to_profile(stub)

    by_id = {x.id: x.sourcePath for x in p.parents}
    assert "1001" in by_id and "2002" in by_id
    # 直述字段不带推断后缀
    assert by_id["2002"].endswith("family_data/real_father")
    assert "#inferred" not in by_id["2002"]
    assert "#inferred_from_child_backref" in by_id["1001"]


def test_no_parents_means_no_inferred_warning():
    p = to_profile(_stub())
    assert p.parents == []
    assert not any(w.code == "inferred_parent" for w in p.evidenceWarnings)


def test_death_event_from_dead_data_with_reason_and_killer():
    stub = _stub()
    stub.update(
        alive=False,
        death="762.3.4",
        death_reason="death_disappearance",
        killer="7777",
    )
    p = to_profile(stub)

    death = next(e for e in p.timeline if e.type.value == "death")
    assert death.date == "762.3.4"
    assert death.sourcePath == "character/6432/dead_data/date"
    # 死因键未本地化时如实展示原键，不编造中文死因
    assert "death_disappearance" in death.description
    assert "7777" in death.description
    keys = {ev.rawKey for ev in death.evidence}
    assert keys == {"dead_data.date", "dead_data.reason", "dead_data.killer"}


def test_dead_without_date_emits_warning_not_fake_date():
    stub = _stub()
    stub.update(alive=False, death=None)
    p = to_profile(stub)

    assert not any(e.type.value == "death" for e in p.timeline)
    assert any(w.code == "unresolved_death_date" for w in p.evidenceWarnings)
    assert p.deathDate is None


def test_numeric_id_warning_message_explains_no_index():
    """读取器新格式 `字段:numeric_id` 需产出解释性告警，且不伪造名称。"""
    stub = _stub()
    stub["evidence_warnings"] = ["faith:numeric_id", "traits:numeric_id"]
    p = to_profile(stub)

    w = next(x for x in p.evidenceWarnings if x.code == "unresolved_faith")
    assert "数字 id" in w.message
    assert "不伪造" in w.message
    assert any(x.code == "unresolved_traits" for x in p.evidenceWarnings)
