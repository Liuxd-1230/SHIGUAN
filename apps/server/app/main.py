"""史官 SHIGUAN 后端入口（FastAPI）。

运行：
  cd apps/server
  uvicorn app.main:app --reload --port 8000
或：
  python -m uvicorn app.main:app --port 8000
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 让后端能 import 到 save-schema 的 Python 契约（packages/save-schema/py/models.py）。
# 仓库根 = apps/server/app/main.py 的 parents[3]。
_SCHEMA_PY = Path(__file__).resolve().parents[3] / "packages" / "save-schema" / "py"
if str(_SCHEMA_PY) not in sys.path:
    sys.path.insert(0, str(_SCHEMA_PY))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.routers import saves  # noqa: E402

app = FastAPI(title="史官 SHIGUAN 后端", version="0.1.0")

# 本地调试允许跨域（前端 vite dev server 在 5173）。生产可用环境变量收紧。
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("SHIGUAN_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(saves.router, prefix="/api")
