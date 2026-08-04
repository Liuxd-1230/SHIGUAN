"""SessionManager —— 一次 melt、多次查询的解析会话（Phase 2A.1 第三节）。

设计目标：
  - 每个 (save_id, staged_signature) 只 melt 一次：prepare 写受控缓存目录
    data/cache/<saveId>/<signature>/，之后所有查询走缓存，绝不重新 melt。
  - 内存中保留人物索引，分页/搜索/筛选在内存完成（仍不 melt），单人物按需取。
  - 服务重启后若缓存目录合法（signature 匹配），可复用磁盘缓存，不必再 melt。
  - 原存档更新（signature 变化）后旧缓存目录被清理，自动废弃。
  - 共享的应用级单例：不得每个请求新建 adapter 后丢弃缓存。

并发保证：同一 (save_id, signature) 的 prepare 只执行一次（prepare 锁）。
"""
from __future__ import annotations

import json
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.adapters.ck3_reader_adapter import Ck3ReaderAdapter
from app.services.save_registry import SaveStillWritingError

# Phase 3A.1：cache schema 版本（与 Rust 侧 CACHE_SCHEMA_VERSION 保持一致）。
# 扫描/提取行为变更时递增，旧缓存（无此字段或值不匹配）自动失效重建。
CACHE_SCHEMA_VERSION = "2"


@dataclass
class ParseSession:
    save_id: str
    signature: str
    cache_dir: Path
    character_count: int = 0
    _records: Optional[list[dict]] = field(default=None, repr=False)
    _by_id: Optional[dict[str, dict]] = field(default=None, repr=False)

    def load_index(self) -> None:
        ndjson = self.cache_dir / "characters.ndjson"
        recs: list[dict] = []
        if ndjson.exists():
            text = ndjson.read_text(encoding="utf-8")
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        self._records = recs
        self._by_id = {r.get("id"): r for r in recs}
        self.character_count = len(recs)

    @property
    def records(self) -> list[dict]:
        if self._records is None:
            self.load_index()
        return self._records  # type: ignore[return-value]

    @property
    def by_id(self) -> dict[str, dict]:
        if self._by_id is None:
            self.load_index()
        return self._by_id  # type: ignore[return-value]


