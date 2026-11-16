"""Güncelleme denetimi ve kurulum."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from test_core import _TMP  # noqa: F401

from compade import __version__, updater  # noqa: E402

REL = {"tag_name": "v99.0.0", "html_url": "https://github.com/sekullar/compade/releases/tag/v99.0.0", "body": "notlar",
       "assets": [{"name": "latest.yml", "browser_download_url": "x"},
                  {"name": "Compade-Setup-99.0.0.exe", "size": 4,
                   "browser_download_url": "https://github.com/sekullar/compade/releases/download/v99.0.0/Compade-Setup-99.0.0.exe"}]}


class TestUpdater(unittest.TestCase):
    def setUp(self):
        updater._cache_file().unlink(missing_ok=True)

    def test_versions(self):
        self.assertTrue(updater.is_newer("v0.2.0", "0.1.9"))
        self.assertTrue(updater.is_newer("0.10.0", "0.9.0"))
        self.assertFalse(updater.is_newer("v0.1.0", "0.1.0"))
        self.assertFalse(updater.is_newer("0.1", "0.1.0"))

    def test_check_and_cache(self):
        calls = []
        f = lambda: calls.append(1) or REL  # noqa: E731
        a = updater.check(fetch=f)
        self.assertTrue(a["has_update"])
        self.assertEqual(a["latest"], "99.0.0")
        self.assertEqual(a["current"], __version__)
        self.assertEqual(a["asset"]["name"], "Compade-Setup-99.0.0.exe")
        self.assertEqual(a["kind"], "source")
        updater.check(fetch=f)                       # önbellekten
        self.assertEqual(len(calls), 1)
        updater.check(fetch=f, force=True)
        self.assertEqual(len(calls), 2)

    def test_network_error_is_quiet(self):
        def boom():
            raise OSError("ağ yok")
        a = updater.check(fetch=boom)
        self.assertFalse(a["has_update"])
        self.assertIn("ağ yok", a["error"])

    def test_install_kind(self):
        hub = Path(os.environ.get("LOCALAPPDATA", "C:/x")) / "SentinelHub" / "apps" / "compade" / "Compade.exe"
        self.assertEqual(updater.install_kind(hub, frozen=True), "hub")
        self.assertEqual(updater.install_kind("C:/Programs/Compade/Compade.exe", frozen=True), "installer")
        self.assertEqual(updater.install_kind(frozen=False), "source")

    def test_install_only_for_installer(self):
        info = updater.check(fetch=lambda: REL)
        with self.assertRaises(ValueError):
            updater.install(info)                    # kaynak kurulum: kendini güncellemez
        cmds = []
        info = {**info, "kind": "installer"}
        with mock.patch.object(sys, "executable", "C:\\Programs\\Compade Dir\\Compade.exe"):
            updater.install(info, download=lambda u, d: Path(d).write_bytes(b"1234"), launch=cmds.append, exit_after=0)
        self.assertEqual(len(cmds), 1)
        self.assertTrue(cmds[0].endswith("--relaunch /S /D=C:\\Programs\\Compade Dir"))
        bad = {**info, "asset": {**info["asset"], "url": "https://evil.example/x.exe"}}
        with self.assertRaises(ValueError):
            updater.install(bad, download=lambda u, d: None, launch=cmds.append, exit_after=0)


if __name__ == "__main__":
    unittest.main()
