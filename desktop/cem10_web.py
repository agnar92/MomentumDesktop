"""CEM10 — nowy interfejs: lokalna strona (desktop/cem10_web/) + mały serwer JSON na 127.0.0.1.
Okno: pywebview (Windows: WebView2 wbudowany w system), a gdy go brak — domyślna przeglądarka. Obliczenia bez zmian: cem10.py (lista) i portfel.py (XTB).
API (nagłówek X-CEM10 = token z adresu strony; inne strony z przeglądarki nie wywołają API):
  GET  /api/state                 wszystko do widoków (lista, portfel, plan, historia, ustawienia, postęp zadania)
  POST /api/settings  {...}       wpłata, udziały docelowe (etf_pct, gpw_share), ETF, konto, tickery trzymane ręcznie -> state
  POST /api/manual {cash, deposited, positions, use}   konto wpisane ręcznie (bez raportu XTB) -> state
  POST /api/manual/deposit {amount}                    wpłata na konto ręczne -> state
  POST /api/adjust {t, kind, op: buy|sell, shares, price, ccy?, amount_pln?}   transakcja dopisana do konta z raportu XTB; /api/adjust/delete {id}
  POST /api/manual/prices                              ceny i kursy walut pozycji ręcznych z Yahoo (w tle)
  POST /api/fetch                 pobranie listy (wątek w tle; postęp w state.task)
  POST /api/curve                 krzywa kapitału z cenami dziennymi Yahoo (wątek w tle)
  POST /api/xtb  (bajty pliku)    raport XTB (zip albo xlsx) -> state
  GET  /api/chart?sym=…           świece miesięczne (10 lat) do wykresu
  POST /api/gpw  {rewizja, WIG20, mWIG40} | {reset: true}   skład GPW
  POST /api/ping                  przeglądarka żyje (bez pywebview program kończy się ~90 s po zamknięciu karty)"""
import copy
import datetime as dt
import json
import re
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
MANUAL = "Ręczne"                                   # etykieta konta wpisanego ręcznie (obok kont z raportu XTB)
KIND = {"usa": ("US", "USD", "STOCK"), "gpw": ("PL", "PLN", "STOCK"), "etf": ("UK", "USD", "ETF")}   # rynek -> (sufiks XTB, waluta, kategoria)
MANUAL_CCY = ("PLN", "USD", "EUR", "GBP")
ADJ = "cem10_adjust"                                 # {etykieta konta XTB: [transakcje dopisane po raporcie]}


