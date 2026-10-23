"""The vault: key hierarchy, access gate, recovery, and authenticated encryption of files.

Key hierarchy
-------------
* **Data key (DEK)**: 32 random bytes. Everything on disk is encrypted with
  keys derived from it. It is never written anywhere in the clear.
* **Primary unlock**: DEK wrapped with AES-256-GCM under
  HKDF(scrypt(passphrase) || device_secret). The device secret is 32 random
  bytes kept in the OS credential store for this OS user. Opening the vault
  needs BOTH the passphrase and that OS account's credential store: a copy of
  the data folder plus the passphrase is not enough, and neither is access to
  the OS account without the passphrase.
* **Recovery**: DEK also wrapped under HKDF(recovery code). The recovery code is
  256 random bits shown once at setup, to be written down and stored offline.
  It restores access if the passphrase is forgotten or the device secret is
  lost (new computer, OS reinstall). Losing both passphrase-or-device AND the
  recovery code means the data is unrecoverable, by design; this is stated at
  setup and in SECURITY.md.

Files
-----
Each file is AES-256-GCM with a random 96-bit nonce. The associated data binds
the ciphertext to this vault and to its logical name (for example
``ws/<client>/session/<id>``), so a file can't be swapped into another
workspace or renamed without failing authentication. Physical file names are
HMACs of the logical names, so client labels, session ids and upload file
names never appear on disk.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import AccessDenied, SecureStorageError, VaultError
from .secrets_store import SecretStore

try:  # the maintained, reviewed primitives; required for any vault
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    HAVE_CRYPTO = True
except ImportError:  # pragma: no cover - reported by the readiness check
    HAVE_CRYPTO = False

FORMAT = "laylaw.vault/1"
HEADER_NAME = "vault.json"
DATA_DIR = "data"
BLOB_MAGIC = b"LLE1"
DEFAULT_SCRYPT_N = 2 ** 17          # ~128 MiB, well under a second on a laptop
MIN_REAL_SCRYPT_N = 2 ** 15         # the readiness check refuses weaker settings
MIN_PASSPHRASE_CHARS = 12
MODES = ("real", "synthetic")


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"), validate=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hkdf(ikm: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(ikm)


def _norm_passphrase(passphrase: str) -> bytes:
    if not isinstance(passphrase, str) or not passphrase:
        raise AccessDenied("a passphrase is required")
    return unicodedata.normalize("NFKC", passphrase).encode("utf-8")


def _wrap(key: bytes, secret: bytes, aad: bytes) -> dict:
    nonce = secrets.token_bytes(12)
    return {"nonce": _b64e(nonce), "ct": _b64e(AESGCM(key).encrypt(nonce, secret, aad))}


def _unwrap(key: bytes, box: dict, aad: bytes) -> bytes:
    try:
        return AESGCM(key).decrypt(_b64d(box["nonce"]), _b64d(box["ct"]), aad)
    except (InvalidTag, KeyError, ValueError) as exc:
        raise AccessDenied("the vault could not be opened with these credentials") from exc


def write_private(path: Path, data: bytes) -> None:
    """Atomic write, owner-only permissions on POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------- recovery codes
def format_recovery_code(raw: bytes) -> str:
    body = base64.b32encode(raw).decode("ascii").rstrip("=")
    return "LLRC-" + "-".join(body[i:i + 4] for i in range(0, len(body), 4))


def parse_recovery_code(code: str) -> bytes:
    body = "".join(ch for ch in code.upper() if ch.isalnum())
    if body.startswith("LLRC"):
        body = body[4:]
    try:
        raw = base64.b32decode(body + "=" * (-len(body) % 8))
    except (ValueError, base64.binascii.Error) as exc:
        raise AccessDenied("that recovery code isn't valid") from exc
    if len(raw) != 32:
        raise AccessDenied("that recovery code isn't valid")
    return raw


# ---------------------------------------------------------------- device secret
def _device_bundle(store: SecretStore, vault_id: str) -> dict:
    raw = store.get(vault_id)
    if not raw:
        raise AccessDenied("this computer's Laylaw key isn't available for this OS user "
                           "(use the recovery code on a new or reinstalled computer)")
    try:
        bundle = json.loads(raw)
        return {"device_secret": _b64d(bundle["device_secret"]), "audit_key": _b64d(bundle["audit_key"])}
    except (ValueError, KeyError) as exc:
        raise AccessDenied("this computer's Laylaw key is damaged; use the recovery code") from exc


def _store_bundle(store: SecretStore, vault_id: str, device_secret: bytes, audit_key: bytes) -> None:
    store.set(vault_id, json.dumps({"v": 1, "device_secret": _b64e(device_secret), "audit_key": _b64e(audit_key)}))


