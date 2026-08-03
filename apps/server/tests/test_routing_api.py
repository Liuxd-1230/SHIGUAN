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

    def meta(self, cache_dir):
        return json.loads(Path(cache_dir / "meta.json").read_text(encoding="utf-8"))

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
