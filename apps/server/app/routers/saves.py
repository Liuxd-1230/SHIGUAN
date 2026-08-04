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

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field

from models import BiographyOutline, BiographyStyle

from biography_engine.biography_generator import DEFAULT_MAX_CHAPTER_REPAIR, BiographyGenerator
from biography_engine.chapter_prompts import CHAPTER_PROMPT_VERSION
from biography_engine.models import COMPRESSION_VERSION
from biography_engine.outline_generator import DEFAULT_MAX_REPAIR, OutlineGenerator
from biography_engine.prompt_builder import PROMPT_VERSION
from biography_engine.providers.base import ProviderNotConfiguredError
from biography_engine.providers.factory import build_provider

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
from app.services.biography_jobs import biography_job_manager
from app.services.biography_store import biography_store
from app.services.character_extractor import to_profile, to_summary
from app.services.character_extractor import _build_timeline_and_evidence
from app.services.character_extractor import _dynasty_entity
from app.services.character_extractor import _entity
from app.services.character_extractor import resolve_display_name
from app.services.directory_watcher import DirectoryWatcher
from app.services.game_data_resolver import GameDataResolver
from app.services.game_def_loader import GameDefLoader
from app.services.local_save_discovery import LocalSaveDiscoveryService
from app.services.localization import LocalizationLoader
from app.services.memory_timeline_extractor import MemoryTimelineIndex
from app.services.mod_resolver import ModResolver, read_launcher_playset
from app.services.entity_index_builder import EntityIndexBuilder, ReferenceResolver
from app.services.outline_store import outline_store
from app.services.save_registry import SaveRegistry, SaveStillWritingError
from app.services.session_manager import SessionManager
from app.services.settings_store import effective_paths, load_settings, save_settings
from app.services.title_reign_extractor import TitleProfileIndex, build_title_events
from app.services.timeline_builder import merge_timeline

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
# M3：头衔索引缓存（一次反解 titles.json，列表页/档案页/titles 端点复用）。
# 值：(TitleProfileIndex, scanner_warnings) —— scanner_warnings 为 Rust 扫描告警。
_title_index_cache: dict[tuple[str, str], tuple[TitleProfileIndex, list[str]]] = {}
# M4：记忆索引缓存（一次反解 memories.json，档案页/memories 端点复用）。
# 值：(MemoryTimelineIndex, scanner_warnings)。
_memory_index_cache: dict[tuple[str, str], tuple[MemoryTimelineIndex, list[str]]] = {}
# 实体索引缓存（entities.json → ReferenceResolver）：王朝/文化/信仰数字 id → 可读名。
# 依赖同一 loader（house 名 = 显示姓），随 saveId 失效由 _drop_entity_resolver 清理。
_entity_resolver_cache: dict[tuple[str, str], ReferenceResolver] = {}
# 玩家/关联度排序缓存（meta.player_name 反推玩家 + 直系/同族/统治者 rank）。
# 值：{"player": id|None, "rel1": set[str], "dynasty": str|None}，随 saveId 失效清理。
_relevance_cache: dict[tuple[str, str], dict] = {}


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
                _drop_title_index(save_id)
                _drop_memory_index(save_id)
                _drop_entity_resolver(save_id)
                _drop_relevance(save_id)
                _drop_search_name_cache(save_id)
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


def _title_index(sess, save_id: str) -> tuple[TitleProfileIndex, list[str]]:
    """构建（或复用）该存档的头衔索引：titles.json + 实体索引 + 本地化 → TitleProfileIndex。

    返回 (index, scanner_warnings)。一次反解后按 (save_id, signature) 缓存；
    单人物查询与列表页共享，绝不重复扫描 titles.json，也不重新 melt。
    头衔名解析只依赖 title 实体（loc 键），无需 GameDefLoader，避免每次扫描游戏定义。
    """
    key = (save_id, sess.signature)
    cached = _title_index_cache.get(key)
    if cached is not None:
        return cached
    raw = _session_manager.titles(sess)
    meta = _session_manager.meta(sess)
    game_version = meta.get("game_version")
    descriptors = _descriptors_from_meta(meta)
    report = _mod_resolver().resolve(descriptors, game_version)
    loader = _build_localization(save_id, sess.signature, report.required)
    reference = _entity_resolver(sess, save_id, loader)
    index = TitleProfileIndex(raw, loc=loader, resolver=reference)
    scanner_warnings = list(raw.get("warnings") or [])
    _title_index_cache[key] = (index, scanner_warnings)
    return index, scanner_warnings


