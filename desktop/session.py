"""Pamięć sesji: które skanery były otwarte przy ostatnim zamknięciu i w jakiej kolejności je otwierano (data/session.json)."""
from pathlib import Path

from . import store

MAX_RECENT = 30


def load(root):
    d = store.read_json(Path(root) / "session.json", {}) or {}
    return {"recent": [s for s in d.get("recent", []) if isinstance(s, str)], "open": [s for s in d.get("open", []) if isinstance(s, str)],
            "launcher": bool(d.get("launcher", False)), "main_hidden": bool(d.get("main_hidden", False)),
            "symbols": [s for s in d.get("symbols", []) if isinstance(s, str)],
            "chart": d.get("chart") if isinstance(d.get("chart"), dict) else {}}   # ustawienia okna wykresu (wspólne dla wszystkich spółek / skanerów)


def save(root, sess):
    store.write_json(Path(root) / "session.json", sess)


def touch(sess, sid):
    """Skaner otwarty właśnie teraz -> na początek listy ostatnio otwieranych."""
    sess["recent"] = [sid] + [s for s in sess["recent"] if s != sid]
    del sess["recent"][MAX_RECENT:]


def order(items, sess):
    """Skanery posortowane wg ostatniego otwarcia (nieotwierane na końcu, alfabetycznie)."""
    rank = {sid: i for i, sid in enumerate(sess["recent"])}
    return sorted(items, key=lambda s: (rank.get(s["id"], len(rank)), s["name"].lower()))


def prune(sess, valid_ids):
    """Wyrzuca skanery, których już nie ma (usunięte)."""
    valid = set(valid_ids)
    sess["recent"] = [s for s in sess["recent"] if s in valid]
    sess["open"] = [s for s in sess["open"] if s in valid]
    return sess
