# -*- coding: utf-8 -*-
"""可写数据目录：优先 %LOCALAPPDATA%\\hnuclass，受权限限制时退回软件目录下的 data/。"""
from __future__ import annotations

import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cached: str | None = None


def data_dir() -> str:
    global _cached
    if _cached:
        return _cached
    env = os.environ.get("HNUCLASS_HOME")
    candidates = []
    if env:
        candidates.append(env)
    local = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    candidates.append(os.path.join(local, "hnuclass"))
    candidates.append(os.path.join(APP_DIR, "data"))
    for path in candidates:
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".write-test")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            _cached = path
            return path
        except OSError:
            continue
    _cached = candidates[-1]
    return _cached


def cookie_path() -> str:
    env = os.environ.get("HNUCLASS_COOKIES")
    if env:
        return env
    return os.path.join(data_dir(), "cookies.json")


def profile_dir() -> str:
    return os.path.join(data_dir(), "browser-profile")
