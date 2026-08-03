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

    def _cache_valid(self, cache_dir: Path) -> bool:
        """磁盘缓存是否完整可用（重启后可复用，不必重新 melt）。"""
        return (
            cache_dir.is_dir()
            and (cache_dir / "meta.json").is_file()
            and (cache_dir / "characters.ndjson").is_file()
            and (cache_dir / "character-offsets.json").is_file()
        )

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
    ) -> dict:
        """在内存索引上做筛选 + 分页（不重新 melt）。

        title 参数：占位 token 表下头衔未提取，无法按头衔过滤；接受该参数但恒为
        “全部通过”，并在 items 中保留 title_hint=None（诚实：不伪造头衔过滤）。
        """
        recs = sess.records
        needle = (q or "").strip().lower()
        out: list[dict] = []
        for r in recs:
            if needle and needle not in json.dumps(r, ensure_ascii=False).lower():
                continue
            if ruler_only and not r.get("ruler"):
                continue
            if alive_only and not r.get("alive", True):
                continue
            if dynasty is not None and str(r.get("dynasty")) != str(dynasty):
                continue
            # title 过滤在占位 token 表下不可用（无数据），恒为通过（不伪造结果）。
            out.append(r)
        if sort == "name":
            out.sort(key=lambda r: (r.get("name") or "").lower())
        elif sort == "birth":
            out.sort(key=lambda r: (r.get("birth") or ""))
        elif sort == "id":
            out.sort(
                key=lambda r: int(r["id"]) if str(r["id"]).isdigit() else 1 << 60
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
