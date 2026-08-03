"""SaveRegistry —— 把本机真实存档登记为稳定可用的 saveId，并管理只读副本。

安全边界（规范一/六/十二）：
  - 真实存档只读复制到受控临时目录（STAGING_ROOT），原文件绝不动、绝不留全路径给前端。
  - 解析/读取前等待原文件“稳定”（大小连续不变 + modified 不变 + debounce），避免读半成品。
  - 前端只拿到 saveId + 文件名 + 展示别名，绝不拿到本地全路径。
  - 副本在 DELETE / 进程退出时清理（数据进 gitignore 的 data/，不进仓库）。
"""
from __future__ import annotations

import hashlib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SaveRecord:
    save_id: str
    file_name: str
    original_path: str
    staging_path: str | None = None
    display_name: str = ""
    size_bytes: int = 0
    modified: float = 0.0
    is_autosave: bool = False
    last_parse_status: str = "untouched"  # untouched | parsed | error
    mod_count: int = 0


def _save_id_for(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8", "replace")).hexdigest()[:16]


def wait_until_stable(
    path: str | Path,
    poll: float = 0.3,
    stable_for: float = 1.2,
    timeout: float = 30.0,
) -> bool:
    """等待文件大小与 modified 时间连续 stable_for 秒不变。

    用于判定 CK3 是否仍在写入。返回 True=已稳定；False=超时（仍不稳定）。
    只读 stat，不打开/锁文件，绝不长期占用原存档。
    """
    p = Path(path)
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    prev = None
    while time.monotonic() < deadline:
        try:
            st = p.stat()
            sig = (st.st_size, int(st.st_mtime * 1000))
        except OSError:
            return False
        if sig == prev:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= stable_for:
                return True
        else:
            stable_since = None
        prev = sig
        time.sleep(poll)
    return False


class SaveRegistry:
    def __init__(self, staging_root: str | Path) -> None:
        self.staging_root = Path(staging_root)
        self._by_id: dict[str, SaveRecord] = {}

    # -- 登记（仅元数据，不复制） ---------------------------------------------
    def register(self, original_path: str | Path) -> SaveRecord:
        src = Path(original_path)
        save_id = _save_id_for(str(src.resolve()))
        st = src.stat()
        rec = self._by_id.get(save_id)
        if rec is None:
            rec = SaveRecord(
                save_id=save_id,
                file_name=src.name,
                original_path=str(src.resolve()),
                display_name=src.name,
                size_bytes=st.st_size,
                modified=st.st_mtime,
                is_autosave=src.name.lower().startswith("autosave"),
            )
            self._by_id[save_id] = rec
        else:
            rec.size_bytes = st.st_size
            rec.modified = st.st_mtime
            rec.file_name = src.name
            rec.display_name = src.name
            rec.is_autosave = src.name.lower().startswith("autosave")
        return rec

    # -- 按需复制稳定副本（解析/读取前调用） ----------------------------------
    def ensure_staged(self, save_id: str, stable: bool = True) -> SaveRecord:
        rec = self._by_id.get(save_id)
        if rec is None:
            raise KeyError(f"未知 saveId：{save_id}")
        if rec.staging_path and Path(rec.staging_path).exists():
            return rec
        src = Path(rec.original_path)
        if stable:
            wait_until_stable(src)
        self.staging_root.mkdir(parents=True, exist_ok=True)
        dest = self.staging_root / f"{save_id}.ck3"
        shutil.copy2(src, dest)
        rec.staging_path = str(dest)
        return rec

    def get(self, save_id: str) -> SaveRecord | None:
        return self._by_id.get(save_id)

    def list(self) -> list[SaveRecord]:
        return list(self._by_id.values())

    def remove(self, save_id: str) -> bool:
        rec = self._by_id.pop(save_id, None)
        if rec is None:
            return False
        if rec.staging_path:
            try:
                Path(rec.staging_path).unlink(missing_ok=True)
            except OSError:
                pass
        return True

    def set_parse_status(self, save_id: str, status: str, mod_count: int = 0) -> None:
        rec = self._by_id.get(save_id)
        if rec:
            rec.last_parse_status = status
            rec.mod_count = mod_count
