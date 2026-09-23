from __future__ import annotations
import os, subprocess, sys, time, ctypes
from pathlib import Path
from .privacy import child_environment

if os.name == "nt":
    from ctypes import wintypes
    _OpenProcess = ctypes.windll.kernel32.OpenProcess
    _OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _OpenProcess.restype = wintypes.HANDLE
    _GetProcessTimes = ctypes.windll.kernel32.GetProcessTimes
    _GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
    _GetProcessTimes.restype = wintypes.BOOL
    _CloseHandle = ctypes.windll.kernel32.CloseHandle
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _QueryFullProcessImageNameW = ctypes.windll.kernel32.QueryFullProcessImageNameW
    _QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    _QueryFullProcessImageNameW.restype = wintypes.BOOL

def identity(pid: int) -> dict | None:
    if os.name != "nt":
        try: os.kill(pid, 0)
        except OSError: return None
        return {"pid": pid}
    handle = _OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle: return None
    try:
        created, exited, kernel, user = (wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME())
        if not _GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        value = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return {"pid": pid, "creation_identity": str(value)}
    finally:
        _CloseHandle(handle)

def evidence(pid: int) -> dict:
    try:
        observed = identity(pid)
    except (OSError, RuntimeError):
        return {"status":"BLOCKED","reason":"PROCESS_EVIDENCE_UNAVAILABLE","pid":pid}
    if observed is None:
        return {"status":"FAIL","reason":"PROCESS_NOT_FOUND","pid":pid,"alive":False}
    result = {"status":"PASS","pid":pid,"alive":True,"creation_identity":observed.get("creation_identity"),"observed_at":time.time()}
    if os.name == "nt":
        handle = _OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            try:
                size = wintypes.DWORD(32768); buffer = ctypes.create_unicode_buffer(size.value)
                if _QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    result["image_path"] = buffer.value[:size.value]
                else:
                    result["image_path"] = None; result["image_path_reason"] = "UNAVAILABLE"
            finally:
                _CloseHandle(handle)
        else:
            result["image_path"] = None; result["image_path_reason"] = "UNAVAILABLE"
    else:
        result["image_path"] = None; result["image_path_reason"] = "UNAVAILABLE"
    return result

def terminate_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], env=child_environment(), capture_output=True, text=True, timeout=10, check=False)
    else:
        os.kill(pid, 15)
