"""Şef karar döngüsü: takılan/başarısız alt görev → şef kararı → plan ilerler (sahte motor)."""
import json
import threading
import time
import unittest
from pathlib import Path

from test_core import _TMP  # noqa: F401
from test_session import FakeEngine, Harness, PLAN, plan_reply

from compade import session  # noqa: E402


def decision(action, task="a", role="", message=""):
    return "Karar.\n```compade-decision " + json.dumps(
        {"action": action, "task": task, "role": role, "message": message}, ensure_ascii=False) + "```"


class SeqEngine(FakeEngine):
    """Rol başına sıralı durumlar: seq={'be': ['error', 'ok']} → ilk deneme hata, ikinci başarı."""
    def __init__(self, replies, seq=None):
        super().__init__(replies)
        self.seq = {k: list(v) for k, v in (seq or {}).items()}

    def run(self, task, jobs, cwd=None, write=False, name=None, on_event=None, run_dir=None, **kw):
        role = jobs[0]["role"]
        with self.lock:
            self.calls.append({"role": role, "task": task, "write": write})
            reply = self.replies.pop(0) if role == "sef" and self.replies else f"çıktı-{role}"
            status = self.seq[role].pop(0) if self.seq.get(role) else "ok"
        (Path(run_dir) / f"out-{jobs[0]['tag']}.md").write_text(reply, encoding="utf-8")
        return run_dir, [{"status": status, "tag": jobs[0]["tag"]}]


class H(Harness):
    def __init__(self, replies, seq=None):
        self.eng = SeqEngine(replies, seq)
        self.events = []
        self.cv = threading.Condition()
        self.s = session.Sessions(self.eng, self.on_event)


