"""Lekki „skrypt” filtrujący listę po kolumnach: warunki `kolumna operator wartość`, operatory > < >= <= == != (też `=` jako ==).
Kolumnę podajesz kluczem (`adr_pct`) albo etykietą w cudzysłowie (`"Cena/min 3M"`). Warunki łączysz słowami `and` / `or` (też `i` / `lub`)
i nawiasami; każda nowa linia to kolejny warunek połączony `and`; linie od `#` to komentarze.
Przykłady:  adr_pct >= 4
            "Cena/min 3M" > 1.5 and price < 100
            glb_state == WYBICIE
            sector == "Technology" or sector == Healthcare
Wartość liczbowa: 4, 4.5, 4,5, 12%; tekst: słowo albo w cudzysłowie (porównanie bez rozróżniania wielkości liter, także z etykietą z listy, np. `darvas == KUP`).
`brak` / `puste` oznacza pustą wartość: `rs_rating != brak`. Brak wartości w komórce nie spełnia żadnego porównania liczbowego."""
import re

from . import columns as columns_mod


class ExprError(ValueError):
    """Błąd składni lub nieznana kolumna — komunikat po polsku, gotowy do pokazania użytkownikowi."""


_TOKEN = re.compile(r"""\s*(?:(?P<str>"[^"]*"|'[^']*')|(?P<op>>=|<=|==|!=|>|<|=)|(?P<par>[()])|(?P<word>[^\s()<>=!"']+))""")
_AND, _OR = {"and", "i", "&&", "oraz"}, {"or", "lub", "||"}
_EMPTY = {"brak", "puste", "null", "none"}


def _tokenize(line):
    out, pos = [], 0
    while pos < len(line):
        if not line[pos:].strip():
            break
        m = _TOKEN.match(line, pos)
        if not m or m.end() == pos:
            raise ExprError(f"nieoczekiwany znak „{line[pos:].strip()[:1]}” w: {line.strip()}")
        pos = m.end()
        if m.group("str") is not None:
            out.append(("str", m.group("str")[1:-1]))
        elif m.group("op"):
            out.append(("op", m.group("op")))
        elif m.group("par"):
            out.append(("par", m.group("par")))
        else:
            w = m.group("word")
            out.append(("and" if w.lower() in _AND else "or" if w.lower() in _OR else "word", w))
    return out


def _number(text):
    t = text.strip().rstrip("%").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def column_index(keys):
    """{nazwa małymi literami: klucz} z kluczy i etykiet kolumn (klucz ma pierwszeństwo przed etykietą)."""
    idx = {}
    for k in keys:
        idx.setdefault(columns_mod.label(k).lower(), k)
    for k in keys:
        idx[k.lower()] = k
    return idx


def _cell_values(row, key):
    """(wartość surowa, teksty do porównań ==: surowy i wyświetlany w tabeli)."""
    raw = row.get(key)
    texts = set()
    if raw not in (None, ""):
        texts.add(str(raw).strip().lower())
        try:
            shown = columns_mod.format_cell(row, key, _state_labels())
        except Exception:   # noqa: BLE001 — formatowanie jest tylko dodatkiem do dopasowania tekstu
            shown = ""
        if shown and shown not in ("–", "—"):
            texts.add(shown.strip().lower())
    return raw, texts


def _state_labels():
    from . import store
    return store.STATE_LABELS


def _compare(op, a, b):
    return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b, "==": a == b, "!=": a != b}[op]


def _make_condition(col, op, kind, value):
    def test(row):
        raw, texts = _cell_values(row, col)
        empty = raw in (None, "") or (isinstance(raw, float) and raw != raw)
        if kind == "empty":
            return empty if op == "==" else (not empty if op == "!=" else False)
        if kind == "num":
            if isinstance(raw, bool):
                raw = 1.0 if raw else 0.0
            if not isinstance(raw, (int, float)) or empty:
                return op == "!="   # brak liczby: spełnia tylko „różne od”
            return _compare(op, float(raw), value)
        # tekst
        if op == "==":
            return value in texts
        if op == "!=":
            return value not in texts
        if empty:
            return False
        return _compare(op, str(raw).strip().lower(), value)
    return test


class _Parser:
    def __init__(self, tokens, idx, line):
        self.t, self.i, self.idx, self.line = tokens, 0, idx, line

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        fn = self.or_expr()
        if self.i < len(self.t):
            raise ExprError(f"nieoczekiwane „{self.t[self.i][1]}” w: {self.line.strip()}")
        return fn

    def or_expr(self):
        parts = [self.and_expr()]
        while self.peek()[0] == "or":
            self.take()
            parts.append(self.and_expr())
        return parts[0] if len(parts) == 1 else (lambda row, p=parts: any(f(row) for f in p))

    def and_expr(self):
        parts = [self.atom()]
        while self.peek()[0] == "and":
            self.take()
            parts.append(self.atom())
        return parts[0] if len(parts) == 1 else (lambda row, p=parts: all(f(row) for f in p))

    def atom(self):
        kind, val = self.peek()
        if kind == "par" and val == "(":
            self.take()
            fn = self.or_expr()
            if self.take() != ("par", ")"):
                raise ExprError(f"brakuje „)” w: {self.line.strip()}")
            return fn
        if kind not in ("word", "str"):
            raise ExprError(f"oczekiwałem nazwy kolumny w: {self.line.strip()}")
        self.take()
        col = self.idx.get(val.lower())
        if col is None:
            known = ", ".join(sorted(self.idx)[:12])
            raise ExprError(f"nieznana kolumna „{val}” (np. {known}…); etykiety ze spacjami wpisz w cudzysłowie")
        okind, op = self.take()
        if okind != "op":
            raise ExprError(f"po „{val}” oczekiwałem operatora (> < >= <= == !=) w: {self.line.strip()}")
        op = "==" if op == "=" else op
        vk, vv = self.take()
        if vk not in ("word", "str"):
            raise ExprError(f"po „{val} {op}” oczekiwałem wartości w: {self.line.strip()}")
        if vk == "word" and vv.lower() in _EMPTY:
            return _make_condition(col, op, "empty", None)
        num = _number(vv) if vk == "word" else None
        if num is not None:
            return _make_condition(col, op, "num", num)
        return _make_condition(col, op, "text", vv.strip().lower())


def compile_filter(text, keys):
    """Zamienia skrypt na funkcję row -> bool (puste = wszystko pasuje). Błąd: ExprError z czytelnym opisem i numerem linii."""
    idx = column_index(keys)
    funcs = []
    for n, line in enumerate((text or "").splitlines(), 1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        try:
            funcs.append(_Parser(_tokenize(line), idx, line).parse())
        except ExprError as e:
            raise ExprError(f"linia {n}: {e}") from None
    if not funcs:
        return lambda row: True
    return lambda row: all(f(row) for f in funcs)


def apply(rows, text, keys):
    fn = compile_filter(text, keys)
    return [r for r in rows if fn(r)]
