"""SessionManager 测试（规范三）：一次 melt 多次查询、分页/筛选、并发只 prepare 一次。

不依赖真实存档：FakeAdapter.prepare 只写出受控缓存产物，验证会话逻辑本身。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from app.services.session_manager import CACHE_SCHEMA_VERSION, ParseSession, SessionManager


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
            # Phase 3A.1：cache schema 版本显式化（与 session_manager 常量一致）。
            "cache_schema_version": CACHE_SCHEMA_VERSION,
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
        (cache_dir / "manifest.json").write_text(
            json.dumps({"signature": cache_dir.name, "cache_schema_version": CACHE_SCHEMA_VERSION}),
            encoding="utf-8",
        )
        # M2/M3 缓存产物：entities.json（实体索引）与 titles.json（头衔）——SessionManager
        # _cache_valid 要求这两个文件存在才视为缓存完整，重启后可复用。
        # Phase 3A.1：5 个缓存文件都必须带同一 cache_schema_version，缺一则整体失效。
        (cache_dir / "entities.json").write_text(
            json.dumps({"schema_version": 1, "kinds": {}, "cache_schema_version": CACHE_SCHEMA_VERSION}),
            encoding="utf-8",
        )
        (cache_dir / "titles.json").write_text(
            json.dumps(
                {"schema_version": 1, "title_count": 0, "titles": [], "cache_schema_version": CACHE_SCHEMA_VERSION}
            ),
            encoding="utf-8",
        )
        # M4 缓存产物：memories.json（记忆库）——_cache_valid 要求其存在。
        (cache_dir / "memories.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "memory_count": 0,
                    "memories": [],
                    "cache_schema_version": CACHE_SCHEMA_VERSION,
                }
            ),
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


def test_stale_cache_with_wrong_schema_version_is_invalid(tmp_path):
    """Phase 3A.1：cache_schema_version 缺失或不匹配 → 旧缓存必须失效重建。

    reader 扫描/提取行为变更（如 CACHE_SCHEMA_VERSION 递增）后，旧缓存语义
    已过时；若仅靠 reader_version + 二进制指纹，旧错误缓存可能被复用。
    """
    adapter = FakeAdapter()
    sm = SessionManager(tmp_path / "cache", adapter)
    sess = sm.prepare("s1", "sigA", "staging.ck3")
    # 篡改 meta.json：改成旧版本号，模拟"升级前"的缓存产物。
    meta_path = sess.cache_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["cache_schema_version"] = "1"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    adapter2 = FakeAdapter()
    sm2 = SessionManager(tmp_path / "cache", adapter2)
    sess2 = sm2.prepare("s1", "sigA", "staging.ck3")
    assert adapter2.prepare_calls == 1  # 版本不符 → 重建
    assert sess2.character_count == 3


def test_stale_cache_when_any_cache_file_version_mismatch(tmp_path):
    """Phase 3A.1：5 个缓存文件任一 cache_schema_version 不匹配 → 整体失效重建。

    防止部分新旧的混合缓存被复用（如只升级了 titles 扫描而 entities 仍是旧格式）。
    """
    adapter = FakeAdapter()
    sm = SessionManager(tmp_path / "cache", adapter)
    sess = sm.prepare("s1", "sigA", "staging.ck3")
    # 篡改 titles.json（非 meta）的版本号，meta.json 保持正确。
    titles_path = sess.cache_dir / "titles.json"
    titles = json.loads(titles_path.read_text(encoding="utf-8"))
    titles["cache_schema_version"] = "1"
    titles_path.write_text(json.dumps(titles), encoding="utf-8")
    adapter2 = FakeAdapter()
    sm2 = SessionManager(tmp_path / "cache", adapter2)
    sess2 = sm2.prepare("s1", "sigA", "staging.ck3")
    assert adapter2.prepare_calls == 1  # 任一文件版本不符 → 重建
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


def test_dirty_cache_dir_is_cleared_before_remelt(tmp_path):
    """3C.7 超时修复：缓存无效时若目录残留损坏半成品（melt 中断留下部分文件），
    必须先清理目录再 melt，避免向脏目录覆盖写造成混合文件（自愈）。

    用户报告"加载存档后端超时"根因：manifest 版本旧 + memories 截断 → 每次请求
    都重新 melt 且 melt 超时被杀 → 留下更脏的半成品 → 恶性循环。本测试锁定：
    无效缓存目录在重建前被整目录清空（prepare 后目录里只有本次 melt 的产物）。
    """
    adapter = FakeAdapter()
    sm = SessionManager(tmp_path / "cache", adapter)
    sess = sm.prepare("s1", "sigA", "staging.ck3")
    # 模拟损坏：memories.json 截断为非法 JSON + manifest 版本改旧。
    mem_path = sess.cache_dir / "memories.json"
    mem_path.write_bytes(b"{broken")
    mani_path = sess.cache_dir / "manifest.json"
    mani = json.loads(mani_path.read_text(encoding="utf-8"))
    mani["cache_schema_version"] = "2"
    mani_path.write_text(json.dumps(mani), encoding="utf-8")
    # 额外放一个"旧脏文件"：若重建前未清理目录，它会被带进新缓存。
    (sess.cache_dir / "stale.tmp").write_text("dirty", encoding="utf-8")
    # 重启：缓存判无效 → 必须清目录后完整重建。
    adapter2 = FakeAdapter()
    sm2 = SessionManager(tmp_path / "cache", adapter2)
    sess2 = sm2.prepare("s1", "sigA", "staging.ck3")
    assert adapter2.prepare_calls == 1  # 不信任脏缓存，重建
    assert sess2.character_count == 3
    # 自愈：脏目录被清理，旧残留文件不再存在；新缓存全部有效。
    assert not (sess2.cache_dir / "stale.tmp").exists()
    assert not (sess2.cache_dir / "memories.json").read_text(
        encoding="utf-8"
    ).startswith("{broken")
    fresh = json.loads((sess2.cache_dir / "manifest.json").read_text(encoding="utf-8"))
    assert fresh["cache_schema_version"] == CACHE_SCHEMA_VERSION


def test_melt_failure_removes_halfwritten_cache(tmp_path):
    """3C.7 超时修复：melt 失败（超时/格式不支持）时必须移除不完整产物，
    避免下次请求复用半成品缓存继续失败（自愈）。
    """
    adapter = FakeAdapter()

    def failing_prepare(staging_path, cache_dir):
        # 先写一部分文件（模拟超时被杀前的半成品），再抛异常。
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "meta.json").write_text('{"partial": true}', encoding="utf-8")
        raise RuntimeError("melt 超时")

    adapter.prepare = failing_prepare  # type: ignore[method-assign]
    sm = SessionManager(tmp_path / "cache", adapter)
    try:
        sm.prepare("s1", "sigA", "staging.ck3")
        raise AssertionError("prepare 应抛出异常")
    except RuntimeError:
        pass
    # 半成品目录必须被移除（自愈：不让脏文件残留）
    assert not (tmp_path / "cache" / "s1" / "sigA").exists()


def test_prepare_succeeds_after_failed_melt(tmp_path):
    """3C.7 超时修复：melt 失败后（半成品已移除），下次请求可正常重建。
    模拟"首次超时 → 清理 → 重试成功"的完整自愈闭环。
    """
    adapter = FakeAdapter()
    fail = True

    def flaky_prepare(staging_path, cache_dir):
        nonlocal fail
        if fail:
            fail = False
            cache_dir = Path(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "meta.json").write_text('{"partial": true}', encoding="utf-8")
            raise RuntimeError("melt 超时")
        return FakeAdapter.prepare(adapter, staging_path, cache_dir)

    adapter.prepare = flaky_prepare  # type: ignore[method-assign]
    sm = SessionManager(tmp_path / "cache", adapter)
    try:
        sm.prepare("s1", "sigA", "staging.ck3")
    except RuntimeError:
        pass
    # 第一次失败后目录被清空 → 第二次重试成功
    sess = sm.prepare("s1", "sigA", "staging.ck3")
    assert sess.character_count == 3
    assert adapter.prepare_calls == 1
    # 第三次命中缓存，不再 melt
    sm.prepare("s1", "sigA", "staging.ck3")
    assert adapter.prepare_calls == 1