class SessionManager:
    def __init__(self, cache_root: str | Path, adapter: Ck3ReaderAdapter | None = None) -> None:
        self.cache_root = Path(cache_root)
        self.adapter = adapter or Ck3ReaderAdapter()
        self._sessions: dict[tuple[str, str], ParseSession] = {}
        self._lock = threading.RLock()
        self._prep_locks: dict[tuple[str, str], threading.Lock] = {}
        self._prep_locks_guard = threading.Lock()
        # 统计：melt 实际执行次数（用于验收报告）。
        self.prepare_calls: int = 0

    @staticmethod
    def _safe_component(value: str) -> str:
        """把 saveId / signature 净化为文件系统安全的单层目录名。

        防御两件事：
          1) 路径穿越（'..'、'/'、'\\' 一律替换掉，绝不允许跳出 cache_root）；
          2) Windows 非法字符（: * ? " < > |）导致 mkdir 失败。
        """
        safe = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in str(value))
        safe = safe.strip(". ") or "_"
        return safe[:120]

    def cache_dir_for(self, save_id: str, signature: str) -> Path:
        return self.cache_root / self._safe_component(save_id) / self._safe_component(signature)

    # -- 二进制指纹（M3.2）：缓存归属同一份 reader 二进制才可复用 -----------------
    # reader_version 只含 Cargo 版本（如 "0.1.0"），无法区分占位/真实 token 表构建：
    # 若用占位表二进制 prepare 写出的缓存被真实表二进制复用，会静默拿到 25 字节空
    # 数据（landed_titles 等容器 "找不到"）。marker 记录二进制自身指纹（路径/尺寸/
    # 修改时间），跨构建（尺寸/时间戳变化）一律判无效重建，绝不静默降级。
    @staticmethod
    def _marker_path_for(cache_root: Path) -> Path:
        return cache_root / "reader-binary.json"

    @staticmethod
    def _binary_fingerprint(adapter_obj: object) -> Optional[dict]:
        path = getattr(adapter_obj, "path", None) or getattr(adapter_obj, "binary", None)
        if not path:
            return None  # 测试用 FakeAdapter 无真实二进制，不做指纹拦截
        try:
            st = Path(path).stat()
        except OSError:
            return None
        return {"path": str(Path(path)), "size": st.st_size, "mtime_ns": st.st_mtime_ns}

    def _cache_marker_valid(self) -> bool:
        """当前 reader 二进制指纹与最近一次 prepare 记录的指纹一致才可复用缓存。

        无真实二进制（FakeAdapter）时跳过；有二进制但无 marker（新装/历史遗留）→
        判无效，由本次 prepare 重建并写入 marker。
        """
        fp = self._binary_fingerprint(self.adapter)
        if fp is None:
            return True
        marker = self._marker_path_for(self.cache_root)
        try:
            recorded = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return recorded == fp

    def _write_marker(self) -> None:
        fp = self._binary_fingerprint(self.adapter)
        if fp is None:
            return
        try:
            self._marker_path_for(self.cache_root).write_text(
                json.dumps(fp), encoding="utf-8"
            )
        except OSError:
            pass

    def _cache_valid(self, cache_dir: Path) -> bool:
        """磁盘缓存是否完整可用（重启后可复用，不必重新 melt）。

        要求 meta.json 含 reader_version：旧版 reader（M3.1 之前）写的缓存无此字段，
        reader 行为变更（如 game_version 提取修正）后旧缓存语义已过时，必须失效重建。
        """
        if not (
            cache_dir.is_dir()
            and (cache_dir / "meta.json").is_file()
            and (cache_dir / "characters.ndjson").is_file()
            and (cache_dir / "character-offsets.json").is_file()
            and (cache_dir / "entities.json").is_file()
            and (cache_dir / "titles.json").is_file()
            and (cache_dir / "memories.json").is_file()
        ):
            return False
        try:
            meta = json.loads((cache_dir / "meta.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not meta.get("reader_version"):
            return False
        # Phase 3A.1：cache schema 版本显式化。Rust 侧 CACHE_SCHEMA_VERSION 递增时，
        # 旧缓存（无此字段或值不匹配）必须失效重建，防止扫描/提取行为变更后被复用。
        # 5 个缓存文件（meta/manifest/entities/titles/memories）都必须带同一版本，
        # 任一文件缺失/版本不一致即整体失效重建，杜绝部分新旧的混合复用。
        required_files = (
            "meta.json",
            "manifest.json",
            "entities.json",
            "titles.json",
            "memories.json",
        )
        for name in required_files:
            try:
                doc = json.loads((cache_dir / name).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            if doc.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
                return False
        # M3.2：同一份 reader 二进制（含同一 token 表构建）产生的缓存才可复用。
        return self._cache_marker_valid()

    def prepare(self, save_id: str, signature: str, staging_path: str | Path) -> ParseSession:
        """一次 melt 并建立 ParseSession。同一 (save_id, signature) 只 melt 一次。

        重启复用：若受控缓存目录已存在且完整（meta + ndjson + offsets），
        直接加载，绝不重新 melt——既快又满足“一次 melt 多次查询”的磁盘可复用要求。
        """
        key = (save_id, signature)
        with self._lock:
            sess = self._sessions.get(key)
            if sess is not None:
                return sess
            with self._prep_locks_guard:
                plock = self._prep_locks.setdefault(key, threading.Lock())
        with plock:
            with self._lock:
                sess = self._sessions.get(key)
                if sess is not None:
                    return sess
            cache_dir = self.cache_dir_for(save_id, signature)
            # 重启复用：磁盘缓存完整则加载，不重新 melt。
            if self._cache_valid(cache_dir):
                sess = ParseSession(save_id, signature, cache_dir)
                sess.load_index()
                with self._lock:
                    self._sessions[key] = sess
                return sess
            cache_dir.mkdir(parents=True, exist_ok=True)
            # 真正 melt 一次（adapter.prepare 内部调用 Rust `prepare`）。
            self.adapter.prepare(staging_path, cache_dir)
            self.prepare_calls += 1
            # M3.2：记录本次使用的 reader 二进制指纹，供重启后判断缓存归属。
            self._write_marker()
            sess = ParseSession(save_id, signature, cache_dir)
            sess.load_index()
            # 清理同一 save_id 的旧签名缓存目录，避免磁盘无限增长。
            self._prune_old_signatures(save_id, signature)
            with self._lock:
                self._sessions[key] = sess
            return sess

    def _prune_old_signatures(self, save_id: str, keep_signature: str) -> None:
        base = self.cache_root / self._safe_component(save_id)
        if not base.exists():
            return
        keep = self._safe_component(keep_signature)
        for d in base.iterdir():
            if d.is_dir() and d.name != keep:
                shutil.rmtree(d, ignore_errors=True)

    def get(self, save_id: str, signature: str) -> ParseSession | None:
        return self._sessions.get((save_id, signature))

    def meta(self, sess: ParseSession) -> dict:
        return self.adapter.meta(sess.cache_dir)

    def titles(self, sess: ParseSession) -> dict:
        """读取该会话的 titles.json（M3 头衔与统治经历，不重新 melt）。"""
        return self.adapter.titles(sess.cache_dir)

    def memories(self, sess: ParseSession) -> dict:
        """读取该会话的 memories.json（M4 记忆库，不重新 melt）。"""
        return self.adapter.memories(sess.cache_dir)

    def list_characters(
        self,
        sess: ParseSession,
        offset: int = 0,
        limit: int = 50,
        q: Optional[str] = None,
        ruler_only: bool = False,
        alive_only: bool = False,
        dynasty: Optional[str] = None,
        title: Optional[str] = None,
        sort: Optional[str] = None,
        ruler_ids: Optional[set[str]] = None,
        search_resolver: Optional[object] = None,
        title_holder_ids: Optional[set[str]] = None,
        relevance: Optional[dict] = None,
    ) -> dict:
        """在内存索引上做筛选 + 分页（不重新 melt）。

        q：M5 起默认匹配**解析后字段**（人名/头衔/王朝/文化等）。search_resolver
        为可调用对象 `(stub: dict) -> str`，返回该人物的可搜索文本（含解析后的
        中文名）；未提供时回退旧行为（在原始 stub JSON 上匹配，仅能命中原始 key）。

        title 参数：M5 起按头衔名反查 holder（title_holder_ids = 持有该头衔的
        人物 id 集合）；未提供时恒为“全部通过”（兼容旧调用/占位 token 表）。

        ruler_ids：M3 由 landed_titles 反解出的“当前持有头衔”人物 id 集合。
        提供时 ruler_only 用它判定（比仅看人物块 ruler 字段更完整，含名义头衔）；
        未提供则退回旧行为（人物块 ruler 字段）。

        relevance：Phase 2C 玩家/关联度优先排序。形如
        `{"player": id|None, "rel1": set[id], "dynasty": id|None}`。
        sort 为 None（默认）或 "relevance" 且 player 命中时，按
        玩家(0) → 配偶/子女/父母/妾(1) → 同 house(2) → 统治者(3) → 其他(4) 排序；
        未命中则退回原默认顺序。显式 name/birth/id 不受影响。
        """
        recs = sess.records
        needle = (q or "").strip().lower()
        out: list[dict] = []
        for r in recs:
            if needle:
                if search_resolver is not None:
                    hay = search_resolver(r).lower()
                    if needle not in hay:
                        continue
                elif needle not in json.dumps(r, ensure_ascii=False).lower():
                    continue
            if ruler_only:
                if ruler_ids is not None:
                    if str(r.get("id")) not in ruler_ids:
                        continue
                elif not r.get("ruler"):
                    continue
            if alive_only and not r.get("alive", True):
                continue
            if dynasty is not None and str(r.get("dynasty")) != str(dynasty):
                continue
            # title 过滤：M5 起按持有者集合判定；未提供则恒通过（兼容）。
            if title is not None and title_holder_ids is not None:
                if str(r.get("id")) not in title_holder_ids:
                    continue
            out.append(r)
        if sort == "name":
            out.sort(key=lambda r: (r.get("name") or "").lower())
        elif sort == "birth":
            out.sort(key=lambda r: (r.get("birth") or ""))
        elif sort == "id":
            out.sort(
                key=lambda r: int(r["id"]) if str(r["id"]).isdigit() else 1 << 60
            )
        elif relevance and relevance.get("player"):
            player = str(relevance["player"])
            rel1 = relevance.get("rel1") or set()
            dyn = relevance.get("dynasty")

            def _rank(r):
                cid = str(r.get("id"))
                if cid == player:
                    return 0
                if cid in rel1:
                    return 1
                if dyn and str(r.get("dynasty")) == dyn:
                    return 2
                if ruler_ids is not None and cid in ruler_ids:
                    return 3
                return 4

            out.sort(
                key=lambda r: (
                    _rank(r),
                    (r.get("name") or "").lower(),
                    int(r["id"]) if str(r["id"]).isdigit() else 1 << 60,
                )
            )
        total = len(out)
        start = max(0, min(offset, total))
        end = min(start + limit, total)
        items = out[start:end]
        return {
            "total": total,
            "offset": start,
            "limit": limit,
            "hasMore": end < total,
            "items": items,
        }

    def get_character(self, sess: ParseSession, character_id: str) -> dict:
        rec = sess.by_id.get(character_id)
        if rec is None:
            # 内存未命中（极端情况）：从磁盘按 offset 读取。
            rec = self.adapter.character(sess.cache_dir, character_id)
        if rec is None:
            raise KeyError(character_id)
        return rec

    def drop_save(self, save_id: str) -> None:
        """丢弃某 save_id 的全部会话并清理其缓存目录（DELETE / 失效时调用）。"""
        with self._lock:
            for key in list(self._sessions.keys()):
                if key[0] == save_id:
                    del self._sessions[key]
        base = self.cache_root / self._safe_component(save_id)
        if base.exists():
            shutil.rmtree(base, ignore_errors=True)

    def clear(self) -> None:
        """清理全部会话（lifespan 关闭时调用，不删用户原存档）。"""
        with self._lock:
            self._sessions.clear()
