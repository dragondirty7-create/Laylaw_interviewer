"""Real-data mode: the readiness gate and the single entry point for opening a vault.

A vault is created in one of two modes, recorded in its header:

* ``synthetic``: encrypted like a real vault, but the environment checks below
  are relaxed so it can run in tests and demos. The app shows a
  "SYNTHETIC DATA ONLY" banner. Never put real case information in it.
* ``real``: every check below must pass, or Laylaw refuses to open the vault
  and says why. It fails closed.

The original plaintext `WorkspaceStore` is the developer library mode. It
refuses to run when LAYLAW_MODE=real is set, or inside a vault folder.
"""
from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .audit import AuditLog
from .errors import AccessDenied, AuditTamperError, NotReadyForRealData, VaultError
from .secrets_store import SecretStore
from .store import SecureStore
from .vault import (DATA_DIR, HAVE_CRYPTO, HEADER_NAME, MIN_REAL_SCRYPT_N, audit_key_for, read_header, unlock)

REAL_MODE_ENV = "LAYLAW_MODE"


def real_mode_requested() -> bool:
    return os.environ.get(REAL_MODE_ENV, "").strip().lower() == "real"


@dataclass
class Readiness:
    mode: str = "unknown"
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _owner_only(path: Path) -> bool:
    return not (stat.S_IMODE(path.stat().st_mode) & 0o077)


def check_readiness(root: str | os.PathLike, secret_store: SecretStore) -> Readiness:
    """Everything that must be true before real case data may be opened."""
    root = Path(root).resolve()
    r = Readiness()
    if not HAVE_CRYPTO:
        r.problems.append("The 'cryptography' package is not installed, so nothing can be encrypted.")
        return r
    try:
        header = read_header(root)
    except VaultError as exc:
        r.problems.append(str(exc))
        return r
    r.mode = header.mode
    strict = header.mode == "real"

    def need(cond: bool, message: str) -> None:
        if not cond:
            (r.problems if strict else r.warnings).append(message)

    need(secret_store.is_os_protected,
         f"The device secret must be kept in the operating system's credential store; "
         f"the available store is '{secret_store.name}'.")
    try:
        audit_key = audit_key_for(root, secret_store)
    except AccessDenied as exc:
        r.problems.append(str(exc))
        audit_key = None
    need(header.kdf_n >= MIN_REAL_SCRYPT_N, "The vault's passphrase stretching is set too low for real data.")

    if os.name == "posix":
        for p in (root, root / DATA_DIR, root / HEADER_NAME):
            if p.exists():
                need(_owner_only(p), f"{p.name} can be read by other accounts on this computer; "
                                     f"it must be private to this user (chmod 700 folders / 600 files).")
    else:
        r.warnings.append("Folder permissions are not checked on Windows; keep the vault inside your own "
                          "user folder and use a Windows account only Chelsea signs into.")

    data = root / DATA_DIR
    if data.exists():
        stray = [p.name for p in data.iterdir() if not (p.suffix == ".bin" or p.name.startswith(".tmp-"))]
        need(not stray, f"The data folder contains {len(stray)} file(s) that are not encrypted Laylaw files.")
    need(not (root / "clients").exists(),
         "A plaintext 'clients' folder exists inside the vault; plaintext case data must not be stored here.")

    if audit_key is not None:
        try:
            AuditLog(root, audit_key).verify()
        except AuditTamperError as exc:
            r.problems.append(f"The audit log failed verification: {exc}. "
                              f"Stop and review before using this vault.")
    return r


class AccessGate:
    """Passphrase check with slow-down after repeated failures. Every attempt is audited."""

    MAX_FAILURES = 5
    LOCKOUT_S = 60.0

    def __init__(self, root: str | os.PathLike, secret_store: SecretStore,
                 clock: Callable[[], float] = time.monotonic):
        self.root = Path(root).resolve()
        self.secret_store = secret_store
        self.clock = clock
        self.failures = 0
        self.locked_until = 0.0

    def _audit(self) -> AuditLog | None:
        try:
            return AuditLog(self.root, audit_key_for(self.root, self.secret_store))
        except (AccessDenied, VaultError):
            return None

    def open(self, passphrase: str) -> SecureStore:
        readiness = check_readiness(self.root, self.secret_store)
        audit = self._audit()
        if not readiness.ok:
            if audit is not None:
                try:
                    audit.append("readiness_refused", detail={"problems": len(readiness.problems)})
                except AuditTamperError:
                    pass
            raise NotReadyForRealData(readiness.problems)
        assert audit is not None  # readiness guarantees the device secret is present

        now = self.clock()
        if now < self.locked_until:
            audit.append("access_refused", detail={"reason": "too_many_failures"})
            raise AccessDenied(f"Too many wrong attempts. Try again in {int(self.locked_until - now) + 1} seconds.")
        try:
            vault = unlock(self.root, passphrase, secret_store=self.secret_store)
        except AccessDenied:
            self.failures += 1
            audit.append("unlock_failed", detail={"attempt": self.failures})
            if self.failures >= self.MAX_FAILURES:
                self.locked_until = now + self.LOCKOUT_S
                self.failures = 0
            raise AccessDenied("That passphrase didn't open the vault.")
        self.failures = 0
        audit.append("unlock_ok", detail={"mode": vault.mode})
        return SecureStore(vault, audit)
