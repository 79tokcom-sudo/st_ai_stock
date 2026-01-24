#!/usr/bin/env python
# coding: utf-8

# In[1]:


# -*- coding: utf-8 -*-
"""
천신대왕 ST AI 증권 v18.0 (Firestore + 채팅/라이브/별풍선/이모티콘/구매/추천/수익분석/최근검색/소셜로그인 골격)
✅ 요청 반영
- 구글/애플/카카오/네이버 로그인 버튼 + OAuth 시작(브라우저) + 토큰저장 자리(키만 넣으면 사용 가능)
- 추천 종목: 국내/미국 분리 탭 (클릭 → 매수창 뜨고 구매 동작)
- 다음 탭: 수익분석
- 새 섹터(탭): 최근 검색 종목 표시
- 라이브 방송 탭 복구(방송 시작/리스트/인기순/좋아요/입장)
- 채팅 탭 복구(이모티콘, 별풍선, 시스템 메시지, 속도제한)
- 매수: 현재 시장가를 수정 불가(readonly) + 5/10/50/전액 버튼 + 잔고 초과 시 차단
- 보유종목/주문내역/이번달 주문/판매수익/배당금 KPI(기본) 포함

설치:
pip install firebase-admin websockets yfinance

필수:
SERVICE_ACCOUNT_JSON 경로 맞추기

주의:
- 소셜 로그인은 각 플랫폼 개발자 콘솔에서 Client ID/Secret 발급 필요 (아래 SOCIAL_CONFIG에 입력)
"""

import os, sys, json, time, threading, queue, traceback, uuid, random, socket, webbrowser
from datetime import datetime, timedelta, date

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import firebase_admin
from firebase_admin import credentials, firestore

import yfinance as yf

import asyncio
import websockets


# =========================
# 기본 설정
# =========================
APP_NAME = "천신대왕 ST AI 증권"
APP_VERSION = "v18.0"

SERVICE_ACCOUNT_JSON = "staidb-firebase-adminsdk-fbsvc-d3ba815ea4.json"

USD_TO_KRW_RATE = 1300.0

CHAT_HOST = "127.0.0.1"
CHAT_PORT = 8765
CHAT_URL = f"ws://{CHAT_HOST}:{CHAT_PORT}"

COL_MEMBERS = "members"
COL_PAYMENT_REQUESTS = "payment_requests"
COL_CHAT_MESSAGES = "chat_messages"
COL_SYSTEM_CHECKS = "system_checks"
COL_ORDERS = "orders"
COL_DIVIDENDS = "dividends"

PLAN_1M_PRICE = 300000
PLAN_1Y_PRICE = 3000000
KB_BANK_ACCOUNT_TEXT = "KB은행 061701-04-086503 (예금주: 신주헌)"
CONTACT_TEXT = "입금후 010 7608 9847 연락바랍니다."
BOTTOM_ACCOUNT_TEXT = (
    f"유료결제/충전: {KB_BANK_ACCOUNT_TEXT} | 1달 {PLAN_1M_PRICE:,}원 / 1년 {PLAN_1Y_PRICE:,}원 | {CONTACT_TEXT}"
)

# 소셜 로그인 골격(키 발급 후 채우면 됨)
SOCIAL_CONFIG = {
    "google": {"client_id": "", "redirect_uri": "http://localhost:8787/callback", "auth_url": "https://accounts.google.com/o/oauth2/v2/auth"},
    "apple": {"client_id": "", "redirect_uri": "http://localhost:8787/callback", "auth_url": "https://appleid.apple.com/auth/authorize"},
    "kakao": {"client_id": "", "redirect_uri": "http://localhost:8787/callback", "auth_url": "https://kauth.kakao.com/oauth/authorize"},
    "naver": {"client_id": "", "redirect_uri": "http://localhost:8787/callback", "auth_url": "https://nid.naver.com/oauth2.0/authorize"},
}
TOKEN_STORE_FILE = "social_tokens.json"  # 토큰 저장(간단)

EMOTES = ["😀", "😂", "😍", "😭", "😡", "👍", "🔥", "🎉", "💎", "🚀", "🙏", "💰", "📈", "📉"]
LOBBY = "전체방"
CHAT_MIN_INTERVAL_SEC = 2.0

BALLOON_PRICE = 100.0

DEFAULT_KR = [
    ("삼성전자", "005930.KS"), ("SK하이닉스", "000660.KS"), ("현대차", "005380.KS"),
    ("카카오", "035720.KS"), ("셀트리온", "068270.KS"), ("LG화학", "051910.KS"),
    ("KT", "030200.KS"), ("매커스", "093520.KQ"), ("엘앤씨바이오", "290650.KQ"), ("와이바이오로직스", "338840.KQ")
]
DEFAULT_US = [
    ("엔비디아", "NVDA"), ("애플", "AAPL"), ("코스트코", "COST"), ("시스코", "CSCO"),
    ("핀터레스트", "PINS"), ("코노코필립스", "COP"), ("먼데이닷컴", "MNDY"),
    ("워너브로스", "WBD"), ("VSAT", "VSAT"), ("HAE", "HAE")
]


# =========================
# 유틸
# =========================
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def month_key():
    return date.today().strftime("%Y-%m")

def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def safe_int(x, default=0):
    try:
        return int(float(x))
    except Exception:
        return default

def init_firestore():
    if not firebase_admin._apps:
        if not os.path.exists(SERVICE_ACCOUNT_JSON):
            raise FileNotFoundError(f"서비스계정 JSON 없음: {SERVICE_ACCOUNT_JSON}")
        cred = credentials.Certificate(SERVICE_ACCOUNT_JSON)
        firebase_admin.initialize_app(cred)
    return firestore.client()

def fetch_market_price(ticker: str):
    """시장가(수정 불가)"""
    try:
        t = yf.Ticker(ticker)
        fi = getattr(t, "fast_info", None)
        if fi:
            lp = fi.get("last_price") or fi.get("regular_market_price") or fi.get("regularMarketPrice")
            if lp and float(lp) > 0:
                return float(lp)
    except Exception:
        pass
    try:
        t = yf.Ticker(ticker)
        info = getattr(t, "info", None)
        if info:
            p = info.get("regularMarketPrice") or info.get("currentPrice")
            if p and float(p) > 0:
                return float(p)
    except Exception:
        pass
    return None

def compute_signal_simple(ticker: str):
    """BUY/SELL/HOLD"""
    try:
        df = yf.download(ticker, period="20d", interval="1d", progress=False)
        if df is None or df.empty or "Close" not in df.columns:
            return "HOLD"
        close = df["Close"].dropna()
        if len(close) < 8:
            return "HOLD"
        d = close.diff().dropna()
        last3 = d.iloc[-3:]
        last7 = d.iloc[-7:]
        if (last3 < 0).all():
            return "SELL"
        if int((last7 > 0).sum()) >= 5:
            return "BUY"
        return "HOLD"
    except Exception:
        return "HOLD"

def fmt_money(x: float, cur="KRW"):
    if cur == "USD":
        return f"${x:,.2f}"
    return f"{x:,.0f}원"

