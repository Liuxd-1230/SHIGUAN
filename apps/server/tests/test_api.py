"""API 集成测试（对齐规范九端点）。

- 列表 / 监听：用临时目录（无需真实存档）。
- inspect / mods / parse / characters：登记真实 autosave 经 SaveRegistry，按需 melt。
  真实存档缺失或 reader 缺失时整体跳过（CI 友好）。
"""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import saves as saves_router

# 真实存档样本不进仓库；用环境变量 SHIGUAN_TEST_SAVE 指向本机真实存档。
# 默认占位路径不存在，CI/无样本环境下测试整体跳过（本地路径（含用户名）不外泄到源码）。
DEFAULT_TEST_SAVE = Path(os.environ.get("SHIGUAN_TEST_SAVE", "fixtures/ck3/autosave.ck3"))
READER = __import__("app.config", fromlist=["resolve_reader_binary"]).resolve_reader_binary()
HAVE_FULL = READER is not None and Path(READER).exists() and DEFAULT_TEST_SAVE.exists()

client = TestClient(app)


@pytest.fixture
def real_save_id():
    if not HAVE_FULL:
        pytest.skip("需要 ck3-reader 与真实存档样本")
    rec = saves_router._registry.register(str(DEFAULT_TEST_SAVE))
    yield rec.save_id
    saves_router._registry.remove(rec.save_id)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_adapter_subprocess_decodes_utf8_explicitly(monkeypatch):
    """回归：ck3-reader 恒输出 UTF-8（含中文玩家名/Mod 名），_run 必须显式
    encoding="utf-8" 解码，否则中文 Windows（GBK 区域）经 subprocess text=True
    缺省解码报 UnicodeDecodeError。pytest 在 Git Bash 有 PYTHONUTF8=1 会掩盖
    此问题（启动器从 PowerShell 启动即暴露），故用 monkeypatch 锁死调用参数。"""
    import subprocess as sp_mod
    import types

    from app.adapters.ck3_reader_adapter import Ck3ReaderAdapter

    captured: dict = {}

    def fake_run(*_args, **_kwargs):
        captured["kwargs"] = _kwargs
        return types.SimpleNamespace(
            returncode=0,
            stdout='{"player_name": "节度使，李瑀", "mod_count": 33}',
            stderr="",
        )

    monkeypatch.setattr(sp_mod, "run", fake_run)
    adapter = Ck3ReaderAdapter()
    out = adapter._run("meta", "some/cache")
    assert captured["kwargs"].get("encoding") == "utf-8", "必须显式 UTF-8 解码 reader 输出"
    assert captured["kwargs"].get("errors") == "replace", "解码失败应以 replace 兜底而非崩溃"
    assert out["player_name"] == "节度使，李瑀"
    assert out["mod_count"] == 33


def test_settings_paths():
    r = client.get("/api/settings/paths")
    assert r.status_code == 200
    assert "saves_dir" in r.json()


def test_settings_put_invalid_dir():
    r = client.put("/api/settings/paths", json={"saves_dir": "C:/no/such/dir/here"})
    assert r.status_code == 400


def test_local_saves_list(tmp_path, monkeypatch):
    (tmp_path / "autosave.ck3").write_bytes(b"SAV0101" + b"\x00" * 20)
    (tmp_path / "manual.ck3").write_bytes(b"SAV0101" + b"\x00" * 10)
    monkeypatch.setenv("SHIGUAN_CK3_SAVES_DIR", str(tmp_path))
    r = client.get("/api/local-saves")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert len(body["saves"]) == 2
    # 前端只拿到 saveId + 文件名，绝不含本地全路径
    s = body["saves"][0]
    assert "saveId" in s and "fileName" in s
    assert "C:/" not in str(s)
    assert "E:/" not in str(s)


def test_local_saves_rescan(tmp_path, monkeypatch):
    (tmp_path / "autosave.ck3").write_bytes(b"SAV0101" + b"\x00" * 20)
    monkeypatch.setenv("SHIGUAN_CK3_SAVES_DIR", str(tmp_path))
    r = client.post("/api/local-saves/rescan")
    assert r.status_code == 200
    assert len(r.json()["saves"]) == 1


def test_watch_start_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIGUAN_CK3_SAVES_DIR", str(tmp_path))
    r = client.post("/api/local-saves/watch/start", params={"interval": 0.1})
    assert r.status_code == 200 and r.json()["running"] is True
    (tmp_path / "autosave.ck3").write_bytes(b"SAV0101" + b"\x00" * 30)
    time_sleep()
    st = client.get("/api/local-saves/watch/status")
    assert st.json()["running"] is True
    sp = client.post("/api/local-saves/watch/stop")
    assert sp.json()["running"] is False


def time_sleep():
    import time

    time.sleep(0.35)


@pytest.mark.skipif(not HAVE_FULL, reason="需要 ck3-reader 与真实存档样本")
def test_inspect(real_save_id):
    r = client.get(f"/api/local-saves/{real_save_id}/inspect")
    assert r.status_code == 200
    b = r.json()
    assert b["encoding"] == "Binary"
    assert b["game_version"] == "1.19.0.6"
    assert b["mod_count"] == 33
    # M1 起 character_count=44096（living 35078 + dead_unprunable 4781 + dead_prunable 4237）。
    assert b["character_count"] == 44096
    assert b["dead_character_count"] == 9018


@pytest.mark.skipif(not HAVE_FULL, reason="需要 ck3-reader 与真实存档样本")
def test_mods_report(real_save_id):
    r = client.get(f"/api/local-saves/{real_save_id}/mods")
    assert r.status_code == 200
    rep = r.json()["report"]
    assert rep["required_count"] == 33
    # 真实安装下大部分 Mod 应能在本地 mod/ 找到（或全部 missing 取决于环境）
    assert "missing_count" in rep and "localization_available" in rep


