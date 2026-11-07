# -*- coding: utf-8 -*-
"""命令行入口：python -m hnuclass.cli <command>"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .cg import CGClient, CGError
from .model import Deck
from .paths import APP_DIR, cookie_path

COOKIE_PATH = cookie_path()


def load_cookies() -> dict:
    env = os.environ.get("HNUCLASS_COOKIES")
    if env and os.path.exists(env):
        with open(env, encoding="utf-8") as f:
            return json.load(f)
    if os.path.exists(COOKIE_PATH):
        with open(COOKIE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cookies(cookies: dict) -> None:
    os.makedirs(os.path.dirname(COOKIE_PATH), exist_ok=True)
    with open(COOKIE_PATH, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)


def cmd_login(args) -> int:
    from .browser_login import login_with_browser

    print("正在打开浏览器，请在窗口里输入账号、密码和验证码完成登录…")
    cookies, client = login_with_browser(port=args.port, timeout=args.timeout)
    save_cookies(cookies)
    print(f"登录成功，Cookie 已保存到 {COOKIE_PATH}")
    name = client.whoami()
    if name:
        print(f"当前用户：{name}")
    return 0


def cmd_courses(args) -> int:
    c = CGClient(cookies=load_cookies())
    for x in c.courses():
        print(f"{x.id}\t{x.name}")
    return 0


def cmd_assignments(args) -> int:
    c = CGClient(cookies=load_cookies())
    for x in c.assignments(args.course):
        print(f"{x.id}\t{x.name}")
    return 0


def cmd_problems(args) -> int:
    from .cg import guess_kind

    c = CGClient(cookies=load_cookies())
    for x in c.problems(args.assign):
        print(f"{x.index}\t{x.problem_id}\t{guess_kind(x.title)}\t{x.title}")
    return 0


META_ARGS = ("session", "group", "klass", "name", "sid")


def _meta_overrides(args) -> dict:
    """命令行里显式给出的封面信息，覆盖配置文件。"""
    out = {}
    if getattr(args, "session", None):
        out["session"] = args.session
    if getattr(args, "group", None):
        out["group"] = args.group
    if getattr(args, "klass", None):
        out["klass"] = args.klass
    if getattr(args, "name", None):
        out["name"] = args.name
    if getattr(args, "sid", None):
        out["student_id"] = args.sid
    return out


def cmd_build(args) -> int:
    from .pipeline import BuildJob, Progress, build

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("meta", {}).update(_meta_overrides(args))
    if not cfg.get("llm", {}).get("api_key") and args.api_key:
        cfg.setdefault("llm", {})["api_key"] = args.api_key
    job = BuildJob.from_dict(cfg, base_dir=os.path.dirname(os.path.abspath(args.config)))
    client = CGClient(cookies=load_cookies())
    out = build(job, client, Progress(lambda m, f=None: print(m)))
    print(out)
    return 0


def cmd_demo(args) -> int:
    from .demo import demo_deck
    from .render import render_deck

    out = args.out or os.path.join(APP_DIR, "demo.pptx")
    deck = demo_deck()
    for key, value in _meta_overrides(args).items():
        setattr(deck, key, value)
    render_deck(deck, out, os.path.join(APP_DIR, "template.pptx"))
    print(out)
    return 0


def cmd_desktop(args) -> int:
    from .desktop import main as desktop_main
    desktop_main()
    return 0


def cmd_gui(args) -> int:
    from .gui import serve

    serve(host=args.host, port=args.port, open_browser=not args.no_open)
    return 0


def _add_meta_args(p) -> None:
    p.add_argument("--session", default="", help="第几次，例如 第五次")
    p.add_argument("--group", default="", help="组别，例如 \"第二组 3 号\"")
    p.add_argument("--class", dest="klass", default="", help="班级，例如 计科 2304")
    p.add_argument("--name", default="", help="姓名")
    p.add_argument("--sid", default="", help="学号")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hnuclass", description="湖南大学程序设计小班课课件生成器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("login", help="浏览器辅助登录并保存会话")
    p.add_argument("--port", type=int, default=9333)
    p.add_argument("--timeout", type=int, default=600)
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("courses", help="列出课程")
    p.set_defaults(func=cmd_courses)

    p = sub.add_parser("assignments", help="列出作业")
    p.add_argument("--course", required=True)
    p.set_defaults(func=cmd_assignments)

    p = sub.add_parser("problems", help="列出题目")
    p.add_argument("--assign", required=True)
    p.set_defaults(func=cmd_problems)

    p = sub.add_parser("build", help="按配置生成课件")
    p.add_argument("--config", required=True)
    p.add_argument("--api-key", default="")
    _add_meta_args(p)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("demo", help="用内置示例生成一份课件")
    p.add_argument("--out", default="")
    _add_meta_args(p)
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("desktop", help="启动独立桌面界面")
    p.set_defaults(func=cmd_desktop)

    p = sub.add_parser("gui", help="启动本地图形界面")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(func=cmd_gui)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except CGError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
