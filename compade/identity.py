"""Hesap kimliği: hangi e-posta/plan hangi girişe bağlı. Yalnız e-posta ve plan adı döner; token ASLA dışarı çıkmaz.

Codex: <CODEX_HOME>/auth.json içindeki id_token (JWT) yükü; Claude: ~/.claude.json oauthAccount.
Dosya yoksa ya da biçim beklenenden farklıysa None döner (hata fırlatmaz).
"""
import base64
import json
import os
from pathlib import Path
import re

_CACHE = {}   # yol -> ((mtime_ns, boyut), sonuç): iki yazma aynı zaman damgasına düşebilir, boyut da bakılır


def _read_json(path):
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return None, None
    key = str(p)
    hit = _CACHE.get(key)
    sig = (st.st_mtime_ns, st.st_size)
    if hit and hit[0] == sig:
        return hit[1], st.st_mtime_ns
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    _CACHE[key] = (sig, data)
    return data, st.st_mtime_ns


def _jwt_claims(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        return claims if isinstance(claims, dict) else {}
    except (ValueError, IndexError, AttributeError):
        return {}


def codex_identity(codex_home):
    """{'email', 'plan'} ya da None. codex_home: auth.json'ın bulunduğu klasör."""
    data, _ = _read_json(Path(codex_home) / "auth.json")
    if not isinstance(data, dict):
        return None
    tokens = data.get("tokens")
    tok = tokens.get("id_token") if isinstance(tokens, dict) else None
    if not isinstance(tok, str):
        return None
    c = _jwt_claims(tok)
    email = c.get("email")
    auth = c.get("https://api.openai.com/auth")
    plan = auth.get("chatgpt_plan_type") if isinstance(auth, dict) else None
    if not isinstance(email, str) or not email:
        return None
    return {"email": email, "plan": plan if isinstance(plan, str) else None}


def claude_identity(home=None):
    """Claude Code girişi: {'email', 'org'} ya da None."""
    base = Path(home) if home else Path.home()
    data, _ = _read_json(base / ".claude.json")
    acct = data.get("oauthAccount") if isinstance(data, dict) else None
    if not isinstance(acct, dict):
        return None
    email = acct.get("emailAddress")
    if not isinstance(email, str) or not email:
        return None
    org = acct.get("organizationName")
    return {"email": email, "org": org if isinstance(org, str) else None}


def agy_email(log_path=None, tail_bytes=2_000_000):
    """Son başarılı consumer auth satırındaki e-posta; dosya mtime'ı ile önbelleklenir."""
    path = Path(log_path) if log_path else Path(os.environ.get("USERPROFILE", Path.home())) / ".gemini/antigravity-cli/cli.log"
    try:
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    hit = _CACHE.get("agy:" + key)
    sig = (st.st_mtime_ns, st.st_size)
    if hit and hit[0] == sig:
        return hit[1]
    try:
        with path.open("rb") as f:
            f.seek(max(0, st.st_size - tail_bytes))
            text = f.read().decode("utf-8", errors="ignore")
        matches = re.findall(r"applyAuthResult:\s*email=([^,\s]+),\s*authMethod=consumer", text)
        email = matches[-1] if matches else None
    except OSError:
        email = None
    _CACHE["agy:" + key] = (sig, email)
    return email
