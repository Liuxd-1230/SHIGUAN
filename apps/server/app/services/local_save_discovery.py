"""LocalSaveDiscoveryService —— 发现本机 CK3 存档并安全暂存。

安全边界（来自规范第十二条）：
  - 只读复制真实存档到受控临时目录（STAGING_ROOT），不移动、不删除原始文件。
  - 不把用户本地路径硬编码进代码；目录经由 Known Folder / 环境变量解析。
  - 真实存档绝不进仓库、绝不写本地路径到源码。
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from app.config import STAGING_ROOT, resolve_default_saves_dir


@dataclass
class SaveFileInfo:
    name: str
    path: str
    size_bytes: int
    modified: float


class LocalSaveDiscoveryService:
    def __init__(self, saves_dir: str | Path | None = None) -> None:
        self.saves_dir = Path(saves_dir) if saves_dir else resolve_default_saves_dir()

    def is_available(self) -> bool:
        return self.saves_dir is not None and Path(self.saves_dir).exists()

    def list_saves(self) -> list[SaveFileInfo]:
        if not self.is_available():
            return []
        out: list[SaveFileInfo] = []
        for f in sorted(Path(self.saves_dir).glob("*.ck3")):  # type: ignore[union-attr]
            st = f.stat()
            out.append(
                SaveFileInfo(
                    name=f.name, path=str(f), size_bytes=st.st_size, modified=st.st_mtime
                )
            )
        return out

    def copy_to_staging(self, save_path: str | Path, staging_root: str | Path = STAGING_ROOT) -> Path:
        """只读复制真实存档到受控临时目录，返回暂存路径。绝不动原始文件。"""
        src = Path(save_path)
        root = Path(staging_root)
        root.mkdir(parents=True, exist_ok=True)
        dest = root / src.name
        shutil.copy2(src, dest)
        return dest
