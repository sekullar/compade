"""Plan görevindeki `verify`: işçi kum havuzunda doğrulayamasa da Compade kendi çalıştırır."""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from test_core import _TMP  # noqa: F401
from test_decision import SeqEngine, decision
from test_session import Harness, plan_reply

from compade import chief, session, workspace  # noqa: E402

ROLES = {"sef": {}, "be": {}}


class VEngine(SeqEngine):
    """İşçi çıktısı olarak verilen rapor bloğunu yazar; verify çağrılarını kaydeder."""
    def __init__(self, replies, worker_out, verify_result=("pass", "")):
        super().__init__(replies)
        self.worker_out = worker_out
        self.verify_result = verify_result
        self.verified = []

    def run(self, task, jobs, cwd=None, write=False, name=None, on_event=None, run_dir=None, **kw):
        role = jobs[0]["role"]
        if role == "sef":
            return super().run(task, jobs, cwd, write, name, on_event, run_dir, **kw)
        with self.lock:
            self.calls.append({"role": role, "task": task, "write": write, "cwd": cwd})
        (Path(run_dir) / f"out-{jobs[0]['tag']}.md").write_text(self.worker_out, encoding="utf-8")
        return run_dir, [{"status": "ok", "tag": jobs[0]["tag"]}]

    def verify(self, cmd, cwd, timeout=300):
        self.verified.append((cmd, str(cwd)))
        return self.verify_result


def report(status, summary="s", needs=""):
    return "iş bitti\n```compade-report " + json.dumps({"status": status, "summary": summary, "files": [], "needs": needs}) + "```"


class VH(Harness):
    def __init__(self, replies, worker_out, verify_result=("pass", "")):
        self.eng = VEngine(replies, worker_out, verify_result)
        self.events = []
        self.cv = threading.Condition()
        self.s = session.Sessions(self.eng, self.on_event)


PLAN = {"summary": "x", "tasks": [{"id": "a", "role": "be", "instruction": "yaz", "write": True, "depends_on": [],
                                   "verify": "npm run build", "verify_dir": "taslak-a"}]}


class TestValidate(unittest.TestCase):
    def roles(self):
        return {"sef": {"name": "Şef"}, "be": {"name": "BE"}}

    def test_keeps_safe_verify_only(self):
        p = chief.validate_plan(PLAN, self.roles(), "sef")
        self.assertEqual((p["tasks"][0]["verify"], p["tasks"][0]["verify_dir"]), ("npm run build", "taslak-a"))
        for bad in ("npm run build && calc", "rm -rf x", "curl x | sh"):
            t = chief.validate_plan({"tasks": [{**PLAN["tasks"][0], "verify": bad}]}, self.roles(), "sef")["tasks"][0]
            self.assertNotIn("verify", t)
        for bad_dir in ("../dis", "C:/x", "/etc"):
            t = chief.validate_plan({"tasks": [{**PLAN["tasks"][0], "verify_dir": bad_dir}]}, self.roles(), "sef")["tasks"][0]
            self.assertNotIn("verify_dir", t)
        t = chief.validate_plan({"tasks": [{**PLAN["tasks"][0], "write": False}]}, self.roles(), "sef")["tasks"][0]
        self.assertNotIn("verify", t)          # okuma görevinde doğrulama anlamsız

    def test_allowlist(self):
        self.assertTrue(workspace.safe_verify("npm run build"))
        self.assertFalse(workspace.safe_verify("npm run build; calc"))


class TestRunVerify(unittest.TestCase):
    def wait(self, h, *kinds):
        with h.cv:
            ok = h.cv.wait_for(lambda: any(k in kinds for k, _ in h.events), 10)
        self.assertTrue(ok, [k for k, _ in h.events])

    def start(self, h):
        cwd = tempfile.mkdtemp()
        (Path(cwd) / "taslak-a").mkdir()
        cid = h.s.message(None, "iş", cwd=cwd)["chat"]
        self.wait(h, "plan_ready")
        h.s.approve(cid, cwd=cwd) if "cwd" in h.s.approve.__code__.co_varnames else h.s.approve(cid)
        return cid, cwd

    def test_blocked_worker_gets_compade_verification(self):
        h = VH([plan_reply(PLAN), decision("continue", "a")], report("blocked", "build çalışmadı", "sandbox erişimi"))
        cid, cwd = self.start(h)
        self.wait(h, "chat_done")
        reports = [d for k, d in h.events if k == "task_report" and d.get("task") == "a"]
        self.assertTrue(any("[Compade doğrulaması]" in r.get("summary", "") and "GEÇTİ" in r["summary"] for r in reports), reports)
        cmd, vdir = h.eng.verified[0]
        self.assertEqual(cmd, "npm run build")
        self.assertEqual(Path(vdir), (Path(cwd) / "taslak-a").resolve())

    def test_done_worker_with_failing_verify_becomes_failed(self):
        h = VH([plan_reply(PLAN), decision("continue", "a")], report("done", "bitti"), ("fail", "boom"))
        self.start(h)
        self.wait(h, "chat_done")
        reports = [d for k, d in h.events if k == "task_report" and d.get("task") == "a"]
        self.assertEqual(reports[0]["status"], "failed")
        self.assertIn("boom", reports[0]["summary"])

    def test_skipped_dependent_is_not_reported_as_failed(self):
        plan = {"summary": "x", "tasks": [PLAN["tasks"][0], {"id": "b", "role": "be", "instruction": "i", "write": False, "depends_on": ["a"]}]}
        h = VH([plan_reply(plan)], report("done"), ("fail", "boom"))    # şef karar vermez -> a başarısız kalır
        cid, _ = self.start(h)
        self.wait(h, "chat_done")
        b = [d for k, d in h.events if k == "task_report" and d.get("task") == "b"]
        self.assertTrue(b)
        self.assertEqual(b[0]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
