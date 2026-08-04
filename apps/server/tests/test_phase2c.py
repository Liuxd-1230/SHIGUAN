"""Phase 2C 修复轮：玩家/关联度排序、姓（house）解析、搜索增强 单测。

覆盖：
  - _player_full_name：meta.player_name「王，梁克贞」→ 姓名主体「梁克贞」；
  - _detect_player / _relevance_ranks：按「姓+名」反推玩家 + 直系/同族 rank；
  - list_characters relevance 排序：玩家 → 直系 → 同族 → 统治者 → 其他；
  - to_summary / to_profile：resolver 把 house id → 可读姓（dynn_liang205→梁）；
  - _search_text_resolver：解析后的文化/信仰/王朝名可被搜索命中。
"""
from __future__ import annotations

import json
import types
from pathlib import Path

from app.routers import saves
from app.services.character_extractor import to_profile, to_summary
from app.services.entity_index_builder import EntityIndexBuilder, ReferenceResolver
from app.services.localization import LocalizationLoader
from app.services.session_manager import SessionManager


def _fake_loc() -> LocalizationLoader:
    loader = LocalizationLoader()
    loader._ingest_text(
        "l_simp_chinese:\n"
        ' dynn_liang205: "梁"\n'
        ' dynn_chai200: "柴"\n'
        ' han: "汉"\n'
        ' jingxue: "景教"\n'
    )
    return loader


RAW_ENTITIES = {
    "schema_version": 1,
    "reader_version": "0.1.0",
    "scan_ms": 1.0,
    "warnings": [],
    "kinds": {
        "house": {
            "source": "save:dynasties.dynasty_house",
            "container_found": True,
            "count": 2,
            "unresolved_key_count": 0,
            "entries": {
                "9067": {"key": "dynn_liang205", "parent": "0"},
                "9068": {"key": "dynn_chai200", "parent": "0"},
            },
        },
        "dynasty": {
            "source": "save:dynasties.dynasties",
            "container_found": True,
            "count": 2,
            "unresolved_key_count": 0,
            "entries": {
                "9067": {"key": "9067", "key_kind": "def"},
                "9068": {"key": "9068", "key_kind": "def"},
            },
        },
        "culture": {
            "source": "save:culture.cultures",
            "container_found": True,
            "count": 1,
            "unresolved_key_count": 0,
            "entries": {"47": {"key": "han", "save_name": "han"}},
        },
        "faith": {
            "source": "save:religion.faiths",
            "container_found": True,
            "count": 1,
            "unresolved_key_count": 0,
            "entries": {"41": {"key": "jingxue"}},
        },
    },
}


def _resolver() -> ReferenceResolver:
    idx = EntityIndexBuilder(game_def=None, loc=_fake_loc()).build(RAW_ENTITIES)
    return ReferenceResolver(idx)


def _session():
    """构造轻量 ParseSession 替身：玩家 id=1（克贞/梁氏，存活统治者）。"""
    records = [
        {"id": "1", "name": "克贞", "dynasty": "9067", "alive": True, "ruler": True,
         "spouses": ["2"], "children": ["3"], "father": None, "mother": None,
         "primary_spouse": "2", "former_spouses": [], "concubines": [], "culture": "47", "faith": "41"},
        {"id": "2", "name": "Bob", "dynasty": "9067", "alive": True, "ruler": False,
         "spouses": ["1"], "children": [], "father": None, "mother": None,
         "primary_spouse": "1", "former_spouses": [], "concubines": [], "culture": "47", "faith": "41"},
        {"id": "3", "name": "Carol", "dynasty": "9067", "alive": True, "ruler": False,
         "spouses": [], "children": [], "father": "1", "mother": None,
         "primary_spouse": None, "former_spouses": [], "concubines": [], "culture": "47", "faith": "41"},
        # 同名「克贞」但不同 house（柴）→ 全名不匹配，不应误判为玩家。
        {"id": "4", "name": "克贞", "dynasty": "9068", "alive": True, "ruler": False,
         "spouses": [], "children": [], "father": None, "mother": None,
         "primary_spouse": None, "former_spouses": [], "concubines": [], "culture": "47", "faith": "41"},
    ]
    by_id = {r["id"]: r for r in records}
    return types.SimpleNamespace(records=records, by_id=by_id, signature="sigA")


