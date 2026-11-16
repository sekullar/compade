"""Compade.exe giriş noktası (PyInstaller).

Pencereli exe'nin başlattığı konsol programları (codex, claude, git, opencode...) her seferinde siyah pencere
açmasın diye, creationflags verilmemiş her alt süreç CREATE_NO_WINDOW ile başlatılır.
"""
import os
import subprocess
import sys

if os.name == "nt":
    _init = subprocess.Popen.__init__

    def _no_window(self, *a, **k):
        if not k.get("creationflags"):
            k["creationflags"] = 0x08000000   # CREATE_NO_WINDOW
        _init(self, *a, **k)

    subprocess.Popen.__init__ = _no_window

from compade.cli import main  # noqa: E402

sys.exit(main())
