"""İşe göre model seçimi."""
import threading
import unittest
from pathlib import Path

from test_core import _TMP  # noqa: F401
from test_session import FakeEngine, plan_reply

from compade import router, session  # noqa: E402
from compade.engine import Engine  # noqa: E402

ROLES = {"models": {
    "free": {"runtime": "opencode", "id": "opencode/glm-5.3-flash-free"},
    "luna": {"runtime": "codex", "id": "gpt-5.6-luna"},
    "big": {"runtime": "codex", "id": "gpt-6-luna"},
    "opus": {"runtime": "claude", "id": "opus"},
    "agy": {"runtime": "agy", "id": "claude-sonnet-4-6"},
    "custom": {"runtime": "opencode", "id": "x", "tier": "strong"}},
    "roles": {
        "sef": {"name": "Şef", "models": ["opus"], "chief": True},
        "dev": {"name": "Dev", "models": ["luna", "big", "free"], "write": True},
        "solo": {"name": "Tek", "models": ["luna"], "write": True},
        "pin": {"name": "Sabit", "models": ["free", "big"], "pin_model": True},
        "doc": {"name": "Doküman", "models": ["agy", "free"]}}}


class TestRouter(unittest.TestCase):
    def test_tiers(self):
        M = ROLES["models"]
        self.assertEqual(router.tier_of("free", M["free"]), "cheap")
        self.assertEqual(router.tier_of("luna", M["luna"]), "mid")
        self.assertEqual(router.tier_of("big", M["big"]), "strong")
        self.assertEqual(router.tier_of("opus", M["opus"]), "strong")
        self.assertEqual(router.tier_of("custom", M["custom"]), "strong")   # açık tier önceliklidir

    def test_difficulty(self):
        self.assertEqual(router.difficulty({"instruction": "x", "difficulty": "hard"}), "hard")
        self.assertEqual(router.difficulty({"instruction": "README'deki yazım hatalarını düzelt", "write": True}), "easy")
        self.assertEqual(router.difficulty({"instruction": "Kimlik doğrulamayı yeniden yapılandır, güvenlik açığını kapat", "write": True}), "hard")
        self.assertEqual(router.difficulty({"instruction": "Giriş formuna doğrulama ekle ve kaydet butonunu bağla", "write": True}), "medium")
        self.assertEqual(router.difficulty({"instruction": "Projeyi incele", "write": False}), "easy")

    def test_balanced_choices(self):
        hard = router.choose(ROLES, "dev", {"instruction": "x", "difficulty": "hard"}, "balanced", write=True)
        self.assertEqual((hard["model"], hard["effort"]), ("big", "high"))
        med = router.choose(ROLES, "dev", {"instruction": "x", "difficulty": "medium"}, "balanced", write=True)
        self.assertEqual((med["model"], med["effort"]), ("luna", "medium"))
        # yazma işi kolay olsa da ücretsiz modele gitmez
        easy_w = router.choose(ROLES, "dev", {"instruction": "x", "difficulty": "easy"}, "balanced", write=True)
        self.assertEqual(easy_w["model"], "luna")
        easy_r = router.choose(ROLES, "dev", {"instruction": "x", "difficulty": "easy"}, "balanced", write=False)
        self.assertEqual(easy_r["model"], "free")
        self.assertIsNone(easy_r["effort"])            # opencode düşünme seviyesi almaz

    def test_policies(self):
        t = {"instruction": "x", "difficulty": "hard"}
        self.assertEqual(router.choose(ROLES, "dev", t, "saver", write=True)["model"], "luna")
        self.assertEqual(router.choose(ROLES, "dev", {"instruction": "x", "difficulty": "medium"}, "quality", write=True)["model"], "big")
        self.assertIsNone(router.choose(ROLES, "dev", t, "off"))

    def test_retry_escalates(self):
        t = {"instruction": "x", "difficulty": "medium"}
        first = router.choose(ROLES, "dev", t, "balanced", attempt=0, write=True)
        again = router.choose(ROLES, "dev", t, "balanced", attempt=1, write=True)
        self.assertEqual((first["model"], again["model"]), ("luna", "big"))
        self.assertIn("yükseltildi", again["reason"])

    def test_single_pinned_and_unusable(self):
        self.assertEqual(router.choose(ROLES, "solo", {"instruction": "x", "difficulty": "hard"})["model"], "luna")
        self.assertEqual(router.choose(ROLES, "pin", {"instruction": "x", "difficulty": "hard"})["model"], "free")
        r = router.choose(ROLES, "dev", {"instruction": "x", "difficulty": "hard"}, write=True, usable=lambda mk: mk != "big")
        self.assertEqual(r["model"], "luna")             # limitli/kaçınılan model atlanır

    def test_chief_effort(self):
        self.assertEqual(router.chief_effort("plan"), "high")
        self.assertEqual(router.chief_effort("chat"), "medium")
        self.assertEqual(router.chief_effort("chat", "saver"), "low")
        self.assertIsNone(router.chief_effort("plan", "off"))


