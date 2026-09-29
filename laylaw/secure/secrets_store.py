"""Where the device secret lives.

Real-data mode keeps the device secret in the operating system's protected
credential store (Windows Credential Manager, macOS Keychain, or a Linux
Secret Service / KWallet), accessed through the maintained `keyring` library.
Those stores are tied to the OS user account. Backends that write secrets to a
plain file, or that don't store anything, are refused.

Tests use MemorySecretStore, which is marked insecure and is refused by the
real-data readiness check.
"""
from __future__ import annotations

from typing import Protocol

SERVICE = "laylaw-vault"

# keyring backends that genuinely use an OS-protected store.
_SECURE_BACKENDS = (
    "keyring.backends.Windows.WinVaultKeyring",
    "keyring.backends.macOS.Keyring",
    "keyring.backends.SecretService.Keyring",
    "keyring.backends.kwallet.DBusKeyring",
    "keyring.backends.libsecret.Keyring",
)


class SecretStore(Protocol):
    name: str
    is_os_protected: bool

    def get(self, vault_id: str) -> str | None: ...

    def set(self, vault_id: str, value: str) -> None: ...

    def delete(self, vault_id: str) -> None: ...


class KeyringSecretStore:
    """The OS credential store via `keyring`."""

    def __init__(self) -> None:
        import keyring  # type: ignore

        self._kr = keyring
        backend = keyring.get_keyring()
        self.name = f"{type(backend).__module__}.{type(backend).__name__}"
        self.is_os_protected = self._check(backend)

    def _check(self, backend) -> bool:
        # A ChainerBackend delegates to its highest-priority viable backend; judge that one.
        inner = getattr(backend, "backends", None)
        if inner:
            backend = inner[0]
            self.name = f"{type(backend).__module__}.{type(backend).__name__}"
        return self.name in _SECURE_BACKENDS

    def get(self, vault_id: str) -> str | None:
        try:
            return self._kr.get_password(SERVICE, vault_id)
        except Exception:  # no usable backend, locked keychain, etc.: treat as missing (fail closed)
            return None

    def set(self, vault_id: str, value: str) -> None:
        self._kr.set_password(SERVICE, vault_id, value)

    def delete(self, vault_id: str) -> None:
        try:
            self._kr.delete_password(SERVICE, vault_id)
        except Exception:  # already gone
            pass


class MemorySecretStore:
    """In-process only. For tests and synthetic demos. Never OS-protected."""

    name = "memory (tests only)"
    is_os_protected = False

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, vault_id: str) -> str | None:
        return self._data.get(vault_id)

    def set(self, vault_id: str, value: str) -> None:
        self._data[vault_id] = value

    def delete(self, vault_id: str) -> None:
        self._data.pop(vault_id, None)


def default_secret_store() -> SecretStore:
    try:
        return KeyringSecretStore()
    except ImportError:
        return _UnavailableStore()


class _UnavailableStore:
    name = "unavailable (the keyring package is not installed)"
    is_os_protected = False

    def get(self, vault_id: str) -> str | None:
        return None

    def set(self, vault_id: str, value: str) -> None:
        raise RuntimeError("no OS secret store: install the 'keyring' package")

    def delete(self, vault_id: str) -> None:
        pass
