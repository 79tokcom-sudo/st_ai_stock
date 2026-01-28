# -*- coding: utf-8 -*-
"""
ST AI Launcher (ONE SOURCE)
- Tkinter DLL (_tkinter) 오류 자동 해결
- PyInstaller onefile / onedir 대응
"""

import os
import sys

# ===============================
# 1. Tkinter DLL 경로 자동 보정
# ===============================
def _fix_tkinter_paths():
    """
    PyInstaller 실행 시 tcl/tk 경로를 못 찾는 문제 해결
    """
    base_dir = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))

    tcl_path = os.path.join(base_dir, "tcl")
    tk_path  = os.path.join(base_dir, "tk")

    if os.path.isdir(tcl_path) and os.path.isdir(tk_path):
        os.environ["TCL_LIBRARY"] = tcl_path
        os.environ["TK_LIBRARY"]  = tk_path

_fix_tkinter_paths()

# ===============================
# 2. 표준 라이브러리
# ===============================
import tkinter as tk
from tkinter import ttk, messagebox

# ===============================
# 3. 메인 앱
# ===============================
class LauncherApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("ST AI Launcher")
        self.geometry("420x280")
        self.resizable(False, False)

        self._build_ui()

    def _build_ui(self):
        frame = ttk.Frame(self, padding=20)
        frame.pack(expand=True, fill="both")

        title = ttk.Label(
            frame,
            text="천신대왕 ST AI 런처",
            font=("Malgun Gothic", 14, "bold")
        )
        title.pack(pady=(0, 20))

        run_btn = ttk.Button(
            frame,
            text="프로그램 실행",
            command=self.run_program
        )
        run_btn.pack(fill="x", pady=5)

        exit_btn = ttk.Button(
            frame,
            text="종료",
            command=self.destroy
        )
        exit_btn.pack(fill="x", pady=5)

    def run_program(self):
        messagebox.showinfo("실행", "정상 실행되었습니다.\n(Tkinter 로딩 성공)")

# ===============================
# 4. 엔트리 포인트
# ===============================
if __name__ == "__main__":
    try:
        app = LauncherApp()
        app.mainloop()
    except Exception as e:
        import traceback
        messagebox.showerror(
            "치명적 오류",
            f"프로그램 실행 중 오류 발생:\n\n{e}\n\n{traceback.format_exc()}"
        )