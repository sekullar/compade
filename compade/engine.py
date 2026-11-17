"""Compade motoru: iş planlama, ajan çalıştırma, hesap yedeklemesi (limit dolunca geçiş), doğrulama, kayıt."""
import datetime
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from . import accounts as acc_mod
from . import config, ledger, limits, rolestore, wincred

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
NOISE = re.compile(r"^(> (build|plan) · .*|\s*)$")
TOKENS = re.compile(r"tokens? used\D{0,8}([\d][\d.,]*)", re.I)

ROLE_HEADER = """# Compade — görev
Sen Seku Software ekibinde **{role}** rolündesin ({model} modeli). Ekibin başı kullanıcıdır; Claude Code sıradan bir araçtır.
Rolünün odağı: {brief}

## Kurallar
- Yanıtı **Türkçe** yaz.
- {mode}
- {shell_rule}
- Bilmediğin şeyi uydurma. Tahmini "tahmin", emin olmadığını "emin değilim" diye işaretle.
- Projedeki bir dosyadan bilgi kullanıyorsan dosya yolunu (ve satırı) belirt.
- Gereksiz giriş cümlesi yazma; doğrudan işe başla.

## Teslim biçimi
1. **Özet** (en çok 3 madde)
2. **Çıktı** (görevin istediği asıl iş)
3. **Riskler / dikkat**
4. **Emin olmadıklarım ve eksik bilgi**

---
## Görev
"""


def exe(name):
    return {"codex": acc_mod._exe_codex, "agy": acc_mod._exe_agy}.get(name, lambda: None)() or None


def exe_opencode():
    p = Path(os.environ.get("APPDATA", "")) / "npm/node_modules/opencode-ai/bin/opencode.exe"
    if p.exists():
        return str(p)
    import shutil
    return shutil.which("opencode.exe") or shutil.which("opencode") or "opencode"


def exe_claude():
    """claude'un gerçek exe'si. npm'in claude.CMD kabuğu cmd.exe'den geçer; cmd uzun sistem talimatındaki tırnak ve
    satır sonlarını bozup argümanları böler ("'medium' is not recognized..."). Kabuğun çağırdığı exe'yi doğrudan kullan."""
    import shutil
    found = shutil.which("claude") or shutil.which("claude.exe")
    if found and found.lower().endswith((".cmd", ".bat")):
        real = Path(found).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if real.is_file():
            return str(real)
    return found


def clean(text):
    lines = [ANSI.sub("", l).rstrip() for l in (text or "").splitlines()]
    return "\n".join(l for l in lines if not NOISE.match(l)).strip()


def kill_tree(p):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
    else:
        p.kill()


class Handle:
    """Bir işin iptal tutamacı."""

    def __init__(self):
        self.cancelled = False
        self.proc = None

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            kill_tree(self.proc)


