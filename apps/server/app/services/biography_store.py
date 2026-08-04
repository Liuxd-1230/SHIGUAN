"""传记正文生成记录存储（Phase 3B 持久化）—— SQLite。

- 数据库位于 data/biography-biographies.sqlite（已被 .gitignore 忽略，不提交 Git）。
- `biography_id`（UUID 字符串）为对外主键；记录关联 (save_id, save_signature,
  character_id, outline_id)。
- 存档重解析（signature 变化）后旧记录标记 `stale=true`，前端据此提示
  "该正文基于旧存档生成"。
- 只存生成结果（chapters JSON / factCheck JSON / 状态 / 版本号），
  **绝不存** API Key、完整 Prompt、本地路径、原始存档。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import WORKSPACE_ROOT

DEFAULT_DB_PATH = WORKSPACE_ROOT / "data" / "biography-biographies.sqlite"

_STATUSES = ("completed", "needs_revision", "error")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS biographies (
    id TEXT PRIMARY KEY,
    save_id TEXT NOT NULL,
    save_signature TEXT NOT NULL,
    character_id TEXT NOT NULL,
    outline_id INTEGER,
    style TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('completed', 'needs_revision', 'error')),
    revision_count INTEGER NOT NULL DEFAULT 0,
    biography_json TEXT,
    fact_check_json TEXT,
    model_name TEXT,
    prompt_version TEXT,
    compression_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_biographies_char
    ON biographies (save_id, character_id, created_at DESC);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BiographyStore:
    """SQLite 正文记录仓库（进程内单例，FastAPI 线程池中安全）。"""

    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- 写 -----------------------------------------------------------------
    def save_biography(
        self,
        *,
        biography_id: str,
        save_id: str,
        save_signature: str,
        character_id: str,
        status: str,
        outline_id: Optional[int] = None,
        style: str = "",
        revision_count: int = 0,
        biography_json: Optional[str] = None,
        fact_check_json: Optional[str] = None,
        model_name: Optional[str] = None,
        prompt_version: Optional[str] = None,
        compression_version: Optional[str] = None,
    ) -> None:
        if status not in _STATUSES:
            raise ValueError(f"非法 status：{status}")
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO biographies (
                    id, save_id, save_signature, character_id, outline_id,
                    style, status, revision_count, biography_json, fact_check_json,
                    model_name, prompt_version, compression_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    biography_id, save_id, save_signature, character_id, outline_id,
                    style, status, revision_count, biography_json, fact_check_json,
                    model_name, prompt_version, compression_version,
                    now, now,
                ),
            )
            self._conn.commit()

    def update_biography(
        self,
        *,
        biography_id: str,
        status: str,
        biography_json: Optional[str] = None,
        fact_check_json: Optional[str] = None,
        revision_count: Optional[int] = None,
    ) -> bool:
        """更新已有记录（如 job 完成后落结果）。不存在返回 False。"""
        if status not in _STATUSES:
            raise ValueError(f"非法 status：{status}")
        sets = ["status = ?", "updated_at = ?"]
        args: list = [status, _now_iso()]
        if biography_json is not None:
            sets.append("biography_json = ?")
            args.append(biography_json)
        if fact_check_json is not None:
            sets.append("fact_check_json = ?")
            args.append(fact_check_json)
        if revision_count is not None:
            sets.append("revision_count = ?")
            args.append(int(revision_count))
        args.append(biography_id)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE biographies SET {', '.join(sets)} WHERE id = ?", args
            )
            self._conn.commit()
            return cur.rowcount > 0

    # -- 读 -----------------------------------------------------------------
    def get_biography(self, biography_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM biographies WHERE id = ?", (biography_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_biographies(
        self,
        save_id: str,
        character_id: str,
        *,
        current_signature: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM biographies
                WHERE save_id = ? AND character_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (save_id, character_id, max(1, int(limit))),
            ).fetchall()
        return [
            self._row_to_dict(row, current_signature=current_signature)
            for row in rows
        ]

    # -- 内部 ---------------------------------------------------------------
    @staticmethod
    def _row_to_dict(
        row: sqlite3.Row | tuple,
        current_signature: Optional[str] = None,
    ) -> dict:
        cols = [
            "id", "save_id", "save_signature", "character_id", "outline_id",
            "style", "status", "revision_count", "biography_json", "fact_check_json",
            "model_name", "prompt_version", "compression_version",
            "created_at", "updated_at",
        ]
        rec = dict(zip(cols, row))
        rec["biography"] = json.loads(rec.pop("biography_json")) if rec.get("biography_json") else None
        rec["factCheck"] = json.loads(rec.pop("fact_check_json")) if rec.get("fact_check_json") else None
        rec.pop("save_id", None)  # 冗余字段不回传（前端已知道 saveId）
        sig = rec.pop("save_signature", None)
        # stale 条件：存档签名变化（重解析）。
        rec["stale"] = bool(
            current_signature is not None
            and sig is not None
            and sig != current_signature
        )
        return rec


_store: BiographyStore | None = None
_store_lock = threading.Lock()


def biography_store(db_path: Optional[Path] = None) -> BiographyStore:
    """进程内单例（测试可传入临时 db_path）。"""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = BiographyStore(db_path)
    return _store
