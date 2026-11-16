"""Compade web arayüz sunucusu (yalnız standart kütüphane).

127.0.0.1'e bağlanır; Edge'i uygulama penceresi olarak açar. API sözleşmesi design/gorev-tasarim-v2.md'dedir;
arayüz yalnız bu API ile konuşur, böylece arka uç ileride (ör. Rust/Tauri) değişse arayüze dokunulmaz.

Güvenlik: oturuma özel rastgele anahtar (HTML'e gömülür) her /api çağrısında zorunlu, Host başlığı doğrulanır.
Başka bir web sayfası localhost'a istek atıp dosya yazamaz / hesap işlemi tetikleyemez.
"""
import json
import mimetypes
import os
import queue
import secrets
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import accounts as accounts_mod
from . import catalog, costs, team, updater
from . import __version__, agyquota, config, identity, ledger, limits, rolestore, session, sysmon, wincred
from .engine import Engine, exe_opencode

WEB = config.PKG / "web"
EDITABLE_CFG = {"theme_color", "plan_approval", "theme", "limit_threshold", "cooldown_minutes_default", "timeout", "editor_enabled", "opencode_model", "default_tool", "discuss_first", "discuss_model", "cc_permission_mode", "cc_allowed_tools", "isolate", "verify_cmd", "verify_timeout", "routing", "notify"}


class Hub:
    """Olay dağıtıcı (SSE) + çalışan iş sayacı."""

    def __init__(self):
        self.clients = []
        self.lock = threading.Lock()
        self.running = {}            # (run, tag) -> runtime
        self.ever = False
        self.last_zero = time.time()

    def publish(self, kind, data):
        msg = {"kind": kind, **data}
        with self.lock:
            for q in list(self.clients):
                q.put(msg)

    def add(self):
        q = queue.Queue()
        with self.lock:
            self.clients.append(q)
            self.ever = True
        return q

    def remove(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)
            if not self.clients:
                self.last_zero = time.time()

    def count(self):
        with self.lock:
            return len(self.clients)


class App:
    def __init__(self):
        self.cfg = config.load()
        self.engine = Engine(self.cfg)
        self.mon = sysmon.Monitor(interval=3.0)
        self.mon.start()
        self.hub = Hub()
        self.sessions = session.Sessions(self.engine, self.on_event)
        self.token = secrets.token_urlsafe(24)
        self.port = 0
        self._opencode_cache = {"at": 0.0, "models": [], "error": None}
        self._opencode_lock = threading.Lock()
        self._opencode_runner = subprocess.run
        self.team_designs = {}
        self._team_lock = threading.Lock()

    def _opencode_models(self):
        with self._opencode_lock:
            if time.time() - self._opencode_cache["at"] < 600:
                return {"models": list(self._opencode_cache["models"]), "error": self._opencode_cache["error"]}
            try:
                p = self._opencode_runner([exe_opencode(), "models"], capture_output=True, text=True, timeout=15, errors="replace")
                if p.returncode:
                    raise RuntimeError((p.stderr or "opencode models başarısız").strip().splitlines()[-1][:160])
                models = [line.strip() for line in p.stdout.splitlines() if line.strip()]
                result = {"models": models, "error": None}
            except Exception as e:
                result = {"models": [], "error": str(e).replace("Bearer ", "Bearer [redacted] ")[:160] or "opencode models başarısız"}
            self._opencode_cache = {**result, "at": time.time()}
            return result

    # ---------- API ----------
    def on_event(self, kind, d):
        tag = d.get("tag")
        if kind == "start":
            self.hub.running[(d["run"], tag)] = self.engine.roles["models"].get(d["model"], {}).get("runtime")
        elif kind == "done":
            self.hub.running.pop((d["run"], tag), None)
        self.hub.publish(kind, d)

    def state(self):
        eng = self.engine
        providers = []
        for key, name in (("codex", "Codex"), ("agy", "Antigravity"), ("opencode", "OpenCode")):
            running = sum(1 for v in self.hub.running.values() if v == key)
            if key == "opencode":
                op = self._opencode_models()
                n = len(op["models"])
                providers.append({"key": key, "name": name, "state": "running" if running else "idle", "used": None,
                                  "ready": n, "total": n, "running": running, "note": "Ücretsiz modeller, hesap gerekmez"})
                continue
            stats = [eng.acc.status(a) for a in eng.acc.list(key) if a.get("enabled", True)]
            ready = [s for s in stats if s["state"] == "ready"]
            if running:
                st = "running"
            elif ready:
                st = "idle"
            elif any(s["state"] in ("limit", "cooldown") for s in stats):
                st = "limit"
            else:
                st = "offline"
            used = [s["used"] for s in stats if s.get("used") is not None]
            nxt = [s["resets_at"] for s in stats if s.get("resets_at")]
            note = f"sıfırlanma {limits.fmt_wait(min(nxt) - time.time())}" if st == "limit" and nxt else ""
            providers.append({"key": key, "name": name, "state": st, "used": max(used) if used else None,
                              "ready": len(ready), "total": len(stats), "running": running, "note": note})
        accounts = []
        duplicate_labels = eng.acc.duplicate_labels()
        today_start = time.localtime()
        today_start = time.mktime((today_start.tm_year, today_start.tm_mon, today_start.tm_mday, 0, 0, 0, 0, 0, -1))
        rows = ledger.tail(5000)
        agy_emails = {}
        for a in eng.acc.list():
            s = eng.acc.status(a)
            ident = identity.codex_identity(eng.acc.codex_home(a)) if a["provider"] == "codex" else (
                eng.acc._st(a["id"]).get("identity") if a["provider"] == "agy" else None)
            acct_rows = [r for r in rows if r.get("account") == a["id"]]
            errors = [r for r in acct_rows if r.get("status") in ("limit", "error")]
            accounts.append({"id": a["id"], "label": a["label"], "provider": a["provider"], "state": s["state"],
                             "used": s.get("used"), "resets_in": int(s["resets_at"] - time.time()) if s.get("resets_at") else None,
                             "plan": s.get("plan"), "active": a["provider"] == "agy" and a["id"] == eng.acc.agy_active(),
                             "windows": s.get("windows", []),
                             "runs": s.get("runs", 0), "detail": s.get("detail", ""),
                             "identity": ident, "note": eng.acc._st(a["id"]).get("note", ""),
                             "checked_at": s.get("checked_at"),
                             "today_runs": sum(1 for r in acct_rows if float(r.get("ts", 0) or 0) >= today_start),
                             "last_limit_error": max((float(r.get("ts", 0) or 0) for r in errors), default=None)})
            accounts[-1]["duplicate_labels"] = duplicate_labels.get(a["id"], [])
            if a["provider"] == "agy":
                aid, is_active = a["id"], a["id"] == eng.acc.agy_active()
                name = accounts_mod.AGY_LIVE if is_active else accounts_mod.SNAP.format(aid)
                accounts[-1]["quota"] = agyquota.get(lambda n=name: wincred.read(n), key=(f"live:{aid}" if is_active else aid))
                agy_emails.setdefault((ident or {}).get("email") or "", []).append(a)
        models = [{"key": k, "label": k, "runtime": m["runtime"], "model_id": (m.get("id") or "").split("/")[-1]}
                  for k, m in eng.roles["models"].items() if m["runtime"] in ("codex", "agy", "opencode")]
        roles = [{"key": k, "name": r["name"], "color": r["color"], "mascot": r["mascot"], "chief": r["chief"],
                  "model": self._role_model(k)} for k, r in eng.roles["roles"].items()]
        st = self.mon.stats() or {}
        hist = [round(x["self"] + x["children"], 1) for x in list(self.mon.hist)[-60:]]
        ram = {"now_self": st.get("now_self", 0), "avg_self": st.get("avg_self", 0), "peak_self": st.get("peak_self", 0),
               "now_children": st.get("now_children", 0), "child_count": st.get("child_count", 0),
               "now_ui": st.get("now_ui", 0), "ui_count": st.get("ui_count", 0),
               "system_used": st.get("system_used", 0), "system_total": st.get("system_total", 0), "history": hist}
        cfg = {k: self.cfg.get(k) for k in EDITABLE_CFG}
        claude = identity.claude_identity() or {"email": None, "org": None}
        claude["usage"] = limits.claude_rate_limits()
        for email, group in agy_emails.items():          # aynı Google hesabı birden fazla kartta
            if email and len(group) > 1:
                for acct in accounts:
                    if acct["provider"] == "agy" and any(g["id"] == acct["id"] for g in group):
                        acct["duplicate_labels"] = [g["label"] for g in group if g["id"] != acct["id"]]
        agy_id = eng.acc.agy_active()
        agy = next((x.get("quota") for x in accounts if x["provider"] == "agy" and x["id"] == agy_id), None)
        agy_error = agy.get("error") if isinstance(agy, dict) else None
        if agy_error and "yenilenmeli" in agy_error and time.time() - getattr(self, "_agy_warm_at", 0) > 300:
            # etkin girişin erişim anahtarı eskimiş (agy bir saattir çalışmadı): agy'ye kotasız bir komutla
            # kendiliğinden yenilet; kullanıcıdan bir şey isteme. 5 dakikada en fazla bir kez.
            self._agy_warm_at = time.time()

            def warm(acc=eng.acc):
                if acc.agy_warm_token():
                    agyquota.invalidate()
            threading.Thread(target=warm, daemon=True).start()
            agy_error = "agy girişi tazeleniyor…"
        if agy_error:
            agy = None
        return {"providers": providers, "accounts": accounts, "models": models, "roles": roles,
                "claude": {"email": claude.get("email"), "org": claude.get("org"), "usage": claude.get("usage")},
                "agy_quota": agy, "agy_quota_error": agy_error,
                "opencode": self._opencode_models(), "ram": ram, "cfg": cfg,
                "version": __version__, "home": str(config.HOME), "cwd": str(Path.cwd()),
                "chats": self.sessions.summaries()}

    def run(self, body):
        task = (body.get("task") or "").strip()
        models = [m for m in (body.get("models") or []) if isinstance(m, str)]
        role = body.get("role") or None
        if not task or not (models or role):
            raise ValueError("Görev yazın ve en az bir ajan (ya da rol) seçin.")
        cwd = (body.get("cwd") or "").strip() or None
        if cwd and not Path(cwd).is_dir():
            raise ValueError("Çalışma klasörü bulunamadı.")
        jobs, _ = self.engine.plan([role] if (role and not models) else [], models, as_role=role if models else None)
        if not jobs:
            raise ValueError("Seçimde dış çalışan yok (yalnız Claude rolleri).")
        name = (role or (models[0] if models else "is"))
        run_dir = self.engine.make_run_dir(name)
        title = task.strip().splitlines()[0][:72]
        (run_dir / "title.txt").write_text(title, encoding="utf-8")

        def go():
            self.engine.run(task, jobs, cwd=cwd, write=bool(body.get("write")), verify=(body.get("verify") or None),
                            name=name, on_event=self.on_event, run_dir=run_dir)
        threading.Thread(target=go, daemon=True).start()
        return {"run_id": run_dir.name, "title": title, "jobs": [j["tag"] for j in jobs]}

    def runs(self):
        out = []
        if config.RUNS.exists():
            for p in sorted([d for d in config.RUNS.glob("*") if d.is_dir()], reverse=True)[:80]:
                ts, _, rest = p.name.partition("-")
                t2, _, name = rest.partition("-")
                dg = p / "digest.md"
                txt = dg.read_text(encoding="utf-8", errors="replace") if dg.exists() else ""
                running = any(k[0] == p.name for k in self.hub.running)
                n_ok, n_lim, n_err, n_sus = txt.count("- ✔"), txt.count("- ▲"), txt.count("- ✖"), txt.count("- ?")
                total = n_ok + n_lim + n_err + n_sus
                if running or not txt:
                    summ = "Çalışıyor"
                else:
                    parts = [f"{n_ok}/{total} başarılı"] + ([f"{n_lim} limit"] if n_lim else []) + ([f"{n_err} hata"] if n_err else [])                         + ([f"{n_sus} şüpheli"] if n_sus else [])
                    summ = " · ".join(parts)
                try:
                    when = int(time.mktime(time.strptime(ts + t2, "%Y%m%d%H%M%S")) * 1000)
                except ValueError:
                    when = int(p.stat().st_mtime * 1000)
                title_f = p / "title.txt"
                title = title_f.read_text(encoding="utf-8", errors="replace").strip() if title_f.exists() else (name or p.name)
                out.append({"id": p.name, "when": when, "name": title, "status_summary": summ, "running": running})
        return out

    def run_detail(self, rid):
        d = (config.RUNS / rid).resolve()
        if config.RUNS.resolve() not in d.parents or not d.is_dir():
            raise ValueError("Çalışma bulunamadı")
        digest = (d / "digest.md").read_text(encoding="utf-8", errors="replace") if (d / "digest.md").exists() else ""
        rows = {e["tag"]: e for e in ledger.tail(2000) if e.get("run") == rid and e.get("tag")}
        workers = []
        for f in sorted(d.glob("out-*.md")):
            tag = f.stem[4:]
            e = rows.get(tag, {})
            workers.append({"tag": tag, "model": e.get("model"), "account": e.get("account"), "status": e.get("status", "?"),
                            "seconds": e.get("seconds"), "chars": e.get("chars"), "tokens": e.get("tokens"),
                            "verify": e.get("verify"), "note": "yedek modele geçti" if e.get("fell_back") else "",
                            "output": f.read_text(encoding="utf-8", errors="replace")})
        return {"digest": digest, "workers": workers}

    def account_action(self, body):
        acc = self.engine.acc
        a, action = acc.get(body.get("id")), body.get("action")
        if not a:
            return {"ok": False, "message": "Hesap bulunamadı"}
        try:
            if action == "login":
                acc.start_login(a)
                return {"ok": True, "message": "Giriş penceresi açıldı"}
            if action in ("rename", "note"):
                acc.update_account(a["id"], label=body.get("label") if action == "rename" else None,
                                   note=body.get("note") if action == "note" else None)
                return {"ok": True, "message": "Kaydedildi"}
            if action in ("save", "activate", "refresh") and a["provider"] != "agy":
                return {"ok": False, "message": "Yalnız agy hesapları için"}
            if action == "refresh":
                agyquota.invalidate()
                return {"ok": True, "message": "Kota yenileniyor"}
            if action == "activate":
                # Hesaba GEÇ: o hesabın yedeğini agy'nin canlı kaydına yaz (eskiden yanlışlıkla 'save' çağrılıyordu
                # ve canlı giriş bu hesabın yedeğinin üstüne yazılıyordu).
                if not accounts_mod.AGY_LOCK.acquire(timeout=3):
                    return {"ok": False, "message": "agy şu an bir işte; iş bitince tekrar dene"}
                try:
                    acc.agy_activate(a["id"])
                finally:
                    accounts_mod.AGY_LOCK.release()
                agyquota.invalidate()

                def warm():                                    # eski anahtarı agy'ye yenilet, sonra kotayı tazele
                    acc.agy_warm_token()
                    agyquota.invalidate()
                threading.Thread(target=warm, daemon=True).start()
                return {"ok": True, "message": f"{a['label']} etkin; agy girişi tazeleniyor, kota birazdan güncellenir"}
            if action == "save":
                # Canlı girişi bu karta kaydet. Başka bir kartın yedeğiyle aynı Google hesabıysa reddet (çift kayıt).
                live_email = agyquota.email_from_credential(wincred.read(accounts_mod.AGY_LIVE))
                if live_email:
                    for other in acc.list("agy"):
                        if other["id"] == a["id"]:
                            continue
                        if agyquota.email_from_credential(wincred.read(accounts_mod.SNAP.format(other["id"]))) == live_email:
                            return {"ok": False, "message": f"agy şu an {live_email} ile açık ve bu giriş zaten "
                                    f"'{other['label']}' kartında kayıtlı. Başka bir Google hesabıyla girip tekrar dene."}
                acc.agy_save_current(a["id"])
                msg = f"agy girişi kaydedildi ({live_email or 'e-posta okunamadı'})"
                prev = acc.agy_take_return(a["id"], consume=False)
                if prev:                                       # yeni hesabı ekledikten sonra önceki hesaba geri dön
                    if accounts_mod.AGY_LOCK.acquire(timeout=3):
                        try:
                            acc.agy_activate(prev)
                            acc.agy_clear_return()
                            msg += f"; agy yeniden '{acc.get(prev)['label']}' hesabında"
                        except wincred.CredError as e:
                            msg += f"; önceki hesaba dönülemedi: {e}"
                        finally:
                            accounts_mod.AGY_LOCK.release()
                    else:
                        msg += "; önceki hesaba dönüş bekliyor (agy şu an çalışıyor)"
                agyquota.invalidate()
                return {"ok": True, "message": msg}
            if action == "check":
                if a["provider"] == "codex":
                    message = acc.login_status_text(a) or "Durum alınamadı"
                    duplicates = acc.duplicate_labels().get(a["id"], [])
                    if duplicates:
                        message += f" Uyarı: aynı e-posta şu hesaplarda da var: {', '.join(duplicates)}."
                    return {"ok": True, "message": message}
                return {"ok": True, "message": "giriş kaydı var" if acc.status(a)["state"] != "loggedout" else "giriş yok"}
            if action == "reset":
                acc.clear_cooldown(a["id"])
                return {"ok": True, "message": "Bekleme sıfırlandı"}
            if action == "remove":
                deferred = acc.remove(a["id"])
                return {"ok": True, "message": "Bu hesap şu an bir işte; iş bitince kaldırıldı" if deferred else "Listeden kaldırıldı"}
        except (wincred.CredError, OSError, subprocess.SubprocessError, ValueError) as e:
            return {"ok": False, "message": str(e)}
        return {"ok": False, "message": "Bilinmeyen eylem"}

    def add_account(self, body):
        prov = body.get("provider")
        if prov not in ("codex", "agy"):
            return {"ok": False, "message": "Sağlayıcı codex ya da agy olmalı"}
        try:
            a = self.engine.acc.add(prov, (body.get("label") or "").strip() or None)
        except ValueError as e:
            return {"ok": False, "message": str(e)}
        try:
            self.engine.acc.start_login(a)
        except (wincred.CredError, OSError) as e:
            return {"ok": False, "message": f"Hesap eklendi ama giriş açılamadı: {e}"}
        duplicates = self.engine.acc.duplicate_labels().get(a["id"], []) if prov == "codex" else []
        warning = f" Uyarı: aynı e-posta başka Codex hesabında da var ({', '.join(duplicates)})." if duplicates else ""
        return {"ok": True, "message": "Hesap eklendi, giriş penceresi açıldı." + warning}

    def chat_message(self, body):
        return self.sessions.message(body.get("chat"), body.get("text", body.get("message")), cwd=(body.get("cwd") or "").strip() or None,
                                     files=body.get("files") or [], approval=self.cfg.get("plan_approval", ""), direct=body.get("direct") is True)

    def chat_start(self, body):
        return self.sessions.start(body.get("chat"), cwd=(body.get("cwd") or "").strip() or None)

    def chat_approve(self, body):
        return self.sessions.approve(body.get("chat"), cwd=(body.get("cwd") or "").strip() or None, drop=body.get("drop") or [])

    def chat_tool(self, body):
        return self.sessions.choose_tool(body.get("session") or body.get("chat"), body.get("tool"), body.get("model"),
                                         body.get("remember", False), cwd=(body.get("cwd") or "").strip() or None)

    def _role_model(self, key):
        """Rolün fiilen çalışacağı dış model (yoksa boş)."""
        try:
            jobs, _ = self.engine.plan([key], [])
            return jobs[0]["model"] if jobs else ""
        except Exception:  # noqa
            return ""

    def get_roles(self):
        eng = self.engine
        models = [{"key": k, "runtime": m["runtime"]} for k, m in eng.roles["models"].items()]
        return {"roles": eng.roles["roles"], "models": models, "mascots": list(rolestore.MASCOTS)}

    def save_roles(self, body):
        data = {"models": self.engine.roles["models"], "roles": body.get("roles")}
        data["_note"] = self.engine.roles.get("_note", "")
        rolestore.save(data)
        self.engine.reload_roles()
        return {"ok": True, "roles": self.engine.roles["roles"]}

    def team_design(self, body):
        if not rolestore.chief_key(self.engine.roles):
            raise ValueError("Önce bir şef rolü seç")
        prompt = (body.get("prompt") or "").strip()
        if not prompt: raise ValueError("Ekip isteği boş olamaz")
        ident = secrets.token_urlsafe(12)
        with self._team_lock: self.team_designs[ident] = {"status": "running"}
        self.hub.publish("team_design_start", {"id": ident})
        def work():
            try:
                result = team.design(prompt, self.engine)
                state = {"status": "ready", "design": result}
                self.hub.publish("team_design_ready", {"id": ident, "design": result})
            except Exception as exc:
                state = {"status": "error", "error": str(exc)}
                self.hub.publish("team_design_error", {"id": ident, "error": str(exc)})
            with self._team_lock: self.team_designs[ident] = state
        threading.Thread(target=work, daemon=True).start()
        return {"id": ident}

    def team_design_status(self, ident):
        with self._team_lock: return self.team_designs.get(ident, {"status": "missing"})

    def team_apply(self, body):
        current = self.engine.roles
        incoming = body.get("roles")
        if isinstance(incoming, dict):      # arayüz {anahtar: rol} gönderir; şef ayrıca korunduğu için atlanır
            incoming = [{**v, "key": v.get("key") or k} for k, v in incoming.items() if isinstance(v, dict) and not v.get("chief")]
        if not isinstance(incoming, list): raise ValueError("roles liste ya da sözlük olmalı")
        models = dict(current["models"])
        rows = {}
        if body.get("replace") is True:
            ck = rolestore.chief_key(current)
            rows = {ck: current["roles"][ck]} if ck else {}
        else:
            rows = dict(current["roles"])
        for role in incoming:
            if not isinstance(role, dict): raise ValueError("Rol nesne olmalı")
            key = role.get("key")
            for ref in role.get("models", []):
                if isinstance(ref, str) and ":" in ref:
                    rt, mid = ref.split(":", 1)
                    if rt not in ("codex", "claude", "agy", "opencode"): raise ValueError("Bilinmeyen runtime")
                    models.setdefault(ref, {"runtime":rt, "id":mid})
            rows[key] = {**role, "brief": role.get("description", role.get("brief", "")), "chief": False, "primary": False}
        clean = rolestore.save({"models": models, "roles": rows, "_note": current.get("_note", "")})
        self.engine.reload_roles()
        return {"roles": self.engine.roles["roles"]}

    def save_config(self, body):
        for k, v in body.items():
            if k in EDITABLE_CFG:
                self.cfg[k] = v
        config.save(self.cfg)

    # ---------- dosya (editör) ----------
    def read_file(self, path):
        p = Path(path)
        return {"path": str(p), "text": p.read_text(encoding="utf-8", errors="replace")}

    def write_file(self, body):
        p = Path(body["path"])
        p.write_text(body.get("text", ""), encoding="utf-8")
        return {"ok": True}

    def ls(self, path):
        p = Path(path or Path.cwd())
        items = []
        for c in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:500]:
            items.append({"name": c.name, "dir": c.is_dir()})
        return {"path": str(p), "items": items}


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        # --- yardımcılar ---
        def _host_ok(self):
            return (self.headers.get("Host") or "") in (f"127.0.0.1:{app.port}", f"localhost:{app.port}")

        def _auth(self, qs):
            tok = self.headers.get("X-Compade-Token") or (qs.get("token") or [""])[0]
            return self._host_ok() and secrets.compare_digest(tok, app.token)

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _json_body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 5_000_000:
                raise ValueError("istek çok büyük")
            return json.loads(self.rfile.read(n) or b"{}")

        # --- yönlendirme ---
        def do_GET(self):
            u = urlparse(self.path)
            qs = parse_qs(u.query)
            if u.path.startswith("/api/"):
                return self._api("GET", u.path, qs)
            if not self._host_ok():
                return self._send(403, b"Forbidden", "text/plain")
            rel = unquote(u.path).lstrip("/") or "index.html"
            if rel == "favicon.ico":
                return self._send(200, (config.PKG / "assets" / "compade.ico").read_bytes(), "image/x-icon")
            f = (WEB / rel).resolve()
            if WEB.resolve() not in f.parents and f != WEB.resolve() / "index.html" or not f.is_file():
                return self._send(404, b"Not found", "text/plain")
            data = f.read_bytes()
            if f.name == "index.html":
                inj = f'<script>window.__COMPADE__={{token:"{app.token}"}};</script>'.encode()
                data = data.replace(b"</head>", inj + b"</head>", 1) if b"</head>" in data else inj + data
            self._send(200, data, (mimetypes.guess_type(f.name)[0] or "application/octet-stream") + ("; charset=utf-8" if f.suffix in (".html", ".js", ".css", ".svg") else ""))

        def do_POST(self):
            u = urlparse(self.path)
            self._api("POST", u.path, parse_qs(u.query))

        def _api(self, method, path, qs):
            if not self._auth(qs):
                return self._send(403, {"error": "yetkisiz"})
            try:
                if method == "GET":
                    if path == "/api/state":
                        return self._send(200, app.state())
                    if path == "/api/runs":
                        return self._send(200, app.runs())
                    if path == "/api/run":
                        return self._send(200, app.run_detail((qs.get("id") or [""])[0]))
                    if path == "/api/file":
                        return self._send(200, app.read_file((qs.get("path") or [""])[0]))
                    if path == "/api/ls":
                        return self._send(200, app.ls((qs.get("path") or [""])[0]))
                    if path == "/api/roles":
                        return self._send(200, app.get_roles())
                    if path == "/api/costs":
                        days = max(1, min(365, int((qs.get("days") or ["7"])[0] or 7)))
                        return self._send(200, costs.aggregate(ledger.tail(20000), days, models=app.engine.roles["models"]))
                    if path == "/api/update":
                        return self._send(200, updater.check(force=(qs.get("force") or ["0"])[0] == "1"))
                    if path == "/api/catalog":
                        return self._send(200, catalog.catalog())
                    if path == "/api/team/design":
                        return self._send(200, app.team_design_status((qs.get("id") or [""])[0]))
                    if path == "/api/chat":
                        return self._send(200, app.sessions.get((qs.get("id") or [""])[0]).to_dict())
                    if path == "/api/chat/changes":
                        return self._send(200, app.sessions.changes((qs.get("id") or [""])[0]))
                    if path == "/api/chat/diff":
                        return self._send(200, app.sessions.diff((qs.get("id") or [""])[0], (qs.get("path") or [""])[0]))
                    if path == "/api/events":
                        return self._sse()
                else:
                    body = self._json_body()
                    routes = {"/api/run": app.run, "/api/account": app.account_action, "/api/account/add": app.add_account,
                              "/api/file": app.write_file, "/api/roles": app.save_roles,
                              "/api/chat": app.chat_message, "/api/chat/start": app.chat_start, "/api/chat/tool": app.chat_tool, "/api/chat/approve": app.chat_approve,
                              "/api/chat/reject": lambda b: app.sessions.reject(b.get("chat")),
                              "/api/chat/mode": lambda b: app.sessions.set_mode(b.get("chat"), b.get("mode")),
                              "/api/team/design": app.team_design, "/api/team/apply": app.team_apply,
                              "/api/chat/cancel": lambda b: app.sessions.cancel(b.get("chat"))}
                    routes["/api/chat/delete"] = lambda b: app.sessions.delete(b.get("chat"))
                    routes["/api/chat/apply"] = lambda b: app.sessions.apply(b.get("chat"), b.get("paths") or [])
                    routes["/api/chat/discard"] = lambda b: app.sessions.discard(b.get("chat"))
                    routes["/api/chat/rename"] = lambda b: app.sessions.rename(b.get("chat"), b.get("title"))
                    routes["/api/update/install"] = lambda b: updater.install()
                    if path in routes:
                        return self._send(200, routes[path](body))
                    if path == "/api/cancel":
                        app.engine.cancel_all()
                        return self._send(200, {"ok": True})
                    if path == "/api/config":
                        app.save_config(body)
                        return self._send(200, {"ok": True})
                self._send(404, {"error": "bilinmeyen uç"})
            except (ValueError, OSError, KeyError) as e:
                self._send(400, {"error": str(e)})
            except Exception as e:  # noqa
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

        def _sse(self):
            q = app.hub.add()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                self.wfile.write(b": hello\n\n")
                self.wfile.flush()
                while True:
                    try:
                        msg = q.get(timeout=10)
                        self.wfile.write(b"data: " + json.dumps(msg, ensure_ascii=False, default=str).encode("utf-8") + b"\n\n")
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                app.hub.remove(q)
    return H


