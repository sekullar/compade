"""Hesap yöneticisi: Codex (CODEX_HOME ile ayrı klasör), agy (Kimlik Yöneticisi kaydı değiştirme), OpenCode (hesapsız)."""
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

from . import agyquota, config, identity, limits, wincred

AGY_LIVE = "gemini:antigravity"        # agy'nin kimlik kaydı
SNAP = "compade:agy:{}"                # Compade'nin hesap yedekleri
AGY_BACKUP = "compade:agy:backup-original"
_state_lock = threading.RLock()
AGY_LOCK = threading.Lock()             # agy kimliği tek kayıt: hesap değişen kurulumda agy işleri sırayla


def _exe_codex():
    p = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/OpenAI/Codex/bin/codex.exe"
    return str(p) if p.exists() else "codex"


def _exe_agy():
    loc = Path(os.environ.get("LOCALAPPDATA", ""))
    for c in (loc / "Microsoft/WinGet/Packages/Google.AntigravityCLI_Microsoft.Winget.Source_8wekyb3d8bbwe/agy.exe",
              loc / "Microsoft/WinGet/Links/agy.exe", loc / "agy/bin/agy.exe"):
        if c.exists():
            return str(c)
    return "agy"


class Accounts:
    def __init__(self, cfg):
        self.cfg = cfg
        # OpenCode kimlik hesabı sağlamaz; eski yapılandırma kayıtlarını yok say.
        self.cfg["accounts"][:] = [a for a in self.cfg.get("accounts", []) if a.get("provider") != "opencode"]
        self._cache = {}
        self._usage_lock = threading.RLock()
        self._in_use = {}
        self._pending_remove = set()
        self.state = self._load_state()

    # ---------- durum dosyası ----------
    def _load_state(self):
        try:
            return json.loads(config.STATE.read_text(encoding="utf-8"))
        except Exception:
            return {"accounts": {}, "agy_active": None}

    def _save_state(self):
        with _state_lock:
            config.HOME.mkdir(parents=True, exist_ok=True)
            tmp = config.STATE.with_name(f"{config.STATE.name}.{uuid.uuid4().hex}.tmp")
            with tmp.open("w", encoding="utf-8", newline="\n") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            try:
                for i in range(6):          # Windows'ta dosya başka süreçte açıksa kısa süre bekleyip yeniden dene
                    try:
                        os.replace(tmp, config.STATE)
                        break
                    except PermissionError:
                        if i == 5:
                            raise
                        time.sleep(0.15)
            finally:
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass

    def _st(self, aid):
        return self.state.setdefault("accounts", {}).setdefault(aid, {})

    # ---------- liste ----------
    def list(self, provider=None):
        return [a for a in self.cfg["accounts"] if provider is None or a["provider"] == provider]

    def get(self, aid):
        for a in self.cfg["accounts"]:
            if a["id"] == aid:
                return a
        return None

    def duplicate_labels(self):
        by_email = {}
        for acct in self.list("codex"):
            ident = identity.codex_identity(self.codex_home(acct)) or {}
            email = ident.get("email")
            if email:
                by_email.setdefault(email.casefold(), []).append(acct)
        return {acct["id"]: [other["label"] for other in group if other["id"] != acct["id"]]
                for group in by_email.values() for acct in group}

    def agy_active(self):
        act = self.state.get("agy_active")
        if act and self.get(act):
            return act
        agy = self.list("agy")
        return agy[0]["id"] if agy else None

    def multi_agy(self):
        return len(self.list("agy")) > 1

    # ---------- Codex ----------
    def codex_home(self, acct):
        h = acct.get("home") or ""
        return Path(h) if h else Path.home() / ".codex"

    def env_for(self, acct):
        env = os.environ.copy()
        if acct["provider"] == "codex" and acct.get("home"):
            env["CODEX_HOME"] = acct["home"]
        return env

    def limit_info(self, acct, max_age=20):
        if acct["provider"] != "codex":
            return None
        c = self._cache.get(acct["id"])
        if c and c[1] is not None and time.time() - c[0] < max_age:
            return c[1]
        info = limits.codex_rate_limits(self.codex_home(acct))
        self._cache[acct["id"]] = (time.time(), info)
        return info

    # ---------- durum özeti (arayüz için) ----------
    def status(self, acct):
        """{"state": ready|cooldown|limit|loggedout, "used": %|None, "resets_at": epoch|None, "detail": str}"""
        now = time.time()
        st = self._st(acct["id"])
        out = {"state": "ready", "used": None, "resets_at": None, "detail": "", "checked_at": now}
        if acct["provider"] == "codex":
            home = self.codex_home(acct)
            if not (home / "auth.json").exists():
                return {**out, "state": "loggedout", "detail": "Bu hesap giriş yapmamış. Giriş yap'a basınca tarayıcı açılır, sonra limit görünür."}
            info = self.limit_info(acct)
            if info and info["windows"]:
                out["used"] = max(w["used"] for w in info["windows"])
                out["windows"] = info["windows"]
                ex, reset = limits.codex_exhausted(info, self.cfg["limit_threshold"], now)
                if ex:
                    out.update(state="limit", resets_at=reset, detail="Limit doldu")
                out["plan"] = info.get("plan")
        elif acct["provider"] == "agy":
            aid = acct["id"]
            active = aid == self.agy_active()
            try:   # kimlik kaydındaki e-posta (yedekli hesaplar için de doğru); yoksa agy log'u
                email = agyquota.email_from_credential(wincred.read(AGY_LIVE if active else SNAP.format(aid)))
            except Exception:
                email = None
            if not email and active:
                email = identity.agy_email()
            if email:
                known = self._st(aid).setdefault("identity", {})
                if known.get("email") != email:
                    known["email"] = email
                    self._save_state()
            if aid == self.agy_active():
                if not wincred.exists(AGY_LIVE):
                    return {**out, "state": "loggedout", "detail": "Giriş yapılmamış"}
            elif not wincred.exists(SNAP.format(aid)):
                return {**out, "state": "loggedout", "detail": "Kayıtlı giriş yok"}
        cu = st.get("cooldown_until")
        if cu and cu > now:
            out.update(state="cooldown" if out["state"] != "limit" else "limit",
                       resets_at=max(cu, out["resets_at"] or 0), detail=st.get("last_error", "Limit"))
        out["runs"] = st.get("runs", 0)
        return out

    def available(self, provider):
        """Kullanıma hazır hesaplar (sıralı). Aktif agy hesabı önce gelir (gereksiz geçiş olmasın)."""
        with self._usage_lock:
            ok = [a for a in self.list(provider) if a.get("enabled", True) and a["id"] not in self._pending_remove and self.status(a)["state"] == "ready"]
        if provider == "agy":
            act = self.agy_active()
            ok.sort(key=lambda a: a["id"] != act)
        return ok

    def acquire(self, aid):
        with self._usage_lock:
            if aid in self._pending_remove or not self.get(aid):
                return False
            self._in_use[aid] = self._in_use.get(aid, 0) + 1
            return True

    def release(self, aid):
        with self._usage_lock:
            count = self._in_use.get(aid, 0) - 1
            if count > 0:
                self._in_use[aid] = count
            else:
                self._in_use.pop(aid, None)
                if aid in self._pending_remove:
                    self._pending_remove.remove(aid)
                    self._remove_now(aid)

    # ---------- işaretleme ----------
    def mark_limit(self, aid, text=""):
        wait = limits.parse_wait_seconds(text) or self.cfg["cooldown_minutes_default"] * 60
        acct = self.get(aid)
        if acct and acct["provider"] == "codex":
            info = limits.codex_rate_limits(self.codex_home(acct))
            ex, reset = limits.codex_exhausted(info, 0.0)  # gerçek sıfırlanma zamanı
            if reset and reset > time.time():
                wait = max(wait, reset - time.time()) if not limits.parse_wait_seconds(text) else wait
        with _state_lock:
            st = self._st(aid)
            st["cooldown_until"] = time.time() + wait
            st["last_error"] = (text or "limit").strip().splitlines()[-1][:160] if text else "limit"
            self._save_state()
        return wait

    def mark_ok(self, aid):
        with _state_lock:
            st = self._st(aid)
            st["runs"] = st.get("runs", 0) + 1
            st["last_ok"] = time.time()
            st.pop("cooldown_until", None)
            self._save_state()

    def clear_cooldown(self, aid):
        with _state_lock:
            self._st(aid).pop("cooldown_until", None)
            self._save_state()

    # ---------- hesap ekle/sil ----------
    def add(self, provider, label):
        if provider not in ("codex", "agy"):
            raise ValueError("Sağlayıcı codex ya da agy olmalı")
        aid = f"{provider}-{uuid.uuid4().hex[:6]}"
        default_label = f"Codex {1 + len(self.list('codex'))}" if provider == "codex" else f"Antigravity {1 + len(self.list('agy'))}"
        acct = {"id": aid, "provider": provider, "label": label or default_label}
        if provider == "codex":
            home = config.ACCOUNTS_DIR / "codex" / aid
            for existing in self.list("codex"):
                if (existing.get("home") and Path(existing["home"]).resolve() == home.resolve()) or existing.get("label", "").casefold() == acct["label"].casefold():
                    raise ValueError("Aynı Codex hesap etiketi veya home zaten kayıtlı")
            home.mkdir(parents=True, exist_ok=True)
            acct["home"] = str(home)
        self.cfg["accounts"].append(acct)
        config.save(self.cfg)
        return acct

    def update_account(self, aid, *, label=None, note=None):
        acct = self.get(aid)
        if not acct:
            raise ValueError("Hesap bulunamadı")
        if label is not None:
            if not isinstance(label, str):
                raise ValueError("Etiket metin olmalı")
            label = label.strip()
            if not label or len(label) > 48 or any(ord(c) < 32 for c in label):
                raise ValueError("Etiket 1–48 karakter olmalı ve kontrol karakteri içermemeli")
            acct["label"] = label
            config.save(self.cfg)
        if note is not None:
            if acct["provider"] != "agy":
                raise ValueError("Not yalnız Antigravity hesapları için kullanılabilir")
            if not isinstance(note, str):
                raise ValueError("Not metin olmalı")
            note = note.strip()
            if len(note) > 240 or any(ord(c) < 32 and c not in "\t" for c in note):
                raise ValueError("Not en fazla 240 karakter olabilir")
            self._st(aid)["note"] = note
            self._save_state()
        return acct

    def remove(self, aid):
        with self._usage_lock:
            if not self.get(aid):
                return False
            if self._in_use.get(aid):
                self._pending_remove.add(aid)
                return True
            self._remove_now(aid)
            return False

    def _remove_now(self, aid):
        acct = self.get(aid)
        if not acct:
            return
        self.cfg["accounts"][:] = [a for a in self.cfg["accounts"] if a["id"] != aid]
        config.save(self.cfg)
        self.state.get("accounts", {}).pop(aid, None)
        if acct["provider"] == "agy":
            wincred.delete(SNAP.format(aid))
            if self.state.get("agy_active") == aid:
                self.state["agy_active"] = None
            if self.state.get("agy_return_to") == aid:
                self.state["agy_return_to"] = None
        self._save_state()

    # ---------- giriş ----------
    def start_login(self, acct):
        """Yeni konsol penceresinde ilgili CLI'nin giriş akışını başlat."""
        flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        if acct["provider"] == "codex":
            subprocess.Popen([_exe_codex(), "login"], env=self.env_for(acct), creationflags=flags)
        elif acct["provider"] == "agy":
            self.agy_prepare_login(acct["id"])
            subprocess.Popen([_exe_agy()], creationflags=flags)

    def login_status_text(self, acct):
        if acct["provider"] != "codex":
            return ""
        r = subprocess.run([_exe_codex(), "login", "status"], env=self.env_for(acct), capture_output=True,
                           text=True, errors="replace", timeout=30)
        txt = (r.stdout + r.stderr).strip().splitlines()
        return txt[-1] if txt else ""

    # ---------- agy kimlik değişimi ----------
    def _live(self):
        return wincred.read(AGY_LIVE)

    def _set_active(self, aid):
        with _state_lock:
            self.state["agy_active"] = aid
            self._save_state()

    def _explicit_active(self):
        """Gerçekten kaydedilmiş aktif hesap. agy_active()'in 'ilk hesap' varsayımı burada YOK:
        canlı kaydın kime ait olduğu bilinmiyorsa hiçbir hesabın yedeğinin üzerine yazılmaz."""
        with _state_lock:
            act = self.state.get("agy_active")
        return act if act and self.get(act) else None

    def _owner(self):
        """Canlı kaydın sahibi. Kayıtlı aktif hesap varsa o. Yoksa (ilk kurulum), yalnız yedeği HENÜZ olmayan
        varsayılan (ilk) agy hesabı sahip sayılır; böylece mevcut yedek asla yanlışlıkla ezilmez."""
        cur = self._explicit_active()
        if cur:
            return cur
        first = self.agy_active()
        if first and not wincred.exists(SNAP.format(first)):
            return first
        return None

    def _put(self, target, cred):
        wincred.write(target, cred["blob"], cred["user"], cred.get("comment"))

    def _backup_once(self, live):
        if live and wincred.read(AGY_BACKUP) is None:
            self._put(AGY_BACKUP, live)

    def agy_restore_backup(self):
        """Acil durum: ilk değişimden önceki özgün agy girişini geri yükle."""
        b = wincred.read(AGY_BACKUP)
        if not b:
            raise wincred.CredError("Özgün yedek yok")
        self._put(AGY_LIVE, b)

    def agy_save_current(self, aid):
        """Şu an agy'nin açık hesabını `aid` olarak yedekle (okuyup doğrula) ve aktif say."""
        live = self._live()
        if not live:
            raise wincred.CredError("agy'de açık bir giriş yok")
        self._put(SNAP.format(aid), live)
        back = wincred.read(SNAP.format(aid))
        if not back or back["blob"] != live["blob"]:
            raise wincred.CredError("Yedek doğrulanamadı")
        self._set_active(aid)

    def agy_prepare_login(self, aid):
        """Giriş için: mevcut hesabı doğrulanmış yedekle, özgün yedeği bir kez al, canlı kaydı kaldır (agy giriş istesin).
        Aynı hesabın yeniden girişi (aid == aktif) de çalışır."""
        owner = self._owner()
        live = self._live()
        if live:
            if owner and owner != aid:
                self._put(SNAP.format(owner), live)          # önce sahibinin yedeğini al ve doğrula
                back = wincred.read(SNAP.format(owner))
                if not back or back["blob"] != live["blob"]:
                    raise wincred.CredError("Yedek doğrulanamadı; giriş başlatılmadı")
            self._backup_once(live)
            wincred.delete(AGY_LIVE)
        with _state_lock:   # yeni giriş kaydedilince bu hesaba geri dönülecek (ana hesap kalıcı olarak değişmesin)
            self.state["agy_return_to"] = owner if owner and owner != aid else None
        self._set_active(aid)

    def agy_warm_token(self, timeout=40):
        """agy'yi kotasız bir komutla (`agy models`) bir kez çalıştırıp süresi dolmuş erişim anahtarını yenilet,
        sonra yenilenen girişi etkin hesabın yedeğine yaz. Çağıran AGY_LOCK'u TUTMAMALI (burada alınır)."""
        if not AGY_LOCK.acquire(timeout=5):
            return False
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            r = subprocess.run([_exe_agy(), "models"], capture_output=True, timeout=timeout, creationflags=flags)
            self.agy_sync_back()
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
        finally:
            AGY_LOCK.release()

    def agy_take_return(self, aid, consume=True):
        """Giriş kaydından sonra dönülecek önceki hesap; başarısız aktivasyonda korunabilir."""
        with _state_lock:
            prev = self.state.get("agy_return_to")
            if consume:
                self.state.pop("agy_return_to", None)
                self._save_state()
        return prev if prev and prev != aid and self.get(prev) else None

    def agy_clear_return(self):
        with _state_lock:
            self.state.pop("agy_return_to", None)
            self._save_state()

    def agy_activate(self, aid):
        """aid hesabını agy'nin canlı kaydına yaz ve doğrula. Çağıran AGY_LOCK'u tutmalı.
        Yedeği olmayan hesapta hiçbir şeyi değiştirmeden hata verir."""
        live = self._live()
        if not self.multi_agy():
            if live:
                return                                       # tek hesap: değişim yok, mevcut girişi olduğu gibi kullan
            raise wincred.CredError("agy'de açık bir giriş yok")
        owner = self._owner()
        if owner == aid and live:
            if not self._explicit_active():
                self._set_active(aid)
            return
        snap = wincred.read(SNAP.format(aid))
        if not snap:
            raise wincred.CredError(f"{aid} için kayıtlı giriş yok; önce o hesapla giriş yapıp 'Girişi kaydet'e bas")
        if live:
            self._backup_once(live)
            if owner and owner != aid:
                self._put(SNAP.format(owner), live)         # tazelenen jetonları sahibinin yedeğine yaz
            # sahip bilinmiyorsa canlı kayıt yalnız özgün yedeğe alındı, hiçbir hesap yedeği ezilmez
        self._put(AGY_LIVE, snap)
        back = wincred.read(AGY_LIVE)
        if not back or back["blob"] != snap["blob"]:
            raise wincred.CredError("Canlı kayıt yazıldıktan sonra doğrulanamadı")
        self._set_active(aid)

    def agy_sync_back(self):
        """İş bitince canlı kaydı aktif hesabın yedeğine yaz (agy jetonu yenilemiş olabilir). Asla istisna fırlatmaz."""
        try:
            cur = self._explicit_active()
            live = self._live()
            if live and cur and self.multi_agy():
                self._put(SNAP.format(cur), live)
        except wincred.CredError:
            pass

    def agy_access_token(self):
        """Etkin agy credential'ını yalnız çağıranın belleğinde kullanması için döndürür."""
        return wincred.read(AGY_LIVE)