# ---------------------------------------------------------------- header
@dataclass
class VaultHeader:
    root: Path
    data: dict

    @property
    def vault_id(self) -> str:
        return self.data["vault_id"]

    @property
    def mode(self) -> str:
        return self.data["mode"]

    @property
    def kdf_n(self) -> int:
        return int(self.data["kdf"]["n"])

    def save(self) -> None:
        write_private(self.root / HEADER_NAME, json.dumps(self.data, indent=2).encode("utf-8"))

    def _aad(self, purpose: str) -> bytes:
        return f"laylaw/v1|{self.vault_id}|{purpose}".encode()

    def _passphrase_kek(self, passphrase: str, device_secret: bytes) -> bytes:
        kdf = self.data["kdf"]
        stretched = Scrypt(salt=_b64d(kdf["salt"]), length=32, n=int(kdf["n"]), r=int(kdf["r"]),
                           p=int(kdf["p"])).derive(_norm_passphrase(passphrase))
        return _hkdf(stretched + device_secret, self.vault_id.encode(), b"laylaw/v1/unlock")

    def _recovery_kek(self, raw: bytes) -> bytes:
        return _hkdf(raw, self.vault_id.encode(), b"laylaw/v1/recovery")


def vault_exists(root: str | os.PathLike) -> bool:
    return (Path(root) / HEADER_NAME).exists()


def read_header(root: str | os.PathLike) -> VaultHeader:
    root = Path(root).resolve()
    path = root / HEADER_NAME
    if not path.exists():
        raise VaultError(f"no Laylaw vault at {root} (run: python -m laylaw init)")
    try:
        data = json.loads(path.read_text("utf-8"))
    except ValueError as exc:
        raise VaultError("the vault header is damaged") from exc
    if data.get("format") != FORMAT or data.get("mode") not in MODES:
        raise VaultError("unrecognized vault format")
    for key in ("vault_id", "kdf", "wrapped_primary", "wrapped_recovery", "meta"):
        if key not in data:
            raise VaultError(f"the vault header is missing {key}")
    return VaultHeader(root, data)


def init_vault(root: str | os.PathLike, passphrase: str, *, secret_store: SecretStore, mode: str = "real",
               kdf_n: int = DEFAULT_SCRYPT_N) -> tuple["UnlockedVault", str]:
    """Create a new vault. Returns the unlocked vault and the recovery code (shown once)."""
    if not HAVE_CRYPTO:
        raise VaultError("the 'cryptography' package is required")
    if mode not in MODES:
        raise ValueError("mode must be 'real' or 'synthetic'")
    if mode == "real" and len(passphrase) < MIN_PASSPHRASE_CHARS:
        raise VaultError(f"use a passphrase of at least {MIN_PASSPHRASE_CHARS} characters")
    root = Path(root).resolve()
    if vault_exists(root):
        raise VaultError(f"a vault already exists at {root}")
    if root.exists() and any(root.iterdir()):
        raise VaultError(f"{root} is not empty; choose an empty folder for the vault")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(root, 0o700)

    dek, device_secret, audit_key = (secrets.token_bytes(32) for _ in range(3))
    recovery_raw = secrets.token_bytes(32)
    header = VaultHeader(root, {
        "format": FORMAT, "vault_id": uuid.uuid4().hex, "mode": mode, "created": _now(),
        "kdf": {"name": "scrypt", "n": kdf_n, "r": 8, "p": 1, "salt": _b64e(secrets.token_bytes(16))},
    })
    header.data["wrapped_primary"] = _wrap(header._passphrase_kek(passphrase, device_secret), dek,
                                           header._aad("primary"))
    header.data["wrapped_recovery"] = _wrap(header._recovery_kek(recovery_raw), dek, header._aad("recovery"))
    header.data["meta"] = _wrap(_hkdf(dek, b"", b"laylaw/v1/meta"),
                                json.dumps({"audit_key": _b64e(audit_key)}).encode(), header._aad("meta"))
    _store_bundle(secret_store, header.vault_id, device_secret, audit_key)
    header.save()
    (root / DATA_DIR).mkdir(mode=0o700, exist_ok=True)
    return UnlockedVault(header, dek, secret_store), format_recovery_code(recovery_raw)


def audit_key_for(root: str | os.PathLike, secret_store: SecretStore) -> bytes:
    """The audit MAC key, available to this OS user before unlock (so failed unlocks are logged)."""
    header = read_header(root)
    return _device_bundle(secret_store, header.vault_id)["audit_key"]


def unlock(root: str | os.PathLike, passphrase: str, *, secret_store: SecretStore) -> "UnlockedVault":
    if not HAVE_CRYPTO:
        raise VaultError("the 'cryptography' package is required")
    header = read_header(root)
    bundle = _device_bundle(secret_store, header.vault_id)
    dek = _unwrap(header._passphrase_kek(passphrase, bundle["device_secret"]), header.data["wrapped_primary"],
                  header._aad("primary"))
    return UnlockedVault(header, dek, secret_store)


