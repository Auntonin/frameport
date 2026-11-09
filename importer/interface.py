"""Minimal desktop layout. Workflow state stays in the application controller."""
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

from .appearance import BACKGROUND, BORDER, MUTED, apply_theme, dark_title_bar
from .settings_dialog import show_settings


def entry(app, frame, row, label, variable):
    ttk.Label(frame, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 18), pady=6)
    widget = ttk.Entry(frame, textvariable=variable, font=("Tahoma", 10))
    widget.grid(row=row, column=1, sticky="ew", pady=6)
    if variable in (app.excel, app.images):
        variable.trace_add("write", lambda *_: app.invalidate())
    if variable is app.url:
        widget.bind("<FocusOut>", lambda _event: app.refresh())


def build_interface(app):
    apply_theme(app.root)
    frame = ttk.Frame(app.root, padding=24)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    frame.rowconfigure(9, weight=1)
    ttk.Label(frame, text="FramePort", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
    ttk.Button(frame, text="ตั้งค่าขั้นสูง", command=lambda: show_settings(app)).grid(row=0, column=2, sticky="e")
    ttk.Label(frame, text="นำเข้าสถานที่จาก Excel / CSV และภาพ", style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 20))
    entry(app, frame, 2, "เว็บไซต์ปลายทาง", app.url)
    account = ttk.Frame(frame)
    account.grid(row=3, column=1, columnspan=2, sticky="w", pady=(4, 16))
    ttk.Button(account, text="เข้าสู่ระบบผ่านเว็บไซต์", command=app.browser_account).pack(side="left")
    ttk.Label(account, textvariable=app.account_status, style="Muted.TLabel").pack(side="left", padx=16)
    entry(app, frame, 4, "ไฟล์ข้อมูล", app.excel)
    ttk.Button(frame, text="เลือกไฟล์…", command=app.pick_excel).grid(row=4, column=2, padx=(12, 0))
    entry(app, frame, 5, "โฟลเดอร์ภาพ", app.images)
    ttk.Button(frame, text="เลือกโฟลเดอร์…", command=app.pick_images).grid(row=5, column=2, padx=(12, 0))
    ttk.Checkbutton(frame, text="แถวแรกเป็นหัวตาราง", variable=app.header, command=app.invalidate).grid(row=6, column=1, sticky="w", pady=(0, 14))
    actions = ttk.Frame(frame)
    actions.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(0, 14))
    for text, command, primary in (("เริ่มนำเข้า", app.start, True), ("ดูตัวอย่าง", app.preview, False), ("เปิดโฟลเดอร์ภาพ", app.open_output, False), ("รายการค้าง", app.retry, False)):
        ttk.Button(actions, text=text, command=command, style="Primary.TButton" if primary else "TButton").pack(side="left", padx=(0, 8))
    app.stop_button = ttk.Button(actions, text="หยุด", command=app.cancel.set)
    app.stop_button.pack(side="right")
    app.stop_button.state(["disabled"])
    status = ttk.Frame(frame)
    status.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(0, 12))
    status.columnconfigure(0, weight=1)
    ttk.Label(status, textvariable=app.message, style="Muted.TLabel", wraplength=1000).grid(row=0, column=0, sticky="w", pady=(0, 8))
    app.activity = ttk.Progressbar(status, mode="indeterminate")
    app.activity.grid(row=1, column=0, sticky="ew")
    table = ttk.Frame(frame)
    table.grid(row=9, column=0, columnspan=3, sticky="nsew")
    table.columnconfigure(0, weight=1)
    table.rowconfigure(0, weight=1)
    app.table = ttk.Treeview(table, columns=("row", "name", "coordinates", "files", "state"), show="headings", selectmode="browse")
    for key, label, width in (("row", "แถว", 55), ("name", "สถานที่", 220), ("coordinates", "พิกัด", 175), ("files", "ภาพ", 330), ("state", "สถานะ", 130)):
        app.table.heading(key, text=label)
        app.table.column(key, width=width, minwidth=55)
    app.table.grid(row=0, column=0, sticky="nsew")
    app.table.bind("<Double-1>", app.details)
    vertical = ttk.Scrollbar(table, orient="vertical", command=app.table.yview)
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal = ttk.Scrollbar(table, orient="horizontal", command=app.table.xview)
    horizontal.grid(row=1, column=0, sticky="ew")
    app.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    ttk.Label(frame, text="บันทึกการทำงาน", style="Muted.TLabel").grid(row=10, column=0, columnspan=3, sticky="w", pady=(14, 6))
    app.log = tk.Text(frame, height=4, background="#080808", foreground="#bcbcbc", insertbackground="white", selectbackground="#444444", font=("Consolas", 10), relief="solid", borderwidth=1, highlightthickness=0, state="disabled", padx=10, pady=8)
    app.log.grid(row=11, column=0, columnspan=3, sticky="ew")
    widgets = list(frame.winfo_children())
    app.controls = []
    while widgets:
        widget = widgets.pop()
        widgets.extend(widget.winfo_children())
        if isinstance(widget, (ttk.Button, ttk.Checkbutton, ttk.Entry)) and widget is not app.stop_button:
            app.controls.append(widget)
    dark_title_bar(app.root)


def show_details(app):
    selection = app.table.selection()
    if not selection or not app.items:
        return
    item = app.items[int(selection[0])]
    window = tk.Toplevel(app.root)
    window.configure(background=BACKGROUND)
    window.title(item["location"]["name"])
    window.photos = []
    location = item["location"]
    ttk.Label(window, text=f"{location['latitude']}, {location['longitude']}\n{location['description']}", padding=16, wraplength=900).grid(row=0, column=0, columnspan=5, sticky="w")
    for column, image in enumerate(item["images"]):
        with Image.open(image["path"]) as source:
            source.thumbnail((180, 160))
            photo = ImageTk.PhotoImage(source)
        window.photos.append(photo)
        ttk.Button(window, image=photo, command=lambda path=image["path"]: os.startfile(path)).grid(row=1, column=column, padx=8, pady=8)
        ttk.Label(window, text=f"{image['source']}\n{image['width']}×{image['height']} · {image['bytes'] / 1048576:.2f} MiB", padding=8).grid(row=2, column=column)
    dark_title_bar(window)
