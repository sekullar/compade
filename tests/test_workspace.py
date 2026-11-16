"""Git worktree yalıtımı: roller kullanıcının klasörüne değil kendi dallarına yazar; kullanıcı onaylayınca uygulanır."""
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from test_core import _TMP  # noqa: F401
from test_session import FakeEngine, plan_reply

from compade import session, workspace  # noqa: E402


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True).stdout


def make_repo():
    repo = Path(tempfile.mkdtemp()) / "proje"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "app.py").write_text("print('eski')\n", encoding="utf-8")
    (repo / "notlar.txt").write_text("bir\n", encoding="utf-8")
    git(repo, *workspace.GIT_ID, "add", "-A")
    git(repo, *workspace.GIT_ID, "commit", "-qm", "ilk")
    return repo


class WriteEngine(FakeEngine):
    """Yazma görevinde cwd'ye dosya yazar; verify sonucu ayarlanabilir."""
    def __init__(self, replies, edits, verify_seq=None):
        super().__init__(replies)
        self.edits = edits                    # role -> [(dosya, içerik), ...] (her çağrıda sıradaki)
        self.verify_seq = list(verify_seq or [])
        self.cwds = []
        self.cfg = {"discuss_first": False, "verify_cmd": "echo test"}

    def run(self, task, jobs, cwd=None, write=False, name=None, on_event=None, run_dir=None, **kw):
        role = jobs[0]["role"]
        with self.lock:
            app = Path(cwd) / "app.py" if cwd else None
            self.cwds.append((role, str(cwd), write, app.read_text(encoding="utf-8") if app and app.exists() else None))
            if write and self.edits.get(role):
                fname, content = self.edits[role].pop(0)
                (Path(cwd) / fname).write_text(content, encoding="utf-8")
        return super().run(task, jobs, cwd=cwd, write=write, name=name, on_event=on_event, run_dir=run_dir, **kw)

    def verify(self, cmd, cwd, timeout=300):
        with self.lock:
            return self.verify_seq.pop(0) if self.verify_seq else ("pass", "ok")


class H:
    def __init__(self, replies, edits, verify_seq=None, isolate=True):
        self.eng = WriteEngine(replies, edits, verify_seq)
        self.eng.cfg["isolate"] = isolate
        self.events = []
        self.cv = threading.Condition()
        self.s = session.Sessions(self.eng, self.on_event)

    def on_event(self, kind, d):
        with self.cv:
            self.events.append((kind, d))
            self.cv.notify_all()

    def kinds(self):
        return [k for k, _ in self.events]


PLAN2 = {"summary": "iki yazar", "tasks": [
    {"id": "a", "role": "be", "instruction": "app.py değiştir", "write": True, "depends_on": []},
    {"id": "b", "role": "be", "instruction": "yeni dosya", "write": True, "depends_on": ["a"]}]}


