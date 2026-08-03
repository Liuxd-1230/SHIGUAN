"""EntityIndexBuilder + ReferenceResolver 单测（M2.5）。

验证：存档成品名 / loc 键 / def 键（经游戏定义→本地化）/ 无法命名 四类解析路径，
以及 ReferenceResolver 对未命中引用诚实返回 name=原 id、resolved=false（绝不伪造）。
"""
from models import EntityKind, EntityNameSource, EntityRef

from app.services.entity_index_builder import EntityIndexBuilder, ReferenceResolver
from app.services.game_def_loader import GameDefLoader
from app.services.localization import LocalizationLoader


def _fake_loc() -> LocalizationLoader:
    loader = LocalizationLoader()
    loader._ingest_text(
        "l_simp_chinese:\n"
        ' dynn_capet: "卡佩"\n'
        ' dynn_karling: "加洛林"\n'
        ' court_position_travel_leader: "旅行领袖"\n'
    )
    return loader


def _fake_game_def() -> GameDefLoader:
    g = GameDefLoader(None)
    g._maps = {
        "dynasty": {"2": "dynn_capet"},
        "house": {"house_karling": "dynn_karling"},
        "courtPositionType": {"travel_leader_court_position": "court_position_travel_leader"},
        "memoryType": {"became_soulmates": "memory_became_soulmates"},
    }
    return g


RAW = {
    "schema_version": 1,
    "reader_version": "0.1.0",
    "scan_ms": 12.0,
    "warnings": [],
    "kinds": {
        "dynasty": {
            "source": "save:dynasties.dynasties",
            "container_found": True,
            "count": 2,
            "unresolved_key_count": 0,
            "entries": {
                "2": {"key": "2", "key_kind": "def"},
                "dynn_capet": {"key": "dynn_capet"},
            },
        },
        "house": {
            "source": "save:dynasties.dynasty_house",
            "container_found": True,
            "count": 1,
            "unresolved_key_count": 0,
            "entries": {
                "house_karling": {"key": "house_karling", "key_kind": "def", "prefix": "dynnp_k"},
            },
        },
        "title": {
            "source": "save:landed_titles.landed_titles",
            "container_found": True,
            "count": 1,
            "unresolved_key_count": 0,
            "entries": {"e_byz": {"key": "e_byz", "save_name": "东罗马帝国"}},
        },
        "war": {
            "source": "save:wars.active_wars",
            "container_found": True,
            "count": 1,
            "unresolved_key_count": 0,
            "entries": {
                "war1": {"save_name": "声索吐蕃", "start_date": "867.1.1", "key": "cb_claim"},
            },
        },
        "courtPositionType": {
            "source": "save:court_positions.database[].court_position",
            "container_found": True,
            "count": 1,
            "unresolved_key_count": 0,
            "entries": {
                "travel_leader_court_position": {"key": "travel_leader_court_position", "key_kind": "def"},
            },
        },
        "faith": {
            "source": "save:religion.faiths",
            "container_found": True,
            "count": 1,
            "unresolved_key_count": 1,
            "entries": {
                # 占位 token 表下 faith 为数字 id，loc 查不到 → 无法命名
                "41": {"key": "41"},
            },
        },
    },
}


def _build() -> "object":
    return EntityIndexBuilder(game_def=_fake_game_def(), loc=_fake_loc()).build(RAW)


def test_def_key_resolves_via_game_def_and_loc():
    idx = _build()
    e = idx.kinds[EntityKind.DYNASTY].entries["2"]
    assert e.name == "卡佩"
    assert e.resolved is True
    assert e.nameSource == EntityNameSource.LOC  # 最终名来自本地化


def test_loc_key_resolves_directly():
    idx = _build()
    e = idx.kinds[EntityKind.DYNASTY].entries["dynn_capet"]
    assert e.name == "卡佩"
    assert e.resolved is True


def test_house_def_key_with_prefix():
    idx = _build()
    e = idx.kinds[EntityKind.HOUSE].entries["house_karling"]
    assert e.name == "加洛林"
    assert e.prefix == "dynnp_k"
    assert e.keyKind.value == "def"


def test_save_name_used_as_is():
    idx = _build()
    t = idx.kinds[EntityKind.TITLE].entries["e_byz"]
    assert t.name == "东罗马帝国"
    assert t.nameSource == EntityNameSource.SAVE
    w = idx.kinds[EntityKind.WAR].entries["war1"]
    assert w.name == "声索吐蕃"
    assert w.startDate == "867.1.1"


def test_court_position_def_key_resolves():
    idx = _build()
    e = idx.kinds[EntityKind.COURT_POSITION_TYPE].entries["travel_leader_court_position"]
    assert e.name == "旅行领袖"


def test_unnameable_entity_is_unresolved_not_fabricated():
    idx = _build()
    f = idx.kinds[EntityKind.FAITH]
    e = f.entries["41"]
    # 占位 token 表下数字 id 无法命名：name 退化为原始 id，绝不伪造可读名。
    assert e.resolved is False
    assert e.name == "41"
    assert f.unresolvedCount == 1


def test_unknown_kind_is_skipped():
    raw = dict(RAW)
    raw["kinds"] = dict(RAW["kinds"])
    raw["kinds"]["totally_new_kind"] = {
        "source": "x", "container_found": True, "count": 0,
        "unresolved_key_count": 0, "entries": {},
    }
    idx = EntityIndexBuilder(game_def=_fake_game_def(), loc=_fake_loc()).build(raw)
    assert "totally_new_kind" not in {k.value for k in idx.kinds}


def test_reference_resolver_hit_and_miss():
    idx = _build()
    rr = ReferenceResolver(idx)
    ref = rr.resolve("dynasty", "2")
    assert isinstance(ref, EntityRef)
    assert ref.name == "卡佩"
    assert ref.resolved is True
    # 未命中：name=原 id，resolved=false（不伪造"未知父亲"式名字）
    miss = rr.resolve("dynasty", "999")
    assert miss.name == "999"
    assert miss.resolved is False
    assert miss.type == "dynasty"
