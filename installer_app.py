# -*- coding: utf-8 -*-
"""单文件安装程序：把内置的 app.zip 解压到安装目录，建快捷方式，写入 uninstall.exe。"""
import os
import sys
import shutil
import zipfile
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox

APP_NAME = "湖大课件生成器"
DEFAULT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", "HNUClassPPT")


def res(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def run_ps(script):
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       creationflags=0x08000000, timeout=20)
    except Exception:
        pass


def make_shortcut(target, link):
    run_ps(
        "$ws=New-Object -ComObject WScript.Shell;"
        f"$s=$ws.CreateShortcut('{link}');"
        f"$s.TargetPath='{target}';$s.WorkingDirectory='{os.path.dirname(target)}';"
        f"$s.IconLocation='{target},0';$s.Save()"
    )


class Installer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} 安装程序")
        self.configure(bg="#123f3a")
        self.resizable(False, False)
        try:
            self.iconbitmap(res("app.ico"))
        except Exception:
            pass
        self.dir_var = tk.StringVar(value=DEFAULT_DIR)
        self.status = tk.StringVar(value="")

        tk.Label(self, text=APP_NAME, font=("Microsoft YaHei UI", 18, "bold"),
                 fg="white", bg="#123f3a").pack(pady=(22, 2))
        tk.Label(self, text="HNU Programming Tutorial Deck", font=("Microsoft YaHei UI", 8),
                 fg="#8fc3b8", bg="#123f3a").pack()

        box = tk.Frame(self, bg="#123f3a")
        box.pack(fill="x", padx=24, pady=(18, 6))
        tk.Label(box, text="安装位置", font=("Microsoft YaHei UI", 9), fg="#cfe6df",
                 bg="#123f3a").pack(anchor="w")
        row = tk.Frame(box, bg="#123f3a")
        row.pack(fill="x", pady=(4, 0))
        self.entry = tk.Entry(row, textvariable=self.dir_var, font=("Microsoft YaHei UI", 9),
                              bg="#0d2f2b", fg="white", insertbackground="white",
                              relief="flat", bd=6)
        self.entry.pack(side="left", fill="x", expand=True)
        tk.Button(row, text="更改…", command=self.pick_dir, bg="#1d5a52", fg="white",
                  relief="flat", font=("Microsoft YaHei UI", 9), padx=10).pack(side="left", padx=(8, 0))

        tk.Label(self, text="安装后会创建桌面和开始菜单快捷方式，安装目录内含 uninstall.exe。",
                 font=("Microsoft YaHei UI", 9), fg="#9fd0c5", bg="#123f3a",
                 wraplength=430, justify="left").pack(anchor="w", padx=24, pady=(8, 0))

        self.bar = tk.Label(self, textvariable=self.status, font=("Microsoft YaHei UI", 9),
                            fg="#ffd479", bg="#123f3a", anchor="w")
        self.bar.pack(fill="x", padx=24, pady=(8, 0))

        btns = tk.Frame(self, bg="#123f3a")
        btns.pack(pady=16)
        self.btn = tk.Button(btns, text="安装", command=self.install, bg="#B01513", fg="white",
                             font=("Microsoft YaHei UI", 11, "bold"), relief="flat",
                             padx=28, pady=7, activebackground="#8d100e", activeforeground="white")
        self.btn.pack(side="left", padx=8)
        tk.Button(btns, text="退出", command=self.destroy, bg="#2a4f49", fg="white",
                  font=("Microsoft YaHei UI", 11), relief="flat",
                  padx=24, pady=7).pack(side="left", padx=8)
        self.geometry("500x330")

    def pick_dir(self):
        d = filedialog.askdirectory(initialdir=os.path.dirname(self.dir_var.get()))
        if d:
            self.dir_var.set(os.path.join(d, "HNUClassPPT"))

    def install(self):
        target = self.dir_var.get().strip().strip('"')
        if not target:
            return
        self.btn.config(state="disabled")
        try:
            self.status.set("正在释放文件…")
            self.update_idletasks()
            os.makedirs(target, exist_ok=True)
            with zipfile.ZipFile(res("app.zip")) as z:
                z.extractall(target)
            self.status.set("正在写入卸载程序…")
            self.update_idletasks()
            shutil.copyfile(res("uninstall.exe"), os.path.join(target, "uninstall.exe"))
            self.status.set("正在创建快捷方式…")
            self.update_idletasks()
            exe = os.path.join(target, "HNUClassPPT.exe")
            make_shortcut(exe, os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}.lnk"))
            programs = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
            make_shortcut(exe, os.path.join(programs, f"{APP_NAME}.lnk"))
            self.status.set("安装完成，正在启动…")
            self.update_idletasks()
            subprocess.Popen([exe], cwd=target)
            self.after(600, self.destroy)
        except Exception as e:
            self.btn.config(state="normal")
            self.status.set("")
            messagebox.showerror("安装失败", f"{e}")


def silent_install(target, launch=True):
    os.makedirs(target, exist_ok=True)
    with zipfile.ZipFile(res("app.zip")) as z:
        z.extractall(target)
    shutil.copyfile(res("uninstall.exe"), os.path.join(target, "uninstall.exe"))
    exe = os.path.join(target, "HNUClassPPT.exe")
    make_shortcut(exe, os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}.lnk"))
    programs = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
    make_shortcut(exe, os.path.join(programs, f"{APP_NAME}.lnk"))
    if launch:
        subprocess.Popen([exe], cwd=target)


if __name__ == "__main__":
    if "--silent" in sys.argv:
        i = sys.argv.index("--silent")
        tgt = sys.argv[i + 1] if len(sys.argv) > i + 1 else DEFAULT_DIR
        silent_install(tgt, launch="--no-launch" not in sys.argv)
    else:
        Installer().mainloop()
