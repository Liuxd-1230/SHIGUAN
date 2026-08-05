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


# ---------------------------------------------------------------------------
# P0：主头衔判定状态（与 titles 列表同源，前端区分无头衔/未能确定/索引不可用）
# ---------------------------------------------------------------------------


def _bits(**kw):
    from app.services.title_reign_extractor import TitleSummaryBits

    return TitleSummaryBits(**kw)


def test_to_summary_title_status_resolved():
    from models import EntityRef, TitleTier

    bits = _bits(
        primary=EntityRef(id="k_dali", name="大理", type="title", resolved=True),
        highestTier=TitleTier.KINGDOM,
        isRuler=True,
    )
    s = to_summary(_stub(), title_bits=bits)
    assert s.titleStatus.value == "resolved"
    assert s.primaryTitle.name == "大理"
    assert s.highestTitleTier == TitleTier.KINGDOM
    assert s.isRuler is True


def test_to_summary_title_status_no_titles():
    s = to_summary(_stub(), title_bits=_bits())
    assert s.titleStatus.value == "no_titles"
    assert s.primaryTitle is None
    assert s.isRuler is False


def test_to_summary_title_status_tier_unknown():
    """持有当前头衔但等级全部未知 → 不强行主头衔，标注 tier_unknown（而非无头衔）。"""
    s = to_summary(_stub(), title_bits=_bits(isRuler=True))
    assert s.titleStatus.value == "tier_unknown"
    assert s.primaryTitle is None
    assert s.isRuler is True


def test_to_summary_title_status_index_unavailable():
    """头衔索引不可用（title_bits=None）→ index_unavailable，而非误显示无头衔。"""
    s = to_summary(_stub(), title_bits=None)
    assert s.titleStatus.value == "index_unavailable"


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


# ---------------------------------------------------------------------------
# M5.1：CharacterRef.resolved —— 父母/子女/兄弟姐妹按 by_id+loader 解析并标注
# ---------------------------------------------------------------------------


def _loader_with_names() -> LocalizationLoader:
    loader = LocalizationLoader()
    loader._data["zh-Hans"] = {
        "Hua_83EF": "华",
        "max_chinese_male_name_1001": "赵大",
        "max_chinese_male_name_1002": "钱二",
        "Maurizio": "毛里齐奥",
    }
    return loader


def test_parents_children_resolved_via_by_id_and_loader():
    """M5.1：父母/子女名字经 by_id 人物索引 + loader 解析，resolved=True。"""
    stub = _stub()
    stub["father"] = "1001"
    stub["mother"] = "1002"
    stub["children"] = ["1003"]
    stub["parent_source"] = "child_backref"
    by_id = {
        "1001": {"id": "1001", "name": "max_chinese_male_name_1001"},
        "1002": {"id": "1002", "name": "max_chinese_male_name_1002"},
        "1003": {"id": "1003", "name": "Maurizio"},
    }
    p = to_profile(stub, _loader_with_names(), by_id=by_id)

    by_ref = {r.id: r for r in p.parents}
    assert by_ref["1001"].name == "赵大"
    assert by_ref["1001"].resolved is True
    assert by_ref["1002"].name == "钱二"
    assert by_ref["1002"].resolved is True

    child = p.children[0]
    assert child.id == "1003"
    assert child.name == "毛里齐奥"
    assert child.resolved is True


def test_unresolved_character_ref_keeps_id_resolved_false():
    """M5.1：人物不在索引中 → name=原始 id、resolved=False（不编造占位姓名）。"""
    stub = _stub()
    stub["father"] = "9999"
    stub["parent_source"] = "child_backref"
    p = to_profile(stub, by_id={})
    assert p.parents[0].name == "9999"
    assert p.parents[0].resolved is False


def test_sibling_refs_resolved():
    """M5.1：兄弟姐妹名字同样经 by_id+loader 解析并标注 resolved。"""
    stub = _stub()
    stub["father"] = "1001"
    stub["mother"] = "1002"
    by_id = {
        "1001": {"id": "1001", "name": "max_chinese_male_name_1001"},
        "1002": {"id": "1002", "name": "max_chinese_male_name_1002"},
        "6432": {"id": "6432", "name": "Hua_83EF", "father": "1001", "mother": "1002"},
        "2001": {"id": "2001", "name": "Hua_83EF", "father": "1001", "mother": "1002"},
    }
    p = to_profile(stub, _loader_with_names(), by_id=by_id)
    sib = next(r for r in p.siblings if r.id == "2001")
    assert sib.name == "华"  # Hua_83EF → 華（hex 解码，_loader_with_names 也含）
    assert sib.resolved is True


def test_parents_deduplicated_by_id():
    """M5.1：父母列表按 id 去重（father 与 real_father 同 id 不重复出现）。"""
    stub = _stub()
    stub["father"] = "1001"
    stub["real_father"] = "1001"
    stub["parent_source"] = "child_backref"
    p = to_profile(stub, by_id={})
    assert [r.id for r in p.parents] == ["1001"]


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




# ---------------------------------------------------------------------------
# 2C.2：姓（house/dynasty）解析后拼接到人物引用名
# ---------------------------------------------------------------------------


