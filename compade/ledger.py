"""Kayıt defteri: her iş bir JSONL satırı. Benchmark ve limit geçmişi buradan çıkar."""
import json
import threading
import time

from . import config

_lock = threading.Lock()


def append(entry):
    entry = dict(entry)
    entry.setdefault("ts", time.time())
    config.HOME.mkdir(parents=True, exist_ok=True)
    with _lock, open(config.LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def tail(n=200):
    if not config.LEDGER.exists():
        return []
    try:
        lines = config.LEDGER.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []
    out = []
    for l in lines:
        try:
            out.append(json.loads(l))
        except ValueError:
            continue
    return out


def summary(entries):
    """Ajan/model başına: iş sayısı, geçen oran, ortalama süre."""
    agg = {}
    for e in entries:
        k = e.get("model") or "?"
        a = agg.setdefault(k, {"n": 0, "ok": 0, "sec": 0.0})
        a["n"] += 1
        a["ok"] += 1 if e.get("status") == "ok" and e.get("verify") in (None, "pass") else 0
        a["sec"] += float(e.get("seconds") or 0)
    return {k: {"n": v["n"], "pass": round(100 * v["ok"] / v["n"]) if v["n"] else 0,
                "avg_sec": round(v["sec"] / v["n"], 1) if v["n"] else 0} for k, v in agg.items()}
