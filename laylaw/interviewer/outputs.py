"""The seven Laylaw Interviewer outputs, kept separate as the spec requires:

1. Interview Record   2. Fact Table   3. Timeline   4. Evidence Follow-up List
5. Open Questions     6. Requested Outcomes (never mixed into facts)
7. Handoff Summary

All renderers are neutral: no legal argument, no strategy, no "verified",
and no description of an unreviewed record as proof or corroboration.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .guard import assert_no_advocacy
from .models import (
    Certainty, DatePrecision, Fact, ReviewStatus, SourceOfKnowledge, TranscriptStatus,
)

if TYPE_CHECKING:
    from .session import InterviewSession

SOURCE_LABEL = {
    SourceOfKnowledge.PERSONAL_OBSERVATION: "PERSONAL-OBSERVATION",
    SourceOfKnowledge.SECONDHAND: "SECONDHAND",
    SourceOfKnowledge.INFERENCE: "INFERENCE",
    SourceOfKnowledge.DOCUMENT_RECOLLECTION: "DOCUMENT-RECOLLECTION",
    SourceOfKnowledge.UNCERTAIN: "UNCERTAIN",
    SourceOfKnowledge.UNKNOWN: "UNKNOWN",
    SourceOfKnowledge.REQUEST: "REQUEST",
}
UNRESOLVED_DATE = "[UNRESOLVED DATE DISCREPANCY]"


def _quote_allowed(f: Fact, s: "InterviewSession") -> bool:
    return f.exact_wording_remembered or s.transcript_status == TranscriptStatus.FULL_VERBATIM


def statement_text(f: Fact, s: "InterviewSession") -> str:
    """Quotation marks only when a transcript exists or the interviewee
    specifically remembers the wording; otherwise marked as a recollection."""
    if _quote_allowed(f, s):
        return f'"{f.statement}"'
    return f"Recollection (paraphrase of interviewee's answer): {f.statement}"


def date_text(f: Fact) -> str:
    if f.date is None:
        return "Date not given [UNKNOWN]"
    return f.date.display()


def neutral_fact_line(f: Fact, s: "InterviewSession") -> str:
    parts = [f"[{SOURCE_LABEL[f.source]}]", statement_text(f, s), f"Date: {date_text(f)}"]
    if f.certainty != Certainty.STATED:
        parts.append(f"Interviewee uncertainty preserved ({', '.join(f.hedges) or f.certainty.value})")
    if f.told_by:
        who = f"{f.told_by} (child)" if f.told_by_is_child else f.told_by
        parts.append(f"Reported to interviewee by: {who}")
    return " | ".join(parts)


def _unresolved_ids(s: "InterviewSession") -> set[str]:
    return {fid for d in s.discrepancies if d.status == "unresolved" for fid in d.fact_ids}


# 1 ---------------------------------------------------------------------------
def interview_record(s: "InterviewSession") -> str:
    status = s.transcript_status.value
    heading = "INTERVIEW RECORD"
    lines = [
        heading,
        f"Interview ID: {s.interview_id}", f"Case ID: {s.case_id}", f"Interviewee: {s.interviewee}",
        f"Interviewer: {s.interviewer}", f"Purpose: {s.purpose}", f"Date started: {s.date_started}",
        f"Last updated: {s.last_updated}", f"Transcript status: {status}",
        f"Session: {'continuation' if s.is_continuation else 'new interview'} ({s.status.value})",
        f"Current section: {s.current_section or '-'}",
        f"Completed sections: {', '.join(s.completed_sections) or '-'}",
        f"Last question answered: {s.last_question_answered or '-'}",
        "",
        "STRUCTURED NOTES" if s.transcript_status != TranscriptStatus.FULL_VERBATIM else "TRANSCRIPT-BACKED NOTES",
    ]
    if s.transcript_status == TranscriptStatus.RECONSTRUCTED:
        lines.append("These notes were reconstructed from available session data. They are not a transcript.")
    for f in s.facts:
        lines.append(f"- {f.id} ({f.topic}) {neutral_fact_line(f, s)}")
    for fd in s.findings:
        f = s.get_fact(fd.fact_id)
        lines += [f"- Document check for {f.id}:",
                  f"    INTERVIEWEE RECOLLECTION: {f.statement} (date as recalled: {date_text(f)})",
                  f"    DOCUMENT CONTENT [{fd.provenance.label}]: {fd.content}"
                  + (f" (date in document: {fd.date.display()})" if fd.date else ""),
                  f"    CONSISTENCY / DIFFERENCE: {fd.consistency}"
                  + (f" - {fd.difference_note}" if fd.difference_note else "")]
    if s.discrepancies:
        lines += ["", "UNCERTAINTIES AND DISCREPANCIES"]
        for d in s.discrepancies:
            tag = UNRESOLVED_DATE if d.status == "unresolved" and d.field == "date" else f"[{d.status.upper()}]"
            lines.append(f"- {d.id} {tag} {d.description}"
                         + (f" | {d.resolution_note}" if d.resolution_note else ""))
    if s.corrections:
        lines += ["", "CORRECTIONS BY INTERVIEWEE"] + [f"- {c}" for c in s.corrections]
    if s.safety_notes:
        lines += ["", "SAFETY PAUSES"] + [f"- {n}" for n in s.safety_notes]
    return assert_no_advocacy("\n".join(lines), s.mode)


# 2 ---------------------------------------------------------------------------
def fact_table(s: "InterviewSession") -> list[dict]:
    unresolved = _unresolved_ids(s)
    rows = []
    for f in s.facts:
        records = [next(r for r in s.records if r.id == rid).describe() for rid in f.possible_records]
        notes = list(f.open_questions)
        if f.id in unresolved:
            notes.append(UNRESOLVED_DATE)
        rows.append({
            "FACT ID": f.id,
            "STATEMENT": statement_text(f, s),
            "KNOWLEDGE SOURCE": SOURCE_LABEL[f.source],
            "DATE / DATE PRECISION": date_text(f),
            "RELATED EVENT": f.event_key,
            "POTENTIAL SUPPORTING RECORD": records,
            "VERIFICATION STATUS": f.verification.value,
            "NOTES": notes,
            "PROVENANCE": f.provenance.label,
        })
    assert_no_advocacy(repr(rows), s.mode)
    return rows


# 3 ---------------------------------------------------------------------------
def timeline(s: "InterviewSession") -> list[dict]:
    """Historical facts only. Requested outcomes live in a separate list and are
    never placed here. Undated facts are listed after dated ones, not guessed."""
    unresolved = _unresolved_ids(s)
    historical = [f for f in s.facts if f.source != SourceOfKnowledge.REQUEST]
    dated = sorted([f for f in historical if f.date and f.date.year],
                   key=lambda f: f.date.sort_key())
    undated = [f for f in historical if not (f.date and f.date.year)]
    events = []
    for f in dated + undated:
        events.append({
            "EVENT ID": f.id,
            "DATE": date_text(f),
            "DATE PRECISION": f.date.precision.value if f.date else DatePrecision.UNKNOWN.value,
            "LOCATION": f.location or "not stated",
            "PEOPLE PRESENT": f.people_present or ["not stated"],
            "WHAT HAPPENED": statement_text(f, s),
            "KIND": f.kind.value,
            "SEQUENCE": f.sequence_hint or "not stated",
            "SOURCE OF KNOWLEDGE": SOURCE_LABEL[f.source],
            "POSSIBLE SUPPORTING RECORDS": [
                next(r for r in s.records if r.id == rid).describe() for rid in f.possible_records],
            "UNRESOLVED QUESTIONS": f.open_questions + ([UNRESOLVED_DATE] if f.id in unresolved else []),
        })
    assert_no_advocacy(repr(events), s.mode)
    return events


# 4 ---------------------------------------------------------------------------
def evidence_followup(s: "InterviewSession") -> list[str]:
    out = []
    for r in s.records:
        facts = ", ".join(r.related_fact_ids) or "no specific fact yet"
        state = "may help clarify" if r.review_status == ReviewStatus.UNREVIEWED else "reviewed; see document check"
        out.append(f"{r.describe()} - {state} ({facts}). Attached to client {r.client_id}, session {r.session_id}.")
    for f in s.facts:
        if f.source == SourceOfKnowledge.SECONDHAND and f.told_by:
            out.append(f"Possible witness: {f.told_by} (source of secondhand information in {f.id}). "
                       f"Do not re-question a child; note only."
                       if f.told_by_is_child else
                       f"Possible witness: {f.told_by} (source of secondhand information in {f.id}).")
    return [assert_no_advocacy(x, s.mode) for x in out]


# 5 ---------------------------------------------------------------------------
def open_questions(s: "InterviewSession") -> list[str]:
    out = list(s.open_questions)
    for f in s.facts:
        if f.date is None or f.date.precision == DatePrecision.UNKNOWN:
            out.append(f"{f.id}: when this happened (not yet known)")
        if not f.people_present:
            out.append(f"{f.id}: who was present (not yet stated)")
    for d in s.discrepancies:
        if d.status == "unresolved":
            out.append(f"{d.id}: {UNRESOLVED_DATE} {d.description}")
    for q in ([s.pending] if s.pending else []) + s.queue:
        if q.kind == "clarify":
            out.append(f"Not yet asked: {q.text} ({q.fact_id})")
    return [assert_no_advocacy(x, s.mode) for x in out]


# 6 ---------------------------------------------------------------------------
def requested_outcomes(s: "InterviewSession") -> list[dict]:
    return [{"ID": o.id, "REQUEST": o.text, "PROVENANCE": o.provenance.label,
             "NOTE": "Requested future outcome - not a historical fact."} for o in s.outcomes]


# 7 ---------------------------------------------------------------------------
def handoff_summary(s: "InterviewSession") -> str:
    by_src: dict[str, int] = {}
    for f in s.facts:
        by_src[SOURCE_LABEL[f.source]] = by_src.get(SOURCE_LABEL[f.source], 0) + 1
    unresolved = [d for d in s.discrepancies if d.status == "unresolved"]
    unreviewed = [r for r in s.records if r.review_status == ReviewStatus.UNREVIEWED]
    text = "\n".join([
        f"HANDOFF SUMMARY - {s.interview_id} ({s.case_id}), interviewee {s.interviewee}",
        f"Transcript status: {s.transcript_status.value}",
        f"Sections completed: {', '.join(x for x in s.completed_sections) or 'none'}; "
        f"current: {s.current_section or '-'}; session {s.status.value}",
        f"Facts recorded: {len(s.facts)} ({', '.join(f'{k} {v}' for k, v in sorted(by_src.items())) or 'none'})",
        f"Hedged or unsure statements: {sum(1 for f in s.facts if f.certainty != Certainty.STATED)}",
        f"Unresolved discrepancies: {len(unresolved)}",
        f"Records mentioned or uploaded: {len(s.records)} ({len(unreviewed)} not yet reviewed - "
        f"potential supporting records only)",
        f"Requested outcomes (kept separate): {len(s.outcomes)}",
        "Downstream stages must preserve provenance and uncertainty and must not rewrite "
        "uncertain statements into definite allegations.",
    ])
    return assert_no_advocacy(text, s.mode)


def all_outputs(s: "InterviewSession") -> dict:
    return {
        "interview_record": interview_record(s),
        "fact_table": fact_table(s),
        "timeline": timeline(s),
        "evidence_followup": evidence_followup(s),
        "open_questions": open_questions(s),
        "requested_outcomes": requested_outcomes(s),
        "handoff_summary": handoff_summary(s),
    }
