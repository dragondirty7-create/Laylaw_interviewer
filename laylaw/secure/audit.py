"""Tamper-evident audit log.

One JSON line per security-relevant event. Each line carries an HMAC over its
content and the previous line's HMAC, so editing, reordering, or deleting a
line breaks the chain. A separate head file records the last sequence number
and HMAC, so cutting lines off the end is detected too.

The HMAC key lives with the device secret in the OS credential store (and a
copy inside the encrypted vault for recovery). That makes failed unlock
attempts loggable before anyone has the passphrase.

Limits (also in SECURITY.md): someone who controls this OS account can read
the key and rewrite the whole log consistently; someone with file access can
roll back BOTH files to an earlier consistent state. The log is evidence for
honest review, not proof against a fully compromised machine.

Nothing in the log is case content. Workspace and session identifiers are
written as opaque HMAC references; details are restricted to small codes and
numbers.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from .errors import AuditTamperError
from .vault import write_private

LOG_NAME = "audit.log"
HEAD_NAME = "audit.head"
GENESIS = "genesis"

EVENTS = {
    "vault_created", "app_started", "app_stopped", "unlock_ok", "unlock_failed", "locked",
    "session_created", "session_open", "session_save", "session_saved_for_later", "session_resumed",
    "upload_stored", "upload_read", "outputs_viewed", "export_refused",
    "session_deleted", "workspace_deleted", "passphrase_changed", "recovery_used", "recovery_failed",
    "key_error", "integrity_error", "readiness_refused", "access_refused", "audit_archived",
}
_SAFE_STR = re.compile(r"^[A-Za-z0-9_.:/-]{0,64}$")


def _canonical(entry: dict) -> bytes:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _check_detail(detail: dict | None) -> dict:
    """Only small numbers, booleans and short codes. Refuses anything that could be case text."""
    out: dict = {}
    for k, v in (detail or {}).items():
        if not _SAFE_STR.match(str(k)):
            raise ValueError("audit detail key not allowed")
        if isinstance(v, bool) or isinstance(v, int):
            out[k] = v
        elif isinstance(v, str) and _SAFE_STR.match(v):
            out[k] = v
        else:
            raise ValueError("audit details may only hold numbers, booleans and short codes")
    return out


class AuditLog:
    def __init__(self, root: str | os.PathLike, key: bytes):
        self.root = Path(root)
        self.path = self.root / LOG_NAME
        self.head_path = self.root / HEAD_NAME
        self._key = bytes(key)
        self._lock = threading.Lock()

    def _mac(self, data: bytes) -> str:
        return hmac.new(self._key, data, hashlib.sha256).hexdigest()

    def _head_mac(self, seq: int, mac: str) -> str:
        return self._mac(f"head|{seq}|{mac}".encode())

    def _read_head(self) -> tuple[int, str]:
        if not self.head_path.exists():
            return 0, GENESIS
        head = json.loads(self.head_path.read_text("utf-8"))
        if not hmac.compare_digest(head.get("head_mac", ""), self._head_mac(head["seq"], head["mac"])):
            raise AuditTamperError("the audit head file fails its integrity check")
        return int(head["seq"]), head["mac"]

    def append(self, event: str, *, ws: str | None = None, session: str | None = None,
               detail: dict | None = None) -> dict:
        if event not in EVENTS:
            raise ValueError(f"unknown audit event {event}")
        for ref in (ws, session):
            if ref is not None and not _SAFE_STR.match(ref):
                raise ValueError("audit references must be opaque codes")
        with self._lock:
            seq, prev = self._read_head()
            entry = {"seq": seq + 1, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "event": event, "ws": ws, "session": session, "detail": _check_detail(detail), "prev": prev}
            entry["mac"] = self._mac(_canonical(entry))
            self.root.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
            write_private(self.head_path, json.dumps(
                {"seq": entry["seq"], "mac": entry["mac"],
                 "head_mac": self._head_mac(entry["seq"], entry["mac"])}).encode())
            return entry

    def verify(self) -> int:
        """Return the number of entries; raise AuditTamperError on any break."""
        with self._lock:
            head_seq, head_mac = self._read_head()
            if not self.path.exists():
                if head_seq:
                    raise AuditTamperError("the audit log is missing but its head says it had entries")
                return 0
            prev, seq = GENESIS, 0
            for n, line in enumerate(self.path.read_text("utf-8").splitlines(), start=1):
                try:
                    entry = json.loads(line)
                    mac = entry.pop("mac")
                except (ValueError, KeyError) as exc:
                    raise AuditTamperError(f"audit line {n} is malformed") from exc
                if entry.get("seq") != seq + 1 or entry.get("prev") != prev:
                    raise AuditTamperError(f"audit chain broken at line {n}")
                if not hmac.compare_digest(mac, self._mac(_canonical(entry))):
                    raise AuditTamperError(f"audit line {n} was modified")
                prev, seq = mac, entry["seq"]
            if (seq, prev) != (head_seq, head_mac):
                raise AuditTamperError("the audit log does not end where its head says it does "
                                       "(lines were removed from the end)")
            return seq

    def archive(self) -> Path:
        """Move the log and head aside (for review) and start a new chain."""
        with self._lock:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            dest = self.root / f"audit-archive-{stamp}"
            dest.mkdir(mode=0o700)
            for p in (self.path, self.head_path):
                if p.exists():
                    os.replace(p, dest / p.name)
        self.append("audit_archived", detail={"archive": dest.name})
        return dest
