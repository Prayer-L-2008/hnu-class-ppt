# -*- coding: utf-8 -*-
"""独立桌面界面（tkinter）：python -m hnuclass.cli desktop"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import traceback
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from . import settings as saved_settings
from .browser_login import login_with_browser
from .cg import BASE, CGClient, guess_kind, parse_problem
from .llm import LLMConfig
from .paths import data_dir
from .pipeline import BuildJob, Progress, build

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(APP_DIR, "template.pptx")

BG = "#0f3b36"
BG2 = "#15524a"
BG3 = "#1b645a"
FG = "#eaf5f1"
MUTED = "#a7c9bf"
ACCENT = "#b01513"
GOLD = "#e6b729"

KINDS = ["编程题", "程序补全", "填空题", "选择题", "接口编程题"]


def _g(o, k, default=""):
    if isinstance(o, dict):
        return o.get(k, default)
    return getattr(o, k, default)


def _ui():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass


class DarkCombo(tk.Frame):
    """深色下拉框：用 tk.Menu 弹出，保证列表底色与文字对比度。"""

    def __init__(self, master, width=22, on_change=None):
        super().__init__(master, bg=BG2, highlightbackground=BG3, highlightthickness=1)
        self.on_change = on_change
        self.values: list[str] = []
        self.index = -1
        self.text = tk.StringVar(value="")
        self.lbl = tk.Label(self, textvariable=self.text, bg="#0c332e", fg=FG,
                            anchor="w", padx=8, pady=5, cursor="hand2",
                            font=("Microsoft YaHei UI", 10))
        self.lbl.pack(side="left", fill="x", expand=True)
        self.arrow = tk.Label(self, text="▾", bg="#0c332e", fg=MUTED, padx=8,
                              cursor="hand2", font=("Microsoft YaHei UI", 9))
        self.arrow.pack(side="right")
        for w in (self, self.lbl, self.arrow):
            w.bind("<Button-1>", self._popup)
        self.configure(width=width)

    def set_values(self, vals, select=None):
        self.values = list(vals)
        if not self.values:
            self.index = -1
            self.text.set("")
            return
        if select is not None:
            self.index = max(0, min(select, len(self.values) - 1))
        elif self.index < 0:
            self.index = 0
        self.text.set(self.values[self.index])

    def current(self):
        return self.index

    def set_index(self, i):
        if 0 <= i < len(self.values):
            self.index = i
            self.text.set(self.values[i])

    def get(self):
        return self.text.get()

    def set(self, v):
        self.text.set(v)

    def _popup(self, _e=None):
        if not self.values:
            return
        m = tk.Menu(self, tearoff=0, bg=BG2, fg=FG,
                    activebackground=GOLD, activeforeground="#1a1a1a",
                    font=("Microsoft YaHei UI", 10), borderwidth=1)
        for i, v in enumerate(self.values):
            m.add_command(label=v, command=lambda i=i: self._choose(i))
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _choose(self, i):
        self.set_index(i)
        if self.on_change:
            self.on_change()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("湖大程序设计小班课课件生成器")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(1180, sw - 40), min(820, sh - 60)
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 20)}")
        self.minsize(min(920, w), min(640, h))
        self.configure(bg=BG)

        self.cookies: dict = {}
        self.client: CGClient | None = None
        self.courses: list[dict] = []
        self.assignments: list[dict] = []
        self.problems: list[dict] = []
        self.picked: list[dict] = []
        self.job_out = ""
        self.code_zip = ""
        self.busy = False

        self._style()
        self._vars()
        self._layout()
        self._load_cookies()
        self._load_settings()
        self.after(300, self._auto_status)

    # ---------------- 外观 ----------------
    def _style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=BG, foreground=FG, fieldbackground=BG2,
                     bordercolor=BG3, lightcolor=BG3, darkcolor=BG)
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=BG2)
        st.configure("TLabel", background=BG, foreground=FG,
                     font=("Microsoft YaHei UI", 10))
        st.configure("Muted.TLabel", background=BG, foreground=MUTED,
                     font=("Microsoft YaHei UI", 9))
        st.configure("H1.TLabel", background=BG, foreground=FG,
                     font=("Microsoft YaHei UI", 18, "bold"))
        st.configure("H2.TLabel", background=BG2, foreground=FG,
                     font=("Microsoft YaHei UI", 12, "bold"))
        st.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(10, 5))
        st.configure("Accent.TButton", background=ACCENT, foreground="white",
                     font=("Microsoft YaHei UI", 10, "bold"), padding=(14, 7))
        st.map("Accent.TButton", background=[("active", "#c92422")])
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=BG2, foreground=MUTED,
                     padding=(16, 8), font=("Microsoft YaHei UI", 10))
        st.map("TNotebook.Tab", background=[("selected", BG3)],
               foreground=[("selected", FG)])
        st.configure("TEntry", fieldbackground=BG2, foreground=FG,
                     insertcolor=FG, padding=6)
        st.configure("TCombobox", fieldbackground=BG2, foreground=FG,
                     background=BG3, arrowcolor=FG, padding=4)
        self.option_add("*TCombobox*Listbox.background", BG2)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        st.configure("Treeview", background=BG2, fieldbackground=BG2,
                     foreground=FG, rowheight=28, borderwidth=0,
                     font=("Microsoft YaHei UI", 10))
        st.configure("Treeview.Heading", background=BG3, foreground=FG,
                     font=("Microsoft YaHei UI", 10, "bold"), padding=6)
        st.map("Treeview", background=[("selected", "#2a7d6f")])
        st.configure("Horizontal.TProgressbar", background=GOLD,
                     troughcolor=BG2, borderwidth=0)

    def _vars(self):
        self.v_status = tk.StringVar(value="未登录")
        self.v_login_msg = tk.StringVar(value="")
        self.v_course = tk.StringVar()
        self.v_assign = tk.StringVar()
        self.v_session = tk.StringVar(value="第五次")
        self.v_zu = tk.StringVar(value="第二组")
        self.v_hao = tk.StringVar(value="3 号")
        self.v_klass = tk.StringVar(value="计科 2304")
        self.v_name = tk.StringVar(value="")
        self.v_sid = tk.StringVar(value="")
        self.v_cover = tk.StringVar(value="")
        self.v_base = tk.StringVar(value="https://api.deepseek.com/v1")
        self.v_key = tk.StringVar()
        self.v_model = tk.StringVar(value="deepseek-chat")
        self.v_hint = tk.StringVar(value="")
        self.v_prog = tk.DoubleVar(value=0.0)
        for v in (self.v_session, self.v_zu, self.v_hao, self.v_klass, self.v_name, self.v_sid):
            v.trace_add("write", lambda *_: self._refresh_cover())

    # ---------------- 布局 ----------------
    def _layout(self):
        head = ttk.Frame(self, padding=(26, 16, 26, 4))
        head.pack(fill="x")
        ttk.Label(head, text="小班课课件生成器", style="H1.TLabel").pack(side="left")
        ttk.Label(head, text=f"  HNU · 桌面版 v{__version__}", style="Muted.TLabel").pack(side="left", padx=(8, 0), pady=(6, 0))
        ttk.Label(head, textvariable=self.v_status, style="Muted.TLabel").pack(side="right")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=26, pady=(8, 8))
        self.nb = nb
        self.tab_login = ttk.Frame(nb, padding=18)
        self.tab_pick = ttk.Frame(nb, padding=12)
        self.tab_me = ttk.Frame(nb, padding=18)
        self.tab_ai = ttk.Frame(nb, padding=18)
        self.tab_gen = ttk.Frame(nb, padding=18)
        nb.add(self.tab_login, text=" 1 登录 ")
        nb.add(self.tab_pick, text=" 2 选题 ")
        nb.add(self.tab_me, text=" 3 个人信息 ")
        nb.add(self.tab_ai, text=" 4 AI 设置 ")
        nb.add(self.tab_gen, text=" 5 生成 ")

        self._tab_login()
        self._tab_pick()
        self._tab_me()
        self._tab_ai()
        self._tab_gen()

        bar = ttk.Frame(self, padding=(26, 0, 26, 12))
        bar.pack(fill="x")
        ttk.Label(bar, text=f"v{__version__} · 仅供课程学习使用", style="Muted.TLabel").pack(side="left")

    def _card(self, parent, title):
        box = tk.Frame(parent, bg=BG2, highlightbackground=BG3, highlightthickness=1)
        box.pack(fill="x", pady=(0, 14))
        ttk.Label(box, text=title, style="H2.TLabel").pack(anchor="w", padx=16, pady=(12, 6))
        inner = tk.Frame(box, bg=BG2)
        inner.pack(fill="x", padx=16, pady=(0, 14))
        return inner

    # ---------------- tab1 登录 ----------------
    def _tab_login(self):
        inner = self._card(self.tab_login, "登录 CG 平台")
        ttk.Label(inner, text="点击下面的按钮，会弹出一个独立的浏览器窗口。\n"
                              "请在里面输入账号、密码和验证码；程序只读取登录状态，不保存密码。",
                  style="Muted.TLabel", justify="left").pack(anchor="w", pady=(0, 12))
        row = tk.Frame(inner, bg=BG2)
        row.pack(anchor="w")
        self.btn_login = ttk.Button(row, text="打开浏览器登录", style="Accent.TButton",
                                    command=self.do_login)
        self.btn_login.pack(side="left")
        ttk.Button(row, text="刷新登录状态", command=self._auto_status).pack(side="left", padx=10)
        ttk.Label(inner, textvariable=self.v_login_msg, style="Muted.TLabel").pack(anchor="w", pady=(12, 0))

    # ---------------- tab2 选题 ----------------
    def _tab_pick(self):
        top = tk.Frame(self.tab_pick, bg=BG2, highlightbackground=BG3, highlightthickness=1)
        top.pack(fill="x", pady=(0, 10))
        row = tk.Frame(top, bg=BG2)
        row.pack(fill="x", padx=14, pady=12)
        ttk.Label(row, text="课程").pack(side="left")
        self.cb_course = DarkCombo(row, width=24, on_change=self.load_assignments)
        self.cb_course.pack(side="left", padx=(6, 16))
        ttk.Label(row, text="作业").pack(side="left")
        self.cb_assign = DarkCombo(row, width=30, on_change=self.load_problems)
        self.cb_assign.pack(side="left", padx=(6, 16))
        ttk.Button(row, text="重新加载", command=self.load_courses).pack(side="left")
        ttk.Button(row, text="＋ 外源题目", command=self.add_oj_problem).pack(side="left", padx=(8, 0))

        body = tk.Frame(self.tab_pick, bg=BG2, highlightbackground=BG3, highlightthickness=1)
        body.pack(fill="both", expand=True, pady=(0, 10))
        ttk.Label(body, text="题目（点「☐」勾选；右键可改题型）", style="H2.TLabel").pack(anchor="w", padx=14, pady=(10, 6))
        cols = ("sel", "no", "kind", "title")
        self.tv = ttk.Treeview(body, columns=cols, show="headings", height=7)
        for c, t, w in (("sel", "选", 46), ("no", "题号", 60), ("kind", "题型", 110), ("title", "题目", 640)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w, anchor="w" if c == "title" else "center", stretch=(c == "title"))
        self.tv.pack(fill="both", expand=True, padx=14)
        self.tv.bind("<Button-1>", self._tv_click)
        self.tv.bind("<Button-3>", self._tv_menu)
        self.tv.bind("<Double-1>", self._tv_double)
        self._menu = tk.Menu(self, tearoff=0, bg=BG2, fg=FG, activebackground=BG3)
        for k in KINDS:
            self._menu.add_command(label=f"改为{k}", command=lambda kk=k: self._set_kind(kk))

        pick = tk.Frame(self.tab_pick, bg=BG2, highlightbackground=BG3, highlightthickness=1)
        pick.pack(fill="x")
        head = tk.Frame(pick, bg=BG2)
        head.pack(fill="x", padx=14, pady=(10, 4))
        self.lb_pick = ttk.Label(head, text="已选题目（0 道）", style="H2.TLabel")
        self.lb_pick.pack(side="left")
        ttk.Button(head, text="清空", command=self.clear_picked).pack(side="right")
        self.tv_pick = ttk.Treeview(pick, columns=("no", "assign", "kind", "title", "code"),
                                    show="headings", height=3)
        for c, t, w in (("no", "题号", 60), ("assign", "作业", 220), ("kind", "题型", 100),
                        ("title", "题目", 480), ("code", "代码", 90)):
            self.tv_pick.heading(c, text=t)
            self.tv_pick.column(c, width=w, anchor="w" if c in ("assign", "title") else "center")
        self.tv_pick.pack(fill="x", padx=14, pady=(0, 6))
        self.tv_pick.bind("<Double-1>", lambda e: self.edit_code())
        btns = tk.Frame(pick, bg=BG2)
        btns.pack(fill="x", padx=14, pady=(0, 12))
        ttk.Button(btns, text="上传 / 编辑代码", command=self.edit_code).pack(side="left")
        ttk.Button(btns, text="修改题型", command=self._pick_kind_dialog).pack(side="left", padx=8)
        ttk.Button(btns, text="移除", command=self.remove_picked).pack(side="left")

    # ---------------- tab3 个人信息 ----------------
    def _tab_me(self):
        inner = self._card(self.tab_me, "个人信息（显示在封面）")
        grid = tk.Frame(inner, bg=BG2)
        grid.pack(fill="x")
        fields = [("第几次", self.v_session), ("第几组", self.v_zu), ("第几号", self.v_hao),
                  ("班级", self.v_klass), ("姓名", self.v_name), ("学号", self.v_sid)]
        for i, (lab, var) in enumerate(fields):
            r, c = divmod(i, 3)
            ttk.Label(grid, text=lab, style="Muted.TLabel").grid(row=r * 2, column=c, sticky="w", padx=6, pady=(6, 2))
            ttk.Entry(grid, textvariable=var).grid(row=r * 2 + 1, column=c, sticky="ew", padx=6, pady=(0, 8))
        for c in range(3):
            grid.columnconfigure(c, weight=1)

        prev = tk.Frame(inner, bg=BG3, highlightbackground=GOLD, highlightthickness=1)
        prev.pack(fill="x", pady=(10, 4))
        ttk.Label(prev, text="封面预览", style="Muted.TLabel").pack(anchor="w", padx=12, pady=(8, 0))
        self.lb_title = ttk.Label(prev, text="", background=BG3, foreground=FG,
                                  font=("Microsoft YaHei UI", 16, "bold"))
        self.lb_title.pack(anchor="w", padx=12, pady=(6, 2))
        self.lb_meta = ttk.Label(prev, text="", background=BG3, foreground=FG,
                                 font=("Microsoft YaHei UI", 11), justify="left")
        self.lb_meta.pack(anchor="w", padx=12, pady=(0, 12))
        self._refresh_cover()

    # ---------------- tab4 AI ----------------
    def _tab_ai(self):
        inner = self._card(self.tab_ai, "AI 接口（生成思路分析与逐行讲解）")
        ttk.Label(inner, text="兼容 OpenAI 协议的服务都可以用（DeepSeek、通义、Kimi、本地 Ollama 等）。",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        g = tk.Frame(inner, bg=BG2)
        g.pack(fill="x")
        ttk.Label(g, text="Base URL", style="Muted.TLabel").grid(row=0, column=0, sticky="w", padx=6)
        ttk.Entry(g, textvariable=self.v_base, width=46).grid(row=1, column=0, sticky="ew", padx=6)
        ttk.Label(g, text="API Key", style="Muted.TLabel").grid(row=0, column=1, sticky="w", padx=6)
        self.ent_key = ttk.Entry(g, textvariable=self.v_key, width=40, show="*")
        self.ent_key.grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Label(g, text="模型", style="Muted.TLabel").grid(row=2, column=0, sticky="w", padx=6, pady=(8, 0))
        self.cb_model = DarkCombo(g, width=30)
        self.cb_model.set_values(["deepseek-chat", "deepseek-reasoner"])
        self.cb_model.grid(row=3, column=0, sticky="w", padx=6)
        row = tk.Frame(inner, bg=BG2)
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="获取可用模型", command=self.fetch_models).pack(side="left")
        ttk.Button(row, text="保存设置", command=self.save_ai).pack(side="left", padx=8)
        self.lb_hint = ttk.Label(inner, textvariable=self.v_hint, style="Muted.TLabel")
        self.lb_hint.pack(anchor="w", pady=(8, 0))

    # ---------------- tab5 生成 ----------------
    def _tab_gen(self):
        inner = self._card(self.tab_gen, "生成课件")
        ttk.Label(inner, text="确认前面四步已完成，然后点下面的按钮。生成过程会逐题抓题、调用 AI、本地编译样例并排版。",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        row = tk.Frame(inner, bg=BG2)
        row.pack(fill="x")
        self.btn_build = ttk.Button(row, text="开始生成课件", style="Accent.TButton", command=self.start_build)
        self.btn_build.pack(side="left")
        self.btn_ppt = ttk.Button(row, text="打开 PPTX", state="disabled", command=self.open_ppt)
        self.btn_ppt.pack(side="left", padx=8)
        self.btn_zip = ttk.Button(row, text="打开代码包", state="disabled", command=self.open_zip)
        self.btn_zip.pack(side="left")
        self.btn_dir = ttk.Button(row, text="打开结果文件夹", command=self.open_out_dir)
        self.btn_dir.pack(side="left", padx=(8, 0))
        self.pb = ttk.Progressbar(inner, variable=self.v_prog, maximum=1.0)
        self.pb.pack(fill="x", pady=(12, 8))
        self.log = tk.Text(inner, height=16, bg=BG, fg=FG, insertbackground=FG,
                           relief="flat", font=("Consolas", 10), wrap="word")
        self.log.pack(fill="both", expand=True)

    # ---------------- 数据 ----------------
    def _load_cookies(self):
        try:
            from .cli import load_cookies
            self.cookies = load_cookies()
        except Exception:  # noqa: BLE001
            self.cookies = {}
        if self.cookies:
            self.client = CGClient(cookies=self.cookies)

    def _auto_status(self):
        if not self.client:
            self.v_status.set("未登录")
            return
        threading.Thread(target=self._auto_status_worker, daemon=True).start()

    def _auto_status_worker(self):
        try:
            ok = self.client.is_logged_in()
            name = self.client.whoami() if ok else ""
            self.after(0, lambda: self.v_status.set(f"已登录 {name}".strip() if ok else "未登录"))
            if ok:
                self.after(0, self.load_courses)
        except Exception:  # noqa: BLE001
            self.after(0, lambda: self.v_status.set("未登录"))

    def do_login(self):
        if self.busy:
            return
        self.busy = True
        self.v_login_msg.set("已打开浏览器，请在浏览器里完成登录……")
        threading.Thread(target=self._login_worker, daemon=True).start()

    def _login_worker(self):
        try:
            cookies, _ = login_with_browser(on_wait=lambda m: self.after(0, lambda: self.v_login_msg.set(m)))
            from .cli import save_cookies
            save_cookies(cookies)
            self.cookies = cookies
            self.client = CGClient(cookies=cookies)
            self.after(0, lambda: self.v_login_msg.set("登录成功，可以切到「2 选题」了。"))
            self.after(0, self.load_courses)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            self.after(0, lambda: self.v_login_msg.set(f"登录失败：{msg}"))
        finally:
            self.busy = False

    def load_courses(self):
        if self.busy or not self.client:
            return
        self.busy = True
        threading.Thread(target=self._courses_worker, daemon=True).start()

    def _courses_worker(self):
        try:
            self.courses = self.client.courses()
            vals = [_g(c, "name") for c in self.courses]
            self.after(0, lambda: self.cb_course.set_values(vals))
            if vals:
                self.after(0, lambda: self.cb_course.set_index(0))
                self.busy = False
                self.after(80, self.load_assignments)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            self.after(0, lambda m=msg: self.v_login_msg.set(f"加载课程失败：{m}"))
        finally:
            self.busy = False

    def load_assignments(self):
        if self.busy or not self.client:
            return
        idx = self.cb_course.current()
        if idx < 0:
            return
        course = self.courses[idx]
        self.busy = True
        threading.Thread(target=self._assign_worker, args=(_g(course, "id"),), daemon=True).start()

    def _assign_worker(self, course_id):
        try:
            self.assignments = self.client.assignments(course_id)
            vals = [_g(a, "name") for a in self.assignments]
            self.after(0, lambda: self.cb_assign.set_values(vals))
            if vals:
                self.after(0, lambda: self.cb_assign.set_index(0))
                self.busy = False
                self.after(80, self.load_problems)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            self.after(0, lambda m=msg: self.v_login_msg.set(f"加载作业失败：{m}"))
        finally:
            self.busy = False

    def load_problems(self):
        if self.busy or not self.client:
            return
        idx = self.cb_assign.current()
        if idx < 0:
            return
        aid = _g(self.assignments[idx], "id")
        self.busy = True
        threading.Thread(target=self._problems_worker, args=(aid,), daemon=True).start()

    def _problems_worker(self, aid):
        try:
            self.problems = self.client.problems(aid)
            self.after(0, self._fill_problems)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            self.after(0, lambda m=msg: self.v_login_msg.set(f"加载题目失败：{m}"))
        finally:
            self.busy = False

    def _fill_problems(self):
        self.tv.delete(*self.tv.get_children())
        for p in self.problems:
            kind = _g(p, "kind") or guess_kind(_g(p, "title"))
            mark = "☑" if self._is_picked(self.cb_assign.current(), p) else "☐"
            self.tv.insert("", "end", values=(mark, _g(p, "index"), kind, _g(p, "title")))

    # ---------------- 选题 ----------------
    def _current_assign(self):
        i = self.cb_assign.current()
        return self.assignments[i] if 0 <= i < len(self.assignments) else None

    def _uid(self, assign_id, p):
        return f"{assign_id}|{_g(p, 'index')}|{_g(p, 'problem_id')}"

    def _is_picked(self, ai, p):
        a = self._current_assign()
        if not a:
            return False
        return any(x["uid"] == self._uid(_g(a, "id"), p) for x in self.picked)

    def _tv_click(self, e):
        row = self.tv.identify_row(e.y)
        col = self.tv.identify_column(e.x)
        if not row or col != "#1":
            return
        vals = self.tv.item(row, "values")
        a = self._current_assign()
        if not a:
            return
        idx = self.tv.index(row)
        p = self.problems[idx]
        if vals[0] == "☑":
            self.picked = [x for x in self.picked if x["uid"] != self._uid(_g(a, "id"), p)]
        else:
            self.picked.append({
                "uid": self._uid(_g(a, "id"), p), "assign_id": _g(a, "id"), "assign_name": _g(a, "name"),
                "index": _g(p, "index"), "problem_id": _g(p, "problem_id"),
                "via": _g(p, "via"), "kind": _g(p, "kind") or guess_kind(_g(p, "title")),
                "title": _g(p, "title"), "user_code": "",
            })
        self.tv.set(row, "sel", "☑" if vals[0] == "☐" else "☐")
        self._refresh_picked()

    def _tv_menu(self, e):
        row = self.tv.identify_row(e.y)
        if not row:
            return
        self.tv.selection_set(row)
        self.tv.focus(row)
        self._menu.tk_popup(e.x_root, e.y_root)

    def _set_kind(self, kind):
        row = self.tv.focus()
        if not row:
            return
        a = self._current_assign()
        if not a:
            return
        idx = self.tv.index(row)
        p = self.problems[idx]
        uid = self._uid(_g(a, "id"), p)
        for x in self.picked:
            if x["uid"] == uid:
                x["kind"] = kind
        self.tv.set(row, "kind", kind)
        self._refresh_picked()

    def _tv_double(self, e):
        row = self.tv.identify_row(e.y)
        if not row:
            return
        idx = self.tv.index(row)
        if 0 <= idx < len(self.problems):
            self.show_problem(self.problems[idx])

    def show_problem(self, p):
        a = self._current_assign()
        win = tk.Toplevel(self)
        win.title("题面预览 · " + _g(p, "title")[:40])
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(860, sw - 80), min(660, sh - 100)
        win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        win.configure(bg=BG)
        head = tk.Frame(win, bg=BG2)
        head.pack(fill="x")
        ttk.Label(head, text=_g(p, "title"), style="H2.TLabel",
                  wraplength=w - 60).pack(anchor="w", padx=16, pady=10)
        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True)
        txt = tk.Text(body, bg=BG, fg=FG, insertbackground=FG, relief="flat",
                      wrap="word", font=("Microsoft YaHei UI", 10), padx=16, pady=12)
        sb = ttk.Scrollbar(body, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)
        detail = _g(p, "detail")
        if detail:
            txt.insert("1.0", detail)
            txt.configure(state="disabled")
        else:
            txt.insert("1.0", "正在加载题面……")
            threading.Thread(target=self._detail_worker, args=(txt, a, p), daemon=True).start()

    @staticmethod
    def _clean_statement(text, title=""):
        junk = {"代码执行结果", "关闭控制台", "控制台", "提交", "本地草稿箱",
                "提示", "离开或者关闭页面前注意提交代码", "样例文件", "×"}
        out = []
        for line in text.splitlines():
            t = line.strip()
            if not t:
                if out and out[-1] != "":
                    out.append("")
                continue
            if t in junk:
                continue
            if t.startswith("样例文件 ") or t.startswith("样例文件："):
                continue
            if title and (t == title or t == f"1. {title}"):
                continue
            out.append(line.rstrip())
        while out and not out[0].strip():
            out.pop(0)
        while out and not out[-1].strip():
            out.pop()
        return "\n".join(out).strip() or "（没有取到题面）"

    def _detail_worker(self, txt, a, p):
        try:
            html = self.client.problem_html(_g(a, "id"), _g(p, "index"),
                                            _g(p, "problem_id"), _g(p, "via"))
            q = parse_problem(html, _g(a, "id"), _g(p, "index"))
            parts = [q.description or ""]
            if q.input_form:
                parts.append("【输入形式】\n" + q.input_form)
            if q.output_form:
                parts.append("【输出形式】\n" + q.output_form)
            if q.code:
                parts.append("【代码模板】\n" + q.code)
            text = self._clean_statement("\n\n".join(x for x in parts if x), _g(p, "title"))
            bad = ("先看看参考答案", "您确认现在在查看答案", "本关卡得分将扣除", "提交代码")
            if any(b in text for b in bad) or len(text.strip()) < 30:
                if _g(p, "via") in ("content", ""):
                    url = f"{BASE}/assignment/problemContent.jsp?problemID={_g(p, 'problem_id')}"
                else:
                    url = (f"{BASE}/assignment/programList.jsp?proNum={_g(p, 'index')}"
                           f"&assignID={_g(a, 'id')}")
                text = ("这道题的题面没有直接暴露在接口里（拿到了提交确认页）。\n\n"
                        "请在平台打开完整题面：\n" + url)

            def upd():
                txt.configure(state="normal")
                txt.delete("1.0", "end")
                txt.insert("1.0", text)
                txt.configure(state="disabled")
            self.after(0, upd)
        except Exception as e:  # noqa: BLE001
            msg = str(e)

            def err():
                txt.configure(state="normal")
                txt.delete("1.0", "end")
                txt.insert("1.0", "加载题面失败：" + msg)
                txt.configure(state="disabled")
            self.after(0, err)

    def _pick_kind_dialog(self):
        sel = self.tv_pick.selection()
        if not sel:
            return
        i = self.tv_pick.index(sel[0])
        cur = self.picked[i]["kind"]
        win = tk.Toplevel(self)
        win.title("修改题型")
        win.configure(bg=BG)
        win.transient(self)
        w, h = 340, 200
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = self.winfo_rooty() + 120
        win.geometry(f"{w}x{h}+{x}+{y}")
        ttk.Label(win, text="题型", style="Muted.TLabel").pack(pady=(18, 6))
        cb = DarkCombo(win, width=22)
        cb.set_values(KINDS, select=KINDS.index(cur) if cur in KINDS else 0)
        cb.pack(padx=28, pady=4, fill="x")

        def ok():
            self.picked[i]["kind"] = cb.get()
            win.destroy()
            self._refresh_picked()

        ttk.Button(win, text="确定", style="Accent.TButton", command=ok).pack(pady=16)

    def add_oj_problem(self):
        win = tk.Toplevel(self)
        win.title("添加外源题目")
        win.configure(bg=BG)
        w, h = 640, 300
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        win.transient(self)
        ttk.Label(win, text="粘贴题目网址（洛谷 / AtCoder / LeetCode / Codeforces 等）",
                  style="H2.TLabel").pack(anchor="w", padx=18, pady=(18, 6))
        entry = ttk.Entry(win, font=("Consolas", 10))
        entry.pack(fill="x", padx=18)
        entry.insert(0, "https://")
        tip = tk.StringVar(value="抓取题面后按「编程题」加入已选题目，与 CG 题目一起生成。")
        ttk.Label(win, textvariable=tip, style="Muted.TLabel", wraplength=w - 40).pack(anchor="w", padx=18, pady=8)
        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=18, pady=(4, 12))
        go = ttk.Button(btns, text="抓取题面", style="Accent.TButton")
        go.pack(side="right")
        ttk.Button(btns, text="取消", command=win.destroy).pack(side="right", padx=8)

        def start():
            url = entry.get().strip()
            if not url or url == "https://":
                tip.set("请先填写题目网址")
                return
            go.configure(state="disabled")
            tip.set("正在抓取，请稍候…")

            def worker():
                try:
                    from .oj import fetch_problem
                    data = fetch_problem(url)
                    def done():
                        self.picked.append({
                            "uid": "oj|" + url, "assign_id": "", "assign_name": data["source"],
                            "index": "OJ", "problem_id": url, "via": "oj",
                            "kind": "编程题", "title": data["title"], "user_code": "",
                            "oj": {
                                "source": data["source"], "url": url, "title": data["title"],
                                "description": data["description"], "input_form": data["input_form"],
                                "output_form": data["output_form"],
                                "samples": [[c.input, c.output] for c in data["samples"]],
                                "note": data.get("note", ""),
                            },
                        })
                        self._refresh_picked()
                        win.destroy()
                    self.after(0, done)
                except Exception as e:  # noqa: BLE001
                    msg = str(e)
                    def fail():
                        go.configure(state="normal")
                        tip.set("抓取失败：" + msg)
                    self.after(0, fail)

            threading.Thread(target=worker, daemon=True).start()

        go.configure(command=start)

    def _refresh_picked(self):
        self.tv_pick.delete(*self.tv_pick.get_children())
        for p in self.picked:
            code = "已上传" if p.get("user_code") else "—"
            self.tv_pick.insert("", "end", values=(p["index"], p["assign_name"], p["kind"], p["title"], code))
        self.lb_pick.configure(text=f"已选题目（{len(self.picked)} 道）")
        kids = self.tv_pick.get_children()
        if kids and not self.tv_pick.selection():
            self.tv_pick.selection_set(kids[0])

    def remove_picked(self):
        sel = self.tv_pick.selection()
        if not sel:
            return
        i = self.tv_pick.index(sel[0])
        self.picked.pop(i)
        self._refresh_picked()
        self._fill_problems()

    def clear_picked(self):
        if self.picked and messagebox.askyesno("清空", "确定清空已选题目？"):
            self.picked = []
            self._refresh_picked()
            self._fill_problems()

    def edit_code(self):
        sel = self.tv_pick.selection()
        if not sel:
            if len(self.picked) == 1:
                i = 0
            else:
                messagebox.showinfo("提示", "请先在「已选题目」里选中一道题")
                return
        else:
            i = self.tv_pick.index(sel[0])
        p = self.picked[i]
        if p["kind"] != "编程题":
            messagebox.showinfo("提示", "只有「编程题」支持上传代码")
            return
        CodeDialog(self, p, on_ok=self._refresh_picked)

    # ---------------- 个人信息 ----------------
    def _refresh_cover(self):
        title = (self.v_session.get().strip() or "第 N 次") + "小班课"
        group = " ".join(x for x in (self.v_zu.get().strip(), self.v_hao.get().strip()) if x)
        self.lb_title.configure(text=title)
        self.lb_meta.configure(text=f"{group}\n{self.v_klass.get().strip()}　{self.v_name.get().strip()}\n学号：{self.v_sid.get().strip()}")

    # ---------------- AI ----------------
    def _load_settings(self):
        s = saved_settings.load()
        if s.get("base_url"):
            self.v_base.set(s["base_url"])
        if s.get("model"):
            self.v_model.set(s["model"])
            self.cb_model.set(s["model"])
        if s.get("api_key"):
            self.v_key.set(s["api_key"])

    def save_ai(self):
        saved_settings.save(self.v_base.get().strip(), self.cb_model.get().strip(), self.v_key.get().strip())
        self.v_hint.set("已保存（Key 用 Windows DPAPI 加密存在本机）。")

    def fetch_models(self):
        key = self.v_key.get().strip() or saved_settings.load().get("api_key", "")
        base = self.v_base.get().strip()
        self.v_hint.set("正在获取可用模型……")
        threading.Thread(target=self._models_worker, args=(base, key), daemon=True).start()

    def _models_worker(self, base, key):
        try:
            from .gui import _list_models
            r = _list_models(base, key)
            if r.get("ok"):
                models = r["models"]

                def done():
                    self.cb_model.set_values(models)
                    if models:
                        self.cb_model.set_index(0)
                    self.v_hint.set("已获取 %d 个可用模型：%s" % (len(models), " / ".join(models[:6])))
                self.after(0, done)
            else:
                self.after(0, lambda: self.v_hint.set("获取模型失败：" + r.get("error", "")))
        except Exception as e:  # noqa: BLE001
            self.after(0, lambda: self.v_hint.set(f"获取模型失败：{e}"))

    # ---------------- 生成 ----------------
    def start_build(self):
        if self.busy:
            return
        if not self.picked:
            messagebox.showinfo("提示", "请先在「2 选题」里勾选至少一道题")
            return
        if not self.v_name.get().strip():
            messagebox.showinfo("提示", "请先在「3 个人信息」里填写姓名")
            return
        out_dir = os.path.join(data_dir(), "out")
        os.makedirs(out_dir, exist_ok=True)
        stem = "小班课件_" + datetime.now().strftime("%Y-%m-%d_%H%M%S")
        out = os.path.join(out_dir, stem + ".pptx")
        n = 2
        while os.path.exists(out) or os.path.exists(os.path.splitext(out)[0] + "_代码.zip"):
            out = os.path.join(out_dir, f"{stem}-{n}.pptx")
            n += 1
        cfg = {
            "meta": {"session": self.v_session.get().strip(), "group": " ".join(
                x for x in (self.v_zu.get().strip(), self.v_hao.get().strip()) if x),
                "klass": self.v_klass.get().strip(), "name": self.v_name.get().strip(),
                "student_id": self.v_sid.get().strip()},
            "llm": {"base_url": self.v_base.get().strip(), "api_key": self.v_key.get().strip(),
                    "model": self.cb_model.get().strip()},
            "problems": [{k: p.get(k, "") for k in ("assign_id", "index", "problem_id", "via", "kind", "title", "user_code")}
                         for p in self.picked],
            "out": out, "template": TEMPLATE, "run_code": True,
        }
        for p, src in zip(cfg["problems"], self.picked):
            p["ptype"] = src["kind"]
            p["assignment"] = src["assign_name"]
            if src.get("oj"):
                p["oj"] = src["oj"]
        self.busy = True
        self.btn_build.configure(state="disabled")
        self.btn_ppt.configure(state="disabled")
        self.btn_zip.configure(state="disabled")
        self.btn_zip.configure(state="disabled")
        self.v_prog.set(0.0)
        self.log.delete("1.0", "end")
        self.nb.select(self.tab_gen)
        threading.Thread(target=self._build_worker, args=(cfg,), daemon=True).start()

    def _build_worker(self, cfg):
        job = BuildJob.from_dict(cfg, base_dir=APP_DIR)

        def prog(msg, frac=None):
            def upd():
                self.log.insert("end", msg + "\n")
                self.log.see("end")
                if frac is not None:
                    self.v_prog.set(max(0.0, min(1.0, frac)))
            self.after(0, upd)

        try:
            client = self.client or CGClient(cookies=self.cookies)
            out = build(job, client, Progress(prog))
            code_zip = os.path.splitext(out)[0] + "_代码.zip"
            self.job_out = out
            self.code_zip = code_zip if os.path.exists(code_zip) else ""
            self.after(0, lambda: self.v_prog.set(1.0))
            self.after(0, self.log.see, "end")
            self.after(0, lambda: self.btn_ppt.configure(state="normal"))
            if self.code_zip:
                self.after(0, lambda: self.btn_zip.configure(state="normal"))
        except Exception as e:  # noqa: BLE001
            tb = traceback.format_exc()
            msg = str(e)
            self.after(0, lambda m=msg, t=tb: self.log.insert("end", f"生成失败：{m}\n{t}\n"))
            self.after(0, messagebox.showerror, "生成失败", msg)
        finally:
            self.busy = False
            self.after(0, lambda: self.btn_build.configure(state="normal"))

    def open_ppt(self):
        if self.job_out and os.path.exists(self.job_out):
            os.startfile(self.job_out)  # noqa: S606

    def open_out_dir(self):
        d = os.path.dirname(self.job_out) if self.job_out else os.path.join(data_dir(), "out")
        os.makedirs(d, exist_ok=True)
        try:
            os.startfile(d)  # noqa: S606
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("打开失败", str(e))

    def open_zip(self):
        if self.code_zip and os.path.exists(self.code_zip):
            os.startfile(self.code_zip)  # noqa: S606

    def reveal(self, path):
        if path and os.path.exists(path):
            try:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            except Exception:  # noqa: BLE001
                os.startfile(os.path.dirname(path))  # noqa: S606


class CodeDialog(tk.Toplevel):
    def __init__(self, master, problem, on_ok):
        super().__init__(master)
        self.problem = problem
        self.on_ok = on_ok
        self.orig = (problem.get("user_code") or "").strip()
        self.title(f"上传代码 · {problem['title']}")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(820, sw - 80), min(620, sh - 100)
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self.configure(bg=BG)
        self.transient(master)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text="粘贴代码，或从文件载入 .cpp/.cc/.c/.txt。\n"
                            "编辑完必须点右下角「确认上传」才会保存；直接关窗口会提示。",
                  style="Muted.TLabel", justify="left", wraplength=w - 60).grid(
                      row=0, column=0, sticky="w", padx=18, pady=(14, 6))
        row = tk.Frame(self, bg=BG)
        row.grid(row=1, column=0, sticky="ew", padx=18)
        ttk.Button(row, text="选择文件…", command=self.load_file).pack(side="left")
        ttk.Button(row, text="清空", command=self.clear).pack(side="left", padx=8)

        body = tk.Frame(self, bg=BG)
        body.grid(row=2, column=0, sticky="nsew", padx=18, pady=10)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.text = tk.Text(body, bg=BG2, fg=FG, insertbackground=FG, relief="flat",
                            font=("Consolas", 10), wrap="none", undo=True)
        ysb = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        xsb = ttk.Scrollbar(body, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        self.text.insert("1.0", problem.get("user_code", ""))
        self.text.edit_reset()
        self.text.bind("<Key>", self._mark_dirty)

        bar = tk.Frame(self, bg=BG)
        bar.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 14))
        self.status = tk.StringVar(value="未修改" if self.orig else "还没有代码")
        ttk.Label(bar, textvariable=self.status, style="Muted.TLabel").pack(side="left")
        ttk.Button(bar, text="确认上传", style="Accent.TButton", command=self.ok).pack(side="right")
        ttk.Button(bar, text="取消", command=self.try_close).pack(side="right", padx=8)

        self.protocol("WM_DELETE_WINDOW", self.try_close)
        self.bind("<Control-s>", lambda e: self.ok())
        self.after(200, self.text.focus_set)

    def _mark_dirty(self, _e=None):
        if self.text.get("1.0", "end").strip() != self.orig:
            self.status.set("有未保存的修改")

    def _dirty(self):
        return self.text.get("1.0", "end").strip() != self.orig

    def clear(self):
        self.text.delete("1.0", "end")
        self.status.set("已清空，点「确认上传」保存")

    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[("代码文件", "*.cpp *.cc *.c *.txt"), ("所有文件", "*.*")])
        if not path:
            return
        for enc in ("utf-8", "gb18030", "utf-16"):
            try:
                with open(path, encoding=enc) as f:
                    content = f.read()
                self.text.delete("1.0", "end")
                self.text.insert("1.0", content)
                self.status.set(f"已载入 {os.path.basename(path)}（点「确认上传」保存）")
                return
            except Exception:  # noqa: BLE001
                continue
        messagebox.showerror("读取失败", "无法识别文件编码")

    def ok(self):
        code = self.text.get("1.0", "end").strip()
        if not code and self.orig:
            if not messagebox.askyesno("清空代码", "代码内容为空，确定清空已保存的代码？"):
                return
        self.problem["user_code"] = code
        self.on_ok()
        self.destroy()

    def try_close(self):
        if self._dirty():
            r = messagebox.askyesnocancel("未保存", "代码还没保存，要先保存再关闭吗？")
            if r is None:
                return
            if r:
                self.ok()
                return
        self.destroy()


def main():
    _ui()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
