"""M4 记忆时间线提取器测试：归属 / 时间线事件 / 关系推导 / 诚实边界。

不依赖真实存档：直接用构造的 memories.json 与人物索引喂 MemoryTimelineIndex，
验证 married 的 family_data 交叉核对归属、child_born 父母归属、became_* 同日期
配对、无日期不生成事件、skipped 类型诚实跳过、名字解析不伪造等。
"""
from __future__ import annotations

import pytest

from app.services.memory_timeline_extractor import (
    MemoryTimelineIndex,
    RELATIONSHIP_MEMORY_TYPES,
    SKIPPED_TYPES,
)
from app.services.character_extractor import derive_siblings

# 人物索引：Alice(1)/Bob(2) 是夫妻（互相列出）；Carol(3) 是 Alice 的女儿。
BY_ID = {
    "1": {"id": "1", "name": "name_alice", "sex": "female", "father": None, "mother": None,
          "spouses": ["2"], "children": ["3"]},
    "2": {"id": "2", "name": "name_bob", "sex": "male", "father": None, "mother": None,
          "spouses": ["1"], "children": []},
    "3": {"id": "3", "name": "name_carol", "sex": "female", "father": "2", "mother": "1",
          "spouses": [], "children": []},
}

# 本地化：把人物名键解析成真实人名。
LOC = type("Loc", (), {"resolve": lambda self, k: {"name_alice": "爱丽丝", "name_bob": "鲍勃", "name_carol": "卡罗尔"}.get(k)})()


def _memory(mid, mtype, participants, creation=None, end=None, location=None):
    return {
        "id": mid,
        "memory_type": mtype,
        "participants": [{"role": r, "character_id": c} for r, c in participants],
        "creation_date": creation,
        "end_date": end,
        "battle_location_id": location,
    }


def test_married_memories_attributed_to_owners_via_family_data():
    """married 记忆 owner 在条目外：family_data 交叉核对归属到双方，各得一条 MARRIAGE。"""
    raw = {
        "memories": [
            _memory("10", "married", [("spouse", "2")], "760.1.1", "890.1.1"),  # owner=Alice(1)
            _memory("11", "married", [("spouse", "1")], "760.1.1", "890.1.1"),  # owner=Bob(2)
        ],
        "warnings": [],
    }
    idx = MemoryTimelineIndex(raw, by_id=BY_ID, loc=LOC)
    # Alice 的记忆：来自 id=10（spouse=2），相关人 Bob。
    alice = idx.memories("1")
    assert len(alice) == 1
    assert alice[0].relatedCharacters[0].id == "2"
    assert alice[0].relatedCharacters[0].name == "鲍勃"
    # Bob 的记忆：来自 id=11（spouse=1），相关人 Alice。
    bob = idx.memories("2")
    assert len(bob) == 1
    assert bob[0].relatedCharacters[0].name == "爱丽丝"
    # 双方都有 MARRIAGE 时间线事件且带 memory 证据。
    for cid in ("1", "2"):
        tl = idx.timeline_events(cid)
        assert len(tl) == 1
        assert tl[0].type.value == "marriage"
        assert tl[0].date == "760.1.1"
        assert tl[0].evidence, "时间线事件必须带证据"
        assert tl[0].evidence[0].sourceType == "memory"
        assert "character_memory_manager/database" in (tl[0].evidence[0].sourcePath or "")
    assert idx.warnings("1") == []


def test_child_born_attributed_to_parent_via_children_index():
    """child_born 记忆：child 在某人 children 列表 → 归属到父母。"""
    raw = {
        "memories": [
            _memory("20", "child_born", [("child", "3")], "800.1.1", "930.1.1"),
        ],
        "warnings": [],
    }
    idx = MemoryTimelineIndex(raw, by_id=BY_ID, loc=LOC)
    # 父母是 Alice(1) 与 Bob(2)（两人的 children/father 关系都指向 Carol）。
    for cid in ("1", "2"):
        tl = idx.timeline_events(cid)
        assert len(tl) == 1, f"cid={cid}"
        assert tl[0].type.value == "child_birth"
        assert tl[0].relatedCharacters[0].id == "3"
        assert tl[0].relatedCharacters[0].name == "卡罗尔"


def test_married_memory_owner_unresolved_falls_back_to_subject_with_warning():
    """spouse 不在任何人的 spouse 列表 → 归属到被指名者 + owner 未解析告警。"""
    raw = {
        "memories": [
            _memory("30", "married", [("spouse", "9")], "760.1.1", "890.1.1"),
        ],
        "warnings": [],
    }
    idx = MemoryTimelineIndex(raw, by_id=BY_ID, loc=LOC)
    # 人物 9 不在索引中：记忆归属到 9 本身（subject 回退），但生成 owner 未解析告警。
    mems = idx.memories("9")
    assert len(mems) == 1
    assert mems[0].relatedCharacters == []
    assert any(w.code == "memory_owner_unresolved" for w in idx.warnings("9"))
    # 时间线事件也应生成（日期存在 + 可归属），只是对方未指名。
    tl = idx.timeline_events("9")
    assert len(tl) == 1
    assert tl[0].type.value == "marriage"
    assert tl[0].evidence


