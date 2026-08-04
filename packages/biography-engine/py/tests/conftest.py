"""pytest 配置：让 biography_engine / save-schema models / server app 可导入。

- biography_engine 位于 packages/biography-engine/py
- `models`（Python 数据契约）位于 packages/save-schema/py
- `app.services.llm_input_filter` 位于 apps/server
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # packages/biography-engine/py/tests
BE_PY = ROOT.parent                     # packages/biography-engine/py
REPO = ROOT.parents[3]                  # 仓库根 SHIGUAN
SCHEMA_PY = REPO / "packages" / "save-schema" / "py"
SERVER_APP = REPO / "apps" / "server"

for p in (str(BE_PY), str(SCHEMA_PY), str(SERVER_APP), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
