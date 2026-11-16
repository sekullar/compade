"""Web sunucusu güvenlik ve API testleri (geçici COMPADE_HOME; gerçek hesaplara dokunmaz)."""
import json
import re
import socket
import threading
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest import mock

from test_core import _TMP  # noqa: F401  (COMPADE_HOME'u ayarlar)

from compade import server  # noqa: E402


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = server.App()
        cls.srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(cls.app))
        cls.srv.daemon_threads = True
        cls.app.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.app.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.app.mon.stop()

    def get(self, path, token=True, host=None):
        req = urllib.request.Request(self.base + path)
        if token:
            req.add_header("X-Compade-Token", self.app.token)
        if host:
            req.add_header("Host", host)
        return urllib.request.urlopen(req, timeout=10)

    def post(self, path, body, token=True):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        if token:
            req.add_header("X-Compade-Token", self.app.token)
        return urllib.request.urlopen(req, timeout=10)

    def test_token_required(self):
        for path in ("/api/state", "/api/runs", "/api/ls?path=C:/"):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.get(path, token=False)
            self.assertEqual(cm.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("/api/file", {"path": "x", "text": "y"}, token=False)
        self.assertEqual(cm.exception.code, 403)

    def test_wrong_host_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/api/state", host="evil.example.com")        # DNS rebinding
        self.assertEqual(cm.exception.code, 403)

    def test_index_gets_token_injected(self):
        html = self.get("/", token=False).read().decode("utf-8")
        m = re.search(r'token:"([^"]+)"', html)
        self.assertTrue(m)
        self.assertEqual(m.group(1), self.app.token)

    def test_path_traversal_blocked(self):
        for p in ("/../config.py", "/..%2fconfig.py", "/%2e%2e/accounts.py"):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.get(p, token=False)
            self.assertIn(cm.exception.code, (403, 404))

    def test_state_shape(self):
        s = json.loads(self.get("/api/state").read())
        for k in ("providers", "accounts", "models", "roles", "ram", "cfg", "version"):
            self.assertIn(k, s)
        self.assertEqual({p["key"] for p in s["providers"]}, {"codex", "agy", "opencode"})
        self.assertIn("history", s["ram"])
        self.assertIn("theme", s["cfg"])
        self.assertIn("agy_quota", s)
        self.assertEqual(set(s["claude"]), {"email", "org", "usage"})
        self.assertEqual(set(s["opencode"]), {"models", "error"})

    def test_opencode_models_uses_runner_cache_and_failure_text(self):
        app = self.app
        app._opencode_cache["at"] = 0
        fake = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout="vendor/model-a\nvendor/model-b\n", stderr=""))
        app._opencode_runner = fake
        a = app._opencode_models()
        b = app._opencode_models()
        self.assertEqual(a["models"], ["vendor/model-a", "vendor/model-b"])
        self.assertEqual(a, b)
        fake.assert_called_once()
        app._opencode_cache["at"] = 0
        app._opencode_runner = mock.Mock(return_value=SimpleNamespace(returncode=1, stdout="", stderr="CLI failed"))
        self.assertEqual(app._opencode_models(), {"models": [], "error": "CLI failed"})

    def test_run_validation_and_config(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("/api/run", {"task": "", "models": []})
        self.assertEqual(cm.exception.code, 400)
        self.post("/api/config", {"limit_threshold": 90, "evil_key": 1})
        s = json.loads(self.get("/api/state").read())
        self.assertEqual(s["cfg"]["limit_threshold"], 90)
        self.assertNotIn("evil_key", self.app.cfg)                  # izinli olmayan anahtar yazılmaz

    def test_file_roundtrip_and_sse_hello(self):
        p = str(__import__("pathlib").Path(_TMP) / "not.txt")
        self.post("/api/file", {"path": p, "text": "merhaba"})
        self.assertEqual(json.loads(self.get("/api/file?path=" + urllib.parse.quote(p)).read())["text"], "merhaba")
        r = self.get("/api/events?token=" + self.app.token, token=False)
        self.assertEqual(r.fp.readline().strip(), b": hello")
        r.close()


if __name__ == "__main__":
    unittest.main()
