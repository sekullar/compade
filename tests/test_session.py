"""Şef oturumu akışı: sahte motorla (gerçek model çağrısı yok)."""
import json
import tempfile
import threading
import threading
import unittest
from pathlib import Path

from test_core import _TMP  # noqa: F401

from compade import session  # noqa: E402

ROLES = {"models": {"codex": {"runtime": "codex"}},
         "roles": {"sef": {"name": "Şef", "brief": "plan", "models": ["codex"], "chief": True, "write": False},
                   "be": {"name": "Backend", "brief": "api", "models": ["codex"], "chief": False, "write": True},
                   "qa": {"name": "QA", "brief": "test", "models": ["codex"], "chief": False, "write": False}}}

PLAN = {"summary": "iki adım", "tasks": [
    {"id": "a", "role": "be", "instruction": "yaz", "write": True, "depends_on": []},
    {"id": "b", "role": "qa", "instruction": "test et", "write": False, "depends_on": ["a"]}]}


class FakeEngine:
    def __init__(self, replies, fail=()):
        self.roles = ROLES
        self.cfg = {"discuss_first": False}
        self.replies = list(replies)      # sıradaki model yanıtları
        self.fail = set(fail)
        self.calls = []
        self.tmp = Path(tempfile.mkdtemp())
        self.n = 0
        self.lock = threading.Lock()

    def plan(self, role_keys=(), model_keys=(), **kw):
        return [{"role": r, "model": "codex", "tag": f"{r}-codex"} for r in role_keys], []

    def make_run_dir(self, name):
        with self.lock:
            self.n += 1
            d = self.tmp / f"r{self.n}-{name}"
        d.mkdir()
        return d

    def run(self, task, jobs, cwd=None, write=False, name=None, on_event=None, run_dir=None, **kw):
        role = jobs[0]["role"]
        with self.lock:
            self.calls.append({"role": role, "task": task, "write": write})
            reply = self.replies.pop(0) if role == "sef" and self.replies else f"çıktı-{role}"
        status = "error" if role in self.fail else "ok"
        (Path(run_dir) / f"out-{jobs[0]['tag']}.md").write_text(reply, encoding="utf-8")
        return run_dir, [{"status": status, "tag": jobs[0]["tag"]}]

    def cancel_all(self):
        pass

    def cancel_run(self, run_id):
        self.cancelled_runs = getattr(self, "cancelled_runs", []) + [run_id]


def plan_reply(plan):
    return "Plan:\n```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```"


class Harness:
    def __init__(self, replies, fail=()):
        self.eng = FakeEngine(replies, fail)
        self.events = []
        self.cv = threading.Condition()
        self.s = session.Sessions(self.eng, self.on_event)

    def on_event(self, kind, d):
        with self.cv:
            self.events.append((kind, d))
            self.cv.notify_all()

    def wait(self, *kinds, timeout=10):
        with self.cv:
            ok = self.cv.wait_for(lambda: any(k in kinds for k, _ in self.events), timeout)
        self.assertTrue(ok, f"{kinds} gelmedi: {[k for k, _ in self.events]}") if hasattr(self, "assertTrue") else None
        return next(d for k, d in self.events if k in kinds)

    kinds = property(lambda self: [k for k, _ in self.events])


