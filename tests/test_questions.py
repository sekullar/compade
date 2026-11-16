"""Şefin soruları: compade-questions bloğu / AskUserQuestion -> soru kartı; kullanıcı yazınca kapanır."""
import copy
import json
import threading
import unittest
from unittest.mock import patch

from test_core import _TMP  # noqa: F401
from test_cc_chat import FakeProc
from test_session import ROLES, Harness

from compade import chief, session  # noqa: E402
from compade.cc_chat import CCTurn  # noqa: E402

QBLOCK = 'Bağlam.\n```compade-questions [{"question":"Hangi site?","options":["ahmetefekorkmaz.dev","başka"]},{"question":"Renk?"}]```'

CC_ROLES = copy.deepcopy(ROLES)
CC_ROLES["models"]["claude:opus"] = {"runtime": "claude", "id": "opus"}
CC_ROLES["roles"]["sef"]["models"] = ["claude:opus"]


class FakeTurn(CCTurn):
    """Gerçek claude yerine: verilen olayları sırayla bildirir."""
    script = []

    def __init__(self, timeout=600, popen=None):
        self.thread = None

    def start(self, text, cwd, session_id=None, model="default", effort=None, mode="plan", allowed=None, on_event=None, system_prompt=None):
        FakeTurn.last_system = system_prompt
        def run():
            for ev in FakeTurn.script:
                on_event(dict(ev))
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        return self

    def cancel(self):
        pass


class TestParse(unittest.TestCase):
    def test_block(self):
        qs = chief.parse_questions(QBLOCK)
        self.assertEqual([q["question"] for q in qs], ["Hangi site?", "Renk?"])
        self.assertEqual(qs[0]["options"], ["ahmetefekorkmaz.dev", "başka"])
        self.assertEqual(CCTurn.clean_text(QBLOCK), "Bağlam.")
        self.assertIsNone(chief.parse_questions("```compade-questions {bozuk}```"))
        self.assertIsNone(chief.parse_questions("soru yok?"))

    def test_tool_input(self):
        qs = chief.questions_from_tool({"questions": [{"question": "A mı B mi?", "header": "x", "multiSelect": True,
                                                       "options": [{"label": "A", "description": "a"}, {"label": "B"}]}]})
        self.assertEqual(qs, [{"question": "A mı B mi?", "options": ["A", "B"], "multi": True}])

    def test_argv_blocks_askuserquestion_and_dedupes_tools(self):
        tool = {"type": "tool_use", "id": "tu1", "name": "Read", "input": {}}
        rows = [{"type": "system", "subtype": "init", "session_id": "s"},
                {"type": "stream_event", "event": {"type": "content_block_start", "index": 1, "content_block": tool}},
                {"type": "stream_event", "event": {"type": "content_block_stop", "index": 1}},
                {"type": "assistant", "message": {"id": "m", "content": [tool]}},
                {"type": "result", "session_id": "s", "result": "ok", "usage": {}}]
        events = []
        with patch("compade.cc_chat.exe_claude", return_value="claude"), \
                patch("compade.cc_chat.subprocess.Popen", return_value=FakeProc([json.dumps(r) for r in rows])):
            t = CCTurn(timeout=2).start("x", ".", on_event=events.append)
            t.thread.join(2)
        self.assertEqual(sum(1 for e in events if e["type"] == "cc_tool"), 1)
        i = t.argv.index("--disallowedTools")
        self.assertEqual(t.argv[i + 1], "AskUserQuestion")


class TestSessionQuestions(unittest.TestCase):
    def setUp(self):
        self.h = Harness([])
        self.h.eng.roles = CC_ROLES

    def wait(self, *kinds):
        with self.h.cv:
            ok = self.h.cv.wait_for(lambda: any(k in kinds for k, _ in self.h.events), 5)
        self.assertTrue(ok, [k for k, _ in self.h.events])
        return next(d for k, d in self.h.events if k in kinds)

    def test_block_becomes_card_and_clears_on_reply(self):
        FakeTurn.script = [{"type": "cc_start", "session_id": "s1"},
                           {"type": "cc_assistant_done", "text": "Bağlam.", "raw_text": QBLOCK},
                           {"type": "cc_result", "ok": True, "text": "Bağlam.", "usage": {}}]
        with patch.object(session, "CCTurn", FakeTurn):
            cid = self.h.s.message(None, "siteyi düzelt")["chat"]
            d = self.wait("cc_questions")
            self.wait("cc_result")
            self.assertEqual(len(d["questions"]), 2)
            chat = self.h.s.get(cid)
            self.assertEqual(chat.to_dict()["questions"][0]["question"], "Hangi site?")
            self.assertIn("compade-questions", FakeTurn.last_system)
            chat.cc_turn.thread.join(2)
            FakeTurn.script = [{"type": "cc_result", "ok": True, "text": "tamam", "usage": {}}]
            self.h.s.message(cid, "1) ahmetefekorkmaz.dev")
            self.assertIsNone(chat.questions)

    def test_state_is_idle_before_result_event_reaches_ui(self):
        seen = {}
        orig = self.h.on_event

        def spy(kind, d):
            if kind == "cc_result":
                seen["state"] = self.h.s.get(d["chat"]).state
            orig(kind, d)
        self.h.s.on_event = spy
        FakeTurn.script = [{"type": "cc_start", "session_id": "s3"}, {"type": "cc_result", "ok": True, "text": "x", "usage": {}}]
        with patch.object(session, "CCTurn", FakeTurn):
            self.h.s.message(None, "merhaba")
            self.wait("cc_result")
        self.assertEqual(seen["state"], "idle")

    def test_askuserquestion_tool_fallback(self):
        FakeTurn.script = [{"type": "cc_start", "session_id": "s2"},
                           {"type": "cc_tool", "id": "t", "name": "AskUserQuestion",
                            "input": {"questions": [{"question": "Hangisi?", "options": [{"label": "X"}]}]}},
                           {"type": "cc_result", "ok": True, "text": "", "usage": {}}]
        with patch.object(session, "CCTurn", FakeTurn):
            self.h.s.message(None, "iş")
            d = self.wait("cc_questions")
        self.assertEqual(d["questions"], [{"question": "Hangisi?", "options": ["X"], "multi": False}])


if __name__ == "__main__":
    unittest.main()
