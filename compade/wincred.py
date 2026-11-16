"""Windows Kimlik Yöneticisi (Credential Manager) için ince ctypes sarmalayıcı.

agy (Antigravity CLI) kimliğini tek bir genel kayıtta (`gemini:antigravity`) tutar.
Compade, hesap değiştirmek için bu kaydı okur/yazar. Kimlik içeriği asla ekrana
ya da günlüğe yazılmaz; yalnız bayt olarak taşınır.
"""
import ctypes
import os
from ctypes import wintypes

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_ok = os.name == "nt"
if _ok:
    _adv = ctypes.WinDLL("advapi32", use_last_error=True)
    _adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    _adv.CredReadW.restype = wintypes.BOOL
    _adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    _adv.CredWriteW.restype = wintypes.BOOL
    _adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _adv.CredDeleteW.restype = wintypes.BOOL
    _adv.CredFree.argtypes = [ctypes.c_void_p]
    _adv.CredFree.restype = None


class CredError(RuntimeError):
    pass


def read(target):
    """Kaydı oku. Yoksa None. Dönüş: {"blob": bytes, "user": str|None, "comment": str|None}."""
    if not _ok:
        return None
    p = ctypes.POINTER(CREDENTIAL)()
    if not _adv.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            return None
        raise CredError(f"CredRead başarısız (hata {err})")
    try:
        c = p.contents
        blob = bytes(bytearray(c.CredentialBlob[i] for i in range(c.CredentialBlobSize))) if c.CredentialBlobSize else b""
        return {"blob": blob, "user": c.UserName, "comment": c.Comment}
    finally:
        _adv.CredFree(p)


def write(target, blob, user=None, comment=None):
    if not _ok:
        raise CredError("Yalnız Windows")
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob) if blob else (ctypes.c_ubyte * 1)()
    c = CREDENTIAL()
    c.Type = CRED_TYPE_GENERIC
    c.TargetName = target
    c.Comment = comment
    c.CredentialBlobSize = len(blob)
    c.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    c.Persist = CRED_PERSIST_LOCAL_MACHINE
    c.UserName = user
    if not _adv.CredWriteW(ctypes.byref(c), 0):
        raise CredError(f"CredWrite başarısız (hata {ctypes.get_last_error()})")


def delete(target):
    if not _ok:
        return False
    return bool(_adv.CredDeleteW(target, CRED_TYPE_GENERIC, 0))


def exists(target):
    try:
        return read(target) is not None
    except CredError:
        return False
