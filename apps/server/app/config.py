"""后端配置与路径解析。

所有路径均在项目/受控目录内解析，绝不把用户本地路径硬编码进代码。
真实存档只读复制到受控临时目录（见 local_save_discovery）。
"""
from __future__ import annotations

import os
from pathlib import Path

# apps/server/app/config.py -> parents[3] = 仓库根 (SHIGUAN)
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv() -> None:
    """极简 .env 加载（零依赖）：仅注入尚未在环境中的变量。

    本地路径/密钥只应通过 .env（已被 .gitignore 忽略）提供，绝不硬编码进源码。
    """
    env_path = WORKSPACE_ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_dotenv()

TOOLS_DIR = WORKSPACE_ROOT / "tools"
CK3_READER_DIR = TOOLS_DIR / "ck3-reader"

# Rust sidecar 二进制：优先 release，回退 debug
_READER_RELEASE = CK3_READER_DIR / "target" / "release" / "ck3-reader.exe"
_READER_DEBUG = CK3_READER_DIR / "target" / "debug" / "ck3-reader.exe"


def resolve_reader_binary() -> Path | None:
    """定位 ck3-reader 二进制（release 优先，其次 debug）。缺失返回 None。"""
    if _READER_RELEASE.exists():
        return _READER_RELEASE
    if _READER_DEBUG.exists():
        return _READER_DEBUG
    return None


# CK3 存档目录（Known Folder）：Documents/Paradox Interactive/Crusader Kings III/save games
# 可用环境变量 SHIGUAN_CK3_SAVES_DIR 覆盖（便于 CI / 非标准安装）。
def resolve_default_saves_dir() -> Path | None:
    env = os.environ.get("SHIGUAN_CK3_SAVES_DIR")
    if env:
        p = Path(env)
        return p if p.exists() else None
    userprofile = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not userprofile:
        return None
    candidate = (
        Path(userprofile)
        / "Documents"
        / "Paradox Interactive"
        / "Crusader Kings III"
        / "save games"
    )
    return candidate if candidate.exists() else None


# 受控临时目录（真实存档只读复制到此处解析，不进仓库）
STAGING_ROOT = Path(os.environ.get("SHIGUAN_STAGING_DIR", str(WORKSPACE_ROOT / "data" / "staging")))

# CK3 游戏安装目录（用于 GameDataResolver 读取真实 DLC / 版本信息）。
# 优先环境变量 SHIGUAN_CK3_GAME_DIR，其次 Steam 默认路径，再扫描常见库根。
def resolve_game_dir() -> Path | None:
    env = os.environ.get("SHIGUAN_CK3_GAME_DIR")
    if env:
        p = Path(env)
        return p if p.exists() else None
    steam = os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles")
    if steam:
        cand = Path(steam) / "Steam" / "steamapps" / "common" / "Crusader Kings III"
        if cand.exists():
            return cand
    for drive in ("C", "D", "E", "F"):
        cand = Path(f"{drive}:/SteamLibrary/steamapps/common/Crusader Kings III")
        if cand.exists():
            return cand
    return None


# 子进程超时（秒）：单存档 melt + 扫描，5.5s 实测，留足余量
READER_TIMEOUT_SECONDS = int(os.environ.get("SHIGUAN_READER_TIMEOUT", "120"))