def load_tokens():
    if os.path.exists(TOKEN_STORE_FILE):
        try:
            with open(TOKEN_STORE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_tokens(tokens: dict):
    try:
        with open(TOKEN_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(tokens, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# =========================
# Firestore Repo
# =========================
class RepoFS:
    def __init__(self, db):
        self.db = db

    def ensure_admin_bootstrap(self):
        ref = self.db.collection(COL_MEMBERS).document("admin")
        snap = ref.get()
        if snap.exists:
            d = snap.to_dict() or {}
            patch = {}
            if d.get("role") != "admin":
                patch["role"] = "admin"
                patch["grade"] = "ADMIN"
            if not d.get("subscription_expiry"):
                patch["subscription_expiry"] = "2099-12-31 23:59:59"
            if patch:
                patch["updated_at"] = firestore.SERVER_TIMESTAMP
                ref.set(patch, merge=True)
            return

        ref.set({
            "user_id": "admin",
            "password": "tt1234",
            "phone": "",
            "role": "admin",
            "grade": "ADMIN",
            "payment_status": "ACTIVE",
            "subscription_expiry": "2099-12-31 23:59:59",
            "balance_krw": 0.0,
            "balance_usd": 0.0,
            "balance_cash": 0.0,
            "holdings": {},
            "recent_stocks": [],
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP
        }, merge=True)

    def member_get(self, user_id: str):
        snap = self.db.collection(COL_MEMBERS).document(user_id).get()
        return snap.to_dict() if snap.exists else None

    def member_create(self, user_id: str, pw: str, phone: str = ""):
        ref = self.db.collection(COL_MEMBERS).document(user_id)
        if ref.get().exists:
            return False, "이미 존재하는 ID"
        start = datetime.now()
        expiry = start + timedelta(hours=24)
        ref.set({
            "user_id": user_id,
            "password": pw,
            "phone": phone,
            "role": "user",
            "grade": "BASIC",
            "payment_status": "TRIAL",
            "trial_start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "subscription_expiry": expiry.strftime("%Y-%m-%d %H:%M:%S"),
            "balance_krw": 0.0,
            "balance_usd": 0.0,
            "balance_cash": 0.0,
            "holdings": {},
            "recent_stocks": [],
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP
        }, merge=True)
        return True, "회원가입 완료(무료 24시간 시작)"

    def verify_login(self, user_id: str, pw: str):
        m = self.member_get(user_id)
        if not m:
            return False
        return (m.get("password") == pw)

    def member_update(self, user_id: str, patch: dict):
        self.db.collection(COL_MEMBERS).document(user_id).set({**patch, "updated_at": firestore.SERVER_TIMESTAMP}, merge=True)

    def create_payment_request(self, user_id: str, typ: str, depositor: str, amount: float, phone: str, memo: str):
        self.db.collection(COL_PAYMENT_REQUESTS).add({
            "user_id": user_id,
            "type": typ,  # PLAN_1M/PLAN_1Y/KRW/USD/CASH
            "depositor": depositor,
            "amount": float(amount),
            "phone": phone,
            "memo": memo,
            "status": "PENDING",
            "bank": KB_BANK_ACCOUNT_TEXT,
            "contact": CONTACT_TEXT,
            "client_time": now_str(),
            "created_at": firestore.SERVER_TIMESTAMP
        })

    def add_order(self, order: dict):
        self.db.collection(COL_ORDERS).add(order)

    def list_orders_for_user(self, user_id: str, limit=200):
        out = []
        q = (self.db.collection(COL_ORDERS)
             .where("user_id", "==", user_id)
             .order_by("created_at", direction=firestore.Query.DESCENDING)
             .limit(limit))
        for s in q.stream():
            d = s.to_dict() or {}
            d["_id"] = s.id
            out.append(d)
        return out

    def sum_dividends_month(self, user_id: str, month: str):
        total = 0.0
        try:
            q = (self.db.collection(COL_DIVIDENDS)
                 .where("user_id", "==", user_id)
                 .where("month", "==", month)
                 .limit(200))
            for s in q.stream():
                d = s.to_dict() or {}
                total += float(d.get("amount", 0.0))
        except Exception:
            pass
        return total

    def save_chat_message(self, room: str, msg_type: str, user: str, message: str = "", gift: str = "", count: int = 0):
        try:
            self.db.collection(COL_CHAT_MESSAGES).add({
                "room": room,
                "msg_type": msg_type,
                "user": user,
                "message": message,
                "gift": gift,
                "count": int(count),
                "time": now_str(),
                "created_at": firestore.SERVER_TIMESTAMP
            })
        except Exception:
            pass


# =========================
# Embedded WebSocket Server (채팅 + 라이브 방송)
# =========================
class EmbeddedServer:
    def __init__(self, repo: RepoFS, host=CHAT_HOST, port=CHAT_PORT):
        self.repo = repo
        self.host = host
        self.port = port
        self.thread = None

        self.lock = threading.Lock()
        self.rooms = {}           # room -> set(ws)
        self.ws_room = {}         # ws -> room
        self.ws_last_send = {}    # ws -> ts

        # 라이브 방송
        self.broadcasts = {}      # bid -> {title, host, room, started_at, likes}
        self.gift_score = {}      # bid -> gift count

    def start(self):
        if self.thread and self.thread.is_alive():
            return

        def runner():
            try:
                asyncio.run(self._main())
            except OSError:
                # 포트 이미 사용 중
                pass
            except Exception:
                pass

        self.thread = threading.Thread(target=runner, daemon=True)
        self.thread.start()

    def _can_send(self, ws):
        now = time.time()
        last = self.ws_last_send.get(ws, 0.0)
        if (now - last) < CHAT_MIN_INTERVAL_SEC:
            return False
        self.ws_last_send[ws] = now
        return True

    def _broadcast_list_payload(self):
        out = []
        with self.lock:
            for bid, b in self.broadcasts.items():
                room = b.get("room", "")
                viewers = len(self.rooms.get(room, set()))
                likes = int(b.get("likes", 0))
                gifts = int(self.gift_score.get(bid, 0))
                score = viewers + likes * 0.5 + gifts * 0.2
                out.append({
                    "id": bid,
                    "title": b.get("title", ""),
                    "host": b.get("host", ""),
                    "started_at": b.get("started_at", ""),
                    "room": room,
                    "viewers": viewers,
                    "likes": likes,
                    "gifts": gifts,
                    "score": score
                })
        out.sort(key=lambda x: (x["score"], x["viewers"], x["likes"]), reverse=True)
        return out

    async def _send(self, ws, payload: dict):
        try:
            await ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

    async def _broadcast_room(self, room: str, payload: dict):
        with self.lock:
            clients = list(self.rooms.get(room, set()))
        msg = json.dumps(payload, ensure_ascii=False)
        for c in clients:
            try:
                await c.send(msg)
            except Exception:
                pass

    async def _broadcast_list_all(self):
        payload = {"type": "broadcast_list", "time": now_str(), "items": self._broadcast_list_payload()}
        with self.lock:
            all_clients = []
            for s in self.rooms.values():
                all_clients.extend(list(s))
        uniq = list({id(ws): ws for ws in all_clients}.values())
        msg = json.dumps(payload, ensure_ascii=False)
        for ws in uniq:
            try:
                await ws.send(msg)
            except Exception:
                pass

    async def _handler(self, ws):
        room = LOBBY
        with self.lock:
            self.rooms.setdefault(room, set()).add(ws)
            self.ws_room[ws] = room

        await self._send(ws, {"type": "broadcast_list", "time": now_str(), "items": self._broadcast_list_payload()})

        try:
            async for raw in ws:
                try:
                    payload = json.loads(raw)
                except Exception:
                    payload = {"type": "chat", "room": room, "user": "unknown", "message": raw}

                typ = payload.get("type")

                if typ == "join":
                    new_room = (payload.get("room") or LOBBY).strip() or LOBBY
                    if new_room != room:
                        with self.lock:
                            self.rooms.get(room, set()).discard(ws)
                            self.rooms.setdefault(new_room, set()).add(ws)
                            self.ws_room[ws] = new_room
                        room = new_room
                        await self._broadcast_list_all()
                    continue

                if typ == "broadcast_list":
                    await self._send(ws, {"type": "broadcast_list", "time": now_str(), "items": self._broadcast_list_payload()})
                    continue

                if typ == "broadcast_create":
                    host = str(payload.get("host", "unknown"))[:40]
                    title = str(payload.get("title", "무제"))[:80]
                    bid = "b" + uuid.uuid4().hex[:10]
                    b_room = f"bcast:{bid}"
                    with self.lock:
                        self.broadcasts[bid] = {
                            "title": title,
                            "host": host,
                            "room": b_room,
                            "started_at": now_str(),
                            "likes": 0
                        }
                        self.gift_score[bid] = 0
                    await self._send(ws, {"type": "broadcast_created", "id": bid, "room": b_room})
                    await self._broadcast_list_all()
                    continue

                if typ == "broadcast_like":
                    bid = str(payload.get("id", ""))
                    with self.lock:
                        if bid in self.broadcasts:
                            self.broadcasts[bid]["likes"] = int(self.broadcasts[bid].get("likes", 0)) + 1
                    await self._broadcast_list_all()
                    continue

                if typ == "broadcast_end":
                    bid = str(payload.get("id", ""))
                    with self.lock:
                        self.broadcasts.pop(bid, None)
                        self.gift_score.pop(bid, None)
                    await self._broadcast_list_all()
                    continue

                if typ in ("chat", "gift"):
                    if not self._can_send(ws):
                        await self._send(ws, {"type": "system", "room": room, "time": now_str(), "message": "전송 속도 제한(2초)"})
                        continue

                    room2 = (payload.get("room") or room).strip() or room
                    user = str(payload.get("user", "unknown"))[:40]
                    payload["room"] = room2
                    payload["time"] = now_str()

                    if typ == "chat":
                        self.repo.save_chat_message(room2, "chat", user=user, message=str(payload.get("message", ""))[:500])
                    else:
                        cnt = int(payload.get("count", 1))
                        gift = str(payload.get("gift", "🎁"))[:20]
                        self.repo.save_chat_message(room2, "gift", user=user, gift=gift, count=cnt)
                        if room2.startswith("bcast:"):
                            bid = room2.replace("bcast:", "")
                            with self.lock:
                                self.gift_score[bid] = int(self.gift_score.get(bid, 0)) + int(cnt)
                            await self._broadcast_list_all()

                    await self._broadcast_room(room2, payload)
                    continue

        except Exception:
            pass
        finally:
            with self.lock:
                cr = self.ws_room.get(ws, LOBBY)
                self.rooms.get(cr, set()).discard(ws)
                self.ws_room.pop(ws, None)
                self.ws_last_send.pop(ws, None)
            await self._broadcast_list_all()

    async def _main(self):
        async with websockets.serve(self._handler, self.host, self.port, ping_interval=20, ping_timeout=20):
            while True:
                await asyncio.sleep(3600)


# =========================
# App
# =========================
class STApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("1900x1020")
        self.root.configure(bg="white")

        self.db = init_firestore()
        self.repo = RepoFS(self.db)
        self.repo.ensure_admin_bootstrap()

        self.server = EmbeddedServer(self.repo)
        self.server.start()

        # 상태
        self.current_user = "guest"
        self.role = "guest"
        self.grade = "GUEST"

        self.user_data = {
            "balance_krw": 0.0,
            "balance_usd": 0.0,
            "balance_cash": 0.0,
            "holdings": {},         # ticker -> {name, qty, avg_price, currency}
            "recent_stocks": [],    # [{name,ticker,time}]
            "subscription_expiry": ""
        }
        self.orders_cache = []
        self.live_items = []

        # worker
        self.work_q = queue.Queue()
        self.ui_q = queue.Queue()
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()

        # ws client
        self.ws_connected = False
        self.ws_thread = None
        self.ws_send_q = queue.Queue()
        self.ws_ui_q = queue.Queue()
        self.chat_room = LOBBY
        self.last_send_ts = 0.0

        self._build_login()
        self.root.after(150, self._tick)

    # ---------------- worker ----------------
    def _worker_loop(self):
        while True:
            job = self.work_q.get()
            if job is None:
                break
            fn, args = job
            try:
                res = fn(*args)
                self.ui_q.put(("OK", fn.__name__, res))
            except Exception as e:
                self.ui_q.put(("ERR", fn.__name__, str(e)))

    def _tick(self):
        try:
            while not self.ui_q.empty():
                tag = self.ui_q.get_nowait()
                if tag[0] == "OK":
                    _, name, res = tag
                    if name == "job_refresh_signals":
                        self._apply_signals(res)
                    elif name == "job_refresh_prices":
                        self._apply_prices(res)
                else:
                    _, name, msg = tag
                    print("[WORKER_ERR]", name, msg)
        except Exception:
            pass

        try:
            while not self.ws_ui_q.empty():
                payload = self.ws_ui_q.get_nowait()
                self._on_ws_payload(payload)
        except Exception:
            pass

        self.root.after(150, self._tick)

    # ---------------- ws ----------------
    def connect_ws(self):
        if self.ws_connected:
            return

        def loop():
            async def run():
                try:
                    async with websockets.connect(CHAT_URL, ping_interval=20, ping_timeout=20) as ws:
                        self.ws_connected = True

                        async def sender():
                            while True:
                                msg = await asyncio.get_event_loop().run_in_executor(None, self.ws_send_q.get)
                                await ws.send(msg)

                        async def receiver():
                            while True:
                                data = await ws.recv()
                                try:
                                    payload = json.loads(data)
                                except Exception:
                                    payload = {"type": "system_local", "message": str(data)}
                                self.ws_ui_q.put(payload)

                        await ws.send(json.dumps({"type": "join", "room": self.chat_room}, ensure_ascii=False))
                        await asyncio.gather(sender(), receiver())
                except Exception as e:
                    self.ws_connected = False
                    self.ws_ui_q.put({"type": "system_local", "message": f"WS 끊김: {e}"})

            asyncio.run(run())

        self.ws_thread = threading.Thread(target=loop, daemon=True)
        self.ws_thread.start()

    def ws_send(self, payload: dict):
        if not self.ws_connected:
            self.connect_ws()
            time.sleep(0.08)
        self.ws_send_q.put(json.dumps(payload, ensure_ascii=False))

    def _can_send_client(self):
        now = time.time()
        if (now - self.last_send_ts) < CHAT_MIN_INTERVAL_SEC:
            return False
        self.last_send_ts = now
        return True

    # ---------------- util ----------------
    def _clear(self):
        for w in self.root.winfo_children():
            w.destroy()

    def total_krw(self):
        return float(self.user_data.get("balance_krw", 0.0)) + float(self.user_data.get("balance_usd", 0.0)) * USD_TO_KRW_RATE

    def refresh_topbar(self):
        if hasattr(self, "top_total_var"):
            self.top_total_var.set(f"총금액 {self.total_krw():,.0f}원 | KRW {self.user_data['balance_krw']:,.0f} | USD {self.user_data['balance_usd']:,.2f} | CASH {self.user_data['balance_cash']:,.0f}")
        if hasattr(self, "kpi_orders_var"):
            self._refresh_kpis()

    def _refresh_kpis(self):
        m = month_key()
        month_orders = [o for o in (self.orders_cache or []) if str(o.get("time", "")).startswith(m)]
        order_count = len(month_orders)
        realized = sum(float(o.get("realized_pnl", 0.0)) for o in month_orders if o.get("side") == "SELL")
        div_total = 0.0
        if self.current_user != "guest":
            div_total = float(self.repo.sum_dividends_month(self.current_user, m))

        self.kpi_orders_var.set(f"이번달 주문: {order_count}건")
        self.kpi_pnl_var.set(f"이번달 판매수익: {realized:,.0f}원")
        self.kpi_div_var.set(f"이번달 배당금: {div_total:,.0f}원")

    def _push_recent(self, name: str, ticker: str):
        recent = list(self.user_data.get("recent_stocks", []))
        recent = [x for x in recent if x.get("ticker") != ticker]
        recent.insert(0, {"name": name, "ticker": ticker, "time": now_str()})
        recent = recent[:15]
        self.user_data["recent_stocks"] = recent
        self._render_recent_tab()
        if self.current_user != "guest":
            self.repo.member_update(self.current_user, {"recent_stocks": recent})

    # ---------------- Social Login skeleton ----------------
    def social_login_start(self, provider: str):
        cfg = SOCIAL_CONFIG.get(provider, {})
        cid = cfg.get("client_id", "")
        redir = cfg.get("redirect_uri", "")
        auth = cfg.get("auth_url", "")
        if not cid or not redir or not auth:
            messagebox.showwarning("설정 필요", f"{provider} 로그인은 Client ID/Redirect URI 설정이 필요합니다.\nSOCIAL_CONFIG에 값을 넣어주세요.")
            return
        # 최소 OAuth 시작(권한/스코프는 서비스에 맞게 조정)
        url = auth
        if provider == "google":
            scope = "openid%20email%20profile"
            url = f"{auth}?client_id={cid}&redirect_uri={redir}&response_type=code&scope={scope}&access_type=offline&prompt=consent"
        elif provider == "kakao":
            url = f"{auth}?client_id={cid}&redirect_uri={redir}&response_type=code"
        elif provider == "naver":
            state = uuid.uuid4().hex[:12]
            url = f"{auth}?client_id={cid}&redirect_uri={redir}&response_type=code&state={state}"
        elif provider == "apple":
            url = f"{auth}?client_id={cid}&redirect_uri={redir}&response_type=code%20id_token&response_mode=form_post&scope=name%20email"
        webbrowser.open(url)
        messagebox.showinfo("안내", "브라우저에서 로그인 후, 콜백 코드(code)를 복사해서 앱에 붙여넣어 토큰 교환을 진행해야 합니다.\n(v18.0은 토큰 교환 자리는 준비되어 있고, 키/서버 설정이 필요합니다.)")

    # ---------------- Login UI ----------------
    def _build_login(self):
        self._clear()
        box = tk.Frame(self.root, bg="white")
        box.pack(expand=True)

        tk.Label(box, text=APP_NAME, bg="white", fg="#0064FF",
                 font=("맑은 고딕", 44, "bold")).pack(pady=16)

        frm = tk.Frame(box, bg="white")
        frm.pack(pady=8)

        tk.Label(frm, text="ID", bg="white", fg="#0064FF", font=("맑은 고딕", 14, "bold")).grid(row=0, column=0, padx=10, pady=10, sticky="e")
        self.id_entry = tk.Entry(frm, font=("맑은 고딕", 14), width=28)
        self.id_entry.grid(row=0, column=1, padx=10, pady=10)

        tk.Label(frm, text="PW", bg="white", fg="#0064FF", font=("맑은 고딕", 14, "bold")).grid(row=1, column=0, padx=10, pady=10, sticky="e")
        self.pw_entry = tk.Entry(frm, font=("맑은 고딕", 14), width=28, show="*")
        self.pw_entry.grid(row=1, column=1, padx=10, pady=10)

        btns = tk.Frame(box, bg="white")
        btns.pack(pady=10)

        tk.Button(btns, text="로그인", bg="#0064FF", fg="white",
                  font=("맑은 고딕", 16, "bold"), width=10, command=self.login).grid(row=0, column=0, padx=6)

        tk.Button(btns, text="회원가입", bg="#111111", fg="white",
                  font=("맑은 고딕", 16, "bold"), width=10, command=self.signup).grid(row=0, column=1, padx=6)

        tk.Button(btns, text="게스트", bg="white", fg="#0064FF",
                  font=("맑은 고딕", 16, "bold"), width=10, command=self.guest).grid(row=0, column=2, padx=6)

        # 소셜 로그인 버튼
        sbox = tk.LabelFrame(box, text="소셜 로그인(설정 필요)", bg="white", fg="#0064FF", font=("맑은 고딕", 12, "bold"))
        sbox.pack(pady=12, padx=20, fill="x")

        row = tk.Frame(sbox, bg="white")
        row.pack(pady=10)
        tk.Button(row, text="Google", bg="#f3f5f7", font=("맑은 고딕", 12, "bold"),
                  command=lambda: self.social_login_start("google")).pack(side="left", padx=6)
        tk.Button(row, text="Apple", bg="#f3f5f7", font=("맑은 고딕", 12, "bold"),
                  command=lambda: self.social_login_start("apple")).pack(side="left", padx=6)
        tk.Button(row, text="Kakao", bg="#f3f5f7", font=("맑은 고딕", 12, "bold"),
                  command=lambda: self.social_login_start("kakao")).pack(side="left", padx=6)
        tk.Button(row, text="Naver", bg="#f3f5f7", font=("맑은 고딕", 12, "bold"),
                  command=lambda: self.social_login_start("naver")).pack(side="left", padx=6)

        tk.Label(box, text=BOTTOM_ACCOUNT_TEXT, bg="white", fg="#666666", font=("맑은 고딕", 12)).pack(pady=12)

    def guest(self):
        self.current_user = "guest"
        self.role = "guest"
        self.grade = "GUEST"
        self.user_data = {"balance_krw": 0.0, "balance_usd": 0.0, "balance_cash": 0.0,
                          "holdings": {}, "recent_stocks": [], "subscription_expiry": ""}
        self.orders_cache = []
        self._build_main()

    def signup(self):
        uid = self.id_entry.get().strip()
        pw = self.pw_entry.get().strip()
        if not uid or not pw:
            messagebox.showwarning("오류", "ID/PW 입력")
            return
        phone = simpledialog.askstring("회원가입", "휴대폰(선택):") or ""
        ok, msg = self.repo.member_create(uid, pw, phone=phone)
        messagebox.showinfo("결과", msg)

    def login(self):
        uid = self.id_entry.get().strip()
        pw = self.pw_entry.get().strip()
        if not uid or not pw:
            messagebox.showwarning("오류", "ID/PW 입력")
            return
        if not self.repo.verify_login(uid, pw):
            messagebox.showerror("실패", "로그인 실패")
            return

        m = self.repo.member_get(uid) or {}
        self.current_user = uid
        self.role = m.get("role", "user")
        self.grade = m.get("grade", "BASIC")

        self.user_data = {
            "balance_krw": float(m.get("balance_krw", 0.0)),
            "balance_usd": float(m.get("balance_usd", 0.0)),
            "balance_cash": float(m.get("balance_cash", 0.0)),
            "holdings": dict(m.get("holdings", {}) or {}),
            "recent_stocks": list(m.get("recent_stocks", []) or []),
            "subscription_expiry": str(m.get("subscription_expiry") or "")
        }
        self.orders_cache = self.repo.list_orders_for_user(uid, limit=200)
        self._build_main()

    # ---------------- Main UI ----------------
    def _build_main(self):
        self._clear()
        self.connect_ws()

        header = tk.Frame(self.root, bg="#0064FF")
        header.pack(fill="x")

        tk.Label(header, text=f"{APP_NAME} | {self.current_user} ({self.role}/{self.grade})",
                 bg="#0064FF", fg="white", font=("맑은 고딕", 15, "bold")).pack(side="left", padx=14, pady=10)

        self.top_total_var = tk.StringVar(value=f"총금액 {self.total_krw():,.0f}원 | KRW {self.user_data['balance_krw']:,.0f} | USD {self.user_data['balance_usd']:,.2f} | CASH {self.user_data['balance_cash']:,.0f}")
        tk.Label(header, textvariable=self.top_total_var,
                 bg="#0064FF", fg="white", font=("맑은 고딕", 12, "bold")).pack(side="left", padx=18)

        right = tk.Frame(header, bg="#0064FF")
        right.pack(side="right", padx=10)

        tk.Button(right, text="충전하기", bg="white", fg="#0064FF", bd=0,
                  font=("맑은 고딕", 12, "bold"), command=self.open_charge_popup).pack(side="right", padx=8)
        tk.Button(right, text="가격갱신", bg="white", fg="#0064FF", bd=0,
                  font=("맑은 고딕", 12, "bold"), command=self.refresh_prices).pack(side="right", padx=8)

        body = tk.Frame(self.root, bg="white")
        body.pack(fill="both", expand=True, padx=12, pady=12)

        # KPI
        kpi = tk.Frame(body, bg="white")
        kpi.pack(fill="x", pady=(0, 10))

        self.kpi_orders_var = tk.StringVar()
        self.kpi_pnl_var = tk.StringVar()
        self.kpi_div_var = tk.StringVar()
        self._refresh_kpis()

        def card(textvar):
            f = tk.Frame(kpi, bg="#f3f5f7")
            f.pack(side="left", padx=8)
            tk.Label(f, textvariable=textvar, bg="#f3f5f7", fg="#111111",
                     font=("맑은 고딕", 14, "bold"), width=22, anchor="w").pack(padx=10, pady=10)

        card(self.kpi_orders_var)
        card(self.kpi_pnl_var)
        card(self.kpi_div_var)

        # Notebook
        self.nb = ttk.Notebook(body)
        self.nb.pack(fill="both", expand=True)

        self.tab_kr = tk.Frame(self.nb, bg="white")
        self.tab_us = tk.Frame(self.nb, bg="white")
        self.tab_analysis = tk.Frame(self.nb, bg="white")
        self.tab_recent = tk.Frame(self.nb, bg="white")
        self.tab_chat = tk.Frame(self.nb, bg="white")
        self.tab_live = tk.Frame(self.nb, bg="white")
        self.tab_portfolio = tk.Frame(self.nb, bg="white")
        self.tab_orders = tk.Frame(self.nb, bg="white")

        self.nb.add(self.tab_kr, text="국내 추천")
        self.nb.add(self.tab_us, text="미국 추천")
        self.nb.add(self.tab_analysis, text="수익분석")
        self.nb.add(self.tab_recent, text="최근검색")
        self.nb.add(self.tab_portfolio, text="보유종목")
        self.nb.add(self.tab_orders, text="주문내역")
        self.nb.add(self.tab_chat, text="채팅")
        self.nb.add(self.tab_live, text="라이브")

        self._build_reco_tab(self.tab_kr, market="KR")
        self._build_reco_tab(self.tab_us, market="US")
        self._build_analysis_tab(self.tab_analysis)
        self._build_recent_tab(self.tab_recent)
        self._build_portfolio_tab(self.tab_portfolio)
        self._build_orders_tab(self.tab_orders)
        self._build_chat_tab(self.tab_chat)
        self._build_live_tab(self.tab_live)

        tk.Label(body, text=BOTTOM_ACCOUNT_TEXT, bg="white", fg="#666666",
                 font=("맑은 고딕", 11)).pack(fill="x", pady=(10, 0))

        # 최초 신호 갱신
        self.work_q.put((self.job_refresh_signals, ()))

        # 초기 렌더
        self._render_recent_tab()
        self._render_portfolio({})
        self._render_orders()

    # ---------------- Tabs ----------------
    def _build_reco_tab(self, parent, market="KR"):
        bar = tk.Frame(parent, bg="white")
        bar.pack(fill="x", padx=10, pady=10)

        tk.Label(bar, text="종목 더블클릭 → 매수창", bg="white", fg="#0064FF",
                 font=("맑은 고딕", 12, "bold")).pack(side="left")

        cols = ("종목", "티커", "신호")
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=18)
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, anchor="center")
        tree.column("종목", width=280)
        tree.column("티커", width=160)
        tree.column("신호", width=120)
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        tree.tag_configure("BUY", foreground="#0a8a2a")
        tree.tag_configure("SELL", foreground="#d02626")
        tree.tag_configure("HOLD", foreground="#666666")

        stocks = DEFAULT_KR if market == "KR" else DEFAULT_US
        for name, tkr in stocks:
            tree.insert("", "end", values=(name, tkr, "HOLD"), tags=("HOLD",))

        def on_dbl(_e):
            sel = tree.selection()
            if not sel:
                return
            name, ticker, sig = tree.item(sel[0], "values")
            self._push_recent(name, ticker)
            self.open_market_buy_popup(name, ticker, sig)

        tree.bind("<Double-Button-1>", on_dbl)

        if market == "KR":
            self.tree_kr = tree
        else:
            self.tree_us = tree

    def _build_analysis_tab(self, parent):
        self.analysis_text = tk.Text(parent, font=("맑은 고딕", 12))
        self.analysis_text.pack(fill="both", expand=True, padx=10, pady=10)
        self._set_analysis("수익분석: 보유 종목이 있으면 '가격갱신'을 눌러 현재가 반영 후 자동 계산됩니다.\n")

    def _build_recent_tab(self, parent):
        top = tk.Frame(parent, bg="white")
        top.pack(fill="x", padx=10, pady=10)
        tk.Label(top, text="최근 검색/클릭한 종목", bg="white", fg="#0064FF",
                 font=("맑은 고딕", 12, "bold")).pack(side="left")
        self.recent_list = tk.Listbox(parent, height=20, font=("맑은 고딕", 12))
        self.recent_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _build_portfolio_tab(self, parent):
        cols = ("종목", "티커", "수량", "평단", "현재가", "손익", "수익률(%)")
        self.tree_port = ttk.Treeview(parent, columns=cols, show="headings", height=18)
        for c in cols:
            self.tree_port.heading(c, text=c)
            self.tree_port.column(c, anchor="center")
        self.tree_port.column("종목", width=260)
        self.tree_port.column("티커", width=160)
        self.tree_port.column("수량", width=90)
        self.tree_port.column("평단", width=120)
        self.tree_port.column("현재가", width=120)
        self.tree_port.column("손익", width=150)
        self.tree_port.column("수익률(%)", width=120)
        self.tree_port.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Button(parent, text="선택 종목 매도", bg="#ff3b30", fg="white",
                  font=("맑은 고딕", 12, "bold"), command=self.sell_selected).pack(pady=6)

    def _build_orders_tab(self, parent):
        cols = ("시간", "구분", "종목", "티커", "수량", "체결가", "통화", "금액")
        self.tree_orders = ttk.Treeview(parent, columns=cols, show="headings", height=18)
        for c in cols:
            self.tree_orders.heading(c, text=c)
            self.tree_orders.column(c, anchor="center")
        self.tree_orders.column("시간", width=170)
        self.tree_orders.column("구분", width=80)
        self.tree_orders.column("종목", width=240)
        self.tree_orders.column("티커", width=150)
        self.tree_orders.column("수량", width=90)
        self.tree_orders.column("체결가", width=120)
        self.tree_orders.column("통화", width=70)
        self.tree_orders.column("금액", width=120)
        self.tree_orders.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Button(parent, text="주문내역 새로고침", bg="#0064FF", fg="white",
                  font=("맑은 고딕", 11, "bold"), command=self.reload_orders).pack(pady=6)

    def _build_chat_tab(self, parent):
        self.chat_text = tk.Text(parent, font=("맑은 고딕", 11))
        self.chat_text.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        self.chat_text.configure(state="disabled")

        self.chat_canvas = tk.Canvas(parent, bg="", highlightthickness=0, height=1)
        self.chat_canvas.pack(fill="x", padx=10)

        em = tk.Frame(parent, bg="white")
        em.pack(fill="x", padx=10, pady=6)
        for e in EMOTES:
            tk.Button(em, text=e, bg="#f3f5f7", command=lambda x=e: self.chat_entry.insert(tk.END, x)).pack(side="left", padx=3)

        bottom = tk.Frame(parent, bg="white")
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        self.chat_entry = tk.Entry(bottom, font=("맑은 고딕", 12))
        self.chat_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        tk.Button(bottom, text="전송", bg="#0064FF", fg="white", font=("맑은 고딕", 12, "bold"),
                  command=self.chat_send).pack(side="right", padx=6)
        tk.Button(bottom, text="🎈별풍선", bg="#ff3b30", fg="white", font=("맑은 고딕", 12, "bold"),
                  command=self.chat_send_balloon).pack(side="right", padx=6)

    def _build_live_tab(self, parent):
        top = tk.Frame(parent, bg="white")
        top.pack(fill="x", padx=10, pady=10)

        tk.Button(top, text="방송 시작", bg="#111111", fg="white", font=("맑은 고딕", 11, "bold"),
                  command=self.live_start).pack(side="left", padx=6)

        tk.Button(top, text="리스트 새로고침", bg="#0064FF", fg="white", font=("맑은 고딕", 11, "bold"),
                  command=lambda: self.ws_send({"type": "broadcast_list"})).pack(side="left", padx=6)

        cols = ("순위", "제목", "호스트", "시청자", "좋아요", "선물", "점수", "시작")
        self.live_tree = ttk.Treeview(parent, columns=cols, show="headings", height=18)
        for c in cols:
            self.live_tree.heading(c, text=c)
            self.live_tree.column(c, anchor="center")
        self.live_tree.column("순위", width=60)
        self.live_tree.column("제목", width=360)
        self.live_tree.column("호스트", width=140)
        self.live_tree.column("시청자", width=90)
        self.live_tree.column("좋아요", width=90)
        self.live_tree.column("선물", width=90)
        self.live_tree.column("점수", width=90)
        self.live_tree.column("시작", width=160)
        self.live_tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        bar = tk.Frame(parent, bg="white")
        bar.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(bar, text="입장(시청)", bg="#0064FF", fg="white", font=("맑은 고딕", 11, "bold"),
                  command=self.live_join).pack(side="right", padx=6)
        tk.Button(bar, text="좋아요 👍", bg="#111111", fg="white", font=("맑은 고딕", 11, "bold"),
                  command=self.live_like).pack(side="right", padx=6)
        tk.Button(bar, text="방송 종료(호스트)", bg="#ff3b30", fg="white", font=("맑은 고딕", 11, "bold"),
                  command=self.live_end).pack(side="right", padx=6)

        # 최초 리스트 요청
        self.ws_send({"type": "broadcast_list"})

    # ---------------- Chat actions ----------------
    def _append_chat(self, line: str):
        self.chat_text.configure(state="normal")
        self.chat_text.insert(tk.END, line + "\n")
        self.chat_text.see(tk.END)
        self.chat_text.configure(state="disabled")

    def chat_send(self):
        txt = self.chat_entry.get().strip()
        if not txt:
            return
        if not self._can_send_client():
            messagebox.showwarning("제한", "전송 속도 제한(2초)")
            return
        self.ws_send({"type": "chat", "room": self.chat_room, "user": self.current_user, "message": txt})
        self.chat_entry.delete(0, tk.END)

    def _balloon_anim(self, count: int):
        try:
            w = self.chat_canvas.winfo_width()
            h = 260
        except Exception:
            return
        items = []
        for _ in range(max(1, min(10, count))):
            x = max(30, w // 2 + random.randint(-180, 180))
            y = h + random.randint(-10, 10)
            items.append(self.chat_canvas.create_text(x, y, text="🎈", font=("맑은 고딕", 26, "bold")))
        steps = {"n": 0}

        def step():
            steps["n"] += 1
            for it in items:
                try:
                    self.chat_canvas.move(it, 0, -10)
                except Exception:
                    pass
            if steps["n"] > 24:
                for it in items:
                    try:
                        self.chat_canvas.delete(it)
                    except Exception:
                        pass
                return
            self.chat_canvas.after(40, step)

        step()

    def chat_send_balloon(self):
        if self.current_user == "guest":
            messagebox.showwarning("제한", "게스트는 별풍선이 제한됩니다.")
            return
        if not self._can_send_client():
            messagebox.showwarning("제한", "전송 속도 제한(2초)")
            return
        cnt = safe_int(simpledialog.askstring("별풍선", "몇 개?"), 1)
        if cnt <= 0:
            return
        total_cost = BALLOON_PRICE * cnt
        if float(self.user_data.get("balance_cash", 0.0)) < total_cost:
            messagebox.showwarning("캐쉬 부족", f"CASH 부족\n필요: {total_cost:,.0f}\n보유: {self.user_data['balance_cash']:,.0f}\n충전하기로 CASH 충전 신청하세요.")
            return
        self.user_data["balance_cash"] -= total_cost
        if self.current_user != "guest":
            self.repo.member_update(self.current_user, {"balance_cash": self.user_data["balance_cash"]})
        self.refresh_topbar()
        self.ws_send({"type": "gift", "room": self.chat_room, "user": self.current_user, "gift": "🎈별풍선", "count": cnt,
                      "message": f"🎈 x{cnt} (CASH -{total_cost:,.0f})"})

    # ---------------- Live actions ----------------
    def live_start(self):
        if self.current_user == "guest":
            messagebox.showwarning("제한", "게스트는 방송 시작 불가")
            return
        title = simpledialog.askstring("방송 시작", "방송 제목:")
        if not title:
            return
        self.ws_send({"type": "broadcast_create", "host": self.current_user, "title": title})

    def _selected_live(self):
        sel = self.live_tree.selection()
        if not sel:
            return None
        bid = sel[0]
        for it in self.live_items:
            if it.get("id") == bid:
                return it
        return None

    def live_join(self):
        it = self._selected_live()
        if not it:
            messagebox.showwarning("선택", "방송 선택")
            return
        room = it.get("room")
        if not room:
            return
        self.chat_room = room
        self.ws_send({"type": "join", "room": room})
        self._append_chat(f"[SYSTEM] 방송 입장: {it.get('title')} / 방: {room}")

    def live_like(self):
        it = self._selected_live()
        if not it:
            messagebox.showwarning("선택", "방송 선택")
            return
        self.ws_send({"type": "broadcast_like", "id": it.get("id")})

    def live_end(self):
        it = self._selected_live()
        if not it:
            messagebox.showwarning("선택", "방송 선택")
            return
        if it.get("host") != self.current_user:
            messagebox.showwarning("권한", "호스트만 종료 가능")
            return
        self.ws_send({"type": "broadcast_end", "id": it.get("id")})

    # ---------------- WS receive ----------------
    def _on_ws_payload(self, payload: dict):
        typ = payload.get("type")

        if typ == "system_local":
            self._append_chat(f"[LOCAL] {payload.get('message')}")
            return

        if typ == "broadcast_list":
            self.live_items = payload.get("items", []) or []
            for r in self.live_tree.get_children():
                self.live_tree.delete(r)
            for idx, it in enumerate(self.live_items, start=1):
                bid = it.get("id")
                if not bid:
                    continue
                self.live_tree.insert("", "end", iid=bid, values=(
                    idx, it.get("title", ""), it.get("host", ""),
                    it.get("viewers", 0), it.get("likes", 0), it.get("gifts", 0),
                    f"{float(it.get('score', 0.0)):.1f}", it.get("started_at", "")
                ))
            return

        if typ == "broadcast_created":
            room = payload.get("room")
            bid = payload.get("id")
            self.chat_room = room
            self.ws_send({"type": "join", "room": room})
            self._append_chat(f"[SYSTEM] 방송 시작 완료! id={bid} room={room}")
            self.ws_send({"type": "broadcast_list"})
            return

        if typ == "chat":
            if payload.get("room") != self.chat_room:
                return
            self._append_chat(f"{payload.get('time','')} {payload.get('user','')}: {payload.get('message','')}")
            return

        if typ == "gift":
            if payload.get("room") != self.chat_room:
                return
            cnt = int(payload.get("count", 1))
            self._append_chat("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            self._append_chat(f"{payload.get('time','')} {payload.get('user','')} ▶ 🎈별풍선 x{cnt}  {payload.get('message','')}")
            self._append_chat("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            self._balloon_anim(cnt)
            return

    # ---------------- Signals / Prices ----------------
    def job_refresh_signals(self):
        out = {}
        for _, tkr in (DEFAULT_KR + DEFAULT_US):
            out[tkr] = compute_signal_simple(tkr)
        return out

    def _apply_signals(self, sig_map: dict):
        for tree in [getattr(self, "tree_kr", None), getattr(self, "tree_us", None)]:
            if not tree:
                continue
            for iid in tree.get_children():
                name, ticker, _sig = tree.item(iid, "values")
                sig = sig_map.get(ticker, "HOLD")
                tree.item(iid, values=(name, ticker, sig), tags=(sig,))

    def refresh_prices(self):
        self.work_q.put((self.job_refresh_prices, ()))

    def job_refresh_prices(self):
        prices = {}
        holdings = self.user_data.get("holdings", {}) or {}
        for tkr in holdings.keys():
            p = fetch_market_price(tkr)
            if p and p > 0:
                prices[tkr] = float(p)
        return prices

    def _apply_prices(self, prices: dict):
        self._render_portfolio(prices)
        self._render_analysis(prices)

    # ---------------- Renderers ----------------
    def _render_recent_tab(self):
        if not hasattr(self, "recent_list"):
            return
        self.recent_list.delete(0, tk.END)
        for r in self.user_data.get("recent_stocks", [])[:15]:
            self.recent_list.insert(tk.END, f"{r.get('time','')}  {r.get('name','')} ({r.get('ticker','')})")

    def _render_portfolio(self, prices: dict):
        if not hasattr(self, "tree_port"):
            return
        for r in self.tree_port.get_children():
            self.tree_port.delete(r)

        holdings = self.user_data.get("holdings", {}) or {}
        for ticker, h in holdings.items():
            name = h.get("name", ticker)
            qty = float(h.get("qty", 0.0))
            avg = float(h.get("avg_price", 0.0))
            cur = float(prices.get(ticker) or 0.0)
            pnl = (cur - avg) * qty if cur > 0 else 0.0
            rr = ((cur / avg) - 1.0) * 100.0 if (cur > 0 and avg > 0) else 0.0
            self.tree_port.insert("", "end", iid=ticker, values=(
                name, ticker, f"{qty:g}", f"{avg:,.4f}", f"{cur:,.4f}" if cur else "-", f"{pnl:,.2f}", f"{rr:,.2f}"
            ))

    def _set_analysis(self, text: str):
        self.analysis_text.configure(state="normal")
        self.analysis_text.delete("1.0", tk.END)
        self.analysis_text.insert("1.0", text)
        self.analysis_text.configure(state="disabled")

    def _render_analysis(self, prices: dict):
        holdings = self.user_data.get("holdings", {}) or {}
        lines = []
        total_pnl = 0.0
        total_cost = 0.0

        for ticker, h in holdings.items():
            name = h.get("name", ticker)
            qty = float(h.get("qty", 0.0))
            avg = float(h.get("avg_price", 0.0))
            cur = float(prices.get(ticker) or 0.0)

            cost = avg * qty
            pnl = (cur - avg) * qty if cur > 0 else 0.0
            rr = ((cur / avg) - 1.0) * 100.0 if (cur > 0 and avg > 0) else 0.0

            total_pnl += pnl
            total_cost += cost
            lines.append(f"- {name}({ticker}) 수량 {qty:g} | 평단 {avg:,.4f} | 현재 {cur:,.4f} | 손익 {pnl:,.2f} | 수익률 {rr:,.2f}%")

        total_rr = (total_pnl / total_cost * 100.0) if total_cost > 0 else 0.0

        summary = [
            "📊 보유종목 수익분석",
            f"총 평가손익: {total_pnl:,.2f}",
            f"총 수익률: {total_rr:,.2f}%",
            "",
            "상세:"
        ]
        if lines:
            summary.extend(lines)
        else:
            summary.append("- 보유종목 없음")

        self._set_analysis("\n".join(summary))

    def _render_orders(self):
        if not hasattr(self, "tree_orders"):
            return
        for r in self.tree_orders.get_children():
            self.tree_orders.delete(r)
        for o in (self.orders_cache or [])[:200]:
            t = o.get("time", "")
            side = o.get("side", "")
            name = o.get("name", "")
            ticker = o.get("ticker", "")
            qty = float(o.get("qty", 0.0))
            price = float(o.get("price", 0.0))
            cur = o.get("currency", "")
            amount = float(o.get("amount", 0.0))
            self.tree_orders.insert("", "end", values=(t, side, name, ticker, f"{qty:g}", f"{price:,.4f}", cur, f"{amount:,.2f}"))

    def reload_orders(self):
        if self.current_user == "guest":
            messagebox.showinfo("안내", "게스트는 주문내역 저장이 제한됩니다.")
            return
        self.orders_cache = self.repo.list_orders_for_user(self.current_user, limit=200)
        self._render_orders()
        self._refresh_kpis()

    # ---------------- Buying/Selling ----------------
    def open_market_buy_popup(self, name: str, ticker: str, sig: str):
        currency = "KRW" if (ticker.endswith(".KS") or ticker.endswith(".KQ")) else "USD"

        win = tk.Toplevel(self.root)
        win.title("시장가 매수")
        win.geometry("620x620")
        win.configure(bg="white")

        tk.Label(win, text=f"{name} ({ticker})", bg="white", fg="#0064FF",
                 font=("맑은 고딕", 16, "bold")).pack(pady=10)
        tk.Label(win, text=f"신호: {sig}", bg="white", fg="#111111",
                 font=("맑은 고딕", 12, "bold")).pack(pady=2)

        tk.Label(win, text="현재시장가(수정 불가)", bg="white", font=("맑은 고딕", 12, "bold")).pack(pady=(12, 4))
        p = fetch_market_price(ticker) or 0.0
        price_var = tk.StringVar(value=f"{p:.6f}".rstrip("0").rstrip(".") if p else "0")
        tk.Entry(win, textvariable=price_var, state="readonly",
                 readonlybackground="#f3f5f7", fg="#111111",
                 font=("맑은 고딕", 13), width=18).pack()

        def refresh_price():
            newp = fetch_market_price(ticker)
            if newp and newp > 0:
                price_var.set(f"{newp:.6f}".rstrip("0").rstrip("."))
            else:
                messagebox.showwarning("실패", "현재가 불러오기 실패")
        tk.Button(win, text="현재가 새로고침", bg="#0064FF", fg="white",
                  font=("맑은 고딕", 10, "bold"), command=refresh_price).pack(pady=8)

        bal = tk.StringVar(value=f"잔고: KRW {self.user_data['balance_krw']:,.0f} / USD {self.user_data['balance_usd']:,.2f} / CASH {self.user_data['balance_cash']:,.0f}")
        tk.Label(win, textvariable=bal, bg="white", fg="#333333",
                 font=("맑은 고딕", 11, "bold")).pack(pady=8)

        frm = tk.Frame(win, bg="white")
        frm.pack(pady=10)

        tk.Label(frm, text="수량", bg="white", font=("맑은 고딕", 12, "bold")).grid(row=0, column=0, padx=8, pady=6, sticky="e")
        qty_entry = tk.Entry(frm, font=("맑은 고딕", 12), width=18)
        qty_entry.grid(row=0, column=1, padx=8, pady=6, sticky="w")

        def available_money():
            return self.user_data["balance_krw"] if currency == "KRW" else self.user_data["balance_usd"]

        def set_qty_by_pct(pct):
            price = safe_float(price_var.get(), 0.0)
            if price <= 0:
                messagebox.showwarning("오류", "현재가 0")
                return
            money = available_money()
            q = (money * pct) / price
            qty_entry.delete(0, tk.END)
            qty_entry.insert(0, f"{q:.6f}".rstrip("0").rstrip("."))

        btns = tk.Frame(win, bg="white")
        btns.pack(pady=8)
        tk.Button(btns, text="5%", bg="#0064FF", fg="white", font=("맑은 고딕", 11, "bold"),
                  width=8, command=lambda: set_qty_by_pct(0.05)).grid(row=0, column=0, padx=6, pady=6)
        tk.Button(btns, text="10%", bg="#0064FF", fg="white", font=("맑은 고딕", 11, "bold"),
                  width=8, command=lambda: set_qty_by_pct(0.10)).grid(row=0, column=1, padx=6, pady=6)
        tk.Button(btns, text="50%", bg="#0064FF", fg="white", font=("맑은 고딕", 11, "bold"),
                  width=8, command=lambda: set_qty_by_pct(0.50)).grid(row=0, column=2, padx=6, pady=6)
        tk.Button(btns, text="전액", bg="#111111", fg="white", font=("맑은 고딕", 11, "bold"),
                  width=8, command=lambda: set_qty_by_pct(1.00)).grid(row=0, column=3, padx=6, pady=6)

        def do_buy():
            # 현재가 다시 조회 (조작 방지)
            price = fetch_market_price(ticker) or safe_float(price_var.get(), 0.0)
            if price <= 0:
                messagebox.showwarning("오류", "현재가 조회 실패")
                return
            price_var.set(f"{price:.6f}".rstrip("0").rstrip("."))

            qty = safe_float(qty_entry.get(), 0.0)
            if qty <= 0:
                messagebox.showwarning("오류", "수량 입력/선택")
                return

            cost = price * qty
            money = available_money()
            if cost > money + 1e-9:
                messagebox.showwarning("잔고 부족", f"필요: {cost:,.4f}\n보유: {money:,.4f}")
                return

            # 잔고 차감
            if currency == "KRW":
                self.user_data["balance_krw"] -= cost
            else:
                self.user_data["balance_usd"] -= cost

            # 보유 갱신 (평단)
            holdings = self.user_data.get("holdings", {}) or {}
            h = holdings.get(ticker)
            if h:
                old_qty = float(h.get("qty", 0.0))
                old_avg = float(h.get("avg_price", 0.0))
                new_qty = old_qty + qty
                new_avg = ((old_avg * old_qty) + (price * qty)) / (new_qty + 1e-12)
                h["qty"] = new_qty
                h["avg_price"] = new_avg
                holdings[ticker] = h
            else:
                holdings[ticker] = {"name": name, "qty": qty, "avg_price": price, "currency": currency}
            self.user_data["holdings"] = holdings

            # 주문 저장
            order = {
                "user_id": self.current_user,
                "side": "BUY",
                "name": name,
                "ticker": ticker,
                "qty": qty,
                "price": float(price),
                "currency": currency,
                "amount": float(cost),
                "realized_pnl": 0.0,
                "time": now_str(),
                "created_at": firestore.SERVER_TIMESTAMP
            }
            if self.current_user != "guest":
                self.repo.add_order(order)
                self.orders_cache.insert(0, order)
                self.repo.member_update(self.current_user, {
                    "balance_krw": self.user_data["balance_krw"],
                    "balance_usd": self.user_data["balance_usd"],
                    "holdings": self.user_data["holdings"]
                })

            self.refresh_topbar()
            self._render_orders()
            self.refresh_prices()
            messagebox.showinfo("매수 완료", f"{name}\n수량: {qty}\n체결가(시장가): {price:,.4f}")
            win.destroy()

        tk.Button(win, text="시장가 매수 실행", bg="#0064FF", fg="white",
                  font=("맑은 고딕", 13, "bold"), width=18, height=2, command=do_buy).pack(pady=14)
        tk.Button(win, text="닫기", bg="#111111", fg="white",
                  font=("맑은 고딕", 12, "bold"), width=18, command=win.destroy).pack(pady=6)

    def sell_selected(self):
        if self.current_user == "guest":
            messagebox.showwarning("제한", "게스트는 매도 저장이 제한됩니다.")
            return
        sel = self.tree_port.selection()
        if not sel:
            messagebox.showwarning("선택", "매도할 종목 선택")
            return
        ticker = sel[0]
        h = (self.user_data.get("holdings", {}) or {}).get(ticker)
        if not h:
            return
        name = h.get("name", ticker)
        currency = h.get("currency", "KRW")
        max_qty = float(h.get("qty", 0.0))

        qty = safe_float(simpledialog.askstring("매도", f"{name} 매도 수량 (보유 {max_qty:g})"), 0.0)
        if qty <= 0 or qty > max_qty + 1e-9:
            messagebox.showwarning("오류", "수량이 잘못됐습니다.")
            return

        price = fetch_market_price(ticker)
        if not price or price <= 0:
            messagebox.showwarning("오류", "현재가 조회 실패")
            return

        avg = float(h.get("avg_price", 0.0))
        proceeds = price * qty
        realized = (price - avg) * qty

        # 잔고 증가
        if currency == "KRW":
            self.user_data["balance_krw"] += proceeds
        else:
            self.user_data["balance_usd"] += proceeds

        # 보유 감소
        new_qty = max_qty - qty
        if new_qty <= 1e-9:
            self.user_data["holdings"].pop(ticker, None)
        else:
            h["qty"] = new_qty
            self.user_data["holdings"][ticker] = h

        order = {
            "user_id": self.current_user,
            "side": "SELL",
            "name": name,
            "ticker": ticker,
            "qty": qty,
            "price": float(price),
            "currency": currency,
            "amount": float(proceeds),
            "realized_pnl": float(realized),
            "time": now_str(),
            "created_at": firestore.SERVER_TIMESTAMP
        }
        self.repo.add_order(order)
        self.orders_cache.insert(0, order)
        self.repo.member_update(self.current_user, {
            "balance_krw": self.user_data["balance_krw"],
            "balance_usd": self.user_data["balance_usd"],
            "holdings": self.user_data["holdings"]
        })

        self.refresh_topbar()
        self._render_orders()
        self.refresh_prices()
        messagebox.showinfo("매도 완료", f"{name}\n수량: {qty}\n실현손익: {realized:,.2f}")

    # ---------------- Charge popup ----------------
    def open_charge_popup(self):
        if self.current_user == "guest":
            messagebox.showwarning("제한", "게스트는 충전 신청이 제한됩니다(회원 로그인 필요).")
            return

        win = tk.Toplevel(self.root)
        win.title("충전/유료결제 신청")
        win.geometry("760x650")
        win.configure(bg="white")

        tk.Label(win, text="충전하기 / 이용권 결제(입금신청)", bg="white", fg="#0064FF",
                 font=("맑은 고딕", 18, "bold")).pack(pady=10)
        tk.Label(win, text=BOTTOM_ACCOUNT_TEXT, bg="white", fg="#666666",
                 font=("맑은 고딕", 12)).pack(pady=8)

        frm = tk.Frame(win, bg="white")
        frm.pack(fill="x", padx=16, pady=10)

        tk.Label(frm, text="입금자명", bg="white", font=("맑은 고딕", 12, "bold")).grid(row=0, column=0, padx=8, pady=8, sticky="e")
        depositor = tk.Entry(frm, font=("맑은 고딕", 12), width=28)
        depositor.grid(row=0, column=1, padx=8, pady=8, sticky="w")

        tk.Label(frm, text="휴대폰", bg="white", font=("맑은 고딕", 12, "bold")).grid(row=1, column=0, padx=8, pady=8, sticky="e")
        phone = tk.Entry(frm, font=("맑은 고딕", 12), width=28)
        phone.grid(row=1, column=1, padx=8, pady=8, sticky="w")

        memo = tk.Entry(win, font=("맑은 고딕", 11))
        memo.pack(fill="x", padx=16, pady=(0, 10))
        memo.insert(0, "입금 확인 후 처리 바랍니다.")

        def submit_plan(plan_type: str):
            dep = depositor.get().strip()
            ph = phone.get().strip()
            if not dep or not ph:
                messagebox.showwarning("오류", "입금자명/휴대폰 입력")
                return
            if plan_type == "PLAN_1M":
                amt = PLAN_1M_PRICE
                title = f"이용권 1달({amt:,}원)"
            else:
                amt = PLAN_1Y_PRICE
                title = f"이용권 1년({amt:,}원)"
            self.repo.create_payment_request(self.current_user, plan_type, dep, amt, ph, memo.get().strip() + " / " + title)
            messagebox.showinfo("접수", f"{title} 신청 접수 완료.\n관리자 승인 후 반영됩니다.")
            win.destroy()

        def submit_wallet(kind: str):
            dep = depositor.get().strip()
            ph = phone.get().strip()
            if not dep or not ph:
                messagebox.showwarning("오류", "입금자명/휴대폰 입력")
                return
            amt = safe_float(simpledialog.askstring("충전 금액", f"{kind} 충전 금액(숫자):"), 0.0)
            if amt <= 0:
                messagebox.showwarning("오류", "금액 오류")
                return
            self.repo.create_payment_request(self.current_user, kind, dep, amt, ph, memo.get().strip() + f" / {kind} 충전")
            messagebox.showinfo("접수", f"{kind} 충전 신청 접수 완료.\n관리자 승인 후 반영됩니다.")
            win.destroy()

        box = tk.LabelFrame(win, text="이용권(유료결제)", bg="white", font=("맑은 고딕", 12, "bold"))
        box.pack(fill="x", padx=16, pady=12)
        tk.Button(box, text=f"1달 이용권 ({PLAN_1M_PRICE:,}원) 신청", bg="#0064FF", fg="white",
                  font=("맑은 고딕", 13, "bold"), height=2, command=lambda: submit_plan("PLAN_1M")).pack(fill="x", padx=12, pady=8)
        tk.Button(box, text=f"1년 이용권 ({PLAN_1Y_PRICE:,}원) 신청", bg="#111111", fg="white",
                  font=("맑은 고딕", 13, "bold"), height=2, command=lambda: submit_plan("PLAN_1Y")).pack(fill="x", padx=12, pady=8)

        box2 = tk.LabelFrame(win, text="지갑 충전(선택)", bg="white", font=("맑은 고딕", 12, "bold"))
        box2.pack(fill="x", padx=16, pady=12)
        row = tk.Frame(box2, bg="white")
        row.pack(padx=12, pady=10)
        tk.Button(row, text="KRW", bg="#0064FF", fg="white", font=("맑은 고딕", 12, "bold"),
                  command=lambda: submit_wallet("KRW")).pack(side="left", padx=6)
        tk.Button(row, text="USD", bg="#0064FF", fg="white", font=("맑은 고딕", 12, "bold"),
                  command=lambda: submit_wallet("USD")).pack(side="left", padx=6)
        tk.Button(row, text="CASH", bg="#0064FF", fg="white", font=("맑은 고딕", 12, "bold"),
                  command=lambda: submit_wallet("CASH")).pack(side="left", padx=6)

        tk.Button(win, text="닫기", bg="#cccccc", fg="#111111",
                  font=("맑은 고딕", 12, "bold"), command=win.destroy).pack(pady=10)


# =========================
# Run
# =========================
def main():
    root = tk.Tk()
    app = STApp(root)
    root.mainloop()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print("치명적 오류:", e)
        print(traceback.format_exc())
        sys.exit(1)


# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:




