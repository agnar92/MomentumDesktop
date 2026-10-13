"""Harmonogram automatycznych synchronizacji (gdy program jest uruchomiony): kiedy była ostatnia zaplanowana chwila i czy dane są od niej starsze."""
from datetime import datetime, timedelta, timezone

GRACE_HOURS = {"prices": 20, "fundamentals": 100}   # nadrabianie: jak długo po zaplanowanej chwili program jeszcze ją wykona (np. włączony później)


def parse_time(text):
    h, m = str(text).split(":")
    h, m = int(h), int(m)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(text)
    return h, m


def last_scheduled(now, cfg):
    """Ostatnia zaplanowana chwila (czas lokalny) nie późniejsza niż `now`, albo None. cfg = {enabled, time 'HH:MM', days [0=pn..6=nd]}."""
    if not cfg.get("enabled") or not cfg.get("days"):
        return None
    try:
        h, m = parse_time(cfg.get("time", "00:00"))
    except ValueError:
        return None
    for back in range(8):
        day = (now - timedelta(days=back)).replace(hour=h, minute=m, second=0, microsecond=0)
        if day.weekday() in cfg["days"] and day <= now:
            return day
    return None


def to_local(iso_utc):
    """'2026-10-12T14:51:33Z' -> czas lokalny bez strefy (albo None)."""
    try:
        return datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def due(now, cfg, last_iso, kind):
    """Zaplanowana chwila, na którą synchronizacja jest należna (dane starsze od niej, a od chwili minęło mniej niż okres nadrabiania), albo None."""
    sched = last_scheduled(now, cfg)
    if sched is None or now - sched > timedelta(hours=GRACE_HOURS.get(kind, 20)):
        return None
    last = to_local(last_iso)
    return sched if last is None or last < sched else None