class TestDecisionLoop(unittest.TestCase):
    def wait(self, h, *kinds, timeout=10):
        with h.cv:
            ok = h.cv.wait_for(lambda: any(k in kinds for k, _ in h.events), timeout)
        self.assertTrue(ok, f"{kinds} gelmedi: {[k for k, _ in h.events]}")
        return next(d for k, d in h.events if k in kinds)

    def run_plan(self, h):
        cid = h.s.message(None, "iş")["chat"]
        self.wait(h, "plan_ready")
        h.s.approve(cid)
        return cid

    def statuses(self, h, cid):
        return {k: v["status"] for k, v in h.s.get(cid).tasks.items()}

    def chief_calls(self, h):
        return sum(1 for c in h.eng.calls if c["role"] == "sef")

    def test_done_never_calls_chief(self):
        h = H([plan_reply(PLAN), "özet"])
        cid = self.run_plan(h)
        self.wait(h, "chat_done")
        self.assertEqual(self.statuses(h, cid), {"a": "ok", "b": "ok"})
        self.assertNotIn("decision_start", [k for k, _ in h.events])
        self.assertEqual(self.chief_calls(h), 1)   # yalnız plan (özet kısa → şefsiz)

    def test_retry_then_success_continues_plan(self):
        h = H([plan_reply(PLAN), decision("retry", "a", message="testleri de çalıştır")], seq={"be": ["error", "ok"]})
        cid = self.run_plan(h)
        self.wait(h, "chat_done")
        self.assertEqual(self.statuses(h, cid), {"a": "ok", "b": "ok"})
        be = [c for c in h.eng.calls if c["role"] == "be"]
        self.assertEqual(len(be), 2)
        self.assertIn("Şefin düzeltmesi", be[1]["task"])
        self.assertIn("testleri de çalıştır", be[1]["task"])
        self.assertTrue(any(c["role"] == "qa" for c in h.eng.calls))   # bağımlı görev çalıştı
        d = next(d for k, d in h.events if k == "chief_decision")
        self.assertEqual(d["action"], "retry")

    def test_retry_limit_per_task(self):
        h = H([plan_reply(PLAN)] + [decision("retry", "a")] * 5, seq={"be": ["error"] * 5})
        cid = self.run_plan(h)
        self.wait(h, "chat_done")
        self.assertEqual(len([c for c in h.eng.calls if c["role"] == "be"]), 1 + session.MAX_TASK_RETRY)
        self.assertIn("decision_limit", [k for k, _ in h.events])
        self.assertEqual(self.statuses(h, cid), {"a": "error", "b": "skipped"})

    def test_chat_restart_limit(self):
        tasks = [{"id": f"t{i}", "role": "be", "instruction": "x", "write": False, "depends_on": []} for i in range(4)]
        plan = {"summary": "çok", "tasks": tasks}
        h = H([plan_reply(plan)] + [decision("retry", f"t{i}") for i in range(4) for _ in range(3)],
              seq={"be": ["error"] * 40})
        orig = session.MAX_CHAT_RESTARTS
        session.MAX_CHAT_RESTARTS = 3
        try:
            cid = self.run_plan(h)
            self.wait(h, "chat_done", timeout=20)
        finally:
            session.MAX_CHAT_RESTARTS = orig
        self.assertLessEqual(h.s.get(cid).restarts, 3)
        self.assertEqual(len([c for c in h.eng.calls if c["role"] == "be"]), 4 + 3)

    def test_reassign_runs_other_role(self):
        h = H([plan_reply(PLAN), decision("reassign", "a", role="qa", message="sen yaz")], seq={"be": ["error"]})
        cid = self.run_plan(h)
        self.wait(h, "chat_done")
        self.assertEqual(self.statuses(h, cid)["a"], "ok")
        qa = [c for c in h.eng.calls if c["role"] == "qa"]
        self.assertIn("sen yaz", qa[0]["task"])
        self.assertEqual(len(qa), 2)   # devralınan a + kendi b

    def test_reassign_to_unknown_or_chief_role_stops(self):
        h = H([plan_reply(PLAN), decision("reassign", "a", role="sef")], seq={"be": ["error"]})
        cid = self.run_plan(h)
        self.wait(h, "chat_done")
        self.assertIn("decision_error", [k for k, _ in h.events])
        self.assertEqual(self.statuses(h, cid), {"a": "error", "b": "skipped"})

    def test_continue_lets_dependents_run(self):
        h = H([plan_reply(PLAN), decision("continue", "a")], seq={"be": ["error"]})
        cid = self.run_plan(h)
        self.wait(h, "chat_done")
        self.assertEqual(self.statuses(h, cid), {"a": "continued", "b": "ok"})

    def test_abort_skips_rest(self):
        h = H([plan_reply(PLAN), decision("abort", "a")], seq={"be": ["error"]})
        cid = self.run_plan(h)
        self.wait(h, "chat_done")
        self.assertEqual(self.statuses(h, cid), {"a": "error", "b": "cancelled"})

    def test_blocked_report_with_ok_status_asks_chief(self):
        blocked = 'iş\n```compade-report {"status":"blocked","summary":"API anahtarı yok","files":[],"needs":"anahtar"}```'
        h = H([plan_reply(PLAN), decision("continue", "a")])
        orig_run = h.eng.run

        def run(task, jobs, **kw):
            rd, res = orig_run(task, jobs, **kw)
            if jobs[0]["role"] == "be":
                (Path(kw["run_dir"]) / f"out-{jobs[0]['tag']}.md").write_text(blocked, encoding="utf-8")
            return rd, res
        h.eng.run = run
        cid = self.run_plan(h)
        self.wait(h, "chat_done")
        rep = next(d for k, d in h.events if k == "task_report" and d["task"] == "a")
        self.assertEqual(rep["status"], "blocked")
        sef_prompt = [c for c in h.eng.calls if c["role"] == "sef"][-1]["task"]
        self.assertIn("API anahtarı yok", sef_prompt)
        self.assertEqual(self.statuses(h, cid)["a"], "continued")

    def test_ask_user_waits_for_reply_then_retries(self):
        h = H([plan_reply(PLAN), decision("ask_user", "a", message="Hangi veritabanı?"),
               decision("retry", "a", message="PostgreSQL kullan")], seq={"be": ["error", "ok"]})
        cid = self.run_plan(h)
        q = self.wait(h, "ask_user")
        self.assertEqual(q["question"], "Hangi veritabanı?")
        self.assertTrue(h.s.get(cid).awaiting_user)
        h.s.message(cid, "PostgreSQL")            # plan çalışırken yanıt kabul edilir
        self.wait(h, "chat_done")
        self.assertEqual(self.statuses(h, cid), {"a": "ok", "b": "ok"})
        sef_prompts = [c["task"] for c in h.eng.calls if c["role"] == "sef"]
        self.assertIn("Kullanıcı yanıtı: PostgreSQL", sef_prompts[-1])
        self.assertIn("PostgreSQL kullan", [c for c in h.eng.calls if c["role"] == "be"][-1]["task"])

    def test_cancel_while_waiting_for_user(self):
        h = H([plan_reply(PLAN), decision("ask_user", "a", message="?")], seq={"be": ["error"]})
        cid = self.run_plan(h)
        self.wait(h, "ask_user")
        h.s.cancel(cid)
        self.wait(h, "chat_done")
        self.assertEqual(self.statuses(h, cid)["b"], "cancelled")

    def test_no_decision_stops_task(self):
        h = H([plan_reply(PLAN), "karar yok"], seq={"be": ["error"]})
        cid = self.run_plan(h)
        self.wait(h, "chat_done")
        self.assertEqual(self.statuses(h, cid), {"a": "error", "b": "skipped"})


if __name__ == "__main__":
    unittest.main()
