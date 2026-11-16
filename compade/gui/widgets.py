"""Düz (degradesiz, gölgesiz) Tkinter bileşenleri; renkler tema jetonlarından."""
import tkinter as tk
from tkinter import ttk


def style_ttk(root, th):
    c = th.c
    s = ttk.Style(root)
    s.theme_use("clam")
    root.configure(bg=c["bg"])
    s.configure(".", background=c["surface"], foreground=c["text"], font=th.font("ui", "body"), borderwidth=0)
    s.configure("Treeview", background=c["surface"], fieldbackground=c["surface"], foreground=c["text"], rowheight=30,
                borderwidth=0, font=th.font("ui", "body"), bordercolor=c["surface"], lightcolor=c["surface"],
                darkcolor=c["surface"])
    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # odak halkasız
    s.configure("Treeview.Heading", background=c["surface_alt"], foreground=c["text_muted"], relief="flat",
                font=th.font("ui", "small", "bold"), padding=(8, 6))
    s.map("Treeview", background=[("selected", c["accent"])], foreground=[("selected", c["accent_text"])])
    s.map("Treeview.Heading", background=[("active", c["border"])])
    for o in ("Vertical", "Horizontal"):
        s.configure(f"{o}.TScrollbar", background=c["surface_alt"], troughcolor=c["bg"], bordercolor=c["bg"],
                    arrowcolor=c["text_muted"], lightcolor=c["surface_alt"], darkcolor=c["surface_alt"], relief="flat")
        s.map(f"{o}.TScrollbar", background=[("active", c["border"])])
    s.configure("TCombobox", fieldbackground=c["surface_alt"], background=c["surface_alt"], foreground=c["text"],
                arrowcolor=c["text_muted"], bordercolor=c["border"], lightcolor=c["surface_alt"], darkcolor=c["surface_alt"],
                padding=4)
    s.map("TCombobox", fieldbackground=[("readonly", c["surface_alt"])], foreground=[("readonly", c["text"])],
          selectbackground=[("readonly", c["surface_alt"])], selectforeground=[("readonly", c["text"])])
    root.option_add("*TCombobox*Listbox.background", c["surface_alt"])
    root.option_add("*TCombobox*Listbox.foreground", c["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", c["accent_text"])
    root.option_add("*TCombobox*Listbox.font", th.font("ui", "body"))
    s.configure("TSpinbox", fieldbackground=c["surface_alt"], foreground=c["text"], background=c["surface_alt"],
                arrowcolor=c["text_muted"], bordercolor=c["border"], lightcolor=c["surface_alt"], darkcolor=c["surface_alt"],
                insertcolor=c["text"])
    return s


def button(parent, th, text, cmd, primary=False, **kw):
    c = th.c
    bg = c["accent"] if primary else c["surface_alt"]
    fg = c["accent_text"] if primary else c["text"]
    hov = c["accent_hover"] if primary else c["border"]
    b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, activebackground=hov, activeforeground=fg,
                  relief="flat", bd=0, padx=14, pady=6, cursor="hand2", highlightthickness=0,
                  font=th.font("ui", "body", "bold"), **kw)
    b.bind("<Enter>", lambda _e: b.config(bg=hov))
    b.bind("<Leave>", lambda _e: b.config(bg=bg))
    return b


def card(parent, th, **kw):
    return tk.Frame(parent, bg=th.c["surface"], highlightbackground=th.c["border"], highlightthickness=1, **kw)


def label(parent, th, text="", kind="body", muted=False, bg=None, **kw):
    weight = "bold" if kind in ("title", "section", "brand") else "normal"
    fam = "brand" if kind == "brand" else "ui"
    return tk.Label(parent, text=text, bg=bg or th.c["surface"], fg=th.c["text_muted"] if muted else th.c["text"],
                    font=th.font(fam, kind if kind in th.sizes else "body", weight), anchor="w", **kw)


def entry(parent, th, var=None, **kw):
    c = th.c
    return tk.Entry(parent, textvariable=var, bg=c["surface_alt"], fg=c["text"], insertbackground=c["text"],
                    relief="flat", highlightthickness=1, highlightbackground=c["border"], highlightcolor=c["accent_fg"],
                    font=th.font("ui", "body"), **kw)


def text_area(parent, th, mono=False, **kw):
    c = th.c
    return tk.Text(parent, bg=c["editor_bg"] if mono else c["surface_alt"], fg=c["editor_fg"] if mono else c["text"],
                   insertbackground=c["editor_fg"], selectbackground=c["editor_selection"], relief="flat",
                   highlightthickness=1, highlightbackground=c["border"], highlightcolor=c["accent_fg"],
                   font=th.font("mono" if mono else "ui", "mono" if mono else "body"), padx=8, pady=6, **kw)


def empty_state(parent, th, title, hint):
    f = tk.Frame(parent, bg=th.c["surface"])
    label(f, th, "∅", "brand", muted=True).pack(pady=(24, 4))
    label(f, th, title, "section").pack()
    tk.Label(f, text=hint, bg=th.c["surface"], fg=th.c["text_muted"], font=th.font("ui", "body"), wraplength=420,
             justify="center").pack(pady=(4, 24))
    return f


class Bar(tk.Canvas):
    """Kullanım çubuğu. Renk eşiği: <70 başarı, <90 uyarı, ≥90 tehlike. Yüzde metni yanında (yalnız renge güvenme)."""

    def __init__(self, parent, th, width=140, height=14, **kw):
        super().__init__(parent, width=width, height=height, bg=th.c["surface"], highlightthickness=0, **kw)
        self.th, self.w, self.h = th, width, height
        self.set(None)

    def set(self, pct):
        self.delete("all")
        c = self.th.c
        self.create_rectangle(0, 0, self.w, self.h, fill=c["surface_alt"], outline=c["border"])
        if pct is None:
            self.create_text(self.w / 2, self.h / 2, text="—", fill=c["text_muted"], font=self.th.font("ui", "small"))
            return
        pct = max(0.0, min(100.0, pct))
        col = c["success"] if pct < 70 else c["warning"] if pct < 90 else c["danger"]
        self.create_rectangle(1, 1, 1 + (self.w - 2) * pct / 100, self.h - 1, fill=col, outline="")
        self.create_text(self.w / 2, self.h / 2, text=f"%{pct:.0f}", fill=c["text"], font=self.th.font("ui", "small", "bold"))


def draw_logo(parent, th, size=28, bg=None):
    """C biçimli ofis bloğu + amber ajan masası (design/logo.svg ile aynı geometri)."""
    cv = tk.Canvas(parent, width=size, height=size, bg=bg or th.c["surface"], highlightthickness=0)
    k = size / 256
    teal, amber = "#0F766E" if th.name == "light" else "#14A398", "#F59E0B"
    for x0, y0, x1, y1 in ((48, 32, 208, 80), (48, 32, 96, 224), (48, 176, 208, 224)):
        cv.create_rectangle(x0 * k, y0 * k, x1 * k, y1 * k, fill=teal, outline="")
    cv.create_rectangle(128 * k, 104 * k, 208 * k, 152 * k, fill=amber, outline="")
    return cv
