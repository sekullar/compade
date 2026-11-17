"""Sohbet başına yalıtılmış çalışma alanı (git worktree).

Akış:
  - Plan başlarken kullanıcının deposunda HEAD'den bir "birleştirme" dalı açılır: compade/<sohbet>
    (worktree: ~/.compade/worktrees/<sohbet>/main). Okuma görevleri burada çalışır.
  - Yazma görevi birleştirme dalının o anki ucundan kendi dalında çalışır (…/<görev>-<deneme>).
    Bitince commit edilir, doğrulama (test) geçerse birleştirme dalına merge edilir.
  - Kullanıcı farkı görür; seçtiği dosyaları kendi çalışma ağacına uygular ya da hepsini atar.
Kullanıcının çalışma ağacına plan sırasında HİÇ dokunulmaz.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import config

GIT_ID = ["-c", "user.name=Compade", "-c", "user.email=compade@localhost", "-c", "commit.gpgsign=false"]
LINK_DIRS = ("node_modules", ".venv", "venv")   # takipsiz ağır klasörler: worktree'ye bağlantı (junction) olarak verilir
_NOWIN = 0x08000000 if os.name == "nt" else 0


def git(*args, cwd=None, check=True, input=None, timeout=120):
    r = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None, capture_output=True, input=input,
                       timeout=timeout, creationflags=_NOWIN)
    out = r.stdout.decode("utf-8", "replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {(r.stderr.decode('utf-8', 'replace') or out).strip()[:400]}")
    return out if check else (r.returncode, out, r.stderr.decode("utf-8", "replace"))


def repo_root(path):
    """Git deposu kökü ya da None (git yoksa da None)."""
    try:
        code, out, _ = git("rev-parse", "--show-toplevel", cwd=path, check=False, timeout=20)
        return Path(out.strip()).resolve() if code == 0 and out.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def has_commit(root):
    code, _, _ = git("rev-parse", "--verify", "HEAD", cwd=root, check=False)
    return code == 0


def detect_verify(root):
    """Projeden güvenilir bir test komutu çıkar; bulunamazsa ''."""
    root = Path(root)
    pkg = root / "package.json"
    if pkg.exists():
        try:
            test = (json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}).get("test", "")
        except (ValueError, OSError):
            test = ""
        if test and "no test specified" not in test and (root / "node_modules").exists():
            return "npm test --silent"
    if (root / "Cargo.toml").exists():
        return "cargo test --quiet"
    if (root / "go.mod").exists():
        return "go test ./..."
    if (root / "tests").is_dir() and any((root / "tests").glob("test_*.py")):
        if (root / "pytest.ini").exists() or (root / "conftest.py").exists() or "pytest" in _read(root / "pyproject.toml"):
            return "python -m pytest -q"
        return "python -m unittest discover -s tests"
    return ""


# Şefin plana yazabileceği doğrulama komutları: yalnız derleme/test/söz dizimi; kabuk işareti (; & | > < ` $) yok
_VERIFY_OK = re.compile(
    r"^(npm (run [\w:.-]+|test|ci)|pnpm (run [\w:.-]+|test)|yarn (run [\w:.-]+|test)|"
    r"npx (--no-install )?(vite build|vitest( run)?|tsc( --noEmit)?|jest|eslint [\w./-]+)|"
    r"node --check [\w./-]+|python -m (unittest|pytest)( [\w./ -]*)?|pytest( [\w./ -]*)?|"
    r"cargo (test|build|check)|go (test|build|vet) [\w./]+|dotnet (test|build))( --?[\w-]+)*$")


def safe_verify(cmd):
    """Plan alanından gelen doğrulama komutu izin listesinde mi? (Compade bunu kendi yetkisiyle çalıştırır.)"""
    cmd = str(cmd or "").strip()
    return bool(cmd) and len(cmd) <= 120 and bool(_VERIFY_OK.match(cmd))


def _read(p):
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _slug(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")[:60] or "x"


class Workspace:
    def __init__(self, root, chat_id, base, home=None, rel="."):
        self.root = Path(root)
        self.chat_id = chat_id
        self.base = base
        self.rel = rel                          # kullanıcının seçtiği klasörün depo köküne göre yolu
        self.dir = Path(home or config.HOME) / "worktrees" / _slug(chat_id)
        self.branch = f"compade/{_slug(chat_id)}"
        self.main = self.dir / "main"
        self.tasks = {}                         # tid -> {"path","branch","sha","files","merged","verify"}

    # ---------- oluşturma ----------
    @classmethod
    def create(cls, cwd, chat_id, home=None):
        root = repo_root(cwd)
        if not root or not has_commit(root):
            return None
        base = git("rev-parse", "HEAD", cwd=root).strip()
        try:
            rel = os.path.relpath(Path(cwd).resolve(), root)
        except ValueError:
            rel = "."
        ws = cls(root, chat_id, base, home, rel)
        ws.dir.mkdir(parents=True, exist_ok=True)
        if not ws.main.exists():
            git("worktree", "add", "-f", "-B", ws.branch, str(ws.main), base, cwd=root)
            ws._link_heavy(ws.main)
        return ws

    def to_dict(self):
        return {"root": str(self.root), "base": self.base, "branch": self.branch, "dir": str(self.dir), "rel": self.rel,
                "tasks": {k: {kk: v for kk, v in t.items() if kk != "path"} | {"path": str(t["path"])} for k, t in self.tasks.items()}}

    @classmethod
    def from_dict(cls, d, chat_id, home=None):
        if not d or not d.get("root"):
            return None
        ws = cls(d["root"], chat_id, d["base"], home, d.get("rel", "."))
        ws.dir, ws.branch = Path(d.get("dir") or ws.dir), d.get("branch") or ws.branch
        ws.main = ws.dir / "main"
        for k, t in (d.get("tasks") or {}).items():
            ws.tasks[k] = {**t, "path": Path(t.get("path", ""))}
        return ws

    def sub(self, tree):
        """Bir worktree içinde kullanıcının seçtiği alt klasör."""
        p = Path(tree) / self.rel if self.rel not in ("", ".") else Path(tree)
        return p if p.is_dir() else Path(tree)

    def _link_heavy(self, tree):
        for name in LINK_DIRS:
            src, dst = self.root / self.rel / name, self.sub(tree) / name
            if src.is_dir() and not dst.exists():
                try:
                    if os.name == "nt":
                        subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)], capture_output=True,
                                       timeout=20, creationflags=_NOWIN)
                    else:
                        os.symlink(src, dst, target_is_directory=True)
                except (OSError, subprocess.SubprocessError):
                    pass

    def _unlink_heavy(self, tree):
        """Bağlantıları KALDIR (hedefi silmeden). Başarısızsa False: worktree silinmemeli."""
        ok = True
        for name in LINK_DIRS:
            dst = self.sub(tree) / name
            if os.path.lexists(dst) and (os.path.islink(dst) or _is_junction(dst)):
                try:
                    os.rmdir(dst) if os.name == "nt" else os.unlink(dst)
                except OSError:
                    ok = False
        return ok

    # ---------- görev ----------
    def task_tree(self, tid, attempt=1):
        head = git("rev-parse", "HEAD", cwd=self.main).strip()
        name = f"{_slug(tid)}-{attempt}"
        path, branch = self.dir / name, f"{self.branch}-{name}"
        if path.exists():
            self._remove_tree(path)
        git("worktree", "add", "-f", "-B", branch, str(path), head, cwd=self.root)
        self._link_heavy(path)
        self.tasks[tid] = {"path": path, "branch": branch, "sha": None, "files": [], "merged": False, "verify": None,
                           "start": head}
        return path

    def commit(self, tid, message):
        t = self.tasks[tid]
        self._unlink_heavy(t["path"])               # bağlantılar commit'e girmesin
        try:
            git("add", "-A", cwd=t["path"])
            code, _, _ = git("diff", "--cached", "--quiet", cwd=t["path"], check=False)
            if code == 0:
                return []
            git(*GIT_ID, "commit", "-q", "--no-verify", "-m", message[:200], cwd=t["path"])
            t["sha"] = git("rev-parse", "HEAD", cwd=t["path"]).strip()
            t["files"] = self._numstat(t["start"], t["sha"])
            return t["files"]
        finally:
            self._link_heavy(t["path"])

    def merge(self, tid):
        """Görev dalını birleştirme dalına al. (True, []) ya da (False, çakışan dosyalar)."""
        t = self.tasks[tid]
        if not t.get("sha"):
            return True, []
        code, out, err = git(*GIT_ID, "merge", "--no-ff", "--no-edit", "-m", f"compade: {tid}", t["branch"], cwd=self.main,
                             check=False)
        if code != 0:
            _, conflicts, _ = git("diff", "--name-only", "--diff-filter=U", cwd=self.main, check=False)
            git("merge", "--abort", cwd=self.main, check=False)
            return False, [c for c in conflicts.splitlines() if c.strip()] or [err.strip()[:200]]
        t["merged"] = True
        return True, []

    def drop_task(self, tid):
        t = self.tasks.pop(tid, None)
        if t:
            self._remove_tree(t["path"])
            git("branch", "-D", t["branch"], cwd=self.root, check=False)

    # ---------- fark / uygula ----------
    def head(self):
        return git("rev-parse", "HEAD", cwd=self.main).strip()

    def _numstat(self, a, b):
        out = git("diff", "--numstat", "-M", a, b, cwd=self.root)
        files = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                add, rem, path = parts[0], parts[1], parts[-1]
                files.append({"path": path, "add": int(add) if add.isdigit() else 0,
                              "del": int(rem) if rem.isdigit() else 0, "binary": add == "-"})
        return files

    def changes(self):
        files = self._numstat(self.base, self.head())
        status = {}
        for line in git("diff", "--name-status", "-M", self.base, self.head(), cwd=self.root).splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                status[parts[-1]] = parts[0][0]
        for f in files:
            f["status"] = {"A": "added", "D": "deleted", "R": "renamed"}.get(status.get(f["path"], "M"), "modified")
        return files

    def file_diff(self, path, limit=200_000):
        text = git("diff", "-M", self.base, self.head(), "--", path, cwd=self.root)
        return text[:limit] + ("\n… (kısaltıldı)" if len(text) > limit else "")

    def apply(self, paths):
        """Seçilen dosyaların değişikliğini kullanıcının çalışma ağacına uygular."""
        paths = [p for p in paths if p]
        if not paths:
            raise ValueError("Uygulanacak dosya seçilmedi.")
        patch = subprocess.run(["git", "diff", "--binary", "-M", self.base, self.head(), "--", *paths], cwd=str(self.root),
                               capture_output=True, timeout=120, creationflags=_NOWIN).stdout
        if not patch.strip():
            return {"ok": True, "applied": [], "mode": "boş"}
        code, _, err = git("apply", "--whitespace=nowarn", "-", cwd=self.root, check=False, input=patch)
        if code == 0:
            return {"ok": True, "applied": paths, "mode": "doğrudan"}
        code3, _, err3 = git("apply", "--3way", "--whitespace=nowarn", "-", cwd=self.root, check=False, input=patch)
        if code3 == 0:
            return {"ok": True, "applied": paths, "mode": "3yollu",
                    "note": "Senin yerel değişikliklerinle birleştirildi; dosyalar git index'ine de eklendi (stage)."}
        conflicts = re.findall(r"(?:conflicts? in|patch failed:) ?([^\s:]+)", err3 + err)
        return {"ok": False, "error": (err3 or err).strip()[:600], "conflicts": sorted(set(conflicts))}

    # ---------- temizlik ----------
    def _remove_tree(self, path):
        path = Path(path)
        if not path.exists():
            git("worktree", "prune", cwd=self.root, check=False)
            return True
        if not self._unlink_heavy(path):
            return False                          # bağlantı kaldırılamadı: hedefi silme riskine girme
        code, _, _ = git("worktree", "remove", "--force", str(path), cwd=self.root, check=False)
        if code != 0 and path.exists() and not any(_is_link(p) for p in path.rglob("*") if p.is_dir()):
            shutil.rmtree(path, ignore_errors=True)
            git("worktree", "prune", cwd=self.root, check=False)
        return True

    def cleanup(self):
        for tid in list(self.tasks):
            self.drop_task(tid)
        self._remove_tree(self.main)
        git("branch", "-D", self.branch, cwd=self.root, check=False)
        try:
            self.dir.rmdir()
        except OSError:
            pass


def _is_junction(p):
    try:
        return bool(getattr(os.path, "isjunction", lambda _: False)(p))
    except OSError:
        return False


def _is_link(p):
    return os.path.islink(p) or _is_junction(p)
