"""Hesap kimliği: sahte auth dosyalarıyla; gerçek kimlik bilgilerine dokunmaz."""
import base64
import json
import tempfile
import unittest
from pathlib import Path

from test_core import _TMP  # noqa: F401

from compade import identity  # noqa: E402
from compade import limits  # noqa: E402


def jwt(claims):
    def b(x):
        return base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip("=")
    return f"{b({'alg': 'none'})}.{b(claims)}.sig"


class TestIdentity(unittest.TestCase):
    def tmp(self):
        return Path(tempfile.mkdtemp(prefix="compade-id-"))

    def test_codex_email_and_plan(self):
        d = self.tmp()
        (d / "auth.json").write_text(json.dumps({"tokens": {"id_token": jwt(
            {"email": "a@example.com", "https://api.openai.com/auth": {"chatgpt_plan_type": "free"}}), "access_token": "SECRET"}}))
        r = identity.codex_identity(d)
        self.assertEqual(r, {"email": "a@example.com", "plan": "free"})
        self.assertNotIn("SECRET", json.dumps(r))

    def test_codex_missing_or_bad(self):
        d = self.tmp()
        self.assertIsNone(identity.codex_identity(d))
        (d / "auth.json").write_text("{bozuk")
        self.assertIsNone(identity.codex_identity(d))
        (d / "auth.json").write_text(json.dumps({"tokens": {"id_token": "a.b"}}))
        self.assertIsNone(identity.codex_identity(d))
        (d / "auth.json").write_text(json.dumps({"tokens": {"id_token": jwt({"sub": "x"})}}))
        self.assertIsNone(identity.codex_identity(d))

    def test_cache_refreshes_on_change(self):
        d = self.tmp()
        f = d / "auth.json"
        f.write_text(json.dumps({"tokens": {"id_token": jwt({"email": "one@example.com"})}}))
        self.assertEqual(identity.codex_identity(d)["email"], "one@example.com")
        f.write_text(json.dumps({"tokens": {"id_token": jwt({"email": "two@example.com"})}}) + " ")
        self.assertEqual(identity.codex_identity(d)["email"], "two@example.com")

    def test_claude(self):
        d = self.tmp()
        self.assertIsNone(identity.claude_identity(d))
        (d / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "c@example.com", "organizationName": "Org"}, "x": "gizli"}))
        self.assertEqual(identity.claude_identity(d), {"email": "c@example.com", "org": "Org"})

    def test_agy_last_consumer_email_and_mtime_cache(self):
        d = self.tmp()
        f = d / "cli.log"
        f.write_text("applyAuthResult: email=old@example.test, authMethod=consumer, ok\n"
                      "applyAuthResult: email=new@example.test, authMethod=consumer, ok\n"
                      "applyAuthResult: email=ignored@example.test, authMethod=other, ok\n", encoding="utf-8")
        self.assertEqual(identity.agy_email(f), "new@example.test")

    def test_claude_usage_windows_and_stale(self):
        d = self.tmp()
        f = d / "claude-usage.json"
        f.write_text(json.dumps({"rate_limits": {"five_hour": {"used_percentage": 22.5, "resets_at": 123},
                                 "seven_day": {"mystery": 1}}, "model": "x", "saved_at": 100}), encoding="utf-8")
        r = limits.claude_rate_limits(f, now=100 + 6 * 3600 + 1)
        self.assertTrue(r["stale"])
        self.assertEqual(r["windows"][0]["used"], 22.5)
        self.assertIn("raw", r["windows"][1])

    def test_agy_last_consumer_email_and_mtime_cache(self):
        d = self.tmp()
        f = d / "cli.log"
        f.write_text("auth.go:221] applyAuthResult: email=old@example.test, authMethod=consumer, ok\n"
                      "auth.go:221] applyAuthResult: email=new@example.test, authMethod=consumer, ok\n"
                      "auth.go:221] applyAuthResult: email=ignored@example.test, authMethod=other, ok\n", encoding="utf-8")
        self.assertEqual(identity.agy_email(f), "new@example.test")


if __name__ == "__main__":
    unittest.main()
