"""SessionManager 测试（规范三）：一次 melt 多次查询、分页/筛选、并发只 prepare 一次。

不依赖真实存档：FakeAdapter.prepare 只写出受控缓存产物，验证会话逻辑本身。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from app.services.session_manager import ParseSession, SessionManager


class FakeAdapter:
    def __init__(self) -> None:
        self.prepare_calls = 0

    def is_available(self) -> bool:
        return True

    def prepare(self, staging_path, cache_dir):
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.prepare_calls += 1
        meta = {
            "encoding": "Binary",
            "save_version": "15",
            "game_version": "1.19.0.6",
            "mods": ["mod/ugc_1.mod", "mod/ugc_2.mod"],
            "character_count": 3,
            "dead_character_count": 1,
        }
        (cache_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        (cache_dir / "mods.json").write_text(json.dumps({"mods": meta["mods"]}), encoding="utf-8")
        recs = [
            {
                "id": "1", "name": "Alice", "birth": "700.1.1", "death": None,
                "alive": True, "sex": "female", "culture": "c1", "faith": "41",
                "dynasty": "9067", "father": None, "mother": None,
                "spouses": [], "children": ["2"], "traits": ["genius"],
                "ruler": True, "evidence_warnings": ["faith", "dynasty", "primary_title"],
            },
            {
                "id": "2", "name": "Bob", "birth": "730.1.1", "death": "800.1.1",
                "alive": False, "sex": "male", "culture": "c2", "faith": "42",
                "dynasty": "9067", "father": "1", "mother": None,
                "spouses": ["1"], "children": [], "traits": [],
                "ruler": False, "evidence_warnings": ["faith", "dynasty", "primary_title"],
            },
            {
                "id": "3", "name": "Carol", "birth": "740.1.1", "death": None,
                "alive": True, "sex": None, "culture": "c3", "faith": "43",
                "dynasty": "9068", "father": None, "mother": None,
                "spouses": [], "children": [], "traits": ["brave"],
                "ruler": False, "evidence_warnings": ["faith", "dynasty", "primary_title"],
            },
        ]
        buf = []
        offsets = {}
        for r in recs:
            line = json.dumps(r)
            offsets[r["id"]] = sum(len(x) for x in buf)
            buf.append(line)
        (cache_dir / "characters.ndjson").write_text("\n".join(buf) + "\n", encoding="utf-8")
        (cache_dir / "character-offsets.json").write_text(json.dumps(offsets), encoding="utf-8")
        (cache_dir / "manifest.json").write_text(json.dumps({"signature": cache_dir.name}), encoding="utf-8")

    def meta(self, cache_dir):
        return json.loads(Path(cache_dir / "meta.json").read_text(encoding="utf-8"))

    def character(self, cache_dir, cid):
        offsets = json.loads(Path(cache_dir / "character-offsets.json").read_text(encoding="utf-8"))
        lines = Path(cache_dir / "characters.ndjson").read_text(encoding="utf-8").splitlines()
        return json.loads(lines[0]) if cid == "1" else None


def test_prepare_once_then_many_queries(tmp_path):
    adapter = FakeAdapter()
    sm = SessionManager(tmp_path / "cache", adapter)
    sm.prepare("s1", "sigA", "staging.ck3")
    # 多次查询不应再次 melt
    for _ in range(5):
        sm.prepare("s1", "sigA", "staging.ck3")
    assert adapter.prepare_calls == 1
    sess = sm.get("s1", "sigA")
    assert sess.character_count == 3


def test_pagination_and_filters(tmp_path):
    adapter = FakeAdapter()
    sm = SessionManager(tmp_path / "cache", adapter)
    sess = sm.prepare("s1", "sigA", "staging.ck3")
    # 全量
    allp = sm.list_characters(sess, offset=0, limit=200)
    assert allp["total"] == 3
    assert allp["hasMore"] is False
    # 分页
    p1 = sm.list_characters(sess, offset=0, limit=1)
    assert len(p1["items"]) == 1 and p1["hasMore"] is True
    # rulerOnly
    r = sm.list_characters(sess, ruler_only=True)
    assert r["total"] == 1 and r["items"][0]["id"] == "1"
    # aliveOnly
    a = sm.list_characters(sess, alive_only=True)
    assert a["total"] == 2
    # dynasty 过滤
    d = sm.list_characters(sess, dynasty="9067")
    assert d["total"] == 2
    # 搜索
    q = sm.list_characters(sess, q="bob")
    assert q["total"] == 1 and q["items"][0]["id"] == "2"
    # 排序
    s = sm.list_characters(sess, sort="birth")
    assert [x["id"] for x in s["items"]] == ["1", "2", "3"]


def test_get_character(tmp_path):
    adapter = FakeAdapter()
    sm = SessionManager(tmp_path / "cache", adapter)
    sess = sm.prepare("s1", "sigA", "staging.ck3")
    rec = sm.get_character(sess, "1")
    assert rec["name"] == "Alice"
    import pytest
    with pytest.raises(KeyError):
        sm.get_character(sess, "999")


def test_new_signature_re_prepares_and_prunes(tmp_path):
    adapter = FakeAdapter()
    sm = SessionManager(tmp_path / "cache", adapter)
    sm.prepare("s1", "sigA", "staging.ck3")
    # 新签名 → 重新 melt 一次
    sm.prepare("s1", "sigB", "staging2.ck3")
    assert adapter.prepare_calls == 2
    # 旧签名缓存目录被清理
    assert not (tmp_path / "cache" / "s1" / "sigA").exists()
    assert (tmp_path / "cache" / "s1" / "sigB").exists()


def test_concurrent_prepare_once(tmp_path):
    adapter = FakeAdapter()
    sm = SessionManager(tmp_path / "cache", adapter)

    def worker():
        sm.prepare("s1", "sigA", "staging.ck3")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert adapter.prepare_calls == 1


def test_restart_reuses_disk_cache(tmp_path):
    """服务重启后，若缓存目录合法可复用（ParseSession.load_index 从磁盘读取）。"""
    adapter = FakeAdapter()
    sm = SessionManager(tmp_path / "cache", adapter)
    sm.prepare("s1", "sigA", "staging.ck3")
    # 模拟重启：新建 SessionManager（adapter.prepare_calls 重置）
    adapter2 = FakeAdapter()
    sm2 = SessionManager(tmp_path / "cache", adapter2)
    sess = sm2.prepare("s1", "sigA", "staging.ck3")
    assert adapter2.prepare_calls == 0  # 复用磁盘缓存，不重新 melt
    assert sess.character_count == 3
