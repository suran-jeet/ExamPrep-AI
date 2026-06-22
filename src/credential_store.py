from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys


class CredentialStoreError(Exception):
    """Raised when secure credential storage or authentication fails."""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class _CredUiInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hwndParent", wintypes.HWND),
        ("pszMessageText", wintypes.LPCWSTR),
        ("pszCaptionText", wintypes.LPCWSTR),
        ("hbmBanner", wintypes.HBITMAP),
    ]


def credential_path() -> Path:
    base = Path(os.getenv("APPDATA", Path.home())) / "ExamPrepAI"
    return base / "gemini_key.bin"


def save_api_key(api_key: str) -> Path:
    value = api_key.strip()
    if not value:
        raise CredentialStoreError("The Gemini API key cannot be empty.")
    encrypted = _protect(value.encode("utf-8"))
    path = credential_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encrypted)
    return path


def load_api_key() -> str:
    path = credential_path()
    if not path.exists():
        return ""
    try:
        return _unprotect(path.read_bytes()).decode("utf-8")
    except Exception as exc:
        raise CredentialStoreError("The saved Gemini key could not be decrypted for this Windows user.") from exc


def delete_api_key() -> None:
    path = credential_path()
    if path.exists():
        path.unlink()


def authenticate_windows_user() -> bool:
    if sys.platform != "win32":
        raise CredentialStoreError("Device authentication is currently supported on Windows only.")

    credui = ctypes.WinDLL("credui", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    username = ctypes.create_unicode_buffer(256)
    password = ctypes.create_unicode_buffer(256)
    try:
        username.value = os.getlogin()
    except OSError:
        username.value = ""

    info = _CredUiInfo(
        cbSize=ctypes.sizeof(_CredUiInfo),
        hwndParent=None,
        pszMessageText="Enter your Windows account password to reveal the saved Gemini API key.",
        pszCaptionText="ExamPrep AI device authentication",
        hbmBanner=None,
    )
    save = wintypes.BOOL(False)
    flags = 0x40000 | 0x80 | 0x2 | 0x8
    result = credui.CredUIPromptForCredentialsW(
        ctypes.byref(info),
        "ExamPrepAI/APIKey",
        None,
        0,
        username,
        len(username),
        password,
        len(password),
        ctypes.byref(save),
        flags,
    )
    if result == 1223:
        return False
    if result != 0:
        raise CredentialStoreError(f"Windows credential prompt failed with error {result}.")

    raw_user = username.value
    domain = "."
    account = raw_user
    if "\\" in raw_user:
        domain, account = raw_user.split("\\", 1)
    elif "@" in raw_user:
        domain = "MicrosoftAccount"

    token = wintypes.HANDLE()
    logged_on = advapi.LogonUserW(account, domain, password.value, 2, 0, ctypes.byref(token))
    ctypes.memset(password, 0, ctypes.sizeof(password))
    if token:
        kernel.CloseHandle(token)
    return bool(logged_on)


def _protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise CredentialStoreError("Secure API-key storage is currently supported on Windows only.")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    source_buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    destination = _DataBlob()
    description = "ExamPrep AI Gemini API key"
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        description,
        None,
        None,
        None,
        0,
        ctypes.byref(destination),
    ):
        raise CredentialStoreError("Windows could not encrypt the Gemini API key.")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel.LocalFree(destination.pbData)


def _unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise CredentialStoreError("Secure API-key storage is currently supported on Windows only.")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    source_buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    destination = _DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(destination),
    ):
        raise CredentialStoreError("Windows could not decrypt the saved Gemini API key.")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel.LocalFree(destination.pbData)
