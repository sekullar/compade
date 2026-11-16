"""v6 backend yardımcılarının sahte girdi testleri."""
import json
import threading
import time
import unittest
from unittest import mock

from compade import agyquota, server


class TestV6Backend(unittest.TestCase):
    def tearDown(self):
        agyquota.reset_cache()

    def test_invalidated_inflight_quota_result_is_discarded(self):
        started, finish = threading.Event(), threading.Event()
        old_result = {"models": [{"name": "old-account", "remaining": 0.1}], "error": None}
        def query(_reader):
            started.set()
            finish.wait(2)
            return old_result
        with mock.patch.object(agyquota, "_query", side_effect=query):
            self.assertIsNone(agyquota.get(lambda: "old", key="race-test"))
            self.assertTrue(started.wait(1))
            agyquota.invalidate("race-test")
            finish.set()
            deadline = time.time() + 1
            while time.time() < deadline:
                with agyquota._lock:
                    cache = agyquota._caches["race-test"]
                    if not cache["running"]:
                        break
                time.sleep(0.005)
            self.assertIsNone(agyquota.get(lambda: "new", key="race-test"))
            with agyquota._lock:
                self.assertIsNone(agyquota._caches["race-test"]["value"])

    def test_quota_model_fields_and_fraction_clamp(self):
        got = agyquota._models_response({"models": [
            {"name": "m1", "quotaInfo": {"remainingFraction": 0.4, "resetTime": "later"}},
            {"name": "m2", "quotaInfo": {"remainingFraction": 2}},
            {"name": "m3", "quotaInfo": {}},
        ]})
        self.assertEqual(got, [{"name": "m1", "remaining": 0.4, "resets_at": "later"},
                               {"name": "m2", "remaining": 1.0, "resets_at": None}])

    def test_token_parser_keeps_secret_out_of_result(self):
        token = "secret-test-value"
        parsed = agyquota._token_from_credential({"blob": json.dumps({"access_token": token}).encode()})
        self.assertEqual(parsed, token)

    def test_opencode_fake_runner_and_cache(self):
        app = object.__new__(server.App)
        app._opencode_cache = {"at": 0.0, "models": [], "error": None}
        app._opencode_lock = __import__("threading").Lock()
        runner = mock.Mock(return_value=type("P", (), {"returncode": 0, "stdout": "m1\nm2\n", "stderr": ""})())
        app._opencode_runner = runner
        with mock.patch.object(server, "exe_opencode", return_value="fake-opencode"):
            self.assertEqual(app._opencode_models(), {"models": ["m1", "m2"], "error": None})
            app._opencode_models()
        runner.assert_called_once()


if __name__ == "__main__":
    unittest.main()