def _resolver_with_house(house_name: str = "梁"):
    """构建实体索引：house 11527 → dynn_liang205 → 本地化 house_name。

    stub.dynasty 实为 dynasty_house 数字 id；_dynasty_entity 先按 house 解析。
    """
    from models import EntityKind
    from app.services.entity_index_builder import EntityIndexBuilder, ReferenceResolver
    from app.services.game_def_loader import GameDefLoader

    loc = LocalizationLoader()
    loc._ingest_text(f"l_simp_chinese:\n dynn_liang205: \"{house_name}\"\n")
    g = GameDefLoader(None)
    g._maps = {"house": {"11527": "dynn_liang205"}}
    raw = {
        "schema_version": 1,
        "reader_version": "0.1.0",
        "scan_ms": 1.0,
        "warnings": [],
        "kinds": {
            "house": {
                "source": "save:dynasties.dynasty_house",
                "container_found": True,
                "count": 1,
                "unresolved_key_count": 0,
                "entries": {"11527": {"key": "11527", "key_kind": "def"}},
            },
            "dynasty": {"source": "x", "container_found": True, "count": 0,
                         "unresolved_key_count": 0, "entries": {}},
        },
    }
    idx = EntityIndexBuilder(game_def=g, loc=loc).build(raw)
    assert idx.kinds[EntityKind.HOUSE].entries.get("11527") is not None
    return ReferenceResolver(idx)


def test_spouse_name_includes_resolved_surname():
    """2C.2：配偶姓（house）解析成功且与名不同 → 「梁章」式拼接。"""
    stub = _stub()
    stub["spouses"] = ["43381"]
    by_id = {
        "43381": {"id": "43381", "name": "Hua_83EF", "dynasty": "11527"},
    }
    p = to_profile(stub, _loader_with_names(), by_id=by_id, resolver=_resolver_with_house())
    sp = p.spouses[0]
    assert sp.name == "梁华"
    assert sp.characterId == "43381"


def test_child_ref_gets_surname_and_dynasty_field():
    """2C.2：子女引用拼接姓，并把解析后的 dynasty EntityRef 落位。"""
    stub = _stub()
    stub["children"] = ["44864"]
    by_id = {
        "44864": {"id": "44864", "name": "Hua_83EF", "dynasty": "11527"},
    }
    p = to_profile(stub, _loader_with_names(), by_id=by_id, resolver=_resolver_with_house())
    child = p.children[0]
    assert child.name == "梁华"
    assert child.dynasty is not None
    assert child.dynasty.name == "梁"
    assert child.dynasty.resolved is True
    assert child.resolved is True


def test_ref_without_dynasty_keeps_given_name():
    """2C.2：存档里配偶确无 dynasty（如真实存档 43381 章庄）→ 不拼接也不伪造。"""
    stub = _stub()
    stub["spouses"] = ["43381"]
    by_id = {
        "43381": {"id": "43381", "name": "Hua_83EF"},
    }
    p = to_profile(stub, _loader_with_names(), by_id=by_id, resolver=_resolver_with_house())
    assert p.spouses[0].name == "华"


def test_surname_not_appended_when_given_name_unresolved():
    """2C.2：名本身未解析（resolved=False）→ 不拼姓，避免「梁20423」半截姓名。"""
    stub = _stub()
    stub["children"] = ["44864"]
    by_id = {
        "44864": {"id": "44864", "dynasty": "11527"},  # 无 name 键 → unresolved
    }
    p = to_profile(stub, _loader_with_names(), by_id=by_id, resolver=_resolver_with_house())
    child = p.children[0]
    assert child.name == "44864"
    assert child.resolved is False


def test_surname_not_appended_when_same_as_given_name():
    """2C.2：姓与名相同（以本人命名的王朝）→ 不重复拼接。"""
    stub = _stub()
    stub["children"] = ["44864"]
    by_id = {
        "44864": {"id": "44864", "name": "Hua_83EF", "dynasty": "11527"},
    }
    p = to_profile(stub, _loader_with_names(), by_id=by_id,
                   resolver=_resolver_with_house(house_name="华"))
    assert p.children[0].name == "华"


def test_relationship_period_former_spouse_also_gets_surname():
    stub = _stub()
    stub["former_spouses"] = ["2001"]
    by_id = {
        "2001": {"id": "2001", "name": "Hua_83EF", "dynasty": "11527"},
    }
    p = to_profile(stub, _loader_with_names(), by_id=by_id, resolver=_resolver_with_house())
    sp = p.spouses[0]
    assert sp.name == "梁华"
    assert sp.isFormer is True


def test_relatives_and_liege_get_surname():
    """2C.2：父母与君主引用同样拼接已解析姓。"""
    stub = _stub()
    stub["father"] = "1001"
    stub["liege"] = "9001"
    stub["parent_source"] = "child_backref"
    by_id = {
        "1001": {"id": "1001", "name": "max_chinese_male_name_1001", "dynasty": "11527"},
        "9001": {"id": "9001", "name": "Hua_83EF", "dynasty": "11527"},
        "6432": {"id": "6432", "name": "Hua_83EF", "dynasty": "11527"},
    }
    p = to_profile(stub, _loader_with_names(), by_id=by_id, resolver=_resolver_with_house())
    assert p.parents[0].name == "梁赵大"
    assert p.liege.name == "梁华"
