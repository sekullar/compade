"""Maliyet panosu toplamı."""
import time
import unittest

from test_core import _TMP  # noqa: F401

from compade import costs  # noqa: E402

NOW = time.mktime((2026, 11, 16, 12, 0, 0, 0, 0, -1))
DAY = 86400
MODELS = {"free": {"runtime": "opencode", "id": "x-free"}, "codex": {"runtime": "codex"}, "claude:opus": {"runtime": "claude", "id": "opus"}}


class TestCosts(unittest.TestCase):
    def rows(self):
        return [
            {"ts": NOW - 100, "model": "codex", "role": "be", "status": "ok", "tokens": 1000, "seconds": 10},
            {"ts": NOW - 200, "model": "codex", "role": "be", "status": "ok", "tokens": 3000, "verify": "fail", "seconds": 30},
            {"ts": NOW - DAY, "model": "free", "role": "qa", "status": "error", "chars": 360, "seconds": 5},
            {"ts": NOW - 300, "kind": "chief", "model": "claude:opus", "role": "sef", "status": "ok",
             "tokens_in": 500, "tokens_out": 500, "cost_usd": 0.12, "cache_read": 9000},
            {"ts": NOW - 30 * DAY, "model": "codex", "status": "ok", "tokens": 99999},   # aralık dışı
        ]

    def test_aggregate(self):
        r = costs.aggregate(self.rows(), days=7, now=NOW, models=MODELS)
        t = r["totals"]
        self.assertEqual(t["runs"], 4)
        self.assertEqual(t["ok"], 2)                       # verify fail ve error başarısız sayılır
        self.assertEqual(t["tokens"], 5000)
        self.assertEqual(t["est_tokens"], 100)             # 360 karakter / 3.6
        self.assertEqual((t["chief_tokens"], t["team_tokens"]), (1000, 4000))
        self.assertEqual(t["team_share"], 80)
        self.assertAlmostEqual(t["cost_usd"], 0.12)
        self.assertEqual(t["cheap_runs"], 1)
        self.assertEqual(len(r["by_day"]), 7)
        self.assertEqual(r["by_day"][-1]["day"], "2026-11-16")
        self.assertEqual((r["by_day"][-1]["team"], r["by_day"][-1]["chief"]), (4000, 1000))
        self.assertEqual(r["by_day"][-2]["est"], 100)
        codex = next(m for m in r["by_model"] if m["key"] == "codex")
        self.assertEqual((codex["runs"], codex["pass"], codex["avg_sec"], codex["tier"]), (2, 50, 20.0, "strong"))
        self.assertEqual(r["by_model"][0]["key"], "codex")   # en çok token önce
        self.assertTrue(any(x["key"] == "sef" and x["chief"] for x in r["by_role"]))

    def test_empty(self):
        r = costs.aggregate([], days=3, now=NOW)
        self.assertIsNone(r["totals"]["team_share"])
        self.assertEqual(len(r["by_day"]), 3)


if __name__ == "__main__":
    unittest.main()
