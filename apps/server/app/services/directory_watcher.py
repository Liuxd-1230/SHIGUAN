"""DirectoryWatcher —— 轮询式监听 save games 目录的变更（无第三方依赖）。

设计：轻量 mtime+size 轮询，避免引入 watchdog 等额外依赖；后台线程周期性
扫描，发现新增/删除/修改的 *.ck3 时通过回调通知。用于"检测到新自动存档即触发解析"。

注意：轮询间隔默认 2s，适合本地开发；生产可用环境变量 SHIGUAN_WATCH_INTERVAL 调整。
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass
class WatchedSave:
    name: str
    path: str
    size_bytes: int
    modified: float


ChangeCallback = Callable[[list[WatchedSave], list[WatchedSave], list[WatchedSave]], None]


class DirectoryWatcher:
    def __init__(
        self,
        directory: str | Path,
        interval: float | None = None,
        on_change: Optional[ChangeCallback] = None,
    ) -> None:
        self.directory = Path(directory)
        self.interval = interval or float(os.environ.get("SHIGUAN_WATCH_INTERVAL", "2.0"))
        self.on_change = on_change
        self._snapshot: dict[str, tuple[float, int]] = {}
        self._stop = False
        self._thread: Optional[threading.Thread] = None

    def _scan(self) -> dict[str, tuple[float, int]]:
        out: dict[str, tuple[float, int]] = {}
        if self.directory.exists():
            for f in self.directory.glob("*.ck3"):
                st = f.stat()
                out[f.name] = (st.st_mtime, st.st_size)
        return out

    def poll_once(self) -> tuple[list[WatchedSave], list[WatchedSave], list[WatchedSave]]:
        """扫描一次，更新快照并返回 (新增, 删除, 修改)。"""
        current = self._scan()
        added_names = [n for n in current if n not in self._snapshot]
        removed_names = [n for n in self._snapshot if n not in current]
        changed_names = [
            n
            for n in current
            if n in self._snapshot and self._snapshot[n] != current[n]
        ]
        old = self._snapshot
        self._snapshot = current

        def _mk(names: list[str], src: dict[str, tuple[float, int]]) -> list[WatchedSave]:
            return [
                WatchedSave(
                    name=n,
                    path=str(self.directory / n),
                    size_bytes=src[n][1],
                    modified=src[n][0],
                )
                for n in names
            ]

        added = _mk(added_names, current)
        changed = _mk(changed_names, current)
        removed = _mk(removed_names, old)
        if self.on_change and (added or removed or changed):
            self.on_change(added, removed, changed)
        return added, removed, changed

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._snapshot = self._scan()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop:
            time.sleep(self.interval)
            if self._stop:
                break
            try:
                self.poll_once()
            except OSError:
                # 目录暂时不可访问：忽略，下一轮重试
                pass

    def stop(self) -> None:
        self._stop = True
        if self._thread:
            self._thread.join(timeout=self.interval + 1.0)
            self._thread = None
