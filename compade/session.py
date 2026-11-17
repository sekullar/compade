"""Şef oturumu: kullanıcı mesajı → şefin planı → onay → alt rollerin çalışması → şefin özeti.

Olaylar (on_event(kind, data)): chat_user, plan_start, plan_ready, plan_question, plan_error, plan_run,
task_state, chat_summary, chat_done. Alt görevlerin kendi olayları (start/done/limit...) Engine'den gelir.
"""
import json
import sys
import os
import re
import threading
import time
import uuid
from pathlib import Path

from . import chief, config, ledger, rolestore, router, workspace
from .cc_chat import CCTurn

MAX_CONTEXT = 3000   # bağımlı görevin çıktısından sonrakine aktarılacak en çok karakter
MAX_RETRY = 1
MAX_TASK_RETRY = 2
MAX_CHAT_RESTARTS = 6
PLAN_WORDS = re.compile(r"planla|plan çıkar|başlat|ekibe ver|tamam yap|hadi yap|uygula", re.I)


class Chat:
    @property
    def plan(self):
        return self._plan

    @plan.setter
    def plan(self, value):
        old = getattr(self, "_plan", None)
        same = bool(old and value and [t.get("id") for t in old.get("tasks", [])] == [t.get("id") for t in value.get("tasks", [])]
                    and old.get("summary") == value.get("summary"))
        self._plan = value
        if value and not same:
            self.plan_at = sum(1 for m in self.messages if m.get("who") != "araç")

    def tasks_started(self):
        return any((t or {}).get("status") not in (None, "waiting") for t in self.tasks.values())

    def __init__(self, cid=None):
        self.id = cid or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.messages = []            # {"who": "kullanıcı"|"şef", "text": str, "ts": float}
        self.plan_at = None           # plan oluştuğunda sohbetteki ileti sayısı (kart akışta o yerde durur)
        self.plan = None              # son doğrulanmış plan
        self.questions = None         # şefin yanıt bekleyen soruları [{question, options, multi}]
        self.state = "idle"           # idle | planning | awaiting | running | done
        self.phase = "plan"
        self.brief = ""
        self.ready = False
        self.usage = {"manager_in": 0, "manager_out": 0, "worker_in": 0, "worker_out": 0}
        self.tasks = {}               # tid -> {"status","run","tag"}
        self.cancelled = False
        self.run_ids = set()          # bu sohbetin başlattığı motor çalışmaları (iptal yalnız bunları durdurur)
        self.cc_session_id = None
        self.cc_turn = None
        self.cc_mode = ""
        self.cc_usage = {"manager_real": {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0}}
        self.cwd = None
        self.restarts = 0
        self.awaiting_user = False
        self.retry_counts = {}
        self.updated = time.time()
        self.title = ""
        self.workspace = None         # workspace.Workspace (git worktree yalıtımı) ya da None
        self.changes = []             # birleştirme dalındaki değişen dosyalar (kullanıcı onayı bekler)
        self.applied = []             # kullanıcının kendi ağacına uyguladığı dosyalar

    def to_dict(self):
        return {"id": self.id, "messages": self.messages, "plan": self.plan, "state": self.state, "tasks": self.tasks,
                "phase": self.phase, "brief": self.brief, "ready": self.ready, "usage": {**self.usage, **self.cc_usage},
                "cc_session_id": self.cc_session_id, "cc_mode": self.cc_mode, "updated": self.updated, "title": self.title,
                "workspace": self.workspace.to_dict() if self.workspace else None, "changes": self.changes,
                "applied": self.applied, "questions": self.questions, "plan_at": self.plan_at}


