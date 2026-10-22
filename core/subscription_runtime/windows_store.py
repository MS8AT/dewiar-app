"""Закрытый stdio-помощник Windows: DPAPI, ACL и межпроцессный мьютекс.

Секреты не передаются в аргументах процесса и не выводятся в stderr.
"""
import base64
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import sys

MAX_BYTES = 3 * 1024 * 1024
ENTROPY = b"ai-worckbook.chatgpt-subscription.dpapi.v1"


def api():
    if os.name != "nt":
        raise RuntimeError("windows_required")
    k = c.WinDLL("kernel32", use_last_error=True)
    a = c.WinDLL("advapi32", use_last_error=True)
    k.GetCurrentProcess.restype = w.HANDLE
    k.LocalFree.argtypes = [c.c_void_p]
    k.LocalFree.restype = c.c_void_p
    k.CloseHandle.argtypes = [w.HANDLE]
    a.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    a.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    a.ConvertSidToStringSidW.argtypes = [c.c_void_p, c.POINTER(w.LPWSTR)]
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, c.POINTER(c.c_void_p), c.POINTER(w.DWORD)]
    return k, a


def current_sid(k, a):
    token = w.HANDLE()
    if not a.OpenProcessToken(k.GetCurrentProcess(), 8, c.byref(token)):
        raise RuntimeError("token")
    try:
        size = w.DWORD()
        a.GetTokenInformation(token, 1, None, 0, c.byref(size))
        buf = c.create_string_buffer(size.value)
        if not a.GetTokenInformation(token, 1, buf, size, c.byref(size)):
            raise RuntimeError("sid")
        ptr = c.cast(buf, c.POINTER(c.c_void_p))[0]
        out = w.LPWSTR()
        if not a.ConvertSidToStringSidW(ptr, c.byref(out)):
            raise RuntimeError("sid")
        try:
            return out.value
        finally:
            k.LocalFree(out)
    finally:
        k.CloseHandle(token)


class SecurityAttributes(c.Structure):
    _fields_ = [("length", w.DWORD), ("descriptor", c.c_void_p), ("inherit", w.BOOL)]


def descriptor(a, sid):
    ptr = c.c_void_p()
    # Защищённый ACL наследуется файлами сеансов; других пользователей Windows нет.
    sddl = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;" + sid + ")"
    if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, c.byref(ptr), None):
        raise RuntimeError("acl")
    return ptr, SecurityAttributes(c.sizeof(SecurityAttributes), ptr, False)


def check_acl(path, k, a, sid):
    """Отказ, если существующий каталог имеет незащищённый или расширенный DACL."""
    a.GetNamedSecurityInfoW.argtypes = [w.LPWSTR, c.c_int, w.DWORD, c.c_void_p, c.c_void_p,
                                      c.POINTER(c.c_void_p), c.c_void_p, c.POINTER(c.c_void_p)]
    a.GetSecurityDescriptorControl.argtypes = [c.c_void_p, c.POINTER(w.WORD), c.POINTER(w.DWORD)]
    a.GetAce.argtypes = [c.c_void_p, w.DWORD, c.POINTER(c.c_void_p)]
    dacl, sd = c.c_void_p(), c.c_void_p()
    if a.GetNamedSecurityInfoW(str(path), 1, 4, None, None, c.byref(dacl), None, c.byref(sd)):
        raise RuntimeError("acl")
    try:
        control, revision = w.WORD(), w.DWORD()
        if not dacl or not a.GetSecurityDescriptorControl(sd, c.byref(control), c.byref(revision)) or not control.value & 0x1000:
            raise RuntimeError("acl")
        # Заголовок ACL: версия/резерв/размер/число записей/резерв (8 байт).
        count = c.cast(dacl.value + 4, c.POINTER(w.WORD))[0]
        principals = set()
        for i in range(count):
            ace = c.c_void_p()
            if not a.GetAce(dacl, i, c.byref(ace)) or c.cast(ace, c.POINTER(c.c_ubyte))[0] != 0:
                raise RuntimeError("acl")
            out = w.LPWSTR()
            if not a.ConvertSidToStringSidW(ace.value + 8, c.byref(out)):
                raise RuntimeError("acl")
            try:
                principal = out.value
                if principal not in {sid, "S-1-5-18"}:
                    raise RuntimeError("acl")
                principals.add(principal)
            finally:
                k.LocalFree(out)
        if principals != {sid, "S-1-5-18"}:
            raise RuntimeError("acl")
    finally:
        k.LocalFree(sd)


