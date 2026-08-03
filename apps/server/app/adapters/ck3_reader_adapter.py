"""Ck3ReaderAdapter —— 通过 subprocess 安全调用 Rust sidecar `ck3-reader`。

设计要点（来自规范与 docs/parser-evaluation.md）：
  - 进程隔离：二进制解析在子进程进行，崩溃不影响 Web 服务。
  - 不静默失败：二进制缺失或执行失败必须捕获 stderr 并显式报错（含安装提示）。
  - 版本化 JSON 协议：inspect / list-mods / list-characters / character-json / dump。
  - 缓存：完整人物索引按 (路径, mtime, size) 缓存，避免重复 melt。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from models import ParsedSaveMeta

from app.config import READER_TIMEOUT_SECONDS, STAGING_ROOT, resolve_reader_binary


class ReaderMissingError(RuntimeError):
    """ck3-reader 二进制不存在。"""

    def __init__(self) -> None:
        super().__init__(
            "未找到 ck3-reader 二进制。请在 tools/ck3-reader 下执行 build.sh"
            "（cargo build --release）构建 Rust sidecar。"
        )


class ReaderExecutionError(RuntimeError):
    """ck3-reader 执行失败（非 0 退出）。"""

    def __init__(self, stderr: str) -> None:
        super().__init__(f"ck3-reader 执行失败：{stderr.strip()}")


class Ck3ReaderAdapter:
    def __init__(self, binary: Path | None = None) -> None:
        self.binary = binary or resolve_reader_binary()
        self._index_cache: dict[tuple[str, float, int], list[dict]] = {}

    # -- 可用性 ---------------------------------------------------------------
    def is_available(self) -> bool:
        return self.binary is not None and Path(self.binary).exists()

    def _require(self) -> Path:
        if not self.is_available():
            raise ReaderMissingError()
        return Path(self.binary)  # type: ignore[arg-type]

    # -- 底层调用 -------------------------------------------------------------
    def _run(self, *args: str) -> dict:
        bin_path = self._require()
        try:
            proc = subprocess.run(
                [str(bin_path), *args],
                capture_output=True,
                text=True,
                timeout=READER_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReaderExecutionError(f"执行超时（>{READER_TIMEOUT_SECONDS}s）") from exc
        if proc.returncode != 0:
            raise ReaderExecutionError(proc.stderr or proc.stdout)
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ReaderExecutionError(f"输出非 JSON：{proc.stdout[:200]}") from exc

    # -- 高层 API -------------------------------------------------------------
    def inspect(self, save_path: str | Path) -> dict:
        """完整初检（会 melt：用于一次性 CLI / 调试）。服务内优先走 prepare+meta。"""
        return self._run("inspect", str(save_path))

    def list_mods(self, save_path: str | Path) -> list[str]:
        out = self._run("list-mods", str(save_path))
        return out.get("mods", [])

    # -- 一次 melt、多次查询的缓存命令（Phase 2A.1） -------------------------
    def prepare(self, staging_path: str | Path, cache_dir: str | Path) -> dict:
        """一次 melt，把受控索引产物写到 cache_dir。后续查询全部走缓存。"""
        return self._run("prepare", str(staging_path), str(cache_dir))

    def meta(self, cache_dir: str | Path) -> dict:
        """读取 prepare 生成的 meta.json（不重新 melt）。"""
        return self._run("meta", str(cache_dir))

    def entities(self, cache_dir: str | Path) -> dict:
        """读取 prepare 生成的 entities.json（M2 实体索引：id → 存档内部键，未本地化）。"""
        return self._run("entities", str(cache_dir))

    def character(self, cache_dir: str | Path, character_id: str) -> dict:
        """从缓存随机读取单人物结构化档案（不重新 melt）。"""
        return self._run("character", str(cache_dir), str(character_id))

    # -- 兼容旧 melt 路径（仅供 adapter 集成测试 / CLI）——服务内优先走 prepare+meta+character --
    def list_characters(self, save_path: str | Path) -> list[dict]:
        """返回完整人物索引（会 melt）。服务内改用 prepare 后分页，避免重复 melt。"""
        out = self._run("list-characters", str(save_path))
        return out.get("sample", [])

    def get_character(self, save_path: str | Path, character_id: str) -> dict:
        """返回单个人物的结构化摘要（会 melt）。"""
        return self._run("character-json", str(save_path), str(character_id))

    def to_parsed_meta(self, inspect: dict) -> ParsedSaveMeta:
        return ParsedSaveMeta(
            saveVersion=inspect.get("save_version"),
            gameVersion=inspect.get("game_version"),
            date=inspect.get("date"),
            # playerId 需后续从字符索引中按 player_name 解析；此处留空
        )
