"""本地设置（AI 接口的 Base URL / 模型 / API Key）。

API Key 用 Windows DPAPI 以当前用户身份加密后落盘，明文不写文件、也不再回传浏览器；
DPAPI 不可用时退化为 base64 并标记，至少不会被一眼看到。
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes

from .paths import data_dir

_FILE = "settings.json"


def _path() -> str:
    return os.path.join(data_dir(), _FILE)


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    blob_out = _BLOB()
    if protect:
        fn = crypt32.CryptProtectData
        fn.argtypes = [ctypes.POINTER(_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_BLOB),
                       wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD,
                       ctypes.POINTER(_BLOB)]
    else:
        fn = crypt32.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(_BLOB), ctypes.POINTER(wintypes.LPWSTR),
                       ctypes.POINTER(_BLOB), wintypes.LPVOID, wintypes.LPVOID,
                       wintypes.DWORD, ctypes.POINTER(_BLOB)]
    fn.restype = wintypes.BOOL
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI 调用失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _pack_key(key: str) -> str:
    raw = key.encode("utf-8")
    try:
        return "dpapi:" + base64.b64encode(_dpapi(raw, True)).decode("ascii")
    except Exception:  # noqa: BLE001
        return "b64:" + base64.b64encode(raw).decode("ascii")


def _unpack_key(stored: str) -> str:
    if not stored:
        return ""
    try:
        tag, _, payload = stored.partition(":")
        data = base64.b64decode(payload)
        if tag == "dpapi":
            data = _dpapi(data, False)
        return data.decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""


def load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:  # noqa: BLE001
        return {"base_url": "", "model": "", "api_key": ""}
    return {
        "base_url": raw.get("base_url") or "",
        "model": raw.get("model") or "",
        "api_key": _unpack_key(raw.get("api_key") or ""),
    }


def save(base_url: str | None = None, model: str | None = None,
         api_key: str | None = None) -> dict:
    cur = load()
    if base_url is not None:
        cur["base_url"] = base_url.strip()
    if model is not None:
        cur["model"] = model.strip()
    if api_key is not None:
        cur["api_key"] = api_key.strip()
    data = {
        "base_url": cur["base_url"],
        "model": cur["model"],
        "api_key": _pack_key(cur["api_key"]) if cur["api_key"] else "",
    }
    os.makedirs(data_dir(), exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path())
    return cur


def public() -> dict:
    """返回给浏览器看的字段：绝不包含 Key 明文。"""
    cur = load()
    return {"base_url": cur["base_url"], "model": cur["model"],
            "has_key": bool(cur["api_key"])}
