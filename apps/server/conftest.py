"""pytest 配置：把 apps/server 与 save-schema/py 加入导入路径。

- `app` 包（后端）位于 apps/server 下。
- `models`（Python 数据契约）位于 packages/save-schema/py。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]  # apps/server
SCHEMA_PY = ROOT.parents[1] / "packages" / "save-schema" / "py"  # SHIGUAN/packages/save-schema/py

for p in (str(ROOT), str(SCHEMA_PY)):
    if p not in sys.path:
        sys.path.insert(0, p)
