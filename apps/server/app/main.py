"""史官 SHIGUAN 后端入口（FastAPI，Phase 2A.1）。

运行：
  cd apps/server
  uvicorn app.main:app --reload --port 8000 --host 127.0.0.1
或：
  python -m uvicorn app.main:app --port 8000 --host 127.0.0.1

安全（规范十二）：默认绑定 127.0.0.1；CORS 默认仅允许 localhost 前端来源，
生产不使用任意 *；关闭时停止监听并清理纯临时文件（不删用户原存档/不删持久缓存）。
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

# 让后端能 import 到 save-schema 的 Python 契约（packages/save-schema/py/models.py）。
# 仓库根 = apps/server/app/main.py 的 parents[3]。
_SCHEMA_PY = Path(__file__).resolve().parents[3] / "packages" / "save-schema" / "py"
if str(_SCHEMA_PY) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_SCHEMA_PY))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.exception_handlers import http_exception_handler  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app.config import STAGING_ROOT  # noqa: E402
from app.routers import saves  # noqa: E402


def _default_cors_origins() -> list[str]:
    """默认仅 localhost 前端来源；显式配置时以其为准，但拒绝任意 *。"""
    env = os.environ.get("SHIGUAN_CORS_ORIGINS")
    localhost = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    if not env:
        return localhost
    origins = [o.strip() for o in env.split(",") if o.strip()]
    # 不允许任意来源；若配置含 * 则回退到 localhost 白名单。
    if "*" in origins:
        return localhost
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：无特殊初始化（registry / session_manager 在模块导入时创建）。
    yield
    # 关闭：停止监听、清理会话、删除纯临时文件（绝不删用户原存档/持久缓存）。
    if saves._watcher is not None:
        try:
            saves._watcher.stop()
        except Exception:  # noqa: BLE001
            pass
    saves._session_manager.clear()
    for tmp in STAGING_ROOT.glob("*.ck3.tmp"):
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


app = FastAPI(title="史官 SHIGUAN 后端", version="0.2.0")

@app.exception_handler(HTTPException)
async def _unified_error(request: Request, exc: HTTPException):
    """统一错误体：{"error": {"code": ..., "message": ...}}。

    路由用 _fail() 抛出 detail={"error": {...}}，FastAPI 默认会再包一层
    {"detail": ...}，导致前端要写 body.detail.error。这里拍平为顶层 error，
    契约稳定且不泄露 traceback（规范十二）。
    """
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail, headers=exc.headers)
    return await http_exception_handler(request, exc)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(saves.router, prefix="/api")
