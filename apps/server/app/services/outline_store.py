"""传记提纲生成记录存储（Phase 3A 5.10）—— SQLite。

- 数据库位于 data/biography-outlines.sqlite（已被 .gitignore 忽略，不提交 Git）。
- 每条记录与 (save_id, save_signature) 关联；存档重解析（signature 变化）后旧记录
  标记 `stale=true`，前端据此提示"该提纲基于旧存档生成"。
- 只存生成结果（outline JSON / 错误码 / 版本号），**绝不存** API Key、原始存档、
  完整 Prompt、模型输出原文之外的中间数据。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import WORKSPACE_ROOT

DEFAULT_DB_PATH = WORKSPACE_ROOT / "data" / "biography-outlines.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outline_generations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    save_id TEXT NOT NULL,
    save_signature TEXT NOT NULL,
    character_id TEXT NOT NULL,
    style TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'error')),
    outline_json TEXT,
    error_code TEXT,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    warning_json TEXT,
    compression_version TEXT,
    prompt_version TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outline_gen_char
    ON outline_generations (save_id, character_id, id DESC);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class OutlineStore:
    """SQLite 生成记录仓库（进程内单例，FastAPI 线程池中安全）。"""

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
    def save_generation(
        self,
        *,
        save_id: str,
        save_signature: str,
        character_id: str,
        style: str,
        status: str,
        outline_json: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        retry_count: int = 0,
        warning_json: Optional[str] = None,
        compression_version: Optional[str] = None,
        prompt_version: Optional[str] = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO outline_generations (
                    save_id, save_signature, character_id, style, status,
                    outline_json, error_code, error_message, retry_count,
                    warning_json, compression_version, prompt_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    save_id, save_signature, character_id, style, status,
                    outline_json, error_code, error_message, retry_count,
                    warning_json, compression_version, prompt_version, _now_iso(),
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    # -- 读 -----------------------------------------------------------------
    def get_generation(self, record_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM outline_generations WHERE id = ?", (record_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_generations(
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
                SELECT * FROM outline_generations
                WHERE save_id = ? AND character_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (save_id, character_id, max(1, int(limit))),
            ).fetchall()
        return [
            self._row_to_dict(row, current_signature=current_signature)
            for row in rows
        ]

    # -- 内部 ---------------------------------------------------------------
    @staticmethod
    def _row_to_dict(row: sqlite3.Row | tuple, current_signature: Optional[str] = None) -> dict:
        cols = [
            "id", "save_id", "save_signature", "character_id", "style", "status",
            "outline_json", "error_code", "error_message", "retry_count",
            "warning_json", "compression_version", "prompt_version", "created_at",
        ]
        rec = dict(zip(cols, row))
        rec["outline"] = json.loads(rec.pop("outline_json")) if rec.get("outline_json") else None
        rec["warnings"] = json.loads(rec.pop("warning_json")) if rec.get("warning_json") else None
        rec.pop("save_id", None)  # 冗余字段不回传（前端已知道 saveId）
        sig = rec.pop("save_signature", None)
        rec["stale"] = bool(
            current_signature is not None and sig is not None and sig != current_signature
        )
        return rec


_store: OutlineStore | None = None
_store_lock = threading.Lock()


def outline_store(db_path: Optional[Path] = None) -> OutlineStore:
    """进程内单例（测试可传入临时 db_path）。"""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = OutlineStore(db_path)
    return _store
