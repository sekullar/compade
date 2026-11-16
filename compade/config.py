"""Compade ayarları ve veri klasörü (~/.compade)."""
import copy
import json
import os
import uuid
from pathlib import Path

HOME = Path(os.environ.get("COMPADE_HOME") or (Path.home() / ".compade"))
RUNS = HOME / "runs"
ACCOUNTS_DIR = HOME / "accounts"
LEDGER = HOME / "ledger.jsonl"
STATE = HOME / "state.json"
CONFIG = HOME / "config.json"
PKG = Path(__file__).resolve().parent
ASSETS = PKG / "assets"

DEFAULTS = {
    "theme": "dark",
    "editor_enabled": True,
    "opencode_model": "",              # OpenCode için seçili model (boş = OpenCode varsayılanı)
    "default_tool": "",                # rol yokken sorulmadan kullanılacak araç (boş = her seferinde sor)
    "discuss_first": True,
    "discuss_model": "",
    "cc_permission_mode": "plan",
    "cc_allowed_tools": [],
    "theme_color": "green",            # green | blue | red | purple | black
    "avoid_models": [],               # rol modeli seçerken mümkünse kaçınılacak modeller (ör. limiti dolan)
    "plan_approval": "",              # "" = henüz sorulmadı, "ask" = her planda sor, "auto" = otomatik onayla
    "timeout": 600,
    "notify": True,                   # pencere arka plandayken masaüstü bildirimi
    "routing": "balanced",            # işe göre model seçimi: off | saver | balanced | quality
    "isolate": True,                  # yazma görevleri git worktree'de (kullanıcının klasörüne onaysız yazılmaz)
    "verify_cmd": "",                 # "" = projeden algıla (pytest/unittest/npm/cargo/go), "off" = kapalı
    "verify_timeout": 300,
    "limit_threshold": 98,            # % — bu değerin üstündeki hesap atlanır
    "cooldown_minutes_default": 60,   # limit mesajından süre okunamazsa
    "limit_patterns": [
        r"usage limit", r"rate.?limit", r"quota", r"RESOURCE_EXHAUSTED", r"\b429\b",
        r"too many requests", r"exceeded.{0,30}(limit|quota)", r"limit (reached|exceeded)",
        r"credits? (exhausted|depleted|ran out)", r"hit your .{0,20}limit",
    ],
    "refusal_patterns": [
        r"okuyam[ıi]yorum", r"eri[sş]emiyorum", r"dosya(y[ıi]|n[ıi]n i[cç]eri[gğ]ini) payla[sş]", r"elimde yok",
        r"(cannot|can't|unable to|couldn't) (read|access|open) ", r"no access to",
    ],
    # Bir sağlayıcının tüm hesapları dolarsa sırayla denenecek modeller (yazma işinde ücretsiz modele düşülmez)
    "fallback": {"codex": ["gemini"], "agy": ["codex"], "opencode": ["gemini"]},   # anahtar: model adı ya da çalışma zamanı (codex/agy/opencode)
    "accounts": [
        {"id": "codex-1", "provider": "codex", "label": "Codex ana hesap", "home": ""},
        {"id": "agy-1", "provider": "agy", "label": "Gemini ana hesap"},
    ],
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = v
    return out


def load():
    HOME.mkdir(parents=True, exist_ok=True)
    if CONFIG.exists():
        try:
            return _merge(DEFAULTS, json.loads(CONFIG.read_text(encoding="utf-8")))
        except Exception:
            pass
    return copy.deepcopy(DEFAULTS)


def save(cfg):
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_name(f"{CONFIG.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def load_roles():
    """Rol ve model tablosu: kullanıcı kopyası varsa onu, yoksa pakettekini kullan."""
    for p in (HOME / "roles.json", ASSETS / "roles.json"):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {"roles": {}, "models": {}}
