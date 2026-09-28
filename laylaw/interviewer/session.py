"""The Laylaw Interviewer session engine.

Implements the canonical spec's INTERVIEW stage:
  orientation -> free account per section -> one-at-a-time clarification ->
  record hook -> end-of-section check -> (next section) -> final check.

The engine records; it never supplies facts, upgrades certainty, picks between
conflicting recollections, or produces advocacy. Downstream stages (ORGANIZE,
VERIFY, ANALYZE, DRAFT) live elsewhere and are refused from here.
"""
from __future__ import annotations

import datetime as _dt
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from . import classify
from .guard import ModeViolation, assert_no_advocacy
from .models import (
    Certainty, DateValue, DatePrecision, Discrepancy, DocumentFinding, EventKind, Fact, Mode,
    Provenance, ProvenanceType, RequestedOutcome, ReviewStatus, SessionStatus,
    SourceOfKnowledge, SupportingRecord, TranscriptStatus, Turn, VerificationStatus, to_jsonable,
)

ORIENTATION_TEXT = (
    "I'll ask about what you remember. It's completely okay to say you don't know, "
    "don't remember, or aren't sure. I won't fill in missing details for you."
)
END_OF_SECTION_QUESTIONS = [
    "Did I get anything wrong?",
    "Did I make anything sound more certain than you intended?",
    "Is there anything important I missed?",
]
FINAL_CHECK_QUESTIONS = [
    "Is there anything important that I didn't ask about?",
    "Is there anything we discussed that you want to correct?",
    "Did I make anything sound more definite than you remember it?",
    "What should we follow up on next?",
]
RECORD_HOOK_QUESTION = "Is there anything that might help document or date this?"
SAFETY_QUESTION = (
    "Before we go on: are you safe right now? If you or anyone else is in immediate danger, "
    "please call 911 (or your local emergency number) now. Tell me when you're ready, and "
    "we can come back to this later."
)
CERTAINTY_QUESTION = "Which part are you certain about, and which part are you unsure about?"

