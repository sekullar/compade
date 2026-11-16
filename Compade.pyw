"""Çift tıkla Compade arayüzünü aç (konsol penceresi olmadan)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compade.gui.app import run_gui  # noqa: E402

run_gui()
