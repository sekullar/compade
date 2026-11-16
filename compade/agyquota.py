"""agy kotasını bellekte sorgulayan, arka planlı yardımcı."""
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://cloudcode-pa.googleapis.com/v1internal:"
URL = BASE + "loadCodeAssist"
MODELS_URL = BASE + "fetchAvailableModels"
PROJECT_FILE = Path.home() / ".gemini" / "antigravity-cli" / "cache" / "default_project_id.txt"
_lock = threading.Lock()
_caches = {}


def _token_from_credential(cred):
    if not cred:
        return None
    try:
        obj = json.loads(cred["blob"].decode("utf-8"))
    except (ValueError, UnicodeDecodeError, KeyError, AttributeError):
        return None
    if not isinstance(obj, dict):
        return None
    for src in (obj.get("token"), obj):        # agy biçimi: {"token": {"access_token": ...}, "id_token_email": ...}
        if not isinstance(src, dict):
            continue
        for key in ("access_token", "accessToken"):
            val = src.get(key)
            if isinstance(val, str) and val:
                return val
    return None


def email_from_credential(cred):
    """agy kimlik kaydındaki e-posta (gizli değil); yoksa None."""
    try:
        obj = json.loads(cred["blob"].decode("utf-8"))
        val = obj.get("id_token_email")
        return val if isinstance(val, str) and "@" in val else None
    except (ValueError, UnicodeDecodeError, KeyError, AttributeError, TypeError):
        return None


def _request(token, url, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "User-Agent": "antigravity",
    })
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def _models_response(obj):
    models = obj.get("models") if isinstance(obj, dict) else None
    out, seen = [], {}
    if isinstance(models, dict):
        models = [dict(v, name=k) if isinstance(v, dict) else {"name": k} for k, v in models.items()]
    if not isinstance(models, list):
        return out
    for item in models:
        if not isinstance(item, dict):
            continue
        # displayName'i olmayanlar agy'nin iç modelleri (sekme tamamlama vb.): kullanıcıya gösterme
        name = item.get("displayName") or ("" if item.get("model") or str(item.get("name", "")).startswith(("chat_", "tab_")) else item.get("name"))
        quota = item.get("quotaInfo") or item.get("quota_info") or {}
        frac = quota.get("remainingFraction") if isinstance(quota, dict) else None
        if not isinstance(name, str) or not name or not isinstance(frac, (int, float)):
            continue
        frac = max(0.0, min(1.0, float(frac)))
        prev = seen.get(name)
        if prev is None:
            seen[name] = {"name": name, "remaining": frac, "resets_at": quota.get("resetTime")}
            out.append(seen[name])
        elif frac < prev["remaining"]:
            prev.update(remaining=frac, resets_at=quota.get("resetTime"))
    return out


def _project(token):
    """agy'nin proje kimliği: önce agy önbelleği, yoksa loadCodeAssist."""
    try:
        val = PROJECT_FILE.read_text(encoding="utf-8").strip()
        if val:
            return val, None
    except OSError:
        pass
    obj = _request(token, URL, {"metadata": {"ideType": "ANTIGRAVITY"}})
    tier = (obj.get("paidTier") or obj.get("currentTier") or {}).get("name") if isinstance(obj, dict) else None
    return (obj.get("cloudaicompanionProject") if isinstance(obj, dict) else None), tier


def _query(credential_reader):
    now = time.time()
    try:
        token = _token_from_credential(credential_reader())
        if not token:
            return {"models": [], "checked_at": now, "error": "agy girişi bulunamadı"}
        try:
            project, tier = _project(token)
            obj = _request(token, MODELS_URL, {"project": project} if project else {})
        except urllib.error.HTTPError as e:
            msg = "agy giriş anahtarı eskimiş (yenilenmeli)" if e.code == 401 else f"agy kota sorgusu reddedildi ({e.code})"
            return {"models": [], "checked_at": now, "error": msg}
        models = _models_response(obj)
        if not models:
            return {"models": [], "checked_at": now, "error": "agy yanıtında kota bilgisi yok"}
        models.sort(key=lambda m: m["remaining"])
        return {"models": models, "checked_at": now, "error": None, "tier": tier}
    except Exception:
        return {"models": [], "checked_at": now, "error": "agy kotası ölçülemiyor"}


def get(credential_reader, *, key="live", now=None, max_age=300, err_age=30):
    """Hesap başına önbellek. Eksik/eski değer için arka plan sorgusu başlatır.

    Dönüş: son ölçüm (hata olsa bile son başarılı model listesi `last_ok` olarak korunur) ya da None.
    """
    now = time.time() if now is None else now
    with _lock:
        c = _caches.setdefault(key, {"value": None, "at": 0.0, "running": False, "last_ok": None, "generation": 0})
        v = c["value"]
        fresh = v is not None and now - c["at"] < (err_age if v.get("error") else max_age)
        if not fresh and not c["running"]:
            c["running"] = True
            generation = c["generation"]
            def work():
                value = _query(credential_reader)
                with _lock:
                    # invalidate() sonrası eski credential reader ile başlayan sorguyu yayımlama.
                    if c["generation"] != generation:
                        c["running"] = False
                        return
                    if not value.get("error"):
                        c["last_ok"] = value
                    c.update(value=value, at=time.time(), running=False)
            threading.Thread(target=work, daemon=True).start()
        if v is None:
            return None
        out = dict(v)
        if v.get("error") and c["last_ok"]:
            out["last_ok"] = c["last_ok"]
        out["refreshing"] = c["running"]
        return out


def invalidate(key=None):
    """Önbelleği boşalt (hesap geçişi/giriş kaydı/yenile düğmesi sonrası)."""
    with _lock:
        for k, c in _caches.items():
            if key is None or k == key:
                c.update(value=None, at=0.0, generation=c.get("generation", 0) + 1)


def reset_cache():
    with _lock:
        _caches.clear()
