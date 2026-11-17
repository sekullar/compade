"""Aynı hatayı tekrarlayan işçi zaman aşımını beklemeden durdurulur."""
import sys
import time
import unittest

from test_core import _TMP  # noqa: F401

from compade.engine import Engine  # noqa: E402


class H:
    proc = None
    cancelled = False


class TestWatchdog(unittest.TestCase):
    def test_repeating_apply_patch_error_is_killed_early(self):
        eng = Engine()
        code = ("import sys,time\n"
                "for i in range(40):\n"
                "    sys.stderr.write('apply_patch verification failed: invalid patch: multiple operations target x\\n'); sys.stderr.flush()\n"
                "    time.sleep(0.1)\n"
                "time.sleep(60)\n")
        t0 = time.time()
        status, out, err, rc = eng._run_process([sys.executable, "-c", code], None, None, ".", 120, H())
        self.assertEqual(status, "error")
        self.assertLess(time.time() - t0, 20)
        self.assertIn("[Compade] Aynı hata", err)

    def test_normal_process_still_returns_output_and_stdin(self):
        eng = Engine()
        status, out, err, rc = eng._run_process([sys.executable, "-c", "import sys;print(sys.stdin.read().upper())"], None, "merhaba", ".", 30, H())
        self.assertEqual((status, rc), ("ok", 0))
        self.assertIn("MERHABA", out)

    def test_timeout(self):
        eng = Engine()
        status, *_ = eng._run_process([sys.executable, "-c", "import time;time.sleep(30)"], None, None, ".", 2, H())
        self.assertEqual(status, "timeout")


if __name__ == "__main__":
    unittest.main()
