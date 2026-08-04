"""Phase 3A 路由集成测试：/api/llm/health + 传记提纲生成 API + SQLite 记录。

全部使用 FakeLlmProvider 家族（CI 禁止访问真实模型服务）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import llm, saves
from app.services import save_registry
from app.services.game_data_resolver import GameDataResolver
from app.services.outline_store import OutlineStore
from app.services.save_registry import SaveRegistry
from app.services.session_manager import SessionManager

from biography_engine.providers.base import ProviderNotConfiguredError
from biography_engine.providers.fake import FakeLlmProvider

from test_routing_api import FakeAdapter


class EchoOutlineProvider(FakeLlmProvider):
    """从 user_prompt 的事件 id 列表确定性构建合法提纲（每事件一章，按时间序）。

    事件列表在 prompt 中按日期升序（compressor 保证）→ 章节自然满足时间顺序约束。
    """

    def generate_json(self, **kw) -> dict:
        ids = re.findall(r"\[([a-zA-Z0-9_.-]+)\]", kw["user_prompt"])
        chapters = [
            {
                "id": f"c{i}",
                "title": f"章 {i}",
                "summary": f"概述 {i}",
                "eventIds": [eid],
            }
            for i, eid in enumerate(ids, 1)
        ]
        m = re.search(r"id=([a-zA-Z0-9_.-]+)", kw["user_prompt"])
        return {
            "profileId": m.group(1) if m else "p1",
            "style": "serious_biography",
            "chapters": chapters,
        }


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
    # Phase 3A：测试隔离 —— 独立 SQLite 记录库 + 默认脚本化 Fake provider。
    store = OutlineStore(tmp_path / "outlines.sqlite")
    monkeypatch.setattr(saves, "outline_store", lambda: store)
    monkeypatch.setattr(saves, "build_provider", lambda: FakeLlmProvider())
    monkeypatch.setattr(llm, "build_provider", lambda cfg: FakeLlmProvider())
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    with TestClient(app) as c:
        yield c, adapter, reg, sm, store, monkeypatch


def _register(tmp_path, reg, name="autosave.ck3", data=b"SAV0101" + b"\x00" * 20):
    f = tmp_path / name
    f.write_bytes(data)
    return reg.register(str(f)).save_id


def _use_echo_provider(monkeypatch):
    monkeypatch.setattr(saves, "build_provider", lambda: EchoOutlineProvider())


# -- /api/llm/health（5.3） ----------------------------------------------------
def test_llm_health_fake_configured(client):
    c, *_rest = client
    r = c.get("/api/llm/health")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["provider"] == "fake"
    assert body["reachable"] is True
    # 绝不泄漏密钥字段。
    assert "api_key" not in body and "apiKey" not in body


def test_llm_health_unknown_provider(client, monkeypatch):
    c, *_rest = client
    monkeypatch.setenv("LLM_PROVIDER", "no_such_provider")

    def _raise(_cfg):
        raise ProviderNotConfiguredError("未知 LLM_PROVIDER")

    monkeypatch.setattr(llm, "build_provider", _raise)
    r = c.get("/api/llm/health")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["errorCode"] == "provider_not_configured"


def test_llm_health_base_url_redacted(client, monkeypatch):
    """baseUrlRedacted 只暴露 scheme://host:port，不带路径/密钥。"""
    c, *_rest = client
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8080/v1/secret")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "2")

    def _make(_cfg):
        # 真正走 OpenAICompatibleProvider（不连网：本地地址无监听 → 快速拒连）。
        import biography_engine.providers.factory as factory

        return factory.build_provider(_cfg)

    monkeypatch.setattr(llm, "build_provider", _make)
    r = c.get("/api/llm/health")
    body = r.json()
    assert body["configured"] is True
    assert body["provider"] == "openai_compatible"
    assert body["baseUrlRedacted"] == "http://127.0.0.1:8080"
    assert "/v1/secret" not in body["baseUrlRedacted"]


