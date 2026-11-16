"""Dinamik rol deposu testleri (geçici COMPADE_HOME)."""
import unittest

from test_core import _TMP  # noqa: F401

from compade import config, rolestore  # noqa: E402

MODELS = {"codex": {"runtime": "codex"}, "gemini": {"runtime": "agy"}}


def table(**roles):
    return {"models": MODELS, "roles": roles}


def role(**kw):
    base = {"name": "Rol", "models": ["codex"]}
    base.update(kw)
    return base


class TestRoleStore(unittest.TestCase):
    def test_defaults_filled(self):
        r = rolestore.normalize(table(a=role()))["roles"]["a"]
        self.assertEqual((r["mascot"], r["write"], r["chief"], r["primary"]), ("cat", False, False, False))

    def test_unknown_model_rejected(self):
        with self.assertRaises(ValueError):
            rolestore.normalize(table(a=role(models=["yok"])))

    def test_two_chiefs_rejected(self):
        with self.assertRaises(ValueError):
            rolestore.normalize(table(a=role(chief=True), b=role(chief=True)))

    def test_ceo_is_not_implicitly_chief(self):
        t = rolestore.normalize(table(ceo=role(), x=role()))
        self.assertIsNone(rolestore.chief_key(t))

    def test_legacy_roles_are_backed_up_but_custom_roles_are_kept(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        legacy = {"ceo", "cto", "architect", "backend", "frontend", "fullstack", "desktop", "mobile",
                  "ai-engineer", "database", "automation", "ui-ux"}
        with tempfile.TemporaryDirectory() as td, patch.object(config, "HOME", Path(td)):
            config.HOME.mkdir(exist_ok=True)
            p = config.HOME / "roles.json"
            p.write_text(json.dumps({"roles": {k: {} for k in legacy}}), encoding="utf-8")
            rolestore._migrate_legacy()
            self.assertFalse(p.exists())
            self.assertEqual(len(list(config.HOME.glob("roles.json.yedek-*"))), 1)
        with tempfile.TemporaryDirectory() as td, patch.object(config, "HOME", Path(td)):
            config.HOME.mkdir(exist_ok=True)
            p = config.HOME / "roles.json"
            p.write_text(json.dumps({"roles": {"my-role": {}}}), encoding="utf-8")
            rolestore._migrate_legacy()
            self.assertTrue(p.exists())

    def test_two_primaries_rejected(self):
        with self.assertRaises(ValueError):
            rolestore.normalize(table(a=role(primary=True), b=role(primary=True)))

    def test_bad_key_color_mascot(self):
        for bad in ({"Bad Key": role()}, {"a": role(color="red")}, {"a": role(mascot="dino")}, {"a": role(name=" ")}):
            with self.assertRaises(ValueError):
                rolestore.normalize({"models": MODELS, "roles": bad})

    def test_save_roundtrip(self):
        data = {"models": MODELS, "roles": {"sef": role(name="Şef", chief=True, prompt="Planla.")}}
        rolestore.save(data)
        self.assertTrue((config.HOME / "roles.json").exists())
        again = rolestore.load()
        self.assertEqual(list(again["roles"]), ["sef"])
        self.assertEqual(again["roles"]["sef"]["prompt"], "Planla.")
        (config.HOME / "roles.json").unlink()

    def test_strict_types_and_folder(self):
        bad = [role(write="false"), role(chief="no"), role(name={}), role(brief=[]), role(prompt=3),
               role(folder="../x"), role(folder="C:/x"), role(folder="/abs")]
        for b in bad:
            with self.assertRaises(ValueError, msg=str(b)):
                rolestore.normalize(table(a=b))
        self.assertEqual(rolestore.normalize(table(a=role(folder="src\\api/")))["roles"]["a"]["folder"], "src/api")

    def test_broken_inputs_raise_valueerror(self):
        for bad in ([], {"models": [], "roles": {}}, {"models": {"x": 1}, "roles": {}}, {"models": MODELS, "roles": []},
                    {"models": MODELS, "roles": {1: role()}}):
            with self.assertRaises(ValueError):
                rolestore.normalize(bad)

    def test_corrupt_user_file_falls_back(self):
        config.HOME.mkdir(parents=True, exist_ok=True)
        (config.HOME / "roles.json").write_text("{bozuk", encoding="utf-8")
        d = rolestore.load()
        self.assertEqual(d["roles"], {})
        self.assertTrue((config.HOME / "roles.bozuk").exists())
        (config.HOME / "roles.bozuk").unlink()

    def test_concurrent_saves(self):
        import threading
        data = {"models": MODELS, "roles": {"a": role()}}
        errs = []
        def go():
            try:
                rolestore.save(data)
            except Exception as e:  # noqa
                errs.append(e)
        ts = [threading.Thread(target=go) for _ in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(errs, [])
        (config.HOME / "roles.json").unlink()

    def test_slug(self):
        self.assertEqual(rolestore.slug("Yazılım Şefi!"), "yazilim-sefi")


if __name__ == "__main__":
    unittest.main()
