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
            # M3.1：_cache_valid 要求 reader_version 存在，模拟新版 reader 产物。
            "reader_version": "0.1.0-test",
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
        # M2/M3 缓存产物：entities.json（实体索引）与 titles.json（头衔）——SessionManager
        # _cache_valid 要求这两个文件存在才视为缓存完整，重启后可复用。
        (cache_dir / "entities.json").write_text(
            json.dumps({"schema_version": 1, "kinds": {}}), encoding="utf-8"
        )
        (cache_dir / "titles.json").write_text(
            json.dumps({"schema_version": 1, "title_count": 0, "titles": []}), encoding="utf-8"
        )
        # M4 缓存产物：memories.json（记忆库）——_cache_valid 要求其存在。
        (cache_dir / "memories.json").write_text(
            json.dumps({"schema_version": 1, "memory_count": 0, "memories": []}),
            encoding="utf-8",
        )

    def meta(self, cache_dir):
        return json.loads(Path(cache_dir / "meta.json").read_text(encoding="utf-8"))

    def titles(self, cache_dir):
        return json.loads(Path(cache_dir / "titles.json").read_text(encoding="utf-8"))

    def memories(self, cache_dir):
        return json.loads(Path(cache_dir / "memories.json").read_text(encoding="utf-8"))

    def entities(self, cache_dir):
        return json.loads(Path(cache_dir / "entities.json").read_text(encoding="utf-8"))

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


def test_titles_reads_cache(tmp_path):
    """M3：titles(sess) 从缓存 titles.json 读取，不重新 melt。"""
    adapter = FakeAdapter()
    sm = SessionManager(tmp_path / "cache", adapter)
    sess = sm.prepare("s1", "sigA", "staging.ck3")
    assert adapter.prepare_calls == 1
    titles = sm.titles(sess)
    assert titles["title_count"] == 0
    assert isinstance(titles["titles"], list)


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


def test_stale_cache_without_reader_version_is_invalid(tmp_path):
    """旧版 reader 缓存（meta.json 无 reader_version）必须判无效并重建。

    M3.1 防线：reader 行为变更（如 game_version 提取修正）后，旧缓存语义
    已过时，若继续复用会返回错误数据。此测试锁定"无 reader_version → 重建"。
    """
    adapter = FakeAdapter()
    sm = SessionManager(tmp_path / "cache", adapter)
    sess = sm.prepare("s1", "sigA", "staging.ck3")
    # 篡改 meta.json：删掉 reader_version，模拟旧版 reader 产物
    meta_path = sess.cache_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.pop("reader_version", None)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    # 重启：缓存判无效 → 重新 prepare（melt 一次）
    adapter2 = FakeAdapter()
    sm2 = SessionManager(tmp_path / "cache", adapter2)
    sess2 = sm2.prepare("s1", "sigA", "staging.ck3")
    assert adapter2.prepare_calls == 1  # 不信任旧缓存，重建
    assert sess2.character_count == 3


class FingerprintFakeAdapter(FakeAdapter):
    """带真实二进制路径的 FakeAdapter：_binary_fingerprint 可拿到指纹。"""

    def __init__(self, binary_path: Path) -> None:
        super().__init__()
        self.binary = str(binary_path)


def test_stale_cache_from_different_binary_is_invalid(tmp_path):
    """M3.2：同一 reader_version（如 "0.1.0"）无法区分占位/真实 token 表构建。

    用占位表二进制 prepare 写出的缓存若被真实表二进制复用，会静默拿到 25 字节空
    数据（容器"找不到"）。marker 记录二进制自身指纹（路径/尺寸/时间戳），
    二进制重建后缓存必须失效重建——绝不静默降级。
    """
    bin_path = tmp_path / "ck3-reader.exe"
    bin_path.write_bytes(b"\x00" * 100)
    adapter = FingerprintFakeAdapter(bin_path)
    sm = SessionManager(tmp_path / "cache", adapter)
    sm.prepare("s1", "sigA", "staging.ck3")
    # 同一二进制重启 → 复用磁盘缓存，不重新 melt
    adapter2 = FingerprintFakeAdapter(bin_path)
    sm2 = SessionManager(tmp_path / "cache", adapter2)
    sess = sm2.prepare("s1", "sigA", "staging.ck3")
    assert adapter2.prepare_calls == 0
    assert sess.character_count == 3
    # 二进制被重建（如换 token 表，尺寸/时间戳变化）→ 缓存判无效，重新 prepare
    bin_path.write_bytes(b"\x00" * 200)
    adapter3 = FingerprintFakeAdapter(bin_path)
    sm3 = SessionManager(tmp_path / "cache", adapter3)
    sess3 = sm3.prepare("s1", "sigA", "staging.ck3")
    assert adapter3.prepare_calls == 1  # 不信任旧二进制的缓存，重建
    assert sess3.character_count == 3
