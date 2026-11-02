"""CEM10 — nowy interfejs: lokalna strona (desktop/cem10_web/) + mały serwer JSON na 127.0.0.1.
Okno: pywebview (Windows: WebView2 wbudowany w system), a gdy go brak — domyślna przeglądarka. Obliczenia bez zmian: cem10.py (lista) i portfel.py (XTB).
API (nagłówek X-CEM10 = token z adresu strony; inne strony z przeglądarki nie wywołają API):
  GET  /api/state                 wszystko do widoków (lista, portfel, plan, historia, ustawienia, postęp zadania)
  POST /api/settings  {...}       wpłata, udziały docelowe, ETF, konto, tickery trzymane ręcznie -> state
  POST /api/fetch                 pobranie listy (wątek w tle; postęp w state.task)
  POST /api/curve                 krzywa kapitału z cenami dziennymi Yahoo (wątek w tle)
  POST /api/xtb  (bajty pliku)    raport XTB (zip albo xlsx) -> state
  GET  /api/chart?sym=…           świece miesięczne (10 lat) do wykresu
  POST /api/gpw  {rewizja, WIG20, mWIG40} | {reset: true}   skład GPW
  POST /api/ping                  przeglądarka żyje (bez pywebview program kończy się ~90 s po zamknięciu karty)"""
import json
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import cem10, portfel

TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
BUCKET = {"usa": "CEM10 USA", "gpw": "CEM10 GPW", "etf": "ETF", "inne": "Inne"}


