"""Storing incident intakes inside the encrypted vault.

Each intake is its own matter in its own workspace, labelled with a random
id, so it shares nothing with any other client or interview. Uploaded files go
through the vault's existing upload path and are never modified afterwards;
notes about a file live in the intake record beside it.
"""
from __future__ import annotations

import hashlib
import uuid

from ..secure.store import SecureStore, SecureWorkspace
from .model import EVIDENCE_CATEGORY_LABELS, EvidenceItem, IncidentIntake, IntakeError, now_iso

KIND = "intake"
MATTER_PREFIX = "matter-"


def new_matter(store: SecureStore, nickname: str, *, synthetic: bool) -> tuple[SecureWorkspace, IncidentIntake]:
    cid = MATTER_PREFIX + uuid.uuid4().hex[:12]
    ws = store.workspace(cid)
    intake = IncidentIntake.new(cid, nickname, synthetic=synthetic)
    save(ws, intake)
    return ws, intake


def save(ws: SecureWorkspace, intake: IncidentIntake) -> None:
    if intake.client_id != ws.client_id:
        raise IntakeError("That intake belongs to a different matter.")
    ws.save_record(KIND, intake.matter_id, intake.to_dict())


def load(ws: SecureWorkspace, matter_id: str) -> IncidentIntake:
    intake = IncidentIntake.from_dict(ws.load_record(KIND, matter_id))
    if intake.client_id != ws.client_id or intake.matter_id != matter_id:
        raise IntakeError("That intake belongs to a different matter.")
    return intake


def list_matters(store: SecureStore) -> list[dict]:
    out = []
    for cid in store.list_clients():
        if not cid.startswith(MATTER_PREFIX):
            continue
        ws = store.existing_workspace(cid)
        for mid in ws.list_records(KIND):
            it = load(ws, mid)
            done, total = it.progress()
            out.append({"client_id": cid, "matter_id": mid, "nickname": it.nickname, "updated": it.updated_at,
                        "done": done, "total": total, "finished": it.finished, "files": len(it.evidence)})
    return sorted(out, key=lambda m: m["updated"], reverse=True)


def add_evidence(ws: SecureWorkspace, intake: IncidentIntake, *, filename: str, data: bytes, category: str,
                 source: str = "", date_text: str = "", notes: str = "") -> EvidenceItem:
    if category not in EVIDENCE_CATEGORY_LABELS:
        raise IntakeError("Choose what kind of file this is.")
    if not data:
        raise IntakeError("That file is empty.")
    record = ws.store_upload(intake.matter_id, filename or "file", data, label=EVIDENCE_CATEGORY_LABELS[category])
    item = EvidenceItem(id=record.id, category=category, filename=record.filename or "file",
                        sha256=hashlib.sha256(data).hexdigest(), size=len(data), stored_at=now_iso(),
                        source=source.strip()[:120], date_text=date_text.strip()[:40], notes=notes.strip()[:500])
    intake.add_evidence(item)
    save(ws, intake)
    return item


def verify_evidence(ws: SecureWorkspace, intake: IncidentIntake) -> dict[str, bool]:
    """Re-hash every stored file against the hash taken at upload. True means unchanged."""
    from ..interviewer.models import ProvenanceType, SupportingRecord

    out = {}
    for ev in intake.evidence:
        rec = SupportingRecord(id=ev.id, client_id=ws.client_id, session_id=intake.matter_id, label=ev.category,
                               provenance_type=ProvenanceType.DOCUMENT, filename=ev.filename, sha256=ev.sha256)
        out[ev.id] = hashlib.sha256(ws.read_upload(rec)).hexdigest() == ev.sha256
    return out


def delete_matter(store: SecureStore, client_id: str) -> dict:
    if not client_id.startswith(MATTER_PREFIX):
        raise IntakeError("Only incident intake matters can be deleted here.")
    return store.delete_workspace(client_id)
