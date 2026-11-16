"""Dinamik rol deposu: kullanıcı rolleri ~/.compade/roles.json içinde yaşar, paketteki dosya yalnız ilk şablondur."""
import json
import re
import threading
import uuid
import os
import time

from . import config

_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
MASCOTS = ("cat", "robot", "round", "owl")
DEFAULT_COLOR = "#0F766E"
SEED_COLORS = ("#35c8ad", "#67bff3", "#f5b544", "#a88bea", "#f07b74", "#62d68a", "#f08fc0", "#8fb3f0")
SEED_WRITERS = {"backend", "frontend", "fullstack", "desktop", "mobile", "ai-engineer", "database", "automation",
                "devops", "ui-ux", "technical-writer"}


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower().replace("ı", "i").replace("ş", "s").replace("ğ", "g")
               .replace("ü", "u").replace("ö", "o").replace("ç", "c")).strip("-")
    return s[:40] or "rol"


def _text(v, label, required=False):
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise ValueError(f"{label}: metin olmalı")
    v = v.strip()
    if required and not v:
        raise ValueError(f"{label} boş olamaz")
    return v


def _bool(v, label):
    if v is None:
        return False
    if not isinstance(v, bool):
        raise ValueError(f"{label}: true/false olmalı")
    return v


def _folder(v, label):
    """Rolün çalışma alt klasörü: göreli, kök dışına çıkamaz."""
    v = _text(v, label).replace("\\", "/")
    if not v:
        return ""
    if v.startswith("/") or ":" in v or any(part == ".." for part in v.split("/")):
        raise ValueError(f"{label}: klasör göreli olmalı ('..', sürücü harfi ve mutlak yol olmaz)")
    return v.strip("/")


def normalize_role(key, r, models):
    """Tek rolü doğrular ve eksik alanları doldurur. Hatada ValueError (Türkçe)."""
    if not isinstance(key, str) or not _KEY.match(key):
        raise ValueError(f"Rol anahtarı geçersiz: {key!r} (küçük harf, rakam, - ve _ kullan)")
    if not isinstance(r, dict):
        raise ValueError(f"{key}: rol bir nesne olmalı")
    name = _text(r.get("name"), f"{key}: rol adı", required=True)
    ms = r.get("models")
    if not isinstance(ms, list) or not ms or not all(isinstance(m, str) for m in ms):
        raise ValueError(f"{name}: en az bir model seçilmeli")
    unknown = [m for m in ms if m not in models]
    if unknown:
        raise ValueError(f"{name}: bilinmeyen model: {', '.join(unknown)}")
    color = r.get("color") or DEFAULT_COLOR
    if not isinstance(color, str) or not _COLOR.match(color):
        raise ValueError(f"{name}: renk #RRGGBB biçiminde olmalı")
    mascot = r.get("mascot") or "cat"
    if mascot not in MASCOTS:
        raise ValueError(f"{name}: maskot şunlardan biri olmalı: {', '.join(MASCOTS)}")
    return {
        "name": name,
        "brief": _text(r.get("brief"), f"{name}: açıklama"),
        "prompt": _prompt(r.get("prompt"), f"{name}: prompt"),
        "description": _text(r.get("description", r.get("brief")), f"{name}: açıklama"),
        "models": list(dict.fromkeys(ms)),
        "color": color,
        "mascot": mascot,
        "write": _bool(r.get("write"), f"{name}: write"),
        "folder": _folder(r.get("folder"), f"{name}: klasör"),
        "chief": _bool(r.get("chief"), f"{name}: chief"),
        "primary": _bool(r.get("primary"), f"{name}: primary"),
        "pin_model": _bool(r.get("pin_model"), f"{name}: pin_model"),
    }


def _prompt(v, label):
    value = _text(v, label)
    if len(value) > 8000:
        raise ValueError(f"{label}: en çok 8000 karakter olabilir")
    return value


