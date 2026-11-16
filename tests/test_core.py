"""Compade çekirdek testleri. Gerçek hesaplara ve gerçek agy kimliğine DOKUNMAZ:
- COMPADE_HOME geçici klasöre alınır
- agy kimlik kayıt adları sahte (compade:test:*) adlarla değiştirilir
Çalıştır:  python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="compade-test-")
os.environ["COMPADE_HOME"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compade import accounts as acc_mod  # noqa: E402
from compade import config, ledger, limits, wincred  # noqa: E402
from compade.engine import Engine  # noqa: E402

PAT = config.DEFAULTS["limit_patterns"]


class TestLimits(unittest.TestCase):
    def test_wait_parse(self):
        self.assertEqual(limits.parse_wait_seconds("Rate limit hit. Try again in 2h 30m."), 9000)
        self.assertEqual(limits.parse_wait_seconds("please retry after 45 minutes"), 2700)
        self.assertEqual(limits.parse_wait_seconds("try again in 1 day 2 hours"), 86400 + 7200)
        self.assertIsNone(limits.parse_wait_seconds("quota exceeded"))
        self.assertIsNone(limits.parse_wait_seconds(""))

    def test_limit_detect(self):
        for t in ("You've hit your usage limit.", "429 Too Many Requests", "RESOURCE_EXHAUSTED: quota", "rate limit reached",
                  "Error: exceeded your current quota"):
            self.assertTrue(limits.is_limit_error(t, PAT), t)
        for t in ("Dosya bulunamadı", "syntax error near line 4", "", None):
            self.assertFalse(limits.is_limit_error(t, PAT), t)

    def test_codex_rate_limits_and_exhaustion(self):
        home = Path(_TMP) / "cx-home"
        d = home / "sessions" / "2026" / "11" / "14"
        d.mkdir(parents=True)
        now = int(time.time())
        ev = {"type": "event_msg", "payload": {"type": "token_count", "info": None, "rate_limits": {
            "primary": {"used_percent": 99.0, "window_minutes": 300, "resets_at": now + 3600},
            "secondary": {"used_percent": 40.0, "window_minutes": 10080, "resets_at": now + 86400},
            "plan_type": "plus", "rate_limit_reached_type": None}}}
        (d / "rollout-x.jsonl").write_text(json.dumps({"type": "other"}) + "\n" + json.dumps(ev) + "\n", encoding="utf-8")
        info = limits.codex_rate_limits(home)
        self.assertEqual(info["plan"], "plus")
        self.assertEqual(len(info["windows"]), 2)
        ex, reset = limits.codex_exhausted(info, 98)
        self.assertTrue(ex)
        self.assertEqual(reset, now + 3600)
        ex2, _ = limits.codex_exhausted(info, 99.5)
        self.assertFalse(ex2)
        # sıfırlanma zamanı geçmişse artık dolu sayılmaz
        info["windows"][0]["resets_at"] = now - 5
        self.assertFalse(limits.codex_exhausted(info, 98)[0])
        self.assertIsNone(limits.codex_rate_limits(Path(_TMP) / "yok"))


class TestWincred(unittest.TestCase):
    def test_roundtrip(self):
        t = "compade:test:roundtrip"
        wincred.delete(t)
        self.assertIsNone(wincred.read(t))
        blob = bytes(range(256)) * 4  # 1024 bayt, sıfır baytlar dahil
        wincred.write(t, blob, "kullanici")
        got = wincred.read(t)
        self.assertEqual(got["blob"], blob)
        self.assertEqual(got["user"], "kullanici")
        self.assertTrue(wincred.exists(t))
        wincred.delete(t)
        self.assertFalse(wincred.exists(t))


def _mk_config(n_codex=2, n_agy=0):
    cfg = json.loads(json.dumps(config.DEFAULTS))
    cfg["accounts"] = []
    for i in range(n_codex):
        home = Path(_TMP) / f"codex-acc-{i}-{time.time_ns()}"
        home.mkdir(parents=True)
        (home / "auth.json").write_text("{}", encoding="utf-8")   # içerik önemsiz: yalnız "giriş var" sayılır
        cfg["accounts"].append({"id": f"codex-{i + 1}", "provider": "codex", "label": f"C{i + 1}", "home": str(home)})
    for i in range(n_agy):
        cfg["accounts"].append({"id": f"agy-{i + 1}", "provider": "agy", "label": f"A{i + 1}"})
    return cfg


class TestFailover(unittest.TestCase):
    def setUp(self):
        config.STATE.unlink(missing_ok=True)       # testler arası bekleme durumu sızmasın
        self.eng = Engine(_mk_config(2))
        self.events = []
        self.job = {"tag": "t1", "role": None, "model": "codex"}
        self.ctx = {"run_dir": Path(tempfile.mkdtemp(dir=_TMP)), "task": "x", "cwd": Path(_TMP), "write": False,
                    "files": [], "timeout": 5}

    def _run(self):
        from compade.engine import Handle
        return self.eng.execute(self.job, self.ctx, Handle(), lambda k, d: self.events.append((k, d)))

    def test_switches_account_on_limit(self):
        calls = []

        def fake(job, mk, account, ctx, handle):
            calls.append(account["id"])
            if account["id"] == "codex-1":
                return {"status": "error", "model": mk, "account": account["id"], "limit": True,
                        "err": "You've hit your usage limit. Try again in 3h.", "body": "", "chars": 0, "seconds": 1}
            return {"status": "ok", "model": mk, "account": account["id"], "body": "tamam " * 40, "chars": 240, "seconds": 1}
        self.eng._attempt = fake
        res = self._run()
        self.assertEqual(calls, ["codex-1", "codex-2"])
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["account"], "codex-2")
        self.assertIn("limit", " ".join(res["notes"]))
        self.assertTrue(any(k == "limit" for k, _ in self.events))
        st = self.eng.acc._st("codex-1")
        self.assertGreater(st["cooldown_until"], time.time() + 3 * 3600 - 60)   # "3h" okundu
        # bekleyen hesap bir sonraki işte atlanır
        self.assertEqual([a["id"] for a in self.eng.acc.available("codex")], ["codex-2"])

    def test_all_exhausted_reports_limit(self):
        self.eng.cfg["fallback"] = {}
        self.eng._attempt = lambda job, mk, account, ctx, handle: {
            "status": "error", "model": mk, "account": account["id"], "limit": True, "err": "rate limit", "body": "",
            "chars": 0, "seconds": 0}
        res = self._run()
        self.assertEqual(res["status"], "limit")
        self.assertEqual(self.eng.acc.available("codex"), [])


    def test_command_and_write_mode_use_claude_cli(self):
        from unittest.mock import patch
        eng = Engine(_mk_config(0))
        eng.roles = {"models": {"claude": {"runtime": "claude"}}, "roles": {}}
        run_dir = Path(tempfile.mkdtemp(dir=_TMP))
        prompt = run_dir / "prompt-claude.md"
        prompt.write_text("istem", encoding="utf-8")
        captured = {}

        def fake_run(cmd, env, stdin, cwd, timeout, handle):
            captured.update(cmd=cmd, cwd=cwd, stdin=stdin)
            return "ok", "Yanıt " * 40, "", 0

        eng._run_process = fake_run
        ctx = {"run_dir": run_dir, "task": "iş", "cwd": Path(_TMP), "write": True, "files": [], "timeout": 5}
        with patch("compade.engine.exe_claude", return_value="claude-test"):
            result = eng._attempt({"tag": "claude", "role": None}, "claude", None, ctx, object())
        self.assertEqual(captured["cmd"][:4], ["claude-test", "-p", "--output-format", "text"])
        self.assertEqual(captured["stdin"], prompt.read_text(encoding="utf-8"))   # uzun istem komut satırına girmez
        self.assertEqual(captured["cmd"][-2:], ["--permission-mode", "acceptEdits"])
        self.assertEqual(captured["cwd"], Path(_TMP))
        self.assertEqual(result["status"], "ok")

    def test_claude_usage_limit_is_classified(self):
        eng = Engine(_mk_config(0))
        status, limit, _ = eng.classify("error", "Usage limit reached", "5-hour limit")
        self.assertEqual((status, limit), ("limit", True))

    def test_non_limit_error_does_not_switch(self):
        calls = []

        def fake(job, mk, account, ctx, handle):
            calls.append(account["id"])
            return {"status": "error", "model": mk, "account": account["id"], "limit": False, "err": "syntax", "body": "x",
                    "chars": 1, "seconds": 0}
        self.eng._attempt = fake
        res = self._run()
        self.assertEqual(calls, ["codex-1"])     # limit olmayan hatada hesap değiştirme
        self.assertEqual(res["status"], "error")

    def test_fallback_to_other_provider_but_not_free_model_when_writing(self):
        self.eng.cfg["fallback"] = {"codex": ["gemini", "glm"]}
        self.eng.acc.mark_limit("codex-1", "limit")
        self.eng.acc.mark_limit("codex-2", "limit")
        used = []

        def fake(job, mk, account, ctx, handle):
            used.append(mk)
            return {"status": "ok", "model": mk, "account": account["id"] if account else None, "body": "ok " * 80,
                    "chars": 240, "seconds": 0}
        self.eng._attempt = fake
        # agy hesabı yok -> gemini atlanır; yazma kapalıyken glm'e (ücretsiz) düşer
        res = self._run()
        self.assertEqual(used, ["glm"])
        self.assertTrue(res["fell_back"])
        # yazma açıkken ücretsiz modele düşülmez
        used.clear()
        self.ctx["write"] = True
        res = self._run()
        self.assertEqual(used, [])
        self.assertEqual(res["status"], "limit")


class TestAgySwap(unittest.TestCase):
    """Sahte kayıt adlarıyla: geçiş, geri yazma, yedekten dönüş. Gerçek agy kimliğine dokunmaz."""

    def setUp(self):
        self._orig = (acc_mod.AGY_LIVE, acc_mod.SNAP, acc_mod.AGY_BACKUP)
        acc_mod.AGY_LIVE, acc_mod.SNAP, acc_mod.AGY_BACKUP = "compade:test:live", "compade:test:snap:{}", "compade:test:backup"
        for t in ("compade:test:live", "compade:test:snap:agy-1", "compade:test:snap:agy-2", "compade:test:backup"):
            wincred.delete(t)
        self.acc = acc_mod.Accounts(_mk_config(0, 2))
        self.acc.state = {"accounts": {}, "agy_active": None}

    def tearDown(self):
        for t in ("compade:test:live", "compade:test:snap:agy-1", "compade:test:snap:agy-2", "compade:test:backup"):
            wincred.delete(t)
        acc_mod.AGY_LIVE, acc_mod.SNAP, acc_mod.AGY_BACKUP = self._orig

    def test_full_cycle(self):
        live = acc_mod.AGY_LIVE
        wincred.write(live, b"TOKEN-A", "a@x")
        self.acc.agy_save_current("agy-1")                       # 1. hesabı yedekle
        self.assertEqual(wincred.read("compade:test:snap:agy-1")["blob"], b"TOKEN-A")
        self.assertEqual(self.acc.agy_active(), "agy-1")

        self.acc.agy_prepare_login("agy-2")                       # yeni hesap için canlı kayıt silinir, yedek güvende
        self.assertIsNone(wincred.read(live))
        self.assertEqual(wincred.read("compade:test:backup")["blob"], b"TOKEN-A")
        self.assertEqual(self.acc.agy_active(), "agy-2")

        wincred.write(live, b"TOKEN-B", "b@x")                    # kullanıcı yeni hesapla giriş yaptı
        self.acc.agy_save_current("agy-2")

        self.acc.agy_activate("agy-1")                            # 2 -> 1 geçişi
        self.assertEqual(wincred.read(live)["blob"], b"TOKEN-A")
        self.assertEqual(wincred.read("compade:test:snap:agy-2")["blob"], b"TOKEN-B")   # 2'nin jetonu korundu

        wincred.write(live, b"TOKEN-A-YENILENMIS", "a@x")         # agy işi sırasında jeton yeniledi
        self.acc.agy_sync_back()
        self.assertEqual(wincred.read("compade:test:snap:agy-1")["blob"], b"TOKEN-A-YENILENMIS")

        self.acc.agy_activate("agy-2")
        self.assertEqual(wincred.read(live)["blob"], b"TOKEN-B")
        self.assertEqual(wincred.read("compade:test:snap:agy-1")["blob"], b"TOKEN-A-YENILENMIS")

    def test_new_account_login_returns_to_previous(self):
        live = acc_mod.AGY_LIVE
        wincred.write(live, b"TOKEN-A", "a@x")
        self.acc.agy_save_current("agy-1")
        self.acc.agy_prepare_login("agy-2")                       # yeni hesap ekleniyor
        wincred.write(live, b"TOKEN-B", "b@x")
        self.acc.agy_save_current("agy-2")
        prev = self.acc.agy_take_return("agy-2")
        self.assertEqual(prev, "agy-1")                           # önceki (ana) hesaba dönülecek
        self.acc.agy_activate(prev)
        self.assertEqual(wincred.read(live)["blob"], b"TOKEN-A")
        self.assertEqual(wincred.read("compade:test:snap:agy-2")["blob"], b"TOKEN-B")
        self.assertIsNone(self.acc.agy_take_return("agy-2"))      # bir kez döner

    def test_return_target_can_be_preserved_until_activation_succeeds(self):
        self.acc.state["agy_return_to"] = "agy-1"
        self.assertEqual(self.acc.agy_take_return("agy-2", consume=False), "agy-1")
        self.assertEqual(self.acc.state["agy_return_to"], "agy-1")
        self.acc.agy_clear_return()
        self.assertIsNone(self.acc.agy_take_return("agy-2"))

    def test_activate_without_snapshot_fails_safely(self):
        wincred.write(acc_mod.AGY_LIVE, b"TOKEN-A", "a@x")
        self.acc.state["agy_active"] = "agy-1"
        with self.assertRaises(wincred.CredError):
            self.acc.agy_activate("agy-2")                        # yedeği yok
        self.assertEqual(wincred.read(acc_mod.AGY_LIVE)["blob"], b"TOKEN-A")   # canlı kayıt bozulmadı

    def test_agy_job_failover_between_accounts(self):
        wincred.write(acc_mod.AGY_LIVE, b"TOKEN-A", "a@x")
        self.acc.agy_save_current("agy-1")
        wincred.write("compade:test:snap:agy-2", b"TOKEN-B", "b@x")
        eng = Engine(self.acc.cfg)
        eng.acc = self.acc
        seen = []

        def fake(job, mk, account, ctx, handle):
            seen.append((account["id"], wincred.read(acc_mod.AGY_LIVE)["blob"]))
            if account["id"] == "agy-1":
                return {"status": "error", "model": mk, "account": "agy-1", "limit": True, "err": "RESOURCE_EXHAUSTED",
                        "body": "", "chars": 0, "seconds": 0}
            return {"status": "ok", "model": mk, "account": account["id"], "body": "tamam " * 40, "chars": 240, "seconds": 0}
        eng._attempt = fake
        from compade.engine import Handle
        ctx = {"run_dir": Path(tempfile.mkdtemp(dir=_TMP)), "task": "x", "cwd": Path(_TMP), "write": False, "files": [], "timeout": 5}
        res = eng.execute({"tag": "g", "role": None, "model": "gemini"}, ctx, Handle(), lambda k, d: None)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(seen, [("agy-1", b"TOKEN-A"), ("agy-2", b"TOKEN-B")])    # her denemede doğru kimlik yazılmıştı


class TestLedger(unittest.TestCase):
    def test_append_and_summary(self):
        ledger.append({"model": "codex", "status": "ok", "seconds": 10, "verify": "pass"})
        ledger.append({"model": "codex", "status": "ok", "seconds": 20, "verify": "fail"})
        s = ledger.summary(ledger.tail(10))
        self.assertEqual(s["codex"]["n"], 2)
        self.assertEqual(s["codex"]["pass"], 50)
        self.assertEqual(s["codex"]["avg_sec"], 15.0)


if __name__ == "__main__":
    unittest.main()