def static_dir():
    """Folder strony: obok modułu albo w paczce PyInstallera (sys._MEIPASS)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "desktop" / "cem10_web"


def _f(x, default=0.0):
    try:
        return float(str(x).replace(",", ".").replace(" ", "").replace(" ", "") or default)
    except (TypeError, ValueError):
        return default


class Api:
    """Stan programu CEM10 nad magazynem danych (store: settings, cache, save_cache, save_settings)."""

    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.task = {"busy": False, "kind": None, "log": "", "progress": 0.0, "error": None, "done": None}
        self.last_ping = time.time()

    # ------------------------------------------------------------ dane
    @property
    def data(self):
        return self.store.cache("cem10") or None

    def accounts(self):
        return self.store.cache("xtb").get("accounts") or []

    def account(self):
        accs = self.accounts()
        lab = self.store.settings.get("xtb_account", "")
        return next((a for a in accs if a.get("label") == lab), accs[0] if accs else None)

    def gpw_members(self):
        return self.store.cache("cem10_gpw") or cem10.GPW_DEFAULT

    def settings(self):
        st = self.store.settings
        return {"deposit": st.get("cem10_deposit", 500), "targets": st.get("cem10_targets") or {}, "etf": st.get("cem10_etf", "CSPX.UK"),
                "hold": st.get("cem10_hold", ""), "account": (self.account() or {}).get("label", ""), "theme": st.get("cem10_theme", "auto")}

    # ------------------------------------------------------------ widoki
    def lists(self):
        D = self.data
        if not D:
            return None
        U, G = D["usa"], D["gpw"]
        uc, gc = cem10.usa_candidates(U["rows"], U["lead"]), cem10.gpw_candidates(G["rows"])
        return {"month": D["month"], "generated_at": D.get("generated_at"),
                "usa": {k: U.get(k) for k in ("lead", "spy5", "qqq5", "spy", "spy_sma12", "bear", "n", "prefilter", "missing")} | {"rows": uc, "count": len(U["rows"])},
                "gpw": {k: G.get(k) for k in ("lv", "lv12", "bear", "n", "rewizja", "w20_6", "w40_6", "missing")} | {"rows": gc, "count": len(G["rows"])}}

    def portfolio(self):
        acc = self.account()
        if not acc:
            return None
        hold, buckets, total = portfel.holdings(acc, self.data)
        dep = sum(x for _, x in portfel.flows(acc))
        for h in hold:
            h["yahoo"] = portfel.yahoo(h["ticker"])
            h["stop_hit"] = h.get("stop_dist") is not None and h["stop_dist"] <= 0
            if h["stop_hit"]:
                h["status"] = "SPRZEDAJ (stop −40 %)"
        return {"label": acc.get("label"), "generated": acc.get("generated"), "total": total, "positions_value": acc["open_value"], "cash": acc["cash"],
                "deposited": dep, "profit": total - dep, "profit_pct": (total - dep) / dep if dep else None,
                "buckets": buckets, "rows": hold, "accounts": [a.get("label") or "?" for a in self.accounts()]}

    def targets(self, pf):
        """Udziały docelowe; przy pierwszym raporcie = obecne udziały koszyków zaokrąglone do 5 %."""
        tg = self.store.settings.get("cem10_targets") or {}
        if any(_f(v) for v in tg.values()):
            return {b: _f(tg.get(b)) for b in ("usa", "gpw", "etf")}
        base = {b: (pf or {}).get("buckets", {}).get(b, 0.0) for b in ("usa", "gpw", "etf")}
        s = sum(base.values())
        if not s:
            return {"usa": 50.0, "gpw": 50.0, "etf": 0.0}
        return {b: float(round(v / s * 20) * 5) for b, v in base.items()}

    def plan(self, pf):
        acc = self.account()
        if not acc or not self.data:
            return None
        st = self.store.settings
        tg = self.targets(pf)
        actions, s = portfel.plan(acc, self.data, deposit=max(_f(st.get("cem10_deposit", 500)), 0.0), targets=tg, etf_ticker=st.get("cem10_etf", "CSPX.UK"))
        D = self.data
        rows = {("usa", r["t"]): r for r in D["usa"]["rows"]} | {("gpw", r["t"]): r for r in D["gpw"]["rows"]}
        usd = next((h["fx"] for h in pf["rows"] if h.get("ccy") == "USD" and h.get("fx")), 3.8)
        names = {h["t"]: h["name"] for h in pf["rows"]}
        for a in actions:
            r = rows.get((a["koszyk"], a["ticker"]))
            a["name"] = (r or {}).get("n") or names.get(a["ticker"], "")
            a["price"] = (r or {}).get("c")
            a["ccy"] = "USD" if a["koszyk"] == "usa" else "PLN"
            k = usd if a["koszyk"] == "usa" else 1.0
            a["shares"] = (a["kwota"] / (a["price"] * k)) if a["price"] and a["akcja"] != "SPRZEDAJ" else None
            a["yahoo"] = a["ticker"] + ".WA" if a["koszyk"] == "gpw" else a["ticker"]
        return {"actions": actions, "summary": s, "targets": tg, "usd": usd}

    def history(self):
        acc = self.account()
        if not acc:
            return None
        c = self.store.cache("xtb_curve")
        exact = c.get("label") == acc.get("label") and c.get("generated") == acc.get("generated")
        pts = (c.get("points") or []) if exact else portfel.curve(acc)
        step = max(len(pts) // 700, 1)   # do wykresu wystarczy ~700 punktów
        pts = pts[::step] + ([pts[-1]] if pts and (len(pts) - 1) % step else [])
        ev = [{"d": d, "kind": "wpłata" if x > 0 else "wypłata", "t": "", "amount": x, "pct": None} for d, x in portfel.flows(acc)]
        ev += [{"d": d, "kind": "sprzedaż", "t": t, "amount": p, "pct": r} for d, t, p, r in portfel.exits(acc)]
        return {"exact": exact, "points": pts, "events": sorted(ev, key=lambda e: e["d"], reverse=True)}

    def manual(self):
        """Tickery wpisane ręcznie (bez raportu XTB) -> decyzja wg SMA 10."""
        D = self.data or {"usa": {"rows": []}, "gpw": {"rows": []}}
        us, gp = {r["t"]: r for r in D["usa"]["rows"]}, {r["t"]: r for r in D["gpw"]["rows"]}
        out, seen = [], set()
        for t in cem10.parse_tickers(self.store.settings.get("cem10_hold", "")):
            if t.endswith(".WA"):
                t = t[:-3]
                r, m = gp.get(t), "GPW"
            else:
                r, m = us.get(t) or us.get(t.replace(".", "-")), "USA"
                if r is None and t in gp:
                    r, m = gp[t], "GPW"
            key = (m, t)
            if key in seen:
                continue
            seen.add(key)
            note = ""
            if r is None:
                note = ("jest w indeksie, ale nie było jej w pobranych danych — pobierz listę jeszcze raz" if m == "USA" and t in (D["usa"].get("all") or [])
                        else "nie ma w S&P 500, Nasdaq-100, WIG20 ani mWIG40 — w USA oznacza to sprzedaż")
            out.append({"t": t, "market": m, "row": r, "decision": cem10.decide(r), "note": note, "yahoo": t + ".WA" if m == "GPW" else t})
        return out

    def state(self):
        pf = self.portfolio()
        g = self.gpw_members()
        with self.lock:
            task = dict(self.task)
        return {"lists": self.lists(), "portfolio": pf, "plan": self.plan(pf) if pf else None, "history": self.history(), "manual": self.manual(),
                "settings": self.settings() | {"targets": self.targets(pf)}, "task": task, "data_dir": str(getattr(self.store, "dir", "")),
                "gpw": {"rewizja": g.get("rewizja"), "WIG20": g["WIG20"], "mWIG40": g["mWIG40"], "custom": bool(self.store.cache("cem10_gpw"))},
                "rules": {"stop": portfel.STOP, "min_topup": portfel.MIN_TOPUP, "slots": portfel.SLOTS}}

    # ------------------------------------------------------------ akcje
    def save_settings(self, body):
        st = self.store.settings
        if "deposit" in body:
            st["cem10_deposit"] = max(_f(body["deposit"]), 0.0)
        if "targets" in body:
            st["cem10_targets"] = {b: max(_f(body["targets"].get(b)), 0.0) for b in ("usa", "gpw", "etf")}
        if "etf" in body:
            st["cem10_etf"] = str(body["etf"]).strip().upper() or "CSPX.UK"
        if "hold" in body:
            st["cem10_hold"] = str(body["hold"])
        if "theme" in body:
            st["cem10_theme"] = body["theme"] if body["theme"] in ("auto", "light", "dark") else "auto"
        if "account" in body:
            st["xtb_account"] = str(body["account"])
            acc = self.account()
            if acc:   # trzymane spółki CEM10 z raportu -> sito pobierania listy
                hold, _, _ = portfel.holdings(acc, self.data)
                st["cem10_hold"] = ", ".join(h["t"] + (".WA" if h["bucket"] == "gpw" else "") for h in hold if h["bucket"] in ("usa", "gpw"))
        self.store.save_settings()
        return self.state()

    def import_xtb(self, blob, name=""):
        accs = portfel.load_report(blob, name)
        self.store.save_cache("xtb", {"accounts": accs})
        return self.save_settings({"account": accs[0].get("label") or ""}) | {"message": f"Wczytano raport XTB: {', '.join(a.get('label') or '?' for a in accs)}"}

    def save_gpw(self, body):
        if body.get("reset"):
            self.store.save_cache("cem10_gpw", {})
        else:
            def clean(d):
                return {str(k).upper().replace(".WA", "").strip(): str(v).strip() or str(k).upper() for k, v in (d or {}).items() if str(k).strip()}
            self.store.save_cache("cem10_gpw", {"rewizja": str(body.get("rewizja") or "").strip(), "WIG20": clean(body.get("WIG20")), "mWIG40": clean(body.get("mWIG40"))})
        return self.state()

    def _run(self, kind, work):
        with self.lock:
            if self.task["busy"]:
                return False
            self.task = {"busy": True, "kind": kind, "log": "Start…", "progress": 0.0, "error": None, "done": None}

        def log(m):
            with self.lock:
                self.task["log"] = str(m)

        def progress(f):
            with self.lock:
                self.task["progress"] = float(f)

        def go():
            try:
                msg = work(log, progress)
                with self.lock:
                    self.task.update(busy=False, progress=1.0, done=msg, log=msg)
            except Exception as exc:
                with self.lock:
                    self.task.update(busy=False, error=str(exc), log=f"Błąd: {exc}")
        threading.Thread(target=go, daemon=True).start()
        return True

    def start_fetch(self, fetch=None):
        fetch = fetch or cem10.fetch
        gpw, old, held = self.gpw_members(), self.data, cem10.parse_tickers(self.store.settings.get("cem10_hold", ""))

        def work(log, progress):
            d = fetch(gpw, old, log=log, progress=progress, held=held)
            self.store.save_cache("cem10", d)
            return f"Lista za {d['month']} gotowa"
        return self._run("fetch", work)

    def start_curve(self, prices=None):
        acc = self.account()
        if not acc:
            return False
        prices = prices or portfel.curve_prices

        def work(log, progress):
            px, fxs = prices(acc, log=log)
            self.store.save_cache("xtb_curve", {"generated": acc.get("generated"), "label": acc.get("label"), "points": portfel.curve(acc, px, fxs)})
            return "Krzywa kapitału przeliczona cenami dziennymi"
        return self._run("curve", work)

    @staticmethod
    def chart(sym):
        from .prices import _yf
        df = _yf().download(sym, period="10y", interval="1mo", auto_adjust=False, progress=False)
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        if df.empty:
            raise ValueError(f"brak notowań {sym}")
        return {"sym": sym, "d": [x.strftime("%Y-%m") for x in df.index],
                **{k: [round(float(v), 4) for v in df[c].fillna(0)] for k, c in (("o", "Open"), ("h", "High"), ("l", "Low"), ("c", "Close"), ("v", "Volume"))}}


# ---------------------------------------------------------------- serwer
def make_server(api, port=0, token=None, root=None):
    """Serwer HTTP na 127.0.0.1 (port 0 = wolny). -> (serwer, adres strony z tokenem)."""
    token = token or secrets.token_urlsafe(16)
    root = Path(root or static_dir())

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _api(self, method):
            if self.headers.get("X-CEM10") != token:
                return self._send(403, {"error": "brak dostępu"})
            u = urlparse(self.path)
            name = u.path[5:]
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                if method == "GET" and name == "state":
                    return self._send(200, api.state())
                if method == "GET" and name == "chart":
                    return self._send(200, api.chart(parse_qs(u.query).get("sym", [""])[0]))
                if method == "POST":
                    api.last_ping = time.time()
                    if name == "ping":
                        return self._send(200, {"ok": True})
                    if name == "xtb":
                        from urllib.parse import unquote
                        return self._send(200, api.import_xtb(raw, unquote(self.headers.get("X-Name") or "")))
                    body = json.loads(raw or b"{}")
                    if name == "settings":
                        return self._send(200, api.save_settings(body))
                    if name == "gpw":
                        return self._send(200, api.save_gpw(body))
                    if name == "fetch":
                        return self._send(200, {"started": api.start_fetch()})
                    if name == "curve":
                        return self._send(200, {"started": api.start_curve()})
                return self._send(404, {"error": "nie ma takiej akcji"})
            except Exception as exc:
                return self._send(400, {"error": str(exc)})

        def do_GET(self):
            if self.path.startswith("/api/"):
                return self._api("GET")
            p = urlparse(self.path).path.lstrip("/") or "index.html"
            f = (root / p).resolve()
            if root.resolve() not in f.parents or not f.is_file():
                return self._send(404, b"404", "text/plain")
            self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))

        def do_POST(self):
            if self.path.startswith("/api/"):
                return self._api("POST")
            self._send(404, b"404", "text/plain")

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.daemon_threads = True
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/index.html#t={token}"


def serve_in_background(api):
    """Serwer w wątku (np. z Momentum Desktop, gdzie główny wątek ma Tk) -> adres strony."""
    srv, url = make_server(api)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return url


def run(store, window=True):
    """Osobny program: serwer + okno pywebview; bez pywebview — przeglądarka, koniec po ~90 s bez pingu strony."""
    api = Api(store)
    srv, url = make_server(api)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if window:
        try:
            import webview
            webview.create_window("CEM10", url, width=1380, height=900, min_size=(380, 560))
            webview.start()
            return
        except Exception:
            pass
    import webbrowser
    webbrowser.open(url)
    api.last_ping = time.time()
    while time.time() - api.last_ping < 90:
        time.sleep(2)