def _entity_resolver(sess, save_id: str, loader: LocalizationLoader) -> ReferenceResolver:
    """构建（或复用）该存档的实体引用解析器：entities.json → 数字 id → 可读名。

    解析范围含 dynasty/house/culture/faith/title（house 名即显示姓）。
    一次反解 entities.json 后按 (save_id, signature) 缓存，列表页/档案页/头衔索引共享，
    绝不重复扫描 entities.json。loader 缺失（本地化不可用）时仍可用 raw key 回退。
    """
    key = (save_id, sess.signature)
    cached = _entity_resolver_cache.get(key)
    if cached is not None:
        return cached
    entity_raw = _session_manager.adapter.entities(sess.cache_dir)
    entity_index = EntityIndexBuilder(game_def=None, loc=loader).build(entity_raw)
    reference = ReferenceResolver(entity_index)
    _entity_resolver_cache[key] = reference
    return reference


def _drop_entity_resolver(save_id: str) -> None:
    for k in list(_entity_resolver_cache.keys()):
        if k[0] == save_id:
            del _entity_resolver_cache[k]


def _drop_relevance(save_id: str) -> None:
    for k in list(_relevance_cache.keys()):
        if k[0] == save_id:
            del _relevance_cache[k]


def _player_full_name(sess) -> Optional[str]:
    """由 meta.player_name 提取玩家姓名主体。

    CK3 的 player_name 形如「安南王，梁克贞」（头衔前缀 + 姓名，逗号分隔），
    排序只比较姓名主体 → 取「，」后片段。
    """
    raw = (_session_manager.meta(sess).get("player_name") or "").strip()
    if not raw:
        return None
    if "，" in raw:
        return raw.rsplit("，", 1)[1].strip()
    return raw


def _detect_player(sess, loader, resolver, player_full: str) -> Optional[str]:
    """在人物索引中按「姓+名」反推玩家 id（玩家必为存活统治者）。

    姓取 house 解析（dynn_liang205→梁），名为本地化解码；二者拼接 == player_full
    即命中。优先返回首个存活统治者命中（玩家特性），否则返回任意首个命中。
    resolver 缺失（实体索引不可用）时无法解析姓 → 返回 None（不伪造）。
    """
    if resolver is None:
        return None
    best = None
    for r in sess.records:
        if not r.get("dynasty") or not r.get("name"):
            continue
        house = _dynasty_entity(r.get("dynasty"), loader, resolver)
        if house is None or not house.resolved:
            continue
        given = resolve_display_name(str(r.get("name")), loader)
        if not given:
            continue
        if (house.name or "") + given != player_full:
            continue
        if bool(r.get("alive")) and bool(r.get("ruler")):
            return str(r.get("id"))
        if best is None:
            best = str(r.get("id"))
    return best


def _relevance_ranks(sess, save_id: str, loader, resolver) -> dict:
    """构建（或复用）该存档的玩家/关联度排序信息。

    返回 {"player": id|None, "rel1": set[str], "dynasty": str|None}：
    player 玩家 id；rel1 直系亲属（配偶/子女/父母/妾）id 集合；
    dynasty 玩家 house id（同族 rank 2 判定）。一次反推后按 (save_id, signature)
    缓存，列表页复用，绝不重复扫描人物索引。玩家未检出 → player=None（退回默认顺序）。
    """
    key = (save_id, sess.signature)
    cached = _relevance_cache.get(key)
    if cached is not None:
        return cached
    info: dict = {"player": None, "rel1": set(), "dynasty": None}
    player_full = _player_full_name(sess)
    if player_full and loader is not None:
        pid = _detect_player(sess, loader, resolver, player_full)
        if pid is not None:
            stub = sess.by_id.get(pid) or {}
            info["player"] = pid
            rel1: set[str] = set()
            for k in (
                "spouses",
                "former_spouses",
                "children",
                "concubines",
                "former_concubines",
                "concubinists",
                "former_concubinists",
            ):
                v = stub.get(k)
                if isinstance(v, list):
                    rel1.update(str(x) for x in v if x is not None)
            for k in ("father", "mother", "real_father", "primary_spouse"):
                v = stub.get(k)
                if v is not None:
                    rel1.add(str(v))
            info["rel1"] = rel1
            dyn = stub.get("dynasty")
            if dyn is not None:
                info["dynasty"] = str(dyn)
    _relevance_cache[key] = info
    return info


def _drop_title_index(save_id: str) -> None:
    for k in list(_title_index_cache.keys()):
        if k[0] == save_id:
            del _title_index_cache[k]