def test_became_friends_date_pairing_infers_named_friendship():
    """同类型同日期恰好两条、主体互异 → 推断互为好友（INFERRED + 告警）。"""
    raw = {
        "memories": [
            _memory("40", "became_friends", [("new_relation", "2")], "770.1.1", "900.1.1"),
            _memory("41", "became_friends", [("new_relation", "1")], "770.1.1", "900.1.1"),
        ],
        "warnings": [],
    }
    idx = MemoryTimelineIndex(raw, by_id=BY_ID, loc=LOC)
    alice_rel = idx.relationships("1")
    assert [r.id for r in alice_rel.friends] == ["2"]
    assert alice_rel.friends[0].name == "鲍勃"
    bob_rel = idx.relationships("2")
    assert [r.id for r in bob_rel.friends] == ["1"]
    # 推断关系必须带告警（不伪装成存档直述）。
    assert any(w.code == "relationship_inferred_from_memory" for w in idx.warnings("1"))
    # became_friends 是关系型记忆：进 memories 列表但不进时间线。
    assert idx.timeline_events("1") == []
    assert len(idx.memories("1")) == 1


def test_unpaired_relationship_counts_only_no_fabricated_name():
    """单条孤儿记忆（对方未指名）→ 只计数，不伪造名字进列表。"""
    raw = {
        "memories": [
            _memory("50", "became_rivals", [("rival", "1")], "775.1.1", "905.1.1"),
        ],
        "warnings": [],
    }
    idx = MemoryTimelineIndex(raw, by_id=BY_ID, loc=LOC)
    rel = idx.relationships("1")
    assert rel.rivals == []
    assert rel.rival_count == 1
    # 但记忆本身进入 memories 列表（如实呈现该事件）。
    assert len(idx.memories("1")) == 1


def test_relative_died_attributed_to_dead_relation_with_death_event():
    """relative_died 记忆：主体=dead_relation，得到 DEATH 事件。"""
    raw = {
        "memories": [
            _memory("60", "relative_died", [("dead_relation", "3")], "810.1.1", "940.1.1"),
        ],
        "warnings": [],
    }
    idx = MemoryTimelineIndex(raw, by_id=BY_ID, loc=LOC)
    tl = idx.timeline_events("3")
    assert len(tl) == 1
    assert tl[0].type.value == "death"
    assert tl[0].evidence[0].sourceType == "memory"


def test_battle_won_not_in_timeline_but_kept_in_memories():
    """battle_* 单场小战役（2C.1）：不进时间线，但 memories 列表保留原始记录。

    无日期记忆也只进列表不生成事件；battle 战场位置仍在 memories 条目上。
    """
    raw = {
        "memories": [
            _memory("70", "battle_won_memory", [("loser", "3"), ("ruler", "1")],
                    "790.1.1", "920.1.1", "6473"),
            _memory("71", "battle_won_memory", [("loser", "3"), ("ruler", "1")], None, None),
        ],
        "warnings": [],
    }
    idx = MemoryTimelineIndex(raw, by_id=BY_ID, loc=LOC)
    tl = idx.timeline_events("1")
    assert tl == []  # battle_* 不进时间线
    # 两条都进 memories 列表（无日期那条 date=None，诚实呈现），带战场位置。
    mems = idx.memories("1")
    assert len(mems) == 2
    assert {m.date for m in mems} == {"790.1.1", None}
    located = next(m for m in mems if m.location is not None)
    assert located.location.id == "6473"
    assert located.type.value == "war"


def test_war_won_in_timeline_with_opponent_name():
    """war_won → 主要战争进时间线，标题带胜负、描述带对手名。"""
    raw = {
        "memories": [
            _memory("72", "war_won", [("winner", "1"), ("loser", "3")], "792.5.5", None),
            _memory("73", "offensive_war", [("other_party", "3")], "793.6.6", None),
        ],
        "warnings": [],
    }
    idx = MemoryTimelineIndex(raw, by_id=BY_ID, loc=LOC)
    tl = idx.timeline_events("1")
    assert len(tl) == 1
    assert tl[0].type.value == "war"
    assert tl[0].title == "战争获胜"
    assert "卡罗尔" in tl[0].description  # 对手名经索引解析，不裸 id
    assert tl[0].relatedCharacters[0].id == "3"
    # offensive_war 主体是 other_party(3)，与 cid=1 不匹配 → 不归属到 Alice。
    assert all(e.id != "1-memory-73" for e in tl)


