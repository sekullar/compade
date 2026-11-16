import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_core import _TMP  # noqa: F401
from compade import catalog, rolestore, team
from compade.engine import Engine


class TestV7Team(unittest.TestCase):
    def setUp(self):
        self.engine = object.__new__(Engine)
        self.engine.roles = {"models": {}, "roles": {}}
        self.engine.cfg = {"avoid_models": [], "timeout": 30}

    def test_team_design_requires_chief(self):
        self.engine.roles["roles"] = {"worker": {"models": ["codex"], "chief": False}}
        with self.assertRaisesRegex(ValueError, "Önce bir şef rolü seç"):
            team.design("test", self.engine)

    def test_validate_team_design_and_reject_invalid_prompt(self):
        with mock.patch.object(catalog, "catalog", return_value={"models": [{"ref": "codex:default"}], "errors": {}}):
            roles = {"models": {"codex:default": {"runtime": "codex", "id": "default"}}}
            generated = []
            for n in ("api", "ui"):
                generated.append({"key": n, "name": n.title(), "description": "İş tanımı", "prompt": "\n".join(["Kurallar"] * 8),
                                 "models": ["codex:default"], "write": False, "folder": "", "color": "#abcdef", "mascot": "owl"})
            result = team.validate({"summary": "Ekip", "roles": generated}, roles)
            self.assertEqual(len(result["roles"]), 2)
            generated[0]["key"] = generated[1]["key"]
            generated[1]["models"] = ["codex:default", "bilinmeyen:x", "codex:default"]
            fixed = team.validate({"roles": generated}, roles)
            self.assertEqual([r["key"] for r in fixed["roles"]], ["ui", "ui-2"])   # çakışan anahtar düşürmez, yeniden adlanır
            self.assertEqual(fixed["roles"][1]["models"], ["codex:default"])        # bilinmeyen/yinelenen ayıklanır
            generated[0]["models"] = []
            self.assertEqual(team.validate({"roles": generated}, roles)["roles"][0]["models"], ["codex:default"])

    def test_team_design_rejects_legacy_gemini_avoid_for_agy_model(self):
        with mock.patch.object(team, "catalog", return_value={"models": [{"ref": "agy:gemini-pro"}], "errors": {}}):
            roles = {"models": {"agy:gemini-pro": {"runtime": "agy", "id": "gemini-pro"}}}
            generated = [{"key": n, "name": n, "description": "", "prompt": "\n".join(["k"] * 8),
                          "models": ["agy:gemini-pro"], "color": "#abcdef", "mascot": "owl"} for n in ("api", "ui")]
            result = team.validate({"roles": generated}, roles, ["gemini"])
            self.assertTrue(all(r["models"] == ["codex:default"] for r in result["roles"]))   # kaçınılan agy:gemini-* atılır

    def test_design_parses_fake_chief_output_and_role_prompt_is_in_task(self):
        prompt_text = "\n".join(["Adım"] * 8)
        roles = [{"key": key, "name": key, "description": "Tanım", "prompt": prompt_text,
                  "models": ["codex:default"], "write": False, "folder": "", "color": "#abcdef", "mascot": "owl"}
                 for key in ("api", "ui")]
        with tempfile.TemporaryDirectory() as tmp:
            class FakeEngine:
                cfg = {"avoid_models": []}
                roles = {"models": {"codex:default": {"runtime": "codex", "id": "default"}},
                         "roles": {"chief": {"chief": True, "models": ["codex:default"]}}}
                def plan(self, *args): return ([{"tag": "chief"}], [])
                def make_run_dir(self, *args): return Path(tmp)
                def run(self, task, jobs, **kwargs):
                    self.task = task
                    (Path(tmp) / "out-chief.md").write_text(json.dumps({"summary": "squad", "roles": roles}), encoding="utf-8")
            fake = FakeEngine()
            with mock.patch.object(catalog, "catalog", return_value={"models": [{"ref": "codex:default"}], "errors": {}}):
                result = team.design("Build service", fake)
            self.assertEqual(result["summary"], "squad")
            self.assertIn("Build service", fake.task)

    def test_job_tags_are_safe_file_names_for_model_refs(self):
        self.engine.roles = {"models": {"codex:default": {"runtime": "codex", "id": "default"},
                                        "opencode:opencode/glm": {"runtime": "opencode", "id": "opencode/glm"}},
                             "roles": {"sef": {"name": "Şef", "models": ["codex:default"]},
                                       "web": {"name": "Web", "models": ["opencode:opencode/glm"]}}}
        jobs, _ = self.engine.plan(["sef", "web"])
        self.assertEqual([j["tag"] for j in jobs], ["sef-codex-default", "web-opencode-opencode-glm"])

    def test_engine_includes_role_prompt(self):
        self.engine.roles = {"models": {"codex": {"runtime": "codex"}}, "roles": {
            "api": {"name": "API", "brief": "short", "prompt": "Detailed instructions", "models": ["codex"]}}}
        text = self.engine.build_prompt({"role": "api", "model": "codex"}, "Task", False, [])
        self.assertIn("Detailed instructions", text)

    def test_apply_replace_preserves_chief(self):
        app_roles = {"models": {"codex": {"runtime": "codex", "id": ""}}, "roles": {
            "chief": {"name": "Şef", "brief": "", "models": ["codex"], "chief": True},
            "old": {"name": "Eski", "brief": "", "models": ["codex"]}}}
        class Fake:
            roles = app_roles
            def reload_roles(self): pass
        fake = Fake()
        from compade.server import App
        app = object.__new__(App)
        app.engine = fake
        saved = {}
        def save(data):
            saved.update(rolestore.normalize(data))
            fake.roles = saved
            return saved
        with mock.patch.object(rolestore, "save", side_effect=save):
            result = app.team_apply({"replace": True, "roles": [{"key": "new-role", "name": "Yeni", "description": "", "prompt": "", "models": ["codex"], "write": False}]})
        self.assertIn("chief", result["roles"])
        self.assertIn("new-role", result["roles"])
        self.assertNotIn("old", result["roles"])
        # Arayüzün gönderdiği biçim: {anahtar: rol}, şef de içinde (atlanır, korunur)
        with mock.patch.object(rolestore, "save", side_effect=save):
            result = app.team_apply({"replace": True, "roles": {
                "chief": {"name": "Şef", "models": ["codex"], "chief": True},
                "ui": {"name": "UI", "description": "", "prompt": "", "models": ["codex"], "write": True}}})
        self.assertEqual(sorted(result["roles"]), ["chief", "ui"])
        self.assertTrue(result["roles"]["chief"]["chief"])


if __name__ == "__main__":
    unittest.main()
