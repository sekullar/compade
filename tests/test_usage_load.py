"""Kayıtlı sohbet yeniden yüklenince sayaçlar bozulmaz; hata, bekleyen planı iptal etmez."""
import json
import unittest

from test_core import _TMP  # noqa: F401
from test_session import Harness

from compade import config, session  # noqa: E402


class TestUsageLoad(unittest.TestCase):
    def test_reload_keeps_manager_real_out_of_counters_and_restores_awaiting(self):
        h = Harness([])
        chats = config.HOME / "chats"
        chats.mkdir(parents=True, exist_ok=True)
        plan = {"summary": "x", "question": "", "levels": [["t1"]],
                "tasks": [{"id": "t1", "role": "be", "instruction": "i", "write": False, "depends_on": []}]}
        (chats / "c-reload.json").write_text(json.dumps({
            "id": "c-reload", "messages": [], "plan": plan, "state": "idle",
            "tasks": {"t1": {"status": "waiting", "run": None}},
            "usage": {"manager_in": 5, "manager_real": {"in": 3, "out": 4, "cost_usd": 0.5}}}), encoding="utf-8")
        s = session.Sessions(h.eng, h.on_event)
        chat = s.get("c-reload")
        self.assertTrue(all(isinstance(v, (int, float)) for v in chat.usage.values()))
        self.assertEqual(chat.cc_usage["manager_real"]["out"], 4)
        self.assertEqual(sum(v for v in chat.usage.values()), 5)   # artık int + dict hatası yok
        self.assertEqual(chat.state, "awaiting")


if __name__ == "__main__":
    unittest.main()
