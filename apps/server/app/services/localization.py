"""LocalizationLoader —— 加载 CK3 游戏 / Mod 的 PDX 本地化文件。

支持语言回退链（规范八）：
  zh-Hans / simp_chinese  →  english  →  原始 key

解析目标：
  - 文化键（如 "asian_han_chinese"）→ 中文名
  - 特质键（如 "trait_genius"）→ 中文名
  - 名称键（如 "Hua_83EF"）多数在 name list 中，可能解析不到 → 回退原始键，不崩溃

设计：
  - 只读扫描 localization 目录；结果缓存，重复 resolve 不重复读盘。
  - 不复制任何游戏/Mod 文件，不读取用户存档内容。
  - 未知 key 一律返回 None（由调用方决定是否展示原始 key 并标记 unresolved）。
"""
from __future__ import annotations

import re
from pathlib import Path

# CK3 本地化语言目录名 -> 内部语言标签
_LANG_DIR_TO_TAG = {
    "simp_chinese": "zh-Hans",
    "chinese": "zh-Hant",
    "english": "en",
}
# 解析回退顺序（最优先简中，其次英文，最后原 key）
_FALLBACK_CHAIN = ["zh-Hans", "en"]

_LANG_HEADER_RE = re.compile(r"^l_(?P<lang>[a-z_]+)\s*:", re.IGNORECASE)
_ENTRY_RE = re.compile(r'^(?P<key>[A-Za-z0-9_]+)\s*:\s*"(?P<val>(?:[^"\\]|\\.)*)"')


class LocalizationLoader:
    def __init__(self) -> None:
        # lang_tag -> { key: value }
        self._data: dict[str, dict[str, str]] = {}

    def _ingest_file(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return
        self._ingest_text(text)

    def load_dir(self, loc_dir: str | Path) -> int:
        """扫描某 localization 根目录（含 simp_chinese/english 子目录及 replace/）。返回加载条目数。"""
        root = Path(loc_dir)
        if not root.exists():
            return 0
        count = 0
        # game/localization/<lang>/*.yml 与 game/localization/replace/<lang>/*.yml
        for pat in ("**/*.yml", "**/*.yaml"):
            for f in root.glob(pat):
                before = sum(len(v) for v in self._data.values())
                self._ingest_file(f)
                after = sum(len(v) for v in self._data.values())
                count += after - before
        return count

    def load_game(self, game_dir: str | Path) -> int:
        return self.load_dir(Path(game_dir) / "game" / "localization")

    def load_mod(self, mod_dir: str | Path) -> int:
        return self.load_dir(Path(mod_dir) / "localization")

    def load_archive(self, archive_path: str | Path) -> int:
        """只读读取压缩包（.zip）内的 localization/*.yml 条目（支持 archive Mod）。

        不修改、不解压到磁盘——仅在内存中解析压缩包里的本地化条目。
        返回加载条目数。压缩包不存在或无法打开时返回 0。
        """
        import zipfile

        try:
            with zipfile.ZipFile(archive_path) as zf:
                count = 0
                for name in zf.namelist():
                    low = name.lower().replace("\\", "/")
                    if not low.endswith((".yml", ".yaml")):
                        continue
                    # 压缩包内 localization 既可能在根（localization/...），
                    # 也可能在子目录（mod/xxx/localization/...）。
                    if not (low.startswith("localization/") or "/localization/" in low):
                        continue
                    try:
                        data = zf.read(name).decode("utf-8-sig", errors="replace")
                    except Exception:  # noqa: BLE001
                        continue
                    before = sum(len(v) for v in self._data.values())
                    self._ingest_text(data)
                    after = sum(len(v) for v in self._data.values())
                    count += after - before
                return count
        except Exception:  # noqa: BLE001
            return 0

    def _ingest_text(self, text: str) -> None:
        cur_lang: str | None = None
        for line in text.splitlines():
            hm = _LANG_HEADER_RE.match(line.strip())
            if hm:
                raw = hm.group("lang").lower()
                cur_lang = _LANG_DIR_TO_TAG.get(raw, raw)
                self._data.setdefault(cur_lang, {})
                continue
            if cur_lang is None:
                continue
            em = _ENTRY_RE.match(line.strip())
            if em:
                key = em.group("key")
                val = em.group("val").replace('\\"', '"').replace("\\n", "\n")
                if key and val:
                    self._data[cur_lang][key] = val

    def resolve(self, key: str | None, languages: list[str] | None = None) -> str | None:
        if not key:
            return None
        langs = languages or _FALLBACK_CHAIN
        for lang in langs:
            val = self._data.get(lang, {}).get(key)
            if val:
                return val
        return None

    @property
    def loaded_languages(self) -> list[str]:
        return sorted(self._data.keys())

    def count(self) -> int:
        return sum(len(v) for v in self._data.values())
