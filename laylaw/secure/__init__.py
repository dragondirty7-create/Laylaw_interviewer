"""Hardened single-user local mode: encrypted storage, access gate, audit log, deletion.

Nothing in this package changes how the Interviewer engine records facts. It only
changes where and how a session is stored, and who can open it.
"""
from .errors import (AccessDenied, AuditTamperError, NotReadyForRealData, RealDataModeError,
                     SecureStorageError, VaultError)

__all__ = ["AccessDenied", "AuditTamperError", "NotReadyForRealData", "RealDataModeError",
           "SecureStorageError", "VaultError"]
