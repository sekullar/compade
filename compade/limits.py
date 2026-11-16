"""Limit denetçisi: hata metninden limit tespiti, bekleme süresi okuma, Codex gerçek kullanım oranı."""
import json
import re
import time
from pathlib import Path


def is_limit_error(text, patterns):
    if not text:
        return False
    for p in patterns:
        try:
            if re.search(p, text, re.I):
                return True
        except re.error:
            continue
    return False


_DUR = [
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:d|day|days|gün)\b", re.I), 86400),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours|saat)\b", re.I), 3600),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:m|min|mins|minute|minutes|dk|dakika)\b", re.I), 60),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds|sn|saniye)\b", re.I), 1),
]


def parse_wait_seconds(text):
    """'try again in 2h 30m' benzeri metinden bekleme süresini (sn) çıkar. Bulunamazsa None."""
    text = text or ""
    segs = []
    m = re.search(r"\b(?:in|after|within)\s+([^.\n]{1,40})", text, re.I)       # "try again in 2h 30m"
    if m:
        segs.append(m.group(1))
    m = re.search(r"([^.\n]{1,40}?)\s+sonra\b", text, re.I)                     # "15 dakika sonra tekrar deneyin"
    if m:
        segs.append(m.group(1))
    for seg in segs:
        total = 0.0
        for rx, mult in _DUR:
            for v in rx.findall(seg):
                total += float(v) * mult
        if total > 0:
            return int(total)
    return None


def codex_rate_limits(home):
    """Codex oturum günlüklerinden en son `rate_limits` olayını oku.

    home: CODEX_HOME klasörü. Dönüş: {"windows": [{"name","used","minutes","resets_at"}], "plan", "reached"} ya da None.
    """
    root = Path(home) / "sessions"
    if not root.exists():
        return None
    files = sorted(root.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:4]
    for f in files:
        try:
            size = f.stat().st_size
            with open(f, "rb") as fh:
                fh.seek(max(0, size - 400_000))
                tail = fh.read().decode("utf-8", errors="ignore")
        except OSError:
            continue
        for line in reversed(tail.splitlines()):
            if '"rate_limits"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            rl = _find_key(obj, "rate_limits")
            if not isinstance(rl, dict):
                continue
            wins = []
            for name in ("primary", "secondary"):
                w = rl.get(name)
                if isinstance(w, dict) and isinstance(w.get("used_percent"), (int, float)):
                    ra = w.get("resets_at")
                    wins.append({"name": name, "used": float(w["used_percent"]), "minutes": w.get("window_minutes"),
                                 "resets_at": ra if isinstance(ra, (int, float)) and not isinstance(ra, bool) else None})
            return {"windows": wins, "plan": rl.get("plan_type"), "reached": rl.get("rate_limit_reached_type"),
                    "seen": f.stat().st_mtime}
    return None


def claude_rate_limits(path=None, now=None):
    """Claude statusline önbelleğini Compade pencerelerine çevirir."""
    path = Path(path) if path else Path.home() / ".compade/claude-usage.json"
    now = time.time() if now is None else now
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("rate_limits")
    windows = []
    if isinstance(raw, dict):
        for name, value in raw.items():
            if not isinstance(value, dict):
                continue
            used = value.get("used_percentage", value.get("used_percent"))
            if isinstance(used, (int, float)) and not isinstance(used, bool):
                windows.append({"name": str(name), "used": float(used), "resets_at": value.get("resets_at")})
            else:
                windows.append({"name": str(name), "used": None, "resets_at": value.get("resets_at"), "raw": value})
    else:
        windows.append({"name": "unknown", "used": None, "resets_at": None, "raw": raw})
    saved_at = data.get("saved_at")
    return {"windows": windows, "saved_at": saved_at, "stale": not isinstance(saved_at, (int, float)) or now - saved_at > 6 * 3600}


def _find_key(obj, key, depth=0):
    if depth > 6:
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _find_key(v, key, depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_key(v, key, depth + 1)
            if r is not None:
                return r
    return None


def codex_exhausted(info, threshold, now=None):
    """Sınırı aşan ve henüz sıfırlanmamış bir pencere var mı? -> (bool, sıfırlanma_epoch|None)"""
    now = now or time.time()
    if not info:
        return False, None
    hit, worst = False, 0
    for w in info["windows"]:           # tüm pencereleri tara: en geç sıfırlanan belirleyici
        reset = w.get("resets_at")
        if w["used"] >= threshold and (reset is None or reset > now):
            hit = True
            worst = max(worst, reset or 0)
    return (True, worst or None) if hit else (False, None)


def fmt_wait(sec):
    sec = int(max(0, sec))
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return f"{d}g {h}sa"
    if h:
        return f"{h}sa {m}dk"
    return f"{m}dk"
