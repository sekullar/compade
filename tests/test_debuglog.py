"""Hata ayıklama günlüğü: yazma, maskeleme, kısaltma, dönme, süzme, kapatma."""
import os
import unittest

from test_core import _TMP  # noqa: F401

from compade import debuglog  # noqa: E402


class TestDebugLog(unittest.TestCase):
    def setUp(self):
        debuglog.clear()
        os.environ.pop("COMPADE_DEBUG", None)

    def test_write_read_filter(self):
        debuglog.log("server", "task_state", {"id": "t1", "status": "running"}, chat="c-1234")
        debuglog.log("ui", "click", {"text": "Onayla"})
        rows = debuglog.read(10)
        self.assertEqual([r["kind"] for r in rows], ["task_state", "click"])
        self.assertEqual(debuglog.read(10, src="ui")[0]["d"]["text"], "Onayla")
        self.assertEqual(len(debuglog.read(10, chat="c-1234")), 1)
        self.assertEqual(len(debuglog.read(10, kind="^task")), 1)
        self.assertIn("task_state", debuglog.fmt(rows[0]))

    def test_scrub_secrets_and_long_text(self):
        debuglog.log("api", "x", {"token": "abc", "Authorization": "Bearer z", "x": "a" * 1000, "n": {"api_key": "k"}})
        d = debuglog.read(1)[0]["d"]
        self.assertEqual((d["token"], d["Authorization"], d["n"]["api_key"]), ("***", "***", "***"))
        self.assertLess(len(d["x"]), 400)

    def test_rotation(self):
        old = debuglog.MAX_BYTES
        debuglog.MAX_BYTES = 2000
        try:
            for i in range(200):
                debuglog.log("server", "e", {"i": i, "pad": "x" * 50})
            self.assertTrue(debuglog._path().with_name("debug.1.jsonl").exists())
            self.assertGreater(len(debuglog.read(1000)), 20)
        finally:
            debuglog.MAX_BYTES = old

    def test_disabled(self):
        os.environ["COMPADE_DEBUG"] = "0"
        debuglog.log("server", "hidden")
        os.environ.pop("COMPADE_DEBUG")
        self.assertEqual(debuglog.read(5), [])


if __name__ == "__main__":
    unittest.main()