@pytest.mark.skipif(not HAVE_FULL, reason="需要 ck3-reader 与真实存档样本")
def test_parse_and_characters(real_save_id):
    r = client.post(f"/api/local-saves/{real_save_id}/parse")
    assert r.status_code == 200
    body = r.json()
    assert body["character_count"] == 44096
    assert body["mod_count"] == 33
    assert "game_data" in body
    assert "localization" in body
    # 分页人物摘要
    r2 = client.get(
        "/api/saves/{}/characters".format(real_save_id),
        params={"limit": 10, "offset": 0},
    )
    assert r2.status_code == 200
    page = r2.json()
    assert page["total"] == 44096
    assert len(page["items"]) == 10
    assert page["items"][0]["id"] == "6432"
    # 单人物档案
    cid = page["items"][0]["id"]
    r3 = client.get("/api/saves/{}/characters/{}".format(real_save_id, cid))
    assert r3.status_code == 200
    prof = r3.json()
    assert prof["id"] == cid
    # 文化字段：占位 token 表下为字符串键或 token-id（不崩溃、不伪造）
    assert prof["culture"] is not None


@pytest.mark.skipif(not HAVE_FULL, reason="需要 ck3-reader 与真实存档样本")
def test_character_titles(real_save_id):
    """M3 真实存档集成：titles 端点返回契约 TitlePeriod[]，现任头衔 isCurrent=True。"""
    r = client.post(f"/api/local-saves/{real_save_id}/parse")
    assert r.status_code == 200
    # 教宗国现任持有者 5371（真实存档 k_papal_state holder=5371）
    r2 = client.get(f"/api/local-saves/{real_save_id}/characters/5371/titles")
    assert r2.status_code == 200
    body = r2.json()
    assert body["characterId"] == "5371"
    assert isinstance(body["titles"], list)
    assert len(body["titles"]) > 0
    papal = [t for t in body["titles"] if t["titleId"] == "k_papal_state"]
    assert len(papal) >= 1
    current = [t for t in papal if t.get("isCurrent")]
    assert len(current) == 1
    assert current[0]["name"] == "教宗国"
    assert current[0]["tier"] == "kingdom"
    assert current[0]["start"] == "752.3.22"
    assert current[0]["end"] is None
    # 契约字段齐全
    for t in body["titles"]:
        assert "titleId" in t and "name" in t
    # 不存在的人物 → 空列表（不 404：头衔列表本身可为空）
    r3 = client.get(f"/api/local-saves/{real_save_id}/characters/99999999/titles")
    assert r3.status_code == 200
    assert r3.json()["titles"] == []


@pytest.mark.skipif(not HAVE_FULL, reason="需要 ck3-reader 与真实存档样本")
def test_character_memories(real_save_id):
    """M4 真实存档集成：memories 端点 + 档案记忆/关系 + 婚姻历史语义。"""
    r = client.post(f"/api/local-saves/{real_save_id}/parse")
    assert r.status_code == 200
    # 12659：family_data spouse=9536/43537、former_spouses=[9536]，且有两段 married 记忆。
    r2 = client.get(f"/api/local-saves/{real_save_id}/characters/12659/memories")
    assert r2.status_code == 200
    body = r2.json()
    assert body["characterId"] == "12659"
    assert body["memoryCount"] > 0
    marriage_memories = [m for m in body["memories"] if m["type"] == "marriage"]
    assert marriage_memories, "12659 应有 marriage 记忆（family_data 交叉核对归属）"
    # 记忆总量与跳过类型（imprisoned/ascended_throne 等 owner 非 participant 诚实跳过）。
    assert body["memoryCount"] > 0
    assert body["skippedTypeCount"] > 0
    for m in marriage_memories:
        assert m["relatedCharacters"], "婚姻记忆应能指名对方（spouse 交叉核对）"
        assert m["sourcePath"] and "character_memory_manager" in m["sourcePath"]
    # 档案：spouses 含 former（isFormer=True）+ memories + 关系字段齐全。
    r3 = client.get(f"/api/saves/{real_save_id}/characters/12659")
    assert r3.status_code == 200
    prof = r3.json()
    spouse_ids = {s["characterId"]: s for s in prof["spouses"]}
    # former_spouses=[9536] → isFormer=True；现任 spouse=43537 → isFormer 非 True。
    if "9536" in spouse_ids:
        assert spouse_ids["9536"].get("isFormer") is True
    if "43537" in spouse_ids:
        assert not spouse_ids["43537"].get("isFormer")
    assert prof["spouses"], "spouses 不应为空"
    assert prof["memories"], "memories 不应为空"
    # 所有时间线事件（含记忆事件）都必须带 EvidenceRef（0 事件缺证据）。
    for e in prof["timeline"]:
        assert e["evidence"], f"事件 {e['id']} 缺 EvidenceRef"
    # 关系：became_soulmates 同日期成对 → 6039 与 4927 互为恋人（推断）。
    r4 = client.get(f"/api/local-saves/{real_save_id}/characters/6039/memories")
    assert r4.status_code == 200
    lovers = r4.json()["relationships"]["lovers"]
    assert any(l["id"] == "4927" for l in lovers), f"6039 应有推断恋人 4927，实际 {lovers}"


@pytest.mark.skipif(not HAVE_FULL, reason="需要 ck3-reader 与真实存档样本")
def test_delete_save(real_save_id):
    r = client.delete(f"/api/saves/{real_save_id}")
    assert r.status_code == 200
    assert r.json()["removed"] is True
    # 删除后 inspect 应 404
    r2 = client.get(f"/api/local-saves/{real_save_id}/inspect")
    assert r2.status_code == 404
