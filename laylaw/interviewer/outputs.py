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
    Certainty, DatePrecision, Fact, FactStatus, ReviewStatus, SourceOfKnowledge, SupportingSourceType,
    TranscriptStatus,
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


def version_note(f: Fact) -> str | None:
    if f.status == FactStatus.SUPERSEDED:
        return f"SUPERSEDED by interviewee correction {f.superseded_by} (original kept)"
    if f.correction_of:
        return f"CORRECTION of {f.correction_of} (interviewee's words)"
    return None


def neutral_fact_line(f: Fact, s: "InterviewSession") -> str:
    parts = [f"[{SOURCE_LABEL[f.source]}]", statement_text(f, s), f"Date: {date_text(f)}"]
    if version_note(f):
        parts.insert(0, f"[{version_note(f)}]")
    if f.certainty != Certainty.STATED:
        parts.append(f"Interviewee uncertainty preserved ({', '.join(f.hedges) or f.certainty.value})")
    if f.told_by:
        who = f"{f.told_by} (child)" if f.told_by_is_child else f.told_by
        parts.append(f"Reported to interviewee by: {who}")
    return " | ".join(parts)


def _guard(obj, s: "InterviewSession"):
    """Check every generated string for advocacy, value by value. The
    interviewee's and documents' own wording is preserved verbatim (attributed),
    so recording an allegation never breaks an output -- but anything the
    renderer itself writes is still refused if it argues, strategizes, or judges."""
    attributed = s.attributed_texts()

    def walk(o):
        if isinstance(o, str):
            assert_no_advocacy(o, s.mode, attributed)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
    walk(obj)
    return obj


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
    if s.intake:
        lines += ["INTAKE (administrative; not historical findings)"]
        for i in s.intake:
            lines.append(f"- {i.key}: {i.answer or '(' + i.status + ')'}")
        lines.append("")
    for f in s.facts:
        src = f" [from answer {f.raw_answer_id}]" if f.raw_answer_id else ""
        ctx = f" [answering: {f.question_context}]" if f.question_context else ""
        lines.append(f"- {f.id} ({f.topic}) {neutral_fact_line(f, s)}{src}{ctx}")
    if s.raw_answers:
        lines += ["", "ANSWERS AS ENTERED (the interviewee's own text; not a transcript)"]
        lines += [f"- {r.id} (turn {r.turn_index}, {r.section}): {r.text}" for r in s.raw_answers]
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
        lines += ["", "CORRECTIONS BY INTERVIEWEE (originals kept)"]
        for c in s.corrections:
            if c.status == "applied":
                lines.append(f"- {c.id} via {c.via}: {c.target_fact_id} -> {c.new_fact_id} | "
                             f"interviewee's words: {c.raw_text}")
            else:
                lines.append(f"- {c.id} via {c.via}: not yet matched to an item | interviewee's words: {c.raw_text}")
    pending = [c for c in s.candidates if c.status == "candidate"]
    if s.candidates:
        lines += ["", "DOCUMENT-DERIVED CANDIDATES (not part of the recollection unless confirmed)"]
        for c in s.candidates:
            lines.append(f"- {c.id} [{c.provenance.label}] {c.field}: {c.value_text} | status: {c.status}"
                         + (f" | client: {c.client_response}" if c.client_response else "")
                         + (f" | new version {c.resulting_fact_id}" if c.resulting_fact_id else ""))
    del pending
    if s.safety_notes:
        lines += ["", "SAFETY PAUSES"] + [f"- {n}" for n in s.safety_notes]
    return _guard("\n".join(lines), s)


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
            "VERSION": version_note(f) or "current",
            "NOTES": notes + [f"{a['field']} also recalled as: {a['value']}" for a in f.alternate_recollections],
            "PROVENANCE": f.provenance.label + (f" / answer {f.raw_answer_id} chars {f.span[0]}-{f.span[1]}"
                                                if f.raw_answer_id and f.span else ""),
        })
    return _guard(rows, s)


# 3 ---------------------------------------------------------------------------
def timeline(s: "InterviewSession") -> list[dict]:
    """Historical facts only. Requested outcomes live in a separate list and are
    never placed here. Undated facts are listed after dated ones, not guessed."""
    unresolved = _unresolved_ids(s)
    historical = [f for f in s.facts if f.source != SourceOfKnowledge.REQUEST]

    def root(f: Fact) -> Fact:
        while f.correction_of:
            f = s.get_fact(f.correction_of)
        return f

    def key(f: Fact):
        r = root(f)
        dated = r.date is not None and r.date.year is not None
        return (0 if dated else 1, r.date.sort_key() if dated else (0, 0, 0), s.facts.index(r), s.facts.index(f))

    events = []
    for f in sorted(historical, key=key):
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
            "VERSION": version_note(f) or "current",
            "POSSIBLE SUPPORTING RECORDS": [
                next(r for r in s.records if r.id == rid).describe() for rid in f.possible_records],
            "UNRESOLVED QUESTIONS": f.open_questions + ([UNRESOLVED_DATE] if f.id in unresolved else [])
            + [f"[UNRESOLVED {d.field.upper().replace('_', ' ')} DISCREPANCY] {d.description}"
               for d in s.discrepancies if f.id in d.fact_ids and d.status == "unresolved" and d.field != "date"],
        })
    return _guard(events, s)


