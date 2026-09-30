"""Encrypted, per-client storage for the web app.

Drop-in replacement for ``laylaw.interviewer.workspace.ClientWorkspace`` used by
the web layer. The interview engine is unchanged; it only sees a workspace.

On disk (under ``LAYLAW_DATA_DIR``):

    clients/<opaque client id>/profile.enc
    clients/<opaque client id>/sessions/<interview id>.enc
    clients/<opaque client id>/drafts/<interview id>.enc
    clients/<opaque client id>/uploads/<interview id>/<record id>.enc

- Every file is AES-256-GCM ciphertext under that client's derived key.
- No real names, original filenames, or case facts appear in paths. Client ids
  are random (``c-`` + 20 hex chars); record ids are random.
- Directories are 0700 and files 0600.
- Any decryption failure is treated as access denied (fail closed).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from laylaw.interviewer.models import ProvenanceType, SupportingRecord
from laylaw.interviewer.workspace import (
    ClientWorkspace, WorkspaceIsolationError, _atomic_write, _check_id, _safe_filename,
)

from .crypto import ClientCipher, DecryptionError

if TYPE_CHECKING:
    from laylaw.interviewer.session import InterviewSession

CLIENT_ID_RE = re.compile(r"^c-[0-9a-f]{20}$")
RECORD_ID_RE = re.compile(r"^R-[0-9a-f]{20}$")


def new_client_id() -> str:
    return "c-" + secrets.token_hex(10)


def _mkdir_private(path: Path) -> None:
    """Create ``path`` and any missing parents as 0700 (not the process umask default)."""
    missing = []
    p = path
    while not p.exists():
        missing.append(p)
        p = p.parent
    for d in reversed(missing):
        d.mkdir(mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
    os.chmod(path, 0o700)


def _write_private(path: Path, data: bytes) -> None:
    _mkdir_private(path.parent)
    _atomic_write(path, data)          # mkstemp creates 0600; os.replace keeps it
    os.chmod(path, 0o600)


class EncryptedStore:
    def __init__(self, root: str | os.PathLike, master_key: bytes):
        self.root = Path(root).resolve()
        self._master = master_key
        _mkdir_private(self.root)
        _mkdir_private(self.root / "clients")

    def workspace(self, client_id: str) -> "EncryptedClientWorkspace":
        if not isinstance(client_id, str) or not CLIENT_ID_RE.match(client_id):
            raise WorkspaceIsolationError("invalid client id")
        return EncryptedClientWorkspace(self, client_id)


class EncryptedClientWorkspace(ClientWorkspace):
    """Same interface as ClientWorkspace; everything it writes is ciphertext."""

    def __init__(self, store: EncryptedStore, client_id: str):  # noqa: D401 - no super().__init__
        self.client_id = client_id
        self.dir = (store.root / "clients" / client_id).resolve()
        _mkdir_private(self.dir)
        self._cipher = ClientCipher(store._master, client_id)

    # -- helpers ----------------------------------------------------------
    def _obj(self, *parts: str) -> Path:
        return self._inside(self.dir.joinpath(*parts))

    def _seal_to(self, path: Path, kind: str, object_id: str, data: bytes) -> None:
        _write_private(path, self._cipher.seal(kind, object_id, data))

    def _open_from(self, path: Path, kind: str, object_id: str) -> bytes:
        try:
            return self._cipher.open(kind, object_id, path.read_bytes())
        except DecryptionError:
            raise WorkspaceIsolationError("stored object failed authentication") from None

    # -- profile (display name lives here, encrypted -- not in the accounts DB) --
    def save_profile(self, profile: dict) -> None:
        self._seal_to(self._obj("profile.enc"), "profile", "profile",
                      json.dumps(profile).encode("utf-8"))

    def load_profile(self) -> dict:
        p = self._obj("profile.enc")
        if not p.exists():
            return {}
        return json.loads(self._open_from(p, "profile", "profile"))

    # -- sessions ---------------------------------------------------------
    def _session_path(self, session_id: str) -> Path:
        return self._obj("sessions", f"{_check_id(session_id, 'session id')}.enc")

    def save_session(self, session: "InterviewSession") -> Path:
        if session.client_id != self.client_id:
            raise WorkspaceIsolationError("session belongs to another workspace")
        path = self._session_path(session.interview_id)
        self._seal_to(path, "session", session.interview_id,
                      json.dumps(session.to_dict()).encode("utf-8"))
        return path

    def load_session(self, session_id: str) -> "InterviewSession":
        from laylaw.interviewer.session import InterviewSession

        path = self._session_path(session_id)
        if not path.exists():
            raise FileNotFoundError("no such session in this workspace")
        data = json.loads(self._open_from(path, "session", session_id))
        if data.get("client_id") != self.client_id or data.get("interview_id") != session_id:
            raise WorkspaceIsolationError("stored session does not belong to this workspace")
        session = InterviewSession.from_dict(data)
        session.workspace = self
        return session

    def has_session(self, session_id: str) -> bool:
        try:
            return self._session_path(session_id).exists()
        except WorkspaceIsolationError:
            return False

    def list_sessions(self) -> list[str]:
        d = self.dir / "sessions"
        return sorted(p.stem for p in d.glob("*.enc")) if d.exists() else []

    # -- drafts (unsent answer text, so a long answer survives a closed tab) --
    def save_draft(self, session_id: str, text: str) -> None:
        path = self._obj("drafts", f"{_check_id(session_id, 'session id')}.enc")
        self._seal_to(path, "draft", session_id, text.encode("utf-8"))

    def load_draft(self, session_id: str) -> str:
        path = self._obj("drafts", f"{_check_id(session_id, 'session id')}.enc")
        return self._open_from(path, "draft", session_id).decode("utf-8") if path.exists() else ""

    def clear_draft(self, session_id: str) -> None:
        path = self._obj("drafts", f"{_check_id(session_id, 'session id')}.enc")
        if path.exists():
            path.unlink()

    # -- last shown prompt (so a page reload shows the same full wording) --
    def save_prompt(self, session_id: str, pending_text: str, shown: str) -> None:
        path = self._obj("prompts", f"{_check_id(session_id, 'session id')}.enc")
        self._seal_to(path, "prompt", session_id, json.dumps([pending_text, shown]).encode("utf-8"))

    def load_prompt(self, session_id: str) -> Optional[list]:
        path = self._obj("prompts", f"{_check_id(session_id, 'session id')}.enc")
        return json.loads(self._open_from(path, "prompt", session_id)) if path.exists() else None

    def clear_prompt(self, session_id: str) -> None:
        path = self._obj("prompts", f"{_check_id(session_id, 'session id')}.enc")
        if path.exists():
            path.unlink()

    # -- uploads ----------------------------------------------------------
    def store_upload(self, session_id: str, filename: str, data: bytes, label: Optional[str] = None,
                     provenance_type: ProvenanceType = ProvenanceType.DOCUMENT) -> SupportingRecord:
        _check_id(session_id, "session id")
        record_id = "R-" + secrets.token_hex(10)
        safe = _safe_filename(filename)
        rel = Path("uploads") / session_id / f"{record_id}.enc"          # no filename on disk
        self._seal_to(self._obj(*rel.parts), "upload", f"{session_id}/{record_id}", data)
        return SupportingRecord(
            id=record_id, client_id=self.client_id, session_id=session_id,
            label=label or safe, provenance_type=provenance_type, filename=safe,
            sha256=hashlib.sha256(data).hexdigest(), stored_path=str(rel),
        )

    def read_upload(self, record: SupportingRecord) -> bytes:
        if record.client_id != self.client_id or not RECORD_ID_RE.match(record.id or ""):
            raise WorkspaceIsolationError("record belongs to another workspace")
        _check_id(record.session_id, "session id")
        path = self._obj("uploads", record.session_id, f"{record.id}.enc")
        data = self._open_from(path, "upload", f"{record.session_id}/{record.id}")
        if record.sha256 and hashlib.sha256(data).hexdigest() != record.sha256:
            raise WorkspaceIsolationError("upload failed integrity check")
        return data