def test_skipped_types_are_not_attributed():
    """imprisoned / ascended_throne_memory：owner 非 participant，诚实跳过。"""
    raw = {
        "memories": [
            _memory("80", "imprisoned", [("imprisoner", "2")], "760.1.1", "890.1.1"),
            _memory("81", "ascended_throne_memory", [("flavor_character", "2")], "760.1.1", "890.1.1"),
        ],
        "warnings": [],
    }
    idx = MemoryTimelineIndex(raw, by_id=BY_ID, loc=LOC)
    assert idx.memories("1") == []
    assert idx.memories("2") == []
    assert idx.timeline_events("2") == []
    assert idx.skipped_type_count == 2


def test_name_resolution_falls_back_honestly():
    """名字解析：不在索引中的 id → name=原 id（不伪造）。"""
    raw = {
        "memories": [
            _memory("90", "war_won", [("winner", "1"), ("loser", "999")], "790.1.1", None),
        ],
        "warnings": [],
    }
    idx = MemoryTimelineIndex(raw, by_id=BY_ID, loc=LOC)
    tl = idx.timeline_events("1")
    assert tl[0].relatedCharacters[0].id == "999"
    assert tl[0].relatedCharacters[0].name == "999"


def test_memory_type_localization_in_description_and_scanner_warnings():
    """scanner_warnings 透传 Rust 扫描告警。"""
    raw = {
        "memories": [_memory("100", "became_friends", [("new_relation", "1")], "770.1.1", None)],
        "warnings": ["container_not_found: 某容器未找到"],
    }
    idx = MemoryTimelineIndex(raw, by_id=BY_ID, loc=LOC)
    assert idx.scanner_warnings() == ["container_not_found: 某容器未找到"]


def test_siblings_derived_from_shared_parents():
    """siblings：共享父/母推导，排除自己，名字经索引解析。"""
    stub = {"id": "3", "father": "2", "mother": "1"}
    # 增加一个与 Carol 共享父母的兄弟（索引里没有则跳过）。
    by_id = dict(BY_ID)
    by_id["4"] = {"id": "4", "name": "name_dave", "father": "2", "mother": "1"}
    sibs = derive_siblings(stub, by_id)
    assert [s.id for s in sibs] == ["4"]
    assert sibs[0].sourcePath and "inferred_from_shared_parent" in sibs[0].sourcePath


def test_relationship_memory_types_and_skipped_types_are_contract_stable():
    """关系型/跳过类型的表完整性：不因代码漂移而静默变化。"""
    assert set(RELATIONSHIP_MEMORY_TYPES) == {
        "became_soulmates", "became_lovers", "became_friends", "became_rivals",
    }
    assert SKIPPED_TYPES >= {"imprisoned", "ascended_throne_memory"}


def test_memory_index_surname_appended_to_relationship_refs():
    """2C.2：MemoryTimelineIndex 传入 resolver 后，关系人引用拼接已解析姓。"""
    from app.services.localization import LocalizationLoader
    from app.services.entity_index_builder import EntityIndexBuilder, ReferenceResolver
    from app.services.game_def_loader import GameDefLoader

    loc = LocalizationLoader()
    loc._ingest_text("l_simp_chinese:\n dynn_liang205: \"梁\"\n")
    g = GameDefLoader(None)
    g._maps = {"house": {"9": "dynn_liang205"}}
    raw = {
        "schema_version": 1, "reader_version": "0.1.0", "scan_ms": 1.0, "warnings": [],
        "kinds": {
            "house": {"source": "save:dynasties.dynasty_house", "container_found": True,
                      "count": 1, "unresolved_key_count": 0,
                      "entries": {"9": {"key": "9", "key_kind": "def"}}},
            "dynasty": {"source": "x", "container_found": True, "count": 0,
                         "unresolved_key_count": 0, "entries": {}},
        },
    }
    resolver = ReferenceResolver(EntityIndexBuilder(game_def=g, loc=loc).build(raw))

    by_id = dict(BY_ID)
    by_id["2"]["dynasty"] = "9"  # Bob 属于「梁」氏
    memories = {
        "memories": [
            _memory("40", "became_friends", [("new_relation", "2")], "770.1.1", "900.1.1"),
            _memory("41", "became_friends", [("new_relation", "1")], "770.1.1", "900.1.1"),
        ],
        "warnings": [],
    }
    idx = MemoryTimelineIndex(memories, by_id=by_id, loc=LOC, resolver=resolver)
    alice_rel = idx.relationships("1")
    friend = alice_rel.friends[0]
    assert friend.name == "梁鲍勃"
    assert friend.dynasty is not None
    assert friend.dynasty.name == "梁"