def _utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def static_dir():
    """Folder strony: obok modułu albo w paczce PyInstallera (sys._MEIPASS)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "desktop" / "cem10_web"


def _f(x, default=0.0):
    try:
        return float(str(x).replace(",", ".").replace(" ", "").replace(" ", "") or default)
    except (TypeError, ValueError):
        return default


def _norm(kind, t):
    """Ticker wpisany ręcznie -> klucz: USA 'NVDA' (BRK-B), GPW 'ALE' (bez .WA / .PL), ETF jak w XTB, np. 'CSPX.UK'."""
    t = str(t or "").strip().upper().replace(" ", "")
    if kind == "gpw":
        return t.rsplit(".", 1)[0] if t.endswith((".WA", ".PL")) else t
    if kind == "usa":
        return (t[:-3] if t.endswith(".US") else t).replace(".", "-")
    return t


def _xtb_ticker(kind, t):
    if kind == "usa":
        return t.replace("-", ".") + ".US"
    if kind == "gpw":
        return t + ".PL"
    return t if "." in t else t + ".UK"


def last_prices(symbols, download=None):
    """{symbol Yahoo: (ostatnie zamknięcie, data)} z ostatnich dni notowań (yfinance); `download` do podmiany w testach."""
    symbols = sorted(set(symbols))
    if not symbols:
        return {}
    if download is None:
        from .prices import _yf

        def download(syms):
            return _yf().download(syms, period="7d", interval="1d", auto_adjust=False, group_by="ticker", progress=False, threads=True)
    df = download(symbols)
    out = {}
    for sym in symbols:
        try:
            col = (df[sym] if len(symbols) > 1 else df)["Close"]
            col = col.iloc[:, 0] if hasattr(col, "columns") else col
            col = col.dropna()
            if len(col):
                out[sym] = (float(col.iloc[-1]), col.index[-1].strftime("%Y-%m-%d"))
        except Exception:
            continue
    return out


def yahoo_symbol(sym):
    """Symbol wpisany przez użytkownika -> symbol Yahoo: z końcówką XTB (CSPX.UK -> CSPX.L, ALE.PL -> ALE.WA, NVDA.US -> NVDA), BRK.B -> BRK-B; symbole Yahoo bez zmian."""
    s = str(sym or "").strip().upper()
    base, _, suf = s.rpartition(".")
    if not base:
        return s
    if suf in ("A", "B"):   # klasa akcji (BRK.B, BF.B); inne jednoliterowe końcówki to giełdy Yahoo (.L, .T, .V)
        return base + "-" + suf
    return portfel.yahoo(s)


def clean_bars(o, h, lo, c):
    """Świece miesięczne z Yahoo bywają błędne: puste albo zerowe Open / High / Low, Low = 1 przy cenie 300 (na skali log rozciąga cały wykres).
    Puste lub niezgodne z Open / Close wartości zastępujemy zakresem Open-Close, a High > 4 × i Low < 0,25 × korpusu uznajemy za błąd danych."""
    def ok(x):
        return x is not None and x == x and x > 0
    out = ([], [], [], [])
    for oo, hh, ll, cc in zip(o, h, lo, c):
        cc = float(cc)
        oo = float(oo) if ok(oo) else cc
        top, bot = max(oo, cc), min(oo, cc)
        hh = float(hh) if ok(hh) and top <= float(hh) <= 4 * top else top
        ll = float(ll) if ok(ll) and 0.25 * bot <= float(ll) <= bot else bot
        for arr, v in zip(out, (oo, hh, ll, cc)):
            arr.append(round(v, 4))
    return out


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

    def manual_data(self):
        return self.store.cache("cem10_manual") or {}

    def manual_has(self):
        d = self.manual_data()
        return bool(d.get("positions") or _f(d.get("cash")) or _f(d.get("deposited")))

    def manual_price(self, p):
        """Cena pozycji ręcznej (waluta instrumentu): wpisana > z Yahoo > ostatnie zamknięcie miesiąca z listy CEM10 > cena zakupu."""
        if p.get("price"):
            return p["price"], "ręczna" if p.get("fixed") else "Yahoo"
        D = self.data
        if D and p["kind"] in ("usa", "gpw"):
            r = next((r for r in D[p["kind"]]["rows"] if r["t"] == p["t"]), None)
            if r and r.get("c"):
                return r["c"], "lista (zamknięcie miesiąca)"
        return (p.get("open_price") or 0.0), "cena zakupu"

    def manual_account(self):
        """Konto z ręcznie wpisanych pozycji i gotówki w tym samym formacie co konto z raportu XTB (portfel.holdings / plan działają bez zmian)."""
        d = self.manual_data()
        fx = {**portfel.CCY, **(d.get("fx") or {})}
        positions, value = [], 0.0
        for p in d.get("positions") or []:
            suf, ccy0, cat = KIND[p["kind"]]
            ccy = p.get("ccy") or ccy0
            price, _ = self.manual_price(p)
            rate = 1.0 if ccy == "PLN" else fx.get(ccy, portfel.CCY.get(ccy, 1.0))
            val = p["shares"] * price * rate
            op = p.get("open_price") or None
            positions.append({"ticker": _xtb_ticker(p["kind"], p["t"]), "name": p["t"], "category": cat, "volume": p["shares"], "value": val, "open_price": op,
                              "profit": val - p["shares"] * (op or price) * rate, "profit_pct": ((price / op - 1) * 100) if op else None, "price": price, "fx": rate})
            value += val
        return {"file": "", "label": MANUAL, "account": "manual", "generated": (d.get("prices_at") or d.get("updated") or dt.datetime.now().isoformat(timespec="seconds")),
                "open_value": value, "positions": positions, "lots": [], "cash_ops": [], "closed": [], "cash": _f(d.get("cash")), "manual": True,
                "deposited": _f(d.get("deposited"))}

    def manual_view(self):
        """Konto ręczne do edycji na stronie (pozycje w formie wpisanej + źródło ceny)."""
        d = self.manual_data()
        out = []
        for p in d.get("positions") or []:
            price, src = self.manual_price(p)
            out.append({"t": p["t"], "kind": p["kind"], "shares": p["shares"], "open_price": p.get("open_price"), "ccy": p.get("ccy") or KIND[p["kind"]][1],
                        "price": price, "price_src": src, "price_date": p.get("price_date"), "fixed": bool(p.get("fixed"))})
        return {"has": self.manual_has(), "cash": _f(d.get("cash")), "deposited": _f(d.get("deposited")), "updated": d.get("updated"), "prices_at": d.get("prices_at"),
                "fx": {**{k: v for k, v in portfel.CCY.items() if k in MANUAL_CCY}, **(d.get("fx") or {})}, "positions": out}

    def adjustments(self, label):
        return list((self.store.cache(ADJ) or {}).get(label) or [])

    def apply_adjustments(self, acc):
        """Zakupy i sprzedaże dopisane ręcznie po dacie raportu XTB (raport ich jeszcze nie zawiera): liczba akcji, średnia cena zakupu, wartość i gotówka."""
        adj = [] if acc.get("manual") else self.adjustments(acc.get("label"))
        if not adj:
            return acc
        acc = copy.deepcopy(acc)
        fx = {**portfel.CCY, **(self.manual_data().get("fx") or {})}
        live = self.store.cache("cem10_live") or {}
        pos = {p["ticker"]: p for p in acc["positions"]}
        for a in sorted(adj, key=lambda x: x["ts"]):
            kind = a["kind"]
            xt, ccy = _xtb_ticker(kind, a["t"]), a.get("ccy") or KIND[kind][1]
            rate = 1.0 if ccy == "PLN" else fx.get(ccy, portfel.CCY.get(ccy, 1.0))
            sh, pr = a["shares"], a["price"]
            money = a.get("amount_pln") or sh * pr * rate
            p = pos.get(xt)
            if a["op"] == "buy":
                if p is None:
                    p = {"ticker": xt, "name": a["t"], "category": KIND[kind][2], "volume": 0.0, "value": 0.0, "open_price": None, "profit": None, "profit_pct": None,
                         "price": (live.get(portfel.yahoo(xt)) or {}).get("p") or pr, "fx": rate}
                    pos[xt] = p
                    acc["positions"].append(p)
                v0 = p["volume"]
                p["open_price"] = ((p.get("open_price") or pr) * v0 + pr * sh) / (v0 + sh)
                p["volume"] = v0 + sh
                acc["cash"] = max(acc["cash"] - money, 0.0)
            elif p is not None:
                p["volume"] = max(p["volume"] - sh, 0.0)
                acc["cash"] += money
            if p is not None:
                p["adjusted"] = True
        keep = []
        for p in acc["positions"]:
            if p["volume"] <= 1e-9:
                continue
            lp = live.get(portfel.yahoo(p["ticker"]))
            if p.get("adjusted") and lp:
                p["price"] = lp["p"]
            rate, price = p.get("fx") or 1.0, p.get("price") or p.get("open_price") or 0.0
            p["value"] = p["volume"] * price * rate
            if p.get("open_price"):
                p["profit_pct"], p["profit"] = (price / p["open_price"] - 1) * 100, p["value"] - p["volume"] * p["open_price"] * rate
            keep.append(p)
        acc["positions"], acc["open_value"] = keep, sum(p["value"] for p in keep)
        return acc

    def accounts(self):
        accs = [self.apply_adjustments(a) for a in (self.store.cache("xtb").get("accounts") or [])]
        if self.manual_has():
            accs.append(self.manual_account())
        return accs

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
        dep = acc["deposited"] if acc.get("manual") else sum(x for _, x in portfel.flows(acc))
        for h in hold:
            h["yahoo"] = portfel.yahoo(h["ticker"])
            h["stop_hit"] = h.get("stop_dist") is not None and h["stop_dist"] <= 0
            if h["stop_hit"]:
                h["status"] = "SPRZEDAJ (stop −40 %)"
        return {"label": acc.get("label"), "generated": acc.get("generated"), "total": total, "positions_value": acc["open_value"], "cash": acc["cash"],
                "deposited": dep, "profit": total - dep, "profit_pct": (total - dep) / dep if dep else None,
                "buckets": buckets, "rows": hold, "accounts": [a.get("label") or "?" for a in self.accounts()], "manual": bool(acc.get("manual"))}

    def targets(self, pf):
        """Udziały docelowe; przy pierwszym raporcie = obecne udziały koszyków zaokrąglone do 5 %."""
        tg = self.store.settings.get("cem10_targets") or {}
        if any(_f(v) for v in tg.values()):
            return {b: _f(tg.get(b)) for b in ("usa", "gpw", "etf")}
        base = {b: (pf or {}).get("buckets", {}).get(b, 0.0) for b in ("usa", "gpw", "etf")}
        s = sum(base.values())
        if not s:
            return {"usa": 47.0, "gpw": 23.0, "etf": 30.0}   # bez danych: baza ETF 30 %, reszta CEM10 w proporcji miejsc 10 : 5
        e = float(round(base["etf"] / s * 20) * 5)                                  # pierwsze wczytanie: baza ETF zaokrąglona do 5 %, reszta CEM10 w proporcji USA : GPW
        g = round(base["gpw"] / (base["usa"] + base["gpw"]) * 20) / 20 if base["usa"] + base["gpw"] else 1 / 3
        return {"etf": e, "usa": round((100 - e) * (1 - g), 2), "gpw": round((100 - e) * g, 2)}

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
            a["yahoo"] = portfel.yahoo(st.get("cem10_etf", "CSPX.UK")) if a["koszyk"] == "etf" else a["ticker"] + ".WA" if a["koszyk"] == "gpw" else a["ticker"]   # ETF: CSPX.UK -> CSPX.L
        return {"actions": actions, "summary": s, "targets": tg, "usd": usd}

    def history(self):
        acc = self.account()
        if not acc or acc.get("manual"):
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
        tg = self.targets(pf)
        tot, cem = sum(tg.values()) or 1.0, tg["usa"] + tg["gpw"]
        shares = {"targets": tg, "etf_pct": round(tg["etf"] / tot * 100, 1),
                  "gpw_share": round(tg["gpw"] / cem * 100, 1) if cem else round(portfel.SLOTS["gpw"] / (portfel.SLOTS["usa"] + portfel.SLOTS["gpw"]) * 100, 1)}
        return {"lists": self.lists(), "portfolio": pf, "plan": self.plan(pf) if pf else None, "history": self.history(), "manual": self.manual(),
                "manual_acct": self.manual_view(), "adjust": self.adjustments((self.account() or {}).get("label")), "settings": self.settings() | shares, "task": task, "data_dir": str(getattr(self.store, "dir", "")),
                "gpw": {"rewizja": g.get("rewizja"), "WIG20": g["WIG20"], "mWIG40": g["mWIG40"], "custom": bool(self.store.cache("cem10_gpw"))},
                "rules": {"stop": portfel.STOP, "min_topup": portfel.MIN_TOPUP, "slots": portfel.SLOTS}}

    # ------------------------------------------------------------ akcje
    def save_settings(self, body):
        st = self.store.settings
        if "deposit" in body:
            st["cem10_deposit"] = max(_f(body["deposit"]), 0.0)
        if "targets" in body:
            st["cem10_targets"] = {b: max(_f(body["targets"].get(b)), 0.0) for b in ("usa", "gpw", "etf")}
        if "etf_pct" in body or "gpw_share" in body:   # baza ETF S&P 500 w % całości; reszta = CEM10, z czego gpw_share % to GPW
            cur = self.state()["settings"]
            e = min(max(_f(body.get("etf_pct"), cur["etf_pct"]) if "etf_pct" in body else cur["etf_pct"], 0.0), 100.0)
            g = min(max(_f(body.get("gpw_share"), cur["gpw_share"]) if "gpw_share" in body else cur["gpw_share"], 0.0), 100.0)
            st["cem10_targets"] = {"etf": round(e, 2), "usa": round((100 - e) * (1 - g / 100), 2), "gpw": round((100 - e) * g / 100, 2)}
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

    def save_manual(self, body):
        """Konto ręczne: gotówka, wpłacono netto i pozycje [{t, kind: usa|gpw|etf, shares, open_price, ccy, price?}]. Duplikaty scalane średnią ważoną."""
        old = self.manual_data()
        oldp = {(p.get("kind"), p.get("t")): p for p in old.get("positions") or []}
        merged = {}
        for p in body.get("positions") or []:
            kind = p.get("kind") if p.get("kind") in KIND else "usa"
            t, shares = _norm(kind, p.get("t")), _f(p.get("shares"))
            if not t or shares <= 0:
                continue
            op = max(_f(p.get("open_price")), 0.0)
            key = (kind, t)
            if key in merged:
                m = merged[key]
                tot = m["shares"] + shares
                m["open_price"] = (m["open_price"] * m["shares"] + op * shares) / tot
                m["shares"] = tot
                continue
            item = {"t": t, "kind": kind, "shares": shares, "open_price": op, "ccy": p.get("ccy") if p.get("ccy") in MANUAL_CCY else KIND[kind][1]}
            typed, prev = _f(p.get("price")), oldp.get(key) or {}
            if typed > 0:
                item.update(price=typed, fixed=True)
            elif prev.get("price") and not prev.get("fixed"):
                item.update(price=prev["price"], price_date=prev.get("price_date"))
            merged[key] = item
        data = {**old, "cash": max(_f(body.get("cash")), 0.0), "deposited": max(_f(body.get("deposited")), 0.0), "positions": list(merged.values()),
                "updated": dt.datetime.now().isoformat(timespec="seconds")}
        self.store.save_cache("cem10_manual", data)
        if (body.get("use") or not self.store.cache("xtb").get("accounts")) and self.manual_has():
            return self.save_settings({"account": MANUAL})
        return self.state()

    def add_adjust(self, body):
        """Zakup / sprzedaż dopisana ręcznie do konta z raportu XTB (np. dzisiejsza transakcja, której raport jeszcze nie ma)."""
        acc = self.account()
        if not acc or acc.get("manual"):
            raise ValueError("Transakcję dopisujesz do konta z raportu XTB. Na koncie ręcznym edytujesz tabelę pozycji.")
        kind = body.get("kind") if body.get("kind") in KIND else "usa"
        t, sh, pr = _norm(kind, body.get("t")), _f(body.get("shares")), _f(body.get("price"))
        if not t or sh <= 0 or pr <= 0 or body.get("op") not in ("buy", "sell"):
            raise ValueError("Podaj ticker, liczbę akcji i cenę transakcji.")
        entry = {"id": secrets.token_hex(4), "t": t, "kind": kind, "op": body["op"], "shares": sh, "price": pr,
                 "ccy": body.get("ccy") if body.get("ccy") in MANUAL_CCY else None, "amount_pln": _f(body.get("amount_pln")) or None, "ts": _utcnow()}
        d = self.store.cache(ADJ) or {}
        d.setdefault(acc["label"], []).append(entry)
        self.store.save_cache(ADJ, d)
        return self.state()

    def del_adjust(self, aid):
        d = {lab: [a for a in lst if a.get("id") != aid] for lab, lst in (self.store.cache(ADJ) or {}).items()}
        self.store.save_cache(ADJ, d)
        return self.state()

    def add_deposit(self, amount):
        """Wpłata na konto ręczne: dopisuje do gotówki i do „wpłacono netto” (ujemna = wypłata, nie schodzi poniżej zera)."""
        d = self.manual_data()
        a = _f(amount)
        d["cash"] = max(_f(d.get("cash")) + a, 0.0)
        d["deposited"] = max(_f(d.get("deposited")) + a, 0.0)
        d["updated"] = dt.datetime.now().isoformat(timespec="seconds")
        self.store.save_cache("cem10_manual", d)
        if self.manual_has() and not self.store.cache("xtb").get("accounts"):
            return self.save_settings({"account": MANUAL})
        return self.state()

    def start_prices(self, download=None):
        """Ceny w tle: pozycje konta ręcznego i spółki dopisane do konta XTB (ostatnie zamknięcia z Yahoo) + kursy walut. Ceny wpisane ręcznie zostają."""
        def adjusted():
            return [a for lst in (self.store.cache(ADJ) or {}).values() for a in lst]
        if not self.manual_data().get("positions") and not adjusted():
            return False

        def work(log, progress):
            d, adj = self.manual_data(), adjusted()
            want = {portfel.yahoo(_xtb_ticker(p["kind"], p["t"])): p for p in d.get("positions") or []}
            extra = {portfel.yahoo(_xtb_ticker(a["kind"], a["t"])): a for a in adj}
            ccys = {p.get("ccy") or KIND[p["kind"]][1] for p in list(want.values()) + list(extra.values())} - {"PLN"}
            fxs = {c: f"{c}PLN=X" for c in sorted(ccys)}
            log(f"Ceny z Yahoo: {len(want) + len(extra)} instrumentów")
            got = last_prices(list(want) + list(extra) + list(fxs.values()), download)
            for sym, p in want.items():
                if sym in got and not p.get("fixed"):
                    p["price"], p["price_date"] = got[sym]
            self.store.save_cache("cem10_live", {sym: {"p": got[sym][0], "d": got[sym][1]} for sym in extra if sym in got})
            d["fx"] = {**(d.get("fx") or {}), **{c: got[sym][0] for c, sym in fxs.items() if sym in got}}
            d["prices_at"] = dt.datetime.now().isoformat(timespec="seconds")
            self.store.save_cache("cem10_manual", d)
            miss = [s_ for s_ in list(want) + list(extra) if s_ not in got and not (want.get(s_) or {}).get("fixed")]
            return "Ceny odświeżone" + (f" (bez notowań: {', '.join(miss)})" if miss else "")
        return self._run("prices", work)

    def import_xtb(self, blob, name=""):
        accs = portfel.load_report(blob, name)
        self.store.save_cache("xtb", {"accounts": accs})
        adj = self.store.cache(ADJ) or {}
        for a in accs:   # nowy raport już zawiera transakcje sprzed swojej daty — nie liczymy ich drugi raz
            adj[a.get("label")] = [x for x in adj.get(a.get("label")) or [] if x["ts"] > (a.get("generated") or "")]
        self.store.save_cache(ADJ, adj)
        return self.save_settings({"account": accs[0].get("label") or ""}) | {"message": f"Wczytano raport XTB: {', '.join(a.get('label') or '?' for a in accs)}"}

    def save_gpw(self, body):
        """Skład GPW: same tickery (lista, tekst po spacji / przecinku / w wierszach albo słownik ticker -> nazwa). Nazwy znanych spółek zostają z poprzedniego składu."""
        if body.get("reset"):
            self.store.save_cache("cem10_gpw", {})
            return self.state()
        known = {}
        for k in ("WIG20", "mWIG40"):
            known.update(self.gpw_members().get(k) or {})

        def norm(t):
            t = str(t).strip().upper()
            return t.rsplit(".", 1)[0] if t.endswith((".WA", ".PL")) else t

        def clean(x):
            names = {norm(k): str(v or "").strip() for k, v in x.items()} if isinstance(x, dict) else {}
            raw = list(x) if isinstance(x, (dict, list, tuple)) else re.split(r"[\s,;]+", str(x or ""))
            out = {}
            for t in map(norm, raw):
                if re.fullmatch(r"[A-Z0-9]{2,5}", t) and t not in out:
                    out[t] = names.get(t) or known.get(t) or t
            return out
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
        if not acc or acc.get("manual"):
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
        want = yahoo_symbol(sym)
        df = None
        for cand in [want] + ([want + ".WA"] if "." not in want and "-" not in want else []):   # sam ticker bez rynku: najpierw USA, potem GPW
            df = _yf().download(cand, period="10y", interval="1mo", auto_adjust=False, progress=False)
            if hasattr(df.columns, "levels"):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=["Close"])
            if not df.empty:
                sym = cand
                break
        if df is None or df.empty:
            raise ValueError(f"brak notowań {want}")
        o, h, lo, c = clean_bars(df["Open"], df["High"], df["Low"], df["Close"])
        return {"sym": sym, "d": [x.strftime("%Y-%m") for x in df.index], "o": o, "h": h, "l": lo, "c": c, "v": [round(float(v), 0) if v == v else 0.0 for v in df["Volume"]]}


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
                    if name == "manual":
                        return self._send(200, api.save_manual(body))
                    if name == "adjust":
                        return self._send(200, api.add_adjust(body))
                    if name == "adjust/delete":
                        return self._send(200, api.del_adjust(body.get("id")))
                    if name == "manual/deposit":
                        return self._send(200, api.add_deposit(body.get("amount")))
                    if name == "manual/prices":
                        return self._send(200, {"started": api.start_prices()})
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