def storage(k, a, sid, sa, parts=None):
    shell = c.WinDLL("shell32", use_last_error=True)
    shell.SHGetFolderPathW.argtypes = [w.HWND, c.c_int, w.HANDLE, w.DWORD, w.LPWSTR]
    buf = c.create_unicode_buffer(32768)
    if shell.SHGetFolderPathW(None, 0x1C, None, 0, buf):
        raise RuntimeError("local_app_data")
    root = Path(buf.value)
    if not root.is_absolute() or str(root).startswith("\\\\"):
        raise RuntimeError("local_storage_required")
    k.GetFileAttributesW.argtypes = [w.LPCWSTR]
    k.GetFileAttributesW.restype = w.DWORD
    # Проверяем отсутствие junction и символических ссылок на всём локальном пути.
    for p in [*reversed(root.parents), root]:
        attrs = k.GetFileAttributesW(str(p))
        if attrs == 0xFFFFFFFF or attrs & 0x400:
            raise RuntimeError("reparse_path")
    return secure_subdirectories(root, k, a, sid, sa, parts=parts)


def secure_subdirectories(root, k, a, sid, sa, parts=None):
    k.GetFileAttributesW.argtypes = [w.LPCWSTR]
    k.GetFileAttributesW.restype = w.DWORD
    k.CreateDirectoryW.argtypes = [w.LPCWSTR, c.POINTER(SecurityAttributes)]
    for part in (parts if parts is not None else ["AI_WorckBook_Subscription", "sessions-v1"]):
        if not part or Path(part).name != part or part in {".", ".."} or ":" in part:
            raise RuntimeError("storage")
        root = root / part
        if not k.CreateDirectoryW(str(root), c.byref(sa)) and c.get_last_error() != 183:
            raise RuntimeError("storage")
        attrs = k.GetFileAttributesW(str(root))
        if attrs == 0xFFFFFFFF or attrs & 0x400 or not attrs & 0x10:
            raise RuntimeError("storage")
        check_acl(root, k, a, sid)
    return root


def guard():
    k, a = api()
    sid = current_sid(k, a)
    sd, sa = descriptor(a, sid)
    mutex = None
    acquired = False
    try:
        k.CreateMutexW.argtypes = [c.POINTER(SecurityAttributes), w.BOOL, w.LPCWSTR]
        k.CreateMutexW.restype = w.HANDLE
        k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        k.ReleaseMutex.argtypes = [w.HANDLE]
        mutex = k.CreateMutexW(c.byref(sa), False, "Global\\AI_WorkBook_SIWC_v1_" + sid)
        if not mutex:
            raise RuntimeError("mutex")
        result = k.WaitForSingleObject(mutex, 0)
        acquired = result in (0, 0x80)
        if result != 0:
            print(json.dumps({"ready": False, "code": "busy" if result == 0x102 else "storage_unavailable"}), flush=True)
            return 2
        path = storage(k, a, sid, sa)
        print(json.dumps({"ready": True, "storage": str(path)}), flush=True)
        # Мьютекс живёт до закрытия канала родителя; перехвата по таймеру нет.
        while sys.stdin.buffer.read(1):
            pass
        return 0
    finally:
        if acquired:
            k.ReleaseMutex(mutex)
        if mutex:
            k.CloseHandle(mutex)
        k.LocalFree(sd)


class Blob(c.Structure):
    _fields_ = [("length", w.DWORD), ("data", c.POINTER(c.c_ubyte))]


def crypt(raw, decrypt=False):
    k, _ = api()
    lib = c.WinDLL("crypt32", use_last_error=True)
    inbuf, entropybuf = c.create_string_buffer(raw), c.create_string_buffer(ENTROPY)
    source = Blob(len(raw), c.cast(inbuf, c.POINTER(c.c_ubyte)))
    entropy = Blob(len(ENTROPY), c.cast(entropybuf, c.POINTER(c.c_ubyte)))
    output = Blob()
    fn = lib.CryptUnprotectData if decrypt else lib.CryptProtectData
    fn.argtypes = [c.POINTER(Blob), c.c_void_p, c.POINTER(Blob), c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(Blob)]
    if not fn(c.byref(source), None, c.byref(entropy), None, None, 1, c.byref(output)):
        raise RuntimeError("dpapi")
    try:
        return c.string_at(output.data, output.length)
    finally:
        k.LocalFree(output.data)


def main():
    try:
        mode = sys.argv[1] if len(sys.argv) == 2 else ""
        if mode == "guard":
            return guard()
        if mode not in ("encrypt", "decrypt"):
            return 2
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return 2
        raw = base64.b64decode(data, validate=True)
        result = crypt(raw, mode == "decrypt")
        sys.stdout.buffer.write(base64.b64encode(result))
        return 0
    except Exception:
        # Клиент получает только фиксированный код, без подробностей исключения.
        return 2


if __name__ == "__main__":
    sys.exit(main())
