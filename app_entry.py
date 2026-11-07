# -*- coding: utf-8 -*-
"""桌面入口：默认启动独立桌面界面；--web 为旧的本地网页模式。"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback


def _fatal(msg: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg[-1500:], "湖大课件生成器 · 启动失败", 0x10)
    except Exception:  # noqa: BLE001
        print(msg)


def _dpi() -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass


def web_main() -> None:
    """旧的浏览器模式：后台起本地服务 + 控制窗。"""
    from hnuclass.gui import serve

    state: dict[str, str] = {}

    def run() -> None:
        try:
            serve(port=8765, open_browser=False,
                  on_ready=lambda url: state.setdefault("url", url))
        except Exception:  # noqa: BLE001
            _fatal(traceback.format_exc())

    threading.Thread(target=run, daemon=True).start()
    for _ in range(80):
        if "url" in state:
            break
        time.sleep(0.1)
    if "url" not in state:
        _fatal("本地服务没能启动，可能端口被占用。请关掉其他实例后重试。")
        return

    url = state["url"]
    import tkinter as tk
    import webbrowser

    root = tk.Tk()
    root.title("湖大课件生成器")
    root.configure(bg="#123f3a")
    root.resizable(False, False)
    w, h = 520, 225
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")

    tk.Label(root, text="湖大课件生成器", font=("Microsoft YaHei UI", 15, "bold"),
             fg="#ffffff", bg="#123f3a").pack(pady=(22, 2))
    tk.Label(root, text="服务已启动，用完关掉本窗口即可。",
             font=("Microsoft YaHei UI", 9), fg="#bfd8d0", bg="#123f3a",
             wraplength=440, justify="center").pack()

    link = tk.Label(root, text=url, font=("Consolas", 10), fg="#e6b729", bg="#123f3a",
                    cursor="hand2")
    link.pack(pady=10)
    link.bind("<Button-1>", lambda e: webbrowser.open(url))

    box = tk.Frame(root, bg="#123f3a")
    box.pack(pady=6)

    def quit_app() -> None:
        root.destroy()
        os._exit(0)

    tk.Button(box, text="打开页面", command=lambda: webbrowser.open(url), width=12,
              font=("Microsoft YaHei UI", 10), bg="#B01513", fg="white",
              activebackground="#8f100f", activeforeground="white",
              relief="flat", cursor="hand2").pack(side="left", padx=8)
    tk.Button(box, text="退出", command=quit_app, width=10,
              font=("Microsoft YaHei UI", 10), bg="#1e5155", fg="white",
              activebackground="#173f42", activeforeground="white",
              relief="flat", cursor="hand2").pack(side="left", padx=8)

    root.protocol("WM_DELETE_WINDOW", quit_app)
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    root.mainloop()


def main() -> None:
    _dpi()
    if "--web" in sys.argv[1:]:
        web_main()
        return
    from hnuclass.desktop import main as desktop_main
    desktop_main()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        _fatal(traceback.format_exc())
