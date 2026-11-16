"""Hesap davranışları yalnızca geçici sahte kimliklerle sınanır."""
import base64
import json
import unittest
from unittest import mock
from pathlib import Path

from test_core import _TMP  # noqa: F401
from compade import accounts, config


def fake_jwt(email):
    enc = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'none'})}.{enc({'email': email})}.sig"


class TestAccounts(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(config.DEFAULTS)
        self.cfg["accounts"] = []
        self.acc = accounts.Accounts(self.cfg)

    def test_duplicate_codex_identity_labels(self):
        a = self.acc.add("codex", "Birinci")
        b = self.acc.add("codex", "İkinci")
        for acct in (a, b):
            home = Path(acct["home"])
            home.mkdir(parents=True, exist_ok=True)
            (home / "auth.json").write_text(json.dumps({"tokens": {"id_token": fake_jwt("same@compade.test")}}), encoding="utf-8")
        self.assertEqual(self.acc.duplicate_labels(), {a["id"]: ["İkinci"], b["id"]: ["Birinci"]})

    def test_rename_and_note_validation_and_persistence(self):
        acct = self.acc.add("agy", "Antigravity 1")
        self.acc.update_account(acct["id"], label="Kişisel", note="Bu giriş: fake@compade.test")
        self.assertEqual(acct["label"], "Kişisel")
        self.assertEqual(self.acc._st(acct["id"])["note"], "Bu giriş: fake@compade.test")
        with self.assertRaises(ValueError):
            self.acc.update_account(acct["id"], label="  ")
        with self.assertRaises(ValueError):
            self.acc.update_account(acct["id"], note="x" * 241)

    def test_added_codex_without_auth_is_logged_out(self):
        acct = self.acc.add("codex", None)
        self.assertEqual(acct["label"], "Codex 1")
        state = self.acc.status(acct)
        self.assertEqual(state["state"], "loggedout")
        self.assertIn("Giriş yap", state["detail"])
        self.assertIsNone(state["used"])

    def test_opencode_account_records_are_ignored(self):
        self.cfg["accounts"].append({"id": "old", "provider": "opencode", "label": "old"})
        acc = accounts.Accounts(self.cfg)
        self.assertEqual(acc.list(), [])

    def test_remove_rejects_duplicate_label_and_preserves_shared_list(self):
        first = self.acc.add("codex", "Birinci")
        shared = self.cfg["accounts"]
        with self.assertRaises(ValueError):
            self.acc.add("codex", "birinci")
        self.acc.remove(first["id"])
        self.assertIs(shared, self.cfg["accounts"])
        self.assertNotIn(first, shared)
        self.assertEqual(self.acc.available("codex"), [])

    def test_in_use_account_is_removed_after_release(self):
        acct = self.acc.add("codex", "Çalışan")
        self.assertTrue(self.acc.acquire(acct["id"]))
        self.assertTrue(self.acc.remove(acct["id"]))
        self.assertEqual(self.acc.available("codex"), [])
        self.assertIsNotNone(self.acc.get(acct["id"]))
        self.acc.release(acct["id"])
        self.assertIsNone(self.acc.get(acct["id"]))

    def test_config_save_uses_atomic_replace(self):
        original = {"accounts": [], "sentinel": "old"}
        config.CONFIG.write_text(json.dumps(original), encoding="utf-8")
        new = {"accounts": [], "sentinel": "new"}
        with mock.patch.object(config.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                config.save(new)
        self.assertEqual(json.loads(config.CONFIG.read_text(encoding="utf-8")), original)


if __name__ == "__main__":
    unittest.main()
