#!/usr/bin/env python
# coding: utf-8

# In[1]:


# -*- coding: utf-8 -*-
import os, math, queue, threading, hashlib, traceback, datetime
import tkinter as tk
from tkinter import ttk, messagebox

# -------------------------
# timezone-aware KST
# -------------------------
KST = datetime.timezone(datetime.timedelta(hours=9))
def now_kst_str():
    return datetime.datetime.now(datetime.timezone.utc).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")

# -------------------------
# deps
# -------------------------
try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
    YF_OK = True
    YF_ERR = ""
except Exception as e:
    YF_OK = False
    YF_ERR = str(e)
    yf = None
    pd = None
    np = None

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MPL_OK = True
except Exception:
    MPL_OK = False
    Figure = None
    FigureCanvasTkAgg = None

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FB_OK = True
    FB_ERR = ""
except Exception as e:
    FB_OK = False
    FB_ERR = str(e)
    firebase_admin = None
    credentials = None
    firestore = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
FIREBASE_KEY_FILE = os.path.join(BASE_DIR, "staidb-firebase-adminsdk-fbsvc-d3ba815ea4.json")

# -------------------------
# ONE UI colors
# -------------------------
C_BG = "#FFFFFF"
C_TEXT = "#111827"
C_MUTED = "#6B7280"
C_BLUE = "#1E5EFF"
C_BLUE_DARK = "#1548CC"
C_BLUE_SOFT = "#EAF1FF"
C_LINE = "#D1D5DB"

C_BUY = "#16A34A"
C_SELL = "#DC2626"
C_WATCH = "#111827"

APP_NAME = "천신대왕 ST AI 증권"
APP_VERSION = "ONE UI v19.6 (CrashProof + LoginFirst + AutoReco)"

PRICE_MONTH = 300000
PRICE_YEAR = 3000000

TOP_N = 10
KR_UNIVERSE = [
    "005930.KS","000660.KS","035420.KS","035720.KS","051910.KS","005380.KS",
    "068270.KS","207940.KS","373220.KS","012330.KS","105560.KS","055550.KS",
    "096770.KS","034020.KS","006400.KS","066570.KS","028260.KS"
]
US_UNIVERSE = [
    "NVDA","AAPL","MSFT","AMZN","GOOGL","META","TSLA","AMD","AVGO","NFLX",
    "COST","ADBE","CRM","ORCL","QQQ","SPY","SMH"
]

def safe_float(x, default=None):
    try:
        return default if x is None else float(x)
    except Exception:
        return default

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