class Sessions:
    def __init__(self, engine, on_event):
        self.engine = engine
        self.on_event = on_event
        self.chats = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        directory = config.HOME / "chats"
        try:
            for path in directory.glob("*.json"):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    chat = Chat(raw.get("id"))
                    for key in ("messages", "plan", "state", "tasks", "phase", "brief", "ready", "cc_session_id", "cc_mode", "updated", "title",
                                "changes", "applied", "questions", "plan_at"):
                        if key in raw:
                            setattr(chat, key, raw[key])
                    if raw.get("workspace"):
                        chat.workspace = workspace.Workspace.from_dict(raw["workspace"], chat.id)
                    if chat.state in ("running", "planning", "discussing"):
                        chat.state = "done"   # uygulama kapanırken yarım kalan iş
                    chat.updated = self._chat_time(chat, path.stat().st_mtime)
                    saved = raw.get("usage") or {}
                    chat.usage.update({k: v for k, v in saved.items() if isinstance(v, (int, float))})
                    if isinstance(saved.get("manager_real"), dict):
                        chat.cc_usage["manager_real"].update({k: v for k, v in saved["manager_real"].items() if isinstance(v, (int, float))})
                    plan_tasks = (chat.plan or {}).get("tasks") or []
                    if plan_tasks and chat.state == "idle" and all((chat.tasks.get(t["id"]) or {}).get("status", "waiting") == "waiting" for t in plan_tasks):
                        chat.state = "awaiting"   # onay bekleyen plan, hata yüzünden boşa düşmüş olabilir
                    self.chats[chat.id] = chat
                except (OSError, ValueError, TypeError):
                    continue
        except OSError:
            pass

    def summaries(self):
        result = []
        for chat in self.chats.values():
            first = next((m.get("text", "") for m in chat.messages if m.get("who") in ("kullanıcı", "user")), "Yeni sohbet")
            result.append({"id": chat.id, "title": getattr(chat, "title", "") or first[:40], "updated": self._chat_time(chat), "state": chat.state, "phase": chat.phase})
        return sorted(result, key=lambda c: c["updated"], reverse=True)

    @staticmethod
    def _chat_time(chat, fallback=None):
        if chat.messages and isinstance(chat.messages[-1], dict):
            message_time = chat.messages[-1].get("ts")
            if isinstance(message_time, (int, float)):
                return message_time
        if fallback is not None:
            return fallback
        match = re.match(r"^(\d{8})-(\d{6})-", str(chat.id))
        if match:
            try:
                return time.mktime(time.strptime("".join(match.groups()), "%Y%m%d%H%M%S"))
            except (ValueError, OverflowError):
                pass
        return getattr(chat, "updated", 0) or 0

    def delete(self, cid):
        chat = self.get(cid)
        if chat.state in ("planning", "discussing", "running"):
            raise ValueError("Çalışan sohbet silinemez.")
        if chat.workspace:
            try:
                chat.workspace.cleanup()
            except Exception:  # noqa
                pass
        del self.chats[cid]
        try:
            (config.HOME / "chats" / f"{cid}.json").unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": True}

    def rename(self, cid, title):
        chat = self.get(cid)
        title = str(title or "").strip()[:80]
        if not title:
            raise ValueError("Başlık boş olamaz.")
        chat.title = title
        self._save(chat)
        return {"ok": True, "title": title}

    # ---------- yardımcılar ----------
    def _emit(self, kind, chat, **data):
        try:
            self.on_event(kind, {"chat": chat.id, **data})
        except Exception:
            pass

    def _save(self, chat):
        try:
            chat.updated = time.time()
            d = config.HOME / "chats"
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{chat.id}.json"
            tmp = p.with_name(f"{chat.id}.{uuid.uuid4().hex[:6]}.tmp")
            tmp.write_text(json.dumps(chat.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, p)
        except OSError as e:
            print(f"[compade] sohbet kaydedilemedi ({chat.id}): {e}", file=sys.stderr)

    def get(self, cid):
        chat = self.chats.get(cid)
        if not chat:
            raise ValueError("Sohbet bulunamadı.")
        return chat

    def _chief(self):
        roles = self.engine.roles
        key = rolestore.chief_key(roles)
        if not key:
            raise ValueError("Şef rolü tanımlı değil. Rol ayarlarından bir rolü şef yap.")
        return key, roles["roles"]

    def _run_one(self, chat, label, role_key, task_text, cwd, write, route=None):
        """Tek rolü çalıştırır; (durum, çıktı metni, run_id) döner."""
        jobs, _ = self.engine.plan([role_key], [])
        if not jobs:
            raise ValueError(f"'{role_key}' rolünün modeli dış çalışan değil (yalnız Claude). Rol ayarlarından model seç.")
        if route and route.get("model"):
            jobs[0]["model"] = route["model"]
            jobs[0]["effort"] = route.get("effort")
        run_dir = self.engine.make_run_dir(f"{label}")
        chat.run_ids.add(run_dir.name)
        (run_dir / "title.txt").write_text(f"{label}: " + task_text.strip().splitlines()[0][:60], encoding="utf-8")
        _, results = self.engine.run(task_text, jobs, cwd=cwd, write=write, name=label,
                                     on_event=self.on_event, run_dir=run_dir)
        res = results[0] if results else {"status": "error", "tag": jobs[0]["tag"]}
        out = run_dir / f"out-{res.get('tag', jobs[0]['tag'])}.md"
        text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
        chief_key = rolestore.chief_key(self.engine.roles)
        prefix = "manager" if role_key == chief_key else "worker"
        prompt_chars = sum(len(p.read_text(encoding="utf-8", errors="replace")) for p in run_dir.glob("prompt-*.md"))
        chat.usage[prefix + "_in"] += prompt_chars or len(task_text)
        chat.usage[prefix + "_out"] += len(text)
        self._usage(chat)
        return res.get("status", "error"), text, run_dir.name

    def _usage(self, chat):
        self._emit("usage", chat, usage=dict(chat.usage), est_tokens=int(sum(v for v in chat.usage.values() if isinstance(v, (int, float))) / 3.6))

    # ---------- 1) planlama ----------
    def message(self, cid, text, cwd=None, files=(), approval="", direct=False):
        text = (text or "").strip()
        if not text:
            raise ValueError("Mesaj boş olamaz.")
        roles = self.engine.roles["roles"]
        key = rolestore.chief_key(self.engine.roles)
        primary = next((k for k, r in roles.items() if r.get("primary")), None)
        if cwd and not Path(cwd).is_dir():
            raise ValueError("Çalışma klasörü bulunamadı.")
        with self._lock:
            chat = self.chats.get(cid) if cid else None
            if not chat:
                chat = Chat()
                self.chats[chat.id] = chat
            reply_ev = getattr(chat, "_reply_event", None)
            if chat.awaiting_user and reply_ev is not None:
                chat.awaiting_user = False
                chat._reply = text
                chat.messages.append({"who": "kullanıcı", "text": text, "ts": time.time()})
                chat.questions = None
                chat.updated = time.time()
                self._emit("chat_user", chat, text=text)
                reply_ev.set()
                return {"chat": chat.id}
            if chat.state in ("planning", "discussing", "running"):
                raise ValueError("Önceki iş sürüyor; bitmesini ya da durdurmayı bekle.")
            if chat.awaiting_user:
                chat.awaiting_user = False
                chat.messages.append({"who": "kullanıcı", "text": text, "ts": time.time()})
                chat.questions = None
                chat.updated = time.time()
                chat.state = "planning"
                threading.Thread(target=self._cc_thread, args=(chat, key, "Kullanıcı yanıtı: " + text, cwd or chat.cwd, (), False), daemon=True).start()
                return {"chat": chat.id}
            discuss = bool(key and getattr(self.engine, "cfg", {}).get("discuss_first", True) and not direct)
            chief_model = (roles.get(key, {}).get("models") or [None])[0] if key else None
            claude_chief = bool(key and chief_model and self.engine.roles["models"].get(chief_model, {}).get("runtime") == "claude")
            if claude_chief:
                discuss = False
            chat.phase = "discuss" if discuss else "plan"
            chat.state, chat.cancelled = ("discussing" if discuss else "planning"), False
            chat.messages.append({"who": "kullanıcı", "text": text, "ts": time.time()})
            chat.questions = None
            chat.updated = time.time()
        self._emit("chat_user", chat, text=text)
        if key and discuss:
            self._emit("discuss_start", chat, chief=key)
            threading.Thread(target=self._discuss_thread, args=(chat, key, roles, text, cwd, list(files)), daemon=True).start()
        elif key and claude_chief:
            chat.cwd = cwd
            chat.phase = "cc"
            threading.Thread(target=self._cc_thread, args=(chat, key, text, cwd, files), daemon=True).start()
        elif key:
            threading.Thread(target=self._plan_thread, args=(chat, key, roles, text, cwd, list(files), approval, None), daemon=True).start()
        elif primary:
            threading.Thread(target=self._direct_thread, args=(chat, primary, text, cwd, list(files)), daemon=True).start()
        elif getattr(self.engine, "cfg", {}).get("default_tool"):
            tool = self.engine.cfg["default_tool"]
            model = {"codex":"codex", "claude":"claude", "agy":"gemini"}.get(tool)
            if tool == "opencode":
                model = next((k for k, v in self.engine.roles["models"].items() if v["runtime"] == "opencode"), None)
            threading.Thread(target=self._single_thread, args=(chat, None, text, cwd, model), daemon=True).start()
        else:
            self._emit("ask_tool", chat, options=[{"key":"codex","label":"Codex"},{"key":"claude","label":"Claude Code"},
                {"key":"agy","label":"Antigravity"},{"key":"opencode","label":"OpenCode","models":getattr(self.engine, "opencode_models", lambda: [])()}])
            chat.state = "awaiting_tool"
        return {"chat": chat.id}

    def start(self, cid, cwd=None):
        chat = self.get(cid)
        if chat.phase != "discuss" or not chat.brief or not any(m["who"] == "kullanıcı" for m in chat.messages):
            raise ValueError("Planı başlatmak için şefle konuşma ve özet gerekir.")
        if chat.state in ("discussing", "planning", "running"):
            raise ValueError("Şef yanıtlıyor, bekle.")
        chat.phase, chat.state = "plan", "planning"
        text = next(m["text"] for m in reversed(chat.messages) if m["who"] == "kullanıcı")
        key = rolestore.chief_key(self.engine.roles)
        threading.Thread(target=self._plan_thread, args=(chat, key, self.engine.roles["roles"], text, cwd, [], "", chat.brief), daemon=True).start()
        return {"ok": True}

    def _discuss_thread(self, chat, key, roles, text, cwd, files):
        try:
            prompt = chief.discuss_prompt(text, roles, key, chat.brief,
                [{"who": m["who"], "text": m["text"]} for m in chat.messages[:-1]], cwd or "", files)
            ref = getattr(self.engine, "cfg", {}).get("discuss_model", "")
            if ref:
                rt, mid = ref.split(":", 1) if ":" in ref else ("", "")
                model_key = ref
                if model_key not in self.engine.roles["models"] and rt:
                    self.engine.roles["models"][model_key] = {"runtime": rt, "id": mid}
                jobs, _ = self.engine.plan([], [model_key], as_role=key)
                if not jobs:
                    raise ValueError("Konuşma modeli çalıştırılamıyor.")
                rd = self.engine.make_run_dir("sef-sohbet")
                chat.run_ids.add(rd.name)
                _, results = self.engine.run(prompt, jobs, cwd=cwd, write=False, name="sef-sohbet", on_event=self.on_event, run_dir=rd)
                out = (rd / f"out-{jobs[0]['tag']}.md").read_text(encoding="utf-8", errors="replace")
                status = results[0].get("status", "error") if results else "error"
                prompt_chars = sum(len(p.read_text(encoding="utf-8", errors="replace")) for p in rd.glob("prompt-*.md"))
                chat.usage["manager_in"] += prompt_chars or len(prompt)
                chat.usage["manager_out"] += len(out)
                self._usage(chat)
            else:
                status, out, _ = self._run_one(chat, "sef-sohbet", key, prompt, cwd, False)
            if status != "ok":
                raise ValueError(f"Şef yanıt veremedi ({status}).")
            meta = chief.extract_discuss(out)
            text_out = chief._FENCE.sub("", out).strip()
            chat.brief, chat.ready = meta["brief"], meta["ready"]
            chat.messages.append({"who": "şef", "text": text_out, "ts": time.time()})
            chat.state = "idle"
            self._emit("discuss_reply", chat, text=text_out, ready=chat.ready, brief=chat.brief)
        except Exception as exc:
            chat.state = "idle"
            self._emit("discuss_error", chat, error=str(exc))
        self._save(chat)

    def _direct_thread(self, chat, role_key, text, cwd, files=()):
        self._single_thread(chat, role_key, text, cwd, files=files)

    def choose_tool(self, cid, tool, model=None, remember=False, cwd=None):
        chat = self.get(cid)
        if not isinstance(remember, bool):
            raise ValueError("remember true/false olmalı.")
        if model is not None and not isinstance(model, str):
            raise ValueError("model metin olmalı.")
        if chat.state != "awaiting_tool":
            raise ValueError("Araç seçimi bekleyen sohbet yok.")
        mapping = {"codex":"codex", "claude":"claude", "agy":"gemini"}
        if tool not in mapping and tool != "opencode":
            raise ValueError("Bilinmeyen araç.")
        mk = model if tool == "opencode" else mapping[tool]
        if tool == "opencode" and not mk:
            mk = next((k for k, v in self.engine.roles["models"].items() if v["runtime"] == "opencode"), None)
            if not mk:
                available = getattr(self.engine, "opencode_models", lambda: [])()
                mk = available[0] if available else None
        if tool == "opencode" and isinstance(mk, str) and mk not in self.engine.roles["models"]:
            self.engine.roles["models"][mk] = {"runtime": "opencode", "id": mk if "/" in mk else f"opencode/{mk}"}
        if mk not in self.engine.roles["models"] or self.engine.roles["models"][mk]["runtime"] != ("opencode" if tool == "opencode" else tool):
            raise ValueError("Araç modeli geçersiz.")
        if remember:
            if not hasattr(self.engine, "cfg"):
                raise ValueError("Yapılandırma kaydedilemiyor.")
            self.engine.cfg["default_tool"] = tool
            config.save(self.engine.cfg)
        text = next(m["text"] for m in reversed(chat.messages) if m["who"] == "kullanıcı")
        threading.Thread(target=self._single_thread, args=(chat, None, text, cwd, mk), daemon=True).start()
        return {"ok": True}

    def _single_thread(self, chat, role_key, text, cwd, model=None, files=()):
        chat.state = "running"
        try:
            if model and model not in self.engine.roles["models"]:
                self.engine.roles["models"][model] = {"runtime": "opencode", "id": model if "/" in model else f"opencode/{model}"}
            jobs, _ = self.engine.plan([role_key] if role_key else [], [model] if model else [])
            if not jobs:
                raise ValueError("Seçilen araç çalıştırılamıyor.")
            rd = self.engine.make_run_dir("chat-task")
            chat.run_ids.add(rd.name)
            role = self.engine.roles["roles"].get(role_key, {}) if role_key else {}
            workdir = str(Path(cwd or ".") / role["folder"]) if role.get("folder") else cwd
            if workdir and role.get("folder") and not Path(workdir).is_dir():
                workdir = cwd  # rol klasörü projede yok: proje köküne dön
            write = bool(role.get("write"))
            _, results = self.engine.run(text, jobs, cwd=workdir, write=write, files=files, on_event=self.on_event, run_dir=rd)
            body = (rd / f"out-{jobs[0]['tag']}.md").read_text(encoding="utf-8", errors="replace")
            chat.messages.append({"who":"asistan", "text":body, "ts":time.time()})
            chat.state = "done"
            self._usage(chat)
            self._emit("chat_summary", chat, text=body, result=results[0] if results else {})
        except Exception as e:
            chat.state = "idle"
            self._emit("plan_error", chat, error=str(e))
        self._emit("chat_done", chat, state=chat.state)
        self._save(chat)

    def _plan_thread(self, chat, key, roles, text, cwd, files, approval, brief=None):
        self._emit("plan_start", chat, chief=key)
        history = chat.messages[:-1][-8:]
        prompt = chief.plan_prompt(text, roles, key, history=[{"who": m["who"], "text": m["text"][:1500]} for m in history],
                                   cwd=cwd or "", files=files, brief=brief)
        plan, err = None, ""
        try:
            for attempt in range(MAX_RETRY + 1):
                extra = "" if not err else f"\n\n## Önceki yanıtın geçersizdi\n{err}\nPlanı düzeltip yeniden ver."
                status, out, _ = self._run_one(chat, "sef-plan", key, prompt + extra, cwd, False)
                if status != "ok":
                    raise ValueError(f"Şef yanıt veremedi ({status}).")
                try:
                    plan = chief.validate_plan(chief.extract_json(out), roles, key)
                    break
                except ValueError as e:
                    err = str(e)
            if plan is None:
                raise ValueError("Şefin planı geçersiz: " + err)
        except Exception as e:  # noqa
            chat.state = "idle"
            self._emit("plan_error", chat, error=str(e))
            self._save(chat)
            return
        chat.plan = plan
        if not plan["tasks"]:
            chat.state = "idle"
            chat.messages.append({"who": "şef", "text": plan["question"], "ts": time.time()})
            self._emit("plan_question", chat, question=plan["question"])
            self._save(chat)
            return
        chat.state = "awaiting"
        chat.messages.append({"who": "şef", "text": plan["summary"] or "Plan hazır.", "ts": time.time()})
        chat.tasks = {t["id"]: {"status": "waiting", "run": None, "tag": None} for t in plan["tasks"]}
        self._emit("plan_ready", chat, plan=plan, auto=(approval == "auto"))
        self._save(chat)
        if approval == "auto":
            self.approve(chat.id, cwd=cwd, user_text=text)

    # ---------- 2) onay → çalıştırma ----------
    def approve(self, cid, cwd=None, user_text=None, drop=()):
        chat = self.get(cid)
        with self._lock:
            if chat.state != "awaiting" or not chat.plan:
                raise ValueError("Onaylanacak plan yok.")
            chat.state = "running"
        plan = chat.plan
        if drop:    # kullanıcı bazı görevleri çıkardıysa bağımlı olanlar da çıkar
            gone = set(drop)
            changed = True
            while changed:
                changed = False
                for t in plan["tasks"]:
                    if t["id"] not in gone and gone & set(t["depends_on"]):
                        gone.add(t["id"])
                        changed = True
            plan = {**plan, "tasks": [t for t in plan["tasks"] if t["id"] not in gone]}
            plan["levels"] = chief.topo_levels(plan["tasks"])
            chat.plan = plan
            for g in gone:
                chat.tasks[g]["status"] = "skipped"
        utext = user_text or next((m["text"] for m in reversed(chat.messages) if m["who"] == "kullanıcı"), "")
        threading.Thread(target=self._run_thread, args=(chat, plan, cwd, utext), daemon=True).start()
        self._emit("plan_run", chat, tasks=[t["id"] for t in plan["tasks"]])
        return {"ok": True}

    def reject(self, cid):
        chat = self.get(cid)
        if chat.state == "awaiting":
            chat.state = "idle"
            chat.plan = None
            self._emit("chat_done", chat, state="rejected")
        return {"ok": True}

    def cancel(self, cid):
        chat = self.get(cid)
        chat.cancelled = True
        ev = getattr(chat, "_reply_event", None)
        if ev is not None:
            ev.set()
        if chat.cc_turn:
            chat.cc_turn.cancel()
        for rid in list(chat.run_ids):      # yalnız bu sohbetin işleri; diğer sohbetlere dokunma
            self.engine.cancel_run(rid)
        self._emit("chat_cancelled", chat)
        self._save(chat)
        return {"ok": True}

    def set_mode(self, cid, mode):
        if mode not in ("plan", "acceptEdits", "default"):
            raise ValueError("mode plan, acceptEdits veya default olmalı")
        chat = self.get(cid)
        if chat.state in ("planning", "discussing", "running"):
            raise ValueError("Şef yanıtlıyor")
        chat.cc_mode = mode
        self._save(chat)
        return {"ok": True, "mode": mode}

    def _cc_system(self, key):
        roles = self.engine.roles["roles"]
        compact = "; ".join(f"{k}: {r.get('name', k)} ({r.get('brief', '')[:100]})" for k, r in roles.items() if k != key)
        return (f"Compade şefisin ({roles[key].get('name', key)}). Kullanıcıyla Türkçe konuş. Roller: {compact}. "
                "ÖNEMLİ DAVRANIŞ: Kullanıcıyla sürekli sohbet halindesin. İlk mesajda ASLA hemen plan çıkarma: işi nasıl anladığını söyle, gerekirse 1-3 kısa soru sor, yaklaşım öner, kullanıcının fikrini al. Gerektiğinde projeyi salt okunur araçlarla incele. Plan bloğunu YALNIZ kullanıcı açıkça isterse ('planla', 'başlat', 'ekibe ver', 'tamam yap' gibi) ya da konuşmayla her şey netleştikten sonra 'Plan çıkarayım mı?' diye sorup onay alırsan ver. Plan istenince: yanıtın SONUNA tek ```compade-plan JSON bloğu ekle. Şema: "
                '{"summary":"...","question":"","tasks":[{"id":"t1","role":"rol-anahtarı","instruction":"...","write":false,"depends_on":[],"difficulty":"easy|medium|hard","verify":"npm run build","verify_dir":""}]} . '
                "verify (yalnız write=true görevde, isteğe bağlı): işin doğruluğunu gösteren derleme/test komutu (npm run build, npm test, python -m unittest...). "
                "Alt roller kısıtlı kum havuzunda çalışır, derleme/tarayıcı çalıştıramayabilir; Compade bu komutu iş bitince KENDİ çalıştırır. Komut alt klasördeyse verify_dir ver. "
                "difficulty dürüst olsun: model seçimi ona göre yapılır (kolay iş ucuz modele, zor iş güçlü modele). "
                "Dosya düzenleme ve alt rol işlerini kendin yapma; yalnız planla. "
                "SORU SORMA: kullanıcıdan cevap beklediğin her soruyu (netleştirme, seçim, onay) AskUserQuestion aracıyla DEĞİL, "
                "yanıtının SONUNA tek ```compade-questions JSON bloğuyla sor; arayüz bunu cevaplanabilir soru kartı yapar. Şema: "
                '[{"question":"...","options":["kısa seçenek","..."],"multi":false}] . '
                "En çok 4 soru; options isteğe bağlı (2-4 kısa seçenek; kullanıcı kendi cevabını da yazabilir); multi=true birden çok seçime izin verir. "
                "Soruları metinde ayrıca numaralı liste olarak tekrar etme; metinde yalnız bağlamı anlat.")

    def _cc_thread(self, chat, key, text, cwd, files, correction=False, sink=None):
        roles = self.engine.roles["roles"]
        model_key = (roles[key].get("models") or [""])[0]
        model = self.engine.roles["models"].get(model_key, {}).get("id", "default")
        prompt = text + (("\nEkli dosyalar: " + ", ".join(files)) if files else "")
        events = []
        def receive(event):
            for field in ("text", "content"):
                if field in event:
                    event[field] = CCTurn.normalize_text(event[field])
            event["chat"] = chat.id
            kind = event.pop("type", "")
            if kind == "cc_start" and event.get("session_id"):
                chat.cc_session_id = event["session_id"]
            if kind == "cc_result":
                usage = event.get("usage") or {}
                real = chat.cc_usage["manager_real"]
                for dst, src in (("in", "in"), ("out", "out"), ("cache_read", "cache_read"), ("cache_write", "cache_write")):
                    real[dst] += int(usage.get(src) or 0)
                real["cost_usd"] += float(event.get("cost_usd") or 0)
                try:
                    ledger.append({"run": f"chat-{chat.id}", "kind": "chief", "role": key, "model": model_key, "runtime": "claude",
                                   "status": "ok" if event.get("ok", True) else "error", "seconds": round(float(event.get("duration_ms") or 0) / 1000, 1),
                                   "tokens_in": int(usage.get("in") or 0), "tokens_out": int(usage.get("out") or 0),
                                   "cache_read": int(usage.get("cache_read") or 0), "cache_write": int(usage.get("cache_write") or 0),
                                   "cost_usd": float(event.get("cost_usd") or 0), "effort": effort})
                except Exception:  # noqa
                    pass
                self._emit("usage", chat, usage={**chat.usage, **chat.cc_usage}, est_tokens=int(sum(v for v in chat.usage.values() if isinstance(v, (int, float))) / 3.6))
            events.append((kind, dict(event)))
            if kind == "cc_tool" and event.get("name") == "AskUserQuestion":
                qs = chief.questions_from_tool(event.get("input"))
                if qs:
                    chat.questions = qs
                    self._save(chat)
                    self._emit("cc_questions", chat, questions=qs)
            if kind == "cc_tool":
                chat.messages.append({"who": "araç", "name": event.get("name"), "input": json.dumps(event.get("input", {}), ensure_ascii=False)[:240], "ok": None, "ts": time.time()})
            elif kind == "cc_tool_result":
                for message in reversed(chat.messages):
                    if message.get("who") == "araç" and message.get("ok") is None:
                        message["ok"] = bool(event.get("ok")); break
            if sink is None and kind in ("cc_result", "cc_error"):
                # durum, olay arayüze ulaşmadan önce güncel olsun (arayüz hemen yenilerse "meşgul" görmesin)
                chat.state = "awaiting" if kind == "cc_result" and chat.plan and chat.plan.get("tasks") and not chat.tasks_started() else "idle"
            self.on_event(kind, event)
            if sink is not None:
                if kind == "cc_assistant_done":
                    d = chief.parse_decision(event.get("raw_text", event.get("text", "")))
                    if d:
                        sink["decision"] = d
                elif kind in ("cc_result", "cc_error"):
                    final = event.get("text") or ""
                    if kind == "cc_result" and final:
                        chat.messages.append({"who": "şef", "text": final, "ts": time.time()})
                    if not sink.get("decision") and final:
                        sink["decision"] = chief.parse_decision(final)
                    self._save(chat)
                    sink["done"].set()
                return
            if kind == "cc_assistant_done":
                raw = event.get("raw_text", event.get("text", ""))
                match = re.search(r"```compade-plan\s*(\{.*?\})\s*```", raw, re.S)
                decision_match = re.search(r"```compade-decision\s*(\{.*?\})\s*```", raw, re.S)
                qs = chief.parse_questions(raw)
                if qs:
                    chat.questions = qs
                    self._save(chat)
                    self._emit("cc_questions", chat, questions=qs)
                if match:
                    try:
                        plan = chief.validate_plan(chief.extract_json(match.group(1)), roles, key)
                        chat.plan = plan
                        chat.tasks = {t["id"]: {"status": "waiting", "run": None, "tag": None} for t in plan["tasks"]}
                        self._emit("cc_plan", chat, plan=plan)
                        if plan["tasks"]:
                            chat.state = "awaiting"
                            self._emit("plan_ready", chat, plan=plan, auto=False)
                        elif plan.get("question"):
                            self._emit("plan_question", chat, question=plan["question"])
                    except ValueError as exc:
                        self._emit("cc_plan_invalid", chat, error=str(exc))
                        if not correction:
                            chat.state = "planning"
                            threading.Thread(target=self._cc_thread, args=(chat, key, f"plan geçersiz: {exc}; yalnız düzeltilmiş bloğu ver", cwd, (), True), daemon=True).start()
                if decision_match:
                    try:
                        decision = chief.parse_decision(decision_match.group(0))
                        if decision:
                            self._apply_decision(chat, decision, cwd)
                    except Exception:
                        pass
            elif kind == "cc_result":
                final = event.get("text") or ""
                if final:
                    chat.messages.append({"who": "şef", "text": final, "ts": time.time()})
                    self._save(chat)
                chat.state = "awaiting" if chat.plan and chat.plan.get("tasks") else "idle"
                self._save(chat)
            elif kind == "cc_error":
                chat.state = "awaiting" if chat.plan and chat.plan.get("tasks") and not chat.tasks_started() else "idle"
                self._save(chat)
        if sink is None:
            chat.state = "planning"
        mode = chat.cc_mode or self.engine.cfg.get("cc_permission_mode", "plan")
        allowed = self.engine.cfg.get("cc_allowed_tools") or ( ["Read", "Grep", "Glob"] if mode == "plan" else [])
        chat.cc_turn = CCTurn(timeout=int(self.engine.cfg.get("timeout", 600)))
        kind = "decision" if sink is not None else ("plan" if PLAN_WORDS.search(text or "") else "chat")
        effort = router.chief_effort(kind, self.engine.cfg.get("routing", "balanced"))
        chat.cc_turn.start(prompt, cwd, chat.cc_session_id, model, effort, mode, allowed,
                           receive, None if chat.cc_session_id else self._cc_system(key))

    def _apply_decision(self, chat, decision, cwd):
        """Plan dışı (sohbetten gelen) karar: yalnız ask_user/abort; yeniden çalıştırma plan döngüsünde (_decide)."""
        action = decision["action"]
        if action == "ask_user":
            chat.awaiting_user = True
            chat.state = "awaiting_user"
            self._emit("ask_user", chat, question=decision["message"])
        elif action == "abort":
            chat.cancelled = True
            chat.state = "idle"

    def _decide(self, chat, tid, role_key, report, extra=""):
        """Şeften senkron karar al (alt görev başarısız/takıldı). Karar dict'i ya da None."""
        key = rolestore.chief_key(self.engine.roles)
        if not key:
            return None
        others = ", ".join(k for k in self.engine.roles["roles"] if k != key)
        block = '```compade-decision {"action":"retry|reassign|ask_user|abort|continue","task":"...","role":"...","message":"..."}```'
        prompt = (f"Alt görev raporu: task={tid}, rol={role_key}, status={report['status']}, "
                  f"summary={report.get('summary', '')}, needs={report.get('needs', '')}."
                  f"{(' ' + extra) if extra else ''} "
                  f"Kalan hak: bu görev için {MAX_TASK_RETRY - chat.retry_counts.get(tid, 0)}, sohbette {MAX_CHAT_RESTARTS - chat.restarts}. "
                  f"Roller: {others}. Bir cümleyle açıkla, sonra tek {block} bloğu ver. "
                  "retry: aynı role düzeltilmiş talimatı message'a yaz; reassign: role alanına başka rol; "
                  "ask_user: message = kullanıcıya soru; continue: bu görevi atla, bağımlılar devam etsin; abort: planı durdur.")
        self._emit("decision_start", chat, task=tid, role=role_key, status=report["status"])
        decision = None
        try:
            models = self.engine.roles["roles"].get(key, {}).get("models") or []
            if models and self.engine.roles["models"].get(models[0], {}).get("runtime") == "claude":
                sink = {"done": threading.Event(), "decision": None}
                self._cc_thread(chat, key, prompt, chat.cwd, (), False, sink)
                sink["done"].wait(int(self.engine.cfg.get("timeout", 600)) + 30)
                decision = sink.get("decision")
            else:
                status, answer, _ = self._run_one(chat, "sef-karar", key, prompt, chat.cwd, False)
                decision = chief.parse_decision(answer) if status == "ok" else None
        except Exception as exc:  # noqa
            self._emit("decision_error", chat, task=tid, error=str(exc))
        if decision:
            self._emit("chief_decision", chat, task=tid, action=decision["action"],
                       role=decision.get("role", ""), message=decision.get("message", ""))
        return decision

    def _ask_user(self, chat, question, timeout=1800):
        """Plan sürerken kullanıcıya sor, yanıtı bekle (iptal ya da zaman aşımında None)."""
        ev = threading.Event()
        chat._reply_event, chat._reply = ev, None
        chat.awaiting_user = True
        chat.messages.append({"who": "şef", "text": question, "ts": time.time()})
        self._emit("ask_user", chat, question=question)
        self._save(chat)
        ev.wait(timeout)
        chat.awaiting_user = False
        chat._reply_event = None
        return None if chat.cancelled else chat._reply

    def _open_workspace(self, chat, plan, cwd):
        """Yazma görevi varsa ve proje bir git deposuysa yalıtılmış çalışma alanı aç."""
        if chat.workspace or not cwd or not self.engine.cfg.get("isolate", True):
            return chat.workspace
        roles = self.engine.roles["roles"]
        if not any(t["write"] and roles.get(t["role"], {}).get("write") for t in plan["tasks"]):
            return None
        try:
            chat.workspace = workspace.Workspace.create(cwd, chat.id)
        except Exception as exc:  # noqa
            self._emit("workspace_error", chat, error=str(exc)[:300])
            return None
        if chat.workspace:
            self._emit("workspace_ready", chat, branch=chat.workspace.branch, root=str(chat.workspace.root))
        else:
            self._emit("workspace_off", chat, reason="Proje bir git deposu değil (ya da hiç commit yok); roller doğrudan klasöre yazar.")
        return chat.workspace

    def _route(self, chat, tid, role_key, task, write):
        policy = self.engine.cfg.get("routing", "balanced")
        avoided = getattr(self.engine, "avoided", lambda mk: False)
        try:
            route = router.choose(self.engine.roles, role_key, task, policy, chat.retry_counts.get(tid, 0), write,
                                  usable=lambda mk: not avoided(mk))
        except Exception:  # noqa
            route = None
        if route:
            chat.tasks[tid].update(model=route["model"], effort=route["effort"], difficulty=route["difficulty"])
            self._emit("route", chat, task=tid, role=role_key, **route)
        return route

    @staticmethod
    def project_notes(cwd, limit=4000):
        """Projenin kalıcı hafızası: kökteki COMPADE.md (kurallar, komutlar, mimari notları)."""
        if not cwd:
            return ""
        p = Path(cwd) / "COMPADE.md"
        try:
            text = p.read_text(encoding="utf-8", errors="replace").strip() if p.is_file() else ""
        except OSError:
            return ""
        return text[:limit] + ("\n… (kısaltıldı)" if len(text) > limit else "")

    def _verify_cmd(self, wd):
        if not wd or not Path(wd).is_dir():
            return ""
        cmd = (self.engine.cfg.get("verify_cmd") or "").strip()
        if cmd.lower() in ("off", "kapalı", "-"):
            return ""
        return cmd or workspace.detect_verify(wd)

    def _verify_target(self, task, base):
        """Görevin kendi `verify` komutu (şef yazdı, izin listesinde) ve çalışacağı klasör; yoksa ('', '')."""
        cmd = str((task or {}).get("verify") or "").strip()
        cfg_cmd = (self.engine.cfg.get("verify_cmd") or "").strip().lower()
        if not cmd or not base or cfg_cmd in ("off", "kapalı", "-") or not workspace.safe_verify(cmd):
            return "", ""
        root = Path(base).resolve()
        d = root
        sub = str(task.get("verify_dir") or "").strip()
        if sub:
            d = (root / sub).resolve()
            try:
                d.relative_to(root)
            except ValueError:
                return "", ""
        return (cmd, str(d)) if d.is_dir() else ("", "")

    def _run_verify(self, chat, tid, cmd, vdir):
        verify = getattr(self.engine, "verify", None)
        if not (cmd and verify):
            return None
        self._emit("verify_start", chat, task=tid, cmd=cmd)
        try:
            res, tail = verify(cmd, vdir, int(self.engine.cfg.get("verify_timeout", 300)))
        except Exception as exc:  # noqa
            res, tail = "fail", str(exc)
        chat.tasks[tid]["verify"] = res
        self._emit("verify_result", chat, task=tid, ok=res == "pass", cmd=cmd, tail=(tail or "")[-1500:])
        return res, tail

    def _integrate(self, chat, ws, ws_lock, tid, wd, report, task=None):
        """Başarılı yazma görevi: commit → doğrulama → birleştirme. Rapor (gerekirse 'failed') döner."""
        files = []
        if ws:
            with ws_lock:
                files = ws.commit(tid, f"compade {tid}: {report.get('summary', '')[:120]}")
            chat.tasks[tid]["files"] = files
        cmd, vdir = self._verify_target(task, wd)
        if not cmd:
            cmd, vdir = self._verify_cmd(wd), wd
        if cmd and (files or not ws):
            got = self._run_verify(chat, tid, cmd, vdir)
            res, tail = got if got else ("pass", "")
            if res != "pass":
                if ws:
                    with ws_lock:
                        ws.drop_task(tid)
                return {"status": "failed", "summary": f"Doğrulama başarısız ({cmd}): {(tail or '')[-500:]}",
                        "files": [f["path"] for f in files], "needs": "Testleri geçirecek düzeltme"}
        if ws:
            with ws_lock:
                ok, conflicts = ws.merge(tid) if files else (True, [])
                ws.drop_task(tid)
            if not ok:
                self._emit("merge_conflict", chat, task=tid, files=conflicts)
                return {"status": "failed", "summary": "Birleştirme çakışması: " + ", ".join(conflicts[:8]),
                        "files": conflicts, "needs": "Güncel dalın üstünden yeniden yap"}
            if files:
                self._emit("task_merged", chat, task=tid, files=files)
        return report

    def _close_workspace(self, chat):
        ws = chat.workspace
        if not ws:
            return
        try:
            chat.changes = ws.changes()
        except Exception as exc:  # noqa
            self._emit("workspace_error", chat, error=str(exc)[:300])
            return
        if chat.changes:
            self._emit("changes_ready", chat, files=chat.changes, branch=ws.branch)
        elif not chat.applied:
            try:
                ws.cleanup()
            except Exception:  # noqa
                pass
            chat.workspace = None

    def _run_thread(self, chat, plan, cwd, user_text):
        by_id = {t["id"]: t for t in plan["tasks"]}
        outputs, results = {}, []
        lock = threading.Lock()
        ws_lock = threading.Lock()
        ws = self._open_workspace(chat, plan, cwd)
        notes = self.project_notes(cwd)

        def do(t):
            tid = t["id"]
            if chat.cancelled:
                return self._finish_task(chat, tid, "cancelled", "", None, results, t, lock)
            failed = [d for d in t["depends_on"] if chat.tasks[d]["status"] not in ("ok", "continued")]
            if failed:
                return self._finish_task(chat, tid, "skipped", f"Bağımlı görev başarısız: {', '.join(failed)}", None, results, t, lock)
            def dependency_context(d):
                raw = outputs[d]
                compact = chief.extract_summary(raw)
                return (compact or raw)[:MAX_CONTEXT]
            ctx = "".join(f"\n\n## Önceki görev çıktısı ({d})\n{dependency_context(d)}" for d in t["depends_on"] if d in outputs)
            if notes:
                ctx += "\n\n## Proje notları (COMPADE.md — uy)\n" + notes
            role_key, instruction, label, extra = t["role"], t["instruction"], f"{chat.id[-4:]}-{tid}", ""
            attempt = 0
            while True:
                chat.tasks[tid]["status"] = "running"
                self._emit("task_state", chat, id=tid, status="running")
                write, base = False, cwd
                try:
                    role = self.engine.roles["roles"][role_key]
                    write = bool(t["write"] and role.get("write"))
                    if ws and write:
                        attempt += 1
                        with ws_lock:
                            base = str(ws.sub(ws.task_tree(tid, attempt)))
                    elif ws:
                        base = str(ws.sub(ws.main))
                    wd = str(Path(base or ".") / role["folder"]) if role.get("folder") else base
                    if wd and role.get("folder") and not Path(wd).is_dir():
                        wd = base  # rol klasörü projede yok: proje köküne dön
                    route = self._route(chat, tid, role_key, {**t, "instruction": instruction}, write)
                    status, text, run_id = self._run_one(chat, label, role_key, instruction + ctx, wd, write, route)
                except Exception as e:  # noqa
                    status, text, run_id = "error", f"BAŞLATILAMADI: {e}", None
                report = self._report(status, text)
                if write and status == "ok" and report["status"] == "done" and not chat.cancelled:
                    try:
                        report = self._integrate(chat, ws, ws_lock, tid, base, report, t)
                    except Exception as e:  # noqa
                        report = {"status": "failed", "summary": f"Entegrasyon hatası: {e}", "files": [], "needs": ""}
                    if report["status"] != "done":
                        status = "error"
                elif ws and write:
                    with ws_lock:
                        ws.drop_task(tid)
                if write and not chat.cancelled and report["status"] in ("blocked", "needs_input") and t.get("verify"):
                    # işçi kum havuzunda doğrulayamadı: Compade kendi yetkisiyle çalıştırıp sonucu şefe iletir
                    vcmd, vdir = self._verify_target(t, base)
                    got = self._run_verify(chat, tid, vcmd, vdir) if vcmd else None
                    if got:
                        note = f"[Compade doğrulaması] `{vcmd}` → {'GEÇTİ' if got[0] == 'pass' else 'KALDI'}" + (f"\n{got[1][-400:]}" if got[0] != "pass" else "")
                        report = {**report, "summary": (report.get("summary", "") + "\n\n" + note)[:1500]}
                if report["status"] == "done" or chat.cancelled or not chat.plan:
                    break
                self._publish_report(chat, tid, role_key, report)
                if chat.restarts >= MAX_CHAT_RESTARTS or chat.retry_counts.get(tid, 0) >= MAX_TASK_RETRY:
                    self._emit("decision_limit", chat, task=tid, restarts=chat.restarts,
                               task_retries=chat.retry_counts.get(tid, 0))
                    break
                decision = self._decide(chat, tid, role_key, report, extra)
                extra = ""
                if decision and decision["action"] == "ask_user":
                    answer = self._ask_user(chat, decision.get("message") or report.get("needs") or "Nasıl devam edeyim?")
                    if answer is None:
                        break
                    decision = self._decide(chat, tid, role_key, report, f"Kullanıcı yanıtı: {answer}")
                    if decision and decision["action"] == "ask_user":
                        decision = None   # ikinci kez sormak yerine dur
                if not decision:
                    break
                act = decision["action"]
                if act == "abort":
                    chat.cancelled = True
                    break
                if act == "continue":
                    status = "continued"
                    break
                if act == "reassign":
                    new_role = decision.get("role")
                    if new_role not in self.engine.roles["roles"] or new_role == rolestore.chief_key(self.engine.roles):
                        self._emit("decision_error", chat, task=tid, error=f"Geçersiz rol: {new_role}")
                        break
                    role_key = t["role"] = new_role
                if act in ("retry", "reassign"):
                    with self._lock:   # paralel görevler aynı sayaca yazar: kontrol + artırma atomik
                        allowed = chat.restarts < MAX_CHAT_RESTARTS
                        if allowed:
                            chat.restarts += 1
                    if not allowed:
                        self._emit("decision_limit", chat, task=tid, restarts=chat.restarts,
                                   task_retries=chat.retry_counts.get(tid, 0))
                        break
                    if decision.get("message"):
                        instruction = t["instruction"] + "\n\n## Şefin düzeltmesi\n" + decision["message"]
                    chat.retry_counts[tid] = chat.retry_counts.get(tid, 0) + 1
                    label = f"{act}-{tid}-{chat.retry_counts[tid]}"
                    continue
                break
            self._finish_task(chat, tid, status, text, run_id, results, t, lock, report)
            outputs[tid] = text

        try:
            for level in plan["levels"]:
                ths = [threading.Thread(target=do, args=(by_id[i],), daemon=True) for i in level if i in by_id]
                for th in ths:
                    th.start()
                for th in ths:
                    th.join()
            self._summarize(chat, plan, results, user_text, cwd)
        finally:
            self._close_workspace(chat)
            chat.state = "done"
            self._emit("chat_done", chat, state="done")
            self._save(chat)

    @staticmethod
    def _report(status, text):
        report = chief.parse_report(text)
        if report is None:
            report = {"status": "failed" if status != "ok" or not (text or "").strip() else "done",
                      "summary": ((text or "").strip()[:300]), "files": [], "needs": ""}
        elif status != "ok" and report["status"] == "done":
            report["status"] = "failed"
        return report

    def _publish_report(self, chat, tid, role_key, report):
        chat.tasks[tid]["report"] = report
        self._emit("task_report", chat, task=tid, role=role_key, **report)

    def _finish_task(self, chat, tid, status, text, run_id, results, t, lock, report=None):
        if report is None:
            report = self._report(status, text)
        if status == "continued":
            report = {**report, "status": "continued"}
        elif status in ("skipped", "cancelled"):
            report = {**report, "status": status}    # çalışmadı: "başarısız" değil
        chat.tasks[tid].update(status=status, run=run_id)
        self._publish_report(chat, tid, t["role"], report)
        with lock:
            results.append({"id": tid, "role": t["role"], "status": status, "output": text})
        self._emit("task_state", chat, id=tid, status=status, run=run_id)

    # ---------- değişiklikler (kullanıcı onayı) ----------
    def _ws(self, cid):
        chat = self.get(cid)
        if not chat.workspace:
            raise ValueError("Bu sohbette incelenecek değişiklik yok.")
        return chat, chat.workspace

    def changes(self, cid):
        chat = self.get(cid)
        ws = chat.workspace
        if ws and chat.state != "running":
            try:
                chat.changes = ws.changes()
            except Exception:  # noqa
                pass
        return {"chat": cid, "files": chat.changes, "applied": chat.applied,
                "branch": ws.branch if ws else "", "root": str(ws.root) if ws else "", "isolated": bool(ws)}

    def diff(self, cid, path):
        chat, ws = self._ws(cid)
        if path not in {f["path"] for f in chat.changes}:
            raise ValueError("Dosya bu sohbetin değişikliklerinde yok.")
        return {"path": path, "diff": ws.file_diff(path)}

    def apply(self, cid, paths):
        chat, ws = self._ws(cid)
        if chat.state == "running":
            raise ValueError("Plan sürüyor; bitince uygula.")
        known = {f["path"] for f in chat.changes}
        paths = [p for p in (paths or known) if p in known and p not in chat.applied]
        res = ws.apply(paths)
        if res.get("ok"):
            chat.applied = sorted(set(chat.applied) | set(res.get("applied") or []))
            self._emit("changes_applied", chat, files=res.get("applied") or [], mode=res.get("mode"))
            if known <= set(chat.applied):
                self._drop_ws(chat)
        self._save(chat)
        return res

    def discard(self, cid):
        chat, _ = self._ws(cid)
        if chat.state == "running":
            raise ValueError("Plan sürüyor; önce durdur.")
        self._drop_ws(chat)
        chat.changes = []
        self._emit("changes_discarded", chat)
        self._save(chat)
        return {"ok": True}

    def _drop_ws(self, chat):
        try:
            chat.workspace.cleanup()
        except Exception as exc:  # noqa
            self._emit("workspace_error", chat, error=str(exc)[:300])
        chat.workspace = None

    # ---------- 3) özet ----------
    def _summarize(self, chat, plan, results, user_text, cwd):
        if chat.cancelled:
            return
        total = sum(len(r.get("output") or "") for r in results)
        if len(plan["tasks"]) == 1 or total <= 1500:
            lines = [plan.get("summary") or "Tamamlandı."]
            for r in results:
                summary = chief.extract_summary(r.get("output") or "") or (r.get("output") or "")
                lines.append(f"- {r['id']} ({r['status']}): {summary[:500]}")
            text = "\n".join(lines)
            chat.messages.append({"who": "şef", "text": text, "ts": time.time()})
            self._emit("chat_summary", chat, text=text)
            return
        try:
            key, _ = self._chief()
            status, text, _ = self._run_one(chat, "sef-ozet", key, chief.summary_prompt(user_text, plan, results), cwd, False)
            text = chief.extract_output(text) if status == "ok" else f"Şef özet yazamadı ({status}). Sonuçlar Çalışmalar sayfasında."
        except Exception as e:  # noqa
            text = f"Özet üretilemedi: {e}"
        chat.messages.append({"who": "şef", "text": text.strip(), "ts": time.time()})
        self._emit("chat_summary", chat, text=text.strip())
