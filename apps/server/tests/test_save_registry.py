"""SaveRegistry 稳定副本生命周期测试（规范二）。

覆盖：签名失效、autosave A→B 读 B、文件写入中绝不复制、并发只复制一次、复制期间变化丢弃。
"""
from __future__ import annotations

import os
import shutil as _shutil
import shutil
import threading
from pathlib import Path

import pytest

from app.services import save_registry
from app.services.save_registry import SaveRegistry, SaveStillWritingError


@pytest.fixture(autouse=True)
def _stable(monkeypatch):
    # 默认视为已稳定（文件早写好），加速测试；still-writing 测试单独覆盖。
    monkeypatch.setattr(save_registry, "wait_until_stable", lambda *a, **k: True)
    yield


def _write(path, data: bytes):
    path.write_bytes(data)


def test_register_sets_save_id_and_staging(tmp_path):
    f = tmp_path / "autosave.ck3"
    _write(f, b"SAV0101" + b"\x00" * 50)
    reg = SaveRegistry(tmp_path / "staging")
    rec = reg.register(str(f))
    rec2 = reg.ensure_staged(rec.save_id)
    assert rec2.staging_path is not None
    assert Path(rec2.staging_path).exists()
    # 签名应为当前原文件签名
    assert rec2.staged_signature == save_registry._signature(
        f.stat().st_size, f.stat().st_mtime_ns
    )


def test_autosave_a_to_b_reads_b(tmp_path):
    f = tmp_path / "autosave.ck3"
    _write(f, b"SAV0101-VERSION-A" + b"\x00" * 40)
    reg = SaveRegistry(tmp_path / "staging")
    rec = reg.register(str(f))
    rec = reg.ensure_staged(rec.save_id)
    staging = Path(rec.staging_path)
    assert staging.read_bytes() == b"SAV0101-VERSION-A" + b"\x00" * 40

    # CK3 写入新 autosave（B）：覆盖原文件。
    _write(f, b"SAV0101-VERSION-B" + b"\x00" * 80)
    rec = reg.register(str(f))  # 重新登记检测到变化 → 旧副本失效
    assert rec.staged_signature is None  # 旧副本已失效
    rec = reg.ensure_staged(rec.save_id)  # 重新复制
    assert Path(rec.staging_path).read_bytes().startswith(b"SAV0101-VERSION-B")
    assert rec.size_bytes == len(b"SAV0101-VERSION-B" + b"\x00" * 80)


def test_still_writing_never_copies(monkeypatch, tmp_path):
    f = tmp_path / "autosave.ck3"
    _write(f, b"SAV0101" + b"\x00" * 30)
    # 模拟“仍在写入”：wait_until_stable 返回 False
    monkeypatch.setattr(save_registry, "wait_until_stable", lambda *a, **k: False)
    reg = SaveRegistry(tmp_path / "staging")
    rec = reg.register(str(f))
    with pytest.raises(SaveStillWritingError):
        reg.ensure_staged(rec.save_id)
    # 绝不复制
    assert rec.staging_path is None
    assert not list((tmp_path / "staging").glob("*.ck3"))


def test_concurrent_ensure_staged_copies_once(monkeypatch, tmp_path):
    f = tmp_path / "autosave.ck3"
    _write(f, b"SAV0101" + b"\x00" * 30)
    reg = SaveRegistry(tmp_path / "staging")
    rec = reg.register(str(f))

    copies = []
    real_copy2 = _shutil.copy2

    def counting_copy(src, dst):
        copies.append(1)
        real_copy2(src, dst)

    monkeypatch.setattr(shutil, "copy2", counting_copy)

    def worker():
        reg.ensure_staged(rec.save_id)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(copies) == 1  # 只创建了一个稳定副本
    assert Path(rec.staging_path).exists()


def test_copy_during_change_discards_tmp(monkeypatch, tmp_path):
    f = tmp_path / "autosave.ck3"
    _write(f, b"SAV0101" + b"\x00" * 30)
    reg = SaveRegistry(tmp_path / "staging")
    rec = reg.register(str(f))

    real_copy2 = _shutil.copy2

    def changing_copy(src, dst):
        real_copy2(src, dst)
        # 模拟“复制期间原文件又变化”：显式把原文件 mtime 推后 10 秒。
        # （不能用 os.utime(src, None)：Windows 系统时钟粒度约 15ms，
        #  紧接着写入很可能拿到同一时间戳，导致签名没变、测不出该分支。）
        st = os.stat(src)
        os.utime(src, (st.st_atime + 10, st.st_mtime + 10))

    monkeypatch.setattr(shutil, "copy2", changing_copy)

    with pytest.raises(SaveStillWritingError):
        reg.ensure_staged(rec.save_id)
    # 临时副本被丢弃
    tmps = list((tmp_path / "staging").glob("*.ck3.tmp"))
    assert tmps == []
    assert rec.staging_path is None
