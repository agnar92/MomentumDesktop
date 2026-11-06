import json

import pytest

from desktop import gist
from desktop.store import Store


def _series(n=30, base=100.0):
    d = [f"2026-{1 + i // 4:02d}-{1 + (i % 4) * 7:02d}" for i in range(n)]
    c = [base + i for i in range(n)]
    return {"d": d, "o": c, "h": [x + 1 for x in c], "l": [x - 1 for x in c], "c": c, "v": [1e6] * n, "raw": 1}


@pytest.fixture
def store(tmp_path):
    st = Store(tmp_path)
    rows = [{"ticker": t, "company": t + " Inc", "glb": 120, "price": 130, "ok": True} for t in ("AAA", "BBB")]
    st.save_scan(rows, {"AAA": _series(), "BBB": _series(base=50.0), "SPY": _series(base=400.0)}, "2026-10-20T08:00")
    st.save_cache("monthly_ohlc", {"AAA": {"d": ["2026-07-01", "2026-08-01", "2026-09-01", "2026-10-01"], "o": [1, 2, 3, 4], "h": [2, 3, 4, 5], "l": [0, 1, 2, 3],
                                           "c": [1.5, 2.5, 3.5, 4.5], "v": [10, 20, 30, 40], "period": "M", "open_last": True}})
    return st


def test_build_files_manifest_chunks_and_closed_months(store):
    files, info = gist.build_files(store)
    man = json.loads(files[gist.MANIFEST])
    assert man["v"] == 1 and man["source"] == "desktop" and man["data_as_of"] == _series()["d"][-1] and info["tickers"] == 2
    assert [r["ticker"] for r in man["rows"]] == ["AAA", "BBB"] and man["rows"][0]["scanners"] and man["chunks"]["weekly"].keys() == {"AAA", "BBB", "SPY"}
    w = json.loads(files["weekly_01.json"])
    assert set(w["AAA"]) == {"d", "o", "h", "l", "c", "v"}                 # bez znacznika raw
    m = json.loads(files[f"monthly_{man['chunks']['monthly']['AAA']:02d}.json"])["AAA"]
    assert m["d"] == ["2026-07-01", "2026-08-01", "2026-09-01"] and m["c"] == [1.5, 2.5, 3.5]   # bieżący (otwarty) miesiąc odpada — strona dobuduje go z tygodniowych
    assert set(man["chunks"]["monthly"]) == {"AAA"} and info["bytes"] > 1000


def test_chunks_respect_the_size_limit_and_batches_send_manifest_last():
    big = {f"T{i}": _series(200) for i in range(20)}
    parts = gist.chunk(big, limit=30_000)
    assert len(parts) > 1 and sum(len(p) for p in parts) == 20 and all(len(gist.dump(p)) <= 30_000 + 5000 for p in parts)
    files = {"weekly_01.json": "x" * 100, "monthly_01.json": "y" * 100, gist.MANIFEST: "m" * 100, "weekly_02.json": "z" * 100}
    b = gist.batches(files, limit=150)
    assert [list(p) for p in b][-1] == [gist.MANIFEST] and sum(len(p) for p in b) == 4


def test_upload_creates_secret_gist_then_patches_remaining_files():
    calls = []

    def req(method, url, token, body=None):
        calls.append((method, url, body))
        return {"id": "abc123", "html_url": "https://gist.github.com/u/abc123"}
    files = {"weekly_01.json": "a" * 60, "weekly_02.json": "b" * 60, gist.MANIFEST: "m" * 60}
    old = gist.BATCH_BYTES
    gist.BATCH_BYTES = 100
    try:
        out = gist.upload(files, "tok", None, request=req)
    finally:
        gist.BATCH_BYTES = old
    assert out == {"id": "abc123", "url": "https://gist.github.com/u/abc123"}
    assert calls[0][0] == "POST" and calls[0][2]["public"] is False
    assert [c[0] for c in calls[1:]] == ["PATCH", "PATCH"] and list(calls[-1][2]["files"]) == [gist.MANIFEST]   # manifest ostatni
    with pytest.raises(gist.GistError):
        gist.upload(files, "", None, request=req)


def test_upload_to_existing_gist_removes_stale_chunks():
    seen = []

    def req(method, url, token, body=None):
        seen.append((method, body))
        return {"id": "g1", "files": {"weekly_01.json": {}, "weekly_07.json": {}, "monthly_03.json": {}, "notes.txt": {}}, "html_url": "u"}
    gist.upload({"weekly_01.json": "w", gist.MANIFEST: "m"}, "tok", "g1", request=req)
    assert seen[0][0] == "GET"
    patch_files = seen[-1][1]["files"]
    assert patch_files["weekly_07.json"] is None and patch_files["monthly_03.json"] is None and "notes.txt" not in patch_files   # cudze pliki zostają
    assert patch_files[gist.MANIFEST] == {"content": "m"}
