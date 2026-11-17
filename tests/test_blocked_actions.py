"""İşçi çıktısındaki izin/erişim engelleri yakalanır; sandbox başlığı gibi gürültü yakalanmaz."""
import unittest

from test_core import _TMP  # noqa: F401

from compade.engine import Engine  # noqa: E402


class TestBlocked(unittest.TestCase):
    def test_extracts_denials_and_ignores_header(self):
        err = ("OpenAI Codex v0.167.0\napproval: never\nsandbox: workspace-write [workdir, /tmp]\n"
               "fatal: detected dubious ownership in repository at 'C:/x'\n"
               "Error: Access is denied. (os error 5)\n")
        body = "Playwright file: protokolünü engelliyor, sunucu kabuk komutu sayılır.\nHer şey yolunda."
        got = Engine.blocked_actions(body, err)
        self.assertEqual(len(got), 3)
        self.assertTrue(any("dubious ownership" in x for x in got))
        self.assertFalse(any(x.startswith(("sandbox:", "approval:")) for x in got))

    def test_clean_output_has_none_and_duplicates_collapse(self):
        self.assertEqual(Engine.blocked_actions("Tamam, dosyalar yazıldı."), [])
        self.assertEqual(len(Engine.blocked_actions("Access is denied.\nAccess is denied.\nAccess is denied.")), 1)


if __name__ == "__main__":
    unittest.main()