def _memory_index(sess, save_id: str) -> tuple[MemoryTimelineIndex, list[str]]:
    """构建（或复用）该存档的记忆索引：memories.json + 人物索引 + 本地化。

    返回 (index, scanner_warnings)。一次反解后按 (save_id, signature) 缓存；
    档案页与 memories 端点共享，绝不重复扫描 memories.json，也不重新 melt。
    人物名解析只依赖人物索引 stub + 本地化表，无需 GameDefLoader。
    """
    key = (save_id, sess.signature)
    cached = _memory_index_cache.get(key)
    if cached is not None:
        return cached
    raw = _session_manager.memories(sess)
    meta = _session_manager.meta(sess)
    game_version = meta.get("game_version")
    descriptors = _descriptors_from_meta(meta)
    report = _mod_resolver().resolve(descriptors, game_version)
    loader = _build_localization(save_id, sess.signature, report.required)
    index = MemoryTimelineIndex(raw, by_id=sess.by_id, loc=loader)
    scanner_warnings = list(raw.get("warnings") or [])
    _memory_index_cache[key] = (index, scanner_warnings)
    return index, scanner_warnings


def _drop_memory_index(save_id: str) -> None:
    for k in list(_memory_index_cache.keys()):
        if k[0] == save_id:
            del _memory_index_cache[k]


def _drop_search_name_cache(save_id: str) -> None:
    """M5：清空该存档的名字解析缓存（settings 变更 / watch 失效 / 删除时调用）。"""
    for k in list(_search_name_cache.keys()):
        if k[0] == save_id:
            del _search_name_cache[k]


def _ensure_loader(sess, save_id: str) -> LocalizationLoader:
    """获取（缓存缺失时构建）该存档的本地化加载器。

    M5 修复：此前端点仅 `_loc_cache.get((save_id, signature))`，服务重启后缓存为
    空且该存档未重新 parse 时 loader=None → 人物名（loc key / 拉丁音译 / 拼音hex）
    完全不翻译、直接显示原始 key。现在缺失时按同 parse 逻辑构建并写入缓存。
    """
    key = (save_id, sess.signature)
    loader = _loc_cache.get(key)
    if loader is not None:
        return loader
    meta = _session_manager.meta(sess)
    game_version = meta.get("game_version")
    descriptors = _descriptors_from_meta(meta)
    report = _mod_resolver().resolve(descriptors, game_version)
    loader = _build_localization(save_id, sess.signature, report.required)
    _loc_cache[key] = loader
    return loader


def _profile_parts(sess, save_id: str, character_id: str, stub: dict):
    """组装单人物档案的 M3 头衔位 + M4 记忆位（供 profile / timeline 端点共用）。

    返回 (loader, title_periods, title_events, title_warnings, memory_index, resolver)。
    索引与 loader 均按 (save_id, signature) 缓存复用，不重复扫描、不重新 melt。
    """
    loader = _ensure_loader(sess, save_id)
    resolver = None
    try:
        resolver = _entity_resolver(sess, save_id, loader)
    except (ReaderExecutionError, ReaderMissingError):
        resolver = None
    title_periods: list = []
    title_events: list = []
    title_warnings: list = []
    try:
        title_index, _ = _title_index(sess, save_id)
    except (ReaderExecutionError, ReaderMissingError):
        title_index = None
    if title_index is not None:
        title_periods = title_index.periods(character_id)
        bits = title_index.primary_bits(character_id)
        name_key = stub.get("name") or ""
        # 与 to_profile 的姓名解析一致（本地化 → 拼音hex 解码 → 原 key），
        # 避免拼音hex 名未命中本地化时 loader.resolve 返回 None，污染头衔描述。
        display_name = resolve_display_name(name_key, loader) if name_key else name_key
        primary_period = None
        if bits.primary is not None:
            primary_period = next(
                (
                    p
                    for p in title_periods
                    if p.isCurrent and p.titleId == bits.primary.id
                ),
                None,
            )
        title_events = build_title_events(
            character_id, display_name, title_periods, primary_period
        )
        title_warnings = title_index.warnings(character_id)
    memory_index = None
    try:
        memory_index, _ = _memory_index(sess, save_id)
    except (ReaderExecutionError, ReaderMissingError):
        memory_index = None
    return loader, title_periods, title_events, title_warnings, memory_index, resolver


