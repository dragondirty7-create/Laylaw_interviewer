"""Client workspaces: storage, save/resume, and uploads.

Each client gets its own directory. A ClientWorkspace handle can only read and
write inside its own directory, and every loaded session is checked against the
workspace's client id before it is returned.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from .models import ProvenanceType, SupportingRecord

if TYPE_CHECKING:
    from .session import InterviewSession

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class WorkspaceIsolationError(PermissionError):
    """Raised on any attempt to cross from one client workspace into another."""


def _check_id(value: str, kind: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise WorkspaceIsolationError(f"invalid {kind}: {value!r}")
    return value


def _safe_filename(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/")).strip() or "upload"
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base)
    return base.lstrip(".") or "upload"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


class WorkspaceStore:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).resolve()
        (self.root / "clients").mkdir(parents=True, exist_ok=True)

    def workspace(self, client_id: str) -> "ClientWorkspace":
        return ClientWorkspace(self, _check_id(client_id, "client id"))


class ClientWorkspace:
    def __init__(self, store: WorkspaceStore, client_id: str):
        self.client_id = client_id
        self.dir = (store.root / "clients" / client_id).resolve()
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- path guard -------------------------------------------------------
    def _inside(self, path: Path) -> Path:
        resolved = path.resolve()
        if resolved != self.dir and self.dir not in resolved.parents:
            raise WorkspaceIsolationError(f"path escapes workspace {self.client_id}")
        return resolved

    def _session_path(self, session_id: str) -> Path:
        return self._inside(self.dir / "sessions" / f"{_check_id(session_id, 'session id')}.json")

    # -- sessions ---------------------------------------------------------
    def save_session(self, session: "InterviewSession") -> Path:
        if session.client_id != self.client_id:
            raise WorkspaceIsolationError(
                f"session belongs to {session.client_id}, not {self.client_id}")
        path = self._session_path(session.interview_id)
        _atomic_write(path, json.dumps(session.to_dict(), indent=2).encode("utf-8"))
        return path

    def load_session(self, session_id: str) -> "InterviewSession":
        from .session import InterviewSession

        path = self._session_path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"no session {session_id} in workspace {self.client_id}")
        data = json.loads(path.read_text("utf-8"))
        if data.get("client_id") != self.client_id:
            raise WorkspaceIsolationError("stored session does not belong to this workspace")
        session = InterviewSession.from_dict(data)
        session.workspace = self
        return session

    def list_sessions(self) -> list[str]:
        d = self.dir / "sessions"
        return sorted(p.stem for p in d.glob("*.json")) if d.exists() else []

    # -- uploads ----------------------------------------------------------
    def store_upload(self, session_id: str, filename: str, data: bytes, label: str | None = None,
                     provenance_type: ProvenanceType = ProvenanceType.DOCUMENT) -> SupportingRecord:
        _check_id(session_id, "session id")
        record_id = "R-" + uuid.uuid4().hex[:10]
        safe = _safe_filename(filename)
        path = self._inside(self.dir / "uploads" / session_id / f"{record_id}__{safe}")
        _atomic_write(path, data)
        return SupportingRecord(
            id=record_id, client_id=self.client_id, session_id=session_id,
            label=label or safe, provenance_type=provenance_type, filename=safe,
            sha256=hashlib.sha256(data).hexdigest(),
            stored_path=str(path.relative_to(self.dir)),
        )

    def read_upload(self, record: SupportingRecord) -> bytes:
        if record.client_id != self.client_id:
            raise WorkspaceIsolationError("record belongs to another workspace")
        return self._inside(self.dir / record.stored_path).read_bytes()
