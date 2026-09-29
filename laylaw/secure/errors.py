"""Errors for the secure layer. Messages never include case content or key material."""


class VaultError(Exception):
    """The vault is missing, malformed, or can't be used."""


class AccessDenied(VaultError):
    """Wrong passphrase, wrong recovery code, or the device secret is missing."""


class SecureStorageError(VaultError):
    """An encrypted file failed authentication (tampered, swapped, or wrong key)."""


class AuditTamperError(VaultError):
    """The audit log's chain doesn't verify."""


class RealDataModeError(RuntimeError):
    """An operation that would handle real data unsafely was refused."""


class NotReadyForRealData(RealDataModeError):
    """Real-data mode was requested but a required security piece is missing."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("Laylaw is not ready for real case data:\n- " + "\n- ".join(self.problems))