def _fake_sm(meta: dict):
    return types.SimpleNamespace(meta=lambda sess: meta)


# -- 玩家名主体提取 ------------------------------------------------------------
def test_player_full_name_strips_title_prefix(monkeypatch):
    monkeypatch.setattr(saves, "_session_manager", _fake_sm({"player_name": "王，梁克贞"}))
    assert saves._player_full_name(None) == "梁克贞"
    # 无「，」前缀时原样返回
    monkeypatch.setattr(saves, "_session_manager", _fake_sm({"player_name": "梁克贞"}))
    assert saves._player_full_name(None) == "梁克贞"
    # 缺 player_name → None（不伪造玩家）
    monkeypatch.setattr(saves, "_session_manager", _fake_sm({}))
    assert saves._player_full_name(None) is None


# -- 玩家反推 ------------------------------------------------------------------
def test_detect_player_prefers_alive_ruler(monkeypatch):
    loader = _fake_loc()
    rslv = _resolver()
    sess = _session()
    pid = saves._detect_player(sess, loader, rslv, "梁克贞")
    assert pid == "1"


def test_detect_player_returns_none_without_resolver():
    loader = _fake_loc()
    assert saves._detect_player(_session(), loader, None, "梁克贞") is None


def test_relevance_ranks_builds_player_relations(monkeypatch):
    loader = _fake_loc()
    rslv = _resolver()
    sess = _session()
    monkeypatch.setattr(saves, "_session_manager", _fake_sm({"player_name": "王，梁克贞"}))
    monkeypatch.setattr(saves, "_relevance_cache", {})
    info = saves._relevance_ranks(sess, "save1", loader, rslv)
    assert info["player"] == "1"
    assert "2" in info["rel1"]  # 配偶
    assert "3" in info["rel1"]  # 子女
    assert info["dynasty"] == "9067"


def test_relevance_ranks_no_player_without_loc(monkeypatch):
    # loader 缺失（本地化不可用）→ 无法解析姓 → player=None，退回默认顺序。
    sess = _session()
    monkeypatch.setattr(saves, "_session_manager", _fake_sm({"player_name": "王，梁克贞"}))
    monkeypatch.setattr(saves, "_relevance_cache", {})
    info = saves._relevance_ranks(sess, "save1", None, _resolver())
    assert info["player"] is None


# -- list_characters 相关性排序 ------------------------------------------------
def test_list_characters_relevance_sort(tmp_path):
    sm = SessionManager(tmp_path)
    recs = [
        {"id": "1", "name": "Alice", "dynasty": "9067", "alive": True, "ruler": True},
        {"id": "2", "name": "Bob", "dynasty": "9067", "alive": True, "ruler": False},
        {"id": "3", "name": "Carol", "dynasty": "9068", "alive": True, "ruler": False},
    ]
    sess = types.SimpleNamespace(records=recs)
    # 玩家 Carol(3)；其父 Bob(2) 直系；Alice(1) 同族 9067 且为统治者 → rank 2。
    relevance = {"player": "3", "rel1": {"2"}, "dynasty": "9067"}
    page = sm.list_characters(sess, offset=0, limit=200, relevance=relevance)
    ids = [r["id"] for r in page["items"]]
    assert ids == ["3", "2", "1"]
    # 显式 sort 不受 relevance 影响
    page2 = sm.list_characters(sess, offset=0, limit=200, relevance=relevance, sort="name")
    ids2 = [r["id"] for r in page2["items"]]
    assert ids2 == ["1", "2", "3"]


# -- 姓（house）解析 -----------------------------------------------------------
def test_to_summary_resolves_dynasty_house_name():
    stub = {"id": "1", "name": "克贞", "dynasty": "9067", "alive": True, "ruler": True,
            "culture": "47", "faith": "41", "evidence_warnings": []}
    summary = to_summary(stub, _fake_loc(), resolver=_resolver())
    assert summary.name == "克贞"
    assert summary.dynasty is not None
    assert summary.dynasty.name == "梁"
    assert summary.dynasty.resolved is True
    assert summary.culture.name == "汉"
    assert summary.faith.name == "景教"


