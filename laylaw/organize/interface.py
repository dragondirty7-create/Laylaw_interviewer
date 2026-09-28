"""Hand-off interface from INTERVIEW to the (future) ORGANIZE stage.

The interviewer keeps its seven canonical outputs. It does NOT build a case
packet. This module only defines:

  * `export_for_organize(session)` -- a read-only, versioned snapshot of the
    interview record with provenance, uncertainty, corrections and
    discrepancies intact, for an ORGANIZE component to consume; and
  * `Organizer` -- the protocol an ORGANIZE component will implement to produce
    the case-packet pieces (overview, dated timeline, document index,
    missing-information checklist, questions for counsel).

Nothing here runs ORGANIZE logic; `NotImplementedOrganizer` refuses every call.
"""
from __future__ import annotations

from typing import Protocol

from ..interviewer import outputs
from ..interviewer.models import FactStatus, to_jsonable

EXPORT_SCHEMA = "laylaw.interview-export/1"

ORGANIZE_PRODUCTS = (
    "concise_overview",
    "dated_timeline",
    "document_index",
    "missing_information_checklist",
    "questions_for_counsel",
)

# Rules every downstream consumer must honor (copied from the canonical spec).
DOWNSTREAM_RULES = (
    "Preserve provenance and uncertainty captured in the interview.",
    "Never silently rewrite uncertain interview statements into definite allegations.",
    "Never describe an unreviewed record as corroboration.",
    "Keep requested outcomes separate from historical facts.",
    "Superseded facts are kept; use the current version and cite the correction.",
    "Never attribute an AI-generated inference to a human source.",
)


def export_for_organize(session) -> dict:
    """A snapshot for ORGANIZE. It carries the interview's own seven outputs plus
    the structured record, and is never used to change the interview record."""
    return {
        "schema": EXPORT_SCHEMA,
        "source_stage": session.mode.value,
        "interview_id": session.interview_id,
        "case_id": session.case_id,
        "client_id": session.client_id,
        "transcript_status": session.transcript_status.value,
        "downstream_rules": list(DOWNSTREAM_RULES),
        "interview_outputs": outputs.all_outputs(session),
        "facts": [to_jsonable(f) for f in session.facts],
        "current_fact_ids": [f.id for f in session.facts if f.status == FactStatus.CURRENT],
        "corrections": [to_jsonable(c) for c in session.corrections],
        "discrepancies": [to_jsonable(d) for d in session.discrepancies],
        "records": [to_jsonable(r) for r in session.records],
        "document_candidates": [to_jsonable(c) for c in session.candidates],
        "requested_outcomes": [to_jsonable(o) for o in session.outcomes],
        "intake": [to_jsonable(i) for i in session.intake],
        "raw_answers": [to_jsonable(r) for r in session.raw_answers],
    }


class Organizer(Protocol):
    """What a future ORGANIZE component provides. Input is `export_for_organize`."""

    def concise_overview(self, export: dict) -> str: ...
    def dated_timeline(self, export: dict) -> list[dict]: ...
    def document_index(self, export: dict) -> list[dict]: ...
    def missing_information_checklist(self, export: dict) -> list[str]: ...
    def questions_for_counsel(self, export: dict) -> list[str]: ...


class NotImplementedOrganizer:
    """Placeholder so callers can wire the interface now. ORGANIZE is a separate stage."""

    def _refuse(self, *_a, **_k):
        raise NotImplementedError("ORGANIZE is a separate Laylaw stage and is not implemented yet")

    concise_overview = dated_timeline = document_index = _refuse
    missing_information_checklist = questions_for_counsel = _refuse
