"""Known Folder 解析 —— Windows 上优先使用 SHGetKnownFolderPath(FOLDERID_Documents)。

设计（规范七）：
  - 真实 Windows 用 Known Folder API 取 Documents 目录（CK3 存档/Mod 在其下）。
  - 不简单拼接 USERPROFILE/Documents（某些机器 Documents 被重定向/OneDrive 接管）。
  - 回退顺序：Known Folder Documents → 已保存用户设置 → OneDrive Documents →
    USERPROFILE/Documents → 用户手动选择。
  - 记录来源类型（known_folder | setting | onedrive | userprofile | manual），
    但绝不把完整个人路径写进日志或远端。
  - 解析函数可注入（inject），便于 CI 在 macOS/Linux 上用假数据测试，不依赖真实系统目录。

只在 Windows + 有 ctypes shell32 时调用 Known Folder API；其他平台直接走回退链。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
from pathlib import Path
from typing import Callable, Optional

# FOLDERID_Documents = {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
_FOLDERID_DOCUMENTS_STR = "FDD39AD0-238F-46AF-ADB4-6C85480369C7"


class GUID(ctypes.Structure):
    """与 Windows KNOWNFOLDERID GUID 结构逐字节对齐（16 字节）。

    SHGetKnownFolderPath 的 REFKNOWNFOLDERID 参数是 ``const GUID*``，
    必须传真正的 GUID 结构，不能传字符串缓冲（否则前 8 个 wchar 会被误读为 GUID）。
    """

    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, s: str) -> "GUID":
        s = s.strip().strip("{}").upper()
        parts = s.split("-")
        if len(parts) != 5:
            raise ValueError(f"非法 GUID 字符串：{s!r}")
        data4_hex = parts[3] + parts[4]
        data4 = (ctypes.c_ubyte * 8)(*bytes.fromhex(data4_hex))
        return cls(
            Data1=int(parts[0], 16),
            Data2=int(parts[1], 16),
            Data3=int(parts[2], 16),
            Data4=data4,
        )


_FOLDERID_DOCUMENTS = GUID.from_string(_FOLDERID_DOCUMENTS_STR)


def _known_folder_documents() -> Optional[str]:
    """调用 SHGetKnownFolderPath(FOLDERID_Documents)。失败返回 None。

    使用正确的 GUID 结构 + 显式 argtypes/restype，确保 64 位下也能正确 marshalling。
    """
    try:
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        ole32 = ctypes.windll.ole32  # type: ignore[attr-defined]
    except AttributeError:
        return None  # 非 Windows

    ppath = ctypes.c_wchar_p()
    try:
        # 显式声明签名，避免 ctypes 默认按 int 推断导致的栈错位（64 位必崩）。
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long  # HRESULT 即 32 位有符号长整型
        # 0x0000 = KF_FLAG_DEFAULT
        hr = shell32.SHGetKnownFolderPath(
            ctypes.byref(_FOLDERID_DOCUMENTS), 0, None, ctypes.byref(ppath)
        )
        if hr != 0 or not ppath or not ppath.value:
            return None
        return ppath.value
    except OSError:
        return None
    finally:
        # SHGetKnownFolderPath 成功时 ppath 指向 CoTaskMemAlloc 的内存，必须释放。
        if ppath and ppath.value:
            try:
                ole32.CoTaskMemFree(ppath)
            except Exception:  # noqa: BLE001
                pass


def _onedrive_documents() -> Optional[str]:
    for env in ("OneDrive", "OneDriveConsumer"):
        v = os.environ.get(env)
        if v:
            cand = Path(v) / "Documents"
            if cand.exists():
                return str(cand)
    return None


def resolve_documents_dir(
    inject: Optional[Callable[[], Optional[str]]] = None,
    settings_dir: Optional[str] = None,
) -> tuple[Optional[str], str]:
    """返回 (Documents 目录, 来源类型)。

    来源类型：known_folder | setting | onedrive | userprofile | manual | none。
    不抛异常；无任何来源时返回 (None, 'none')。
    """
    # 1) 已保存的用户设置（settings_store 传入的绝对目录，视为 manual/setting）
    if settings_dir:
        p = Path(settings_dir)
        if p.exists():
            return str(p), "setting"
    # 2) Known Folder API（可注入以便测试）
    if inject is not None:
        kf = inject()
    else:
        kf = _known_folder_documents()
    if kf and Path(kf).exists():
        return kf, "known_folder"
    # 3) OneDrive Documents
    od = _onedrive_documents()
    if od:
        return od, "onedrive"
    # 4) USERPROFILE/Documents
    userprofile = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if userprofile:
        cand = Path(userprofile) / "Documents"
        if cand.exists():
            return str(cand), "userprofile"
    return None, "none"


def resolve_ck3_user_dir(
    inject: Optional[Callable[[], Optional[str]]] = None,
    settings_dir: Optional[str] = None,
) -> tuple[Optional[str], str]:
    """返回 CK3 用户数据目录（Documents/Paradox Interactive/Crusader Kings III）。"""
    docs, source = resolve_documents_dir(inject=inject, settings_dir=settings_dir)
    if not docs:
        return None, source
    ck3 = Path(docs) / "Paradox Interactive" / "Crusader Kings III"
    if ck3.exists():
        return str(ck3), source
    return None, source
