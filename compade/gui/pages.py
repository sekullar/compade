"""Ofis, Hesaplar, Çalışmalar, Ayarlar sayfaları."""
import os
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import config, ledger, limits, wincred
from . import widgets as w

PROVIDERS = [("codex", "Codex", "ChatGPT hesapları"), ("agy", "Antigravity", "Gemini hesapları"),
             ("opencode", "OpenCode", "Ücretsiz modeller")]


class OfisPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=app.th.c["bg"])
        self.app, th = app, app.th
        c = th.c
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # --- ajan kartları ---
        cards = tk.Frame(self, bg=c["bg"])
        cards.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.cards = {}
        for i, (key, name, sub) in enumerate(PROVIDERS):
            cards.columnconfigure(i, weight=1, uniform="c")
            cd = w.card(cards, th)
            cd.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            top = tk.Frame(cd, bg=c["surface"])
            top.pack(fill="x", padx=12, pady=(10, 0))
            w.label(top, th, name, "section").pack(side="left")
            st = tk.Label(top, text="", bg=c["surface"], font=th.font("ui", "small", "bold"))
            st.pack(side="right")
            w.label(cd, th, sub, muted=True).pack(fill="x", padx=12)
            bar = w.Bar(cd, th, width=170)
            bar.pack(anchor="w", padx=12, pady=(6, 2))
            info = w.label(cd, th, "", "small", muted=True)
            info.pack(fill="x", padx=12, pady=(0, 10))
            self.cards[key] = (st, bar, info)

        # --- yeni görev ---
        box = w.card(self, th)
        box.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        box.columnconfigure(1, weight=1)
        w.label(box, th, "Yeni görev", "section").grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(10, 4))
        self.task = w.text_area(box, th, height=5)
        self.task.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12)
        self.task.bind("<Control-Return>", lambda e: (self.start(), "break")[1])

        row = tk.Frame(box, bg=c["surface"])
        row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=8)
        row.columnconfigure(1, weight=1)
        w.label(row, th, "Klasör", muted=True).grid(row=0, column=0, sticky="w")
        self.cwd = tk.StringVar(value=str(Path.cwd()))
        w.entry(row, th, self.cwd).grid(row=0, column=1, sticky="ew", padx=8, ipady=3)
        w.button(row, th, "Seç", self.pick_dir).grid(row=0, column=2)
        w.label(row, th, "Doğrulama", muted=True).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.verify = tk.StringVar()
        w.entry(row, th, self.verify).grid(row=1, column=1, columnspan=2, sticky="ew", padx=8, pady=(6, 0), ipady=3)

        opts = tk.Frame(box, bg=c["surface"])
        opts.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 10))
        w.label(opts, th, "Ajanlar", muted=True).pack(side="left")
        lb = tk.Frame(opts, bg=c["surface"])
        lb.pack(side="left", padx=(8, 12))
        self.models = tk.Listbox(lb, selectmode="multiple", height=5, exportselection=False, bg=c["surface_alt"],
                                 fg=c["text"], selectbackground=c["accent"], selectforeground=c["accent_text"],
                                 relief="flat", highlightthickness=1, highlightbackground=c["border"],
                                 font=th.font("ui", "body"), activestyle="none", width=36)
        lsb = ttk.Scrollbar(lb, orient="vertical", command=self.models.yview)
        self.models.configure(yscrollcommand=lsb.set)
        self.model_keys = []
        pretty = {"codex": "Codex (ChatGPT)", "agy": "Antigravity (Gemini)"}
        for mk, m in app.engine.roles["models"].items():
            if m["runtime"] in ("codex", "agy", "opencode"):
                self.model_keys.append(mk)
                self.models.insert("end", f"{mk}  ·  " + (pretty.get(m["runtime"]) or "OpenCode: " + m["id"].split("/")[-1]))
        self.models.pack(side="left")
        lsb.pack(side="left", fill="y")
        if "codex" in self.model_keys:
            self.models.selection_set(self.model_keys.index("codex"))
        col = tk.Frame(opts, bg=c["surface"])
        col.pack(side="left", fill="y")
        w.label(col, th, "Rol (isteğe bağlı)", muted=True).pack(anchor="w")
        self.role = tk.StringVar()
        names = [""] + [f"{k} — {r['name']}" for k, r in app.engine.roles["roles"].items()]
        ttk.Combobox(col, textvariable=self.role, values=names, state="readonly", width=32).pack(anchor="w", pady=(2, 6))
        self.write = tk.BooleanVar()
        tk.Checkbutton(col, text="Yazma izni (dosyaları değiştirebilir)", variable=self.write, bg=c["surface"], fg=c["text"],
                       selectcolor=c["surface_alt"], activebackground=c["surface"], activeforeground=c["text"],
                       font=th.font("ui", "body"), highlightthickness=0).pack(anchor="w")
        btns = tk.Frame(opts, bg=c["surface"])
        btns.pack(side="right", anchor="s")
        w.button(btns, th, "Durdur", self.app.cancel).pack(side="left", padx=(0, 6))
        w.button(btns, th, "Dağıt ve Başlat  (Ctrl+Enter)", self.start, primary=True).pack(side="left")

        # --- canlı akış ---
        logbox = w.card(self, th)
        logbox.grid(row=2, column=0, sticky="nsew")
        w.label(logbox, th, "Canlı akış", "section").pack(anchor="w", padx=12, pady=(8, 2))
        self.log = w.text_area(logbox, th, mono=True, height=6, state="disabled")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        for k in ("ok", "warn", "err", "info"):
            self.log.tag_configure(k, foreground={"ok": c["success"], "warn": c["warning"], "err": c["danger"],
                                                  "info": c["info"]}[k])
        self.add_log("Compade ofisine hoş geldiniz. Ajanlar hazır; görevi yazıp Ctrl+Enter ile dağıtın.", "info")

    def pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.cwd.get() or None)
        if d:
            self.cwd.set(d)

    def add_log(self, text, tag=None):
        self.log.config(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S  ") + text + "\n", tag or "")
        self.log.see("end")
        self.log.config(state="disabled")

    def start(self):
        task = self.task.get("1.0", "end").strip()
        sel = [self.model_keys[i] for i in self.models.curselection()]
        role = self.role.get().split(" — ")[0] if self.role.get() else None
        if not task or not (sel or role):
            messagebox.showinfo("Compade", "Görevi dağıtmak için kısa bir açıklama yazın ve en az bir ajan (ya da rol) seçin.")
            return
        cwd = self.cwd.get().strip() or None
        if cwd and not Path(cwd).is_dir():
            messagebox.showerror("Compade", "Çalışma klasörü bulunamadı.")
            return
        try:
            jobs, skipped = self.app.engine.plan([role] if (role and not sel) else [], sel, as_role=role if sel else None)
        except ValueError as e:
            messagebox.showerror("Compade", str(e))
            return
        if not jobs:
            messagebox.showinfo("Compade", "Seçimde dış çalışan yok (yalnız Claude rolleri). Bu işi yönetici yapar.")
            return
        if self.write.get() and not messagebox.askyesno("Compade", "Yazma izni verildi: ajan seçili klasördeki dosyaları değiştirebilir. Devam edilsin mi?"):
            return
        self.add_log("Başlatılıyor: " + ", ".join(j["tag"] for j in jobs), "info")
        self.app.start_run(task, jobs, cwd, self.write.get(), self.verify.get().strip() or None,
                           name=(role or sel[0] if sel else "is"))

    def refresh(self):
        eng = self.app.engine
        th = self.app.th
        for key, (st, bar, info) in self.cards.items():
            running = self.app.running_count(key)
            if key == "opencode":
                state, used, txt = ("running" if running else "idle"), None, f"{len(eng.roles['models'])} model tanımlı · hesap gerekmez"
            else:
                accts = eng.acc.list(key)
                stats = [eng.acc.status(a) for a in accts if a.get("enabled", True)]
                ready = [s for s in stats if s["state"] == "ready"]
                if running:
                    state = "running"
                elif ready:
                    state = "idle"
                elif any(s["state"] in ("limit", "cooldown") for s in stats):
                    state = "limit"
                else:
                    state = "offline"
                usedv = [s["used"] for s in stats if s.get("used") is not None]
                used = max(usedv) if usedv else None
                txt = f"{len(ready)}/{len(stats)} hesap hazır"
                nxt = [s["resets_at"] for s in stats if s.get("resets_at")]
                if state == "limit" and nxt:
                    txt += f" · sıfırlanma {limits.fmt_wait(min(nxt) - time.time())}"
            st.config(text=th.status_text(state), fg=th.status_color(state))
            bar.set(used)
            info.config(text=txt + (f" · {running} iş" if running else ""))


class HesaplarPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=app.th.c["bg"])
        self.app, th = app, app.th
        c = th.c
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        bar = tk.Frame(self, bg=c["bg"])
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for txt, cmd, prim in (("Hesap ekle", self.add, True), ("Giriş yap", self.login, False),
                               ("Girişi kaydet (agy)", self.save_agy, False), ("Girişi doğrula", self.check, False),
                               ("Limiti sıfırla", self.reset, False), ("Kaldır", self.remove, False), ("Yenile", self.refresh, False)):
            w.button(bar, th, txt, cmd, primary=prim).pack(side="left", padx=(0, 6))
        box = w.card(self, th)
        box.grid(row=1, column=0, sticky="nsew")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        cols = ("label", "provider", "state", "used", "reset", "note")
        self.tree = ttk.Treeview(box, columns=cols, show="headings", selectmode="browse")
        for col, txt, wd in (("label", "Hesap", 220), ("provider", "Sağlayıcı", 100), ("state", "Durum", 130),
                             ("used", "Kullanım", 90), ("reset", "Sıfırlanma", 110), ("note", "Not", 300)):
            self.tree.heading(col, text=txt, anchor="w")
            self.tree.column(col, width=wd, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        for k in ("limit", "offline"):   # yalnız sorunlu satırlar renkli; hazır satırlar normal metin
            self.tree.tag_configure(k, foreground=th.status_color(k))
        self.msg = tk.Label(self, text="", bg=c["bg"], fg=c["text_muted"], font=th.font("ui", "small"), justify="left",
                            anchor="w", wraplength=900)
        self.msg.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.msg.config(text="Codex: her hesap ayrı bir klasörde (CODEX_HOME) tutulur, aynı anda paralel çalışabilir. "
                             "agy: kimlik Windows'ta tek kayıttır; hesaplar yedeklenip işten önce değiştirilir, bu yüzden agy işleri "
                             "birden çok hesapta sırayla çalışır. Limit dolunca Compade otomatik sıradaki hesaba geçer.")

    def _sel(self):
        s = self.tree.selection()
        return self.app.engine.acc.get(s[0]) if s else None

    def refresh(self):
        eng, th = self.app.engine, self.app.th
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for a in eng.acc.list():
            s = eng.acc.status(a)
            key = {"ready": "idle", "limit": "limit", "cooldown": "limit", "loggedout": "offline"}[s["state"]]
            note = s.get("detail", "")
            if a["provider"] == "agy" and a["id"] == eng.acc.agy_active():
                note = ("Aktif · " + note).strip(" ·")
            if s.get("plan"):
                note = f"{s['plan']} planı" + (f" · {note}" if note else "")
            self.tree.insert("", "end", iid=a["id"], tags=(key,), values=(
                a["label"], {"codex": "Codex", "agy": "Antigravity"}.get(a["provider"], a["provider"]),
                th.status_text(key) if s["state"] != "cooldown" else "▲ Bekliyor",
                f"%{s['used']:.0f}" if s.get("used") is not None else "—",
                limits.fmt_wait(s["resets_at"] - time.time()) if s.get("resets_at") else "—", note))
        for k in keep:
            if self.tree.exists(k):
                self.tree.selection_set(k)

    def add(self):
        win = tk.Toplevel(self)
        win.title("Hesap ekle")
        win.configure(bg=self.app.th.c["surface"])
        win.transient(self.winfo_toplevel())
        th = self.app.th
        w.label(win, th, "Sağlayıcı", muted=True).grid(row=0, column=0, padx=14, pady=(14, 4), sticky="w")
        prov = tk.StringVar(value="codex")
        ttk.Combobox(win, textvariable=prov, values=["codex", "agy"], state="readonly", width=22).grid(row=0, column=1, padx=14, pady=(14, 4))
        w.label(win, th, "Ad", muted=True).grid(row=1, column=0, padx=14, pady=4, sticky="w")
        lab = tk.StringVar()
        w.entry(win, th, lab).grid(row=1, column=1, padx=14, pady=4, sticky="ew", ipady=3)

        def ok():
            p = prov.get()
            if p == "agy" and not messagebox.askyesno(
                    "Compade", "Yeni agy hesabı için mevcut giriş yedeklenecek ve agy yeni giriş isteyecek.\n"
                               "Girişi tamamlayınca burada 'Girişi kaydet (agy)' düğmesine basın. Devam edilsin mi?", parent=win):
                return
            a = self.app.engine.acc.add(p, lab.get().strip() or None)
            try:
                self.app.engine.acc.start_login(a)
            except Exception as e:  # noqa
                messagebox.showerror("Compade", f"Giriş penceresi açılamadı: {e}", parent=win)
            win.destroy()
            self.refresh()
        w.button(win, th, "Ekle ve giriş yap", ok, primary=True).grid(row=2, column=0, columnspan=2, pady=14)

    def login(self):
        a = self._sel()
        if a:
            self.app.engine.acc.start_login(a)
            self.app.status("Giriş penceresi açıldı")

    def save_agy(self):
        a = self._sel()
        if not a or a["provider"] != "agy":
            messagebox.showinfo("Compade", "agy hesabı seçin.")
            return
        try:
            self.app.engine.acc.agy_save_current(a["id"])
            self.app.status("agy girişi kaydedildi: " + a["label"])
        except wincred.CredError as e:
            messagebox.showerror("Compade", str(e))
        self.refresh()

    def check(self):
        a = self._sel()
        if not a:
            return
        if a["provider"] == "codex":
            try:
                self.app.status(f"{a['label']}: " + (self.app.engine.acc.login_status_text(a) or "durum alınamadı"))
            except Exception as e:  # noqa
                self.app.status(f"Doğrulanamadı: {e}")
        else:
            self.app.status(f"{a['label']}: " + ("giriş kaydı var" if self.app.engine.acc.status(a)["state"] != "loggedout" else "giriş yok"))
        self.refresh()

    def reset(self):
        a = self._sel()
        if a:
            self.app.engine.acc.clear_cooldown(a["id"])
            self.refresh()

    def remove(self):
        a = self._sel()
        if a and messagebox.askyesno("Compade", f"'{a['label']}' listeden kaldırılsın mı? (Hesabın kendisi silinmez, yalnız Compade'den çıkar.)"):
            self.app.engine.acc.remove(a["id"])
            self.refresh()


class CalismalarPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=app.th.c["bg"])
        self.app, th = app, app.th
        c = th.c
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self.sum = tk.Label(self, text="", bg=c["bg"], fg=c["text_muted"], font=th.font("ui", "small"), anchor="w", justify="left")
        self.sum.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        left = w.card(self, th)
        left.grid(row=1, column=0, sticky="nsw", padx=(0, 8))
        self.tree = ttk.Treeview(left, columns=("when", "name"), show="headings", selectmode="browse", height=18)
        self.tree.heading("when", text="Zaman")
        self.tree.heading("name", text="İş")
        self.tree.column("when", width=120)
        self.tree.column("name", width=200)
        self.tree.pack(fill="y", expand=True, padx=1, pady=1)
        self.tree.bind("<<TreeviewSelect>>", self.show)
        right = w.card(self, th)
        right.grid(row=1, column=1, sticky="nsew")
        self.view = w.text_area(right, th, mono=True, state="disabled", wrap="word")
        self.view.pack(fill="both", expand=True, padx=1, pady=1)
        self.empty = w.empty_state(self, th, "Henüz çalışma yok",
                                   "Bir ajana iş verdiğinizde canlı çıktı ve rapor burada listelenir.")
        self.runs = []

    def refresh(self):
        self.runs = sorted([p for p in config.RUNS.glob("*") if p.is_dir()], reverse=True)[:60] if config.RUNS.exists() else []
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for p in self.runs:
            ts, _, name = p.name.partition("-")
            t2, _, name = name.partition("-")
            self.tree.insert("", "end", iid=p.name, values=(f"{ts[4:6]}/{ts[6:8]} {t2[:2]}:{t2[2:4]}", name))
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])
        elif self.runs:
            self.tree.selection_set(self.runs[0].name)   # en yeni çalışmayı göster
            self.show()
        s = ledger.summary(ledger.tail(1000))
        self.sum.config(text="Ajan başına geçmiş:  " + "   |   ".join(
            f"{k}: {v['n']} iş, %{v['pass']} geçti, ort. {v['avg_sec']} sn" for k, v in sorted(s.items())) if s else
            "Henüz kayıt yok. İlk işten sonra ajan başına başarı ve süre özeti burada görünür.")
        if self.runs:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.5, anchor="center")

    def show(self, _e=None):
        s = self.tree.selection()
        if not s:
            return
        d = config.RUNS / s[0]
        txt = ""
        for name in ("digest.md", "report.md"):
            f = d / name
            if f.exists():
                txt += f.read_text(encoding="utf-8", errors="replace") + "\n\n"
        self.view.config(state="normal")
        self.view.delete("1.0", "end")
        self.view.insert("1.0", txt or "(rapor yok)")
        self.view.config(state="disabled")


class AyarlarPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=app.th.c["bg"])
        self.app, th = app, app.th
        c = th.c
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        # RAM kartı
        ram = w.card(self, th)
        ram.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        w.label(ram, th, "Bellek (RAM) kullanımı", "section").pack(anchor="w", padx=14, pady=(12, 6))
        self.lbl = {}
        for key, txt in (("now", "Şu an (Compade)"), ("avg", "Ortalama (Compade)"), ("peak", "Tepe (Compade)"),
                         ("kids", "Ajan süreçleri (şu an)"), ("tot_avg", "Toplam ortalama (Compade + ajanlar)"),
                         ("sys", "Sistem"), ("up", "Açık kalma süresi")):
            r = tk.Frame(ram, bg=c["surface"])
            r.pack(fill="x", padx=14, pady=1)
            w.label(r, th, txt, muted=True).pack(side="left")
            v = w.label(r, th, "—", bg=c["surface"])
            v.pack(side="right")
            self.lbl[key] = v
        self.spark = tk.Canvas(ram, height=70, bg=c["surface_alt"], highlightthickness=1, highlightbackground=c["border"])
        self.spark.pack(fill="x", padx=14, pady=(10, 4))
        w.label(ram, th, "Son ölçümler (Compade süreci). Ölçüm 3 sn'de bir, hafif ve bağımlılıksız.", "small", muted=True).pack(anchor="w", padx=14, pady=(0, 12))
        # Ayarlar kartı
        st = w.card(self, th)
        st.grid(row=0, column=1, sticky="nsew")
        w.label(st, th, "Görünüm ve davranış", "section").pack(anchor="w", padx=14, pady=(12, 6))
        cfg = app.cfg
        self.theme = tk.StringVar(value=cfg["theme"])
        r = tk.Frame(st, bg=c["surface"]); r.pack(fill="x", padx=14, pady=3)
        w.label(r, th, "Tema", muted=True).pack(side="left")
        ttk.Combobox(r, textvariable=self.theme, values=["dark", "light"], state="readonly", width=10).pack(side="right")
        self.editor = tk.BooleanVar(value=cfg["editor_enabled"])
        tk.Checkbutton(st, text="Metin editörü sekmesini göster", variable=self.editor, bg=c["surface"], fg=c["text"],
                       selectcolor=c["surface_alt"], activebackground=c["surface"], activeforeground=c["text"],
                       font=th.font("ui", "body"), highlightthickness=0).pack(anchor="w", padx=14, pady=3)
        self.thr = tk.IntVar(value=cfg["limit_threshold"])
        r = tk.Frame(st, bg=c["surface"]); r.pack(fill="x", padx=14, pady=3)
        w.label(r, th, "Limit eşiği (%) — üstündeki hesap atlanır", muted=True).pack(side="left")
        ttk.Spinbox(r, from_=50, to=100, textvariable=self.thr, width=5).pack(side="right")
        self.cool = tk.IntVar(value=cfg["cooldown_minutes_default"])
        r = tk.Frame(st, bg=c["surface"]); r.pack(fill="x", padx=14, pady=3)
        w.label(r, th, "Varsayılan bekleme (dk) — süre okunamazsa", muted=True).pack(side="left")
        ttk.Spinbox(r, from_=1, to=1440, textvariable=self.cool, width=5).pack(side="right")
        self.tmo = tk.IntVar(value=cfg["timeout"])
        r = tk.Frame(st, bg=c["surface"]); r.pack(fill="x", padx=14, pady=3)
        w.label(r, th, "İş zaman aşımı (sn)", muted=True).pack(side="left")
        ttk.Spinbox(r, from_=30, to=7200, textvariable=self.tmo, width=6).pack(side="right")
        w.label(st, th, f"Veri klasörü: {config.HOME}", "small", muted=True).pack(anchor="w", padx=14, pady=(8, 0))
        row = tk.Frame(st, bg=c["surface"]); row.pack(fill="x", padx=14, pady=12)
        w.button(row, th, "Kaydet", self.save, primary=True).pack(side="left")
        w.button(row, th, "Veri klasörünü aç", lambda: os.startfile(str(config.HOME))).pack(side="left", padx=6)

    def save(self):
        cfg = self.app.cfg
        old = (cfg["theme"], cfg["editor_enabled"])
        cfg.update(theme=self.theme.get(), editor_enabled=self.editor.get(), limit_threshold=int(self.thr.get()),
                   cooldown_minutes_default=int(self.cool.get()), timeout=int(self.tmo.get()))
        config.save(cfg)
        self.app.status("Ayarlar kaydedildi")
        if old != (cfg["theme"], cfg["editor_enabled"]):
            self.app.rebuild("ayarlar")

    def refresh(self):
        s = self.app.mon.stats()
        if not s:
            return
        mb = lambda v: f"{v:.1f} MB"
        self.lbl["now"].config(text=mb(s["now_self"]))
        self.lbl["avg"].config(text=mb(s["avg_self"]))
        self.lbl["peak"].config(text=mb(s["peak_self"]))
        self.lbl["kids"].config(text=f"{mb(s['now_children'])} ({s['child_count']} süreç)")
        self.lbl["tot_avg"].config(text=mb(s["avg_total"]))
        self.lbl["sys"].config(text=f"{s['system_used']:.0f} / {s['system_total']:.0f} MB")
        up = int(s["uptime"])
        self.lbl["up"].config(text=f"{up // 3600}sa {up % 3600 // 60}dk {up % 60}sn")
        cv, c = self.spark, self.app.th.c
        cv.delete("all")
        h = [x["self"] + x["children"] for x in self.app.mon.hist]
        cw = cv.winfo_width() if cv.winfo_width() > 20 else 300
        if len(h) > 1:
            hi = max(h) * 1.7 or 1
            pts = []
            for i, v in enumerate(h):
                pts += [i * (cw - 4) / (len(h) - 1) + 2, 68 - v / hi * 64]
            cv.create_line(*pts, fill=c["accent_fg"], width=2)
            cv.create_text(6, 6, anchor="nw", text=f"üst {hi:.0f} MB", fill=c["text_muted"], font=self.app.th.font("ui", "small"))
