"""存档解析 API（对齐 Phase 2A 规范九）。

端点（纵向链路：发现 → 初检 → Mod → 解析 → 人物列表 → 人物档案 → 游戏数据）：
  GET  /api/health                                 健康检查（reader / 游戏目录可用性）
  GET  /api/settings/paths                        当前生效目录设置（仅展示，无密钥）
  PUT  /api/settings/paths                        保存自定义目录（校验存在）
  GET  /api/local-saves                           列出本机存档（saveId + 文件名，不含本地全路径）
  POST /api/local-saves/rescan                    重新扫描
  POST /api/local-saves/watch/start               开始监听存档目录
  POST /api/local-saves/watch/stop                停止监听
  GET  /api/local-saves/{saveId}/inspect          单存档初检（meta + mods + 计数）
  GET  /api/local-saves/{saveId}/mods             Mod 兼容性报告
  POST /api/local-saves/{saveId}/parse            完整解析（复制稳定副本后 melt）
  GET  /api/saves/{saveId}/characters             分页人物摘要
  GET  /api/saves/{saveId}/characters/{cid}       单人物档案
  DELETE /api/saves/{saveId}                       移除登记并清理副本

安全：前端只收到 saveId + 文件名 + 展示别名；原始全路径仅存于服务端 SaveRegistry。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.adapters.ck3_reader_adapter import (
    Ck3ReaderAdapter,
    ReaderExecutionError,
    ReaderMissingError,
)
from app.adapters.protocol import inspect_save
from app.config import STAGING_ROOT, resolve_default_saves_dir, resolve_game_dir
from app.services.character_extractor import to_profile, to_summary
from app.services.directory_watcher import DirectoryWatcher
from app.services.game_data_resolver import GameDataResolver
from app.services.local_save_discovery import LocalSaveDiscoveryService
from app.services.localization import LocalizationLoader
from app.services.mod_resolver import ModResolver, read_launcher_playset
from app.services.save_registry import SaveRegistry, wait_until_stable
from app.services.settings_store import effective_paths, load_settings, save_settings

router = APIRouter()

_registry = SaveRegistry(STAGING_ROOT)
_watcher: DirectoryWatcher | None = None
_watcher_events: list[dict] = []
_loc_cache: dict[str, LocalizationLoader] = {}


# -- 辅助 ---------------------------------------------------------------------
def _discovery_service() -> LocalSaveDiscoveryService:
    paths = effective_paths()
    saves_dir = paths.get("saves_dir")
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
    # 未显式配置时回退到默认用户 Mod 目录（Documents/.../mod）
    return ModResolver()


def _on_watch_change(added, removed, changed) -> None:
    for s in added:
        _watcher_events.append({"type": "added", "name": s.name, "path": s.path})
    for s in removed:
        _watcher_events.append({"type": "removed", "name": s.name, "path": s.path})
    for s in changed:
        _watcher_events.append({"type": "changed", "name": s.name, "path": s.path})
    del _watcher_events[:-50]


def _build_localization(save_id: str, mod_descriptors: list[str]) -> LocalizationLoader:
    if save_id in _loc_cache:
        return _loc_cache[save_id]
    paths = effective_paths()
    resolver = _game_resolver()
    loader = resolver.build_localization(mod_descriptors, paths.get("mods_dir"))
    _loc_cache[save_id] = loader
    return loader


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
                "status": "available",
                "gameVersion": None,
                "date": None,
                "modCount": None,
                "lastParseStatus": rec.last_parse_status,
            }
        )
    return out


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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    """手动导入一个 .ck3 文件（备用入口，非主流程）。

    文件先落到受控传入目录（data/staging/incoming），再登记为 saveId。
    原上传文件只经此副本，绝不外传。
    """
    if not file.filename or not file.filename.lower().endswith(".ck3"):
        raise HTTPException(status_code=400, detail="仅支持 .ck3 文件。")
    incoming = STAGING_ROOT / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    dest = incoming / file.filename
    data = await file.read()
    dest.write_bytes(data)
    rec = _registry.register(dest)
    return {
        "saveId": rec.save_id,
        "fileName": rec.file_name,
        "sizeBytes": rec.size_bytes,
        "status": "imported",
    }


# -- 目录监听 -----------------------------------------------------------------
@router.post("/local-saves/watch/start")
def watch_start(interval: float = 2.0):
    global _watcher
    svc = _discovery_service()
    if not svc.is_available():
        raise HTTPException(status_code=400, detail="存档目录不可用，无法开始监听。")
    if _watcher is not None and _watcher._thread is not None and _watcher._thread.is_alive():
        return {"running": True, "directory": str(_watcher.directory), "interval": _watcher.interval}
    eff = interval or float(os.environ.get("SHIGUAN_WATCH_INTERVAL", "2.0"))
    _watcher = DirectoryWatcher(svc.saves_dir, interval=eff, on_change=_on_watch_change)  # type: ignore[arg-type]
    _watcher.start()
    return {"running": True, "directory": str(_watcher.directory), "interval": eff}


@router.post("/local-saves/watch/stop")
def watch_stop():
    global _watcher
    if _watcher is not None:
        _watcher.stop()
    return {"running": False}


@router.get("/local-saves/watch/status")
def watch_status():
    return {
        "running": bool(_watcher and _watcher._thread and _watcher._thread.is_alive()),
        "directory": str(_watcher.directory) if _watcher else None,
        "recent_events": _watcher_events[-20:],
    }


# -- 单存档：初检 / Mod / 解析 ------------------------------------------------
@router.get("/local-saves/{save_id}/inspect")
def inspect_save_endpoint(save_id: str):
    rec = _registry.get(save_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="未知 saveId，请先扫描本地存档。")
    adapter = Ck3ReaderAdapter()
    if not adapter.is_available():
        raise HTTPException(status_code=500, detail="ck3-reader 二进制缺失：请在 tools/ck3-reader 下执行 build.sh。")
    try:
        rec = _registry.ensure_staged(save_id)
        raw = adapter.inspect(rec.staging_path)  # type: ignore[arg-type]
    except (ReaderExecutionError, ReaderMissingError, KeyError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "saveId": save_id,
        "encoding": raw.get("encoding"),
        "save_version": raw.get("save_version"),
        "game_version": raw.get("game_version"),
        "date": raw.get("date"),
        "player_name": raw.get("player_name"),
        "mod_count": raw.get("mod_count"),
        "character_count": raw.get("character_count"),
        "dead_character_count": raw.get("dead_character_count"),
        "unknown_token_count": raw.get("unknown_token_count"),
        "header_parse_ok": raw.get("header_parse_ok"),
    }


@router.get("/local-saves/{save_id}/mods")
def mods_endpoint(save_id: str):
    rec = _registry.get(save_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="未知 saveId，请先扫描本地存档。")
    adapter = Ck3ReaderAdapter()
    if not adapter.is_available():
        raise HTTPException(status_code=500, detail="ck3-reader 二进制缺失：请先构建 tools/ck3-reader。")
    try:
        rec = _registry.ensure_staged(save_id)
        mods_raw = adapter.list_mods(rec.staging_path)  # type: ignore[arg-type]
        raw = adapter.inspect(rec.staging_path)  # type: ignore[arg-type]
    except (ReaderExecutionError, ReaderMissingError, KeyError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    game_version = raw.get("game_version")
    loader = _build_localization(save_id, mods_raw)
    paths = effective_paths()
    playset = None
    if paths.get("saves_dir"):
        lp = Path(paths["saves_dir"]).parent / "launcher-v2.sqlite"
        playset = read_launcher_playset(lp)
    report = _mod_resolver().resolve(mods_raw, game_version, playset)
    return {"saveId": save_id, "report": report.to_dict()}


@router.post("/local-saves/{save_id}/parse")
def parse_save_endpoint(save_id: str):
    rec = _registry.get(save_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="未知 saveId，请先扫描本地存档。")
    adapter = Ck3ReaderAdapter()
    if not adapter.is_available():
        raise HTTPException(status_code=500, detail="ck3-reader 二进制缺失：请先构建 tools/ck3-reader。")
    try:
        rec = _registry.ensure_staged(save_id)
        raw = adapter.inspect(rec.staging_path)  # type: ignore[arg-type]
        mods_raw = adapter.list_mods(rec.staging_path)  # type: ignore[arg-type]
    except (ReaderExecutionError, ReaderMissingError, KeyError) as exc:
        _registry.set_parse_status(save_id, "error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    game_version = raw.get("game_version")
    loader = _build_localization(save_id, mods_raw)
    paths = effective_paths()
    playset = None
    if paths.get("saves_dir"):
        lp = Path(paths["saves_dir"]).parent / "launcher-v2.sqlite"
        playset = read_launcher_playset(lp)
    report = _mod_resolver().resolve(mods_raw, game_version, playset)
    samples = [to_summary(s, loader).model_dump() for s in raw.get("sample_characters", [])]
    game_data = _game_resolver().resolve(game_version)
    _registry.set_parse_status(save_id, "parsed", len(report.required))
    return {
        "saveId": save_id,
        "meta": adapter.to_parsed_meta(raw).model_dump(),
        "player_name": raw.get("player_name"),
        "mod_count": len(report.required),
        "mods": report.to_dict(),
        "character_count": raw.get("character_count"),
        "dead_character_count": raw.get("dead_character_count"),
        "encoding": raw.get("encoding"),
        "unknown_token_count": raw.get("unknown_token_count"),
        "header_parse_ok": raw.get("header_parse_ok"),
        "parse_ms": raw.get("parse_ms"),
        "sample": samples,
        "game_data": game_data,
        "localization": {"loaded_languages": loader.loaded_languages, "entry_count": loader.count()},
    }


# -- 人物索引 / 档案（按需，均对稳定副本操作） --------------------------------
@router.get("/saves/{save_id}/characters")
def list_characters_endpoint(save_id: str, limit: int = 50, offset: int = 0, q: Optional[str] = None):
    rec = _registry.get(save_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="未知 saveId，请先扫描本地存档。")
    adapter = Ck3ReaderAdapter()
    if not adapter.is_available():
        raise HTTPException(status_code=500, detail="ck3-reader 二进制缺失：请先构建 tools/ck3-reader。")
    try:
        rec = _registry.ensure_staged(save_id)
        index = adapter.list_characters(rec.staging_path)  # type: ignore[arg-type]
    except (ReaderExecutionError, ReaderMissingError, KeyError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    # 本地化：若之前解析过则复用缓存，否则按需构建（仅 game 基础，mods 未知时无 mod 覆盖）
    loader = _loc_cache.get(save_id)
    qry = (q or "").strip().lower()
    if qry:
        filtered = [
            s for s in index
            if qry in str(s.get("id", "")).lower() or qry in str(s.get("name", "") or "").lower()
        ]
    else:
        filtered = index
    total = len(filtered)
    start = max(0, min(offset, total))
    end = min(start + limit, total)
    page = filtered[start:end]
    items = [to_summary(s, loader).model_dump() for s in page]
    return {"saveId": save_id, "total": total, "offset": start, "limit": limit, "items": items}


@router.get("/saves/{save_id}/characters/{character_id}")
def character_profile_endpoint(save_id: str, character_id: str):
    rec = _registry.get(save_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="未知 saveId，请先扫描本地存档。")
    adapter = Ck3ReaderAdapter()
    if not adapter.is_available():
        raise HTTPException(status_code=500, detail="ck3-reader 二进制缺失：请先构建 tools/ck3-reader。")
    try:
        rec = _registry.ensure_staged(save_id)
        stub = adapter.get_character(rec.staging_path, character_id)  # type: ignore[arg-type]
    except (ReaderExecutionError, ReaderMissingError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    loader = _loc_cache.get(save_id)
    return to_profile(stub, loader).model_dump()


# -- 清理 ---------------------------------------------------------------------
@router.delete("/saves/{save_id}")
def delete_save_endpoint(save_id: str):
    removed = _registry.remove(save_id)
    _loc_cache.pop(save_id, None)
    return {"saveId": save_id, "removed": removed}
