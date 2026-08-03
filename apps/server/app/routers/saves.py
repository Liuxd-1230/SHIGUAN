"""存档解析 API（Phase 2A.1：稳定副本 + 一次 melt 多次查询 + 真实路由 + 安全）。

端点（纵向链路：发现 → 初检 → Mod → 解析 → 人物列表 → 人物档案 → 游戏数据）：
  GET  /api/health                                 健康检查（reader / 游戏目录可用性）
  GET  /api/settings/paths                        当前生效目录设置（仅展示，无密钥）
  PUT  /api/settings/paths                        保存自定义目录（校验存在）
  GET  /api/local-saves                           列出本机存档（saveId + 文件名，不含本地全路径）
  POST /api/local-saves/rescan                    重新扫描
  POST /api/local-saves/import                    手动导入 .ck3（安全：基名/分块/限流/验头）
  POST /api/local-saves/watch/start               开始监听存档目录
  POST /api/local-saves/watch/stop                停止监听
  GET  /api/local-saves/watch/status              监听事件（eventId/type/saveId/fileName/timestamp，无完整路径）
  GET  /api/local-saves/{saveId}/inspect          单存档初检（meta + token 指标 + 兼容性提示）
  GET  /api/local-saves/{saveId}/mods             Mod 兼容性报告（ResolvedMod 真实资源目录）
  POST /api/local-saves/{saveId}/parse            一次 melt 建立 ParseSession，返回 meta + 样本
  GET  /api/saves/{saveId}                        真实路由恢复：返回存档有效性 + meta（404=过期）
  GET  /api/saves/{saveId}/characters             服务端分页 + 搜索（offset/limit/q/rulerOnly/...）
  GET  /api/saves/{saveId}/characters/{cid}       单人物档案（不重新 melt）
  DELETE /api/saves/{saveId}                       移除登记并清理副本 + 缓存

安全：前端只收到 saveId + 文件名 + 展示别名；原始全路径仅存于服务端 SaveRegistry。
     普通人物/监听 API 绝不返回本地全路径或 staging 目录；不把 traceback 返回前端。
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from pydantic import BaseModel

from app.adapters.ck3_reader_adapter import (
    Ck3ReaderAdapter,
    ReaderExecutionError,
    ReaderMissingError,
)
from app.adapters.protocol import inspect_save
from app.config import (
    CACHE_ROOT,
    INCOMING_ROOT,
    MAX_UPLOAD_BYTES,
    STAGING_ROOT,
    UPLOAD_CHUNK_BYTES,
    redact_path,
    resolve_default_saves_dir,
    resolve_game_dir,
)
from app.services.character_extractor import to_profile, to_summary
from app.services.directory_watcher import DirectoryWatcher
from app.services.game_data_resolver import GameDataResolver
from app.services.local_save_discovery import LocalSaveDiscoveryService
from app.services.localization import LocalizationLoader
from app.services.mod_resolver import ModResolver, read_launcher_playset
from app.services.save_registry import SaveRegistry, SaveStillWritingError
from app.services.session_manager import SessionManager
from app.services.settings_store import effective_paths, load_settings, save_settings

# Phase 2A.1 验证版本（占位 token 表针对此版本反推；新版本出现给兼容性提示）。
VALIDATED_VERSION = "1.19.0.6"

router = APIRouter()

_registry = SaveRegistry(STAGING_ROOT)
_session_manager = SessionManager(CACHE_ROOT)

_watcher: DirectoryWatcher | None = None
# 监听事件：只含 eventId/seq/type/saveId/fileName/timestamp（无完整本地路径）。
_watcher_events: list[dict] = []
_last_event_id: str | None = None
_event_seq: int = 0
_loc_cache: dict[tuple, LocalizationLoader] = {}


# -- 统一错误结构 -------------------------------------------------------------
def _fail(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": {"code": code, "message": message}})


def _safe_import_filename(raw: str | None) -> str:
    """校验并归一化导入文件名。

    - 拒绝缺失文件名。
    - 只取基名（剔除任何路径分隔符）；若原始名含路径分隔符或 '..' 片段 → 拒绝（路径穿越）。
    - 仅允许 .ck3 扩展名。
    返回安全基名；否则抛出 ValueError（由调用方转 400）。
    """
    if not raw:
        raise ValueError("missing_filename")
    safe = Path(raw).name  # 只取基名
    if safe != raw or "/" in raw or "\\" in raw or ".." in safe:
        raise ValueError("invalid_filename")
    if not safe.lower().endswith(".ck3"):
        raise ValueError("bad_extension")
    return safe


# -- 辅助 ---------------------------------------------------------------------
def _discovery_service() -> LocalSaveDiscoveryService:
    paths = effective_paths()
    saves_dir = paths.get("saves_dir") or resolve_default_saves_dir()
    if saves_dir:
        svc = LocalSaveDiscoveryService(saves_dir)
        if svc.is_available():
            return svc
    return LocalSaveDiscoveryService()


def _game_resolver() -> GameDataResolver:
    paths = effective_paths()
    return GameDataResolver(paths.get("game_dir") or resolve_game_dir())


def _mod_resolver() -> ModResolver:
    paths = effective_paths()
    mods_dir = paths.get("mods_dir")
    if mods_dir:
        return ModResolver(mods_dir)
    return ModResolver()


def _save_id_for_path(path: str) -> str:
    import hashlib

    return hashlib.sha1(str(Path(path).resolve()).encode("utf-8", "replace")).hexdigest()[:16]


def _on_watch_change(added, removed, changed) -> None:
    global _last_event_id, _event_seq
    ts = datetime.now(timezone.utc).isoformat()
    for kind, items in (("added", added), ("removed", removed), ("changed", changed)):
        for s in items:
            save_id = _save_id_for_path(s.path)
            event_id = uuid.uuid4().hex
            _event_seq += 1
            _watcher_events.append(
                {
                    "eventId": event_id,
                    "seq": _event_seq,
                    "type": kind,
                    "saveId": save_id,
                    "fileName": s.name,
                    "timestamp": ts,
                }
            )
            _last_event_id = event_id
            # 使旧 staging 与 ParseSession 失效；下次访问会等待稳定后重建（绝不读半成品）。
            try:
                _registry.register(s.path)
                _session_manager.drop_save(save_id)
            except Exception:  # noqa: BLE001
                pass
    del _watcher_events[:-50]


def _build_localization(save_id: str, signature: str, resolved_mods: list) -> LocalizationLoader:
    key = (save_id, signature)
    if key in _loc_cache:
        return _loc_cache[key]
    resolver = _game_resolver()
    loader = resolver.build_localization(resolved_mods=resolved_mods)
    _loc_cache[key] = loader
    return loader


def _ensure_session(save_id: str):
    """确保存档已稳定复制并准备好 ParseSession（一次 melt，多次查询）。

    返回 (SaveRecord, ParseSession)。文件仍写入 → 409；未知 saveId → 404。
    """
    rec = _registry.get(save_id)
    if rec is None:
        raise _fail(404, "unknown_save", "未知 saveId，请先扫描本地存档或确认该存档仍有效。")
    try:
        rec = _registry.ensure_staged(save_id)
    except SaveStillWritingError:
        raise _fail(409, "save_still_writing", "存档仍在写入，暂不可解析，请稍后重试。")
    sig = rec.staged_signature
    sess = _session_manager.get(save_id, sig)
    if sess is None:
        sess = _session_manager.prepare(save_id, sig, rec.staging_path)  # type: ignore[arg-type]
        _registry.set_parse_status(save_id, "parsed")
    return rec, sess


def _descriptors_from_meta(meta: dict) -> list[str]:
    return meta.get("mods", []) or []


def _version_compatibility(game_version: Optional[str]) -> dict:
    if not game_version:
        return {"validated_version": VALIDATED_VERSION, "status": "unknown"}
    if game_version == VALIDATED_VERSION:
        return {"validated_version": VALIDATED_VERSION, "status": "validated"}
    return {
        "validated_version": VALIDATED_VERSION,
        "status": "compatibility_warning",
        "message": f"当前存档版本 {game_version} 与已验证版本 {VALIDATED_VERSION} 不同，占位 token 表可能不完全匹配。",
    }


# -- 健康检查 / 设置 ----------------------------------------------------------
@router.get("/health")
def health():
    adapter = Ck3ReaderAdapter()
    return {
        "status": "ok",
        "reader_available": adapter.is_available(),
        "game_available": _game_resolver().is_available(),
        "saves_dir_available": _discovery_service().is_available(),
    }


@router.get("/settings/paths")
def get_settings():
    paths = effective_paths()
    svc = _discovery_service()
    return {
        "saves_dir": paths.get("saves_dir") or (str(svc.saves_dir) if svc.saves_dir else None),
        "game_dir": paths.get("game_dir") or (str(resolve_game_dir()) if resolve_game_dir() else None),
        "mods_dir": paths.get("mods_dir"),
        # 设置页可展示受控 staging 目录（非用户个人路径）；普通人物/监听 API 不返回。
        "staging_dir": str(STAGING_ROOT),
        "saves_dir_available": svc.is_available(),
    }


class PathsSettings(BaseModel):
    saves_dir: Optional[str] = None
    game_dir: Optional[str] = None
    mods_dir: Optional[str] = None


@router.put("/settings/paths")
def put_settings(req: PathsSettings):
    try:
        saved = save_settings(req.model_dump(exclude_none=True))
    except ValueError as exc:
        raise _fail(400, "invalid_dir", str(exc)) from exc
    _loc_cache.clear()
    return {"saved": saved}


# -- 本地存档发现 -------------------------------------------------------------
@router.get("/local-saves")
def list_local_saves():
    saves = _refresh_local_saves()
    return {"available": _discovery_service().is_available(), "saves": saves}


@router.post("/local-saves/rescan")
def rescan_local_saves():
    return {"available": _discovery_service().is_available(), "saves": _refresh_local_saves()}


@router.post("/local-saves/import")
async def import_local_save(file: UploadFile = File(...)):
    """手动导入一个 .ck3 文件（安全：基名/拒路径穿越/分块流式/限流/验头/清理）。"""
    try:
        safe = _safe_import_filename(file.filename)
    except ValueError as exc:
        code = str(exc)
        message = {
            "missing_filename": "缺少文件名。",
            "invalid_filename": "文件名包含非法路径分隔符或遍历片段。",
            "bad_extension": "仅支持 .ck3 文件。",
        }.get(code, "文件名不合法。")
        raise _fail(400, code, message) from exc

    INCOMING_ROOT.mkdir(parents=True, exist_ok=True)
    unique = f"{Path(safe).stem}_{uuid.uuid4().hex}{Path(safe).suffix}"
    dest = INCOMING_ROOT / unique
    written = 0
    header_checked = False
    try:
        with open(dest, "wb") as fh:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                if not header_checked:
                    if not (
                        chunk[:7] == b"SAV0101"
                        or chunk[:4] == b"PK\x03\x04"
                        or b"PK\x05\x06" in chunk[:65536]
                    ):
                        raise _fail(400, "bad_header", "文件头不是合法的 CK3 存档（需 SAV0101 或 zip 容器）。")
                    header_checked = True
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise _fail(
                        413, "too_large", f"文件超过最大允许体积（{MAX_UPLOAD_BYTES} 字节）。"
                    )
                fh.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise _fail(500, "import_failed", "导入写入失败，已清理临时文件。")

    # 空文件：未写入任何字节 → 400 empty_file，并删除半成品（不登记、不残留）。
    if written == 0:
        dest.unlink(missing_ok=True)
        raise _fail(400, "empty_file", "导入文件为空，已清理临时文件。")

    rec = _registry.register(dest)
    return {
        "saveId": rec.save_id,
        "fileName": rec.file_name,
        "sizeBytes": rec.size_bytes,
        "status": "imported",
    }


def _refresh_local_saves() -> list[dict]:
    svc = _discovery_service()
    out: list[dict] = []
    if not svc.is_available():
        return out
    for f in svc.list_saves():
        rec = _registry.register(f.path)
        out.append(
            {
                "saveId": rec.save_id,
                "fileName": rec.file_name,
                "displayName": rec.display_name,
                "sizeBytes": rec.size_bytes,
                "modifiedAt": datetime.fromtimestamp(rec.modified, tz=timezone.utc).isoformat(),
                "isAutosave": rec.is_autosave,
                "status": rec.last_parse_status,
                "gameVersion": None,
                "date": None,
                "modCount": None,
            }
        )
    return out


# -- 目录监听 -----------------------------------------------------------------
@router.post("/local-saves/watch/start")
def watch_start(interval: float = 2.0):
    global _watcher
    svc = _discovery_service()
    if not svc.is_available():
        raise _fail(400, "saves_dir_unavailable", "存档目录不可用，无法开始监听。")
    if _watcher is not None and _watcher._thread is not None and _watcher._thread.is_alive():
        return {"running": True, "interval": _watcher.interval}
    eff = interval or float(os.environ.get("SHIGUAN_WATCH_INTERVAL", "2.0"))
    _watcher = DirectoryWatcher(svc.saves_dir, interval=eff, on_change=_on_watch_change)  # type: ignore[arg-type]
    _watcher.start()
    return {"running": True, "interval": eff}


@router.post("/local-saves/watch/stop")
def watch_stop():
    global _watcher
    if _watcher is not None:
        _watcher.stop()
    return {"running": False}


@router.get("/local-saves/watch/status")
def watch_status(sinceEventId: Optional[str] = None):
    """返回监听状态与增量事件。

    - 事件只含 eventId/seq/type/saveId/fileName/timestamp（无完整本地路径）。
    - 传入 sinceEventId 仅返回该事件之后的新事件（前端据此游标只处理新事件）。
    - 未知/空的 sinceEventId 回退为返回最近事件。
    """
    events = _watcher_events
    if sinceEventId:
        try:
            idx = next(i for i, e in enumerate(events) if e["eventId"] == sinceEventId)
            events = events[idx + 1 :]
        except StopIteration:
            # 游标未知（如服务端重启已丢弃）：返回全部近期事件，前端以 lastEventId 重新对齐。
            events = events
    return {
        "running": bool(_watcher and _watcher._thread and _watcher._thread.is_alive()),
        "lastEventId": _last_event_id,
        # 事件不含完整本地路径，仅 eventId/seq/type/saveId/fileName/timestamp。
        "recent_events": events[-20:],
    }


# -- 单存档：初检 / Mod / 解析 ------------------------------------------------
@router.get("/local-saves/{save_id}/inspect")
def inspect_save_endpoint(save_id: str):
    _rec, sess = _ensure_session(save_id)
    try:
        meta = _session_manager.meta(sess)
    except (ReaderExecutionError, ReaderMissingError) as exc:
        raise _fail(500, "reader_error", str(exc)) from exc
    game_version = meta.get("game_version")
    return {
        "saveId": save_id,
        "encoding": meta.get("encoding"),
        "save_version": meta.get("save_version"),
        "game_version": game_version,
        "date": meta.get("date"),
        "player_name": meta.get("player_name"),
        "mod_count": meta.get("mod_count"),
        "character_count": meta.get("character_count"),
        "dead_character_count": meta.get("dead_character_count"),
        # 占位表造成的 unknown_token_count=0 不表示“语义已解析”，仅作信息字段保留。
        "unknown_token_count": meta.get("unknown_token_count"),
        "token_metrics": meta.get("token_metrics"),
        "header_parse_ok": meta.get("header_parse_ok"),
        "version_compatibility": _version_compatibility(game_version),
    }


@router.get("/local-saves/{save_id}/mods")
def mods_endpoint(save_id: str, full_paths: bool = Query(False)):
    _rec, sess = _ensure_session(save_id)
    try:
        meta = _session_manager.meta(sess)
    except (ReaderExecutionError, ReaderMissingError) as exc:
        raise _fail(500, "reader_error", str(exc)) from exc
    game_version = meta.get("game_version")
    descriptors = _descriptors_from_meta(meta)
    paths = effective_paths()
    playset = None
    if paths.get("saves_dir"):
        lp = Path(paths["saves_dir"]).parent / "launcher-v2.sqlite"
        playset = read_launcher_playset(lp)
    report = _mod_resolver().resolve(descriptors, game_version, playset)
    loader = _build_localization(save_id, sess.signature, report.required)
    return {
        "saveId": save_id,
        # 默认脱敏：descriptor/content/archive/localization 路径只发基名（文件名），
        # 不默认发送完整绝对路径（隐私/安全）。调试可传 full_paths=true 取完整路径。
        "report": report.to_dict(redact_paths=not full_paths),
        "localization": {"loaded_languages": loader.loaded_languages, "entry_count": loader.count()},
    }


@router.post("/local-saves/{save_id}/parse")
def parse_save_endpoint(save_id: str):
    rec, sess = _ensure_session(save_id)
    try:
        meta = _session_manager.meta(sess)
    except (ReaderExecutionError, ReaderMissingError) as exc:
        _registry.set_parse_status(save_id, "error")
        raise _fail(500, "reader_error", str(exc)) from exc
    game_version = meta.get("game_version")
    descriptors = _descriptors_from_meta(meta)
    report = _mod_resolver().resolve(descriptors, game_version)
    loader = _build_localization(save_id, sess.signature, report.required)
    # 首屏一页样本（服务端分页，不一次下发全部人物）。
    page = _session_manager.list_characters(sess, offset=0, limit=20)
    samples = [to_summary(it, loader).model_dump() for it in page["items"]]
    char_count = int(meta.get("character_count") or 0)
    dead_count = int(meta.get("dead_character_count") or 0)
    # 游戏级数据（game_data）：只放真实可提取、不伪造的字段。
    # 占位 token 表下 faith/dynasty 为数值 id、无头衔/领地地图，必须诚实标注，绝不编造。
    game_data = {
        "save_version": meta.get("save_version"),
        "game_version": game_version,
        "date": meta.get("date"),
        "player_name": meta.get("player_name"),
        # player_id 在占位 token 表下无法从字符索引稳定反推，诚实置空。
        "player_id": None,
        "character_count": char_count,
        "dead_character_count": dead_count,
        "living_character_count": char_count - dead_count,
        "encoding": meta.get("encoding"),
        "header_parse_ok": meta.get("header_parse_ok"),
        "unknown_token_count": meta.get("unknown_token_count"),
        "version_compatibility": _version_compatibility(game_version),
        "parse_ms": meta.get("parse_ms"),
        "token_metrics": meta.get("token_metrics"),
        "caveats": [
            "faith/dynasty 在占位 token 表下为数值 id，无可读名（未接真实 token 表）。",
            "头衔/领地地图当前不可用（占位表下 primary_title 已缺失）。",
        ],
    }
    return {
        "saveId": save_id,
        "meta": {
            "saveVersion": meta.get("save_version"),
            "gameVersion": game_version,
            "date": meta.get("date"),
            "playerId": None,
        },
        "player_name": meta.get("player_name"),
        "mod_count": report.required_count,
        "mods": report.to_dict(),
        "character_count": char_count,
        "dead_character_count": dead_count,
        "encoding": meta.get("encoding"),
        "unknown_token_count": meta.get("unknown_token_count"),
        "token_metrics": meta.get("token_metrics"),
        "header_parse_ok": meta.get("header_parse_ok"),
        "version_compatibility": _version_compatibility(game_version),
        "parse_ms": meta.get("parse_ms"),
        "sample": samples,
        "game_data": game_data,
        "localization": {"loaded_languages": loader.loaded_languages, "entry_count": loader.count()},
    }


# -- 真实路由恢复（URL 中的 saveId） -----------------------------------------
@router.get("/saves/{save_id}")
def save_meta_endpoint(save_id: str):
    rec = _registry.get(save_id)
    if rec is None:
        raise _fail(404, "unknown_save", "该 saveId 已过期或不存在，请返回本地存档列表重新选择。")
    sig = rec.staged_signature
    sess = _session_manager.get(save_id, sig) if sig else None
    body: dict = {
        "saveId": save_id,
        "fileName": rec.file_name,
        "isAutosave": rec.is_autosave,
        "registered": True,
        "prepared": sess is not None,
        "status": rec.last_parse_status,
    }
    if sess is not None:
        try:
            meta = _session_manager.meta(sess)
        except (ReaderExecutionError, ReaderMissingError):
            body["prepared"] = False
            return body
        body["meta"] = {
            "saveVersion": meta.get("save_version"),
            "gameVersion": meta.get("game_version"),
            "date": meta.get("date"),
            "characterCount": meta.get("character_count"),
            "deadCharacterCount": meta.get("dead_character_count"),
            "modCount": meta.get("mod_count"),
        }
        body["version_compatibility"] = _version_compatibility(meta.get("game_version"))
    return body


# -- 人物索引（服务端分页 + 搜索 + 筛选，不重新 melt） -----------------------
@router.get("/saves/{save_id}/characters")
def list_characters_endpoint(
    save_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    q: Optional[str] = None,
    rulerOnly: bool = False,
    aliveOnly: bool = False,
    dynasty: Optional[str] = None,
    title: Optional[str] = None,
    sort: Optional[str] = Query(None, pattern="^(name|birth|id)$"),
):
    _rec, sess = _ensure_session(save_id)
    page = _session_manager.list_characters(
        sess,
        offset=offset,
        limit=limit,
        q=q,
        ruler_only=rulerOnly,
        alive_only=aliveOnly,
        dynasty=dynasty,
        title=title,
        sort=sort,
    )
    loader = _loc_cache.get((save_id, sess.signature))
    items = [to_summary(it, loader).model_dump() for it in page["items"]]
    return {
        "saveId": save_id,
        "total": page["total"],
        "offset": page["offset"],
        "limit": page["limit"],
        "hasMore": page["hasMore"],
        "items": items,
    }


@router.get("/saves/{save_id}/characters/{character_id}")
def character_profile_endpoint(save_id: str, character_id: str):
    _rec, sess = _ensure_session(save_id)
    try:
        stub = _session_manager.get_character(sess, character_id)
    except KeyError:
        raise _fail(404, "character_not_found", f"缓存中未找到人物 id={character_id}")
    except (ReaderExecutionError, ReaderMissingError) as exc:
        raise _fail(500, "reader_error", str(exc)) from exc
    loader = _loc_cache.get((save_id, sess.signature))
    return to_profile(stub, loader).model_dump()


# -- 清理 ---------------------------------------------------------------------
@router.delete("/saves/{save_id}")
def delete_save_endpoint(save_id: str):
    rec = _registry.get(save_id)
    sig = rec.staged_signature if rec else None
    removed = _registry.remove(save_id)
    _session_manager.drop_save(save_id)
    if sig:
        _loc_cache.pop((save_id, sig), None)
    return {"saveId": save_id, "removed": removed}
