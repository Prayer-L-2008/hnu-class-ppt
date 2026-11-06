# -*- coding: utf-8 -*-
"""浏览器辅助登录：拉起独立 Chrome/Edge，读取 CG 站点 Cookie。

账号、密码、验证码全部由用户在弹出的浏览器里自己输入；本模块只通过
DevTools 协议读取 cg.hnu.edu.cn 的会话 Cookie，不接触也不保存密码。
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import time
import urllib.parse
import urllib.request

LOGIN_URL = "https://cg.hnu.edu.cn/indexcs/simple.jsp"
CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser() -> str:
    for p in CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError("未找到 Chrome 或 Edge，请先安装其中之一。")


class _WS:
    """极简 WebSocket 客户端，只用于本地 DevTools。"""

    def __init__(self, url: str, timeout: float = 10):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path + ("?" + u.query if u.query else "")
        req = (
            f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        self.rf = self.sock.makefile("rb")
        status = self.rf.readline()
        if b"101" not in status:
            raise RuntimeError(f"DevTools 握手失败: {status!r}")
        while True:
            line = self.rf.readline()
            if line in (b"\r\n", b"\n", b""):
                break
        self._id = 0

    def _send_frame(self, payload: bytes, opcode: int = 1) -> None:
        mask = os.urandom(4)
        n = len(payload)
        head = bytearray([0x80 | opcode])
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        head += mask
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(head) + data)

    def _read_frame(self) -> tuple[int, bytes]:
        h = self.rf.read(2)
        if len(h) < 2:
            raise ConnectionError("DevTools 连接已关闭")
        opcode = h[0] & 0x0F
        n = h[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", self.rf.read(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self.rf.read(8))[0]
        masked = h[1] & 0x80
        mask = self.rf.read(4) if masked else b""
        data = self.rf.read(n)
        if masked:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return opcode, data

    def call(self, method: str, params: dict | None = None, timeout: float = 15):
        self._id += 1
        mid = self._id
        self._send_frame(json.dumps({"id": mid, "method": method,
                                     "params": params or {}}).encode())
        end = time.time() + timeout
        while time.time() < end:
            opcode, data = self._read_frame()
            if opcode == 9:      # ping
                self._send_frame(data, 10)
                continue
            if opcode == 8:
                raise ConnectionError("DevTools 主动关闭")
            if opcode != 1:
                continue
            msg = json.loads(data)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(f"CDP {method} 超时")

    def close(self) -> None:
        try:
            self._send_frame(b"", 8)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


def _http_json(url: str, timeout: float = 2.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def launch(port: int = 9333, profile_dir: str | None = None) -> subprocess.Popen:
    exe = find_browser()
    if profile_dir is None:
        from .paths import profile_dir as default_profile
        profile_dir = default_profile()
    os.makedirs(profile_dir, exist_ok=True)
    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run", "--no-default-browser-check",
        "--disable-background-networking", "--disable-sync",
        "--start-maximized", LOGIN_URL,
    ]
    return subprocess.Popen(args)


def wait_port(port: int, timeout: float = 20) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            _http_json(f"http://127.0.0.1:{port}/json/version")
            return
        except Exception:
            time.sleep(0.4)
    raise RuntimeError("浏览器调试端口没有起来，可能被安全软件拦截。")


def _page_ws(port: int) -> str:
    tabs = _http_json(f"http://127.0.0.1:{port}/json")
    cg = [t for t in tabs if "cg.hnu.edu.cn" in t.get("url", "") and t.get("webSocketDebuggerUrl")]
    pool = cg or [t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if not pool:
        raise RuntimeError("没有找到可用的浏览器标签页")
    return pool[0]["webSocketDebuggerUrl"]


def grab_cookies(port: int = 9333, domain: str = "hnu.edu.cn") -> dict:
    ws = _WS(_page_ws(port))
    try:
        ws.call("Network.enable")
        res = ws.call("Storage.getCookies")
        out = {}
        for c in res.get("cookies", []):
            d = c.get("domain", "").lstrip(".")
            if d.endswith(domain):
                out[c["name"]] = c["value"]
        return out
    finally:
        ws.close()


def login_with_browser(port: int = 9333, timeout: int = 600, on_wait=None):
    """打开浏览器并等待用户完成登录，返回 (cookies, client_or_None)。"""
    from .cg import CGClient

    proc = launch(port)
    wait_port(port)
    end = time.time() + timeout
    last = {}
    while time.time() < end:
        try:
            cookies = grab_cookies(port)
        except Exception:
            cookies = {}
        if cookies and cookies != last:
            last = cookies
            client = CGClient(cookies=cookies)
            if client.is_logged_in():
                return cookies, client
        if on_wait:
            on_wait()
        time.sleep(2.0)
    raise TimeoutError("等待登录超时。请在弹出的浏览器里完成登录后重试。")


def close_browser(port: int = 9333) -> None:
    try:
        info = _http_json(f"http://127.0.0.1:{port}/json/version")
        ws = _WS(info["webSocketDebuggerUrl"])
        ws.call("Browser.close", timeout=3)
        ws.close()
    except Exception:
        pass
