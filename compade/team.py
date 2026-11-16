"""Şef tarafından ekip tasarımı üretimi ve doğrulaması."""
import json
import re

from . import chief, rolestore
from .catalog import catalog
from . import ledger, limits, wincred, agyquota
from . import accounts as accounts_mod
import time

MAX_ROLES = 40
TEAM_SYSTEM = """Yalnız JSON nesnesi üret. Şeması: {\"summary\":str,\"roles\":[{\"key\":\"kebab-ascii\",\"name\":str,\"description\":str,\"prompt\":str,\"models\":[ref],\"write\":bool,\"folder\":str,\"color\":\"#rrggbb\",\"mascot\":\"round|cat|robot|owl\"}]}. Her rol için models listesinde 1-2 katalog ref'i ver. İşin gerektirdiği kadar rol üret (en az 2, en çok 40); kullanıcı rol sayısı belirttiyse ona uy. Gereksiz rol ekleme. prompt ayrıntılı, en az 8 satır. Şef rolünü listeleme.\n"""


def validate(design, existing, avoided=()):
    if not isinstance(design, dict) or not isinstance(design.get("roles"), list) or not 2 <= len(design["roles"]) <= MAX_ROLES:
        raise ValueError(f"Tasarım 2-{MAX_ROLES} rol içermeli")
    refs = {m["ref"] for m in catalog()["models"]} | {f"{r}:default" for r in ("codex", "claude", "agy", "opencode")}
    keys, out = set(), []

    def bad(ref):
        if not isinstance(ref, str) or ref not in refs:
            return True
        runtime, model_id = ref.split(":", 1)
        # avoid_models legacy girdileri runtime adını (örn. "gemini") içerebilir; agy kataloğu "agy:gemini-*" sunar.
        return (ref in avoided or runtime in avoided or model_id in avoided
                or any(model_id.startswith(f"{item}-") for item in avoided if isinstance(item, str)))

    fallback = next((r for r in ("codex:default", "claude:default", "opencode:default", "agy:default") if not bad(r)), None)
    for i, role in enumerate(design["roles"]):
        if not isinstance(role, dict): raise ValueError("Rol nesne olmalı")
        # Anahtar: geçersizse addan üret, çakışırsa sonuna sayı ekle (tek hatalı rol tüm ekibi düşürmesin).
        key = role.get("key") if isinstance(role.get("key"), str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", role.get("key", "")) else rolestore.slug(role.get("name") or f"rol-{i + 1}")
        base, n = key[:36], 2
        while key in keys or key in existing.get("roles", {}):
            key, n = f"{base}-{n}", n + 1
        keys.add(key)
        role = {**role, "key": key}
        # Modeller: bilinmeyen/kaçınılanları ayıkla, en çok 3 tut; hiç kalmazsa güvenli varsayılan.
        ms = [m for m in dict.fromkeys(role.get("models") or []) if not bad(m)][:3]
        if not ms:
            if not fallback: raise ValueError(f"{key}: kullanılabilir model yok")
            ms = [fallback]
        role["models"] = ms
        row = {**role, "brief": role.get("description", "")}
        out.append((key, rolestore.normalize_role(key, row, {**existing["models"], **{r: {"runtime":r.split(":",1)[0],"id":r.split(":",1)[1]} for r in ms}})))
        out[-1][1]["description"] = role.get("description", "")
    return {"summary": str(design.get("summary", "")), "roles": [{"key": k, **v} for k,v in out]}


def _check(ret, rd):
    """Şef işi hiç çalışamadıysa (limit, CLI hatası…) asıl nedeni göster; 'JSON bulunamadı' diye örtme."""
    results = ret[1] if isinstance(ret, tuple) and len(ret) == 2 else None
    if not results:
        return
    r = results[0]
    if r.get("status") not in ("ok", "suspicious"):
        out = next(iter(Path(rd).glob("out-*.md")), None)
        detail = (out.read_text(encoding="utf-8", errors="replace").strip()[:300] if out else "") or r.get("summary") or ""
        raise ValueError(f"Şef ({r.get('model')}) çalışamadı: {r.get('status')}" + (f" — {detail}" if detail else ""))


def design(prompt, engine):
    roles = engine.roles
    ck = rolestore.chief_key(roles)
    if not ck: raise ValueError("Önce bir şef rolü seç")
    key = roles["roles"][ck]["models"][0]
    jobs, _ = engine.plan([ck], [])
    if not jobs: raise ValueError("Şef modeli çalıştırılamıyor")
    from pathlib import Path
    rd = engine.make_run_dir("ekip-tasarimi")
    rows = ledger.tail(5000)
    day = time.localtime()
    midnight = time.mktime((day.tm_year, day.tm_mon, day.tm_mday, 0, 0, 0, 0, 0, -1))
    counts, last_limits = {}, {}
    for entry in rows:
        ref = entry.get("model")
        if ref and entry.get("status") in ("limit", "error"):
            last_limits[ref] = max(float(entry.get("ts", 0) or 0), last_limits.get(ref, 0))
        if float(entry.get("ts", 0) or 0) >= midnight:
            if ref: counts[ref] = counts.get(ref, 0) + 1
    codex_usage, agy_quota = [], []
    try:
        for account in engine.acc.list():
            if account.get("provider") == "codex":
                status = engine.acc.status(account)
                codex_usage.append({"account": account.get("label"), "used_percent": status.get("used")})
            elif account.get("provider") == "agy":
                aid = account["id"]
                name = accounts_mod.AGY_LIVE if aid == engine.acc.agy_active() else accounts_mod.SNAP.format(aid)
                q = agyquota.get(lambda n=name: wincred.read(n), key=aid)
                if isinstance(q, dict):
                    agy_quota.append({"account": account.get("label"), "models": q.get("models", [])})
    except Exception:
        pass
    try: claude_usage = limits.claude_rate_limits()
    except Exception: claude_usage = None
    quota = {"codex": codex_usage, "agy": agy_quota, "claude": claude_usage, "opencode": {"free": True, "today_runs": counts,
             "last_limit_error": last_limits}}
    system = TEAM_SYSTEM + "\nKatalog:\n" + json.dumps(catalog()["models"], ensure_ascii=False) + "\nHesap kotası özeti:\n" + json.dumps(quota, ensure_ascii=False) + "\nKaçınılanlar: " + json.dumps(engine.cfg.get("avoid_models", []))
    task = system + "\nKullanıcı isteği:\n" + prompt
    _check(engine.run(task, jobs, cwd=Path.cwd(), write=False, run_dir=rd), rd)
    candidates = list(rd.glob("out-*.md"))
    if not candidates: raise ValueError("Şef yanıtı bulunamadı")
    out = candidates[0].read_text(encoding="utf-8")
    for attempt in range(2):
        try: return validate(chief.extract_json(out), roles, engine.cfg.get("avoid_models", []))
        except ValueError as e:
            if attempt: raise
            task = (system + "\nKullanıcı isteği:\n" + prompt + "\n\nÖnceki yanıtın:\n" + out[:12000] +
                    "\n\nÖnceki yanıttaki hata: " + str(e) + "\nAynı ekibi koruyarak JSON'u düzelt. summary alanı kullanıcıya ekibi anlatsın; hatadan söz etme.")
            _check(engine.run(task, jobs, cwd=Path.cwd(), write=False, run_dir=rd), rd)
            out = candidates[0].read_text(encoding="utf-8")