class TestWorkspace(unittest.TestCase):
    def wait(self, h, *kinds, timeout=15):
        with h.cv:
            ok = h.cv.wait_for(lambda: any(k in kinds for k in h.kinds()), timeout)
        self.assertTrue(ok, f"{kinds} gelmedi: {h.kinds()}")
        return next(d for k, d in h.events if k in kinds)

    def run(self, result=None):
        self.repo = make_repo()
        try:
            return super().run(result)
        finally:
            subprocess.run(["git", "worktree", "prune"], cwd=self.repo, capture_output=True)

    def start(self, h, plan=PLAN2):
        cid = h.s.message(None, "iş")["chat"]
        self.wait(h, "plan_ready")
        h.s.approve(cid, cwd=str(self.repo))
        self.wait(h, "chat_done")
        return cid

    def test_writes_go_to_isolated_branch_not_user_tree(self):
        h = H([plan_reply(PLAN2), "özet"], {"be": [("app.py", "print('yeni')\n"), ("yeni.py", "x = 1\n")]})
        cid = self.start(h)
        chat = h.s.get(cid)
        self.assertEqual({k: v["status"] for k, v in chat.tasks.items()}, {"a": "ok", "b": "ok"})
        self.assertEqual((self.repo / "app.py").read_text(encoding="utf-8"), "print('eski')\n")   # kullanıcı ağacı temiz
        self.assertFalse((self.repo / "yeni.py").exists())
        for role, cwd, write, _ in h.eng.cwds:
            if write:
                self.assertNotEqual(Path(cwd).resolve(), self.repo.resolve())
        self.assertEqual({f["path"] for f in chat.changes}, {"app.py", "yeni.py"})
        self.assertIn("changes_ready", h.kinds())
        self.assertEqual(len([k for k in h.kinds() if k == "task_merged"]), 2)
        # bağımlı görev, öncekinin birleştirilmiş halini görür
        b_seen = [seen for r, c, w, seen in h.eng.cwds if w][1]
        self.assertEqual(b_seen, "print('yeni')\n")

    def test_diff_apply_selected_then_rest_cleans_up(self):
        h = H([plan_reply(PLAN2), "özet"], {"be": [("app.py", "print('yeni')\n"), ("yeni.py", "x = 1\n")]})
        cid = self.start(h)
        d = h.s.diff(cid, "app.py")["diff"]
        self.assertIn("+print('yeni')", d)
        with self.assertRaises(ValueError):
            h.s.diff(cid, "../dışarı.txt")
        r = h.s.apply(cid, ["app.py"])
        self.assertTrue(r["ok"], r)
        self.assertEqual((self.repo / "app.py").read_text(encoding="utf-8"), "print('yeni')\n")
        self.assertFalse((self.repo / "yeni.py").exists())
        self.assertIsNotNone(h.s.get(cid).workspace)
        ws_dir = h.s.get(cid).workspace.dir
        h.s.apply(cid, ["yeni.py"])
        self.assertTrue((self.repo / "yeni.py").exists())
        self.assertIsNone(h.s.get(cid).workspace)     # hepsi uygulandı → temizlendi
        self.assertFalse(ws_dir.exists())
        self.assertNotIn("compade/", git(self.repo, "branch"))

    def test_discard_removes_branch_and_keeps_user_tree(self):
        h = H([plan_reply(PLAN2), "özet"], {"be": [("app.py", "print('yeni')\n"), ("yeni.py", "x = 1\n")]})
        cid = self.start(h)
        h.s.discard(cid)
        self.assertEqual(h.s.get(cid).changes, [])
        self.assertEqual((self.repo / "app.py").read_text(encoding="utf-8"), "print('eski')\n")
        self.assertNotIn("compade/", git(self.repo, "branch"))
        self.assertEqual(len(git(self.repo, "worktree", "list").strip().splitlines()), 1)

    def test_verify_fail_is_reported_and_not_merged(self):
        plan = {"summary": "tek", "tasks": [PLAN2["tasks"][0]]}
        h = H([plan_reply(plan), "karar yok"], {"be": [("app.py", "bozuk(\n")]}, verify_seq=[("fail", "SyntaxError")])
        cid = self.start(h, plan)
        chat = h.s.get(cid)
        self.assertEqual(chat.tasks["a"]["status"], "error")
        self.assertEqual(chat.tasks["a"]["verify"], "fail")
        v = next(d for k, d in h.events if k == "verify_result")
        self.assertFalse(v["ok"])
        self.assertIn("SyntaxError", chat.tasks["a"]["report"]["summary"])
        self.assertEqual(chat.changes, [])
        self.assertIsNone(chat.workspace)             # değişiklik yok → temizlendi

    def test_verify_fail_then_retry_passes(self):
        plan = {"summary": "tek", "tasks": [PLAN2["tasks"][0]]}
        retry = 'Düzelt.\n```compade-decision {"action":"retry","task":"a","message":"sözdizimini düzelt"}```'
        h = H([plan_reply(plan), retry, "özet"], {"be": [("app.py", "bozuk(\n"), ("app.py", "print('iyi')\n")]},
              verify_seq=[("fail", "SyntaxError"), ("pass", "ok")])
        cid = self.start(h, plan)
        chat = h.s.get(cid)
        self.assertEqual(chat.tasks["a"]["status"], "ok")
        self.assertEqual([f["path"] for f in chat.changes], ["app.py"])
        self.assertIn("+print('iyi')", h.s.diff(cid, "app.py")["diff"])

    def test_parallel_conflict_reported(self):
        plan = {"summary": "paralel", "tasks": [
            {"id": "a", "role": "be", "instruction": "x", "write": True, "depends_on": []},
            {"id": "b", "role": "be", "instruction": "y", "write": True, "depends_on": []}]}
        h = H([plan_reply(plan), "karar yok", "karar yok", "özet"],
              {"be": [("notlar.txt", "A\n"), ("notlar.txt", "B\n")]})
        cid = self.start(h, plan)
        st = sorted(v["status"] for v in h.s.get(cid).tasks.values())
        self.assertEqual(st, ["error", "ok"])
        self.assertIn("merge_conflict", h.kinds())

    def test_non_git_folder_writes_directly(self):
        folder = Path(tempfile.mkdtemp())
        plan = {"summary": "tek", "tasks": [PLAN2["tasks"][0]]}
        h = H([plan_reply(plan), "özet"], {"be": [("app.py", "yeni\n")]})
        cid = h.s.message(None, "iş")["chat"]
        self.wait(h, "plan_ready")
        h.s.approve(cid, cwd=str(folder))
        self.wait(h, "chat_done")
        self.assertIn("workspace_off", h.kinds())
        self.assertEqual((folder / "app.py").read_text(encoding="utf-8"), "yeni\n")

    def test_isolation_disabled_by_config(self):
        plan = {"summary": "tek", "tasks": [PLAN2["tasks"][0]]}
        h = H([plan_reply(plan), "özet"], {"be": [("app.py", "yeni\n")]}, isolate=False)
        self.start(h, plan)
        self.assertEqual((self.repo / "app.py").read_text(encoding="utf-8"), "yeni\n")

    def test_read_only_plan_opens_no_workspace(self):
        plan = {"summary": "oku", "tasks": [{"id": "a", "role": "qa", "instruction": "incele", "write": False, "depends_on": []}]}
        h = H([plan_reply(plan), "özet"], {})
        cid = self.start(h, plan)
        self.assertIsNone(h.s.get(cid).workspace)
        self.assertNotIn("workspace_ready", h.kinds())

    def test_workspace_persists_across_reload(self):
        h = H([plan_reply(PLAN2), "özet"], {"be": [("app.py", "print('yeni')\n"), ("yeni.py", "x = 1\n")]})
        cid = self.start(h)
        s2 = session.Sessions(h.eng, lambda *a: None)
        self.assertEqual({f["path"] for f in s2.changes(cid)["files"]}, {"app.py", "yeni.py"})
        s2.discard(cid)


