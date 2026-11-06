# -*- coding: utf-8 -*-
"""本地编译并运行 C++ 参考程序，用真实运行结果填“用例及运行结果”页。"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field

GPP_CANDIDATES = [
    r"C:\Program Files (x86)\Dev-Cpp\MinGW32\bin\g++.exe",
    r"C:\Program Files (x86)\Dev-Cpp\MinGW64\bin\g++.exe",
    r"C:\MinGW\bin\g++.exe",
    "g++",
]


def find_gpp() -> str:
    for p in GPP_CANDIDATES:
        if p == "g++" or os.path.exists(p):
            return p
    return "g++"


@dataclass
class RunResult:
    ok: bool = False
    outputs: list[str] = field(default_factory=list)
    stderr: str = ""
    compiler: str = ""


def _workdir(base: str | None) -> str:
    """优先在指定目录下建临时目录；系统临时目录不可写时退回当前目录。"""
    for root in (base, tempfile.gettempdir(), os.path.join(os.getcwd(), ".hnuclass_tmp")):
        if not root:
            continue
        d = os.path.join(root, "hnuclass_" + uuid.uuid4().hex[:10])
        try:
            os.makedirs(d, exist_ok=False)
            probe = os.path.join(d, ".probe")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return d
        except OSError:
            continue
    d = os.path.join(os.getcwd(), "hnuclass_" + uuid.uuid4().hex[:10])
    os.makedirs(d, exist_ok=True)
    return d


def compile_and_run(code: str, cases, timeout: int = 6, workdir: str | None = None) -> RunResult:
    res = RunResult()
    if not code.strip():
        return res
    gpp = find_gpp()
    res.compiler = gpp
    d = _workdir(workdir)
    try:
        src = os.path.join(d, "main.cpp")
        exe = os.path.join(d, "main.exe")
        with open(src, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            cp = subprocess.run(
                [gpp, "-std=c++17", "-O2", "-o", exe, src],
                capture_output=True, timeout=60,
            )
        except FileNotFoundError:
            res.stderr = "未找到 g++，跳过运行。可在设置里指定编译器路径。"
            return res
        except subprocess.TimeoutExpired:
            res.stderr = "编译超时。"
            return res
        if cp.returncode != 0:
            res.stderr = cp.stderr.decode("utf-8", "replace")[:2000]
            return res
        for c in cases:
            try:
                rp = subprocess.run(
                    [exe], input=c.input.encode("utf-8"),
                    capture_output=True, timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                res.outputs.append("（运行超时）")
                continue
            out = rp.stdout.decode("utf-8", "replace").replace("\r\n", "\n").rstrip("\n")
            if rp.returncode != 0:
                out += f"\n（程序返回 {rp.returncode}）"
            res.outputs.append(out)
        res.ok = True
        return res
    finally:
        shutil.rmtree(d, ignore_errors=True)