def test_to_summary_without_resolver_falls_back_to_raw_id():
    stub = {"id": "1", "name": "克贞", "dynasty": "9067", "alive": True, "ruler": True,
            "culture": "47", "faith": "41", "evidence_warnings": []}
    summary = to_summary(stub, None, resolver=None)
    assert summary.dynasty is not None
    assert summary.dynasty.name == "9067"
    assert summary.dynasty.resolved is False


def test_to_profile_resolves_dynasty_house_name():
    stub = {"id": "1", "name": "克贞", "dynasty": "9067", "alive": True, "ruler": True,
            "culture": "47", "faith": "41", "evidence_warnings": []}
    profile = to_profile(stub, _fake_loc(), resolver=_resolver())
    assert profile.dynasty is not None
    assert profile.dynasty.name == "梁"
    assert profile.culture.name == "汉"


# -- 搜索增强 ------------------------------------------------------------------
def test_search_text_resolver_matches_resolved_names(monkeypatch):
    monkeypatch.setattr(saves, "_search_name_cache", {})
    loader = _fake_loc()
    rslv = _resolver()
    sess = _session()
    search_text = saves._search_text_resolver(sess, "save1", None, loader, rslv)
    text = search_text(sess.records[0])
    assert "梁" in text  # 解析后的王朝名
    assert "汉" in text  # 解析后的文化名
    assert "景教" in text  # 解析后的信仰名
    # 数字 id 仍可搜索（兼容旧行为）
    assert "9067" in text


def test_search_text_resolver_without_resolver_keeps_ids(monkeypatch):
    monkeypatch.setattr(saves, "_search_name_cache", {})
    loader = _fake_loc()
    sess = _session()
    search_text = saves._search_text_resolver(sess, "save1", None, loader, None)
    text = search_text(sess.records[0])
    assert "9067" in text
    assert "梁" not in text  # 无实体索引时不强造可读名


# -- M5.1 收尾：已解析字段不保留过时 unresolved 告警 ------------------------------
def test_to_profile_drops_stale_unresolved_warnings_for_resolved_fields():
    """实体索引已把 culture/faith/dynasty 解析成中文名时，不再报"未命中可读名称"。

    读取器的 evidence_warnings 在无索引时把数字 id 标记为 unresolved；索引接入后
    这些字段已可读，过时告警应被过滤（未命中字段仍保留，绝不伪造）。
    """
    stub = {"id": "1", "name": "克贞", "dynasty": "9067", "alive": True, "ruler": True,
            "culture": "47", "faith": "41",
            "evidence_warnings": ["culture:numeric_id", "faith:numeric_id",
                                  "dynasty_house:numeric_id", "traits:numeric_id"]}
    profile = to_profile(stub, _fake_loc(), resolver=_resolver())
    assert profile.culture.name == "汉"
    assert profile.faith.name == "景教"
    assert profile.dynasty.name == "梁"
    codes = {w.code for w in profile.evidenceWarnings}
    # culture/faith/dynasty 已解析 → 不再有对应 unresolved 告警
    assert "unresolved_culture" not in codes
    assert "unresolved_faith" not in codes
    assert "unresolved_dynasty" not in codes
    assert "unresolved_dynasty_house" not in codes
    # 未解析的 traits 仍如实保留告警
    assert "unresolved_traits" in codes


def test_to_profile_keeps_unresolved_warnings_without_resolver():
    """无实体索引时，数字 id 字段的 unresolved 告警原样保留（不伪造）。"""
    stub = {"id": "1", "name": "克贞", "dynasty": "9067", "alive": True, "ruler": True,
            "culture": "47", "faith": "41",
            "evidence_warnings": ["culture:numeric_id", "faith:numeric_id"]}
    profile = to_profile(stub, None, resolver=None)
    codes = {w.code for w in profile.evidenceWarnings}
    assert "unresolved_culture" in codes
    assert "unresolved_faith" in codes