class TestProjectNotes(TestWorkspace.__mro__[1]):
    def test_notes_injected_into_worker_prompt(self):
        d = Path(tempfile.mkdtemp())
        (d / "COMPADE.md").write_text("Testler: pytest. Türkçe yorum yaz.", encoding="utf-8")
        plan = {"summary": "oku", "tasks": [{"id": "a", "role": "qa", "instruction": "incele", "write": False, "depends_on": []}]}
        h = H([plan_reply(plan), "özet"], {})
        cid = h.s.message(None, "iş")["chat"]
        with h.cv:
            h.cv.wait_for(lambda: "plan_ready" in h.kinds(), 10)
        h.s.approve(cid, cwd=str(d))
        with h.cv:
            h.cv.wait_for(lambda: "chat_done" in h.kinds(), 10)
        qa = [c for c in h.eng.calls if c["role"] == "qa"][0]["task"]
        self.assertIn("Türkçe yorum yaz", qa)
        self.assertEqual(session.Sessions.project_notes(None), "")


class TestDetectVerify(unittest.TestCase):
    def test_detect(self):
        d = Path(tempfile.mkdtemp())
        self.assertEqual(workspace.detect_verify(d), "")
        (d / "tests").mkdir()
        (d / "tests" / "test_x.py").write_text("", encoding="utf-8")
        self.assertEqual(workspace.detect_verify(d), "python -m unittest discover -s tests")
        (d / "conftest.py").write_text("", encoding="utf-8")
        self.assertEqual(workspace.detect_verify(d), "python -m pytest -q")


if __name__ == "__main__":
    unittest.main()
