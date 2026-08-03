"""路由/分页/安全/监听集成测试（规范四/五/八/九/十二）。

用 FakeAdapter 替换真实 melt，使整个后端点对点流程可测，无需真实 62MB 存档。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import saves
from app.services import save_registry
from app.services.game_data_resolver import GameDataResolver
from app.services.save_registry import SaveRegistry
from app.services.session_manager import SessionManager


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
            "encoding": "Binary", "save_version": "15", "game_version": "1.19.0.6",
            "date": "1100.1.1", "player_name": "玩家", "mod_count": 2,
            "mods": ["mod/ugc_1.mod", "mod/ugc_2.mod"], "character_count": 3,
            "dead_character_count": 1, "unknown_token_count": 0, "header_parse_ok": True,
            "token_metrics": {
                "token_ids_seen": 10, "placeholder_tokens_used": 5,
                "semantic_fields_mapped": 12, "unresolved_semantic_fields": ["faith", "dynasty"],
                "version_specific_field_mappings": [],
            }, "parse_ms": 1.0,
            # M3.1：_cache_valid 要求 reader_version 存在，模拟新版 reader 产物。
            "reader_version": "0.1.0-test",
        }
        (cache_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        (cache_dir / "mods.json").write_text(json.dumps({"mods": meta["mods"]}), encoding="utf-8")
        recs = [
            {"id": "1", "name": "Alice", "birth": "700.1.1", "death": None, "alive": True,
             "sex": "female", "culture": "c1", "faith": "41", "dynasty": "9067",
             "father": None, "mother": None, "spouses": [], "children": ["2"],
             "traits": ["genius"], "ruler": True, "evidence_warnings": ["faith", "dynasty", "primary_title"]},
            {"id": "2", "name": "Bob", "birth": "730.1.1", "death": "800.1.1", "alive": False,
             "sex": "male", "culture": "c2", "faith": "42", "dynasty": "9067",
             "father": "1", "mother": None, "spouses": ["1"], "children": [],
             "traits": [], "ruler": False, "evidence_warnings": ["faith", "dynasty", "primary_title"]},
            {"id": "3", "name": "Carol", "birth": "740.1.1", "death": None, "alive": True,
             "sex": None, "culture": "c3", "faith": "43", "dynasty": "9068",
             "father": None, "mother": None, "spouses": [], "children": [],
             "traits": ["brave"], "ruler": False, "evidence_warnings": ["faith", "dynasty", "primary_title"]},
        ]
        buf, offsets = [], {}
        for r in recs:
            line = json.dumps(r)
            offsets[r["id"]] = sum(len(x) for x in buf)
            buf.append(line)
        (cache_dir / "characters.ndjson").write_text("\n".join(buf) + "\n", encoding="utf-8")
        (cache_dir / "character-offsets.json").write_text(json.dumps(offsets), encoding="utf-8")
        (cache_dir / "manifest.json").write_text(json.dumps({"signature": cache_dir.name}), encoding="utf-8")
        # M2/M3 缓存产物：实体索引 + 头衔（landed_titles 反解）。
        (cache_dir / "entities.json").write_text(
            json.dumps({"schema_version": 1, "reader_version": "0.1.0", "kinds": {}}),
            encoding="utf-8",
        )
        # 头衔：Alice(1) 现任 d_alpha（公爵，历史两段），Bob(2) 曾持 c_beta（伯爵）后失去。
        titles = {
            "schema_version": 1,
            "reader_version": "0.1.0",
            "scan_ms": 1.0,
            "title_count": 2,
            "titles": [
                {
                    "key": "d_alpha",
                    "name": "阿尔法公国",
                    "name_source": "save",
                    "tier": "duchy",
                    "holder_id": "1",
                    "de_facto_liege_id": None,
                    "history": [
                        {"date": "760.1.1", "holder_id": "9", "kind": "holder"},
                        {"date": "780.5.10", "holder_id": "1", "kind": "holder"},
                    ],
                },
                {
                    "key": "c_beta",
                    "name": "c_beta",
                    "name_source": "key",
                    "tier": "county",
                    "holder_id": None,
                    "de_facto_liege_id": None,
                    "history": [
                        {"date": "770.2.2", "holder_id": "2", "kind": "holder"},
                        {"date": "790.3.3", "holder_id": "3", "kind": "holder"},
                    ],
                },
            ],
            "warnings": [],
        }
        (cache_dir / "titles.json").write_text(
            json.dumps(titles, ensure_ascii=False), encoding="utf-8"
        )

    def meta(self, cache_dir):
        return json.loads(Path(cache_dir / "meta.json").read_text(encoding="utf-8"))

    def titles(self, cache_dir):
        return json.loads(Path(cache_dir / "titles.json").read_text(encoding="utf-8"))

    def entities(self, cache_dir):
        return json.loads(Path(cache_dir / "entities.json").read_text(encoding="utf-8"))

    def character(self, cache_dir, cid):
        lines = Path(cache_dir / "characters.ndjson").read_text(encoding="utf-8").splitlines()
        for ln in lines:
            if json.loads(ln)["id"] == cid:
                return json.loads(ln)
        raise KeyError(cid)


@pytest.fixture
def client(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    staging.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    reg = SaveRegistry(staging)
    sm = SessionManager(cache)
    adapter = FakeAdapter()
    sm.adapter = adapter
    monkeypatch.setattr(saves, "_registry", reg)
    monkeypatch.setattr(saves, "_session_manager", sm)
    monkeypatch.setattr(saves, "_loc_cache", {})
    monkeypatch.setattr(saves, "_title_index_cache", {})
    # 测试隔离：不加载真实游戏本地化（CI/无游戏环境一致，且快）。
    monkeypatch.setattr(saves, "_game_resolver", lambda: GameDataResolver(game_dir="__no_game__"))
    monkeypatch.setattr(saves, "_watcher_events", [])
    monkeypatch.setattr(saves, "_last_event_id", None)
    monkeypatch.setattr(save_registry, "wait_until_stable", lambda *a, **k: True)
    with TestClient(app) as c:
        yield c, adapter, reg, sm


def _register(tmp_path, reg, name="autosave.ck3", data=b"SAV0101" + b"\x00" * 20):
    f = tmp_path / name
    f.write_bytes(data)
    return reg.register(str(f)).save_id


# -- 路由恢复（五） ----------------------------------------------------------
def test_expired_save_id_404(client, tmp_path):
    c, _a, _r, _s = client
    r = c.get("/api/saves/does_not_exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "unknown_save"


def test_recovery_save_meta_prepared_after_access(client, tmp_path):
    c, _a, reg, _s = client
    sid = _register(tmp_path, reg)
    r0 = c.get(f"/api/saves/{sid}")
    assert r0.status_code == 200
    assert r0.json()["registered"] is True
    assert r0.json()["prepared"] is False  # 尚未 melt
    c.get(f"/api/saves/{sid}/characters", params={"limit": 1})
    r1 = c.get(f"/api/saves/{sid}")
    assert r1.json()["prepared"] is True
    assert r1.json()["meta"]["characterCount"] == 3


# -- 一次 melt 多次查询（三/四） ---------------------------------------------
def test_no_re_melt_across_requests(client, tmp_path):
    c, adapter, reg, _s = client
    sid = _register(tmp_path, reg)
    c.get(f"/api/saves/{sid}/characters", params={"limit": 50})
    c.get(f"/api/saves/{sid}/characters", params={"limit": 10, "offset": 1})
    c.get(f"/api/saves/{sid}/characters/1")
    c.get(f"/api/saves/{sid}/characters/2")
    assert adapter.prepare_calls == 1  # 整个会话只 melt 一次


def test_pagination_limit_cap_and_has_more(client, tmp_path):
    c, _a, reg, _s = client
    sid = _register(tmp_path, reg)
    r = c.get(f"/api/saves/{sid}/characters", params={"limit": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["hasMore"] is True
    # limit 超过 200 被拒绝（防一次下载全部）
    r2 = c.get(f"/api/saves/{sid}/characters", params={"limit": 100000})
    assert r2.status_code == 422


def test_server_side_filters(client, tmp_path):
    c, _a, reg, _s = client
    sid = _register(tmp_path, reg)
    r = c.get(f"/api/saves/{sid}/characters", params={"rulerOnly": True, "limit": 50})
    assert r.json()["total"] == 1
    r2 = c.get(f"/api/saves/{sid}/characters", params={"aliveOnly": True})
    assert r2.json()["total"] == 2
    r3 = c.get(f"/api/saves/{sid}/characters", params={"q": "bob"})
    assert r3.json()["total"] == 1


def test_profile_endpoint_minimal_credible(client, tmp_path):
    c, _a, reg, _s = client
    sid = _register(tmp_path, reg)
    r = c.get(f"/api/saves/{sid}/characters/1")
    assert r.status_code == 200
    p = r.json()
    assert p["id"] == "1"
    assert len(p["timeline"]) >= 1  # 至少出生事件
    assert p["timeline"][0]["evidence"]  # 带证据
    assert any(w["code"] == "unresolved_faith" for w in p["evidenceWarnings"])
    # 关系字段带来源路径
    assert p["children"][0]["sourcePath"] == "character/1/child/2"


# -- 文件写入中（二） --------------------------------------------------------
def test_still_writing_returns_409(client, tmp_path, monkeypatch):
    monkeypatch.setattr(save_registry, "wait_until_stable", lambda *a, **k: False)
    c, _a, reg, _s = client
    sid = _register(tmp_path, reg)
    r = c.get(f"/api/saves/{sid}/characters", params={"limit": 1})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "save_still_writing"


# -- 安全导入（九） ----------------------------------------------------------
def test_import_rejects_path_traversal(client):
    c, _a, _r, _s = client
    r = c.post("/api/local-saves/import", files={"file": ("../../evil.ck3", b"SAV0101data")})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_filename"


def test_safe_import_filename_unit():
    """文件名校验的服务端防御（单元级）。

    注意：Starlette 的 multipart 解析器在到达处理函数**之前**就会把
    "C:\\Users\\x\\evil.ck3" 截成基名 "evil.ck3"，所以反斜杠分支无法用
    TestClient 端到端触发。但服务端仍必须自带这层校验（其他客户端/解析器
    未必会截断），故在此直接对校验函数断言。
    """
    import pytest as _pytest

    from app.routers.saves import _safe_import_filename

    assert _safe_import_filename("my.ck3") == "my.ck3"
    for bad in (
        None,
        "",
        "C:" + chr(92) + "Users" + chr(92) + "evil.ck3",
        "../../evil.ck3",
        "sub/evil.ck3",
        "..",
        "notasave.txt",
        "evil.ck3.exe",
    ):
        with _pytest.raises(ValueError):
            _safe_import_filename(bad)


def test_import_rejects_bad_header(client, tmp_path):
    c, _a, reg, _s = client
    r = c.post("/api/local-saves/import", files={"file": ("ok.ck3", b"NOTAC K3FILE!!")})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_header"


def test_import_ok_unique_name(client, tmp_path):
    c, _a, reg, _s = client
    r = c.post("/api/local-saves/import", files={"file": ("my.ck3", b"SAV0101" + b"\x00" * 10)})
    assert r.status_code == 200
    assert r.json()["status"] == "imported"
    assert r.json()["saveId"]
    # 同名再次导入 → 唯一文件名，不覆盖
    r2 = c.post("/api/local-saves/import", files={"file": ("my.ck3", b"SAV0101" + b"\x00" * 5)})
    assert r2.status_code == 200
    assert r2.json()["saveId"] != r.json()["saveId"]


def test_import_rejects_oversize(client, tmp_path, monkeypatch):
    monkeypatch.setattr(saves, "MAX_UPLOAD_BYTES", 10)
    c, _a, reg, _s = client
    r = c.post("/api/local-saves/import", files={"file": ("big.ck3", b"SAV0101" + b"\x00" * 100)})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "too_large"


# -- 监听事件无路径 + 游标（八） ---------------------------------------------
def test_watch_events_no_path_and_cursor(client, tmp_path, monkeypatch):
    monkeypatch.setattr(saves, "resolve_default_saves_dir", lambda: str(tmp_path))
    c, _a, reg, _s = client
    r = c.post("/api/local-saves/watch/start", params={"interval": 0.05})
    assert r.json()["running"] is True
    (tmp_path / "autosave.ck3").write_bytes(b"SAV0101" + b"\x00" * 20)
    import time

    time.sleep(0.3)
    st = c.get("/api/local-saves/watch/status").json()
    assert st["running"] is True
    assert st["lastEventId"] is not None
    assert len(st["recent_events"]) >= 1
    ev = st["recent_events"][-1]
    # 事件不含完整本地路径
    assert "path" not in ev
    assert set(ev.keys()) >= {"eventId", "type", "saveId", "fileName", "timestamp"}
    c.post("/api/local-saves/watch/stop")


# -- CORS 默认仅 localhost（十二） -------------------------------------------
def test_cors_blocks_non_localhost(client):
    c, _a, _r, _s = client
    r = c.get("/api/health", headers={"Origin": "http://evil.com"})
    assert r.headers.get("access-control-allow-origin") is None


def test_cors_allows_localhost(client):
    c, _a, _r, _s = client
    r = c.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


# -- 监听状态增量游标（八） -----------------------------------------------
def test_watch_status_supports_since_event_id(client):
    c, _a, _reg, _s = client
    saves._watcher_events.clear()
    saves._last_event_id = None
    for i in range(3):
        eid = f"evt-{i}"
        saves._watcher_events.append(
            {
                "eventId": eid,
                "seq": i + 1,
                "type": "added",
                "saveId": f"s{i}",
                "fileName": f"a{i}.ck3",
                "timestamp": "t",
            }
        )
        saves._last_event_id = eid
    # 无游标：返回全部近期事件
    r = c.get("/api/local-saves/watch/status")
    assert r.status_code == 200
    assert len(r.json()["recent_events"]) == 3
    # since=evt-0：仅返回其后的 evt-1、evt-2
    r2 = c.get("/api/local-saves/watch/status?sinceEventId=evt-0")
    evs = r2.json()["recent_events"]
    assert [e["eventId"] for e in evs] == ["evt-1", "evt-2"]
    assert r2.json()["lastEventId"] == "evt-2"
    # 未知游标：回退为返回全部近期事件（前端以 lastEventId 重新对齐）
    r3 = c.get("/api/local-saves/watch/status?sinceEventId=does-not-exist")
    assert len(r3.json()["recent_events"]) == 3


# -- Mod API 路径脱敏（六） --------------------------------------------------
def test_mods_endpoint_redacts_paths_by_default(client, tmp_path, monkeypatch):
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()
    (mods_dir / "ugc_1.mod").write_text(
        'name="Mod One"\npath="mod/ugc_1"\nremote_file_id="1"\n', encoding="utf-8"
    )
    monkeypatch.setattr(
        saves,
        "effective_paths",
        lambda: {"mods_dir": str(mods_dir), "saves_dir": None, "game_dir": None},
    )
    c, _a, _reg, _s = client
    # 导入端点注册一个存档（FakeAdapter 提供 meta）
    r = c.post("/api/local-saves/import", files={"file": ("save.ck3", b"SAV0101" + b"\x00" * 5)})
    assert r.status_code == 200
    sid = r.json()["saveId"]
    # 默认脱敏：descriptor_path 只有基名，无路径分隔符
    r2 = c.get(f"/api/local-saves/{sid}/mods")
    assert r2.status_code == 200
    first = next(m for m in r2.json()["report"]["required"] if m["mod_id"] == "ugc_1")
    assert first["descriptor_path"] == "ugc_1.mod"
    assert "\\" not in first["descriptor_path"] and "/" not in first["descriptor_path"]
    # 调试可用 full_paths=true 取完整路径
    r3 = c.get(f"/api/local-saves/{sid}/mods?full_paths=true")
    first3 = next(m for m in r3.json()["report"]["required"] if m["mod_id"] == "ugc_1")
    assert first3["descriptor_path"] == str(mods_dir / "ugc_1.mod")


# -- 空导入文件 → 400 empty_file + 清理半成品（七） -------------------------
def test_import_empty_file_returns_empty_file_and_cleans_up(client, tmp_path, monkeypatch):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    monkeypatch.setattr(saves, "INCOMING_ROOT", incoming)
    c, _a, _reg, _s = client
    r = c.post("/api/local-saves/import", files={"file": ("empty.ck3", b"")})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "empty_file"
    # 半成品已删除：incoming 目录不应残留任何 .ck3
    assert list(incoming.glob("*.ck3")) == []


def test_critical_routes_registered():
    """路由注册表防护：关键端点必须真实挂载（防装饰器被误删导致 404）。

    历史教训：M2（3214461）编辑 entities 端点时误删了 parse 的
    @router.post 装饰器，POST /local-saves/{id}/parse 在 HEAD 上返回
    FastAPI 默认 404，因真实集成测试在无 reader 环境整体跳过而未暴露，
    直到 M3 真实集成测试才抓到。此测试不依赖 reader/存档，CI 必跑。
    """
    paths = {
        "/api/health": {"GET"},
        "/api/local-saves": {"GET"},
        "/api/settings/paths": {"GET", "PUT"},
        "/api/local-saves/import": {"POST"},
        "/api/local-saves/{save_id}/inspect": {"GET"},
        "/api/local-saves/{save_id}/mods": {"GET"},
        "/api/local-saves/{save_id}/parse": {"POST"},
        "/api/local-saves/{save_id}/entities": {"GET"},
        "/api/local-saves/{save_id}/characters/{character_id}/titles": {"GET"},
        "/api/saves/{save_id}": {"GET", "DELETE"},
        "/api/saves/{save_id}/characters": {"GET"},
        "/api/saves/{save_id}/characters/{character_id}": {"GET"},
    }
    registered: dict[str, set[str]] = {}
    for route in app.routes:
        if type(route).__name__ == "_IncludedRouter":
            # FastAPI 新版把 include_router 封装为 _IncludedRouter，子路由在
            # original_router.routes 且 path 不含 prefix（prefix 在 include_context）。
            prefix = route.include_context.prefix or ""
            for sub in route.original_router.routes:
                path = prefix + getattr(sub, "path", "")
                if path.startswith("/api/"):
                    methods = set(getattr(sub, "methods", set()) or set())
                    registered.setdefault(path, set()).update(methods)
        else:
            # FastAPI 0.136+ 直接把 include_router 的子路由拍平为 APIRoute，
            # 同 path 的 GET/PUT（settings/paths）、GET/DELETE（saves/{id}）
            # 是两条独立路由：这里必须合并方法集，不能覆盖，否则会漏报。
            path = getattr(route, "path", "")
            if path.startswith("/api/"):
                methods = set(getattr(route, "methods", set()) or set())
                registered.setdefault(path, set()).update(methods)
    missing = []
    for path, expected in paths.items():
        methods = registered.get(path)
        if methods is None:
            missing.append(f"{path} 未注册")
        elif not expected.issubset(methods):
            missing.append(f"{path} 缺方法 {expected - methods}（现有 {methods}）")
    assert missing == [], "关键路由缺失：\n" + "\n".join(missing)


# -- M3 头衔与统治经历（列表摘要 / 档案 / titles 端点） -------------------------
def test_list_summary_merges_title_bits(client, tmp_path):
    """M3：人物列表摘要带 primaryTitle / highestTitleTier / isRuler（由 titles.json 反解）。"""
    c, _a, reg, _s = client
    sid = _register(tmp_path, reg)
    r = c.get(f"/api/saves/{sid}/characters", params={"limit": 100})
    items = {it["id"]: it for it in r.json()["items"]}
    alice = items["1"]
    assert alice["primaryTitle"]["id"] == "d_alpha"
    assert alice["primaryTitle"]["name"] == "阿尔法公国"
    assert alice["highestTitleTier"] == "duchy"
    assert alice["isRuler"] is True
    bob = items["2"]
    assert bob["primaryTitle"] is None
    assert bob["isRuler"] is False  # 仅有历史任期，非现任


def test_ruler_only_filter_uses_title_holders(client, tmp_path):
    """M3：rulerOnly 以 landed_titles 现任持有者为权威（Alice 是，Bob/Carol 不是）。"""
    c, _a, reg, _s = client
    sid = _register(tmp_path, reg)
    r = c.get(f"/api/saves/{sid}/characters", params={"rulerOnly": True})
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == "1"


def test_profile_includes_titles_and_title_events(client, tmp_path):
    """M3：人物档案含 titles[]（现任 + 历史任期）与 title_gain/loss 时间线事件。"""
    c, _a, reg, _s = client
    sid = _register(tmp_path, reg)
    r = c.get(f"/api/saves/{sid}/characters/1")
    assert r.status_code == 200
    p = r.json()
    titles = {t["titleId"]: t for t in p["titles"]}
    alpha = titles["d_alpha"]
    assert alpha["isCurrent"] is True
    assert alpha["start"] == "780.5.10"
    assert alpha["end"] is None
    assert alpha["sourcePath"] == "landed_titles/d_alpha"
    # 现任主头衔任期起点 → succession（inferred）事件
    kinds = {e["type"] for e in p["timeline"]}
    assert "title_gain" in kinds
    assert "succession" in kinds
    for e in p["timeline"]:
        if e["type"].startswith("title_"):
            assert e["evidence"], f"事件 {e['id']} 缺 EvidenceRef"


def test_titles_endpoint_returns_periods(client, tmp_path):
    """M3：/titles 端点返回契约 TitlePeriod[]，warnings 含扫描告警 + 头衔告警。"""
    c, _a, reg, _s = client
    sid = _register(tmp_path, reg)
    r = c.get(f"/api/local-saves/{sid}/characters/2/titles")
    assert r.status_code == 200
    body = r.json()
    assert body["characterId"] == "2"
    assert body["titles"]  # 曾持 c_beta
    beta = [t for t in body["titles"] if t["titleId"] == "c_beta"][0]
    assert beta["start"] == "770.2.2"
    assert beta["end"] == "790.3.3"
    assert beta["isCurrent"] is False
    # 不存在人物 → 空列表（不 404）
    r2 = c.get(f"/api/local-saves/{sid}/characters/999999/titles")
    assert r2.status_code == 200
    assert r2.json()["titles"] == []


def test_title_paths_do_not_leak_local_paths(client, tmp_path):
    """M3 安全：titles / profile 响应中的 sourcePath 不含本地绝对路径（盘符/反斜杠）。"""
    c, _a, reg, _s = client
    sid = _register(tmp_path, reg)
    for url in (
        f"/api/local-saves/{sid}/characters/1/titles",
        f"/api/saves/{sid}/characters/1",
    ):
        r = c.get(url)
        assert r.status_code == 200
        data = r.json()
        for value in _walk_strings(data):
            if "Path" in value or "path" in value or value.startswith("landed_titles"):
                assert "\\" not in value, f"响应泄露本地路径片段: {value}"
                assert not value[:2].replace(":", "").isalnum() or ":" not in value[:2], (
                    f"响应含盘符前缀: {value}"
                )


def _walk_strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)
    elif isinstance(obj, str):
        yield obj
