"""lifespan 测试（规范十二）：创建 FastAPI 时传入 lifespan，关闭后 watcher 停止 + 临时文件清理。

用 TestClient 上下文管理器触发 lifespan 关闭分支，验证：
  - 关闭时停止目录监听（_watcher 线程结束）；
  - 关闭时删除 staging 下的 *.ck3.tmp 半成品（绝不删用户原存档）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app
from app.routers import saves
from app.services.directory_watcher import DirectoryWatcher


def test_lifespan_shutdown_stops_watcher_and_cleans_tmp(tmp_path, monkeypatch):
    # 受控临时 staging 目录，并造一个未完成的 .ck3.tmp 半成品。
    staging = tmp_path / "staging"
    staging.mkdir()
    orphan = staging / "orphan.ck3.tmp"
    orphan.write_text("partial")

    # lifespan 读取 main 模块的 STAGING_ROOT，替换为受控目录。
    monkeypatch.setattr(app_main, "STAGING_ROOT", staging)

    # 启动一个真实目录监听，交给 lifespan 在关闭时停止。
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    (watch_dir / "a.ck3").write_bytes(b"SAV0101")
    watcher = DirectoryWatcher(watch_dir, interval=0.05)
    watcher.start()
    monkeypatch.setattr(saves, "_watcher", watcher)

    try:
        with TestClient(app) as client:
            # 启动期：应用可用
            assert client.get("/api/health").status_code == 200
        # 退出上下文 → lifespan 关闭分支执行：
        # 1) watcher 已停止（线程置空）
        assert watcher._thread is None
        # 2) 半成品临时文件被清理
        assert not orphan.exists()
        # 3) 用户原存档不被触碰
        assert (watch_dir / "a.ck3").exists()
    finally:
        saves._watcher = None
