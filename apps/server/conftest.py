"""pytest 配置：把 apps/server、save-schema/py 与 biography-engine/py 加入导入路径。

- `app` 包（后端）位于 apps/server 下。
- `models`（Python 数据契约）位于 packages/save-schema/py。
- `biography_engine`（Phase 3A 提纲生成）位于 packages/biography-engine/py。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]  # apps/server
SCHEMA_PY = ROOT.parents[1] / "packages" / "save-schema" / "py"  # SHIGUAN/packages/save-schema/py
BE_PY = ROOT.parents[1] / "packages" / "biography-engine" / "py"
TESTS = ROOT / "tests"

for p in (str(ROOT), str(SCHEMA_PY), str(BE_PY), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)
