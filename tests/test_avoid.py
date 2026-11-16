"""avoid_models: kaçınılan model (ör. limiti dolan agy) başka dış model varsa seçilmez."""
import unittest

from test_core import _TMP  # noqa: F401

from compade.engine import Engine  # noqa: E402


class TestAvoid(unittest.TestCase):
    def engine(self, avoid):
        e = Engine()
        e.cfg["avoid_models"] = avoid
        e.roles = {"models": {"claude": {"runtime": "claude"}, "gemini": {"runtime": "agy"}, "codex": {"runtime": "codex"}},
                   "roles": {"a": {"name": "A", "models": ["gemini", "codex"]},
                             "b": {"name": "B", "models": ["claude", "gemini"]},
                             "c": {"name": "C", "models": ["claude", "codex"]}}}
        return e

    def test_default_unchanged(self):
        jobs, _ = self.engine([]).plan(["a"], [])
        self.assertEqual(jobs[0]["model"], "gemini")

    def test_avoid_picks_alternative(self):
        jobs, _ = self.engine(["gemini"]).plan(["a"], [])
        self.assertEqual(jobs[0]["model"], "codex")

    def test_avoid_last_resort_when_no_alternative(self):
        with self.assertRaises(ValueError):
            self.engine(["claude", "gemini"]).plan(["b"], [])

    def test_internal_first_role_uses_external_second(self):
        jobs, _ = self.engine(["gemini"]).plan(["c"], [])
        self.assertEqual(jobs[0]["model"], "claude")

    def test_fallback_never_uses_avoided_model(self):
        e = self.engine(["gemini"])
        e.cfg["fallback"] = {"codex": ["gemini"]}
        e.acc.available = lambda runtime: [None]
        calls = []
        e._attempt = lambda job, mk, account, ctx, handle: (calls.append(mk) or
            {"status": "ok", "model": mk, "body": "done " * 40, "chars": 200, "seconds": 0})
        events = []
        from compade.engine import Handle
        result = e.execute({"tag": "x", "model": "codex", "role": None},
                           {"run_dir": self._tmp_dir(), "task": "x", "cwd": ".", "write": False, "files": [], "timeout": 2},
                           Handle(), lambda kind, data: events.append((kind, data)))
        self.assertEqual(calls, ["codex"])
        self.assertFalse(any(kind == "fallback" for kind, _ in events))
        self.assertEqual(result["status"], "ok")

    def _tmp_dir(self):
        import tempfile
        from pathlib import Path
        return Path(tempfile.mkdtemp())


if __name__ == "__main__":
    unittest.main()
