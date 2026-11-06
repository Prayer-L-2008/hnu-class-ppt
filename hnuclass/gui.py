# -*- coding: utf-8 -*-
"""本地 Web 图形界面：python -m hnuclass.cli gui"""
from __future__ import annotations

import json
import os
import ssl
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .cg import CGClient, guess_kind
from .cli import load_cookies, save_cookies
from .llm import LLMConfig
from . import settings as saved_settings
from .pipeline import BuildJob, Progress, build

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(APP_DIR, "web")

_state_lock = threading.Lock()
_state = {
    "cookies": {},
    "client": None,
    "login": "idle",       # idle | waiting | done | error
    "login_msg": "",
    "job": None,           # {state, log, out, error}
}


def _client() -> CGClient:
    if _state["client"] is None:
        _state["cookies"] = load_cookies()
        _state["client"] = CGClient(cookies=_state["cookies"])
    return _state["client"]


def _list_models(base_url: str, api_key: str) -> dict:
    """用写好的 Key 去 {base}/models 拉可用模型（兼容 OpenAI 协议）。"""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        base = "https://api.deepseek.com/v1"
    urls = [base + "/models"]
    if base.endswith("/v1"):
        urls.append(base[:-3] + "/models")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    last = "没有拿到模型列表"
    for url in urls:
        req = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + api_key,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            detail = raw[:200]
            try:
                j = json.loads(raw)
                detail = ((j.get("error") or {}).get("message") or detail)
            except Exception:  # noqa: BLE001
                pass
            last = f"HTTP {e.code}：{detail}"
            continue
        except Exception as e:  # noqa: BLE001
            last = str(e)
            continue
        rows = data.get("data") or data.get("models") or []
        ids = []
        for row in rows:
            if isinstance(row, dict):
                mid = row.get("id") or row.get("name")
                if mid:
                    ids.append(str(mid))
        if ids:
            return {"ok": True, "models": ids, "source": url}
        last = "接口返回里没有模型列表"
    return {"ok": False, "error": last}


def _login_worker(port: int = 9333) -> None:
    from .browser_login import login_with_browser

    try:
        cookies, client = login_with_browser(port=port, timeout=600)
        save_cookies(cookies)
        with _state_lock:
            _state["cookies"] = cookies
            _state["client"] = client
            _state["login"] = "done"
            _state["login_msg"] = "已登录" + (f"：{client.whoami()}" if client.whoami() else "")
    except Exception as e:
        with _state_lock:
            _state["login"] = "error"
            _state["login_msg"] = str(e)


def _build_worker(cfg: dict) -> None:
    try:
        job = BuildJob.from_dict(cfg, base_dir=APP_DIR)
        client = _client()
        log: list[str] = []

        def progress(msg: str, frac=None):
            log.append(msg)
            with _state_lock:
                _state["job"]["log"] = log[:200]
                _state["job"]["frac"] = frac

        build(job, client, Progress(progress))
        with _state_lock:
            _state["job"].update(state="done", out=job.out, frac=1.0)
    except Exception as e:
        with _state_lock:
            _state["job"].update(state="error", error=str(e), trace=traceback.format_exc()[-2000:])


