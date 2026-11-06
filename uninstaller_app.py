# -*- coding: utf-8 -*-
"""安装目录里的 uninstall.exe：删快捷方式、删安装目录（自身退出后由临时脚本删除）。"""
import os
import sys
import tempfile
import subprocess
import tkinter as tk
from tkinter import messagebox

APP_NAME = "湖大课件生成器"


def run_ps(script):
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       creationflags=0x08000000, timeout=15)
    except Exception:
        pass


class Uninstaller(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} 卸载")
        self.configure(bg="#123f3a")
        self.resizable(False, False)
        self.dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
        tk.Label(self, text="卸载 " + APP_NAME, font=("Microsoft YaHei UI", 15, "bold"),
                 fg="white", bg="#123f3a").pack(pady=(20, 6))
        tk.Label(self, text=self.dir, font=("Microsoft YaHei UI", 8), fg="#9fd0c5",
                 bg="#123f3a", wraplength=420).pack(padx=20)
        tk.Label(self, text="登录状态和 API Key 会保留在 %LOCALAPPDATA%\\hnuclass。",
                 font=("Microsoft YaHei UI", 9), fg="#cfe6df", bg="#123f3a").pack(pady=(10, 0))
        btns = tk.Frame(self, bg="#123f3a")
        btns.pack(pady=18)
        tk.Button(btns, text="卸载", command=self.do_uninstall, bg="#B01513", fg="white",
                  font=("Microsoft YaHei UI", 11, "bold"), relief="flat",
                  padx=26, pady=6).pack(side="left", padx=8)
        tk.Button(btns, text="取消", command=self.destroy, bg="#2a4f49", fg="white",
                  font=("Microsoft YaHei UI", 11), relief="flat",
                  padx=22, pady=6).pack(side="left", padx=8)
        self.geometry("460x240")

    def do_uninstall(self, ask=True):
        if ask and not messagebox.askyesno("确认卸载", "确定要删除本程序吗？"):
            return
        desk = os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}.lnk")
        programs = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
        for p in (desk, os.path.join(programs, f"{APP_NAME}.lnk")):
            try:
                os.remove(p)
            except Exception:
                pass
        bat = os.path.join(tempfile.gettempdir(), "hnuclass_uninstall.bat")
        with open(bat, "w", encoding="gbk", errors="ignore") as f:
            f.write("@echo off\r\n")
            f.write("ping -n 3 127.0.0.1 >nul\r\n")
            f.write(f'rmdir /s /q "{self.dir}"\r\n')
            f.write('del "%~f0"\r\n')
        subprocess.Popen(["cmd", "/c", bat], creationflags=0x00000008 | 0x08000000)
        self.destroy()


def silent_uninstall(d):
    desk = os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}.lnk")
    programs = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
    for p in (desk, os.path.join(programs, f"{APP_NAME}.lnk")):
        try:
            os.remove(p)
        except Exception:
            pass
    bat = os.path.join(tempfile.gettempdir(), "hnuclass_uninstall.bat")
    with open(bat, "w", encoding="gbk", errors="ignore") as f:
        f.write("@echo off\r\n")
        f.write("ping -n 3 127.0.0.1 >nul\r\n")
        f.write(f'rmdir /s /q "{d}"\r\n')
        f.write('del "%~f0"\r\n')
    subprocess.Popen(["cmd", "/c", bat], creationflags=0x00000008 | 0x08000000)


if __name__ == "__main__":
    if "--yes" in sys.argv:
        i = sys.argv.index("--yes")
        d = sys.argv[i + 1] if len(sys.argv) > i + 1 else os.path.dirname(os.path.abspath(sys.executable))
        silent_uninstall(d)
    else:
        Uninstaller().mainloop()
