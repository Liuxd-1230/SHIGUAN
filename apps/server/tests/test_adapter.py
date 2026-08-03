"""Ck3ReaderAdapter 集成测试（需要 ck3-reader 与真实存档样本）。

默认读取受控临时目录中的 autosave.ck3；可用环境变量 SHIGUAN_TEST_SAVE 覆盖。
无 reader 或无样本时整体跳过（CI 友好）。
"""
import os
from pathlib import Path

import pytest

from app.adapters.ck3_reader_adapter import Ck3ReaderAdapter
from app.config import resolve_reader_binary

# 真实存档样本不进仓库；用环境变量 SHIGUAN_TEST_SAVE 指向本机真实存档。
# 默认占位路径不存在，CI/无样本环境下测试整体跳过（本地路径（含用户名）不外泄到源码）。
DEFAULT_TEST_SAVE = Path(os.environ.get("SHIGUAN_TEST_SAVE", "fixtures/ck3/autosave.ck3"))
READER = resolve_reader_binary()
HAVE_READER = READER is not None and Path(READER).exists()
HAVE_SAVE = DEFAULT_TEST_SAVE.exists()

pytestmark = pytest.mark.skipif(
    not (HAVE_READER and HAVE_SAVE),
    reason="需要 ck3-reader 与真实存档样本（设置 SHIGUAN_TEST_SAVE）",
)


def test_adapter_inspect():
    a = Ck3ReaderAdapter()
    raw = a.inspect(str(DEFAULT_TEST_SAVE))
    assert raw["encoding"] == "Binary"
    assert raw["save_version"] == "15"
    assert raw["game_version"] == "1.19.0.6"
    assert raw["character_count"] == 35078
    assert raw["mod_count"] == 33
    assert raw["unknown_token_count"] == 0


def test_adapter_list_characters_full_index():
    a = Ck3ReaderAdapter()
    idx = a.list_characters(str(DEFAULT_TEST_SAVE))
    assert len(idx) == 35078
    assert idx[0]["id"] == "6432"


def test_adapter_get_character():
    a = Ck3ReaderAdapter()
    stub = a.get_character(str(DEFAULT_TEST_SAVE), "6432")
    assert stub["id"] == "6432"
    assert stub["name"]


def test_adapter_list_mods():
    a = Ck3ReaderAdapter()
    mods = a.list_mods(str(DEFAULT_TEST_SAVE))
    assert len(mods) == 33
    assert all(m.startswith("mod/ugc_") for m in mods)
