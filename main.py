#!/usr/bin/env python
# coding: utf-8

# In[1]:


import os
import sys
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import requests


class STAIInstaller:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ST AI 로봇박사 설치기 v1.0.0 💉🤖")
        self.root.geometry("800x600")
        self.root.configure(bg="#0a0a2e")

        # GitHub
        self.github_user = "79tokcom-sudo"
        self.github_repo = "st_ai_stock"

        # 기본(없으면 최신 릴리즈로 자동)
        self.default_release_tag = "v1.0.0"
        self.asset_name_primary = "main_app.zip"
        self.asset_name_compat = "main-app.zip"  # 호환용(있으면 사용)

        # 설치 경로
        self.install_path = Path.home() / "ST_AI_Robot"

        # 앱 실행 파일(권장: zip 안에 이 exe 포함)
        self.app_exe_name = "STAI_ONEUI.exe"      # ← main.py를 빌드한 exe 이름으로 통일 추천
        self.launcher_exe_name = "launcher.exe"   # 있으면 실행, 없으면 STAI_ONEUI.exe 실행
        self.fallback_main_py = "main.py"         # exe 없을 때 실행할 main.py

        # 설치 마커/버전 파일
        self.marker_file = ".installed"
        self.version_file = "version.txt"         # zip에 넣거나 설치기가 생성

        # UI
        self.progress_var = tk.DoubleVar(value=0)
        self.status_text = "준비 중..."
        self.create_gui()

    # ---------------- UI ----------------
    def create_gui(self):
        title_frame = tk.Frame(self.root, bg="#0064FF", height=100)
        title_frame.pack(fill="x")
        tk.Label(
            title_frame,
            text="🩺 ST AI 로봇박사 설치기\n암세포 사멸 + 증권 AI 2030 프로젝트",
            font=("맑은 고딕", 20, "bold"),
            fg="white",
            bg="#0064FF"
        ).pack(expand=True, pady=20)

        path_frame = tk.Frame(self.root, bg="#0a0a2e")
        path_frame.pack(fill="x", padx=40, pady=20)
        tk.Label(path_frame, text="설치 경로:", font=("맑은 고딕", 14),
                 fg="white", bg="#0a0a2e").pack(anchor="w")

        entry_frame = tk.Frame(path_frame, bg="#0a0a2e")
        entry_frame.pack(fill="x", pady=5)

        self.path_entry = tk.Entry(entry_frame, font=("맑은 고딕", 12),
                                   bg="#1a1a3e", fg="white", insertbackground="white")
        self.path_entry.insert(0, str(self.install_path))
        self.path_entry.pack(side="left", fill="x", expand=True)

        tk.Button(entry_frame, text="찾아보기", command=self.browse_path,
                  bg="#FF6B6B", fg="white", font=("맑은 고딕", 11, "bold")).pack(side="right", padx=10)

        self.progress = ttk.Progressbar(self.root, variable=self.progress_var, maximum=100)
        self.progress.pack(fill="x", padx=40, pady=10)

        self.status_label = tk.Label(self.root, text=self.status_text, font=("맑은 고딕", 12),
                                     fg="#00FF88", bg="#0a0a2e")
        self.status_label.pack(pady=10)

        btn_frame = tk.Frame(self.root, bg="#0a0a2e")
        btn_frame.pack(fill="x", padx=40, pady=20)

        self.install_btn = tk.Button(
            btn_frame, text="🚀 설치/업데이트 & 실행", command=self.start_install_thread,
            bg="#00FF88", fg="black", font=("맑은 고딕", 16, "bold"), height=2
        )
        self.install_btn.pack(side="left", expand=True, fill="x", padx=(0, 10))

        tk.Button(btn_frame, text="취소", command=self.root.quit,
                  bg="#FF4444", fg="white", font=("맑은 고딕", 16, "bold"), height=2).pack(side="right")

    def browse_path(self):
        path = filedialog.askdirectory()
        if path:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, path)
            self.install_path = Path(path)

    def start_install_thread(self):
        self.install_btn.config(state="disabled")
        threading.Thread(target=self.install_or_update_and_run, daemon=True).start()

    def update_status(self, text, progress):
        self.status_text = text
        self.root.after(0, lambda: self.status_label.config(text=text))
        self.root.after(0, lambda: self.progress_var.set(progress))

    # ---------------- Helpers ----------------
    def is_installed(self) -> bool:
        return (self.install_path / self.marker_file).exists()

    def read_local_version(self) -> str:
        p = self.install_path / self.version_file
        if p.exists():
            try:
                return p.read_text(encoding="utf-8").strip()
            except Exception:
                return ""
        return ""

    def write_local_version(self, v: str):
        try:
            (self.install_path / self.version_file).write_text(v, encoding="utf-8")
        except Exception:
            pass

    def ensure_install_dir(self):
        self.install_path.mkdir(parents=True, exist_ok=True)

    def github_api_latest_release(self) -> dict:
        # 최신 릴리즈 정보
        url = f"https://api.github.com/repos/{self.github_user}/{self.github_repo}/releases/latest"
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.json()

    def github_api_release_by_tag(self, tag: str) -> dict:
        url = f"https://api.github.com/repos/{self.github_user}/{self.github_repo}/releases/tags/{tag}"
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.json()

    def pick_asset_download_url(self, release_json: dict) -> tuple[str, str]:
        """
        릴리즈 JSON에서 main_app.zip(또는 main-app.zip) asset을 찾아 download_url 반환
        return: (asset_name, browser_download_url)
        """
        assets = release_json.get("assets", [])
        # 1) primary
        for a in assets:
            if a.get("name") == self.asset_name_primary:
                return a["name"], a["browser_download_url"]
        # 2) compat
        for a in assets:
            if a.get("name") == self.asset_name_compat:
                return a["name"], a["browser_download_url"]

        raise RuntimeError(f"Release Assets에 {self.asset_name_primary} 또는 {self.asset_name_compat} 가 없습니다.")

    def download_file(self, url: str, dest: Path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

        # 빈 파일 방지
        if dest.exists() and dest.stat().st_size == 0:
            raise RuntimeError("다운로드된 파일이 0바이트입니다(빈 파일). Release Assets 업로드를 확인하세요.")

    def extract_zip_atomic(self, zip_path: Path):
        """
        안전한 설치:
        - temp 폴더에 압축 해제
        - 기존 앱 폴더 백업
        - temp -> install_path 로 교체
        """
        temp_dir = self.install_path.parent / f"{self.install_path.name}__tmp"
        backup_dir = self.install_path.parent / f"{self.install_path.name}__bak"

        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(temp_dir)

        # temp_dir 안의 실제 루트 탐색:
        # zip이 "그대로 파일들"로 풀리는지, "폴더 하나로 감싸져" 풀리는지 둘 다 지원
        # 루트 후보: temp_dir 안에 파일이 있으면 temp_dir 자체
        candidates = [p for p in temp_dir.iterdir() if p.name not in ["__MACOSX"]]
        if not candidates:
            raise RuntimeError("압축 해제 결과가 비어 있습니다. main_app.zip 내용을 확인하세요.")

        # temp 내부에 단일 폴더 1개만 있고 그 안이 실제 내용이면 그걸 루트로 사용
        content_root = temp_dir
        if len(candidates) == 1 and candidates[0].is_dir():
            content_root = candidates[0]

        # 기존 설치 백업
        if self.install_path.exists():
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
            try:
                shutil.move(str(self.install_path), str(backup_dir))
            except Exception:
                # 이동 실패 시 강제 삭제
                shutil.rmtree(self.install_path, ignore_errors=True)

        # 새 설치 이동
        shutil.move(str(content_root), str(self.install_path))
        # temp 정리
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

        # 백업은 유지(문제 발생 시 복구 가능)

    def create_marker(self):
        (self.install_path / self.marker_file).write_text("installed", encoding="utf-8")

    def create_desktop_shortcut(self, target_exe: Path, shortcut_name: str = "STAI ONEUI"):
        """
        바탕화면 바로가기(.lnk) 생성 (Windows 전용)
        - PowerShell + WScript.Shell 사용
        """
        desktop = Path(os.path.join(os.environ.get("USERPROFILE", str(Path.home())), "Desktop"))
        lnk_path = desktop / f"{shortcut_name}.lnk"

        # 아이콘은 실행 파일 자체를 사용
        ps = f"""
        $WshShell = New-Object -ComObject WScript.Shell;
        $Shortcut = $WshShell.CreateShortcut("{lnk_path}");
        $Shortcut.TargetPath = "{target_exe}";
        $Shortcut.WorkingDirectory = "{target_exe.parent}";
        $Shortcut.IconLocation = "{target_exe},0";
        $Shortcut.Save();
        """
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, text=True)

    def run_app(self):
        """
        1) launcher.exe 있으면 실행
        2) 없으면 STAI_ONEUI.exe 실행
        3) exe도 없으면 main.py 실행 (python 필요)
        """
        launcher = self.install_path / self.launcher_exe_name
        app_exe = self.install_path / self.app_exe_name
        main_py = self.install_path / self.fallback_main_py

        if launcher.exists():
            subprocess.Popen([str(launcher)], cwd=str(self.install_path))
            return ("launcher", launcher)

        if app_exe.exists():
            subprocess.Popen([str(app_exe)], cwd=str(self.install_path))
            return ("exe", app_exe)

        # exe가 없으면 main.py 실행 (python 필요)
        if main_py.exists():
            # python 찾기: pythonw 우선
            py = shutil.which("pythonw") or shutil.which("python")
            if not py:
                raise RuntimeError("Python이 설치되어 있지 않아 main.py를 실행할 수 없습니다. exe를 zip에 포함시키는 방식이 권장됩니다.")
            subprocess.Popen([py, str(main_py)], cwd=str(self.install_path))
            return ("py", main_py)

        raise RuntimeError("실행 파일(launcher.exe / STAI_ONEUI.exe / main.py)을 찾지 못했습니다. main_app.zip 구성 확인 필요")

    # ---------------- Main flow ----------------
    def install_or_update_and_run(self):
        download_url = ""
        try:
            self.ensure_install_dir()

            # 인터넷 체크
            self.update_status("인터넷 연결 확인 중...", 5)
            requests.get("https://1.1.1.1", timeout=4)

            # 최신 릴리즈 조회
            self.update_status("최신 업데이트 확인 중...", 12)
            try:
                latest = self.github_api_latest_release()
                latest_tag = latest.get("tag_name", "").strip()  # 예: v1.0.0
                if not latest_tag:
                    raise RuntimeError("latest release tag_name이 비어 있습니다.")
            except Exception:
                # 최신 조회 실패 시 기본 태그로 fallback
                latest_tag = self.default_release_tag
                latest = self.github_api_release_by_tag(latest_tag)

            local_ver = self.read_local_version()
            need_install = not self.is_installed()
            need_update = (local_ver != latest_tag)

            # 설치/업데이트 여부 판단
            if need_install:
                self.update_status(f"설치 필요: 로컬 미설치 → {latest_tag} 설치", 18)
            elif need_update:
                self.update_status(f"업데이트 필요: {local_ver} → {latest_tag}", 18)
            else:
                self.update_status(f"최신 버전입니다: {latest_tag}", 20)

            # 설치/업데이트가 필요하면 다운로드+설치
            if need_install or need_update:
                asset_name, download_url = self.pick_asset_download_url(latest)

                self.update_status(f"다운로드 중...\n{latest_tag} / {asset_name}", 28)

                temp_zip = self.install_path / "temp_main_app.zip"
                # 기존 temp 제거
                if temp_zip.exists():
                    temp_zip.unlink(missing_ok=True)

                self.download_file(download_url, temp_zip)

                self.update_status("압축 해제 및 설치 적용 중...", 55)
                self.extract_zip_atomic(temp_zip)
                temp_zip.unlink(missing_ok=True)

                self.create_marker()
                self.write_local_version(latest_tag)

            # 바로가기 생성(앱 실행 파일 기준)
            self.update_status("바탕화면 아이콘 생성 중...", 78)
            exe_candidate = (self.install_path / self.launcher_exe_name)
            if not exe_candidate.exists():
                exe_candidate = (self.install_path / self.app_exe_name)

            if exe_candidate.exists():
                self.create_desktop_shortcut(exe_candidate, shortcut_name="STAI ONEUI")
            else:
                # exe가 없으면 main.py 바로가기 대신 안내(윈도우에서 .py 바로가기는 환경에 따라 실패 가능)
                self.update_status("exe 없음 → 아이콘 생성 건너뜀(권장: zip에 exe 포함)", 80)

            # 실행
            self.update_status("프로그램 실행 중...", 90)
            mode, target = self.run_app()

            self.update_status("완료! 설치/업데이트 후 실행했습니다 ✅", 100)
            self.root.after(500, lambda: messagebox.showinfo(
                "성공",
                f"완료!\n경로: {self.install_path}\n버전: {self.read_local_version()}\n실행: {mode} → {target.name}"
            ))
            self.root.after(1200, self.root.quit)

        except requests.exceptions.HTTPError as e:
            code = getattr(e.response, "status_code", "UNKNOWN")
            msg = (
                f"다운로드 실패 (코드 {code})\nURL: {download_url}\n\n"
                f"✅ 해결 체크리스트\n"
                f"1) GitHub Releases에 태그(v1.0.0 등) 존재\n"
                f"2) Release Assets에 {self.asset_name_primary} 업로드(0바이트 금지)\n"
                f"3) 파일명(main_app.zip / main-app.zip) 정확\n"
            )
            self.root.after(0, lambda: messagebox.showerror("다운로드 오류", msg))

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("설치 오류", f"오류: {str(e)}"))

        finally:
            self.root.after(0, lambda: self.install_btn.config(state="normal"))

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    STAIInstaller().run()


# In[ ]:




