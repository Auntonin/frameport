"""Optional compatibility and manual-login controls, kept off the main workflow."""
import tkinter as tk
from tkinter import ttk
from .appearance import BACKGROUND, dark_title_bar


def show_settings(app):
    if app.busy:
        return
    window = tk.Toplevel(app.root)
    window.title("ตั้งค่าขั้นสูง")
    window.configure(background=BACKGROUND)
    window.transient(app.root)
    window.grab_set()
    panel = ttk.Frame(window, padding=20)
    panel.pack(fill="both", expand=True)
    ttk.Label(panel, text="การใช้งานทั่วไปใช้ปุ่มเข้าสู่ระบบผ่านเว็บไซต์ได้เลย", wraplength=650).grid(row=0, column=0, columnspan=2, sticky="w", pady=8)
    for row, (label, variable) in enumerate((("อีเมลบัญชีเว็บไซต์", app.email), ("รหัสผ่านบัญชีเว็บไซต์", app.password), ("Cookie สำหรับกรณีพิเศษ", app.cookie)), 1):
        ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=5)
        ttk.Entry(panel, textvariable=variable, show="•" if row > 1 else "", width=50).grid(row=row, column=1, sticky="ew")
    def login():
        window.destroy()
        app.check_account()
    ttk.Button(panel, text="เข้าสู่ระบบด้วยข้อมูลข้างบน", command=login).grid(row=4, column=1, sticky="w", pady=12)
    ttk.Checkbutton(panel, text="ลอง lossless ก่อน · หากเกินขนาด API จะเลือก lossy ที่ผ่านขนาด", variable=app.lossless, command=app.invalidate).grid(row=5, column=0, columnspan=2, sticky="w")
    ttk.Label(panel, text="API profile คือการตั้งค่าเส้นทาง API และชื่อข้อมูลที่เว็บไซต์รับ ค่าเริ่มต้นตรงกับ main แล้ว เปลี่ยนเมื่อใช้เว็บไซต์เวอร์ชันที่ API ต่างกัน", wraplength=650).grid(row=6, column=0, columnspan=2, sticky="w", pady=12)
    def profile():
        window.destroy()
        app.pick_profile()
    ttk.Button(panel, text="เปลี่ยน API profile…", command=profile).grid(row=7, column=0, sticky="w")
    ttk.Button(panel, text="ปิด", command=window.destroy).grid(row=7, column=1, sticky="e")

    dark_title_bar(window)