def recover(root: str | os.PathLike, recovery_code: str, new_passphrase: str, *,
            secret_store: SecretStore) -> "UnlockedVault":
    """Use the recovery code to set a new passphrase and a fresh device secret on this computer."""
    header = read_header(root)
    if header.mode == "real" and len(new_passphrase) < MIN_PASSPHRASE_CHARS:
        raise VaultError(f"use a passphrase of at least {MIN_PASSPHRASE_CHARS} characters")
    dek = _unwrap(header._recovery_kek(parse_recovery_code(recovery_code)), header.data["wrapped_recovery"],
                  header._aad("recovery"))
    vault = UnlockedVault(header, dek, secret_store)
    audit_key = vault.meta()["audit_key"]
    device_secret = secrets.token_bytes(32)
    header.data["wrapped_primary"] = _wrap(header._passphrase_kek(new_passphrase, device_secret), dek,
                                           header._aad("primary"))
    _store_bundle(secret_store, header.vault_id, device_secret, audit_key)
    header.save()
    return vault


class UnlockedVault:
    """An open vault. Holds the data key in memory until lock()."""

    def __init__(self, header: VaultHeader, dek: bytes, secret_store: SecretStore):
        self.header = header
        self.root = header.root
        self.vault_id = header.vault_id
        self.mode = header.mode
        self._secret_store = secret_store
        self._dek = bytearray(dek)
        self._enc = bytearray(_hkdf(dek, b"", b"laylaw/v1/files"))
        self._names = bytearray(_hkdf(dek, b"", b"laylaw/v1/names"))
        self.locked = False

    # -- keys ------------------------------------------------------------
    def _need_open(self) -> None:
        if self.locked:
            raise AccessDenied("the vault is locked")

    def lock(self) -> None:
        """Forget keys (best effort: Python can't guarantee memory is wiped)."""
        for buf in (self._dek, self._enc, self._names):
            for i in range(len(buf)):
                buf[i] = 0
        self.locked = True

    def meta(self) -> dict:
        self._need_open()
        raw = _unwrap(_hkdf(bytes(self._dek), b"", b"laylaw/v1/meta"), self.header.data["meta"],
                      self.header._aad("meta"))
        data = json.loads(raw)
        return {"audit_key": _b64d(data["audit_key"])}

    def change_passphrase(self, old_passphrase: str, new_passphrase: str) -> None:
        self._need_open()
        if self.mode == "real" and len(new_passphrase) < MIN_PASSPHRASE_CHARS:
            raise VaultError(f"use a passphrase of at least {MIN_PASSPHRASE_CHARS} characters")
        bundle = _device_bundle(self._secret_store, self.vault_id)
        # Re-check the old passphrase so an unattended unlocked app can't be re-keyed silently.
        _unwrap(self.header._passphrase_kek(old_passphrase, bundle["device_secret"]),
                self.header.data["wrapped_primary"], self.header._aad("primary"))
        self.header.data["wrapped_primary"] = _wrap(self.header._passphrase_kek(new_passphrase,
                                                                                bundle["device_secret"]),
                                                    bytes(self._dek), self.header._aad("primary"))
        self.header.save()

    # -- files -----------------------------------------------------------
    def physical_path(self, logical: str) -> Path:
        self._need_open()
        name = hmac.new(bytes(self._names), logical.encode("utf-8"), hashlib.sha256).hexdigest()[:40]
        return self.root / DATA_DIR / f"{name}.bin"

    def opaque_ref(self, value: str) -> str:
        """A stable, non-reversible reference for logs."""
        self._need_open()
        return hmac.new(bytes(self._names), b"ref|" + value.encode(), hashlib.sha256).hexdigest()[:16]

    def _aad(self, logical: str) -> bytes:
        return f"laylaw/v1|{self.vault_id}|file|{logical}".encode("utf-8")

    def encrypt(self, logical: str, plaintext: bytes) -> bytes:
        self._need_open()
        nonce = secrets.token_bytes(12)
        return BLOB_MAGIC + nonce + AESGCM(bytes(self._enc)).encrypt(nonce, plaintext, self._aad(logical))

    def decrypt(self, logical: str, blob: bytes) -> bytes:
        self._need_open()
        if len(blob) < 4 + 12 + 16 or blob[:4] != BLOB_MAGIC:
            raise SecureStorageError("an encrypted file is not in the expected format")
        try:
            return AESGCM(bytes(self._enc)).decrypt(blob[4:16], blob[16:], self._aad(logical))
        except InvalidTag as exc:
            raise SecureStorageError("an encrypted file failed its integrity check "
                                     "(tampered, moved, or from another vault)") from exc

    def write(self, logical: str, plaintext: bytes) -> Path:
        path = self.physical_path(logical)
        write_private(path, self.encrypt(logical, plaintext))
        return path

    def read(self, logical: str) -> bytes:
        path = self.physical_path(logical)
        if not path.exists():
            raise FileNotFoundError(logical)
        return self.decrypt(logical, path.read_bytes())

    def exists(self, logical: str) -> bool:
        return self.physical_path(logical).exists()

    def erase(self, logical: str) -> bool:
        """Overwrite then unlink. Best effort; see SECURITY.md for what this can't guarantee."""
        path = self.physical_path(logical)
        if not path.exists():
            return False
        size = path.stat().st_size
        with open(path, "r+b") as f:
            f.write(secrets.token_bytes(size))
            f.flush()
            os.fsync(f.fileno())
        path.unlink()
        return True
