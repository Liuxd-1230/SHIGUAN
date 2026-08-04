"""Phase 3B 路由集成测试：异步正文生成 API + SQLite 记录 + 任务进度/取消。

全部使用 FakeLlmProvider 家族（CI 禁止访问真实模型服务）。
POST /biography 返回 jobId，测试轮询 GET /biography/jobs/{id} 直到终态。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import llm, saves
from app.services import save_registry
from app.services.biography_store import BiographyStore
from app.services.game_data_resolver import GameDataResolver
from app.services.outline_store import OutlineStore
from app.services.save_registry import SaveRegistry
from app.services.session_manager import SessionManager

from biography_engine.providers.base import ProviderError
from biography_engine.providers.fake import FakeLlmProvider

from test_outline_api import EchoOutlineProvider
from test_routing_api import FakeAdapter

_EVENT_ID_RE = re.compile(r"\[([a-zA-Z0-9_.-]+)\]")
_CHAPTER_RE = re.compile(r"章节：([a-zA-Z0-9_.-]+)《([^》]*)》")


class EchoBiographyProvider(FakeLlmProvider):
    """从 user_prompt 的本章事件 id 确定性构建合法章节（内容无日期/无风险词）。"""

    def generate_json(self, **kw) -> dict:
        ids = _EVENT_ID_RE.findall(kw["user_prompt"])
        m = _CHAPTER_RE.search(kw["user_prompt"])
        cid = m.group(1) if m else (ids[0] if ids else "c1")
        title = m.group(2) if m else cid
        return {
            "id": cid,
            "title": title,
            # 「据推断」为中性推断措辞：无论本章事件是否为 inferred 都通过规则 9。
            "content": "据推断，本章所载之事皆见于存档，其行迹略如上述。",
            "eventIds": ids,
        }


class BadBiographyProvider(FakeLlmProvider):
    """始终输出含虚构对白的章节 → FactChecker 拦截 → 修复耗尽 → needs_revision。"""

    def generate_json(self, **kw) -> dict:
        ids = _EVENT_ID_RE.findall(kw["user_prompt"])
        m = _CHAPTER_RE.search(kw["user_prompt"])
        cid = m.group(1) if m else (ids[0] if ids else "c1")
        return {
            "id": cid,
            "title": cid,
            "content": "他说：「此战必胜。」",
            "eventIds": ids,
        }


class SlowBiographyProvider(FakeLlmProvider):
    """每次调用先睡 delay 秒（供取消测试留出时间窗）。"""

    def __init__(self, delay: float = 0.4):
        super().__init__(script=[])
        self.delay = delay

    def generate_json(self, **kw) -> dict:
        time.sleep(self.delay)
        raise ProviderError("slow provider 不应走到这里")


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
    monkeypatch.setattr(saves, "_memory_index_cache", {})
    monkeypatch.setattr(saves, "_search_name_cache", {})
    monkeypatch.setattr(saves, "_game_resolver", lambda: GameDataResolver(game_dir="__no_game__"))
    monkeypatch.setattr(saves, "_watcher_events", [])
    monkeypatch.setattr(saves, "_last_event_id", None)
    monkeypatch.setattr(save_registry, "wait_until_stable", lambda *a, **k: True)
    # Phase 3A/3B：独立 SQLite 记录库 + 默认脚本化 Fake provider。
    store = OutlineStore(tmp_path / "outlines.sqlite")
    bstore = BiographyStore(tmp_path / "biographies.sqlite")
    monkeypatch.setattr(saves, "outline_store", lambda: store)
    monkeypatch.setattr(saves, "biography_store", lambda: bstore)
    monkeypatch.setattr(saves, "build_provider", lambda: FakeLlmProvider())
    monkeypatch.setattr(llm, "build_provider", lambda cfg: FakeLlmProvider())
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    with TestClient(app) as c:
        yield c, adapter, reg, sm, store, bstore, monkeypatch


def _register(tmp_path, reg, name="autosave.ck3", data=b"SAV0101" + b"\x00" * 20):
    f = tmp_path / name
    f.write_bytes(data)
    return reg.register(str(f)).save_id


def _outline_id(client, monkeypatch, tmp_path, reg):
    """生成 Alice(1) 的提纲并返回 recordId。"""
    monkeypatch.setattr(saves, "build_provider", lambda: EchoOutlineProvider())
    sid = _register(tmp_path, reg)
    r = client.post(
        f"/api/local-saves/{sid}/characters/1/biography/outline",
        json={"style": "serious_biography"},
    )
    assert r.status_code == 200
    assert r.json()["valid"] is True
    return sid, r.json()["recordId"]


def _poll_job(client, job_id, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/biography/jobs/{job_id}")
        assert r.status_code == 200
        job = r.json()
        if job["status"] in ("completed", "error", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} 未在 {timeout}s 内进入终态")


# -- POST /biography：成功落库 -------------------------------------------------
def test_biography_generate_success(client, monkeypatch, tmp_path):
    c, _a, reg, _s, _store, bstore, monkeypatch = client
    sid, oid = _outline_id(c, monkeypatch, tmp_path, reg)
    monkeypatch.setattr(saves, "build_provider", lambda: EchoBiographyProvider())

    r = c.post(
        f"/api/local-saves/{sid}/characters/1/biography",
        json={"outlineId": oid},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["jobId"]
    assert body["status"] == "pending"

    job = _poll_job(c, body["jobId"])
    assert job["status"] == "completed"
    assert job["recordStatus"] == "completed"
    assert job["totalChapters"] >= 1
    assert job["completedChapters"] == job["totalChapters"]
    assert job["biographyId"]

    rec = bstore.get_biography(job["biographyId"])
    assert rec is not None
    assert rec["status"] == "completed"
    assert rec["biography"] is not None
    assert len(rec["biography"]["chapters"]) == job["totalChapters"]
    assert rec["biography"]["factCheck"]["status"] == "pass"
    assert rec["outline_id"] == oid
    assert rec["revision_count"] == 0


def test_biography_retries_exhausted_needs_revision(client, monkeypatch, tmp_path):
    """正文始终含虚构对白 → 有限修复耗尽 → 记录 status=needs_revision（不伪装成功）。"""
    c, _a, reg, _s, _store, bstore, monkeypatch = client
    sid, oid = _outline_id(c, monkeypatch, tmp_path, reg)
    monkeypatch.setattr(saves, "build_provider", lambda: BadBiographyProvider())

    r = c.post(
        f"/api/local-saves/{sid}/characters/1/biography",
        json={"outlineId": oid},
    )
    job = _poll_job(c, r.json()["jobId"])
    assert job["status"] == "completed"
    assert job["recordStatus"] == "needs_revision"
    assert job["retryCount"] >= 1
    assert job["factCheckIssueCount"] >= 1

    rec = bstore.get_biography(job["biographyId"])
    assert rec["status"] == "needs_revision"
    assert rec["biography"]["factCheck"]["status"] == "needs_revision"
    assert any(
        i["rule"] == "fabricated_dialogue"
        for i in rec["biography"]["factCheck"]["issues"]
    )


def test_biography_provider_unreachable_no_record(client, monkeypatch, tmp_path):
    """模型不可达 → job=error，不保存任何记录（不伪造成功）。"""
    c, _a, reg, _s, _store, bstore, monkeypatch = client
    sid, oid = _outline_id(c, monkeypatch, tmp_path, reg)
    monkeypatch.setattr(saves, "build_provider", lambda: FakeLlmProvider(script=[{"unreachable": True}]))

    r = c.post(
        f"/api/local-saves/{sid}/characters/1/biography",
        json={"outlineId": oid},
    )
    job = _poll_job(c, r.json()["jobId"])
    assert job["status"] == "error"
    assert job["error"]["code"] == "provider_unreachable"
    assert job["biographyId"] is None
    assert bstore.list_biographies(sid, "1") == []


def test_biography_cancel(client, monkeypatch, tmp_path):
    """取消任务：job → cancelled，不保存半成品。"""
    c, _a, reg, _s, _store, bstore, monkeypatch = client
    sid, oid = _outline_id(c, monkeypatch, tmp_path, reg)
    monkeypatch.setattr(saves, "build_provider", lambda: SlowBiographyProvider())

    r = c.post(
        f"/api/local-saves/{sid}/characters/1/biography",
        json={"outlineId": oid},
    )
    job_id = r.json()["jobId"]
    time.sleep(0.05)  # 让任务进入 running
    cancel_r = c.post(f"/api/biography/jobs/{job_id}/cancel")
    assert cancel_r.status_code == 200
    assert cancel_r.json()["cancelled"] is True

    job = _poll_job(c, job_id)
    assert job["status"] == "cancelled"
    assert job["biographyId"] is None
    assert bstore.list_biographies(sid, "1") == []


# -- 参数校验 ------------------------------------------------------------------
def test_biography_outline_not_found_404(client, tmp_path):
    c, _a, reg, _s, _store, _bstore, _mp = client
    sid = _register(tmp_path, reg)
    r = c.post(
        f"/api/local-saves/{sid}/characters/1/biography",
        json={"outlineId": 999999},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "outline_not_found"


def test_biography_outline_stale_400(client, monkeypatch, tmp_path):
    """提纲基于旧签名存档 → 400（需重新生成提纲）。"""
    c, _a, reg, _s, _store, _bstore, monkeypatch = client
    monkeypatch.setattr(saves, "build_provider", lambda: EchoOutlineProvider())
    sid = _register(tmp_path, reg)
    r = c.post(
        f"/api/local-saves/{sid}/characters/1/biography/outline",
        json={"style": "serious_biography"},
    )
    oid = r.json()["recordId"]
    # 模拟存档更新：签名变化 → 旧提纲 stale。
    f = tmp_path / "autosave.ck3"
    f.write_bytes(b"SAV0101" + b"\x00" * 25)
    reg.ensure_staged(sid)
    r2 = c.post(
        f"/api/local-saves/{sid}/characters/1/biography",
        json={"outlineId": oid},
    )
    assert r2.status_code == 400
    assert r2.json()["error"]["code"] == "outline_stale"


def test_biography_unknown_character_404(client, monkeypatch, tmp_path):
    c, _a, reg, _s, _store, _bstore, monkeypatch = client
    monkeypatch.setattr(saves, "build_provider", lambda: EchoOutlineProvider())
    sid, oid = _outline_id(c, monkeypatch, tmp_path, reg)
    r = c.post(
        f"/api/local-saves/{sid}/characters/99999/biography",
        json={"outlineId": oid},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "character_not_found"


# -- job 查询 / 取消 404 --------------------------------------------------------
def test_biography_job_not_found_404(client):
    c, *_rest = client
    assert c.get("/api/biography/jobs/nonexistent").status_code == 404
    assert c.post("/api/biography/jobs/nonexistent/cancel").status_code == 404


# -- 列表与 stale --------------------------------------------------------------
def test_biographies_list_and_stale(client, monkeypatch, tmp_path):
    c, _a, reg, _s, _store, bstore, monkeypatch = client
    sid, oid = _outline_id(c, monkeypatch, tmp_path, reg)
    monkeypatch.setattr(saves, "build_provider", lambda: EchoBiographyProvider())
    r = c.post(
        f"/api/local-saves/{sid}/characters/1/biography",
        json={"outlineId": oid},
    )
    job = _poll_job(c, r.json()["jobId"])
    bid = job["biographyId"]

    r2 = c.get(f"/api/local-saves/{sid}/characters/1/biographies")
    assert r2.status_code == 200
    records = r2.json()["records"]
    assert len(records) == 1
    assert records[0]["id"] == bid
    assert records[0]["stale"] is False
    assert records[0]["biography"] is not None
    assert "save_signature" not in records[0]
    assert "save_id" not in records[0]

    # 模拟存档更新 → 记录 stale。
    f = tmp_path / "autosave.ck3"
    f.write_bytes(b"SAV0101" + b"\x00" * 25)
    reg.ensure_staged(sid)
    r3 = c.get(f"/api/local-saves/{sid}/characters/1/biographies")
    assert r3.json()["records"][0]["stale"] is True


def test_biography_responses_never_leak_sensitive(client, monkeypatch, tmp_path):
    """POST/GET 响应不含：API Key、本地绝对路径、完整 prompt。"""
    c, _a, reg, _s, _store, _bstore, monkeypatch = client
    monkeypatch.setenv("LLM_API_KEY", "sk-super-secret-12345")
    sid, oid = _outline_id(c, monkeypatch, tmp_path, reg)
    monkeypatch.setattr(saves, "build_provider", lambda: EchoBiographyProvider())
    r = c.post(
        f"/api/local-saves/{sid}/characters/1/biography",
        json={"outlineId": oid},
    )
    assert "sk-super-secret-12345" not in r.text
    job = _poll_job(c, r.json()["jobId"])
    for resp in (
        c.get(f"/api/biography/jobs/{job['jobId']}"),
        c.get(f"/api/local-saves/{sid}/characters/1/biographies"),
    ):
        assert "sk-super-secret-12345" not in resp.text
        assert "user_prompt" not in resp.text and "system_prompt" not in resp.text
