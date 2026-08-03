"""SaveRegistry —— 把本机真实存档登记为稳定可用的 saveId，并管理只读副本。

安全边界（规范一/六/十二）：
  - 真实存档只读复制到受控临时目录（STAGING_ROOT），原文件绝不动、绝不留全路径给前端。
  - 解析/读取前等待原文件“稳定”（大小连续不变 + modified 不变 + debounce），避免读半成品。
  - 文件不稳定时**绝不**复制或解析，返回明确的 SaveStillWritingError（API 层转 409/423）。
  - 原文件签名（size + mtime_ns）变化时，旧 staging 副本与解析缓存失效，绝不复用旧副本。
  - 复制期间若原文件再变化，丢弃临时副本并请客户端重试，绝不基于不一致数据解析。
  - 前端只拿到 saveId + 文件名 + 展示别名，绝不拿到本地全路径。
  - 副本在 DELETE / 进程退出时清理（数据进 gitignore 的 data/，不进仓库）。
"""
from __future__ import annotations

import hashlib
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path


class SaveStillWritingError(RuntimeError):
    """原存档仍在被 CK3 写入（wait_until_stable 超时）。

    API 层应转换为 409 Conflict 或 423 Locked，提示客户端稍后重试。
    """

    def __init__(self, save_id: str, detail: str = "存档仍在写入，暂不可解析，请稍后重试。") -> None:
        self.save_id = save_id
        super().__init__(detail)


def _save_id_for(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8", "replace")).hexdigest()[:16]


def _signature(size: int, mtime_ns: int) -> str:
    """原文件签名：大小 + 纳秒 mtime。任一变化即视为新版本。

    该值会直接用作解析缓存目录名（data/cache/<saveId>/<signature>/），
    因此必须只含文件系统安全字符——绝不能用 ':'（Windows 目录名非法，
    且在 NTFS 上会被当作 ADS 备用数据流分隔符）。
    """
    return f"{size}-{mtime_ns}"


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


@dataclass
class SaveRecord:
    save_id: str
    file_name: str
    original_path: str
    staging_path: str | None = None
    display_name: str = ""
    size_bytes: int = 0
    modified: float = 0.0
    # 原文件签名（size:mtime_ns）——随文件更新而变。
    original_mtime_ns: int = 0
    staged_signature: str | None = None
    is_autosave: bool = False
    last_parse_status: str = "untouched"  # untouched | parsed | error
    mod_count: int = 0


class SaveRegistry:
    def __init__(self, staging_root: str | Path) -> None:
        self.staging_root = Path(staging_root)
        self._by_id: dict[str, SaveRecord] = {}
        # 每个 save_id 一把锁：保证“同时请求同一存档时只创建一个稳定副本”。
        self._copy_locks: dict[str, threading.Lock] = {}
        self._copy_locks_guard = threading.Lock()

    def _copy_lock(self, save_id: str) -> threading.Lock:
        with self._copy_locks_guard:
            return self._copy_locks.setdefault(save_id, threading.Lock())

    # -- 登记（仅元数据，不复制） ---------------------------------------------
    def register(self, original_path: str | Path) -> SaveRecord:
        src = Path(original_path)
        save_id = _save_id_for(str(src.resolve()))
        st = src.stat()
        mtime_ns = st.st_mtime_ns
        sig = _signature(st.st_size, mtime_ns)
        rec = self._by_id.get(save_id)
        if rec is None:
            rec = SaveRecord(
                save_id=save_id,
                file_name=src.name,
                original_path=str(src.resolve()),
                display_name=src.name,
                size_bytes=st.st_size,
                modified=st.st_mtime,
                original_mtime_ns=mtime_ns,
                is_autosave=src.name.lower().startswith("autosave"),
            )
            self._by_id[save_id] = rec
        else:
            # 重新登记：检测原文件是否变化。
            rec.size_bytes = st.st_size
            rec.modified = st.st_mtime
            rec.original_mtime_ns = mtime_ns
            rec.file_name = src.name
            rec.display_name = src.name
            rec.is_autosave = src.name.lower().startswith("autosave")
            # 若原文件签名与已暂存签名不同 → 旧副本/缓存失效，等待下次按需重建。
            if rec.staged_signature is not None and rec.staged_signature != sig:
                self._invalidate_staging(rec)
                rec.last_parse_status = "stale"
        return rec

    def _invalidate_staging(self, rec: SaveRecord) -> None:
        if rec.staging_path:
            try:
                Path(rec.staging_path).unlink(missing_ok=True)
            except OSError:
                pass
        rec.staging_path = None
        rec.staged_signature = None

    def current_signature(self, save_id: str) -> str | None:
        rec = self._by_id.get(save_id)
        if rec is None:
            return None
        src = Path(rec.original_path)
        try:
            st = src.stat()
        except OSError:
            return None
        return _signature(st.st_size, st.st_mtime_ns)

    # -- 按需复制稳定副本（解析/读取前调用） ----------------------------------
    def ensure_staged(self, save_id: str, stable: bool = True) -> SaveRecord:
        rec = self._by_id.get(save_id)
        if rec is None:
            raise KeyError(f"未知 saveId：{save_id}")
        src = Path(rec.original_path)
        # 当前原文件签名。
        src_stat = src.stat()
        cur_sig = _signature(src_stat.st_size, src_stat.st_mtime_ns)

        # 已有且签名一致 → 直接复用，绝不重新复制。
        if rec.staging_path and Path(rec.staging_path).exists() and rec.staged_signature == cur_sig:
            return rec

        # 否则需要（重）建稳定副本；加锁保证并发只复制一次。
        with self._copy_lock(save_id):
            # 双重检查：另一线程可能已建好。
            if (
                rec.staging_path
                and Path(rec.staging_path).exists()
                and rec.staged_signature == cur_sig
            ):
                return rec

            # 旧副本失效。
            self._invalidate_staging(rec)

            # 不稳定 → 绝不复制，明确报错（API 层转 409/423）。
            if stable and not wait_until_stable(src):
                raise SaveStillWritingError(save_id)

            self.staging_root.mkdir(parents=True, exist_ok=True)
            tmp = self.staging_root / f"{save_id}.ck3.tmp"
            shutil.copy2(src, tmp)

            # 复制完成后再次校验原文件签名：若期间又变化 → 丢弃临时副本，请重试。
            try:
                after = src.stat()
            except OSError:
                tmp.unlink(missing_ok=True)
                raise SaveStillWritingError(save_id)
            if _signature(after.st_size, after.st_mtime_ns) != cur_sig:
                tmp.unlink(missing_ok=True)
                raise SaveStillWritingError(save_id)

            dest = self.staging_root / f"{save_id}.ck3"
            # 原子替换：先把 tmp 改名为最终名（同盘 rename 原子）。
            tmp.replace(dest)
            rec.staging_path = str(dest)
            rec.staged_signature = cur_sig
            rec.size_bytes = after.st_size
            rec.modified = after.st_mtime
            rec.original_mtime_ns = after.st_mtime_ns
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
