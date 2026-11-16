import unittest

from test_core import _TMP  # noqa: F401

from compade import chief  # noqa: E402

R = {"sef": {"name": "Şef", "brief": "planlar"}, "be": {"name": "Backend", "brief": "api", "write": True},
     "qa": {"name": "QA", "brief": "test"}}


def task(i, role="be", dep=(), ins="yap"):
    return {"id": i, "role": role, "instruction": ins, "depends_on": list(dep)}


class TestChief(unittest.TestCase):
    def test_extract_last_block(self):
        txt = 'a ```json\n{"x":1}\n``` b ```json\n{"tasks":[]}\n```'
        self.assertEqual(chief.extract_json(txt), {"tasks": []})

    def test_extract_bare_and_fail(self):
        self.assertEqual(chief.extract_json('plan: {"a": 2} bitti'), {"a": 2})
        with self.assertRaises(ValueError):
            chief.extract_json("json yok")

    def test_valid_levels(self):
        p = chief.validate_plan({"tasks": [task("a"), task("b", "qa", ["a"]), task("c")]}, R, "sef")
        self.assertEqual(p["levels"], [["a", "c"], ["b"]])

    def test_rejects(self):
        bad = [{"tasks": [task("a", "yok")]}, {"tasks": [task("a", "sef")]}, {"tasks": [task("a", ins=" ")]},
               {"tasks": [task("a"), task("a")]}, {"tasks": [task("a", dep=["z"])]},
               {"tasks": [task("a", dep=["b"]), task("b", dep=["a"])]}, {"tasks": []},
               {"tasks": [task(f"t{i}") for i in range(13)]}]
        for b in bad:
            with self.assertRaises(ValueError, msg=str(b)[:60]):
                chief.validate_plan(b, R, "sef")

    def test_question_only(self):
        p = chief.validate_plan({"tasks": [], "question": "Hangi dil?"}, R, "sef")
        self.assertEqual((p["tasks"], p["question"]), ([], "Hangi dil?"))

    def test_prompt_lists_roles_not_chief(self):
        s = chief.system_prompt(R, "sef")
        self.assertIn("`be`", s)
        self.assertNotIn("`sef` —", s)
        self.assertIn('"tasks"', s)


class TestExtract(unittest.TestCase):
    def test_extract_output_section(self):
        txt = "## 1. Özet\n- a\n## 2. Çıktı\nAsıl metin\nİkinci satır\n## 3. Riskler / dikkat\n- x\n"
        self.assertEqual(chief.extract_output(txt), "Asıl metin\nİkinci satır")

    def test_extract_output_fallback(self):
        self.assertEqual(chief.extract_output("düz metin"), "düz metin")
        self.assertEqual(chief.extract_output(""), "")