# -- 2C.1：绰号 nickname --------------------------------------------------------
def test_nickname_resolved_via_localization():
    """nick_the_peaceful → 本地化「仁」；resolved=True。"""
    loader = LocalizationLoader()
    loader._ingest_text('l_simp_chinese:\n nick_the_peaceful: "仁"\n')
    stub = {"id": "1", "name": "克贞", "nickname": "nick_the_peaceful", "alive": True}
    profile = to_profile(stub, loader)
    assert profile.nickname is not None
    assert profile.nickname.name == "仁"
    assert profile.nickname.resolved is True
    summary = to_summary(stub, loader)
    assert summary.nickname.name == "仁"


def test_nickname_falls_back_to_key_when_unlocalized():
    """本地化未命中 → 保留原 key + resolved=False（不伪造）。"""
    stub = {"id": "1", "name": "克贞", "nickname": "nick_unknown", "alive": True}
    profile = to_profile(stub, None)
    assert profile.nickname is not None
    assert profile.nickname.name == "nick_unknown"
    assert profile.nickname.resolved is False


def test_no_nickname_stays_none():
    """无绰号 → nickname 如实为空。"""
    stub = {"id": "1", "name": "克贞", "alive": True}
    assert to_profile(stub).nickname is None
    assert to_summary(stub).nickname is None


# -- 2C.1：君主 + 血缘远近/姻亲 ------------------------------------------------
def test_liege_extracted_from_dead_data():
    """dead_data.liege → CharacterProfile.liege；名字经索引解析。"""
    by_id = {
        "7": {"id": "7", "name": "name_king", "alive": False},
        "2": {"id": "2", "name": "name_vassal", "liege": "7", "alive": False},
    }
    loader = LocalizationLoader()
    loader._ingest_text('l_simp_chinese:\n name_king: "王上"\n name_vassal: "臣下"\n')
    stub = {"id": "2", "name": "name_vassal", "liege": "7", "alive": False}
    profile = to_profile(stub, loader, by_id=by_id)
    assert profile.liege is not None
    assert profile.liege.id == "7"
    assert profile.liege.name == "王上"
    assert profile.liege.sourcePath == "character/2/dead_data/liege"


def test_no_liege_stays_none():
    stub = {"id": "2", "name": "克贞", "alive": True}
    assert to_profile(stub).liege is None


def test_derive_extended_relations_covers_grandparent_cousin_inlaw():
    """血缘远近 + 姻亲：祖辈/堂表亲/姻亲经推断标注 sourcePath，不含直系重复。"""
    from app.services.character_extractor import derive_extended_relations

    # 家系：祖(10)-父(20)-己(1)，叔(30) 之子 = 堂弟(31)；配偶(40) 之父 = 岳丈(50)。
    by_id = {
        "10": {"id": "10", "name": "祖", "father": None, "mother": None},
        "20": {"id": "20", "name": "父", "father": "10", "mother": None},
        "30": {"id": "30", "name": "叔", "father": "10", "mother": None},
        "31": {"id": "31", "name": "堂弟", "father": "30", "mother": None},
        "1": {"id": "1", "name": "己", "father": "20", "mother": None, "spouses": ["40"]},
        "40": {"id": "40", "name": "妻", "father": "50", "mother": None, "spouses": ["1"]},
        "50": {"id": "50", "name": "岳丈", "father": None, "mother": None},
    }
    rels = derive_extended_relations(by_id["1"], by_id, LocalizationLoader())
    by_kind: dict[str, str] = {}
    for r in rels:
        kind = r.sourcePath.rsplit("#inferred_from_", 1)[-1]
        by_kind[r.id] = kind
    assert by_kind.get("10") == "grandparent"
    assert by_kind.get("30") == "aunt_uncle"
    assert by_kind.get("31") == "cousin"
    assert by_kind.get("50") == "in_law"
    # 直系亲属（父 20）不重复出现在 relatives
    assert "20" not in by_kind
    # 不含自己
    assert "1" not in by_kind