def normalize(data):
    """Tüm tabloyu doğrular. En çok bir şef; yoksa 'ceo' rolü şef sayılır (varsa)."""
    if not isinstance(data, dict):
        raise ValueError("Rol dosyası bir nesne olmalı")
    models = data.get("models")
    if not isinstance(models, dict) or not all(isinstance(m, dict) and m.get("runtime") for m in models.values()):
        raise ValueError("Model tablosu bozuk: her modelin 'runtime' alanı olmalı")
    models = dict(models)
    for runtime in ("codex", "claude", "agy", "opencode"):
        for rolespec in (data.get("roles") or {}).values():
            if isinstance(rolespec, dict):
                for ref in rolespec.get("models") or []:
                    if isinstance(ref, str) and ref.startswith(runtime + ":"):
                        mid = ref.split(":", 1)[1]
                        if not mid:
                            raise ValueError("Model referansı boş")
                        models.setdefault(ref, {"runtime": runtime, "id": mid})
    raw = data.get("roles")
    if not isinstance(raw, dict):
        raise ValueError("roller bir sözlük olmalı")
    roles = {k: normalize_role(k, v, models) for k, v in raw.items()}
    chiefs = [k for k, v in roles.items() if v["chief"]]
    if len(chiefs) > 1:
        raise ValueError("Yalnız bir rol şef olabilir: " + ", ".join(chiefs))
    primaries = [k for k, v in roles.items() if v["primary"]]
    if len(primaries) > 1:
        raise ValueError("Yalnız bir rol primary olabilir: " + ", ".join(primaries))
    return {**{k: v for k, v in data.items() if k not in ("roles", "models")}, "models": models, "roles": roles}


def chief_key(roles_table):
    for k, v in roles_table.get("roles", {}).items():
        if v.get("chief"):
            return k
    return None


_SAVE_LOCK = threading.Lock()


def load():
    """Kullanıcı dosyası bozuksa uyarı vermeden paketteki şablona düşer ve bozuk dosyayı .bozuk olarak saklar."""
    p = config.HOME / "roles.json"
    _migrate_legacy()
    if p.exists():
        try:
            return normalize(json.loads(p.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            try:
                p.replace(p.with_suffix(".bozuk"))
            except OSError:
                pass
    seed = json.loads((config.ASSETS / "roles.json").read_text(encoding="utf-8"))
    if seed.get("roles") == []:
        seed["roles"] = {}
    for i, (k, r) in enumerate(seed.get("roles", {}).items()):      # şablon: kod yazan roller yazma iznine sahip başlar
        r.setdefault("write", k in SEED_WRITERS)
        r.setdefault("color", SEED_COLORS[i % len(SEED_COLORS)])
        r.setdefault("mascot", MASCOTS[(i // 2) % len(MASCOTS)])
    return normalize(seed)


def _migrate_legacy():
    """Eski hazır rol tablosunu bir kez yedekle ve sıfırla; kullanıcı rollerine dokunma."""
    flag = config.HOME / ".roles-migrated-v1"
    if flag.exists():
        return
    p = config.HOME / "roles.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            keys = set(data.get("roles", {}))
            legacy = {"ceo", "cto", "architect", "backend", "frontend", "fullstack", "desktop", "mobile",
                      "ai-engineer", "database", "automation", "ui-ux"}
            if keys == legacy:
                stamp = time.strftime("%Y%m%d")
                backup = p.with_name(f"roles.json.yedek-{stamp}")
                n = 2
                while backup.exists():
                    backup = p.with_name(f"roles.json.yedek-{stamp}-{n}"); n += 1
                p.replace(backup)
        except (ValueError, OSError, AttributeError):
            pass
    config.HOME.mkdir(parents=True, exist_ok=True)
    flag.write_text("1", encoding="utf-8")


def save(data):
    clean = normalize(data)
    with _SAVE_LOCK:
        config.HOME.mkdir(parents=True, exist_ok=True)
        p = config.HOME / "roles.json"
        tmp = p.with_name(f"roles.{uuid.uuid4().hex[:8]}.tmp")
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as f:
                json.dump(clean, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
    return clean