# -------------------------
# Firestore error logger (optional)
# -------------------------
class FirestoreStore:
    def __init__(self, log_fn):
        self.enabled = False
        self.db = None
        self._log = log_fn

    def init(self):
        if not FB_OK:
            self._log(f"[주의] firebase-admin 불가: {FB_ERR}")
            return False
        if not os.path.exists(FIREBASE_KEY_FILE):
            self._log(f"[주의] Firebase 키 파일 없음: {FIREBASE_KEY_FILE}")
            return False
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(FIREBASE_KEY_FILE)
                firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            self.enabled = True
            self._log("[성공] Firestore 연결 OK (error_logs 저장)")
            return True
        except Exception as e:
            self._log(f"[주의] Firestore 연결 실패: {e}")
            return False

    @staticmethod
    def fp(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def log_error(self, where: str, exc: Exception):
        if not self.enabled or not self.db:
            return
        try:
            tb = traceback.format_exc()
            msg = f"{type(exc).__name__}: {str(exc)}"
            fp = self.fp(msg)
            payload = {
                "ts_kst": now_kst_str(),
                "app_version": APP_VERSION,
                "where": where,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "traceback": tb,
                "fingerprint": fp,
            }
            self.db.collection("error_logs").add(payload)

            ref = self.db.collection("error_fingerprints").document(fp)
            doc = ref.get()
            cnt = int((doc.to_dict() or {}).get("count", 0)) + 1 if doc.exists else 1
            ref.set({"fingerprint": fp, "lastSeen_kst": payload["ts_kst"], "count": cnt, "sample_error": msg}, merge=True)
        except Exception:
            pass

# -------------------------
# yfinance logic
# -------------------------
def yf_hist_3mo_daily(ticker: str):
    t = yf.Ticker(ticker)
    hist = t.history(period="3mo", interval="1d", auto_adjust=True)
    if hist is None or hist.empty:
        raise RuntimeError("가격 데이터 없음")
    hist = hist[["Close","Volume"]].dropna()
    if len(hist) < 15:
        raise RuntimeError("데이터 부족")
    return hist

def yf_info_safe(ticker: str):
    try:
        return (yf.Ticker(ticker).info) or {}
    except Exception:
        return {}

def compute_signal(closes):
    if len(closes) >= 3 and closes[-3] > closes[-2] > closes[-1]:
        return "매도"
    if len(closes) >= 8:
        up7 = True
        for i in range(-7, 0):
            if not (closes[i-1] < closes[i]):
                up7 = False
                break
        if up7:
            return "매수"
    return "관망"

def compute_rank(hist, info):
    closes = hist["Close"].tolist()
    vols = hist["Volume"].tolist()
    last = float(closes[-1])

    # 증가율(20일)
    growth = (last / float(closes[-21]) - 1.0) * 100.0 if len(closes) >= 21 else 0.0
    growth_score = clamp((growth + 10.0) / 30.0, 0.0, 1.0) * 35.0

    # 구매강도 v5/v20
    v20 = sum(vols[-20:]) / 20.0 if len(vols) >= 20 else sum(vols) / max(1, len(vols))
    v5 = sum(vols[-5:]) / min(5, len(vols))
    vr = (v5 / v20) if v20 > 0 else 1.0
    buy_score = clamp((vr - 0.7) / 1.1, 0.0, 1.0) * 25.0

    opm = safe_float(info.get("operatingMargins"), None)  # 0.12=12%
    dte = safe_float(info.get("debtToEquity"), None)

    if opm is None:
        opm_score = 8.0
        opm_pct = None
    else:
        opm_score = clamp(opm, 0.0, 0.4) / 0.4 * 30.0
        opm_pct = opm * 100.0

    if dte is None:
        debt_penalty = 10.0
        dte_val = None
    else:
        debt_penalty = clamp(dte, 0.0, 200.0) / 200.0 * 20.0
        dte_val = dte

    score = 20.0 + growth_score + buy_score + opm_score - debt_penalty
    score = clamp(score, 0.0, 100.0)

    return {
        "rank_score": round(score, 1),
        "growth_20d_pct": round(growth, 2),
        "buy_strength": round(vr, 2),
        "operating_margin_pct": None if opm_pct is None else round(opm_pct, 2),
        "debt_to_equity": None if dte_val is None else round(dte_val, 2),
    }

def build_top10(universe, market: str):
    items = []
    for tk_ in universe:
        hist = yf_hist_3mo_daily(tk_)
        closes = [float(x) for x in hist["Close"].tolist()]
        price = closes[-1]
        sig = compute_signal(closes)
        info = yf_info_safe(tk_)
        name = ""
        if market == "KR":
            name = (info.get("shortName") or info.get("longName") or info.get("displayName") or "")
        else:
            name = (info.get("shortName") or info.get("longName") or "")
        pack = compute_rank(hist, info)
        items.append({"ticker": tk_, "name": name, "price": round(price,4), "signal": sig, **pack})
    items.sort(key=lambda x: float(x.get("rank_score", 0.0)), reverse=True)
    return items[:TOP_N]

# -------------------------
# App (Crash-proof)
# -------------------------
class STAIApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} | {APP_VERSION}")
        self.geometry("1420x860")
        self.minsize(1200, 760)

        self.bgq = queue.Queue()
        self._logs = []

        # 계좌/보유(데모)
        self.usd_cash = 10000.0
        self.krw_cash = 10000000.0
        self.holdings = {"KR": {}, "US": {}}
        self.session = {"mode": "NONE"}

        # 에러 로거
        self.store = FirestoreStore(self._log)
        self.store.init()

        # Tk 콜백 에러를 전부 safe_call로 잡기
        self.report_callback_exception = self._tk_callback_exception

        self._init_style()

        self.container = ttk.Frame(self, padding=0)
        self.container.pack(fill="both", expand=True)

        self.after(120, self._poll_bgq)
        self.show_login()

    # ---------- error safe layer ----------
    def _tk_callback_exception(self, exc, val, tb):
        # Tkinter callback 예외가 터질 때 여기로 옴
        self.safe_call("TkinterCallback", lambda: (_ for _ in ()).throw(val))

    def safe_call(self, where: str, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            # 상태바/팝업/DB 저장
            try:
                self._set_status(f"오류: {where}")
            except Exception:
                pass
            try:
                messagebox.showerror("오류", f"{where}\n\n{e}")
            except Exception:
                pass
            try:
                if getattr(self.store, "enabled", False):
                    self.store.log_error(where, e)
            except Exception:
                pass
            print(f"[SAFE_CALL] {where}: {e}\n{traceback.format_exc()}")
            return None

    # ---------- logs/status ----------
    def _log(self, msg: str):
        self._logs.append(f"[{now_kst_str()}] {msg}")

    def _set_status(self, msg: str):
        # lbl_status가 없을 때도 죽지 않게
        try:
            if hasattr(self, "lbl_status") and self.lbl_status.winfo_exists():
                self.lbl_status.config(text=f"[{now_kst_str()}] {msg}")
        except Exception:
            pass

    # ---------- style ----------
    def _init_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(".", background=C_BG, foreground=C_TEXT, font=("Malgun Gothic", 10))
        style.configure("TFrame", background=C_BG)
        style.configure("Top.TLabel", background=C_BG, foreground=C_TEXT, font=("Malgun Gothic", 11, "bold"))
        style.configure("Sub.TLabel", background=C_BG, foreground=C_MUTED, font=("Malgun Gothic", 10))
        style.configure("Card.TFrame", background=C_BG, relief="solid", borderwidth=1)
        style.configure("Primary.TButton", padding=10, font=("Malgun Gothic", 10, "bold"))
        style.map("Primary.TButton",
                  background=[("active", C_BLUE_DARK), ("!active", C_BLUE_DARK)],
                  foreground=[("active", "#FFFFFF"), ("!active", "#FFFFFF")])
        style.configure("Ghost.TButton", padding=10, font=("Malgun Gothic", 10, "bold"))
        style.map("Ghost.TButton",
                  background=[("active", C_BLUE_SOFT), ("!active", C_BG)],
                  foreground=[("active", C_BLUE), ("!active", C_BLUE)])
        style.configure("Treeview", font=("Malgun Gothic", 10), rowheight=26)
        style.configure("Treeview.Heading", font=("Malgun Gothic", 10, "bold"))

    # ---------- screen switch ----------
    def _clear(self):
        for w in self.container.winfo_children():
            w.destroy()

    # ---------- login screen ----------
    def show_login(self):
        self._clear()

        topbar = tk.Frame(self.container, bg=C_BLUE_DARK, height=46)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        tk.Label(topbar, text="천신대왕  ST", bg=C_BLUE_DARK, fg="white",
                 font=("Malgun Gothic", 14, "bold")).pack(side="left", padx=14)
        tk.Label(topbar, text=f"{APP_NAME} | 로그인", bg=C_BLUE_DARK, fg="white",
                 font=("Malgun Gothic", 10)).pack(side="left")

        body = ttk.Frame(self.container, padding=14)
        body.pack(fill="both", expand=True)

        card = ttk.Frame(body, style="Card.TFrame", padding=18)
        card.place(relx=0.5, rely=0.5, anchor="center", width=520, height=420)

        ttk.Label(card, text="로그인", font=("Malgun Gothic", 18, "bold")).pack(anchor="w")
        s1 = "yfinance: OK" if YF_OK else f"yfinance: 오류({YF_ERR})"
        s2 = "구글DB(오류로그): 연결됨" if self.store.enabled else "구글DB(오류로그): 미연결"
        ttk.Label(card, text=f"{s1}  |  {s2}", style="Sub.TLabel").pack(anchor="w", pady=(6, 14))

        frm = ttk.Frame(card)
        frm.pack(fill="x")
        frm.columnconfigure(0, weight=1)

        ttk.Label(frm, text="이메일(데모)", style="Sub.TLabel").grid(row=0, column=0, sticky="w")
        self.ent_email = ttk.Entry(frm)
        self.ent_email.grid(row=1, column=0, sticky="ew", pady=(4, 10))

        ttk.Label(frm, text="비밀번호(데모)", style="Sub.TLabel").grid(row=2, column=0, sticky="w")
        self.ent_pw = ttk.Entry(frm, show="*")
        self.ent_pw.grid(row=3, column=0, sticky="ew", pady=(4, 10))

        ttk.Button(card, text="로그인", style="Primary.TButton",
                   command=lambda: self.safe_call("login", self._login_demo)).pack(fill="x", pady=(10, 8))
        ttk.Button(card, text="24시간 게스트 시작", style="Ghost.TButton",
                   command=lambda: self.safe_call("guest", self._guest_start)).pack(fill="x")

        ttk.Label(card, text=f"유료: 월 {PRICE_MONTH:,}원 / 연 {PRICE_YEAR:,}원 (고정)", style="Sub.TLabel").pack(anchor="w", pady=(16, 0))

    def _login_demo(self):
        email = (self.ent_email.get() or "").strip()
        pw = (self.ent_pw.get() or "").strip()
        if not email or not pw:
            messagebox.showinfo("안내", "이메일/비밀번호를 입력하세요.")
            return
        self.session = {"mode": "LOGIN", "email": email}
        self.show_main()

    def _guest_start(self):
        exp = (now_kst() + datetime.timedelta(hours=24)).isoformat()
        self.session = {"mode": "GUEST", "expiresAt": exp}
        self.show_main()

    # ---------- main screen ----------
    def show_main(self):
        self._clear()

        topbar = tk.Frame(self.container, bg=C_BLUE_DARK, height=46)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        tk.Label(topbar, text="천신대왕  ST", bg=C_BLUE_DARK, fg="white",
                 font=("Malgun Gothic", 14, "bold")).pack(side="left", padx=14)
        mode_txt = "로그인" if self.session.get("mode") == "LOGIN" else "게스트(24h)"
        tk.Label(topbar, text=f"{APP_NAME} | {mode_txt}", bg=C_BLUE_DARK, fg="white",
                 font=("Malgun Gothic", 10)).pack(side="left")

        tk.Button(topbar, text="로그인 화면", bg=C_BLUE_DARK, fg="white", bd=0,
                  activebackground=C_BLUE, activeforeground="white",
                  font=("Malgun Gothic", 10, "bold"),
                  command=lambda: self.safe_call("show_login", self.show_login)).pack(side="right", padx=(0, 14))
        tk.Button(topbar, text="새로고침", bg=C_BLUE_DARK, fg="white", bd=0,
                  activebackground=C_BLUE, activeforeground="white",
                  font=("Malgun Gothic", 10, "bold"),
                  command=lambda: self.safe_call("reload_all_recos(btn)", self.reload_all_recos)).pack(side="right", padx=14)

        # grid-only zone
        root = ttk.Frame(self.container, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        acct = ttk.Frame(root)
        acct.grid(row=0, column=0, sticky="ew")
        acct.columnconfigure(0, weight=1)

        self.lbl_usd = ttk.Label(acct, text="", style="Top.TLabel")
        self.lbl_krw = ttk.Label(acct, text="", style="Top.TLabel")
        self.lbl_usd.grid(row=0, column=0, sticky="w")
        self.lbl_krw.grid(row=0, column=1, sticky="w", padx=(18, 0))

        self.lbl_status = ttk.Label(acct, text=f"[{now_kst_str()}] 메인 진입", style="Sub.TLabel")
        self.lbl_status.grid(row=0, column=2, sticky="e")
        self._refresh_wallet()

        ttk.Separator(root, orient="horizontal").grid(row=1, column=0, sticky="ew", pady=(10, 10))

        body = ttk.Frame(root)
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # left: 국내/미국
        left = ttk.Frame(body, style="Card.TFrame", padding=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        left.rowconfigure(4, weight=1)

        ttk.Label(left, text="추천종목 TOP 10 | 국내", style="Top.TLabel").grid(row=0, column=0, sticky="w")
        self.kr_tree = self._make_tree(left, "KR")
        self.kr_tree.grid(row=1, column=0, sticky="nsew", pady=(8, 10))

        ttk.Separator(left, orient="horizontal").grid(row=2, column=0, sticky="ew", pady=(6, 10))

        ttk.Label(left, text="추천종목 TOP 10 | 미국", style="Top.TLabel").grid(row=3, column=0, sticky="w")
        self.us_tree = self._make_tree(left, "US")
        self.us_tree.grid(row=4, column=0, sticky="nsew", pady=(8, 0))

        self._init_tree_tags(self.kr_tree)
        self._init_tree_tags(self.us_tree)

        # right: tabs
        right = ttk.Frame(body, style="Card.TFrame", padding=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        ttk.Label(right, text="기능 | 주식차트 | 주식토론 | 채팅방 | 방송방", style="Top.TLabel").grid(row=0, column=0, sticky="w")
        self.nb = ttk.Notebook(right)
        self.nb.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.tab_chart = ttk.Frame(self.nb)
        self.tab_forum = ttk.Frame(self.nb)
        self.tab_chat = ttk.Frame(self.nb)
        self.tab_live = ttk.Frame(self.nb)
        self.nb.add(self.tab_chart, text="주식차트")
        self.nb.add(self.tab_forum, text="주식토론")
        self.nb.add(self.tab_chat, text="채팅방")
        self.nb.add(self.tab_live, text="방송방")

        self._build_tabs()

        # holdings big
        ttk.Separator(root, orient="horizontal").grid(row=3, column=0, sticky="ew", pady=(12, 10))
        hold = ttk.Frame(root, style="Card.TFrame", padding=10)
        hold.grid(row=4, column=0, sticky="ew")
        hold.columnconfigure(0, weight=1)
        ttk.Label(hold, text="보유현황(가상) | 높이 2배", style="Top.TLabel").grid(row=0, column=0, sticky="w")
        self.txt_hold = tk.Text(hold, height=8, wrap="word", bd=0, highlightthickness=0)
        self.txt_hold.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self._render_holdings()

        self._tree_info(self.kr_tree, "자동 로드 대기...")
        self._tree_info(self.us_tree, "자동 로드 대기...")

        # ✅ 메인 진입 즉시 추천 표시
        self.after(100, lambda: self.safe_call("reload_all_recos(after)", self.reload_all_recos))

    def _build_tabs(self):
        self.chart_area = ttk.Frame(self.tab_chart, padding=8)
        self.chart_area.pack(fill="both", expand=True)
        self.lbl_chart = ttk.Label(self.chart_area, text="(데모) 차트 탭", style="Sub.TLabel")
        self.lbl_chart.pack(anchor="w")
        self.forum_txt = tk.Text(self.tab_forum, wrap="word", bd=0, highlightthickness=0)
        self.forum_txt.pack(fill="both", expand=True, padx=8, pady=8)
        self.forum_txt.insert("end", "주식토론(데모)\n")
        self.chat_txt = tk.Text(self.tab_chat, wrap="word", bd=0, highlightthickness=0)
        self.chat_txt.pack(fill="both", expand=True, padx=8, pady=8)
        self.chat_txt.insert("end", "채팅방(데모)\n")
        self.live_txt = tk.Text(self.tab_live, wrap="word", bd=0, highlightthickness=0)
        self.live_txt.pack(fill="both", expand=True, padx=8, pady=8)
        self.live_txt.insert("end", "방송방(데모)\n")

    def _make_tree(self, parent, market: str):
        if market == "KR":
            cols = ("rank","ticker","name","price","signal","score")
            tree = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")
            for c, t, w in [
                ("rank","순위",50),("ticker","티커",95),("name","종목명",170),
                ("price","현재가",95),("signal","신호",70),("score","추천점수",90)
            ]:
                tree.heading(c, text=t)
                tree.column(c, width=w, anchor="center" if c in ("rank","signal") else ("e" if c in ("price","score") else "w"))
            return tree
        else:
            cols = ("rank","ticker","price","signal","score")
            tree = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")
            for c, t, w in [
                ("rank","순위",50),("ticker","티커",95),("price","현재가",95),
                ("signal","신호",70),("score","추천점수",90)
            ]:
                tree.heading(c, text=t)
                tree.column(c, width=w, anchor="center" if c in ("rank","signal") else ("e" if c in ("price","score") else "w"))
            return tree

    def _init_tree_tags(self, tree):
        tree.tag_configure("BUY", foreground=C_BUY)
        tree.tag_configure("SELL", foreground=C_SELL)
        tree.tag_configure("WATCH", foreground=C_WATCH)

    def _tree_clear(self, tree):
        for iid in tree.get_children():
            tree.delete(iid)

    def _tree_info(self, tree, text):
        cols = tree["columns"]
        tree.insert("", "end", values=(text,) + ("",) * (len(cols)-1))

    def _refresh_wallet(self):
        self.lbl_usd.config(text=f"기본계좌(달러):  $ {self.usd_cash:,.2f}")
        self.lbl_krw.config(text=f"원화:  ₩ {self.krw_cash:,.0f}")

    def _render_holdings(self):
        self.txt_hold.delete("1.0","end")
        self.txt_hold.insert("end", f"KRW 현금: ₩ {self.krw_cash:,.0f}\nUSD 현금: $ {self.usd_cash:,.2f}\n\n")
        self.txt_hold.insert("end", "[국내 보유]\n")
        self.txt_hold.insert("end", "- 없음\n" if not self.holdings["KR"] else "\n".join([f"- {k}: {v}주" for k,v in self.holdings["KR"].items()])+"\n")
        self.txt_hold.insert("end", "\n[미국 보유]\n")
        self.txt_hold.insert("end", "- 없음\n" if not self.holdings["US"] else "\n".join([f"- {k}: {v}주" for k,v in self.holdings["US"].items()])+"\n")

    # ---------- async reco ----------
    def reload_all_recos(self):
        if not YF_OK:
            self._set_status(f"yfinance 오류: {YF_ERR}")
            return

        self._set_status("추천 TOP10 로딩 시작(자동)")
        self._tree_clear(self.kr_tree); self._tree_info(self.kr_tree, "국내 로딩 중...")
        self._tree_clear(self.us_tree); self._tree_info(self.us_tree, "미국 로딩 중...")

        def worker():
            try:
                kr = build_top10(KR_UNIVERSE, "KR")
                us = build_top10(US_UNIVERSE, "US")
                self.bgq.put(("recos", kr, us))
            except Exception as e:
                self.bgq.put(("err", "reload_all_recos(worker)", e))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_bgq(self):
        try:
            while True:
                item = self.bgq.get_nowait()
                self.safe_call("handle_bg", self._handle_bg, item)
        except queue.Empty:
            pass
        self.after(120, lambda: self.safe_call("poll_bgq", self._poll_bgq))

    def _handle_bg(self, item):
        kind = item[0]
        if kind == "recos":
            _, kr, us = item
            self._render_recos(self.kr_tree, kr, "KR")
            self._render_recos(self.us_tree, us, "US")
            self._set_status("추천 TOP10 로드 완료")
        elif kind == "err":
            _, where, exc = item
            self._set_status("오류 발생(저장)")
            self.store.log_error(where, exc)
            messagebox.showerror("오류", f"{where}\n\n{exc}")

    def _render_recos(self, tree, items, market: str):
        self._tree_clear(tree)
        for idx, it in enumerate(items, 1):
            sig = it.get("signal","관망")
            tag = "WATCH"
            if sig == "매수": tag = "BUY"
            if sig == "매도": tag = "SELL"

            if market == "KR":
                row = (idx, it["ticker"], it.get("name",""), it.get("price",0.0), sig, it.get("rank_score",0.0))
            else:
                row = (idx, it["ticker"], it.get("price",0.0), sig, it.get("rank_score",0.0))
            tree.insert("", "end", values=row, tags=(tag,))

# -------------------------
# run
# -------------------------
if __name__ == "__main__":
    app = STAIApp()
    app.mainloop()


# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:




