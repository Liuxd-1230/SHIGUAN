"""settings_store —— 持久化用户自定义目录设置（saves/game/mods）。

- 写入 data/server-settings.json（该目录已被 .gitignore 忽略，不进仓库）。
- 仅保存路径覆盖，绝不保存真实存档内容或密钥。
- PUT /api/settings/paths 写入前会校验目录存在，不存在则拒绝（清晰错误）。
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import WORKSPACE_ROOT


SETTINGS_PATH = WORKSPACE_ROOT / "data" / "server-settings.json"
_KEYS = ("saves_dir", "game_dir", "mods_dir")


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return {k: data[k] for k in _KEYS if k in data}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_settings(settings: dict) -> dict:
    validated: dict = {}
    for k in _KEYS:
        v = settings.get(k)
        if v:
            p = Path(v)
            if not p.exists() or not p.is_dir():
                raise ValueError(f"目录不存在或不是文件夹：{k}={v}")
            validated[k] = str(p)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(validated, ensure_ascii=False, indent=2), encoding="utf-8")
    return validated


def effective_paths() -> dict:
    """合并默认解析与用户覆盖，返回最终生效路径。"""
    out: dict = {}
    saved = load_settings()
    out.update(saved)
    return out
