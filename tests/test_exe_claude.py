"""claude.CMD kabuğu atlanır (cmd.exe tırnak + | içeren sistem talimatını bölüyordu)."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_core import _TMP  # noqa: F401

from compade import engine  # noqa: E402


class TestExeClaude(unittest.TestCase):
    def test_cmd_shim_resolves_to_real_exe(self):
        d = Path(tempfile.mkdtemp())
        shim = d / "claude.CMD"
        shim.write_text("@echo off", encoding="utf-8")
        real = d / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        with mock.patch.object(shutil, "which", lambda n: str(shim) if n == "claude" else None):
            self.assertEqual(engine.exe_claude(), str(shim))        # gerçek exe yoksa kabuk
            real.parent.mkdir(parents=True)
            real.write_bytes(b"MZ")
            self.assertEqual(engine.exe_claude(), str(real))
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
