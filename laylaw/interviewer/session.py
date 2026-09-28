"""The Laylaw Interviewer session engine.

Implements the canonical spec's INTERVIEW stage:
  [preflight intake] -> orientation -> free account per section -> one-at-a-time
  clarification -> record hook -> end-of-section check -> (next section) -> final check.

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
    SUPPORTING_TO_PROVENANCE, Certainty, Correction, DateValue, DatePrecision, Discrepancy,
    DocumentCandidate, DocumentFinding, EventKind, Fact, FactStatus, IntakeItem, Mode, Provenance,
    ProvenanceType, RawAnswer, RequestedOutcome, ReviewStatus, SessionStatus, SourceOfKnowledge,
    SupportingRecord, SupportingSourceType, TranscriptStatus, Turn, VerificationStatus, to_jsonable,
)
from .paths import PATHS, PREFLIGHT_QUESTIONS, spec_for, validate_sections

ORIENTATION_TEXT = (
    "I'll ask about what you remember. It's completely okay to say you don't know, "
    "don't remember, or aren't sure. I won't fill in missing details for you. "
    "You can also say \"skip\", \"not sure\", or \"save and finish later\" at any point."
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
SAVED_FOR_LATER = "Saved. When you come back, we'll pick up at the same question."


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _slug(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-") or "UNKNOWN"


def _norm(text: Optional[str]) -> str:
    t = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    t = re.sub(r"\b(?:the|a|an|at|in|on|by)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


class AdultInterviewOnly(ValueError):
    """The interviewer interviews adults only; never a child forensic interview."""


class ProvenanceError(ValueError):
    """Raised when text that is not the interviewee's own words is offered as their statement."""


