"""Monochrome desktop styles and Windows title bar integration."""
import ctypes
import os
from tkinter import ttk

BACKGROUND = "#0b0b0b"
SURFACE = "#111111"
BORDER = "#303030"
TEXT = "#f2f2f2"
MUTED = "#a1a1a1"


def apply_theme(root):
    root.configure(background=BACKGROUND)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BACKGROUND, foreground=TEXT, font=("Tahoma", 10))
    style.configure("TFrame", background=BACKGROUND)
    style.configure("TLabel", background=BACKGROUND, foreground=TEXT)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Title.TLabel", font=("Consolas", 24, "bold"))
    style.configure("TButton", background="#1c1c1c", foreground=TEXT, bordercolor=BORDER, focuscolor=BORDER, padding=(14, 9), relief="flat")
    style.map("TButton", background=[("active", "#303030"), ("disabled", "#151515")], foreground=[("disabled", "#666666")])
    style.configure("Primary.TButton", background=TEXT, foreground=BACKGROUND, bordercolor=TEXT)
    style.map("Primary.TButton", background=[("active", "#cccccc"), ("disabled", "#444444")], foreground=[("disabled", "#888888")])
    style.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT, insertcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=8)
    style.map("TEntry", fieldbackground=[("disabled", "#101010")], foreground=[("disabled", "#777777")])
    style.configure("TCheckbutton", background=BACKGROUND, foreground=MUTED, indicatorbackground=SURFACE, indicatorforeground=TEXT)
    style.map("TCheckbutton", background=[("active", BACKGROUND)], foreground=[("disabled", "#666666")])
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT, bordercolor=BORDER, rowheight=32, font=("Tahoma", 10))
    style.configure("Treeview.Heading", background="#1c1c1c", foreground=MUTED, bordercolor=BORDER, relief="flat", padding=(8, 9))
    style.map("Treeview", background=[("selected", "#353535")], foreground=[("selected", "#ffffff")])
    style.map("Treeview.Heading", background=[("active", "#292929")])
    style.configure("Vertical.TScrollbar", background="#353535", troughcolor=SURFACE, bordercolor=SURFACE, arrowcolor=MUTED)
    style.configure("Horizontal.TScrollbar", background="#353535", troughcolor=SURFACE, bordercolor=SURFACE, arrowcolor=MUTED)
    style.configure("Horizontal.TProgressbar", background="#dedede", troughcolor="#242424", bordercolor=BACKGROUND, thickness=3)
    root.option_add("*selectBackground", "#444444")
    root.option_add("*selectForeground", TEXT)


def dark_title_bar(window):
    if os.name != "nt":
        return
    window.update_idletasks()
    user = ctypes.windll.user32
    user.GetParent.argtypes = [ctypes.c_void_p]
    user.GetParent.restype = ctypes.c_void_p
    handle = user.GetParent(window.winfo_id())
    enabled = ctypes.c_int(1)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(handle), 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