class Engine:
    def __init__(self, cfg=None):
        self.cfg = cfg if cfg is not None else config.load()
        self.roles = rolestore.load()
        self.acc = acc_mod.Accounts(self.cfg)
        self.active = {}          # run_id -> {"handles":[...], "workers":[...], "started":..}
        self._lock = threading.Lock()

    def reload_roles(self):
        self.roles = rolestore.load()

    # ---------- planlama ----------
    def internal(self, mk):
        return self.roles["models"].get(mk, {}).get("runtime") in ("manual", None)

    def avoided(self, mk):
        avoid = set(self.cfg.get("avoid_models") or [])
        model = self.roles["models"].get(mk, {})
        return mk in avoid or f"{model.get('runtime')}:{model.get('id')}" in avoid or model.get("runtime") in avoid

    def plan(self, role_keys=(), model_keys=(), second=False, as_role=None):
        jobs, skipped = [], []
        R, M = self.roles["roles"], self.roles["models"]
        for rk in role_keys:
            if rk not in R:
                raise ValueError(f"Bilinmeyen rol: {rk}")
            ms = R[rk]["models"]
            use = ms if second else ms[:1]
            if not second and self.roles["models"].get(use[0], {}).get("runtime") == "manual" and len(ms) > 1:
                skipped.append({"role": rk, "model": use[0]})
                use = ms[1:2]
            if not second and use and self.avoided(use[0]):      # kullanıcının kaçındığı model (ör. limiti dolan): başka dış model varsa onu seç
                alt = [m for m in ms if not self.avoided(m) and not self.internal(m)]
                if alt:
                    use = alt[:1]
                else:
                    raise ValueError(f"Rolün tek modeli avoid_models içinde: {use[0]}")
            for mk in use:
                (skipped if self.roles["models"].get(mk, {}).get("runtime") == "manual" else jobs).append({"role": rk, "model": mk})
        for mk in model_keys:
            if mk not in M:
                raise ValueError(f"Bilinmeyen model: {mk}")
            (skipped if self.roles["models"].get(mk, {}).get("runtime") == "manual" else jobs).append({"role": as_role, "model": mk})
        seen = set()
        for j in jobs:
            base = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{j['role'] or 'genel'}-{j['model']}").strip("-")   # ':' '/' dosya adında (Windows ADS) sorun çıkarır
            tag, n = base, 2
            while tag in seen:
                tag, n = f"{base}-{n}", n + 1
            seen.add(tag)
            j["tag"] = tag
        return jobs, skipped

    def build_prompt(self, job, task, write, files):
        role = self.roles["roles"].get(job["role"]) if job.get("role") else None
        mode = ("Görevde izin verilen klasördeki dosyaları değiştirebilirsin; kapsam dışına dokunma."
                if write else "Dosya DEĞİŞTİRME. Yalnız oku ve yanıt yaz.")
        # Codex dosyaları kabuk komutuyla okur; "kabuk çalıştırma" kuralı onu körleştirir (seku.py'da görülen hata).
        if self.roles["models"].get(job["model"], {}).get("runtime") == "codex":
            shell_rule = ("Dosya okumak için salt-okunur kabuk komutları (Get-Content, rg, dir) kullanabilirsin"
                          + ("; testi de çalıştırabilirsin" if write else "") + ". İnternete gönderim, commit/push yapma.")
        else:
            shell_rule = "Kabuk komutu çalıştırma, internete gönderim yapma, commit/push yapma."
        head = ROLE_HEADER.format(role=role["name"] if role else "Uzman", model=job["model"],
                                  brief=(role["brief"] + ("\n\n" + role["prompt"] if role.get("prompt") else "") if role else "Görevi eksiksiz yap."), mode=mode,
                                  shell_rule=shell_rule)
        if files:
            head = head.replace("---\n## Görev", "Ek dosyalar (oku/incele):\n" + "\n".join(f"- {f}" for f in files) + "\n\n---\n## Görev")
        if role and not role.get("chief") and not role.get("design") and "tasar" not in role.get("name", "").lower():
            head += ('\n## Çıktı biçimi\nİlk bölüm `## Özet` (en çok 5 madde, dosya yolları + sonuç). Sonra gerekirse ayrıntı. '
                     'Kodu/dosya içeriğini tekrar yapıştırma; değişen dosyaları yol + tek satır açıklamayla listele.\n'
                     'Yanıtın sonuna zorunlu olarak tek ```compade-report JSON bloğu ekle: '
                     '{"status":"done|blocked|failed|needs_input","summary":"≤300 karakter","files":["yol"],"needs":"şeften ne gerekiyor"}. '
                     'Yapamadıysan veya takıldıysan bunu dürüstçe bildir.\n')
        return head + task.strip() + "\n"

    # ---------- komut ----------
    def command(self, model_key, prompt_file, cwd, write, files, account, effort=None):
        m = self.roles["models"][model_key]
        rt = m["runtime"]
        env = self.acc.env_for(account) if account else os.environ.copy()
        stdin = out_file = None
        if rt == "claude":
            executable = exe_claude()
            if not executable:
                raise FileNotFoundError("Claude Code bulunamadı (claude CLI PATH içinde değil).")
            # İstem stdin'den: Windows komut satırı ~8 KB'ı aşınca "The command line is too long" veriyordu.
            cmd = [executable, "-p", "--output-format", "text"]
            stdin = prompt_file.read_text(encoding="utf-8")
            if m.get("id") and m["id"] != "default":
                cmd += ["--model", m["id"]]
            if effort:
                cmd += ["--effort", effort]
            if write:
                cmd += ["--permission-mode", "acceptEdits"]
        elif rt == "codex":
            out_file = prompt_file.with_name(prompt_file.name.replace("prompt-", "last-"))
            out_file.unlink(missing_ok=True)      # önceki denemenin bayat çıktısını okuma
            cmd = [exe("codex"), "exec", "-s", "workspace-write" if write else "read-only", "-C", str(cwd),
                   "--skip-git-repo-check", "-o", str(out_file)]
            if m.get("id") and m["id"] != "default":
                cmd += ["-m", m["id"]]
            if effort:
                cmd += ["-c", f'model_reasoning_effort="{effort}"']
            for f in files:
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    cmd += ["-i", f]
            cmd += ["-"]
            stdin = prompt_file.read_text(encoding="utf-8")
        elif rt == "agy":
            msg = (f"Read the task file {prompt_file} and do exactly what it asks. Answer in Turkish. "
                   "Use only your file-reading tool; do not run shell commands.")
            if files:
                msg += " Also read these files it lists: " + ", ".join(files)
            cmd = [exe("agy"), "--mode", "accept-edits" if write else "plan", "--print-timeout", "0s",
                   "--add-dir", str(prompt_file.parent), "--add-dir", str(cwd)]
            if m.get("id") and m["id"] != "default":
                cmd += ["--model", m["id"]]
            for f in files:
                cmd += ["--add-dir", str(Path(f).parent)]
            cmd += ["-p", msg]
        elif rt == "opencode":
            # v2'nin veri tabanı şeması v1'den farklı; eski kullanıcı verisinin açılış hatası yaratmaması için yalıt.
            env["XDG_DATA_HOME"] = str(Path(os.environ.get("TEMP", config.HOME)) / "oc-data")
            cmd = [exe_opencode(), "run", "Ekli görev dosyasını oku ve içindekini eksiksiz yap. Yanıt Türkçe."]
            if m.get("id") and m["id"] != "default":
                cmd += ["-m", m["id"]]
            if not write:
                cmd += ["--agent", "plan"]
            else:
                cmd += ["--auto"]
            cmd += ["--archived"]
            cmd += ["-f", str(prompt_file)] + [x for f in files for x in ("-f", f)]
        else:
            raise ValueError(rt)
        return cmd, env, stdin, out_file

    def opencode_models(self):
        try:
            p = subprocess.run([exe_opencode(), "models"], capture_output=True, text=True, timeout=15)
            return [line.strip().split()[-1] for line in p.stdout.splitlines() if line.strip()] if p.returncode == 0 else []
        except (OSError, subprocess.SubprocessError):
            return []

    # ---------- tek çalıştırma ----------
    # aynı hatayı tekrar tekrar üreten işçiyi (ör. Codex apply_patch döngüsü) zaman aşımını beklemeden durdur
    STUCK_PATTERN = re.compile(r"apply_patch verification failed|invalid patch")
    STUCK_LIMIT = 4

    def _run_process(self, cmd, env, stdin, cwd, timeout, handle):
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        p = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                             creationflags=flags)
        handle.proc = p
        chunks = {"out": [], "err": []}
        hits = [0]

        def pump(stream, key):
            try:
                for line in iter(stream.readline, ""):
                    chunks[key].append(line)
                    if self.STUCK_PATTERN.search(line):
                        hits[0] += 1
            except (OSError, ValueError):
                pass

        def feed():
            try:
                p.stdin.write(stdin)
                p.stdin.close()
            except (OSError, ValueError):
                pass

        threads = [threading.Thread(target=pump, args=(p.stdout, "out"), daemon=True),
                   threading.Thread(target=pump, args=(p.stderr, "err"), daemon=True)]
        if stdin:
            threads.append(threading.Thread(target=feed, daemon=True))
        for t in threads:
            t.start()
        deadline, status, note = time.time() + timeout, None, ""
        while p.poll() is None:
            if time.time() > deadline:
                kill_tree(p)
                status = "timeout"
                break
            if hits[0] >= self.STUCK_LIMIT:
                kill_tree(p)
                status = "error"
                note = f"\n[Compade] Aynı hata {hits[0]} kez tekrarlandı (apply_patch reddi); işçi zaman aşımını beklemeden durduruldu. Dosyayı tek yamada tek kez düzenle ya da küçük parçalara böl."
                break
            time.sleep(0.4)
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            kill_tree(p)
        for t in threads:
            t.join(3)
        out, err = "".join(chunks["out"]), "".join(chunks["err"]) + note
        if status is None:
            status = "ok" if p.returncode == 0 else "error"
        if handle.cancelled:
            status = "cancelled"
        return status, out, err, p.returncode

    def _attempt(self, job, mk, account, ctx, handle):
        """Bir modelle, bir hesapla çalıştır. Dönüş: sonuç sözlüğü (+ "limit": bool)."""
        pf = ctx["run_dir"] / f"prompt-{job['tag']}.md"
        pf.write_text(self.build_prompt({**job, "model": mk}, ctx["task"], ctx["write"], ctx["files"]), encoding="utf-8")
        t0 = time.time()
        res = {"status": "error", "model": mk, "account": account["id"] if account else None, "chars": 0}
        cmd, env, stdin, out_file = self.command(mk, pf, ctx["cwd"], ctx["write"], ctx["files"], account,
                                                 job.get("effort") if mk == job.get("model") else None)
        if not cmd[0]:
            raise FileNotFoundError(f"{self.roles['models'][mk]['runtime']} bulunamadı")
        status, out, err, code = self._run_process(cmd, env, stdin, ctx["cwd"], ctx["timeout"], handle)
        body = clean(out_file.read_text(encoding="utf-8", errors="replace")) if out_file and out_file.exists() else clean(out)
        errc = clean(err)
        if not body and errc:
            body, status = errc, ("error" if status == "ok" else status)
        status, limit, note = self.classify(status, body, errc)
        if note:
            res["note"] = note
        m = TOKENS.search(err + "\n" + out)
        res.update(status=status, body=body, err=errc, exit=code, chars=len(body), seconds=round(time.time() - t0, 1),
                   tokens=int(re.sub(r"[.,]", "", m.group(1))) if m else None)
        if limit is not None:
            res["limit"] = limit
        return res

    def classify(self, status, body, errc):
        """Sonuç durumunu, limit mi olduğunu ve notu belirle. -> (status, limit|None, note|None)

        Limit deseni YALNIZ süreç başarısızsa ya da yanıt kısa/boşsa aranır. Uzun, başarılı bir yanıtın içeriğinde
        'rate limit', 'quota' gibi sözcüklerin geçmesi (ör. kod incelemesi) hesabı bekletmemeli (canlıda yaşandı).
        """
        limit, note = None, None
        if status in ("error", "timeout", "suspicious") and re.search(r"usage limit|rate limit|5[- ]hour limit", errc + "\n" + (body if len(body) < 800 else ""), re.I):
            return "limit", True, None
        if status == "ok" and len(body) < 150:
            status = "suspicious"
        if status in ("error", "timeout", "suspicious"):
            limit = limits.is_limit_error(errc + "\n" + (body if len(body) < 800 else ""), self.cfg["limit_patterns"])
        elif status == "ok" and limits.is_limit_error(body[:1500], self.cfg["refusal_patterns"]):
            status, note = "suspicious", "Yanıt işi yapamadığını söylüyor (erişim/okuma sorunu olabilir)"
        return status, limit, note

    # ---------- yedekli çalıştırma ----------
    def execute(self, job, ctx, handle, emit):
        tag, primary = job["tag"], job["model"]
        chain = [primary]
        fb = self.cfg.get("fallback", {})
        # yedek zinciri model adıyla (gemini) ya da çalışma zamanı adıyla (agy) tanımlanabilir
        for mk in fb.get(primary) or fb.get(self.roles["models"][primary]["runtime"]) or []:
            if mk in self.roles["models"] and mk not in chain and not self.internal(mk) and not self.avoided(mk):
                chain.append(mk)
        if self.avoided(primary):
            if not chain[1:]:
                return {"status": "error", "model": primary, "body": f"İş başlatılmadı: {primary} avoid_models içinde ve kullanılabilir yedek yok.", "chars": 0, "seconds": 0}
            chain = chain[1:]
        notes = []
        last = {"status": "error", "model": primary, "account": None, "chars": 0, "seconds": 0, "body": ""}
        for mk in chain:
            rt = self.roles["models"][mk]["runtime"]
            if ctx["write"] and mk != primary and rt == "opencode":
                continue  # yazma işinde ücretsiz modele düşme
            accts = self.acc.available(rt) if rt in ("codex", "agy") else [None]
            if not accts:
                notes.append(f"{mk}: kullanılabilir hesap yok")
                emit("nohosts", {"tag": tag, "model": mk})
                continue
            if mk != primary:
                emit("fallback", {"tag": tag, "from": primary, "to": mk, "fallback_from": primary})
            for a in accts:
                if handle.cancelled:
                    return {**last, "status": "cancelled", "notes": notes}
                if a and not self.acc.acquire(a["id"]):
                    continue
                lock = acc_mod.AGY_LOCK if rt == "agy" and self.acc.multi_agy() else None
                locked = False
                try:
                    if lock:
                        while not lock.acquire(timeout=0.5):       # iptal edilen iş kilidi sonsuza dek beklemesin
                            if handle.cancelled:
                                return {**last, "status": "cancelled", "notes": notes}
                        locked = True
                        if handle.cancelled:
                            return {**last, "status": "cancelled", "notes": notes}
                        # kilit beklerken başka iş bu hesabı limitli bulmuş olabilir: durumu şimdi yeniden doğrula
                        if a and self.acc.status(a)["state"] != "ready":
                            continue
                    if rt == "agy" and a:
                        self.acc.agy_activate(a["id"])
                    emit("start", {"tag": tag, "model": mk, "account": a["id"] if a else None})
                    res = self._attempt(job, mk, a, ctx, handle)
                except (wincred.CredError, FileNotFoundError, ValueError) as e:
                    res = {"status": "error", "model": mk, "account": a["id"] if a else None, "body": f"BAŞLATILAMADI: {e}",
                           "err": str(e), "chars": 0, "seconds": 0}
                finally:
                    if locked:
                        try:
                            if rt == "agy":
                                self.acc.agy_sync_back()
                        finally:
                            lock.release()                      # senkron hata verse bile kilit mutlaka bırakılır
                    if a:
                        self.acc.release(a["id"])
                last = res
                if res.get("limit"):
                    if a:
                        wait = self.acc.mark_limit(a["id"], res.get("err", "") or res.get("body", ""))
                        notes.append(f"{a['id']} limit doldu ({limits.fmt_wait(wait)}), sıradakine geçildi")
                        emit("limit", {"tag": tag, "account": a["id"], "wait": wait})
                    else:
                        notes.append(f"{mk}: limit doldu, sıradakine geçildi")
                    continue
                if res["status"] == "ok" and a:
                    self.acc.mark_ok(a["id"])
                res["notes"] = notes
                res["fell_back"] = mk != primary
                return res
        last["notes"] = notes
        last["status"] = "limit" if any("limit" in n or "hesap yok" in n for n in notes) else last["status"]
        return last

    def verify(self, cmd, cwd, timeout=300):
        try:
            r = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True, errors="replace", timeout=timeout)
            tail = clean((r.stdout + "\n" + r.stderr))[-600:]
            return ("pass" if r.returncode == 0 else "fail"), tail
        except subprocess.TimeoutExpired:
            return "fail", "doğrulama zaman aşımı"

    # ---------- toplu iş ----------
    def make_run_dir(self, name=None):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", (name or "is").lower()).strip("-")[:40] or "is"
        run_dir = config.RUNS / f"{stamp}-{slug}"
        n = 2
        while run_dir.exists():
            run_dir = config.RUNS / f"{stamp}-{slug}-{n}"
            n += 1
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def run(self, task, jobs, cwd=None, write=False, files=(), verify=None, name=None, timeout=None,
            on_event=None, run_id=None, run_dir=None):
        """Eşzamanlı çalıştırır (çağıran thread'i bloklar). Dönüş: (run_dir, results)."""
        cwd = Path(cwd or os.getcwd()).resolve()
        files = [str(Path(f).resolve()) for f in files]
        run_dir = Path(run_dir) if run_dir else self.make_run_dir(name)
        (run_dir / "task.md").write_text(task, encoding="utf-8")
        run_id = run_id or run_dir.name

        def emit(kind, data):
            if on_event:
                try:
                    on_event(kind, {"run": run_id, **data})
                except Exception:
                    pass

        ctx = {"run_dir": run_dir, "task": task, "cwd": cwd, "write": write, "files": files,
               "timeout": timeout or self.cfg["timeout"]}
        handles = {j["tag"]: Handle() for j in jobs}
        with self._lock:
            self.active[run_id] = {"handles": handles, "tags": [j["tag"] for j in jobs], "started": time.time(), "dir": str(run_dir)}
        results, rl = [], threading.Lock()

        def worker(job):
            h = handles[job["tag"]]
            emit("queued", {"tag": job["tag"], "model": job["model"]})
            try:
                res = self.execute(job, ctx, h, emit)
            except Exception as e:  # noqa
                res = {"status": "error", "model": job["model"], "body": f"BAŞLATILAMADI: {e}", "chars": 0, "seconds": 0}
            res.update(tag=job["tag"], role=job.get("role"))
            body = res.pop("body", "") or ""
            (run_dir / f"out-{job['tag']}.md").write_text(body + "\n", encoding="utf-8")
            if res.get("err"):
                (run_dir / f"err-{job['tag']}.log").write_text(res["err"] + "\n", encoding="utf-8")
            res["summary"] = body.strip().replace("\n", " ")[:240]
            if verify and res["status"] == "ok":
                res["verify"], res["verify_tail"] = self.verify(verify, cwd)
            else:
                res["verify"] = None
            res.pop("err", None)
            ledger.append({"run": run_id, **{k: res.get(k) for k in (
                "tag", "role", "model", "account", "status", "seconds", "chars", "tokens", "verify", "fell_back")},
                           "effort": job.get("effort"), "runtime": self.roles["models"].get(res.get("model") or job["model"], {}).get("runtime")})
            with rl:
                results.append(res)
            emit("done", {"tag": job["tag"], "result": res})

        threads = [threading.Thread(target=worker, args=(j,), daemon=True) for j in jobs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        order = {j["tag"]: i for i, j in enumerate(jobs)}
        results.sort(key=lambda r: order[r["tag"]])
        self._write_reports(run_dir, task, cwd, write, results)
        with self._lock:
            self.active.pop(run_id, None)
        emit("finished", {"dir": str(run_dir), "results": results})
        return run_dir, results

    def submit(self, *args, on_event=None, **kw):
        """Arka planda başlat (arayüz için). Dönüş: thread."""
        t = threading.Thread(target=self.run, args=args, kwargs={**kw, "on_event": on_event}, daemon=True)
        t.start()
        return t

    def cancel_run(self, run_id):
        """Yalnız verilen çalışmayı durdurur; bilinmeyen/bitmiş kimlikte hiçbir şey yapmaz."""
        with self._lock:
            r = self.active.get(run_id)
        for h in (r["handles"].values() if r else ()):
            h.cancel()

    def cancel_all(self, run_id=None):
        with self._lock:
            runs = [self.active[run_id]] if run_id in self.active else list(self.active.values())
        for r in runs:
            for h in r["handles"].values():
                h.cancel()

    def _write_reports(self, run_dir, task, cwd, write, results):
        icon = {"ok": "✔", "limit": "▲", "error": "✖", "timeout": "✖", "suspicious": "?", "cancelled": "■"}
        digest = ["# Özet (Claude için kısa görünüm)", ""]
        for r in results:
            v = f" · doğrulama: {r['verify']}" if r.get("verify") else ""
            fb = " · yedek modele geçti" if r.get("fell_back") else ""
            digest.append(f"- {icon.get(r['status'], '?')} **{r['tag']}** → {r['status']} · {r.get('seconds', 0)} sn · "
                          f"{r.get('chars', 0)} karakter · hesap: {r.get('account') or '-'}{v}{fb}")
            for n in r.get("notes", []):
                digest.append(f"    - {n}")
            if r.get("summary"):
                digest.append(f"    - {r['summary']}")
        (run_dir / "digest.md").write_text("\n".join(digest) + "\n", encoding="utf-8")
        rep = [f"# Compade raporu — {run_dir.name}", "", f"Klasör: `{cwd}` · Yazma izni: {'evet' if write else 'hayır'}", "",
               "| Çalışan | Model | Hesap | Durum | Süre | Uzunluk | Doğrulama |", "|---|---|---|---|---|---|---|"]
        for r in results:
            rep.append(f"| {r['tag']} | {r.get('model')} | {r.get('account') or '-'} | {r['status']} | {r.get('seconds', 0)} sn | "
                       f"{r.get('chars', 0)} | {r.get('verify') or '-'} |")
        for r in results:
            rep += ["", "---", f"## {r['tag']} ({r['status']})", "", (run_dir / f"out-{r['tag']}.md").read_text(encoding="utf-8")]
        (run_dir / "report.md").write_text("\n".join(rep), encoding="utf-8")