_CERTAINTY_RANK = {Certainty.UNSURE: 0, Certainty.HEDGED: 1, Certainty.STATED: 2}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _slug(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-") or "UNKNOWN"


class AdultInterviewOnly(ValueError):
    """The interviewer interviews adults only; never a child forensic interview."""


@dataclass
class PendingQuestion:
    kind: str                       # free_account | clarify | record_hook | recap | final | safety
    text: str
    fact_id: Optional[str] = None
    field: Optional[str] = None


@dataclass
class InterviewSession:
    interview_id: str
    case_id: str
    client_id: str
    interviewee: str
    interviewer: str
    purpose: str
    sections: list[str]
    date_started: str = field(default_factory=_now)
    last_updated: str = field(default_factory=_now)
    transcript_status: TranscriptStatus = TranscriptStatus.UNKNOWN
    mode: Mode = Mode.INTERVIEW
    status: SessionStatus = SessionStatus.ACTIVE
    is_continuation: bool = False
    path_name: str = "general"
    current_section: Optional[str] = None
    completed_sections: list[str] = field(default_factory=list)
    queue: list[PendingQuestion] = field(default_factory=list)
    pending: Optional[PendingQuestion] = None
    last_question_answered: Optional[str] = None
    turns: list[Turn] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    outcomes: list[RequestedOutcome] = field(default_factory=list)
    records: list[SupportingRecord] = field(default_factory=list)
    findings: list[DocumentFinding] = field(default_factory=list)
    discrepancies: list[Discrepancy] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=list)
    oriented: bool = False
    final_check_started: bool = False
    workspace: Any = None  # not serialized

    # ------------------------------------------------------------------ setup
    @classmethod
    def start(cls, workspace, *, case_id: str, interviewee: str, interviewer: str,
              purpose: str, sections: list[str], interviewee_is_adult: bool,
              transcript_status: TranscriptStatus = TranscriptStatus.STRUCTURED_NOTES,
              path_name: str = "general") -> "InterviewSession":
        if not interviewee_is_adult:
            raise AdultInterviewOnly(
                "Laylaw Interviewer interviews adults only and does not conduct forensic "
                "interviews of children. Record an adult's recollection of what a child said instead.")
        s = cls(interview_id="INT-" + uuid.uuid4().hex[:10], case_id=case_id,
                client_id=workspace.client_id, interviewee=interviewee, interviewer=interviewer,
                purpose=purpose, sections=list(sections), transcript_status=transcript_status,
                path_name=path_name)
        s.workspace = workspace
        s.save()
        return s

    # ----------------------------------------------------------- persistence
    def save(self) -> None:
        self.last_updated = _now()
        if self.workspace is not None:
            self.workspace.save_session(self)

    def to_dict(self) -> dict:
        d = {k: to_jsonable(getattr(self, k)) for k in self.__dataclass_fields__ if k != "workspace"}
        d["schema"] = "laylaw.interviewer.session/1"
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "InterviewSession":
        def dv(x):
            return None if x is None else DateValue(**{**x, "precision": DatePrecision(x["precision"])})

        def prov(x):
            return Provenance(**{**x, "type": ProvenanceType(x["type"])})

        def fact(x):
            return Fact(**{**x, "source": SourceOfKnowledge(x["source"]),
                           "certainty": Certainty(x["certainty"]), "provenance": prov(x["provenance"]),
                           "date": dv(x["date"]), "kind": EventKind(x["kind"]),
                           "verification": VerificationStatus(x["verification"])})

        def rec(x):
            return SupportingRecord(**{**x, "provenance_type": ProvenanceType(x["provenance_type"]),
                                       "review_status": ReviewStatus(x["review_status"])})

        pq = lambda x: None if x is None else PendingQuestion(**x)  # noqa: E731
        s = cls(
            interview_id=d["interview_id"], case_id=d["case_id"], client_id=d["client_id"],
            interviewee=d["interviewee"], interviewer=d["interviewer"], purpose=d["purpose"],
            sections=d["sections"], date_started=d["date_started"], last_updated=d["last_updated"],
            transcript_status=TranscriptStatus(d["transcript_status"]), mode=Mode(d["mode"]),
            status=SessionStatus(d["status"]), is_continuation=d["is_continuation"],
            path_name=d["path_name"], current_section=d["current_section"],
            completed_sections=d["completed_sections"], queue=[pq(q) for q in d["queue"]],
            pending=pq(d["pending"]), last_question_answered=d["last_question_answered"],
            turns=[Turn(**t) for t in d["turns"]], facts=[fact(f) for f in d["facts"]],
            outcomes=[RequestedOutcome(**{**o, "provenance": prov(o["provenance"])}) for o in d["outcomes"]],
            records=[rec(r) for r in d["records"]],
            findings=[DocumentFinding(**{**f, "provenance": prov(f["provenance"]), "date": dv(f["date"])})
                      for f in d["findings"]],
            discrepancies=[Discrepancy(**x) for x in d["discrepancies"]],
            open_questions=d["open_questions"], corrections=d["corrections"],
            safety_notes=d["safety_notes"], oriented=d["oriented"],
            final_check_started=d["final_check_started"],
        )
        return s

    # ----------------------------------------------------------- interrupt/resume
    def interrupt(self) -> None:
        """Save an interrupted interview so it can be resumed exactly here."""
        if self.status == SessionStatus.ACTIVE:
            self.status = SessionStatus.PAUSED
        self.save()

    def resume_prompt(self) -> str:
        topic = self.current_section or (self.sections[0] if self.sections else "the beginning")
        last = self._last_covered_summary()
        return self._emit(f"I have us stopped at {topic}. The last thing we covered was {last}. "
                          f"Shall we continue there?")

    def resume(self) -> str:
        self.is_continuation = True
        if self.status == SessionStatus.PAUSED:
            self.status = SessionStatus.ACTIVE
        self.save()
        return self.resume_prompt()

    def _last_covered_summary(self) -> str:
        if not self.facts:
            return "the introduction"
        f = self.facts[-1]
        return f"{f.topic}: the account recorded as fact {f.id}"

    # ----------------------------------------------------------- provenance
    def _provenance(self, turn_index: Optional[int]) -> Provenance:
        day = self.date_started[:10]
        return Provenance(ProvenanceType.INTERVIEW, f"INTERVIEW:{_slug(self.interviewee)}:{day}",
                          session_id=self.interview_id, turn_index=turn_index)

    # ----------------------------------------------------------- questioning
    def _emit(self, text: str) -> str:
        return assert_no_advocacy(text, self.mode)

    def next_question(self) -> Optional[str]:
        """Return exactly one question (or None when the interview is done)."""
        if self.status == SessionStatus.PAUSED_FOR_SAFETY:
            self.pending = PendingQuestion("safety", SAFETY_QUESTION)
            return self._emit(SAFETY_QUESTION)
        if self.status == SessionStatus.CLOSED:
            return None
        if self.pending is None:
            self.pending = self._advance()
        self.save()
        if self.pending is None:
            return None
        text = self.pending.text
        if self.pending.kind == "recap" and self.pending.field == "0":
            text = self.section_recap(with_questions=False) + "\n\n" + text
        if self.pending.kind == "free_account" and not self.oriented:
            self.oriented = True
            text = ORIENTATION_TEXT + "\n\n" + text
        return self._emit(text)

    def _advance(self) -> Optional[PendingQuestion]:
        if self.queue:
            return self.queue.pop(0)
        if self.current_section and self.current_section in self.sections \
                and self.current_section not in self.completed_sections:
            self.completed_sections.append(self.current_section)
        remaining = [s for s in self.sections if s not in self.completed_sections]
        if remaining:
            self.current_section = remaining[0]
            return PendingQuestion("free_account", self.free_account_prompt(self.current_section))
        if not self.final_check_started:
            self.final_check_started = True
            self.current_section = "Final check"
            self.queue = [PendingQuestion("final", q) for q in FINAL_CHECK_QUESTIONS[1:]]
            return PendingQuestion("final", FINAL_CHECK_QUESTIONS[0])
        self.status = SessionStatus.CLOSED
        return None

    @staticmethod
    def is_request_section(section: Optional[str]) -> bool:
        return bool(section) and bool(re.search(r"(?i)request|going forward|would like", section))

    @staticmethod
    def free_account_prompt(section: str) -> str:
        if InterviewSession.is_request_section(section):
            return "What would you like to happen going forward?"
        if re.search(r"(?i)routine", section):
            return f"Tell me what normally happens with {section.lower()}."
        return f"Tell me about {section.lower()}, from the beginning."

    # ----------------------------------------------------------- answering
    def answer(self, text: str, **tags) -> None:
        """Record the interviewee's answer to the pending question."""
        q = self.pending
        turn = Turn(len(self.turns), self.current_section or "", q.text if q else None, text)
        self.turns.append(turn)
        self.last_question_answered = q.text if q else None
        self.pending = None

        if classify.detect_present_safety_issue(text):
            self.status = SessionStatus.PAUSED_FOR_SAFETY
            self.safety_notes.append(f"turn {turn.index}: possible present danger described; "
                                     f"ordinary interviewing paused")
            if q:
                self.queue.insert(0, q)  # come back to the same question afterwards
            self.save()
            return

        kind = q.kind if q else "free_account"
        if kind == "safety":
            self.safety_notes.append(f"turn {turn.index}: safety check answered")
            if not tags.get("keep_paused"):
                self.status = SessionStatus.ACTIVE
        elif kind == "free_account":
            self._record_answer_as_fact_or_request(text, turn.index, **tags)
        elif kind == "clarify":
            self._apply_clarification(q, text, turn.index, **tags)
        elif kind == "record_hook":
            self._apply_record_hook(q, text)
        elif kind == "recap":
            self._apply_recap_answer(text, turn.index)
        elif kind == "final":
            if text.strip() and not re.fullmatch(r"(?i)\s*(no|nope|nothing|no,? that'?s it\.?)\s*", text):
                self.open_questions.append(f"Final check - {q.text} -> {text}")
        self.save()

    def _record_answer_as_fact_or_request(self, text: str, turn_index: int, **tags) -> None:
        if self.is_request_section(self.current_section) and not tags.get("source"):
            self.record_request(text, turn_index=turn_index)
            return
        if re.search(r"(?i)routine", self.current_section or "") and "kind" not in tags:
            tags["kind"] = EventKind.ROUTINE
        if classify.is_request(text) and not tags.get("source"):
            self.record_request(text, turn_index=turn_index)
            return
        fact = self.record_fact(text, turn_index=turn_index, topic=self.current_section or "general", **tags)
        self._queue_clarifications(fact)

    def _queue_clarifications(self, fact: Fact) -> None:
        """One question at a time, open-ended, never suggesting an answer."""
        qs: list[PendingQuestion] = []
        if fact.source == SourceOfKnowledge.REQUEST:
            return
        if fact.date is None:
            qs.append(PendingQuestion("clarify", "About when was this?", fact.id, "date"))
        if not fact.people_present:
            qs.append(PendingQuestion("clarify", "Who else was there?", fact.id, "people_present"))
        if not fact.location and fact.kind != EventKind.ROUTINE:
            qs.append(PendingQuestion("clarify", "Where did this happen?", fact.id, "location"))
        if fact.source in (SourceOfKnowledge.PERSONAL_OBSERVATION, SourceOfKnowledge.UNCERTAIN) \
                and not fact.told_by:
            qs.append(PendingQuestion("clarify", "How do you know that?", fact.id, "source"))
        if fact.certainty == Certainty.HEDGED:
            qs.append(PendingQuestion("clarify", CERTAINTY_QUESTION, fact.id, "certainty"))
        if fact.kind == EventKind.ROUTINE:
            qs.append(PendingQuestion("clarify", "Was there a particular time that was different?",
                                      fact.id, "next"))
        else:
            qs.append(PendingQuestion("clarify", "What happened next?", fact.id, "next"))
        qs.append(PendingQuestion("record_hook", RECORD_HOOK_QUESTION, fact.id))
        # End-of-section check comes after this fact's clarifications. The recap
        # text itself is built when asked, so it reflects everything recorded.
        self.queue = [q for q in self.queue if q.kind != "recap"] + qs + [
            PendingQuestion("recap", q_text, None, field=str(i))
            for i, q_text in enumerate(END_OF_SECTION_QUESTIONS)]

    def _apply_clarification(self, q: PendingQuestion, text: str, turn_index: int, **tags) -> None:
        fact = self.get_fact(q.fact_id)
        if q.field == "date":
            self.set_fact_date(fact.id, text)
        elif q.field == "people_present":
            # Keep the interviewee's own words; never expand or guess names.
            if re.search(r"(?i)\bi don'?t (?:know|remember)\b|\bnot sure\b", text):
                fact.open_questions.append(f"People present: interviewee said \"{text}\"")
            elif re.fullmatch(r"(?i)\s*(?:no one|nobody|no one else|nobody else)\.?\s*", text):
                fact.people_present.append("interviewee only (as stated)")
            else:
                cleaned = re.sub(r"(?i)^\s*just\s+", "", text.strip().rstrip("."))
                parts = [n.strip() for n in re.split(r",|\band\b", cleaned) if n.strip()]
                fact.people_present.extend("interviewee" if p.lower() in ("me", "i", "myself") else p
                                           for p in parts)
        elif q.field == "location":
            if _is_nothing_more(text):
                fact.open_questions.append(f"Location: interviewee said \"{text}\"")
            else:
                fact.location = text.strip()
        elif q.field == "source":
            src = tags.get("source") or classify.classify_source(text)
            self._set_source(fact, SourceOfKnowledge(src), basis_text=text)
        elif q.field == "certainty":
            fact.open_questions.append(f"Certainty clarification (interviewee's words): {text}")
        elif q.field == "next":
            if not _is_nothing_more(text):
                nxt = self.record_fact(text, turn_index=turn_index, topic=fact.topic,
                                       sequence_hint=f"after {fact.id}", **tags)
                self._queue_clarifications(nxt)

    def _apply_record_hook(self, q: PendingQuestion, text: str) -> None:
        if re.fullmatch(r"(?i)\s*(no|nope|nothing|not that i know of|i don'?t think so)\.?\s*", text):
            return
        rec = SupportingRecord(id="R-" + uuid.uuid4().hex[:10], client_id=self.client_id,
                               session_id=self.interview_id, label=f"Mentioned by interviewee: {text}",
                               provenance_type=ProvenanceType.DOCUMENT,
                               related_fact_ids=[q.fact_id] if q.fact_id else [])
        self.records.append(rec)
        if q.fact_id:
            f = self.get_fact(q.fact_id)
            f.possible_records.append(rec.id)
            if f.verification == VerificationStatus.INTERVIEW_ONLY:
                f.verification = VerificationStatus.DOCUMENT_LOCATED

    def _apply_recap_answer(self, text: str, turn_index: int) -> None:
        if re.fullmatch(r"(?i)\s*(no|nope|looks right|that'?s right|correct)\.?\s*", text):
            return
        self.corrections.append(f"turn {turn_index}: {text}")

    # ----------------------------------------------------------- direct recording API
    def record_fact(self, statement: str, *, topic: str, turn_index: Optional[int] = None,
                    date_text: Optional[str] = None, source: Optional[SourceOfKnowledge | str] = None,
                    told_by: Optional[str] = None, told_by_is_child: bool = False,
                    witnessed_underlying_event: bool = False, people_present: Optional[list[str]] = None,
                    location: Optional[str] = None, kind: EventKind = EventKind.UNSPECIFIED,
                    event_key: Optional[str] = None, exact_wording_remembered: bool = False,
                    sequence_hint: Optional[str] = None, correction_of: Optional[str] = None) -> Fact:
        if self.mode != Mode.INTERVIEW:
            raise ModeViolation("facts are recorded only in INTERVIEW mode")
        certainty, hedges = classify.classify_certainty(statement)
        detected = classify.classify_source(statement)
        if detected == SourceOfKnowledge.REQUEST and source is None:
            raise ValueError("this is a requested outcome; use record_request()")
        fact = Fact(id=f"F-{len(self.facts) + 1:03d}", topic=topic, statement=statement,
                    source=SourceOfKnowledge.UNKNOWN, certainty=certainty, hedges=hedges,
                    provenance=self._provenance(turn_index), location=location,
                    people_present=list(people_present or []), kind=kind, told_by=told_by,
                    told_by_is_child=told_by_is_child,
                    witnessed_underlying_event=witnessed_underlying_event,
                    exact_wording_remembered=exact_wording_remembered,
                    sequence_hint=sequence_hint, correction_of=correction_of)
        fact.event_key = event_key or f"{topic}:{fact.id}"
        self._set_source(fact, SourceOfKnowledge(source) if source else detected)
        self.facts.append(fact)
        if date_text is not None:
            self.set_fact_date(fact.id, date_text)
        self.save()
        return fact

    def _set_source(self, fact: Fact, src: SourceOfKnowledge, basis_text: str = "") -> None:
        """Assign source of knowledge, refusing to upgrade secondhand reports."""
        if src == SourceOfKnowledge.REQUEST:
            raise ValueError("a requested outcome can never be a historical fact")
        heard_it = fact.told_by is not None or fact.source == SourceOfKnowledge.SECONDHAND
        if heard_it and src == SourceOfKnowledge.PERSONAL_OBSERVATION and not fact.witnessed_underlying_event:
            src = SourceOfKnowledge.SECONDHAND
        if fact.told_by_is_child and not fact.witnessed_underlying_event:
            src = SourceOfKnowledge.SECONDHAND
        fact.source = src
        if basis_text:
            fact.open_questions.append(f"Basis of knowledge (interviewee's words): {basis_text}")

    def set_fact_date(self, fact_id: str, date_text: str) -> DateValue:
        fact = self.get_fact(fact_id)
        dv = classify.parse_date(date_text)
        if fact.certainty != Certainty.STATED and dv.precision == DatePrecision.EXACT:
            # a hedged statement can't carry an exact date the speaker didn't commit to
            dv.precision, dv.qualifier = DatePrecision.APPROXIMATE, "hedged statement"
        if fact.date is not None and not _dates_compatible(fact.date, dv):
            # A second, different recollection for the same fact: keep both.
            dup = self.record_fact(fact.statement, topic=fact.topic, source=fact.source,
                                   told_by=fact.told_by, told_by_is_child=fact.told_by_is_child,
                                   witnessed_underlying_event=fact.witnessed_underlying_event,
                                   event_key=fact.event_key,
                                   sequence_hint=f"second date recollection for the event in {fact.id}")
            dup.date = dv
            self._check_date_conflicts(dup)
            self.save()
            return dv
        fact.date = dv
        self._check_date_conflicts(fact)
        self.save()
        return dv

    def _check_date_conflicts(self, fact: Fact) -> None:
        for other in self.facts:
            if other.id == fact.id or other.event_key != fact.event_key or other.date is None:
                continue
            if _dates_compatible(other.date, fact.date):
                continue
            ids = sorted({other.id, fact.id})
            if any(sorted(d.fact_ids) == ids for d in self.discrepancies):
                continue
            self.discrepancies.append(Discrepancy(
                id=f"D-{len(self.discrepancies) + 1:03d}", topic=fact.topic, fact_ids=ids, field="date",
                description=(f'Recollection A ({other.id}): "{other.date.original_text}"; '
                             f'Recollection B ({fact.id}): "{fact.date.original_text}"')))
            for f in (other, fact):
                f.verification = VerificationStatus.DISPUTED if f.verification in (
                    VerificationStatus.INTERVIEW_ONLY, VerificationStatus.DISPUTED) else f.verification
            self.queue.insert(0, PendingQuestion(
                "clarify",
                f'Earlier I wrote down "{other.date.original_text}". Just now you said '
                f'"{fact.date.original_text}". Which is closer to what you remember now?',
                fact.id, "discrepancy"))

    def resolve_discrepancy(self, discrepancy_id: str, interviewee_explanation: str) -> Discrepancy:
        """Only the interviewee's own explanation can resolve a discrepancy, and
        both original recollections are kept either way."""
        d = next(x for x in self.discrepancies if x.id == discrepancy_id)
        if re.search(r"(?i)\b(?:don'?t know|not sure|can'?t say|either|both)\b", interviewee_explanation):
            d.resolution_note = f"Interviewee could not resolve: {interviewee_explanation}"
            d.status = "unresolved"
        else:
            d.resolution_note = f"Interviewee's explanation: {interviewee_explanation}"
            d.status = "clarified by interviewee"
        self.save()
        return d

    def record_request(self, text: str, *, turn_index: Optional[int] = None) -> RequestedOutcome:
        o = RequestedOutcome(id=f"RQ-{len(self.outcomes) + 1:03d}", text=text,
                             provenance=self._provenance(turn_index))
        self.outcomes.append(o)
        self.save()
        return o

    def get_fact(self, fact_id: str) -> Fact:
        return next(f for f in self.facts if f.id == fact_id)

    # ----------------------------------------------------------- records & documents
    def add_upload(self, filename: str, data: bytes, *, label: Optional[str] = None,
                   related_fact_ids: Optional[list[str]] = None,
                   provenance_type: ProvenanceType = ProvenanceType.DOCUMENT) -> SupportingRecord:
        """Uploads can arrive at any point in the interview; each stays attached to
        this client and this session."""
        rec = self.workspace.store_upload(self.interview_id, filename, data, label=label,
                                          provenance_type=provenance_type)
        rec.related_fact_ids = list(related_fact_ids or [])
        self.records.append(rec)
        for fid in rec.related_fact_ids:
            f = self.get_fact(fid)
            f.possible_records.append(rec.id)
            if f.verification == VerificationStatus.INTERVIEW_ONLY:
                f.verification = VerificationStatus.DOCUMENT_LOCATED
        self.save()
        return rec

    def mark_record_reviewed(self, record_id: str) -> SupportingRecord:
        rec = next(r for r in self.records if r.id == record_id)
        rec.review_status = ReviewStatus.REVIEWED
        for fid in rec.related_fact_ids:
            f = self.get_fact(fid)
            if f.verification in (VerificationStatus.INTERVIEW_ONLY, VerificationStatus.DOCUMENT_LOCATED):
                f.verification = VerificationStatus.DOCUMENT_REVIEWED
        self.save()
        return rec

    def add_document_finding(self, fact_id: str, record_id: str, content: str, *,
                             date_text: Optional[str] = None, page: Optional[str] = None) -> DocumentFinding:
        """Record what a reviewed document says, beside the recollection.
        The fact's statement and date are never touched."""
        rec = next(r for r in self.records if r.id == record_id)
        if rec.review_status != ReviewStatus.REVIEWED:
            raise ValueError("review the record before recording what it says")
        fact = self.get_fact(fact_id)
        dv = classify.parse_date(date_text) if date_text else None
        consistency, note = "not assessed", None
        if dv is not None and fact.date is not None:
            if _dates_compatible(fact.date, dv):
                consistency = "consistent"
            else:
                consistency = "different"
                note = (f'Recollection: "{fact.date.original_text}"; '
                        f'document: "{dv.original_text}"')
        label = f"DOCUMENT:{_slug(rec.label)}" + (f":PAGE-{page}" if page else "")
        finding = DocumentFinding(id=f"DF-{len(self.findings) + 1:03d}", fact_id=fact_id,
                                  record_id=record_id, content=content,
                                  provenance=Provenance(ProvenanceType.DOCUMENT, label, record_id=record_id),
                                  date=dv, consistency=consistency, difference_note=note)
        self.findings.append(finding)
        if record_id not in fact.possible_records:
            fact.possible_records.append(record_id)
        if consistency == "consistent":
            fact.verification = VerificationStatus.CONSISTENT_WITH_DOCUMENT
        elif consistency == "different":
            fact.verification = VerificationStatus.INCONSISTENT_WITH_DOCUMENT
        else:
            fact.verification = VerificationStatus.DOCUMENT_REVIEWED
        self.save()
        return finding

    # ----------------------------------------------------------- recaps
    def section_recap(self, section: Optional[str] = None, with_questions: bool = True) -> str:
        from .outputs import neutral_fact_line
        section = section or self.current_section
        lines = [neutral_fact_line(f, self) for f in self.facts if f.topic == section]
        body = "\n".join(f"- {ln}" for ln in lines) or "- (nothing recorded yet)"
        text = f"Here's what I have for {section.lower()}:\n{body}"
        if with_questions:
            text += "\n\n" + "\n".join(END_OF_SECTION_QUESTIONS)
        return self._emit(text)

    # ----------------------------------------------------------- transcript status
    def mark_reconstructed(self) -> None:
        """Notes rebuilt after the fact. Never called a transcript afterwards."""
        self.transcript_status = TranscriptStatus.RECONSTRUCTED
        self.save()

    # ----------------------------------------------------------- later stages
    def request_stage_output(self, stage: Mode) -> None:
        if self.mode == Mode.INTERVIEW and stage != Mode.INTERVIEW:
            raise ModeViolation(f"{stage.value} is a separate Laylaw stage; INTERVIEW does not produce it")


_NOTHING_MORE = re.compile(
    r"(?i)\s*(?:no|nope|none|nothing(?: else)?(?: happened)?|that'?s (?:it|all)|not really|"
    r"i don'?t (?:know|remember)|n/?a)[.!]?\s*")


def _is_nothing_more(text: str) -> bool:
    return not text.strip() or bool(_NOTHING_MORE.fullmatch(text))


def _dates_compatible(a: DateValue, b: DateValue) -> bool:
    """True unless both recollections pin a component that differs.
    Unknown/relative values are never treated as conflicting (nothing to compare)."""
    if DatePrecision.UNKNOWN in (a.precision, b.precision) or DatePrecision.RELATIVE in (a.precision, b.precision):
        return True
    for part in ("year", "month", "day"):
        x, y = getattr(a, part), getattr(b, part)
        if x is not None and y is not None and x != y:
            return False
    return True
