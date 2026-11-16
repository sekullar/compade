"""RAM izleyici (bağımlılıksız, Windows). Compade'nin kendisi + alt süreçleri + sistem."""
import collections
import ctypes
import os
import threading
import time
from ctypes import wintypes

AGENT_EXES = {"codex.exe", "agy.exe", "opencode.exe", "node.exe", "python.exe", "cmd.exe"}


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


class PE32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


class MEMSTATUS(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


_nt = os.name == "nt"
if _nt:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PE32)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PE32)]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]


def _proc_mb(pid):
    h = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not h:
        return 0.0
    try:
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return (pmc.PrivateUsage or pmc.WorkingSetSize) / 1048576
    finally:
        k32.CloseHandle(h)
    return 0.0


def _process_table():
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    rows = []
    if snap in (None, -1, ctypes.c_void_p(-1).value):
        return rows
    try:
        e = PE32()
        e.dwSize = ctypes.sizeof(PE32)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            rows.append((e.th32ProcessID, e.th32ParentProcessID, e.szExeFile.lower()))
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return rows


def snapshot():
    """Anlık ölçüm (MB): self, children (ajan süreçleri dahil alt süreç ağacı), system_used, system_total."""
    if not _nt:
        return {"self": 0.0, "children": 0.0, "system_used": 0.0, "system_total": 0.0, "child_count": 0}
    me = os.getpid()
    rows = _process_table()
    names = {pid: name for pid, _, name in rows}
    kids, frontier = set(), {me}
    while frontier:
        nxt = {pid for pid, ppid, _ in rows if ppid in frontier and pid not in kids and pid != me}
        kids |= nxt
        frontier = nxt
    # Arayüz penceresi (Edge) ve alt süreçleri ajan süreçlerinden ayrı say
    ui, frontier = {p for p in kids if names.get(p) == "msedge.exe"}, set()
    frontier = set(ui)
    while frontier:
        nxt = {pid for pid, ppid, _ in rows if ppid in frontier and pid in kids and pid not in ui}
        ui |= nxt
        frontier = nxt
    agents = kids - ui
    ms = MEMSTATUS()
    ms.dwLength = ctypes.sizeof(MEMSTATUS)
    k32.GlobalMemoryStatusEx(ctypes.byref(ms))
    return {"self": _proc_mb(me), "children": sum(_proc_mb(p) for p in agents), "child_count": len(agents),
            "ui": sum(_proc_mb(p) for p in ui), "ui_count": len(ui),
            "system_used": (ms.ullTotalPhys - ms.ullAvailPhys) / 1048576, "system_total": ms.ullTotalPhys / 1048576}


class Monitor:
    """Arka planda örnekler; ortalama/tepe/geçmiş verir."""

    def __init__(self, interval=3.0, keep=600):
        self.interval, self.hist = interval, collections.deque(maxlen=keep)
        self.peak_self = self.peak_total = 0.0
        self.started = time.time()
        self._stop = threading.Event()
        self._t = None
        self.last = None

    def start(self):
        self._sample()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(self.interval):
            self._sample()

    def _sample(self):
        s = snapshot()
        s["t"] = time.time()
        self.last = s
        self.hist.append(s)
        self.peak_self = max(self.peak_self, s["self"])
        self.peak_total = max(self.peak_total, s["self"] + s["children"])

    def stats(self):
        h = list(self.hist)
        if not h:
            return {}
        n = len(h)
        return {"now_ui": h[-1].get("ui", 0.0), "avg_ui": sum(x.get("ui", 0.0) for x in h) / n, "ui_count": h[-1].get("ui_count", 0),
                "now_self": h[-1]["self"], "now_children": h[-1]["children"], "child_count": h[-1]["child_count"],
                "avg_self": sum(x["self"] for x in h) / n, "avg_total": sum(x["self"] + x["children"] for x in h) / n,
                "peak_self": self.peak_self, "peak_total": self.peak_total, "samples": n,
                "uptime": time.time() - self.started,
                "system_used": h[-1]["system_used"], "system_total": h[-1]["system_total"]}
