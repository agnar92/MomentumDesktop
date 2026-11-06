"""Eksport danych do tajnego gista GitHub — dla webowej wersji (agnar92/momentum): lista, serie tygodniowe i miesięczne bez czekania na Weekly Refresh.
Pliki gista: `momentum.json` (manifest: wiersze listy, symbole, sektory, daty i mapa paczek) + paczki `weekly_NN.json` / `monthly_NN.json`
(po ≈ 0,9 MB: {ticker: seria}). Manifest wysyłamy OSTATNI, żeby strona nigdy nie widziała manifestu wskazującego brakujące paczki.
Token GitHub (uprawnienie „gist”) trzymamy w settings.json; strona czyta gist po samym ID (tajny gist = adres znany tylko Tobie)."""
import datetime as dt
import json
import urllib.error
import urllib.request

from . import calc

API = "https://api.github.com"
MANIFEST = "momentum.json"
CHUNK_BYTES = 900_000      # rozmiar paczki serii (poniżej 1 MB: API gista nie ucina treści)
BATCH_BYTES = 3_000_000    # jedno żądanie do API nie wysyła więcej niż tyle
PREFIXES = ("weekly_", "monthly_")


class GistError(Exception):
    pass


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def chunk(by_ticker, limit=CHUNK_BYTES):
    """{ticker: seria} -> lista paczek {ticker: seria}, każda ≤ limit bajtów (pojedyncza większa seria dostaje własną paczkę)."""
    out, cur, size = [], {}, 0
    for t, s in by_ticker.items():
        n = len(dump(s)) + len(t) + 6
        if cur and size + n > limit:
            out.append(cur)
            cur, size = {}, 0
        cur[t] = s
        size += n
    if cur:
        out.append(cur)
    return out


def _weekly(series):
    return {k: series[k] for k in ("d", "o", "h", "l", "c", "v")} if series and series.get("d") and series.get("c") else None


def _monthly(entry):
    """Wpis cache `monthly_ohlc` -> zamknięte miesiące {d, o, h, l, c, v} (bieżący miesiąc w toku strona dobuduje z tygodniowych); None przy krótkiej historii."""
    if not entry or not entry.get("d"):
        return None
    n = len(entry["d"]) - (1 if entry.get("open_last") else 0)
    if n < 2:
        return None
    return {"d": [d[:7] + "-01" for d in entry["d"][:n]], **{k: entry[k][:n] for k in ("o", "h", "l", "c", "v")}}


def build_files(store, now=None):
    """Pliki gista z danych desktopa -> ({nazwa: tekst JSON}, opis do okna: {"tickers", "bytes"}); wiersze listy bez zmian — te same obliczenia co w webowej."""
    now = now or dt.datetime.now(dt.timezone.utc)
    scanner = store.settings.get("scanner") or "Skaner"
    rows = [{**r, "scanners": r.get("scanners") or [scanner]} for r in store.rows]
    symbols = [{**row, "scanners": row.get("scanners") or [scanner]} for row, _ in store.extra.values() if row]
    wanted = [r["ticker"] for r in rows + symbols] + ["SPY"]
    weekly = {}
    for t in dict.fromkeys(wanted):
        w = _weekly(store.weekly(t))
        if w:
            weekly[t] = w
    mcache = store.cache("monthly_ohlc") or {}
    monthly = {t: m for t in weekly for m in [_monthly(mcache.get(t))] if m}
    wchunks, mchunks = chunk(weekly), chunk(monthly)
    files, where = {}, {"weekly": {}, "monthly": {}}
    for kind, chunks in (("weekly", wchunks), ("monthly", mchunks)):
        for i, part in enumerate(chunks, 1):
            name = f"{kind}_{i:02d}.json"
            files[name] = dump(part)
            where[kind].update({t: i for t in part})
    last = max((w["d"][-1] for w in weekly.values()), default=None)
    manifest = {"v": 1, "source": "desktop", "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "data_as_of": last,
                "scanners": [{"name": scanner, "filters": "", "total": len(rows), "n": len(rows), "stale": False}], "sectors": store.sectors or [],
                "rules": {"confirm_months": calc.CONFIRM_MONTHS, "entry_max_pct": calc.ENTRY_MAX_PCT, "stop_pct": calc.STOP_PCT},
                "rows": rows, "symbols": symbols, "chunks": where}
    files[MANIFEST] = dump(manifest)
    return files, {"tickers": len(rows), "bytes": sum(len(v.encode("utf-8")) for v in files.values())}


def _request(method, url, token, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "momentum-desktop",
        "X-GitHub-Api-Version": "2022-11-28", **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("message", "")
        except (ValueError, OSError):
            msg = ""
        hint = " — sprawdź token (uprawnienie „gist”) i ID gista" if e.code in (401, 403, 404) else ""
        raise GistError(f"GitHub {e.code}: {msg or e.reason}{hint}") from e
    except urllib.error.URLError as e:
        raise GistError(f"Brak połączenia z GitHub: {e.reason}") from e


def batches(files, limit=None):
    """Pliki w kolejności wysyłki (paczki serii, manifest na końcu) -> lista porcji ≤ limit bajtów (każda ma ≥ 1 plik)."""
    limit = limit or BATCH_BYTES
    order = sorted(n for n in files if n != MANIFEST) + ([MANIFEST] if MANIFEST in files else [])
    out, cur, size = [], {}, 0
    for n in order:
        sz = len(files[n].encode("utf-8"))
        if cur and size + sz > limit:
            out.append(cur)
            cur, size = {}, 0
        cur[n] = files[n]
        size += sz
    if cur:
        out.append(cur)
    return out


def upload(files, token, gist_id=None, request=_request, log=lambda s: None):
    """Wysyła pliki do gista: bez ID tworzy NOWY TAJNY gist, z ID aktualizuje (stare paczki weekly_ / monthly_ są usuwane). -> {"id", "url"}."""
    if not token:
        raise GistError("Brak tokenu GitHub (uprawnienie „gist”).")
    parts = [{n: {"content": c} for n, c in p.items()} for p in batches(files)]
    if gist_id:
        info = request("GET", f"{API}/gists/{gist_id}", token)
        parts[-1].update({n: None for n in (info.get("files") or {}) if n.startswith(PREFIXES) and n not in files})   # stare paczki znikają razem z ostatnią porcją (z manifestem)
        for i, p in enumerate(parts, 1):
            log(f"Gist: wysyłam {i}/{len(parts)}")
            info = request("PATCH", f"{API}/gists/{gist_id}", token, {"files": p})
    else:
        log(f"Gist: tworzę tajny gist (1/{len(parts)})")
        info = request("POST", f"{API}/gists", token, {"description": "Momentum Desktop — dane dla strony webowej", "public": False, "files": parts[0]})
        gist_id = info["id"]
        for i, p in enumerate(parts[1:], 2):
            log(f"Gist: wysyłam {i}/{len(parts)}")
            info = request("PATCH", f"{API}/gists/{gist_id}", token, {"files": p})
    return {"id": gist_id, "url": (info or {}).get("html_url") or f"https://gist.github.com/{gist_id}"}
