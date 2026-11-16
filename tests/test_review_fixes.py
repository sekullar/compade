"""Compade'nin kendi kod incelemesinden (Codex + Gemini) çıkan hataların regresyon testleri.
Gerçek hesaplara ve gerçek agy kimliğine dokunmaz (sahte kayıt adları, geçici veri klasörü)."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from test_core import _TMP, _mk_config  # noqa: F401  (COMPADE_HOME'u ayarlar)

from compade import accounts as acc_mod  # noqa: E402
from compade import config, limits, wincred  # noqa: E402
from compade.engine import Engine, Handle  # noqa: E402


def _ctx(write=False):
    return {"run_dir": Path(tempfile.mkdtemp(dir=_TMP)), "task": "x", "cwd": Path(_TMP), "write": write, "files": [], "timeout": 5}


OK = lambda mk, a: {"status": "ok", "model": mk, "account": a["id"] if a else None, "body": "ok " * 80, "chars": 240, "seconds": 0}  # noqa: E731


class TestReviewFixes(unittest.TestCase):
    def setUp(self):
        config.STATE.unlink(missing_ok=True)

    def test_turkish_wait_and_bad_resets_at(self):
        self.assertEqual(limits.parse_wait_seconds("Limit doldu, 15 dakika sonra tekrar deneyin"), 900)
        self.assertEqual(limits.parse_wait_seconds("2 saat 30 dakika sonra"), 9000)
        home = Path(_TMP) / "cx-bad"
        d = home / "sessions" / "a"
        d.mkdir(parents=True, exist_ok=True)
        ev = {"payload": {"rate_limits": {"primary": {"used_percent": 99, "resets_at": "yarin"}}}}
        (d / "r.jsonl").write_text(json.dumps(ev) + "\n", encoding="utf-8")
        info = limits.codex_rate_limits(home)
        self.assertIsNone(info["windows"][0]["resets_at"])      # sayısal olmayan alan None olur, TypeError yok
        self.assertTrue(limits.codex_exhausted(info, 98)[0])

    def test_exhausted_uses_latest_reset_of_all_windows(self):
        now = time.time()
        info = {"windows": [{"used": 99, "resets_at": now + 100}, {"used": 100, "resets_at": now + 9000}]}
        ex, reset = limits.codex_exhausted(info, 98, now)
        self.assertTrue(ex)
        self.assertEqual(reset, now + 9000)

    def test_classify_no_false_positive_on_successful_long_answer(self):
        eng = Engine(_mk_config(1))
        long_ok = "Kod incelemesi: rate limit ve quota kontrolü, 429 durumu, RESOURCE_EXHAUSTED işleme. " * 20
        st, limit, _ = eng.classify("ok", long_ok, "")
        self.assertEqual((st, limit), ("ok", None))              # uzun başarılı yanıt limit sayılmaz (canlıda yaşanan hata)
        st, limit, _ = eng.classify("ok", "Dosyayı okuyamıyorum. " + "x" * 200, "")
        self.assertEqual(st, "suspicious")
        self.assertIsNone(limit)                                  # reddetme != limit
        st, limit, _ = eng.classify("error", "", "429 Too Many Requests")
        self.assertTrue(limit)
        st, limit, _ = eng.classify("ok", "usage limit reached", "")   # kısa gövde: gerçek limit mesajı olabilir
        self.assertEqual(st, "suspicious")
        self.assertTrue(limit)
        st, limit, _ = eng.classify("error", "quota " * 300, "")        # uzun hata gövdesi içerik sayılır
        self.assertFalse(limit)

    def test_fallback_key_by_runtime_name(self):
        eng = Engine(_mk_config(1, 0))            # agy hesabı yok
        eng.cfg["fallback"] = {"agy": ["codex"]}  # çalışma zamanı adıyla tanımlı
        used = []
        eng._attempt = lambda job, mk, a, ctx, h: (used.append(mk), OK(mk, a))[1]
        res = eng.execute({"tag": "g", "role": None, "model": "gemini"}, _ctx(), Handle(), lambda k, d: None)
        self.assertEqual(used, ["codex"])           # gemini -> codex (eskiden anahtar uyuşmazlığı yüzünden hiç tetiklenmiyordu)
        self.assertTrue(res["fell_back"])

    def test_cancel_while_waiting_for_agy_lock(self):
        eng = Engine(_mk_config(0, 2))
        h = Handle()
        h.cancelled = True
        eng.acc.status = lambda a: {"state": "ready"}
        acc_mod.AGY_LOCK.acquire()                  # başka iş kilidi tutuyor
        try:
            t0 = time.time()
            res = eng.execute({"tag": "g", "role": None, "model": "gemini"}, _ctx(), h, lambda k, d: None)
            self.assertEqual(res["status"], "cancelled")
            self.assertLess(time.time() - t0, 3)    # kilidi sonsuza dek beklemedi
        finally:
            acc_mod.AGY_LOCK.release()

    def test_lock_released_even_if_sync_back_raises(self):
        eng = Engine(_mk_config(0, 2))
        eng.acc.status = lambda a: {"state": "ready"}
        eng.acc.agy_activate = lambda aid: None

        def boom():
            raise RuntimeError("sync patladı")
        eng.acc.agy_sync_back = boom
        eng._attempt = lambda job, mk, a, ctx, h: OK(mk, a)
        with self.assertRaises(RuntimeError):
            eng.execute({"tag": "g", "role": None, "model": "gemini"}, _ctx(), Handle(), lambda k, d: None)
        self.assertTrue(acc_mod.AGY_LOCK.acquire(timeout=1))   # kilit takılı kalmadı
        acc_mod.AGY_LOCK.release()

    def test_account_limited_while_waiting_is_skipped(self):
        """Kilit beklerken başka iş hesabı limitli bulursa, bu iş o hesabı denemeden sıradakine geçer."""
        eng = Engine(_mk_config(0, 2))
        states = {"agy-1": "limit", "agy-2": "ready"}
        eng.acc.status = lambda a: {"state": states[a["id"]]}
        eng.acc.available = lambda rt: list(eng.cfg["accounts"]) if rt == "agy" else []   # liste eskimiş: agy-1 hâlâ içinde
        eng.acc.agy_activate = lambda aid: None
        tried = []
        eng._attempt = lambda job, mk, a, ctx, h: (tried.append(a["id"]), OK(mk, a))[1]
        res = eng.execute({"tag": "g", "role": None, "model": "gemini"}, _ctx(), Handle(), lambda k, d: None)
        self.assertEqual(tried, ["agy-2"])
        self.assertEqual(res["status"], "ok")


class TestAgySafety(unittest.TestCase):
    def setUp(self):
        self._orig = (acc_mod.AGY_LIVE, acc_mod.SNAP, acc_mod.AGY_BACKUP)
        acc_mod.AGY_LIVE, acc_mod.SNAP, acc_mod.AGY_BACKUP = "compade:test2:live", "compade:test2:snap:{}", "compade:test2:backup"
        self.targets = ["compade:test2:live", "compade:test2:snap:agy-1", "compade:test2:snap:agy-2", "compade:test2:backup"]
        for t in self.targets:
            wincred.delete(t)
        config.STATE.unlink(missing_ok=True)
        self.acc = acc_mod.Accounts(_mk_config(0, 2))
        self.acc.state = {"accounts": {}, "agy_active": None}

    def tearDown(self):
        for t in self.targets:
            wincred.delete(t)
        acc_mod.AGY_LIVE, acc_mod.SNAP, acc_mod.AGY_BACKUP = self._orig

    def test_unknown_active_never_overwrites_account_backup(self):
        wincred.write("compade:test2:snap:agy-1", b"AGY1-ESKI", "a")
        wincred.write("compade:test2:snap:agy-2", b"AGY2", "b")
        wincred.write(acc_mod.AGY_LIVE, b"BILINMEYEN-KIMLIK", "x")   # canlı kayıt kime ait belli değil
        self.acc.agy_activate("agy-2")
        self.assertEqual(wincred.read("compade:test2:snap:agy-1")["blob"], b"AGY1-ESKI")      # agy-1 yedeği ezilmedi
        self.assertEqual(wincred.read("compade:test2:backup")["blob"], b"BILINMEYEN-KIMLIK")   # kayıp olmasın diye özgün yedek
        self.assertEqual(wincred.read(acc_mod.AGY_LIVE)["blob"], b"AGY2")
        self.acc.state["agy_active"] = None
        self.acc.agy_sync_back()                                      # aktif belirsiz: yedeklere dokunmaz
        self.assertEqual(wincred.read("compade:test2:snap:agy-2")["blob"], b"AGY2")

    def test_relogin_same_account_removes_live(self):
        wincred.write(acc_mod.AGY_LIVE, b"BOZUK-JETON", "a")
        self.acc.agy_save_current("agy-1")
        self.acc.agy_prepare_login("agy-1")                           # aynı hesabın yeniden girişi
        self.assertIsNone(wincred.read(acc_mod.AGY_LIVE))             # agy giriş isteyebilsin
        self.assertEqual(wincred.read("compade:test2:backup")["blob"], b"BOZUK-JETON")

    def test_restore_backup(self):
        wincred.write(acc_mod.AGY_LIVE, b"OZGUN", "a")
        self.acc.agy_save_current("agy-1")
        self.acc.agy_prepare_login("agy-2")
        self.assertIsNone(wincred.read(acc_mod.AGY_LIVE))
        self.acc.agy_restore_backup()
        self.assertEqual(wincred.read(acc_mod.AGY_LIVE)["blob"], b"OZGUN")

    def test_first_time_single_account_uses_live_login(self):
        """Gerileme testi: hiç 'Girişi kaydet' yapılmamış tek hesapta agy canlı girişiyle çalışmalı (canlıda yaşandı)."""
        acc = acc_mod.Accounts(_mk_config(0, 1))
        acc.state = {"accounts": {}, "agy_active": None}
        wincred.write(acc_mod.AGY_LIVE, b"TEK-HESAP", "a")
        acc.agy_activate("agy-1")                                      # hata vermemeli
        self.assertEqual(wincred.read(acc_mod.AGY_LIVE)["blob"], b"TEK-HESAP")
        wincred.delete(acc_mod.AGY_LIVE)
        with self.assertRaises(wincred.CredError):
            acc.agy_activate("agy-1")                                  # giriş hiç yoksa anlamlı hata

    def test_add_second_account_first_time_saves_default_owner(self):
        """İlk kurulumda ikinci hesap eklenirken mevcut giriş, yedeği olmayan varsayılan (ilk) hesaba yedeklenir."""
        wincred.write(acc_mod.AGY_LIVE, b"ILK-HESAP", "a")
        self.acc.agy_prepare_login("agy-2")                            # state'te aktif hesap hiç kayıtlı değil
        self.assertEqual(wincred.read("compade:test2:snap:agy-1")["blob"], b"ILK-HESAP")
        self.assertIsNone(wincred.read(acc_mod.AGY_LIVE))
        wincred.write(acc_mod.AGY_LIVE, b"IKINCI", "b")
        self.acc.agy_save_current("agy-2")
        self.acc.agy_activate("agy-1")                                 # geri geçiş çalışır
        self.assertEqual(wincred.read(acc_mod.AGY_LIVE)["blob"], b"ILK-HESAP")

    def test_first_time_multi_account_adopts_live_for_default(self):
        wincred.write("compade:test2:snap:agy-2", b"IKINCI", "b")
        wincred.write(acc_mod.AGY_LIVE, b"ILK-HESAP", "a")             # aktif kayıtlı değil, agy-1'in yedeği de yok
        self.acc.agy_activate("agy-2")
        self.assertEqual(wincred.read("compade:test2:snap:agy-1")["blob"], b"ILK-HESAP")   # kayıp olmadı
        self.assertEqual(wincred.read(acc_mod.AGY_LIVE)["blob"], b"IKINCI")

    def test_failed_activate_changes_nothing(self):
        wincred.write(acc_mod.AGY_LIVE, b"A", "a")
        self.acc.agy_save_current("agy-1")
        with self.assertRaises(wincred.CredError):
            self.acc.agy_activate("agy-2")                            # yedeği yok
        self.assertEqual(wincred.read(acc_mod.AGY_LIVE)["blob"], b"A")
        self.assertEqual(self.acc.agy_active(), "agy-1")


if __name__ == "__main__":
    unittest.main()