class Handler(BaseHTTPRequestHandler):
    server_version = "hnuclass/1.0"

    def log_message(self, fmt, *args):  # 静音
        pass

    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: str, ctype: str = "application/octet-stream") -> None:
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        path = u.path
        try:
            if path in ("/", "/index.html"):
                return self._file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
            if path == "/api/status":
                c = _client()
                ok = bool(_state["cookies"]) and c.is_logged_in()
                return self._json({
                    "login": _state["login"], "message": _state["login_msg"],
                    "logged_in": ok, "user": c.whoami() if ok else "",
                })
            if path == "/api/courses":
                return self._json({"items": [x.__dict__ for x in _client().courses()]})
            if path == "/api/assignments":
                cid = (q.get("course") or [""])[0]
                return self._json({"items": [x.__dict__ for x in _client().assignments(cid)]})
            if path == "/api/settings":
                return self._json(saved_settings.public())
            if path == "/api/problems":
                aid = (q.get("assign") or [""])[0]
                items = []
                for x in _client().problems(aid):
                    items.append({"index": x.index, "problem_id": x.problem_id,
                                  "title": x.title, "kind": x.kind or guess_kind(x.title),
                                  "via": x.via, "detail": x.detail})
                return self._json({"items": items})
            if path == "/api/build/status":
                with _state_lock:
                    return self._json(dict(_state["job"] or {}))
            if path == "/download":
                with _state_lock:
                    out = (_state["job"] or {}).get("out")
                if not out or not os.path.exists(out):
                    return self._json({"error": "文件不存在"}, 404)
                name = urllib.parse.quote(os.path.basename(out))
                with open(out, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.presentationml.presentation")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{name}")
                self.end_headers()
                self.wfile.write(data)
                return
            return self._json({"error": "not found"}, 404)
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            body = {}
        try:
            if u.path == "/api/login":
                with _state_lock:
                    if _state["login"] == "waiting":
                        return self._json({"ok": True, "message": "已在等待登录"})
                    _state["login"] = "waiting"
                    _state["login_msg"] = "请在浏览器里完成登录…"
                threading.Thread(target=_login_worker, daemon=True).start()
                return self._json({"ok": True})
            if u.path == "/api/settings":
                saved_settings.save(body.get("base_url"), body.get("model"),
                                    body.get("api_key"))
                return self._json({"ok": True, **saved_settings.public()})
            if u.path == "/api/models":
                key = (body.get("api_key") or "").strip() or saved_settings.load()["api_key"]
                if not key:
                    return self._json({"ok": False, "error": "请先填写 API Key"}, 400)
                base = body.get("base_url") or saved_settings.load()["base_url"]
                return self._json(_list_models(base, key))
            if u.path == "/api/build":
                llm = body.get("llm")
                if not isinstance(llm, dict):
                    llm = {}
                    body["llm"] = llm
                if not (llm.get("api_key") or "").strip():
                    llm["api_key"] = saved_settings.load()["api_key"]
                if not (llm.get("base_url") or "").strip():
                    llm["base_url"] = saved_settings.load()["base_url"]
                if not (llm.get("model") or "").strip():
                    llm["model"] = saved_settings.load()["model"]
                if (llm.get("api_key") or "").strip():
                    saved_settings.save(llm.get("base_url") or "", llm.get("model") or "",
                                        llm.get("api_key") or "")
                if not (body.get("problems") or []):
                    return self._json({"error": "请先在「选择作业与题目」里勾选至少一道题"}, 400)
                if not (body.get("meta") or {}).get("name"):
                    return self._json({"error": "请在「课件信息」里填写姓名"}, 400)
                with _state_lock:
                    if _state["job"] and _state["job"].get("state") == "running":
                        return self._json({"error": "已有任务在生成"}, 409)
                    _state["job"] = {"state": "running", "log": [], "frac": 0, "out": ""}
                threading.Thread(target=_build_worker, args=(body,), daemon=True).start()
                return self._json({"ok": True})
            return self._json({"error": "not found"}, 404)
        except Exception as e:
            return self._json({"error": str(e)}, 500)


class _Server(ThreadingHTTPServer):
    # 端口被占用时直接报错，交给 serve() 换下一个端口，避免两个进程抢同一个端口
    allow_reuse_address = False


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True,
          on_ready=None) -> None:
    srv = None
    for p in range(port, port + 20):
        try:
            srv = _Server((host, p), Handler)
            port = p
            break
        except OSError:
            continue
    if srv is None:
        raise SystemExit("8765-8784 都被占用了，请先关掉多余的 python 进程")
    url = f"http://{host}:{port}/"
    print(f"小班课课件生成器已启动：{url}", flush=True)
    print("按 Ctrl+C 退出。", flush=True)
    if on_ready:
        try:
            on_ready(url)
        except Exception:  # noqa: BLE001
            pass
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
