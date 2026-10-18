"""Windows user-scoped DPAPI credentials. No network or plaintext disk fallback."""

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path

from ..errors import ZjuError

MAGIC = b"ZJU-AC\x00\x01"
ENTROPY = b"ZJU-AC/local-credentials/v1"


class CredentialError(ZjuError):
    pass


class DataBlob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise CredentialError("加密凭据仅支持 Windows 用户保护，未保存任何明文。")
    crypt = ctypes.WinDLL("crypt32.dll", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    source = ctypes.create_string_buffer(data)
    entropy = ctypes.create_string_buffer(ENTROPY)
    incoming = DataBlob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    extra = DataBlob(len(ENTROPY), ctypes.cast(entropy, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = DataBlob()
    try:
        # UI forbidden; deliberately omit LOCAL_MACHINE and credential-sync flags.
        if not function(
            ctypes.byref(incoming),
            None,
            ctypes.byref(extra),
            None,
            None,
            0x1,
            ctypes.byref(outgoing),
        ):
            raise CredentialError("Windows 无法解密或保护凭据，请重新输入登录信息。")
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        ctypes.memset(source, 0, len(source))
        if outgoing.data:
            ctypes.memset(outgoing.data, 0, outgoing.size)
            kernel.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))


def seal_credentials(student: str, password: str) -> bytes:
    payload = json.dumps(
        {"version": 1, "student": student, "password": password}, ensure_ascii=False
    ).encode("utf-8")
    return MAGIC + _crypt(payload)


def open_credentials(blob: bytes) -> tuple[str, str]:
    if not blob.startswith(MAGIC) or not len(MAGIC) < len(blob) <= 65536:
        raise CredentialError("保存的凭据格式无效，请清除后重新输入。")
    try:
        value = json.loads(_crypt(blob[len(MAGIC) :], decrypt=True))
        if (
            not isinstance(value, dict)
            or value.get("version") != 1
            or not isinstance(value.get("student"), str)
            or not value["student"].strip()
            or len(value["student"]) > 80
            or not isinstance(value.get("password"), str)
            or not 0 < len(value["password"]) <= 4096
        ):
            raise ValueError
    except (ValueError, UnicodeError) as exc:
        raise CredentialError("保存的凭据无法读取，请清除后重新输入。") from exc
    return value["student"], value["password"]


class CredentialVault:
    def __init__(self, directory: Path):
        self.path = directory / "credentials.dpapi"

    def load(self) -> tuple[str, str] | None:
        if not self.path.exists():
            return None
        if self.path.stat().st_size > 65536:
            raise CredentialError("凭据缓存大小无效，请清除后重新输入。")
        return open_credentials(self.path.read_bytes())

    def save_blob(self, blob: bytes) -> None:
        # Validate before replacing an existing cache; the disk receives ciphertext only.
        open_credentials(blob)
        temporary = self.path.with_suffix(".tmp")
        try:
            with temporary.open("wb") as stream:
                stream.write(blob)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def forget(self) -> None:
        self.path.unlink(missing_ok=True)
        self.path.with_suffix(".tmp").unlink(missing_ok=True)


class SessionClock:
    def __init__(self, clock):
        self.clock = clock
        self.started = None
        self.elapsed = 0.0

    def reset(self):
        self.started, self.elapsed = None, 0.0

    def start(self):
        self.elapsed, self.started = 0.0, self.clock()

    def stop(self):
        self.elapsed = self.seconds
        self.started = None

    @property
    def seconds(self):
        return max(
            0.0, self.elapsed + (self.clock() - self.started if self.started is not None else 0)
        )

    @property
    def text(self):
        elapsed = int(self.seconds)
        return f"{elapsed // 3600:02}:{elapsed // 60 % 60:02}:{elapsed % 60:02}"
