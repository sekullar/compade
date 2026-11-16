import json
import unittest
from io import StringIO
from unittest.mock import patch

from compade.cc_chat import CCTurn
from compade import chief


class FakeProc:
    def __init__(self, rows):
        self.stdin = StringIO()
        self.stdout = iter(rows)
        self.stderr = StringIO()
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0


class CCChatTests(unittest.TestCase):
    def test_report_parser(self):
        self.assertEqual(chief.parse_report('```compade-report {"status":"blocked","summary":"takıldı","files":[],"needs":"erişim"}```'),
                         {"status": "blocked", "summary": "takıldı", "files": [], "needs": "erişim"})
        self.assertIsNone(chief.parse_report('```compade-report {broken}```'))
        self.assertIsNone(chief.parse_report('rapor yok'))

    def test_plan_fence(self):
        value = chief.extract_json('```compade-plan {"summary":"x","tasks":[]}```')
        self.assertEqual(value["summary"], "x")

    def test_decision_and_block_removal(self):
        text = 'Göründü ```compade-plan {"tasks":[]} ``` ve ```compade-decision {"action":"continue"}```'
        self.assertEqual(chief.parse_decision(text)["action"], "continue")
        self.assertEqual(CCTurn.clean_text(text), "Göründü  ve")

    def test_stream_normalizes(self):
        rows = [
            {"type":"system","subtype":"init","session_id":"sid","model":"sonnet"},
            {"type":"stream_event","event":{"type":"message_start","message":{"id":"m1"}}},
            {"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"düşünüyor"}}},
            {"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"Merhaba"}}},
            {"type":"stream_event","event":{"type":"message_stop"}},
            {"type":"rate_limit_event","rate_limit_info":{"status":"allowed_warning"}},
            {"type":"result","session_id":"sid","result":"Merhaba","total_cost_usd":0.1,"usage":{"input_tokens":2,"output_tokens":3}},
        ]
        events = []
        with patch("compade.cc_chat.exe_claude", return_value="claude"), patch("compade.cc_chat.subprocess.Popen", return_value=FakeProc([json.dumps(x) for x in rows])):
            turn = CCTurn(timeout=2).start("soru", ".", model="sonnet", on_event=events.append)
            turn.thread.join(2)
        kinds = [e["type"] for e in events]
        self.assertIn("cc_start", kinds)
        self.assertIn("cc_thinking", kinds)
        self.assertIn("cc_text", kinds)
        self.assertIn("cc_assistant_done", kinds)
        self.assertIn("cc_limit", kinds)
        result = next(e for e in events if e["type"] == "cc_result")
        self.assertEqual(result["usage"]["in"], 2)
        self.assertIn("--permission-mode", turn.argv)
        self.assertNotIn("--resume", turn.argv)


if __name__ == "__main__":
    unittest.main()