# 4 ---------------------------------------------------------------------------
def evidence_followup(s: "InterviewSession") -> list[str]:
    out = []
    for r in s.records:
        facts = ", ".join(r.related_fact_ids) or "no specific fact yet"
        if r.source_type == SupportingSourceType.WITNESS:
            state = "possible witness; may help clarify" if r.review_status == ReviewStatus.UNREVIEWED \
                else "contacted"
        else:
            state = "may help clarify" if r.review_status == ReviewStatus.UNREVIEWED else "reviewed; see document check"
        out.append(f"[{r.source_type.value.upper()}] {r.describe()} - {state} ({facts}). "
                   f"Attached to client {r.client_id}, session {r.session_id}.")
    for c in s.candidates:
        if c.status == "candidate":
            out.append(f"[DOCUMENT-DERIVED CANDIDATE] {c.id}: {c.field} '{c.value_text}' from {c.provenance.label} "
                       f"- waiting for the client to confirm or correct.")
    for f in s.facts:
        if f.source == SourceOfKnowledge.SECONDHAND and f.told_by:
            out.append(f"Possible witness: {f.told_by} (source of secondhand information in {f.id}). "
                       f"Do not re-question a child; note only."
                       if f.told_by_is_child else
                       f"Possible witness: {f.told_by} (source of secondhand information in {f.id}).")
    return _guard(out, s)


# 5 ---------------------------------------------------------------------------
def open_questions(s: "InterviewSession") -> list[str]:
    out = list(s.open_questions)
    for f in s.facts:
        if f.status != FactStatus.CURRENT or f.question_context:
            continue
        if f.date is None or f.date.precision == DatePrecision.UNKNOWN:
            out.append(f"{f.id}: when this happened (not yet known)")
        if not f.people_present:
            out.append(f"{f.id}: who was present (not yet stated)")
    for d in s.discrepancies:
        if d.status == "unresolved":
            out.append(f"{d.id}: {UNRESOLVED_DATE} {d.description}")
    for c in s.candidates:
        if c.status == "candidate":
            out.append(f"{c.id}: ask the client whether the document's {c.field} ('{c.value_text}') "
                       f"matches what they remember")
    for q in ([s.pending] if s.pending else []) + s.queue:
        if q.kind == "clarify":
            out.append(f"Not yet asked: {q.text} ({q.fact_id})")
    return _guard(out, s)


# 6 ---------------------------------------------------------------------------
def requested_outcomes(s: "InterviewSession") -> list[dict]:
    return _guard([{"ID": o.id, "REQUEST": o.text, "PROVENANCE": o.provenance.label,
                    "NOTE": "Requested future outcome - not a historical fact."} for o in s.outcomes], s)


# 7 ---------------------------------------------------------------------------
def handoff_summary(s: "InterviewSession") -> str:
    by_src: dict[str, int] = {}
    for f in s.facts:
        if f.status != FactStatus.CURRENT:
            continue
        by_src[SOURCE_LABEL[f.source]] = by_src.get(SOURCE_LABEL[f.source], 0) + 1
    unresolved = [d for d in s.discrepancies if d.status == "unresolved"]
    unreviewed = [r for r in s.records if r.review_status == ReviewStatus.UNREVIEWED]
    text = "\n".join([
        f"HANDOFF SUMMARY - {s.interview_id} ({s.case_id}), interviewee {s.interviewee}",
        f"Transcript status: {s.transcript_status.value}",
        f"Sections completed: {', '.join(x for x in s.completed_sections) or 'none'}; "
        f"current: {s.current_section or '-'}; session {s.status.value}",
        f"Current facts: {sum(by_src.values())}, superseded by correction: "
        f"{sum(1 for f in s.facts if f.status != FactStatus.CURRENT)} ({', '.join(f'{k} {v}' for k, v in sorted(by_src.items())) or 'none'})",
        f"Hedged or unsure statements: {sum(1 for f in s.facts if f.certainty != Certainty.STATED)}",
        f"Unresolved discrepancies: {len(unresolved)}",
        f"Records mentioned or uploaded: {len(s.records)} ({len(unreviewed)} not yet reviewed - "
        f"potential supporting records only)",
        f"Requested outcomes (kept separate): {len(s.outcomes)}",
        f"Interviewee corrections: {sum(1 for c in s.corrections if c.status == 'applied')} applied, "
        f"{sum(1 for c in s.corrections if c.status != 'applied')} awaiting an item (all originals kept)",
        f"Skipped or 'not sure' answers: {sum(1 for t in s.turns if t.control in ('skip', 'not_sure'))}",
        f"Document-derived candidates awaiting client confirmation: "
        f"{sum(1 for c in s.candidates if c.status == 'candidate')}",
        f"Intake items (administrative): {', '.join(i.key for i in s.intake) or 'none'}",
        "Downstream stages must preserve provenance and uncertainty and must not rewrite "
        "uncertain statements into definite allegations.",
    ])
    return _guard(text, s)


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
