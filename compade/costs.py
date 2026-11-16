"""Maliyet/kullanım panosu: kayıt defterinden (ledger.jsonl) gün, model ve rol bazında toplam.

Token: sağlayıcının bildirdiği gerçek sayı (Codex "tokens used", Claude Code result.usage). Bildirilmemişse
karakterden tahmin edilir (karakter / 3.6) ve `est` olarak ayrı tutulur. Para: yalnız Claude Code'un bildirdiği
`total_cost_usd` (abonelikte "eşdeğer API maliyeti"dir, kartından çekilen tutar değil).
"""
import time

from . import router


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _tokens(row):
    real = row.get("tokens")
    if real is None and (row.get("tokens_in") is not None or row.get("tokens_out") is not None):
        real = _num(row.get("tokens_in")) + _num(row.get("tokens_out"))
    if real is not None:
        return int(_num(real)), 0
    return 0, int(_num(row.get("chars")) / 3.6)


def aggregate(rows, days=7, now=None, models=None):
    now = now or time.time()
    lt = time.localtime(now)
    day0 = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)) - (days - 1) * 86400
    keys = [time.strftime("%Y-%m-%d", time.localtime(day0 + i * 86400 + 3600)) for i in range(days)]
    by_day = {k: {"day": k, "chief": 0, "team": 0, "est": 0, "runs": 0, "cost_usd": 0.0} for k in keys}
    by_model, by_role = {}, {}
    tot = {"runs": 0, "ok": 0, "tokens": 0, "est_tokens": 0, "chief_tokens": 0, "team_tokens": 0, "cost_usd": 0.0,
           "seconds": 0.0, "cache_read": 0, "fell_back": 0, "cheap_runs": 0}
    models = models or {}
    for r in rows:
        ts = _num(r.get("ts"))
        if ts < day0:
            continue
        real, est = _tokens(r)
        chief = r.get("kind") == "chief"
        ok = r.get("status") == "ok" and r.get("verify") in (None, "pass")
        cost = _num(r.get("cost_usd"))
        day = by_day.get(time.strftime("%Y-%m-%d", time.localtime(ts)))
        if day:
            day["chief" if chief else "team"] += real
            day["est"] += est
            day["runs"] += 1
            day["cost_usd"] += cost
        tot["runs"] += 1
        tot["ok"] += ok
        tot["tokens"] += real
        tot["est_tokens"] += est
        tot["chief_tokens" if chief else "team_tokens"] += real
        tot["cost_usd"] += cost
        tot["seconds"] += _num(r.get("seconds"))
        tot["cache_read"] += int(_num(r.get("cache_read")))
        tot["fell_back"] += 1 if r.get("fell_back") else 0
        mk = r.get("model") or "?"
        tier = router.tier_of(mk, models.get(mk)) if mk in models else ""
        tot["cheap_runs"] += 1 if tier == "cheap" else 0
        for table, key in ((by_model, mk), (by_role, r.get("role") or ("şef" if chief else "—"))):
            a = table.setdefault(key, {"key": key, "runs": 0, "ok": 0, "tokens": 0, "est_tokens": 0, "seconds": 0.0,
                                       "cost_usd": 0.0, "chief": chief, "tier": tier if table is by_model else ""})
            a["runs"] += 1
            a["ok"] += ok
            a["tokens"] += real
            a["est_tokens"] += est
            a["seconds"] += _num(r.get("seconds"))
            a["cost_usd"] += cost

    def finish(table):
        out = []
        for a in table.values():
            a["pass"] = round(100 * a["ok"] / a["runs"]) if a["runs"] else 0
            a["avg_sec"] = round(a["seconds"] / a["runs"], 1) if a["runs"] else 0
            a["cost_usd"] = round(a["cost_usd"], 4)
            out.append(a)
        return sorted(out, key=lambda a: (a["tokens"] + a["est_tokens"], a["runs"]), reverse=True)

    known = tot["chief_tokens"] + tot["team_tokens"]
    tot["team_share"] = round(100 * tot["team_tokens"] / known) if known else None
    tot["pass"] = round(100 * tot["ok"] / tot["runs"]) if tot["runs"] else None
    tot["cost_usd"] = round(tot["cost_usd"], 4)
    for d in by_day.values():
        d["cost_usd"] = round(d["cost_usd"], 4)
    return {"days": days, "totals": tot, "by_day": list(by_day.values()), "by_model": finish(by_model),
            "by_role": finish(by_role)}