class TestEngineEffort(unittest.TestCase):
    def test_effort_flags(self):
        eng = Engine({"accounts": [], "limit_patterns": [], "refusal_patterns": []})
        eng.roles = ROLES
        pf = Path(_TMP) / "prompt-x.md"
        pf.write_text("görev", encoding="utf-8")
        cmd, *_ = eng.command("luna", pf, _TMP, False, [], None, "high")
        self.assertIn('model_reasoning_effort="high"', cmd)
        cmd, *_ = eng.command("luna", pf, _TMP, False, [], None)
        self.assertFalse(any("reasoning" in c for c in cmd))
        try:
            cmd, *_ = eng.command("opus", pf, _TMP, False, [], None, "low")
            self.assertEqual(cmd[cmd.index("--effort") + 1], "low")
        except FileNotFoundError:
            self.skipTest("claude CLI yok")


class RouteEngine(FakeEngine):
    def __init__(self, replies, seq):
        super().__init__(replies)
        self.roles = {"models": {**ROLES["models"], "codex": {"runtime": "codex"}},
                      "roles": {"sef": {"name": "Şef", "brief": "plan", "models": ["codex"], "chief": True},
                                "dev": {"name": "Dev", "brief": "kod", "models": ["luna", "big"], "write": True}}}
        self.cfg = {"discuss_first": False, "routing": "balanced", "isolate": False}
        self.seq = list(seq)
        self.jobs = []

    def run(self, task, jobs, **kw):
        with self.lock:
            if jobs[0]["role"] == "dev":
                self.jobs.append(dict(jobs[0]))
        rd, res = super().run(task, jobs, **kw)
        if jobs[0]["role"] == "dev" and self.seq:
            res[0]["status"] = self.seq.pop(0)
        return rd, res


class TestSessionRouting(unittest.TestCase):
    def test_routes_and_escalates_on_retry(self):
        plan = {"summary": "s", "tasks": [{"id": "a", "role": "dev", "instruction": "özellik ekle", "write": True,
                                           "depends_on": [], "difficulty": "medium"}]}
        retry = 'R\n```compade-decision {"action":"retry","task":"a","message":"tekrar"}```'
        eng = RouteEngine([plan_reply(plan), retry, "özet"], ["error", "ok"])
        events, cv = [], threading.Condition()

        def on(kind, d):
            with cv:
                events.append((kind, d))
                cv.notify_all()
        s = session.Sessions(eng, on)
        cid = s.message(None, "iş")["chat"]
        with cv:
            cv.wait_for(lambda: any(k == "plan_ready" for k, _ in events), 10)
        s.approve(cid, cwd=None)
        with cv:
            self.assertTrue(cv.wait_for(lambda: any(k == "chat_done" for k, _ in events), 10))
        self.assertEqual([(j["model"], j["effort"]) for j in eng.jobs], [("luna", "medium"), ("big", "high")])
        routes = [d for k, d in events if k == "route"]
        self.assertEqual(len(routes), 2)
        self.assertEqual(s.get(cid).tasks["a"]["model"], "big")


if __name__ == "__main__":
    unittest.main()
