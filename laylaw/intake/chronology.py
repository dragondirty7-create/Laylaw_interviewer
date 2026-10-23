"""Neutral chronology and evidence inventory, built from what the person entered.

Every row says what it rests on:

  USER_STATEMENT  the person said it
  EVIDENCE        a detail of a file, as entered for that file (the file itself is not read)
  INFERENCE       Laylaw placed it, for example by the order the lines were written in
  UNKNOWN         not known or not given
  CONFLICT        two things the person provided point different ways; both are kept, neither is chosen

Nothing here interprets or judges what happened.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .model import EVIDENCE_CATEGORY_LABELS, AnswerStatus, IncidentIntake
from .steps import STEP_BY_ID

USER_STATEMENT = "USER_STATEMENT"
EVIDENCE = "EVIDENCE"
INFERENCE = "INFERENCE"
UNKNOWN = "UNKNOWN"
CONFLICT = "CONFLICT"

BASIS_LABELS = {
    USER_STATEMENT: "You said",
    EVIDENCE: "File details (as entered)",
    INFERENCE: "Placed by Laylaw",
    UNKNOWN: "Not known",
    CONFLICT: "Two things differ",
}

_LEADING_TIME = re.compile(
    r"^\s*(?P<when>(?:(?:about|around|approx\.?|approximately|maybe|~)\s*)?"
    r"\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?)\s*(?:[-–—:,]\s*|\s+)(?P<what>\S.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Row:
    when: str
    what: str
    basis: str
    #: How the "when" is known, separately from the event itself.
    when_basis: str


def _split_line(line: str) -> tuple[str | None, str]:
    m = _LEADING_TIME.match(line)
    if m and re.search(r"\d", m.group("when")):
        # A bare number like "2 people came in" is not a time. Require a colon or am/pm.
        when = m.group("when").strip()
        if ":" in when or "." in when or re.search(r"[ap]\.?m", when, re.IGNORECASE):
            return when, m.group("what").strip()
    return None, line.strip()


def chronology(intake: IncidentIntake) -> list[Row]:
    rows: list[Row] = []
    day = intake.value("incident_date")
    day_text = day if day else "Day not known"
    day_basis = USER_STATEMENT if day else UNKNOWN
    time_text = intake.value("incident_time")

    lines = [ln for ln in (intake.value("what_happened") or "").splitlines() if ln.strip()]
    if lines:
        for ln in lines:
            when, what = _split_line(ln)
            if when:
                rows.append(Row(f"{day_text}, {when}", what, USER_STATEMENT, USER_STATEMENT))
            else:
                rows.append(Row(f"{day_text}, time not given", what, USER_STATEMENT, INFERENCE))
    elif intake.value("summary"):
        when = f"{day_text}, {time_text}" if time_text else day_text
        rows.append(Row(when, intake.value("summary") or "", USER_STATEMENT, day_basis))
    else:
        rows.append(Row(day_text, "What happened has not been described yet.", UNKNOWN, day_basis))

    for step_id, label in (("entrant_response", "Response of the person who came in"),
                           ("resident_response", "Response of the person at home")):
        v = intake.value(step_id)
        if v:
            rows.append(Row(f"{day_text}, after the entry", f"{label}: {v}", USER_STATEMENT, INFERENCE))

    mgmt = intake.value("management_response")
    if mgmt:
        rows.append(Row("Afterwards, date not given", f"Property manager or landlord: {mgmt}", USER_STATEMENT,
                        UNKNOWN))

    for ev in intake.evidence:
        if ev.date_text:
            cat = EVIDENCE_CATEGORY_LABELS.get(ev.category, ev.category)
            rows.append(Row(ev.date_text, f"File: {cat} ({ev.filename})", EVIDENCE, EVIDENCE))
    return rows


def conflicts(intake: IncidentIntake) -> list[str]:
    """Places where what the person said and what they uploaded point different ways."""
    out: list[str] = []
    cats = {e.category for e in intake.evidence}
    if intake.value("notice_given") == "no" and "entry_notice" in cats:
        out.append("You said you weren't told beforehand, and a file was added as an entry notice or log. "
                   "Both are kept as given.")
    if intake.value("notice_given") == "yes" and not intake.value("notice_details") and \
            intake.answers.get("notice_details") is not None:
        out.append("You said you were told beforehand, but how and when wasn't given.")
    if intake.value("open_request") == "no" and "work_order" in cats:
        out.append("You said no repair request was open, and a file was added as a maintenance request or "
                   "work order. Both are kept as given.")
    if intake.value("consent_given") == "yes" and intake.value("entry_method") == "unlocked":
        out.append("You said someone at home said it was OK to come in, and also that they opened an unlocked "
                   "door. Both are kept as given.")
    return out


def open_questions(intake: IncidentIntake) -> list[str]:
    """Questions answered "I'm not sure" or skipped, plus anything the person flagged themselves."""
    out: list[str] = []
    for step in intake.applicable_steps():
        if step.kind in ("upload",) or step.id == "stage_gate":
            continue
        a = intake.answers.get(step.id)
        if a is None:
            out.append(f"Not answered yet: {step.prompt}")
        elif a.status == AnswerStatus.NOT_SURE:
            out.append(f"Not sure: {step.prompt}")
        elif a.status == AnswerStatus.SKIPPED:
            out.append(f"Skipped: {step.prompt}")
    flagged = intake.value("unresolved")
    if flagged:
        out.append(f"You noted: {flagged}")
    return out + [f"Differs: {c}" for c in conflicts(intake)]


def evidence_inventory(intake: IncidentIntake) -> list[dict]:
    return [{
        "file": ev.filename,
        "kind": EVIDENCE_CATEGORY_LABELS.get(ev.category, ev.category),
        "source": ev.source or "Not given",
        "date": ev.date_text or "Not given",
        "original": "Original kept unchanged" if ev.original_preserved else "Changed",
        "sha256": ev.sha256,
        "size": ev.size,
        "notes": ev.notes,
        "added": ev.stored_at,
    } for ev in intake.evidence]


def step_prompt(step_id: str) -> str:
    return STEP_BY_ID[step_id].prompt