# -- POST /biography/outline（5.9/5.10） --------------------------------------
def test_outline_generate_success(client, tmp_path):
    c, _a, reg, _s, _store, monkeypatch = client
    sid = _register(tmp_path, reg)
    _use_echo_provider(monkeypatch)
    r = c.post(
        f"/api/local-saves/{sid}/characters/1/biography/outline",
        json={"style": "serious_biography"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert "error" not in body or body["error"] is None
    assert body["recordId"] >= 1
    assert body["outline"]["profileId"] == "1"
    assert len(body["outline"]["chapters"]) >= 1
    # 每章 eventIds 来自压缩事件白名单。
    allowed = {e["eventId"] for e in body["compressed"]["selectedEvents"]}
    for ch in body["outline"]["chapters"]:
        assert set(ch["eventIds"]) <= allowed
    # 记录已写入 SQLite。
    rec = _store.get_generation(body["recordId"])
    assert rec is not None
    assert rec["status"] == "success"
    assert rec["stale"] is False


def test_outline_generate_not_configured(client, tmp_path, monkeypatch):
    """未配置模型 → 结构化错误且记录 status=error（绝不伪造成功）。"""
    c, _a, reg, _s, _store, _mp = client
    sid = _register(tmp_path, reg)

    def _raise():
        raise ProviderNotConfiguredError()

    monkeypatch.setattr(saves, "build_provider", lambda: _raise())
    r = c.post(
        f"/api/local-saves/{sid}/characters/1/biography/outline",
        json={"style": "serious_biography"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert body["error"]["code"] == "provider_not_configured"
    rec = _store.get_generation(body["recordId"])
    assert rec["status"] == "error"
    assert rec["error_code"] == "provider_not_configured"


def test_outline_generate_provider_error_recorded(client, tmp_path, monkeypatch):
    """Provider 运行时错误 → valid False + 记录 error。"""
    c, _a, reg, _s, _store, _mp = client
    sid = _register(tmp_path, reg)
    monkeypatch.setattr(
        saves,
        "build_provider",
        lambda: FakeLlmProvider(script=[{"unreachable": True}]),
    )
    r = c.post(
        f"/api/local-saves/{sid}/characters/1/biography/outline",
        json={"style": "serious_biography"},
    )
    body = r.json()
    assert body["valid"] is False
    assert body["error"]["code"] == "provider_unreachable"
    assert _store.get_generation(body["recordId"])["status"] == "error"


def test_outline_invalid_style_400(client, tmp_path):
    c, _a, reg, _s, _store, _mp = client
    sid = _register(tmp_path, reg)
    r = c.post(
        f"/api/local-saves/{sid}/characters/1/biography/outline",
        json={"style": "not_a_style"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_style"


def test_outline_unknown_character_404(client, tmp_path):
    c, _a, reg, _s, _store, _mp = client
    sid = _register(tmp_path, reg)
    r = c.post(
        f"/api/local-saves/{sid}/characters/99999/biography/outline",
        json={"style": "serious_biography"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "character_not_found"


def test_outlines_list_and_stale(client, tmp_path):
    """生成记录列表：签名变化（存档更新）→ 旧记录标记 stale。"""
    c, _a, reg, _s, store, monkeypatch = client
    sid = _register(tmp_path, reg)
    _use_echo_provider(monkeypatch)
    r = c.post(
        f"/api/local-saves/{sid}/characters/1/biography/outline",
        json={"style": "serious_biography"},
    )
    rid = r.json()["recordId"]
    r2 = c.get(f"/api/local-saves/{sid}/characters/1/biography/outlines")
    assert r2.status_code == 200
    records = r2.json()["records"]
    assert len(records) == 1
    assert records[0]["id"] == rid
    assert records[0]["stale"] is False
    # 模拟存档更新：同一路径文件内容变大 → signature 变化 → 重新 parse。
    f = tmp_path / "autosave.ck3"
    f.write_bytes(b"SAV0101" + b"\x00" * 25)  # 不同 size → 不同 signature
    reg.ensure_staged(sid)
    r3 = c.get(f"/api/local-saves/{sid}/characters/1/biography/outlines")
    records = r3.json()["records"]
    assert records[0]["id"] == rid
    assert records[0]["stale"] is True


def test_outline_response_never_leaks_sensitive(client, tmp_path, monkeypatch):
    """响应不含：API Key、本地绝对路径、完整 prompt、原始存档内容。"""
    c, _a, reg, _s, store, _mp = client
    sid = _register(tmp_path, reg)
    _use_echo_provider(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "sk-super-secret-12345")
    r = c.post(
        f"/api/local-saves/{sid}/characters/1/biography/outline",
        json={"style": "serious_biography"},
    )
    text = r.text
    assert "sk-super-secret-12345" not in text
    assert "tmp" not in text or "staging" not in text  # 不泄漏 staging 路径细节
    assert "user_prompt" not in text and "system_prompt" not in text
