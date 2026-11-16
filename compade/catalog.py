"""Runtime bazında model kataloğu."""
import os
import subprocess
import threading
import time
from pathlib import Path

from .engine import exe_opencode, exe
from . import config

_lock = threading.Lock()
_cache = {"at": 0, "models": [], "errors": {}}


def catalog(force=False):
    global _cache
    with _lock:
        if not force and time.time() - _cache["at"] < 600:
            return {"models": list(_cache["models"]), "errors": dict(_cache["errors"])}
        models, errors = [], {}
        def add(rt, mid, label=None, free=False, group=None):
            ref = f"{rt}:{mid}"
            if not any(x["ref"] == ref for x in models):
                models.append({"ref": ref, "runtime": rt, "model_id": mid, "label": label or mid,
                               "free": bool(free), "group": group or rt})
        try:
            candidates = [Path.home()/".codex"/"models_cache.json", Path.home()/".codex"/"config.toml"]
            mids = []
            for p in candidates:
                if p.name.endswith(".json") and p.exists():
                    import json
                    raw = json.loads(p.read_text(encoding="utf-8"))
                    mids += raw if isinstance(raw, list) else raw.get("models", [])
                    break
                if p.name == "config.toml" and p.exists():
                    import re
                    match = re.search(r"(?m)^\s*model\s*=\s*['\"]([^'\"]+)['\"]", p.read_text(encoding="utf-8"))
                    if match:
                        mids.append(match.group(1))
                        break
            # models_cache.json kayıtları: {slug, display_name, visibility: list|hide, priority}
            mids = [m for m in mids if isinstance(m, str) or m.get("visibility", "list") != "hide"]
            mids.sort(key=lambda m: 0 if isinstance(m, str) else m.get("priority", 99))
            add("codex", "default", "Varsayılan")
            if not [m for m in mids if m != "default"]:
                mids = ["gpt-5-codex"]
            for m in mids:
                mid = m if isinstance(m, str) else (m.get("slug") or m.get("id"))
                label = None if isinstance(m, str) else m.get("display_name")
                if mid and mid != "default":
                    add("codex", mid, label or mid)
        except Exception as e: errors["codex"] = str(e)
        try:
            for m in ("sonnet", "opus", "haiku", "default"): add("claude", m, m.title())
        except Exception as e: errors["claude"] = str(e)
        for rt, cmd in (("agy", [exe("agy"), "models"]), ("opencode", [exe_opencode(), "models"])):
            try:
                if not cmd[0]: raise FileNotFoundError(f"{rt} CLI bulunamadı")
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=15, errors="replace")
                if p.returncode: raise RuntimeError((p.stderr or "CLI başarısız").strip()[:160])
                for line in p.stdout.splitlines():
                    line = line.strip()
                    if not line: continue
                    if rt == "agy":
                        parts = line.split("\t", 1); mid = parts[0]
                        add(rt, mid, parts[1] if len(parts)>1 else mid)
                    else:
                        mid = line.split()[0]
                        add(rt, mid, mid, mid.endswith("-free") or mid.startswith(("opencode/", "ollama/")), group=("opencode-yerel" if mid.startswith("ollama/") else None))
                add(rt, "default", "Varsayılan")
            except Exception as e: errors[rt] = str(e)[:200]
        _cache = {"at": time.time(), "models": models, "errors": errors}
        return {"models": list(models), "errors": dict(errors)}
