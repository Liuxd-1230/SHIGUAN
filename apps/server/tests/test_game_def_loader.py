"""GameDefLoader 单测（M2.4）：PDX 文本解析 + game/common 目录扫描 + 优雅降级。"""
from app.services.game_def_loader import GameDefLoader, _parse_name_map


def test_parse_dynasty_numeric_key():
    text = '2 = {\n  name = "dynn_capet"\n}\n'
    assert _parse_name_map(text) == {"2": "dynn_capet"}


def test_parse_house_block():
    text = 'house_karling = {\n  name = "dynn_karling"\n  prefix = "dynnp_k"\n}\n'
    assert _parse_name_map(text) == {"house_karling": "dynn_karling"}


def test_parse_nested_wrapper_block():
    # court_positions 文件常用外层包裹块，类型块在 depth-2。
    text = (
        "court_positions = {\n"
        "  travel_leader_court_position = {\n"
        '    name = "court_position_travel_leader"\n'
        "  }\n"
        "}\n"
    )
    assert _parse_name_map(text) == {
        "travel_leader_court_position": "court_position_travel_leader"
    }


def test_parse_self_contained_block():
    text = 'became_soulmates = { name = "memory_became_soulmates" }\n'
    assert _parse_name_map(text) == {"became_soulmates": "memory_became_soulmates"}


def test_parse_ignores_blocks_without_name():
    text = "coinheritors = {\n  who = {}\n}\n2 = {\n name = \"dynn_capet\"\n}\n"
    # 没有 name 的区块不进入映射；有 name 的才进入。
    assert _parse_name_map(text) == {"2": "dynn_capet"}


def test_load_from_game_dir(tmp_path):
    common = tmp_path / "game" / "common"
    dyn = common / "dynasties"
    dyn.mkdir(parents=True)
    (dyn / "00_dynasties.txt").write_text(
        '2 = {\n name = "dynn_capet"\n}\n3 = {\n name = "dynn_plantagenet"\n}\n',
        encoding="utf-8",
    )
    hdir = dyn / "karling"
    hdir.mkdir()
    (hdir / "houses.txt").write_text(
        'house_karling = {\n name = "dynn_karling"\n}\n', encoding="utf-8"
    )
    cp = common / "court_positions"
    cp.mkdir(parents=True)
    (cp / "00_court_positions.txt").write_text(
        'travel_leader_court_position = {\n name = "court_position_travel_leader"\n}\n',
        encoding="utf-8",
    )
    mem = common / "character_memory_types"
    mem.mkdir(parents=True)
    (mem / "00_memories.txt").write_text(
        'became_soulmates = {\n name = "memory_became_soulmates"\n}\n', encoding="utf-8"
    )
    g = GameDefLoader(tmp_path)
    maps = g.load()
    assert maps["dynasty"].get("2") == "dynn_capet"
    assert maps["dynasty"].get("3") == "dynn_plantagenet"
    assert maps["house"].get("house_karling") == "dynn_karling"
    assert maps["courtPositionType"].get("travel_leader_court_position") == "court_position_travel_leader"
    assert maps["memoryType"].get("became_soulmates") == "memory_became_soulmates"
    assert g.lookup("dynasty", "2") == "dynn_capet"
    assert g.lookup("house", "house_karling") == "dynn_karling"


def test_missing_game_dir_degrades_gracefully():
    g = GameDefLoader(None)
    maps = g.load()
    assert all(len(v) == 0 for v in maps.values())
    assert g.is_available() is False
    assert g.lookup("dynasty", "2") is None
