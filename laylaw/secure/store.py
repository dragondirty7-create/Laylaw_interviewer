"""Encrypted client workspaces: a drop-in replacement for WorkspaceStore / ClientWorkspace.

The Interviewer engine only uses `client_id`, `save_session`, and
`store_upload` on its workspace, so it runs unchanged on top of this store.
Every read, write and delete goes through the unlocked vault (authenticated
encryption, opaque file names) and is recorded in the audit log without case
content.

Logical layout (never visible on disk):
    clients                         -> {client_id: {"created": ...}}
    ws/<client>/index               -> sessions and uploads in this workspace
    ws/<client>/session/<id>        -> one InterviewSession as JSON
    ws/<client>/upload/<record id>  -> one uploaded file's bytes
    ws/<client>/record/<kind>/<id>  -> one structured record (for example an incident intake)
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..interviewer.models import ProvenanceType, SupportingRecord
from ..interviewer.workspace import WorkspaceIsolationError, _check_id, _safe_filename
from .audit import AuditLog
from .errors import RealDataModeError, SecureStorageError
from .vault import UnlockedVault

if TYPE_CHECKING:
    from ..interviewer.session import InterviewSession

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SAVE_AUDIT_INTERVAL_S = 60  # the engine saves after every step; log saves at most once a minute per session


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SecureStore:
    def __init__(self, vault: UnlockedVault, audit: AuditLog):
        self.vault = vault
        self.audit = audit
        self.root = vault.root
        self._last_save_audit: dict[str, float] = {}
        self._saves_since: dict[str, int] = {}

    # -- helpers -----------------------------------------------------------
    def _read_bytes(self, logical: str) -> bytes:
        try:
            return self.vault.read(logical)
        except SecureStorageError:
            self.audit.append("integrity_error", detail={"what": logical.split("/")[0]})
            raise

    def _read_json(self, logical: str, default):
        try:
            return json.loads(self._read_bytes(logical))
        except FileNotFoundError:
            return default

    def _write_json(self, logical: str, data) -> None:
        self.vault.write(logical, json.dumps(data, indent=1).encode("utf-8"))

    def ref(self, value: str) -> str:
        return self.vault.opaque_ref(value)

    # -- workspaces -----------------------------------------------------------
    def list_clients(self) -> list[str]:
        return sorted(self._read_json("clients", {}))

    def workspace(self, client_id: str) -> "SecureWorkspace":
        cid = _check_id(client_id, "client id")
        clients = self._read_json("clients", {})
        if cid not in clients:
            clients[cid] = {"created": _now()}
            self._write_json("clients", clients)
        return SecureWorkspace(self, cid)

    def existing_workspace(self, client_id: str) -> "SecureWorkspace":
        cid = _check_id(client_id, "client id")
        if cid not in self._read_json("clients", {}):
            raise FileNotFoundError("no such workspace")
        return SecureWorkspace(self, cid)

    def delete_workspace(self, client_id: str) -> dict:
        ws = self.existing_workspace(client_id)
        counts = {"sessions": 0, "uploads": 0}
        for sid in ws.list_sessions():
            c = ws.delete_session(sid, _audit=False)
            counts["sessions"] += 1
            counts["uploads"] += c["uploads"]
        for kind, rid in ws.list_record_keys():
            c = ws.delete_record(kind, rid, _audit=False)
            counts["records"] = counts.get("records", 0) + 1
            counts["uploads"] += c["uploads"]
        self.vault.erase(ws._index_name)
        clients = self._read_json("clients", {})
        clients.pop(ws.client_id, None)
        self._write_json("clients", clients)
        self.audit.append("workspace_deleted", ws=self.ref(ws.client_id), detail=counts)
        return counts

    def export(self, *_args, **_kwargs):
        """Export of real case material is disabled until a secure export exists (Issue #2, item 6)."""
        self.audit.append("export_refused", detail={"reason": "export_disabled_in_vault"})
        raise RealDataModeError("Export is disabled for encrypted Laylaw data. View outputs inside the app; "
                                "a secure export will be added in a later reviewed phase.")


class SecureWorkspace:
    def __init__(self, store: SecureStore, client_id: str):
        self.store = store
        self.client_id = client_id
        self._vault = store.vault
        self._audit = store.audit
        self._index_name = f"ws/{client_id}/index"

    @property
    def ref(self) -> str:
        return self.store.ref(self.client_id)

    def _index(self) -> dict:
        idx = self.store._read_json(self._index_name, {"sessions": {}, "uploads": {}})
        if idx.get("client_id", self.client_id) != self.client_id:
            raise WorkspaceIsolationError("stored index does not belong to this workspace")
        return idx

    def _save_index(self, idx: dict) -> None:
        idx["client_id"] = self.client_id
        self.store._write_json(self._index_name, idx)

    def _session_name(self, session_id: str) -> str:
        return f"ws/{self.client_id}/session/{_check_id(session_id, 'session id')}"

    # -- sessions ---------------------------------------------------------
    def save_session(self, session: "InterviewSession") -> str:
        if session.client_id != self.client_id:
            raise WorkspaceIsolationError(f"session belongs to {session.client_id}, not {self.client_id}")
        sid = session.interview_id
        self._vault.write(self._session_name(sid), json.dumps(session.to_dict()).encode("utf-8"))
        idx = self._index()
        new = sid not in idx["sessions"]
        entry = idx["sessions"].setdefault(sid, {"created": _now()})
        entry.update({"updated": session.last_updated, "status": getattr(session.status, "value", str(session.status)),
                      "interviewee": session.interviewee, "case_id": session.case_id, "path": session.path_name})
        self._save_index(idx)

        sref = self.store.ref(sid)
        if new:
            self._audit.append("session_created", ws=self.ref, session=sref)
            self.store._last_save_audit[sid] = time.monotonic()
            return sid
        self.store._saves_since[sid] = self.store._saves_since.get(sid, 0) + 1
        if time.monotonic() - self.store._last_save_audit.get(sid, 0) >= SAVE_AUDIT_INTERVAL_S:
            self._audit.append("session_save", ws=self.ref, session=sref,
                               detail={"saves": self.store._saves_since.pop(sid, 1)})
            self.store._last_save_audit[sid] = time.monotonic()
        return sid

    def load_session(self, session_id: str) -> "InterviewSession":
        from ..interviewer.session import InterviewSession

        name = self._session_name(session_id)
        if session_id not in self._index()["sessions"] or not self._vault.exists(name):
            raise FileNotFoundError(f"no session {session_id} in workspace {self.client_id}")
        data = json.loads(self.store._read_bytes(name))
        if data.get("client_id") != self.client_id:
            raise WorkspaceIsolationError("stored session does not belong to this workspace")
        session = InterviewSession.from_dict(data)
        session.workspace = self
        self._audit.append("session_open", ws=self.ref, session=self.store.ref(session_id))
        return session

    def list_sessions(self) -> list[str]:
        return sorted(self._index()["sessions"])

    def session_summaries(self) -> list[dict]:
        """Metadata for the app's home page (decrypted in memory only)."""
        return [{"id": sid, **meta} for sid, meta in sorted(self._index()["sessions"].items(),
                                                            key=lambda kv: kv[1].get("updated", ""), reverse=True)]

    def delete_session(self, session_id: str, _audit: bool = True) -> dict:
        idx = self._index()
        if session_id not in idx["sessions"]:
            raise FileNotFoundError("no such session")
        uploads = [rid for rid, meta in idx["uploads"].items() if meta.get("session_id") == session_id]
        for rid in uploads:
            self._vault.erase(f"ws/{self.client_id}/upload/{rid}")
            idx["uploads"].pop(rid, None)
        self._vault.erase(self._session_name(session_id))
        idx["sessions"].pop(session_id, None)
        self._save_index(idx)
        counts = {"uploads": len(uploads)}
        if _audit:
            self._audit.append("session_deleted", ws=self.ref, session=self.store.ref(session_id), detail=counts)
        return counts

    # -- structured records -------------------------------------------------
    # Small JSON documents other than interview sessions, such as an incident
    # intake. Stored encrypted like everything else; the audit log records only
    # the kind and an opaque reference, never the content.
    _RECORD_KINDS = {"intake"}

    def _record_name(self, kind: str, record_id: str) -> str:
        if kind not in self._RECORD_KINDS:
            raise ValueError(f"unknown record kind {kind!r}")
        return f"ws/{self.client_id}/record/{kind}/{_check_id(record_id, 'record id')}"

    def save_record(self, kind: str, record_id: str, data: dict) -> None:
        name = self._record_name(kind, record_id)
        if data.get("client_id") != self.client_id:
            raise WorkspaceIsolationError("record belongs to another workspace")
        self._vault.write(name, json.dumps(data).encode("utf-8"))
        idx = self._index()
        records = idx.setdefault("records", {}).setdefault(kind, {})
        new = record_id not in records
        records[record_id] = {"updated": _now()}
        self._save_index(idx)
        if new:
            self._audit.append("record_created", ws=self.ref, session=self.store.ref(record_id),
                               detail={"kind": kind})

    def load_record(self, kind: str, record_id: str) -> dict:
        name = self._record_name(kind, record_id)
        if record_id not in self._index().get("records", {}).get(kind, {}) or not self._vault.exists(name):
            raise FileNotFoundError(f"no {kind} {record_id} in workspace {self.client_id}")
        data = json.loads(self.store._read_bytes(name))
        if data.get("client_id") != self.client_id:
            raise WorkspaceIsolationError("stored record does not belong to this workspace")
        return data

    def list_records(self, kind: str) -> list[str]:
        return sorted(self._index().get("records", {}).get(kind, {}))

    def list_record_keys(self) -> list[tuple[str, str]]:
        return [(k, rid) for k, ids in sorted(self._index().get("records", {}).items()) for rid in sorted(ids)]

    def delete_record(self, kind: str, record_id: str, _audit: bool = True) -> dict:
        idx = self._index()
        if record_id not in idx.get("records", {}).get(kind, {}):
            raise FileNotFoundError("no such record")
        uploads = [rid for rid, meta in idx["uploads"].items() if meta.get("session_id") == record_id]
        for rid in uploads:
            self._vault.erase(f"ws/{self.client_id}/upload/{rid}")
            idx["uploads"].pop(rid, None)
        self._vault.erase(self._record_name(kind, record_id))
        idx["records"][kind].pop(record_id, None)
        self._save_index(idx)
        counts = {"uploads": len(uploads)}
        if _audit:
            self._audit.append("record_deleted", ws=self.ref, session=self.store.ref(record_id),
                               detail={"kind": kind, **counts})
        return counts

    # -- uploads ----------------------------------------------------------
    def store_upload(self, session_id: str, filename: str, data: bytes, label: str | None = None,
                     provenance_type: ProvenanceType = ProvenanceType.DOCUMENT) -> SupportingRecord:
        _check_id(session_id, "session id")
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(f"uploads are limited to {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
        record_id = "R-" + uuid.uuid4().hex[:10]
        safe = _safe_filename(filename)
        self._vault.write(f"ws/{self.client_id}/upload/{record_id}", data)
        idx = self._index()
        idx["uploads"][record_id] = {"session_id": session_id, "size": len(data)}
        self._save_index(idx)
        self._audit.append("upload_stored", ws=self.ref, session=self.store.ref(session_id),
                           detail={"bytes": len(data)})
        return SupportingRecord(
            id=record_id, client_id=self.client_id, session_id=session_id,
            label=label or safe, provenance_type=provenance_type, filename=safe,
            sha256=hashlib.sha256(data).hexdigest(),
            stored_path=f"vault:{record_id}",
        )

    def read_upload(self, record: SupportingRecord) -> bytes:
        if record.client_id != self.client_id:
            raise WorkspaceIsolationError("record belongs to another workspace")
        _check_id(record.id, "record id")
        data = self.store._read_bytes(f"ws/{self.client_id}/upload/{record.id}")
        self._audit.append("upload_read", ws=self.ref, session=self.store.ref(record.session_id),
                           detail={"bytes": len(data)})
        return data