class TestSession(unittest.TestCase):
    def test_chat_history_summary_rename_delete_and_reload(self):
        h = Harness([])
        chat = session.Chat("history-test")
        chat.messages.append({"who": "kullanıcı", "text": "İlk istek başlığı", "ts": 10})
        chat.updated = 123
        h.s.chats[chat.id] = chat
        h.s._save(chat)
        summary = next(c for c in h.s.summaries() if c["id"] == chat.id)
        self.assertEqual(summary["title"], "İlk istek başlığı")
        self.assertEqual(summary["updated"], 10)
        loaded = session.Sessions(h.eng, lambda *_: None)
        self.assertEqual(loaded.get(chat.id).messages[0]["text"], "İlk istek başlığı")
        loaded.rename(chat.id, "Yeni başlık")
        self.assertEqual(next(c for c in loaded.summaries() if c["id"] == chat.id)["title"], "Yeni başlık")
        loaded.delete(chat.id)
        self.assertNotIn(chat.id, [c["id"] for c in loaded.summaries()])

    def test_chat_history_uses_latest_message_time_for_order(self):
        h = Harness([])
        older = session.Chat("20261115-180559-old1")
        older.updated = 9999999999
        older.messages.append({"who": "user", "text": "eski", "ts": 100})
        newer = session.Chat("20261115-180559-new1")
        newer.updated = 1
        newer.messages.append({"who": "user", "text": "yeni", "ts": 200})
        h.s.chats.update({older.id: older, newer.id: newer})
        rows = [c["id"] for c in h.s.summaries() if c["id"] in (newer.id, older.id)]
        self.assertEqual(rows, [newer.id, older.id])

    def test_chat_time_falls_back_to_id_timestamp(self):
        chat = session.Chat("20261115-180559-abcd")
        self.assertGreater(session.Sessions._chat_time(chat), 0)

    def wait(self, h, *kinds):
        with h.cv:
            ok = h.cv.wait_for(lambda: any(k in kinds for k, _ in h.events), 10)
        self.assertTrue(ok, f"{kinds} gelmedi: {h.kinds}")
        return next(d for k, d in h.events if k in kinds)

    def test_cancel_only_stops_own_chat_runs(self):
        h = Harness([plan_reply(PLAN), plan_reply(PLAN)])
        a = h.s.message(None, "bir")["chat"]
        self.wait(h, "plan_ready", "plan_error")
        h.events.clear()
        b = h.s.message(None, "iki")["chat"]
        self.wait(h, "plan_ready", "plan_error")
        own_a, own_b = set(h.s.get(a).run_ids), set(h.s.get(b).run_ids)
        self.assertTrue(own_a and own_b and not own_a & own_b)
        h.s.cancel(a)
        self.assertEqual(set(h.eng.cancelled_runs), own_a)

    def test_full_flow_manual_approval(self):
        h = Harness([plan_reply(PLAN), "Hepsi tamam."])
        cid = h.s.message(None, "bir şey yap")["chat"]
        ready = self.wait(h, "plan_ready", "plan_error")
        self.assertEqual(len(ready["plan"]["tasks"]), 2)
        self.assertFalse(ready["auto"])
        self.assertEqual(h.s.get(cid).state, "awaiting")
        h.s.approve(cid)
        self.wait(h, "chat_done")
        chat = h.s.get(cid)
        self.assertEqual({k: v["status"] for k, v in chat.tasks.items()}, {"a": "ok", "b": "ok"})
        self.assertIn("iki adım", chat.messages[-1]["text"])
        self.assertEqual(sum(1 for c in h.eng.calls if c["role"] == "sef"), 1)
        by_role = {c["role"]: c for c in h.eng.calls if c["role"] != "sef"}
        self.assertTrue(by_role["be"]["write"])
        self.assertFalse(by_role["qa"]["write"])
        self.assertIn("çıktı-be", by_role["qa"]["task"])    # bağımlı görev öncekinin çıktısını görür

    def test_auto_approval_runs_without_approve(self):
        h = Harness([plan_reply(PLAN), "ok"])
        cid = h.s.message(None, "x", approval="auto")["chat"]
        self.wait(h, "chat_done")
        self.assertEqual(h.s.get(cid).state, "done")

    def test_invalid_plan_retried_once_then_error(self):
        h = Harness(["json yok", "yine yok"])
        h.s.message(None, "x")
        d = self.wait(h, "plan_error")
        self.assertIn("geçersiz", d["error"])
        self.assertEqual(sum(1 for c in h.eng.calls if c["role"] == "sef"), 2)

    def test_invalid_then_valid(self):
        h = Harness(["saçma", plan_reply(PLAN)])
        h.s.message(None, "x")
        self.wait(h, "plan_ready", "plan_error")
        self.assertIn("plan_ready", h.kinds)
        self.assertIn("Önceki yanıtın geçersizdi", h.eng.calls[1]["task"])

    def test_question_only(self):
        h = Harness([plan_reply({"tasks": [], "question": "Hangi dil?"})])
        h.s.message(None, "x")
        d = self.wait(h, "plan_question")
        self.assertEqual(d["question"], "Hangi dil?")

    def test_failed_dependency_skips_dependent(self):
        h = Harness([plan_reply(PLAN), "özet"], fail={"be"})
        cid = h.s.message(None, "x")["chat"]
        self.wait(h, "plan_ready")
        h.s.approve(cid)
        self.wait(h, "chat_done")
        st = {k: v["status"] for k, v in h.s.get(cid).tasks.items()}
        self.assertEqual(st, {"a": "error", "b": "skipped"})
        self.assertFalse(any(c["role"] == "qa" for c in h.eng.calls))

    def test_drop_task_removes_dependents(self):
        h = Harness([plan_reply(PLAN), "özet"])
        cid = h.s.message(None, "x")["chat"]
        self.wait(h, "plan_ready")
        h.s.approve(cid, drop=["a"])
        self.wait(h, "chat_done")
        self.assertEqual({k: v["status"] for k, v in h.s.get(cid).tasks.items()}, {"a": "skipped", "b": "skipped"})

    def test_approve_without_plan_and_busy(self):
        h = Harness([plan_reply(PLAN)])
        cid = h.s.message(None, "x")["chat"]
        self.wait(h, "plan_ready")
        with self.assertRaises(ValueError):
            h.s.message(cid, "tekrar") if h.s.get(cid).state in ("planning", "running") else h.s.approve("yok")
        with self.assertRaises(ValueError):
            h.s.approve(cid + "x")

    def test_reject(self):
        h = Harness([plan_reply(PLAN)])
        cid = h.s.message(None, "x")["chat"]
        self.wait(h, "plan_ready")
        h.s.reject(cid)
        self.assertEqual(h.s.get(cid).state, "idle")
        with self.assertRaises(ValueError):
            h.s.approve(cid)

    def test_no_chief(self):
        h = Harness([])
        h.eng.roles = {"models": ROLES["models"], "roles": {"be": {**ROLES["roles"]["be"]}}}
        cid = h.s.message(None, "x")["chat"]
        d = self.wait(h, "ask_tool")
        self.assertEqual(d["chat"], cid)
        self.assertEqual([x["key"] for x in d["options"]], ["codex", "claude", "agy", "opencode"])

    def test_claude_chief_history_message_never_asks_tool(self):
        h = Harness([])
        h.eng.roles = {"models": {"claude": {"runtime": "claude", "id": "sonnet"}},
                       "roles": {"sef": {"name": "Şef", "models": ["claude"], "chief": True}}}
        old = session.Chat("claude-history")
        old.phase = "cc"
        old.messages = [{"who": "kullanıcı", "text": "Önceki istek"}, {"who": "şef", "text": "Devam edelim."}]
        h.s.chats[old.id] = old
        h.s._save(old)
        loaded = session.Sessions(h.eng, h.on_event)
        self.assertEqual(loaded.get(old.id).phase, "cc")
        entered = threading.Event()
        calls = []
        loaded._cc_thread = lambda *args, **kwargs: (calls.append(args), entered.set())
        loaded.message(old.id, "Bir iyileştirme fikrim daha var")
        self.assertTrue(entered.wait(2))
        self.assertEqual(calls[0][1], "sef")
        self.assertNotIn("ask_tool", [kind for kind, _ in h.events])

    def test_primary_role_direct_task(self):
        h = Harness([])
        h.eng.roles = {"models": ROLES["models"], "roles": {"be": {**ROLES["roles"]["be"], "primary": True}}}
        h.s.message(None, "do it")
        self.wait(h, "chat_done")
        self.assertEqual([x["role"] for x in h.eng.calls], ["be"])
        self.assertFalse(any(k.startswith("plan_") for k in h.kinds))

    def test_discuss_then_start_uses_brief_without_history(self):
        answer = 'Anladım.\n```json\n{"ready":false,"brief":"Kapsam: API değişikliği; yalnız backend."}\n```'
        h = Harness([answer, answer, plan_reply({"summary":"tek", "tasks":[
            {"id":"x", "role":"be", "instruction":"uygula", "write":True, "depends_on":[]} ]})])
        h.eng.cfg["discuss_first"] = True
        cid = h.s.message(None, "İlk istek") ["chat"]
        reply = self.wait(h, "discuss_reply")
        self.assertFalse(reply["ready"])
        self.assertEqual(h.s.get(cid).phase, "discuss")
        self.assertFalse(any("## Plan kuralları" in c["task"] for c in h.eng.calls))
        h.events.clear()
        h.s.message(cid, "yalnız backend")
        self.wait(h, "discuss_reply")
        discuss_calls = [c["task"] for c in h.eng.calls if c["role"] == "sef"]
        self.assertIn("Önceki özet", discuss_calls[1])
        self.assertIn("İlk istek", discuss_calls[1])
        h.s.start(cid)
        self.wait(h, "plan_ready", "plan_error")
        plan_call = [c["task"] for c in h.eng.calls if c["role"] == "sef"][-1]
        self.assertIn("Önceki konuşma özeti", plan_call)
        self.assertNotIn("İlk istek", plan_call)
        self.assertEqual(h.s.get(cid).phase, "plan")


if __name__ == "__main__":
    unittest.main()