@dataclass
class PendingQuestion:
    # preflight | free_account | clarify | procedural | record_hook | recap | final |
    # check_followup | correction_target | safety
    kind: str
    text: str
    fact_id: Optional[str] = None
    field: Optional[str] = None
    ref: Optional[str] = None   # exact item this question is about (e.g. a discrepancy id); saved with it


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
    raw_answers: list[RawAnswer] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    outcomes: list[RequestedOutcome] = field(default_factory=list)
    records: list[SupportingRecord] = field(default_factory=list)
    findings: list[DocumentFinding] = field(default_factory=list)
    candidates: list[DocumentCandidate] = field(default_factory=list)
    discrepancies: list[Discrepancy] = field(default_factory=list)
    corrections: list[Correction] = field(default_factory=list)
    intake: list[IntakeItem] = field(default_factory=list)
    sequence_links: list[dict] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=list)
    oriented: bool = False
    final_check_started: bool = False
    workspace_confirmed: Optional[bool] = None   # None = not asked; False = blocked until confirmed
    workspace: Any = None  # not serialized

    # ------------------------------------------------------------------ setup
    @classmethod
    def start(cls, workspace, *, case_id: str, interviewee: str, interviewer: str,
              purpose: str, sections: list[str], interviewee_is_adult: bool,
              transcript_status: TranscriptStatus = TranscriptStatus.STRUCTURED_NOTES,
              path_name: str = "general", preflight: Optional[list[str]] = None) -> "InterviewSession":
        if not interviewee_is_adult:
            raise AdultInterviewOnly(
                "Laylaw Interviewer interviews adults only and does not conduct forensic "
                "interviews of children. Record an adult's recollection of what a child said instead.")
        s = cls(interview_id="INT-" + uuid.uuid4().hex[:10], case_id=case_id,
                client_id=workspace.client_id, interviewee=interviewee, interviewer=interviewer,
                purpose=purpose, sections=list(sections), transcript_status=transcript_status,
                path_name=path_name)
        s.workspace = workspace
        if preflight:
            s.current_section = "Intake"
            s.queue = [PendingQuestion("preflight", PREFLIGHT_QUESTIONS[k].format(
                interviewee=interviewee, case_id=case_id), field=k) for k in preflight]
        s.save()
        return s

    # ----------------------------------------------------------- persistence
    def save(self) -> None:
        self.last_updated = _now()
        if self.workspace is not None:
            self.workspace.save_session(self)

    def to_dict(self) -> dict:
        d = {k: to_jsonable(getattr(self, k)) for k in self.__dataclass_fields__ if k != "workspace"}
        d["schema"] = "laylaw.interviewer.session/2"
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "InterviewSession":
        def dv(x):
            return None if x is None else DateValue(**{**x, "precision": DatePrecision(x["precision"])})

        def prov(x):
            return Provenance(**{**x, "type": ProvenanceType(x["type"])})

        def fact(x):
            x = dict(x)
            if "status" in x and x["status"] is not None:
                x["status"] = FactStatus(x["status"])
            return Fact(**{**x, "source": SourceOfKnowledge(x["source"]),
                           "certainty": Certainty(x["certainty"]), "provenance": prov(x["provenance"]),
                           "date": dv(x["date"]), "kind": EventKind(x["kind"]),
                           "verification": VerificationStatus(x["verification"])})

        def rec(x):
            x = dict(x)
            if x.get("source_type") is not None:
                x["source_type"] = SupportingSourceType(x["source_type"])
            return SupportingRecord(**{**x, "provenance_type": ProvenanceType(x["provenance_type"]),
                                       "review_status": ReviewStatus(x["review_status"])})

        def corr(x):
            if isinstance(x, str):  # schema/1 stored corrections as plain strings
                return Correction(id="C-legacy", raw_text=x, via="legacy",
                                  provenance=Provenance(ProvenanceType.INTERVIEW, "INTERVIEW:LEGACY"))
            return Correction(**{**x, "provenance": prov(x["provenance"])})

        pq = lambda x: None if x is None else PendingQuestion(**x)  # noqa: E731
        return cls(
            interview_id=d["interview_id"], case_id=d["case_id"], client_id=d["client_id"],
            interviewee=d["interviewee"], interviewer=d["interviewer"], purpose=d["purpose"],
            sections=d["sections"], date_started=d["date_started"], last_updated=d["last_updated"],
            transcript_status=TranscriptStatus(d["transcript_status"]), mode=Mode(d["mode"]),
            status=SessionStatus(d["status"]), is_continuation=d["is_continuation"],
            path_name=d["path_name"], current_section=d["current_section"],
            completed_sections=d["completed_sections"], queue=[pq(q) for q in d["queue"]],
            pending=pq(d["pending"]), last_question_answered=d["last_question_answered"],
            turns=[Turn(**t) for t in d["turns"]],
            raw_answers=[RawAnswer(**r) for r in d.get("raw_answers", [])],
            facts=[fact(f) for f in d["facts"]],
            outcomes=[RequestedOutcome(**{**o, "provenance": prov(o["provenance"])}) for o in d["outcomes"]],
            records=[rec(r) for r in d["records"]],
            findings=[DocumentFinding(**{**f, "provenance": prov(f["provenance"]), "date": dv(f["date"])})
                      for f in d["findings"]],
            candidates=[DocumentCandidate(**{**c, "provenance": prov(c["provenance"])})
                        for c in d.get("candidates", [])],
            discrepancies=[Discrepancy(**x) for x in d["discrepancies"]],
            corrections=[corr(c) for c in d.get("corrections", [])],
            intake=[IntakeItem(**{**i, "provenance": prov(i["provenance"])}) for i in d.get("intake", [])],
            sequence_links=d.get("sequence_links", []),
            open_questions=d["open_questions"], safety_notes=d["safety_notes"], oriented=d["oriented"],
            final_check_started=d["final_check_started"],
            workspace_confirmed=d.get("workspace_confirmed"),
        )

    # ----------------------------------------------------------- interrupt/resume
    def interrupt(self) -> None:
        """Save an interrupted interview so it can be resumed exactly here."""
        if self.status == SessionStatus.ACTIVE:
            self.status = SessionStatus.PAUSED
        self.save()

    def save_and_finish_later(self) -> str:
        """Engine-level control. Keeps the exact pending question as the resume point."""
        self.turns.append(Turn(len(self.turns), self.current_section or "",
                               self.pending.text if self.pending else None, "save and finish later",
                               control="save_later"))
        self.interrupt()
        return SAVED_FOR_LATER

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
        current = [f for f in self.facts if f.status == FactStatus.CURRENT]
        if not current:
            return "the introduction" if not self.intake else "the intake questions"
        f = current[-1]
        return f"{f.topic}: the account recorded as fact {f.id}"

    # ----------------------------------------------------------- provenance
    def _provenance(self, turn_index: Optional[int]) -> Provenance:
        day = self.date_started[:10]
        return Provenance(ProvenanceType.INTERVIEW, f"INTERVIEW:{_slug(self.interviewee)}:{day}",
                          session_id=self.interview_id, turn_index=turn_index)

    # ----------------------------------------------------------- sections
    def add_section(self, section: str) -> None:
        """Adaptive: add a section from the path's canonical set mid-interview."""
        if self.path_name in PATHS:
            validate_sections(self.path_name, [section])
        if section not in self.sections:
            self.sections.append(section)
            self.save()

    def remove_section(self, section: str) -> None:
        if section in self.completed_sections or section == self.current_section:
            raise ValueError("a section already covered or in progress stays on the record")
        if section in self.sections:
            self.sections.remove(section)
            self.save()

    # ----------------------------------------------------------- questioning
    def _emit(self, text: str) -> str:
        return assert_no_advocacy(text, self.mode, attributed=self.attributed_texts())

    def attributed_texts(self) -> list[str]:
        """Wording that belongs to the interviewee or to a document -- never to the
        engine. The advocacy guard preserves it verbatim instead of treating it as
        the interviewer's own statement; all other emitted text is still checked."""
        out: list[str] = [t.answer for t in self.turns] + [r.text for r in self.raw_answers]
        for f in self.facts:
            out += [f.statement, f.location or "", f.told_by or "", *f.people_present]
            if f.date is not None:
                out.append(f.date.original_text)
            for alt in f.alternate_recollections:
                v = alt.get("value")
                out += [str(x) for x in v] if isinstance(v, list) else [str(v)]
        out += [c.raw_text for c in self.corrections]
        out += [i.answer for i in self.intake] + [o.text for o in self.outcomes]
        out += [fd.content for fd in self.findings] + [fd.date.original_text for fd in self.findings if fd.date]
        out += [c.value_text for c in self.candidates] + [c.client_response or "" for c in self.candidates]
        prefix = "Mentioned by interviewee: "
        out += [r.label[len(prefix):] for r in self.records if r.label.startswith(prefix)]
        return [x for x in out if x]

    def next_question(self) -> Optional[str]:
        """Return exactly one question (or None when the interview is done)."""
        if self.status == SessionStatus.PAUSED_FOR_SAFETY:
            self.pending = PendingQuestion("safety", SAFETY_QUESTION)
            return self._emit(SAFETY_QUESTION)
        if self.status == SessionStatus.CLOSED:
            return None
        if self.workspace_confirmed is False:
            return None  # wrong workspace: nothing more is asked until an operator confirms
        if self.status == SessionStatus.PAUSED:
            self.status = SessionStatus.ACTIVE
        if self.pending is None:
            self.pending = self._advance()
        self.save()
        if self.pending is None:
            return None
        text = self.pending.text
        if self.pending.kind == "recap" and self.pending.field == "0":
            text = self.section_recap(with_questions=False) + "\n\n" + text
        if self.pending.kind == "final" and self.pending.field == "0":
            text = self.summary_review() + "\n\n" + text
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
            self.queue = [PendingQuestion("final", q, field=str(i))
                          for i, q in enumerate(FINAL_CHECK_QUESTIONS) if i > 0]
            return PendingQuestion("final", FINAL_CHECK_QUESTIONS[0], field="0")
        self.status = SessionStatus.CLOSED
        return None

    @staticmethod
    def is_request_section(section: Optional[str]) -> bool:
        if not section:
            return False
        return spec_for(section).kind == "request" or bool(
            re.search(r"(?i)request|going forward|would like", section))

    @staticmethod
    def free_account_prompt(section: str) -> str:
        spec = spec_for(section)
        if spec.prompt:
            return spec.prompt
        if InterviewSession.is_request_section(section):
            return "What would you like to happen going forward?"
        if re.search(r"(?i)routine", section):
            return f"Tell me what normally happens with {section.lower()}."
        return f"Tell me about {section.lower()}, from the beginning."

    # ----------------------------------------------------------- answering
    def answer(self, text: str, **tags) -> Optional[str]:
        """Record the interviewee's answer to the pending question.

        Returns a short acknowledgement only for controls (e.g. save-for-later)."""
        q = self.pending
        control = tags.pop("control", None) or classify.detect_control(text)
        if control == "save_later":
            return self.save_and_finish_later()

        turn = Turn(len(self.turns), self.current_section or "", q.text if q else None, text, control=control)
        self.turns.append(turn)
        self.last_question_answered = q.text if q else None
        self.pending = None

        if q and q.kind == "preflight" and q.field == "danger" and control != "skip":
            # Any answer other than a clear "no" -- a plain "yes", "maybe", "not sure" --
            # pauses ordinary interviewing. The answer is kept as intake.
            if control == "not_sure" or classify.detect_present_safety_issue(text) or not _is_no_danger(text):
                self.intake.append(IntakeItem(q.field, q.text, text, self._provenance(turn.index),
                                              status="not_sure" if control == "not_sure" else "answered"))
                self._pause_for_safety(q, turn.index)
                return None
        if classify.detect_present_safety_issue(text) or (
                q and q.kind == "preflight" and q.field == "urgent"
                and re.match(r"(?i)\s*yes\b", text) and re.search(r"(?i)danger|hurt|unsafe|threat", text)):
            self._pause_for_safety(q, turn.index)
            return None

        kind = q.kind if q else "free_account"
        if control in ("skip", "not_sure"):
            self._apply_control(control, q, turn.index)
        elif kind == "safety":
            if tags.get("keep_paused") or _not_safe(text):
                self.safety_notes.append(f"turn {turn.index}: interviewee not yet safe; interview stays paused")
            else:
                self.safety_notes.append(f"turn {turn.index}: safety check answered")
                self.status = SessionStatus.ACTIVE
        elif kind == "preflight":
            self._record_intake(q, text, turn.index)
        elif kind == "free_account":
            self._record_free_account(text, turn.index, **tags)
        elif kind == "procedural":
            self._record_procedural(q, text, turn.index, **tags)
        elif kind == "clarify":
            self._apply_clarification(q, text, turn.index, **tags)
        elif kind == "record_hook":
            self._apply_record_hook(q, text, source_type=tags.get("source_type"))
        elif kind in ("recap", "final"):
            self._handle_check_answer(q, text, turn.index)
        elif kind == "check_followup":
            self._handle_check_followup(q, text, turn.index)
        elif kind == "correction_target":
            self._resolve_correction_target(q, text)
        self.save()
        return None

    def _pause_for_safety(self, q: Optional[PendingQuestion], turn_index: int) -> None:
        self.status = SessionStatus.PAUSED_FOR_SAFETY
        self.safety_notes.append(f"turn {turn_index}: possible present danger described; "
                                 f"ordinary interviewing paused")
        if q and q.kind != "safety" and not (q.kind == "preflight" and q.field in ("danger", "urgent")):
            self.queue.insert(0, q)  # come back to the same question afterwards
        self.save()

    # ----------------------------------------------------------- controls
    def skip(self) -> None:
        self.answer("skip", control="skip")

    def not_sure(self) -> None:
        self.answer("not sure", control="not_sure")

    def _apply_control(self, control: str, q: Optional[PendingQuestion], turn_index: int) -> None:
        """Skip / not sure are recorded as what they are -- never as facts."""
        label = "Skipped by interviewee" if control == "skip" else "Interviewee not sure / doesn't remember"
        if q is None:
            return
        if q.kind == "preflight":
            self.intake.append(IntakeItem(q.field, q.text, "", self._provenance(turn_index),
                                          status="skipped" if control == "skip" else "not_sure"))
            if q.field == "confirm_workspace":
                self._set_workspace_confirmation(False)   # unconfirmed is never treated as confirmed
            if q.field == "danger":                       # a skipped danger question is never a "no"
                self.safety_notes.append(f"turn {turn_index}: immediate-danger question {label.lower()}; "
                                         f"not treated as 'no one is in danger'")
                self.open_questions.append("Immediate danger not answered: check in about safety before "
                                           "relying on this session")
            return
        if q.kind in ("free_account", "procedural"):
            self.open_questions.append(f"{label}: {q.text} ({self.current_section})")
            return
        if q.kind == "clarify" and q.fact_id:
            fact = self.get_fact(q.fact_id)
            if q.field == "date" and control == "not_sure":
                fact.date = DateValue("not sure", DatePrecision.UNKNOWN)  # unknown, stated as such
            if q.field == "discrepancy":
                d = self._discrepancy_for(q)
                if d:
                    d.resolution_note = f"Interviewee: {'skipped' if control == 'skip' else 'not sure'}"
            fact.open_questions.append(f"{label}: {q.text}")
            return
        if q.kind == "correction_target":
            self.open_questions.append(f"Correction {q.field} not yet matched to an item ({label.lower()})")
            return
        if q.kind in ("recap", "final", "record_hook", "check_followup"):
            self.open_questions.append(f"{label}: {q.text}")

    # ----------------------------------------------------------- intake
    def _record_intake(self, q: PendingQuestion, text: str, turn_index: int) -> None:
        self.intake.append(IntakeItem(q.field, q.text, text, self._provenance(turn_index)))
        if q.field == "confirm_workspace":
            self._set_workspace_confirmation(bool(re.match(r"(?i)\s*(?:yes|yeah|yep|correct|right|that'?s right|"
                                                           r"it is|confirmed)\b", text)) and
                                             not re.search(r"(?i)\b(?:not|wrong|isn'?t|no)\b", text))

    def _set_workspace_confirmation(self, confirmed: bool) -> None:
        self.workspace_confirmed = confirmed
        if not confirmed:
            self.status = SessionStatus.PAUSED
            self.open_questions.append("Workspace NOT confirmed by the interviewee. Stop and open the correct "
                                       "client's workspace before continuing; nothing further was asked here.")
        self.save()

    def confirm_workspace(self) -> None:
        """Operator confirms the right workspace is open after a mismatch was resolved."""
        self.workspace_confirmed = True
        self.open_questions = [o for o in self.open_questions if not o.startswith("Workspace NOT confirmed")]
        if self.status == SessionStatus.PAUSED:
            self.status = SessionStatus.ACTIVE
        self.save()

    def record_intake(self, key: str, answer: str) -> IntakeItem:
        item = IntakeItem(key, PREFLIGHT_QUESTIONS.get(key, key), answer, self._provenance(None))
        self.intake.append(item)
        self.save()
        return item

    # ----------------------------------------------------------- free account / propositions
    def _add_raw_answer(self, text: str, turn_index: int, section: Optional[str] = None) -> RawAnswer:
        raw = RawAnswer(f"A-{len(self.raw_answers) + 1:03d}", turn_index,
                        section if section is not None else (self.current_section or ""), text)
        self.raw_answers.append(raw)
        return raw

    def log_answer(self, text: str, *, question: str, section: Optional[str] = None) -> RawAnswer:
        """Log the interviewee's own answer to a question that was put to them.

        Outside the question flow, this is the only way words enter the record as
        the interviewee's: the answer is kept verbatim as a turn (with its question)
        and as a raw answer. Facts, corrections, and alternate accounts must then be
        exact slices of a logged answer. There is no API that attributes generated
        or paraphrased text to the interviewee."""
        if self.mode != Mode.INTERVIEW:
            raise ModeViolation("answers are logged only in INTERVIEW mode")
        if not (text or "").strip():
            raise ProvenanceError("an empty answer cannot be attributed to the interviewee")
        if not (question or "").strip():
            raise ProvenanceError("log the question this answer responded to")
        sec = section if section is not None else (self.current_section or "")
        turn = Turn(len(self.turns), sec, question, text)
        self.turns.append(turn)
        raw = self._add_raw_answer(text, turn.index, section=sec)
        self.save()
        return raw

    def record_statement(self, text: str, *, topic: str, question: Optional[str] = None, **tags) -> Fact:
        """Log the interviewee's answer and record it, whole and verbatim, as one fact."""
        if classify.is_request(text) and tags.get("source") is None:
            raise ValueError("this is a requested outcome; use record_request()")
        raw = self.log_answer(text, question=question or "(answer entered directly)", section=topic)
        return self.record_fact(text, topic=topic, raw_answer_id=raw.id, span=[0, len(text)], **tags)

    def _source_slice(self, statement: str, raw_answer_id: Optional[str],
                      span: Optional[list[int]]) -> tuple[RawAnswer, list[int]]:
        """Traceability check: the statement must be an exact slice of a logged answer."""
        if raw_answer_id is None:
            raise ProvenanceError("an interview statement must come from the interviewee's logged answer "
                                  "(raw_answer_id); generated text cannot be attributed to the interviewee")
        raw = next((r for r in self.raw_answers if r.id == raw_answer_id), None)
        if raw is None:
            raise ProvenanceError(f"no logged answer {raw_answer_id}")
        if span is None:
            start = raw.text.find(statement) if statement else -1
            span = [start, start + len(statement)] if start >= 0 else None
        if not statement.strip() or span is None or raw.text[span[0]:span[1]] != statement:
            raise ProvenanceError("statement is not a verbatim slice of the interviewee's answer")
        return raw, list(span)

    def _record_free_account(self, text: str, turn_index: int, **tags) -> None:
        section = self.current_section or "general"
        spec = spec_for(section)
        if _is_nothing_more(text):
            # "No" / "nothing" to an opening prompt is not a fact and not a request.
            self.open_questions.append(f"Interviewee had nothing to add for: {section} (answer: \"{text}\")")
            return
        if spec.kind == "request" or (self.is_request_section(section) and not tags.get("source")):
            self.record_request(text, turn_index=turn_index)
            return
        if spec.kind == "records":
            self._apply_record_hook(PendingQuestion("record_hook", "", None), text,
                                    source_type=tags.get("source_type"))
            return
        if spec.kind == "routine" or re.search(r"(?i)routine", section):
            tags.setdefault("kind", EventKind.ROUTINE)
        if spec.default_source and "source" not in tags:
            tags["source"] = spec.default_source
        raw = self._add_raw_answer(text, turn_index)
        facts = self._record_propositions(raw, spec_question=None if spec.kind != "procedural" else spec.prompt,
                                          **tags)
        if spec.kind == "procedural":
            self.queue = [q for q in self.queue if q.kind != "recap"] + [
                PendingQuestion("procedural", question, facts[0].id if facts else None, field=key)
                for key, question in spec.followups] + self._recap_questions()
            return
        for f in facts:
            self._queue_clarifications(f)

    def _record_propositions(self, raw: RawAnswer, spans: Optional[list[tuple[int, int]]] = None,
                             spec_question: Optional[str] = None, **tags) -> list[Fact]:
        """One raw answer -> one or more propositions, each a verbatim slice."""
        spans = spans or classify.proposition_spans(raw.text) or [(0, len(raw.text))]
        facts = []
        for a, b in spans:
            piece = raw.text[a:b]
            if classify.is_request(piece) and not tags.get("source"):
                self.record_request(piece, turn_index=raw.turn_index)
                continue
            facts.append(self.record_fact(piece, topic=raw.section or "general", turn_index=raw.turn_index,
                                          raw_answer_id=raw.id, span=[a, b],
                                          question_context=spec_question, **tags))
        return facts

    def record_proposition(self, raw_answer_id: str, start: int, end: int, **tags) -> Fact:
        """Record a proposition from a slice of a stored raw answer. Only the
        interviewee's own words can be recorded this way -- there is no API that
        accepts generated text as the interviewee's statement."""
        raw = next(r for r in self.raw_answers if r.id == raw_answer_id)
        if not (0 <= start < end <= len(raw.text)):
            raise ProvenanceError("span outside the stored answer")
        return self.record_fact(raw.text[start:end], topic=raw.section or "general", turn_index=raw.turn_index,
                                raw_answer_id=raw.id, span=[start, end], **tags)

    def _record_procedural(self, q: PendingQuestion, text: str, turn_index: int, **tags) -> None:
        if _is_no(text) and q.field != "basis":
            return
        raw = self._add_raw_answer(text, turn_index)
        base = self.get_fact(q.fact_id) if q.fact_id else None
        if q.field == "basis" and base is not None:
            base.open_questions.append(f"Basis (interviewee's words): {text}")
            return
        spec = spec_for(self.current_section or "")
        if spec.default_source and "source" not in tags:
            tags["source"] = spec.default_source
        f = self.record_fact(text, topic=raw.section, turn_index=turn_index, raw_answer_id=raw.id,
                             span=[0, len(text)], question_context=q.text, **tags)
        phrase = classify.find_date_phrase(text)
        if phrase and f.date is None:
            self.set_fact_date(f.id, phrase)

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
        if fact.source in (SourceOfKnowledge.PERSONAL_OBSERVATION, SourceOfKnowledge.UNCERTAIN,
                           SourceOfKnowledge.UNKNOWN) and not fact.told_by:
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
        self.queue = [q for q in self.queue if q.kind != "recap"] + qs + self._recap_questions()

    @staticmethod
    def _recap_questions() -> list[PendingQuestion]:
        return [PendingQuestion("recap", q_text, None, field=str(i))
                for i, q_text in enumerate(END_OF_SECTION_QUESTIONS)]

    def _apply_clarification(self, q: PendingQuestion, text: str, turn_index: int, **tags) -> None:
        fact = self.get_fact(q.fact_id)
        if q.field == "date":
            self.set_fact_date(fact.id, text)
        elif q.field == "people_present":
            self.set_people_present(fact.id, text, turn_index=turn_index)
        elif q.field == "location":
            if _is_nothing_more(text):
                fact.open_questions.append(f"Location: interviewee said \"{text}\"")
            else:
                self.set_fact_location(fact.id, text, turn_index=turn_index)
        elif q.field == "source":
            src = tags.get("source") or classify.classify_source(text)
            self._set_source(fact, SourceOfKnowledge(src), basis_text=text)
        elif q.field == "certainty":
            fact.open_questions.append(f"Certainty clarification (interviewee's words): {text}")
        elif q.field == "discrepancy":
            d = self._discrepancy_for(q)
            if d:
                self.resolve_discrepancy(d.id, text)
            else:
                fact.open_questions.append(f"Clarification not matched to a single discrepancy "
                                           f"(interviewee's words): {text}")
        elif q.field == "next":
            if not _is_nothing_more(text):
                raw = self._add_raw_answer(text, turn_index)
                for nxt in self._record_propositions(raw, sequence_hint=f"after {fact.id}", **tags):
                    self._queue_clarifications(nxt)

    # ----------------------------------------------------------- supporting sources
    def _apply_record_hook(self, q, text: str, source_type: Optional[SupportingSourceType] = None) -> None:
        if re.fullmatch(r"(?i)\s*(no|nope|nothing|none|not that i know of|i don'?t think so)\.?\s*", text):
            return
        fact_id = getattr(q, "fact_id", None)
        kind = SupportingSourceType(source_type) if source_type else classify.classify_supporting_source(text)
        rec = SupportingRecord(id="R-" + uuid.uuid4().hex[:10], client_id=self.client_id,
                               session_id=self.interview_id, label=f"Mentioned by interviewee: {text}",
                               provenance_type=SUPPORTING_TO_PROVENANCE[kind], source_type=kind,
                               related_fact_ids=[fact_id] if fact_id else [])
        self.records.append(rec)
        if fact_id:
            f = self.get_fact(fact_id)
            f.possible_records.append(rec.id)
            if f.verification == VerificationStatus.INTERVIEW_ONLY:
                f.verification = (VerificationStatus.WITNESS_IDENTIFIED if kind == SupportingSourceType.WITNESS
                                  else VerificationStatus.DOCUMENT_LOCATED if kind != SupportingSourceType.OTHER
                                  else VerificationStatus.INTERVIEW_ONLY)

    # ----------------------------------------------------------- direct recording API
    def record_fact(self, statement: str, *, topic: str, turn_index: Optional[int] = None,
                    date_text: Optional[str] = None, source: Optional[SourceOfKnowledge | str] = None,
                    told_by: Optional[str] = None, told_by_is_child: bool = False,
                    witnessed_underlying_event: bool = False, people_present: Optional[list[str]] = None,
                    location: Optional[str] = None, kind: EventKind = EventKind.UNSPECIFIED,
                    event_key: Optional[str] = None, exact_wording_remembered: bool = False,
                    sequence_hint: Optional[str] = None, correction_of: Optional[str] = None,
                    raw_answer_id: Optional[str] = None, span: Optional[list[int]] = None,
                    question_context: Optional[str] = None, _derived_from: Optional[Fact] = None) -> Fact:
        """Record a fact that is an exact slice of a logged answer.

        `raw_answer_id` (and `span`, or a statement found verbatim in that answer)
        are required: text with no logged answer behind it -- generated,
        paraphrased, or typed by someone else -- is refused. `_derived_from` is
        internal: a second recollection of an existing fact reuses that fact's
        own words and source slice."""
        if self.mode != Mode.INTERVIEW:
            raise ModeViolation("facts are recorded only in INTERVIEW mode")
        if _derived_from is not None:
            if statement != _derived_from.statement:
                raise ProvenanceError("a derived recollection must keep the original words")
            raw_answer_id, span = _derived_from.raw_answer_id, _derived_from.span
        else:
            raw, span = self._source_slice(statement, raw_answer_id, span)
            if turn_index is None:
                turn_index = raw.turn_index
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
                    sequence_hint=sequence_hint, correction_of=correction_of,
                    raw_answer_id=raw_answer_id, span=list(span) if span else None,
                    question_context=question_context)
        fact.event_key = event_key or f"{topic}:{fact.id}"
        chosen = SourceOfKnowledge(source) if source else detected
        # A secondhand phrase in the interviewee's own words always wins over a default.
        if detected == SourceOfKnowledge.SECONDHAND:
            chosen = SourceOfKnowledge.SECONDHAND
        self._set_source(fact, chosen)
        self.facts.append(fact)
        if date_text is not None:
            self.set_fact_date(fact.id, date_text)
        else:
            phrase = classify.find_date_phrase(statement)
            if phrase and _derived_from is None:
                self.set_fact_date(fact.id, phrase)
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

    # ----------------------------------------------------------- field setters (never overwrite)
    def set_fact_date(self, fact_id: str, date_text: str) -> DateValue:
        fact = self.get_fact(fact_id)
        dv = classify.parse_date(date_text)
        if fact.certainty != Certainty.STATED and dv.precision in (
                DatePrecision.EXACT, DatePrecision.MONTH_ONLY, DatePrecision.SEASON_YEAR) and dv.year is not None:
            # The hedge ("I think...") covers the whole statement, including its date:
            # never present a hedged statement's date as firmer than the statement.
            dv.precision, dv.qualifier = DatePrecision.APPROXIMATE, dv.qualifier or "hedged statement"
        if fact.date is not None and not _dates_compatible(fact.date, dv):
            # A second, different recollection for the same fact: keep both.
            dup = self.record_fact(fact.statement, topic=fact.topic, source=fact.source,
                                   told_by=fact.told_by, told_by_is_child=fact.told_by_is_child,
                                   witnessed_underlying_event=fact.witnessed_underlying_event,
                                   event_key=fact.event_key, turn_index=fact.provenance.turn_index,
                                   sequence_hint=f"second date recollection for the event in {fact.id}",
                                   _derived_from=fact)
            dup.date = dv
            self._check_conflicts(dup)
            self.save()
            return dv
        fact.date = dv
        self._check_conflicts(fact)
        self.save()
        return dv

    def set_fact_location(self, fact_id: str, text: str, *, turn_index: Optional[int] = None) -> None:
        fact = self.get_fact(fact_id)
        if fact.location and _norm(fact.location) != _norm(text):
            fact.alternate_recollections.append({"field": "location", "value": text, "turn": turn_index})
            self._add_discrepancy("location", [fact.id], fact.location, text, fact)
        elif not fact.location:
            fact.location = text.strip()
            self._check_conflicts(fact)
        self.save()

    def set_people_present(self, fact_id: str, text: str, *, turn_index: Optional[int] = None) -> None:
        """Keep the interviewee's own words; never expand or guess names."""
        fact = self.get_fact(fact_id)
        if re.search(r"(?i)\bi don'?t (?:know|remember)\b|\bnot sure\b", text):
            fact.open_questions.append(f"People present: interviewee said \"{text}\"")
            return
        if re.fullmatch(r"(?i)\s*(?:no one|nobody|no one else|nobody else)\.?\s*", text):
            people = ["interviewee only (as stated)"]
        else:
            additive = bool(re.match(r"(?i)\s*(?:also|and also|plus)\b", text))
            cleaned = re.sub(r"(?i)^\s*(?:just|also|and also|plus)\s+", "", text.strip().rstrip("."))
            parts = [n.strip() for n in re.split(r",|\band\b", cleaned) if n.strip()]
            people = ["interviewee" if p.lower() in ("me", "i", "myself") else p for p in parts]
            if additive:
                fact.people_present.extend(p for p in people if p not in fact.people_present)
                self.save()
                return
        if fact.people_present and {_norm(p) for p in fact.people_present} != {_norm(p) for p in people}:
            fact.alternate_recollections.append({"field": "people_present", "value": people, "turn": turn_index})
            self._add_discrepancy("people_present", [fact.id], ", ".join(fact.people_present),
                                  ", ".join(people), fact)
        elif not fact.people_present:
            fact.people_present.extend(people)
            self._check_conflicts(fact)
        self.save()

    def record_sequence(self, first_id: str, relation: str, second_id: str) -> None:
        """Record the interviewee's stated order of two events ("before"/"after")."""
        if relation not in ("before", "after"):
            raise ValueError("relation must be 'before' or 'after'")
        a, b = (first_id, second_id) if relation == "before" else (second_id, first_id)
        opposite = next((x for x in self.sequence_links if x["earlier"] == b and x["later"] == a), None)
        self.sequence_links.append({"earlier": a, "later": b})
        if opposite:
            self._add_discrepancy("sequence", [a, b], f"{b} happened before {a}", f"{a} happened before {b}",
                                  self.get_fact(a))
        self.save()

    def record_conflicting_account(self, fact_id: str, statement: str, *,
                                   raw_answer_id: Optional[str] = None, span: Optional[list[int]] = None,
                                   turn_index: Optional[int] = None) -> Fact:
        """A materially different recollection of the same event. Both are kept;
        the engine never decides which is more accurate or more favorable. The
        alternate account must be the interviewee's own logged words."""
        orig = self.get_fact(fact_id)
        self._source_slice(statement, raw_answer_id, span)     # refuse before anything changes
        alt = self.record_fact(statement, topic=orig.topic, turn_index=turn_index, event_key=orig.event_key,
                               told_by=orig.told_by, told_by_is_child=orig.told_by_is_child,
                               witnessed_underlying_event=orig.witnessed_underlying_event,
                               sequence_hint=f"alternate recollection of {orig.id}",
                               raw_answer_id=raw_answer_id, span=span)
        self._add_discrepancy("account", [orig.id, alt.id], orig.statement, alt.statement, alt)
        self.save()
        return alt

    def _check_conflicts(self, fact: Fact) -> None:
        for other in self.facts:
            if other.id == fact.id or other.event_key != fact.event_key or other.status != FactStatus.CURRENT \
                    or fact.status != FactStatus.CURRENT:
                continue
            if other.date is not None and fact.date is not None and not _dates_compatible(other.date, fact.date):
                self._add_discrepancy("date", [other.id, fact.id], other.date.original_text,
                                      fact.date.original_text, fact)
            if other.location and fact.location and _norm(other.location) != _norm(fact.location):
                self._add_discrepancy("location", [other.id, fact.id], other.location, fact.location, fact)
            if other.people_present and fact.people_present and \
                    {_norm(p) for p in other.people_present} != {_norm(p) for p in fact.people_present}:
                self._add_discrepancy("people_present", [other.id, fact.id], ", ".join(other.people_present),
                                      ", ".join(fact.people_present), fact)

    def _add_discrepancy(self, field_name: str, fact_ids: list[str], earlier: str, later: str,
                         ask_about: Fact) -> Optional[Discrepancy]:
        ids = sorted(set(fact_ids))
        description = f'Recollection A: "{earlier}"; Recollection B: "{later}"'
        if any(d.field == field_name and sorted(d.fact_ids) == ids and d.description == description
               for d in self.discrepancies):
            return None
        d = Discrepancy(id=f"D-{len(self.discrepancies) + 1:03d}", topic=ask_about.topic, fact_ids=ids,
                        field=field_name, description=description)
        self.discrepancies.append(d)
        for fid in ids:
            f = self.get_fact(fid)
            if f.verification in (VerificationStatus.INTERVIEW_ONLY, VerificationStatus.DISPUTED):
                f.verification = VerificationStatus.DISPUTED
        self.queue.insert(0, PendingQuestion(
            "clarify",
            f'Earlier I wrote down "{earlier}". Just now you said "{later}". '
            f"Which is closer to what you remember now?",
            ask_about.id, "discrepancy", ref=d.id))
        return d

    def _discrepancy_for(self, q: PendingQuestion) -> Optional[Discrepancy]:
        """The exact discrepancy a clarification question was about. Questions
        saved before ids were bound fall back only when one discrepancy is open
        for the fact; the engine never guesses between several."""
        if q.ref:
            return next((d for d in self.discrepancies if d.id == q.ref), None)
        open_ = [d for d in self.discrepancies if q.fact_id in d.fact_ids and d.status == "unresolved"]
        return open_[0] if len(open_) == 1 else None

    def resolve_discrepancy(self, discrepancy_id: str, interviewee_explanation: str) -> Discrepancy:
        """Only the interviewee's own explanation can resolve a discrepancy, and
        both original recollections are kept either way."""
        d = next(x for x in self.discrepancies if x.id == discrepancy_id)
        if re.search(r"(?i)\b(?:don'?t know|not sure|can'?t say|either|both|no idea)\b", interviewee_explanation) \
                or classify.detect_control(interviewee_explanation):
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

    def _current_facts(self, section: Optional[str] = None) -> list[Fact]:
        return [f for f in self.facts if f.status == FactStatus.CURRENT and (section is None or f.topic == section)]

    # ----------------------------------------------------------- end-of-section / final checks
    def _handle_check_answer(self, q: PendingQuestion, text: str, turn_index: int) -> None:
        """Separate acknowledgements, additions, and corrections.

        A bare "yes" is an acknowledgement, never content: it asks what should
        change (or what was missed) instead of replacing anything. Only the
        interviewee's substantive words become a correction or an addition."""
        stage = q.kind
        role = _CHECK_ROLES.get((stage, q.field or "0"), "follow_up")
        if _is_no(text):
            return
        if _is_bare_ack(text):
            if role in _CHECK_FOLLOWUPS:
                self.queue.insert(0, PendingQuestion("check_followup", _CHECK_FOLLOWUPS[role],
                                                     field=f"{stage}:{role}"))
            else:
                self.open_questions.append(f"Final check - {q.text} -> {text}")
            return
        self._route_check_content(stage, role, q.text, text, turn_index)

    def _handle_check_followup(self, q: PendingQuestion, text: str, turn_index: int) -> None:
        stage, role = (q.field or "recap:correction").split(":", 1)
        if _is_no(text):
            return
        if _is_bare_ack(text):
            self.open_questions.append(f"Interviewee indicated a change at the {stage} check but did not say "
                                       f"what it was (answer to \"{q.text}\": \"{text}\")")
            return
        self._route_check_content(stage, role, q.text, text, turn_index)

    def _route_check_content(self, stage: str, role: str, question: str, text: str, turn_index: int) -> None:
        start = _content_start(text)
        if role in ("correction", "certainty"):
            candidates = [f.id for f in self._current_facts(self.current_section if stage == "recap" else None)]
            self._start_correction(text, "recap" if stage == "recap" else "final_check", turn_index,
                                   candidates, content_start=start)
        elif role == "addition":
            self._record_addition(text, start, turn_index, question)
        else:
            self.open_questions.append(f"Final check - {question} -> {text}")

    def _record_addition(self, text: str, start: int, turn_index: int, question: str = "") -> None:
        """Something the interviewee says was missed: recorded as new items in
        their own words. Nothing already on the record is replaced."""
        section = self.current_section or "general"
        spec = spec_for(section)
        end = len(text.rstrip())
        raw = self._add_raw_answer(text, turn_index)
        content = text[start:end]
        if spec.kind == "request" or self.is_request_section(section):
            self.record_request(content, turn_index=turn_index)
            return
        if spec.kind == "records":
            self._apply_record_hook(PendingQuestion("record_hook", "", None), content)
            return
        tags: dict = {}
        if spec.kind == "routine" or re.search(r"(?i)routine", section):
            tags["kind"] = EventKind.ROUTINE
        if spec.default_source:
            tags["source"] = spec.default_source
        spans = [(start + a, start + b) for a, b in classify.proposition_spans(content)] or [(start, end)]
        if spec.kind == "procedural":
            # Paperwork/court items: kept with the question they answered; no incident follow-ups.
            self._record_propositions(raw, spans=spans, spec_question=question, **tags)
            return
        for f in self._record_propositions(raw, spans=spans, **tags):
            self._queue_clarifications(f)

    # ----------------------------------------------------------- corrections
    def _start_correction(self, text: str, via: str, turn_index: int, candidate_ids: list[str],
                          content_start: int = 0) -> Correction:
        raw = self._add_raw_answer(text, turn_index)
        span = [content_start, len(text.rstrip())]
        corr = Correction(id=f"C-{len(self.corrections) + 1:03d}", raw_text=text, via=via,
                          provenance=self._provenance(turn_index), raw_answer_id=raw.id, span=span)
        self.corrections.append(corr)
        corr.candidate_ids = list(candidate_ids)
        target = _explicit_target(text, candidate_ids)
        if target is None and len(candidate_ids) == 1:
            target = candidate_ids[0]
        if target:
            self._apply_correction(corr, target)
        elif candidate_ids:
            listing = "\n".join(f"{i}. {self.get_fact(fid).statement}" for i, fid in enumerate(candidate_ids, 1))
            self.queue.insert(0, PendingQuestion(
                "correction_target",
                f"Here is what I have written down:\n{listing}\n\nWhich numbered item does that change?",
                None, field=corr.id))
            self.open_questions.append(f"Correction {corr.id} awaiting the item it applies to")
        else:
            self.open_questions.append(f"Correction {corr.id} could not be matched to a recorded item")
        return corr

    def _resolve_correction_target(self, q: PendingQuestion, text: str) -> None:
        corr = next(c for c in self.corrections if c.id == q.field)
        cands = corr.candidate_ids or [f.id for f in self._current_facts()]
        target = _explicit_target(text, cands, allow_bare_number=True)
        if target:
            self._apply_correction(corr, target)
            self.open_questions = [o for o in self.open_questions if corr.id not in o]

    def _apply_correction(self, corr: Correction, target_id: str) -> Fact:
        if corr.raw_answer_id is None:
            # Saved before corrections were linked to a logged answer: the words were the
            # interviewee's answer at that turn, so link them to that turn -- nothing else.
            turn = next((t for t in self.turns if t.index == corr.provenance.turn_index), None)
            if turn is None or turn.answer != corr.raw_text:
                raise ProvenanceError(f"{corr.id} cannot be traced to the interviewee's answer")
            corr.raw_answer_id = self._add_raw_answer(turn.answer, turn.index, turn.section).id
            corr.span = [0, len(turn.answer.rstrip())]
        raw = next(r for r in self.raw_answers if r.id == corr.raw_answer_id)
        content = raw.text[corr.span[0]:corr.span[1]]
        return self.correct_fact(target_id, content, via=corr.via, turn_index=corr.provenance.turn_index,
                                 raw_answer_id=corr.raw_answer_id, span=corr.span, _correction=corr)

    def correct_fact(self, fact_id: str, corrected_statement: str, *, via: str = "direct",
                     raw_answer_id: Optional[str] = None, span: Optional[list[int]] = None,
                     turn_index: Optional[int] = None, date_text: Optional[str] = None,
                     location: Optional[str] = None, people_present: Optional[list[str]] = None,
                     _correction: Optional[Correction] = None) -> Fact:
        """Create a corrected version linked to the original. The original is
        kept, marked superseded, and never edited or deleted. The corrected words
        must be an exact slice of the interviewee's logged answer."""
        orig = self.get_fact(fact_id)
        if orig.status == FactStatus.SUPERSEDED:
            raise ValueError(f"{fact_id} was already corrected by {orig.superseded_by}; correct that version")
        raw, span = self._source_slice(corrected_statement, raw_answer_id, span)   # refuse before changing
        detected = classify.classify_source(corrected_statement)
        # A correction revises the same account: when its words give no basis of
        # their own, it keeps the basis already on record (which may be UNKNOWN)
        # rather than acquiring one the interviewee never stated.
        source = orig.source if detected in (SourceOfKnowledge.REQUEST, SourceOfKnowledge.UNKNOWN) else detected
        if date_text is None:
            date_text = classify.find_date_phrase(corrected_statement)  # interviewee's own words only
        new = self.record_fact(corrected_statement, topic=orig.topic, turn_index=turn_index, source=source,
                               told_by=orig.told_by, told_by_is_child=orig.told_by_is_child,
                               witnessed_underlying_event=orig.witnessed_underlying_event, kind=orig.kind,
                               event_key=orig.event_key, correction_of=orig.id, date_text=date_text,
                               location=location, people_present=people_present,
                               raw_answer_id=raw.id, span=span)
        orig.status = FactStatus.SUPERSEDED
        orig.superseded_by = new.id
        corr = _correction or Correction(id=f"C-{len(self.corrections) + 1:03d}",
                                         raw_text=raw.text, via=via, provenance=self._provenance(new.provenance.turn_index),
                                         raw_answer_id=raw.id, span=span)
        if _correction is None:
            self.corrections.append(corr)
        corr.target_fact_id, corr.new_fact_id, corr.status = orig.id, new.id, "applied"
        self.save()
        return new

    # ----------------------------------------------------------- records & documents
    def add_upload(self, filename: str, data: bytes, *, label: Optional[str] = None,
                   related_fact_ids: Optional[list[str]] = None,
                   provenance_type: ProvenanceType = ProvenanceType.DOCUMENT,
                   source_type: Optional[SupportingSourceType] = None) -> SupportingRecord:
        """Uploads can arrive at any point in the interview; each stays attached to
        this client and this session."""
        rec = self.workspace.store_upload(self.interview_id, filename, data, label=label,
                                          provenance_type=provenance_type)
        if source_type is not None:
            rec.source_type = SupportingSourceType(source_type)
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
        finding = DocumentFinding(id=f"DF-{len(self.findings) + 1:03d}", fact_id=fact_id,
                                  record_id=record_id, content=content,
                                  provenance=self._doc_provenance(rec, page),
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

    def _doc_provenance(self, rec: SupportingRecord, page: Optional[str]) -> Provenance:
        prefix = {SupportingSourceType.EMAIL_TEXT: "EMAIL-TEXT",
                  SupportingSourceType.COURT_RECORD: "COURT-RECORD"}.get(rec.source_type, "DOCUMENT")
        label = f"{prefix}:{_slug(rec.label)}" + (f":PAGE-{page}" if page else "")
        return Provenance(rec.provenance_type, label, record_id=rec.id)

    # document-derived candidates ------------------------------------------------
    def propose_document_candidate(self, record_id: str, field_name: str, value_text: str, *,
                                   fact_id: Optional[str] = None, page: Optional[str] = None) -> DocumentCandidate:
        """A date/detail read from a document (by a person or an extractor). It is
        never merged into the recollection; it waits for the client to confirm or correct it."""
        rec = next(r for r in self.records if r.id == record_id)
        cand = DocumentCandidate(id=f"DC-{len(self.candidates) + 1:03d}", record_id=record_id,
                                 field=field_name, value_text=value_text,
                                 provenance=self._doc_provenance(rec, page), fact_id=fact_id)
        self.candidates.append(cand)
        self.save()
        return cand

    def respond_to_candidate(self, candidate_id: str, client_words: str, decision: str, *,
                             corrected_value: Optional[str] = None,
                             turn_index: Optional[int] = None) -> DocumentCandidate:
        """decision: 'confirm' | 'correct' | 'reject'. Confirming or correcting
        creates a new, linked fact version in the client's own words; the original
        recollection stays on the record."""
        cand = next(c for c in self.candidates if c.id == candidate_id)
        if decision not in ("confirm", "correct", "reject"):
            raise ValueError("decision must be confirm, correct, or reject")
        cand.client_response = client_words
        if decision == "reject":
            cand.status = "rejected"
        else:
            cand.status = "confirmed" if decision == "confirm" else "corrected"
            value = cand.value_text if decision == "confirm" else (corrected_value or client_words)
            if cand.fact_id:
                # The client's reply is logged as their answer to the document check,
                # so the new version is a traceable slice of their own words.
                raw = self.log_answer(client_words, question=(
                    f"Document check: {cand.provenance.label} shows {cand.field} '{cand.value_text}'. "
                    f"Does that match what you remember?"))
                new = self.correct_fact(cand.fact_id, client_words, via="document_candidate",
                                        raw_answer_id=raw.id, span=[0, len(client_words)],
                                        turn_index=raw.turn_index,
                                        date_text=value if cand.field == "date" else None)
                cand.resulting_fact_id = new.id
        self.save()
        return cand

    # ----------------------------------------------------------- recaps
    def section_recap(self, section: Optional[str] = None, with_questions: bool = True) -> str:
        from .outputs import neutral_fact_line
        section = section or self.current_section
        lines = [neutral_fact_line(f, self) for f in self._current_facts(section)]
        body = "\n".join(f"- {ln}" for ln in lines) or "- (nothing recorded yet)"
        text = f"Here's what I have for {section.lower()}:\n{body}"
        if with_questions:
            text += "\n\n" + "\n".join(END_OF_SECTION_QUESTIONS)
        return self._emit(text)

    def summary_review(self) -> str:
        """Build Notes: review the summary together, separating what the client
        reported, what documents show, and what remains unknown."""
        from .outputs import neutral_fact_line
        reported = [f"- {neutral_fact_line(f, self)}" for f in self._current_facts()] or ["- (nothing recorded)"]
        docs = [f"- {fd.provenance.label}: {fd.content} ({fd.consistency} with the recollection)"
                for fd in self.findings]
        docs += [f"- {c.provenance.label}: {c.field} '{c.value_text}' (client {c.status})"
                 for c in self.candidates if c.status in ("confirmed", "corrected")]
        docs += [f"- {c.provenance.label}: {c.field} '{c.value_text}' (not yet confirmed by you)"
                 for c in self.candidates if c.status == "candidate"]
        unknown = [f"- {o}" for o in self.open_questions]
        unknown += [f"- {d.id}: two recollections kept ({d.field}): {d.description}"
                    for d in self.discrepancies if d.status == "unresolved"]
        text = ("Before we finish, here is the summary.\n\nWHAT YOU REPORTED\n" + "\n".join(reported)
                + "\n\nWHAT DOCUMENTS SHOW\n" + ("\n".join(docs) or "- (no documents reviewed yet)")
                + "\n\nWHAT REMAINS UNKNOWN\n" + ("\n".join(unknown) or "- (nothing listed)"))
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
_NO_WORD = (r"(?:no|nope|nah|none|nothing|looks (?:right|good|fine)|that'?s (?:right|correct|it|all)|correct|"
            r"all good|nothing else|i think (?:that'?s|it'?s) (?:it|all|right))")
_NO = re.compile(rf"(?i)\s*{_NO_WORD}(?:[\s,.!;:-]+{_NO_WORD})*[.!]?\s*")


def _is_nothing_more(text: str) -> bool:
    return not text.strip() or bool(_NOTHING_MORE.fullmatch(text))


_NO_DANGER = re.compile(
    r"(?i)\s*(?:no|nope|nah|not that i know of|nobody|no one|no-one|none|"
    r"(?:i'?m|i am|we'?re|we are|everyone'?s|everyone is|we'?re all|all) (?:safe|fine|ok(?:ay)?))\b")
_NOT_SAFE = re.compile(
    r"(?i)\s*(?:no|nope|not (?:yet|really|safe|right now)|i'?m not|i am not|we'?re not|we are not)\b"
    r"(?![,.]? (?:problem|worries)\b)")


_SAYS_SAFE = re.compile(r"(?i)\b(?:i'?m|i am|we'?re|we are|everyone'?s|everyone is|all) (?:now |all )?"
                        r"(?:safe|fine|ok(?:ay)?|good)\b")


def _not_safe(text: str) -> bool:
    """'No' / 'not yet' to "are you safe right now?" -- unless they also say they are safe."""
    return bool(_NOT_SAFE.match(text)) and not _SAYS_SAFE.search(text)


def _is_no_danger(text: str) -> bool:
    return bool(_NO_DANGER.match(text))


def _is_no(text: str) -> bool:
    return not text.strip() or bool(_NO.fullmatch(text))


# Acknowledgements carry no content of their own ("yes", "yeah, actually").
_ACK_WORD = (r"(?:yes|yeah|yep|yup|ya|sure|ok(?:ay)?|right|mm-?hm+|uh-?huh|i think so|kind of|sort of|"
             r"a little|maybe|probably|actually|there is|there'?s (?:one|something)(?: thing)?|one thing|"
             r"something|i do|a couple(?: of)? things|a few things)")
_ACK = re.compile(rf"(?i)\s*{_ACK_WORD}(?:[\s,.!;:-]+{_ACK_WORD})*[\s.!,]*")
_LEAD_ACK = re.compile(r"(?i)\s*(?:yes|yeah|yep|yup|actually)\b[\s,.:;!\-–—]*")

# What each check question is asking for.
_CHECK_ROLES = {("recap", "0"): "correction", ("recap", "1"): "certainty", ("recap", "2"): "addition",
                ("final", "0"): "not_asked", ("final", "1"): "correction", ("final", "2"): "certainty",
                ("final", "3"): "follow_up"}
_CHECK_FOLLOWUPS = {"correction": "What should I change?",
                    "certainty": "Which part did I make sound more certain than you meant?",
                    "addition": "What did I miss?",
                    "not_asked": "What should I have asked about?"}


def _is_bare_ack(text: str) -> bool:
    return bool(text.strip()) and bool(_ACK.fullmatch(text))


def _content_start(text: str) -> int:
    """Index where the substantive words begin, after leading acknowledgements
    ("Yes, it was green." -> "it was green."). The full answer is still kept."""
    pos = 0
    while True:
        m = _LEAD_ACK.match(text, pos)
        if not m or m.end() == pos or not text[m.end():].strip():
            return pos if text[pos:].strip() else 0
        pos = m.end()


def _explicit_target(text: str, candidate_ids: list[str], allow_bare_number: bool = False) -> Optional[str]:
    """Only an explicit reference picks a target ("item 2", "#2", "F-002"). A
    number inside a correction ("3 people were there") is never read as an item."""
    m = re.search(r"\bF-\d{3}\b", text)
    if m and m.group(0) in candidate_ids:
        return m.group(0)
    if allow_bare_number:
        m = re.fullmatch(r"\s*(?:item|number|no\.?|#)?\s*(\d{1,3})\s*[.!]?\s*", text, flags=re.I)
    else:
        m = re.search(r"(?i)(?:\bitem|\bnumber|#)\s*(\d{1,3})\b", text)
    if m:
        n = int(m.group(1))
        if 1 <= n <= len(candidate_ids):
            return candidate_ids[n - 1]
    return None


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