def _close_stale_windows(prof):
    """Önceki çalıştırmadan kalan Compade pencerelerini (yalnız Compade'ın Edge profili) kapat.

    Aynı profil açıkken yeni --app isteği eski sürece düşüyor ve kullanıcı ölü sunucuya bağlı
    eski pencereyi ("Bağlantı kesildi") görüyordu.
    """
    if os.name != "nt":
        return
    needle = str(prof).replace("'", "''")
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $_.CommandLine -and "
          f"$_.CommandLine.Contains('{needle}') }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=10,
                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        time.sleep(0.5)
    except (OSError, subprocess.SubprocessError):
        pass


def find_edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft/Edge/Application/msedge.exe"
            if p.exists():
                return str(p)
    return shutil.which("msedge")


def run_web(open_window=True, port=0):
    app = App()
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    srv.daemon_threads = True
    app.port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{app.port}/"
    print(f"Compade arayüzü: {url}", flush=True)
    proc = None
    if open_window:
        edge = find_edge()
        if edge:
            prof = config.HOME / "edge-profile"
            _close_stale_windows(prof)
            proc = subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={prof}", "--no-first-run",
                                     "--no-default-browser-check", "--window-size=1360,860"])
        else:
            import webbrowser
            webbrowser.open(url)
    # pencere kapanınca (SSE bağlantısı kalmayınca) kapan
    start = time.time()
    try:
        while True:
            time.sleep(1.0)
            h = app.hub
            if h.ever and h.count() == 0 and time.time() - h.last_zero > 8:
                break
            if not h.ever and time.time() - start > 90:
                break
    except KeyboardInterrupt:
        pass
    app.engine.cancel_all()
    app.mon.stop()
    srv.shutdown()
    if proc and proc.poll() is None:
        proc.terminate()
    return 0