def _ensure_session(save_id: str):
    """确保存档已稳定复制并准备好 ParseSession（一次 melt，多次查询）。

    返回 (SaveRecord, ParseSession)。文件仍写入 → 409；未知 saveId → 404。
    读取器执行失败（格式不支持 / melt 失败 / 二进制缺失）→ 统一 500 错误体，
    避免未捕获异常逃逸成无 CORS 头的纯文本 500（浏览器会显示 "Failed to fetch"）。
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
        try:
            sess = _session_manager.prepare(save_id, sig, rec.staging_path)  # type: ignore[arg-type]
        except (ReaderExecutionError, ReaderMissingError) as exc:
            raise _fail(500, "reader_error", str(exc)) from exc
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
    _title_index_cache.clear()
    _memory_index_cache.clear()
    _search_name_cache.clear()
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
                        chunk[:7] in (b"SAV0101", b"SAV0102", b"SAV0103")
                        or chunk[:4] == b"PK\x03\x04"
                        or b"PK\x05\x06" in chunk[:65536]
                    ):
                        raise _fail(
                            400,
                            "bad_header",
                            "文件头不是合法的 CK3 存档（需 SAV0101/SAV0102/SAV0103 或 zip 容器）。",
                        )
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
        # M2.2：明确暴露当前 token 来源与兼容性状态；enum_resolved 才是枚举是否翻译为可读名的真实指标。
        "token_source": meta.get("token_source"),
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


@router.get("/local-saves/{save_id}/entities")
def entities_endpoint(save_id: str):
    """M2 实体索引：合并 entities.json（存档内部键）+ GameDefLoader（游戏定义键）+ LocalizationLoader。

    返回带可读名的 EntityIndex；无法命名的实体 resolved=false、name=原始 id（绝不伪造）。
    游戏目录缺失时 GameDefLoader 优雅降级，def 键实体标 unresolved。
    """
    _rec, sess = _ensure_session(save_id)
    try:
        raw = _session_manager.adapter.entities(sess.cache_dir)
    except (ReaderExecutionError, ReaderMissingError) as exc:
        raise _fail(500, "reader_error", str(exc)) from exc
    meta = _session_manager.meta(sess)
    game_version = meta.get("game_version")
    descriptors = _descriptors_from_meta(meta)
    paths = effective_paths()
    playset = None
    if paths.get("saves_dir"):
        lp = Path(paths["saves_dir"]).parent / "launcher-v2.sqlite"
        playset = read_launcher_playset(lp)
    report = _mod_resolver().resolve(descriptors, game_version, playset)
    loader = _build_localization(save_id, sess.signature, report.required)
    resolver = _game_resolver()
    game_def = GameDefLoader(resolver.game_dir)
    game_def.load()
    index = EntityIndexBuilder(game_def=game_def, loc=loader).build(raw)
    return index.model_dump(mode="json")


@router.get("/local-saves/{save_id}/characters/{character_id}/titles")
def character_titles_endpoint(save_id: str, character_id: str):
    """M3 头衔与统治经历：从 titles.json（landed_titles 反解）聚合单角色 TitlePeriod[]。

    现任头衔 isCurrent=True；过往任职为 history 连续持有段。名字解析：
    存档直书可读名 → 实体索引 → 本地化 → key（不伪造）。无法命名的头衔
    name=key、无 sourcePath 伪造。warnings 含 Rust 扫描告警 + 头衔冲突/推断告警。
    """
    _rec, sess = _ensure_session(save_id)
    try:
        index, scanner_warnings = _title_index(sess, save_id)
    except (ReaderExecutionError, ReaderMissingError) as exc:
        raise _fail(500, "reader_error", str(exc)) from exc
    periods = index.periods(character_id)
    title_warnings = [w.message for w in index.warnings(character_id)]
    return {
        "saveId": save_id,
        "characterId": character_id,
        "titles": [p.model_dump() for p in periods],
        "warnings": scanner_warnings + title_warnings,
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
    # 首屏一页样本（服务端分页，不一次下发全部人物）。M3：附带头衔摘要位。
    page = _session_manager.list_characters(sess, offset=0, limit=20)
    try:
        title_index, _ = _title_index(sess, save_id)
    except (ReaderExecutionError, ReaderMissingError):
        title_index = None
    if title_index is not None:
        samples = [
            to_summary(
                it, loader, title_index.primary_bits(str(it.get("id")))
            ).model_dump()
            for it in page["items"]
        ]
    else:
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
            "头衔归属已由 landed_titles 的 holder/history 反解（M3）；未本地化头衔以 key 展示。",
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
# M5 搜索：名字解析结果缓存（name key → 可读名），避免 44096 人重复 resolve。
# 键为 (save_id, signature, name_key)，随 saveId 失效由 _drop 清理。
_search_name_cache: dict[tuple, str] = {}


def _search_text_resolver(sess, save_id: str, title_index, loader, resolver=None):
    """构造 `(stub) -> str` 搜索文本解析器（解析后名字 + 头衔名 + 关键字段）。

    搜索范围：解析后的中文人名（loc key / 拉丁音译 / 拼音hex 解码）+ 原始名字键
    （便于按拼音搜索）+ 头衔名（current/历史）+ 王朝/文化/信仰的**解析后中文名**
    （如「汉」「景教」）及原始 id（数字可搜）。
    """

    def _name(nk: str) -> str:
        if not nk:
            return ""
        key = (save_id, sess.signature, nk)
        cached = _search_name_cache.get(key)
        if cached is not None:
            return cached
        resolved = resolve_display_name(nk, loader)
        _search_name_cache[key] = resolved
        return resolved

    def _search_text(stub: dict) -> str:
        parts: list[str] = []
        nk = str(stub.get("name") or "")
        if nk:
            parts.append(_name(nk))
            parts.append(nk)  # 原始键（拼音）也可搜索
        # 2C.1：绰号解析名进搜索（nick_the_peaceful → 「仁」）。
        nknick = stub.get("nickname")
        if nknick:
            parts.append(_name(nknick))
            parts.append(str(nknick))
        cid = str(stub.get("id"))
        if title_index is not None:
            for p in title_index.periods(cid):
                if p.name:
                    parts.append(p.name)
                if p.titleId:
                    parts.append(p.titleId)
        for field in ("dynasty", "culture", "faith", "house"):
            v = stub.get(field)
            if v is None:
                continue
            parts.append(str(v))
            if resolver is not None:
                ent = (
                    _dynasty_entity(v, loader, resolver)
                    if field == "dynasty"
                    else _entity(v, field, loader, resolver)
                )
                if ent is not None and ent.name:
                    parts.append(ent.name)
        return " ".join(parts)

    return _search_text


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
    sort: Optional[str] = Query(None, pattern="^(name|birth|id|relevance)$"),
):
    _rec, sess = _ensure_session(save_id)
    try:
        title_index, _ = _title_index(sess, save_id)
    except (ReaderExecutionError, ReaderMissingError):
        title_index = None
    loader = _ensure_loader(sess, save_id)
    try:
        resolver = _entity_resolver(sess, save_id, loader)
    except (ReaderExecutionError, ReaderMissingError):
        resolver = None
    search_resolver = None
    title_holder_ids = None
    if q or title:
        if q:
            search_resolver = _search_text_resolver(sess, save_id, title_index, loader, resolver)
        if title and title_index is not None:
            title_holder_ids = title_index.holder_ids_for_title(title)
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
        ruler_ids=title_index.ruler_ids() if title_index is not None else None,
        search_resolver=search_resolver,
        title_holder_ids=title_holder_ids,
        relevance=_relevance_ranks(sess, save_id, loader, resolver),
    )
    items = [
        to_summary(
            it,
            loader,
            title_index.primary_bits(str(it.get("id"))) if title_index is not None else None,
            resolver=resolver,
        ).model_dump()
        for it in page["items"]
    ]
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
    loader, title_periods, title_events, title_warnings, memory_index, resolver = _profile_parts(
        sess, save_id, character_id, stub
    )
    return to_profile(
        stub,
        loader,
        title_periods=title_periods,
        title_events=title_events,
        title_warnings=title_warnings,
        by_id=sess.by_id,
        memory_index=memory_index,
        resolver=resolver,
    ).model_dump()


@router.get("/local-saves/{save_id}/characters/{character_id}/timeline")
def character_timeline_endpoint(save_id: str, character_id: str):
    """M5 时间线：去重合并后的契约时间线 + 合并统计（不重新 melt）。

    - timeline：基础（出生/逝世）+ 头衔 + 记忆事件经 TimelineBuilder 去重合并，
      每条带 EvidenceRef（0 缺证据）；mergedCount>1 表示由多条重复存档记录合并。
    - mergedCount：被合并（并入主事件、不再单独呈现）的记录总数。
    """
    _rec, sess = _ensure_session(save_id)
    try:
        stub = _session_manager.get_character(sess, character_id)
    except KeyError:
        raise _fail(404, "character_not_found", f"缓存中未找到人物 id={character_id}")
    except (ReaderExecutionError, ReaderMissingError) as exc:
        raise _fail(500, "reader_error", str(exc)) from exc
    loader, _title_periods, title_events, _title_warnings, memory_index, _resolver = _profile_parts(
        sess, save_id, character_id, stub
    )
    name_key = stub.get("name") or ""
    display_name = loader.resolve(name_key) if (loader and name_key) else name_key
    base_events, _base_warnings = _build_timeline_and_evidence(stub, display_name or name_key)
    source_events: list = list(base_events) + list(title_events)
    if memory_index is not None:
        source_events += memory_index.timeline_events(character_id)
    merged = merge_timeline(source_events)
    return {
        "saveId": save_id,
        "characterId": character_id,
        "eventCount": len(merged.timeline),
        "mergedCount": merged.merged_count,
        "mergeDetails": merged.merge_details,
        "timeline": [e.model_dump() for e in merged.timeline],
    }


@router.get("/local-saves/{save_id}/characters/{character_id}/memories")
def character_memories_endpoint(save_id: str, character_id: str):
    """M4 关系与记忆：从 memories.json 聚合单角色的记忆/关系（不重新 melt）。

    - memories：归属到该人物的记忆 LifeEvent[]（含无日期条目，诚实呈现）。
    - friends/rivals/lovers：由 became_* 记忆同日期配对推断（INFERRED，名字可解析）；
      未配对的关系以 *_count 计数呈现（不伪造名字）。
    - warnings 含 Rust 扫描告警 + 推断告警。
    """
    _rec, sess = _ensure_session(save_id)
    try:
        index, scanner_warnings = _memory_index(sess, save_id)
    except (ReaderExecutionError, ReaderMissingError) as exc:
        raise _fail(500, "reader_error", str(exc)) from exc
    rel = index.relationships(character_id)
    return {
        "saveId": save_id,
        "characterId": character_id,
        "memoryCount": len(index.memories(character_id)),
        "skippedTypeCount": index.skipped_type_count,
        "memories": [m.model_dump() for m in index.memories(character_id)],
        "relationships": {
            "friends": [r.model_dump() for r in rel.friends],
            "rivals": [r.model_dump() for r in rel.rivals],
            "lovers": [r.model_dump() for r in rel.lovers],
            "friendCount": rel.friend_count,
            "rivalCount": rel.rival_count,
            "loverCount": rel.lover_count,
        },
        "warnings": scanner_warnings
        + [w.model_dump() for w in index.warnings(character_id)],
    }


# -- Phase 3A：传记提纲生成 -----------------------------------------------------
class OutlineRequest(BaseModel):
    style: str = "serious_biography"
    includeInferred: bool = True
    includeUncertain: bool = True
    maxEvents: int = Field(default=24, ge=1, le=100)


def _current_provider():
    """按当前环境构建 LlmProvider；未配置 / 未知 provider → None。

    None 时生成流程返回 provider_not_configured（前端可提示用户配置 .env）。
    配置读取发生在模块级 .env 已加载之后（app.config._load_dotenv 于启动时执行）。
    """
    try:
        return build_provider()
    except ProviderNotConfiguredError:
        return None


@router.post("/local-saves/{save_id}/characters/{character_id}/biography/outline")
def generate_outline_endpoint(save_id: str, character_id: str, req: OutlineRequest):
    """生成人物传记提纲（压缩 → Provider → 校验 → 有限修复重试）。

    - 只读存档缓存，不重新 melt；绝不把完整存档/原始人物库发给模型。
    - 生成记录写入 SQLite（data/biography-outlines.sqlite，saveSignature 关联）。
    - 未配置模型时返回结构化错误（不伪造成功）。
    """
    _rec, sess = _ensure_session(save_id)
    try:
        stub = _session_manager.get_character(sess, character_id)
    except KeyError:
        raise _fail(404, "character_not_found", f"缓存中未找到人物 id={character_id}")
    except (ReaderExecutionError, ReaderMissingError) as exc:
        raise _fail(500, "reader_error", str(exc)) from exc

    try:
        style = BiographyStyle(req.style)
    except ValueError:
        raise _fail(400, "invalid_style", f"非法 BiographyStyle：{req.style}")

    loader, title_periods, title_events, title_warnings, memory_index, resolver = _profile_parts(
        sess, save_id, character_id, stub
    )
    profile = to_profile(
        stub,
        loader,
        title_periods=title_periods,
        title_events=title_events,
        title_warnings=title_warnings,
        by_id=sess.by_id,
        memory_index=memory_index,
        resolver=resolver,
    )

    provider = _current_provider()
    result = OutlineGenerator(provider=provider, max_repair=DEFAULT_MAX_REPAIR).generate(
        profile,
        style=style,
        include_inferred=req.includeInferred,
        include_uncertain=req.includeUncertain,
        max_events=req.maxEvents,
    )

    warnings = result.warnings or []
    if result.valid:
        outline_json = result.outline.model_dump_json()
        record_id = outline_store().save_generation(
            save_id=save_id,
            save_signature=sess.signature,
            character_id=character_id,
            style=style.value,
            status="success",
            outline_json=outline_json,
            retry_count=result.retryCount,
            warning_json=json.dumps(warnings, ensure_ascii=False),
            compression_version=(
                result.compressed.compressionVersion if result.compressed else None
            ),
            prompt_version=PROMPT_VERSION,
        )
        return {
            "saveId": save_id,
            "characterId": character_id,
            "recordId": record_id,
            "valid": True,
            "retryCount": result.retryCount,
            "warnings": warnings,
            "outline": result.outline.model_dump(),
            "compressed": (
                result.compressed.model_dump() if result.compressed is not None else None
            ),
            "stale": False,
        }

    record_id = outline_store().save_generation(
        save_id=save_id,
        save_signature=sess.signature,
        character_id=character_id,
        style=style.value,
        status="error",
        error_code=result.errorCode,
        error_message=result.errorMessage,
        retry_count=result.retryCount,
        warning_json=json.dumps(warnings, ensure_ascii=False),
        compression_version=(
            result.compressed.compressionVersion if result.compressed else None
        ),
        prompt_version=PROMPT_VERSION,
    )
    return {
        "saveId": save_id,
        "characterId": character_id,
        "recordId": record_id,
        "valid": False,
        "retryCount": result.retryCount,
        "warnings": warnings,
        "outline": None,
        "compressed": (
            result.compressed.model_dump() if result.compressed is not None else None
        ),
        "error": {"code": result.errorCode, "message": result.errorMessage},
        "stale": False,
    }


@router.get("/local-saves/{save_id}/characters/{character_id}/biography/outlines")
def list_outlines_endpoint(
    save_id: str,
    character_id: str,
    limit: int = Query(default=10, ge=1, le=50),
):
    """列出该人物的提纲生成记录（含 stale 标记：签名变化 → 基于旧存档）。"""
    _rec, sess = _ensure_session(save_id)
    records = outline_store().list_generations(
        save_id,
        character_id,
        current_signature=sess.signature,
        current_compression_version=COMPRESSION_VERSION,
        limit=limit,
    )
    return {
        "saveId": save_id,
        "characterId": character_id,
        "count": len(records),
        "records": records,
    }


# -- Phase 3B：传记正文生成（异步任务） --------------------------------------
class BiographyRequest(BaseModel):
    """以已生成提纲为依据，异步生成正文。

    - outlineId：outline_store 中的提纲记录 id（必须属于该存档且未 stale）。
    - includeInferred / includeUncertain / maxEvents：与提纲生成时一致的压缩设置。
    """
    outlineId: int
    includeInferred: bool = True
    includeUncertain: bool = True
    maxEvents: int = Field(default=24, ge=1, le=100)


def _build_biography_worker(
    save_id: str,
    character_id: str,
    session,
    req: BiographyRequest,
    outline_rec: dict,
):
    """构造后台 worker：加载人物档案 + 运行 BiographyGenerator + 落库。

    返回 manager.start() 用的 dict 结果；进度通过 manager.update_progress 更新。
    """
    manager = biography_job_manager()
    outline = BiographyOutline.model_validate(outline_rec["outline"])
    outline_id = int(outline_rec["id"])

    def _worker(job) -> dict:
        # 档案加载（与提纲生成同路径：一次 melt 多次查询，不重新解析）。
        stub = _session_manager.get_character(session, character_id)
        loader, title_periods, title_events, title_warnings, memory_index, resolver = _profile_parts(
            session, save_id, character_id, stub
        )
        profile = to_profile(
            stub,
            loader,
            title_periods=title_periods,
            title_events=title_events,
            title_warnings=title_warnings,
            by_id=session.by_id,
            memory_index=memory_index,
            resolver=resolver,
        )
        total = len(outline.chapters)
        manager.update_progress(
            job.job_id, total=total, completed=0,
            current_index=1, current_title=outline.chapters[0].title if total else "",
            retry_count=0, fact_check_issue_count=0,
        )

        def on_progress(completed: int, total_ch: int) -> None:
            title = (
                outline.chapters[completed - 1].title
                if 1 <= completed <= total_ch
                else ""
            )
            manager.update_progress(
                job.job_id, total=total_ch, completed=completed,
                current_index=completed, current_title=title,
                retry_count=0, fact_check_issue_count=0,
            )

        result = BiographyGenerator(
            provider=_current_provider(),
            max_repair=DEFAULT_MAX_CHAPTER_REPAIR,
        ).generate(
            profile,
            outline,
            include_inferred=req.includeInferred,
            include_uncertain=req.includeUncertain,
            max_events=req.maxEvents,
            on_progress=on_progress,
            is_cancelled=lambda: manager.is_cancelled(job.job_id),
        )

        if result.biography is None:
            return {
                "status": "error",
                "error_code": result.errorCode,
                "error_message": result.errorMessage,
                "retry_count": result.retryCount,
                "fact_check_issue_count": 0,
            }

        record_status = (
            "needs_revision"
            if result.biography.factCheck is not None
            and result.biography.factCheck.status.value == "needs_revision"
            else "completed"
        )
        biography_id = uuid.uuid4().hex
        biography_store().save_biography(
            biography_id=biography_id,
            save_id=save_id,
            save_signature=session.signature,
            character_id=character_id,
            outline_id=outline_id,
            status=record_status,
            style=outline.style.value,
            revision_count=result.retryCount,
            biography_json=result.biography.model_dump_json(),
            fact_check_json=(
                result.biography.factCheck.model_dump_json()
                if result.biography.factCheck is not None
                else None
            ),
            model_name=result.biography.modelName,
            prompt_version=CHAPTER_PROMPT_VERSION,
            compression_version=(
                result.compressed.compressionVersion
                if result.compressed is not None
                else None
            ),
        )
        return {
            "status": "completed",
            "biography_id": biography_id,
            "record_status": record_status,
            "retry_count": result.retryCount,
            "fact_check_issue_count": (
                len(result.biography.factCheck.issues)
                if result.biography.factCheck is not None
                else 0
            ),
        }

    return _worker


@router.post("/local-saves/{save_id}/characters/{character_id}/biography")
def generate_biography_endpoint(save_id: str, character_id: str, req: BiographyRequest):
    """以已生成提纲为依据，异步生成传记正文。

    - 立即返回 {jobId, status:"pending"}；进度经 GET /api/biography/jobs/{job_id} 查询。
    - 提纲必须存在且基于当前存档（signature 一致 + 未 stale），否则 400。
    - 模型不可达 / 未配置：job 以 error 结束，**不保存半成品、不伪造成功**。
    - 完成后正文落库（data/biography-biographies.sqlite），status 区分
      completed / needs_revision（有限修复耗尽仍存在问题时的诚实草稿）。
    """
    _rec, sess = _ensure_session(save_id)
    outline_rec = outline_store().get_generation_raw(req.outlineId)
    if outline_rec is None:
        raise _fail(404, "outline_not_found", f"提纲记录不存在：{req.outlineId}")
    if outline_rec.get("save_signature") != sess.signature:
        raise _fail(
            400,
            "outline_stale",
            "该提纲基于旧存档生成，请先用当前存档重新生成提纲。",
        )
    try:
        stub = _session_manager.get_character(sess, character_id)
    except KeyError:
        raise _fail(404, "character_not_found", f"缓存中未找到人物 id={character_id}")
    except (ReaderExecutionError, ReaderMissingError) as exc:
        raise _fail(500, "reader_error", str(exc)) from exc

    worker = _build_biography_worker(save_id, character_id, sess, req, outline_rec)
    job = biography_job_manager().start(
        worker=worker, save_id=save_id, character_id=character_id
    )
    return {
        "saveId": save_id,
        "characterId": character_id,
        "jobId": job.job_id,
        "status": "pending",
    }


@router.get("/biography/jobs/{job_id}")
def biography_job_status_endpoint(job_id: str):
    """查询正文生成任务进度（pending/running/completed/error/cancelled）。"""
    job = biography_job_manager().get(job_id)
    if job is None:
        raise _fail(404, "job_not_found", f"任务不存在：{job_id}")
    return job


@router.post("/biography/jobs/{job_id}/cancel")
def biography_job_cancel_endpoint(job_id: str):
    """取消正文生成任务（worker 在下一章前退出，不保存半成品）。"""
    status = biography_job_manager().cancel(job_id)
    if status is None:
        raise _fail(404, "job_not_found", f"任务不存在：{job_id}")
    return {"jobId": job_id, "cancelled": status not in ("completed", "error", "cancelled")}


@router.get("/local-saves/{save_id}/characters/{character_id}/biographies")
def list_biographies_endpoint(
    save_id: str,
    character_id: str,
    limit: int = Query(default=10, ge=1, le=50),
):
    """列出该人物的正文生成记录（含 stale 标记：签名变化 → 基于旧存档）。"""
    _rec, sess = _ensure_session(save_id)
    records = biography_store().list_biographies(
        save_id,
        character_id,
        current_signature=sess.signature,
        limit=limit,
    )
    return {
        "saveId": save_id,
        "characterId": character_id,
        "count": len(records),
        "records": records,
    }


# -- 清理 ---------------------------------------------------------------------
@router.delete("/saves/{save_id}")
def delete_save_endpoint(save_id: str):
    rec = _registry.get(save_id)
    sig = rec.staged_signature if rec else None
    removed = _registry.remove(save_id)
    _session_manager.drop_save(save_id)
    _drop_title_index(save_id)
    _drop_memory_index(save_id)
    _drop_search_name_cache(save_id)
    if sig:
        _loc_cache.pop((save_id, sig), None)
    return {"saveId": save_id, "removed": removed}
