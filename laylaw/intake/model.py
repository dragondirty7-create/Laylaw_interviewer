"""The incident intake record.

Everything here is facts as the person gave them. Nothing is inferred into a
fact. A correction keeps the earlier answer. An uploaded file is kept exactly
as received: notes about a file are stored beside it and never written into it.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from .steps import STEP_BY_ID, STEPS, applicable

SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


class AnswerStatus(str, Enum):
    ANSWERED = "answered"
    NOT_SURE = "not_sure"
    SKIPPED = "skipped"


EVIDENCE_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("texts_emails", "Texts or emails"),
    ("work_order", "Maintenance request or work order"),
    ("lease", "Lease pages"),
    ("entry_notice", "Entry notice or entry log"),
    ("footage", "Doorbell or security footage"),
    ("photos", "Photos"),
    ("witness", "Witness material"),
    ("management_response", "Response from management"),
    ("other", "Something else"),
)
EVIDENCE_CATEGORY_LABELS = dict(EVIDENCE_CATEGORIES)


@dataclass
class Answer:
    step_id: str
    status: AnswerStatus
    value: Optional[str]
    answered_at: str
    #: Earlier versions, oldest first, kept when the person changes an answer.
    history: list[dict] = field(default_factory=list)


@dataclass
class EvidenceItem:
    id: str  # the encrypted upload's record id
    category: str
    filename: str
    sha256: str
    size: int
    stored_at: str
    #: Where the file came from, in the person's words ("my phone", "manager's email").
    source: str = ""
    #: The file's date as the person entered it. Not read from the file.
    date_text: str = ""
    notes: str = ""
    #: Always True: the stored bytes are never changed after upload.
    original_preserved: bool = True


class IntakeError(ValueError):
    """A request the intake refuses, with a message for the person."""


@dataclass
class IncidentIntake:
    matter_id: str
    client_id: str
    nickname: str
    created_at: str
    updated_at: str
    synthetic: bool
    answers: dict[str, Answer] = field(default_factory=dict)
    evidence: list[EvidenceItem] = field(default_factory=list)
    #: Exact words a child said on their own, recorded once. See record_child_words.
    child_statement: Optional[dict] = None
    #: Step the person is on. None once every applicable question has been seen.
    current: Optional[str] = None
    #: Set while the person is changing one answer from the review page.
    editing: Optional[str] = None
    schema: int = SCHEMA_VERSION

    # -- creation -----------------------------------------------------------
    @classmethod
    def new(cls, client_id: str, nickname: str, *, synthetic: bool) -> "IncidentIntake":
        stamp = now_iso()
        intake = cls(matter_id="N-" + uuid.uuid4().hex[:12], client_id=client_id,
                     nickname=nickname.strip()[:80], created_at=stamp, updated_at=stamp, synthetic=synthetic)
        intake.current = STEPS[0].id
        return intake

    # -- reading answers -------------------------------------------------------
    def value(self, step_id: str) -> Optional[str]:
        a = self.answers.get(step_id)
        return a.value if a and a.status == AnswerStatus.ANSWERED else None

    def plain_answers(self) -> dict[str, str]:
        """Answered values, plus "not_sure" for not-sure choice questions, for step conditions."""
        out: dict[str, str] = {}
        for sid, a in self.answers.items():
            if a.status == AnswerStatus.ANSWERED and a.value is not None:
                out[sid] = a.value
            elif a.status == AnswerStatus.NOT_SURE:
                out[sid] = "not_sure"
        return out

    def applicable_steps(self) -> list:
        answers = self.plain_answers()
        return [s for s in STEPS if applicable(s, answers)]

    def progress(self) -> tuple[int, int]:
        steps = self.applicable_steps()
        done = sum(1 for s in steps if s.id in self.answers)
        return done, len(steps)

    @property
    def finished(self) -> bool:
        return self.current is None

    # -- answering ------------------------------------------------------------
    def _next_after(self, step_id: str) -> Optional[str]:
        steps = self.applicable_steps()
        ids = [s.id for s in steps]
        if step_id in ids:
            start = ids.index(step_id) + 1
        else:
            # The step stopped applying because of the answer just given; continue from its position.
            order = [s.id for s in STEPS]
            pos = order.index(step_id)
            start = next((i for i, s in enumerate(steps) if order.index(s.id) > pos), len(steps))
        for s in steps[start:]:
            if s.id not in self.answers:
                return s.id
        return None

    def respond(self, step_id: str, status: AnswerStatus, value: Optional[str] = None) -> None:
        step = STEP_BY_ID.get(step_id)
        if step is None:
            raise IntakeError("That question isn't part of this intake.")
        if step_id not in (self.current, self.editing):
            raise IntakeError("That question isn't the one being asked right now. Reload the page.")
        if status == AnswerStatus.ANSWERED:
            value = (value or "").strip()
            if not value:
                raise IntakeError("Add an answer, or choose \"I'm not sure\" or Skip.")
            if len(value) > step.max_len:
                raise IntakeError(f"That answer is longer than this question allows ({step.max_len} characters).")
            if step.kind == "choice" and value not in dict(step.choices):
                raise IntakeError("Choose one of the options.")
            if step.kind == "upload" and value != "done":
                raise IntakeError("Choose Continue when you've added what you have, or Skip.")
            if step.kind == "date" and not _valid_date(value):
                raise IntakeError("Pick a date, or choose \"I'm not sure\".")
            if step.kind == "choice" and value == "not_sure":
                status, value = AnswerStatus.NOT_SURE, None
        else:
            value = None

        if step_id == "child_words" and status == AnswerStatus.ANSWERED:
            self.record_child_words(value or "")

        stamp = now_iso()
        prev = self.answers.get(step_id)
        history = list(prev.history) if prev else []
        if prev is not None:
            history.append({"status": prev.status.value, "value": prev.value, "answered_at": prev.answered_at})
        self.answers[step_id] = Answer(step_id, status, value, stamp, history)
        self._prune_inapplicable()
        self.updated_at = stamp

        if self.editing == step_id:
            self.editing = None
            # A changed answer can open questions that were not asked before (for example
            # "a child was there" after first answering no). Ask those next.
            self.current = self._first_unanswered()
        else:
            self.current = self._next_after(step_id)

    def _first_unanswered(self) -> Optional[str]:
        for s in self.applicable_steps():
            if s.id not in self.answers:
                return s.id
        return None

    def _prune_inapplicable(self) -> None:
        """Answers to questions that no longer apply are set aside, not silently kept in the record.

        They move into the history of a placeholder so nothing the person said is lost, but they no
        longer appear as current facts. The child's recorded words are the exception: words recorded
        once are kept exactly as recorded."""
        live = {s.id for s in self.applicable_steps()}
        for sid in list(self.answers):
            if sid not in live and sid != "child_words":
                a = self.answers.pop(sid)
                self.answers.setdefault(f"_set_aside_{sid}", Answer(
                    f"_set_aside_{sid}", AnswerStatus.SKIPPED, None, now_iso(),
                    [{"status": a.status.value, "value": a.value, "answered_at": a.answered_at}]))

    def go_back(self) -> None:
        steps = [s.id for s in self.applicable_steps()]
        if self.current is None:
            if steps:
                self.current = steps[-1]
            return
        if self.current in steps:
            i = steps.index(self.current)
            if i > 0:
                self.current = steps[i - 1]

    def edit(self, step_id: str) -> None:
        if step_id not in {s.id for s in self.applicable_steps()}:
            raise IntakeError("That question isn't part of this intake.")
        self.editing = step_id

    def cancel_edit(self) -> None:
        self.editing = None

    # -- the child's own words ------------------------------------------------
    def record_child_words(self, words: str) -> None:
        """Exact words, recorded once. A second, different version is refused rather than replacing the first."""
        words = words.strip()
        if not words:
            raise IntakeError("Add the words, or choose \"I'm not sure\" or Skip.")
        if self.child_statement is not None:
            if self.child_statement["words"] == words:
                return
            raise IntakeError("The child's words were already recorded once and are kept exactly as first "
                              "written. If something is different, add it under \"anything you're unsure "
                              "about\" instead.")
        self.child_statement = {"words": words, "recorded_at": now_iso()}

    # -- evidence ---------------------------------------------------------------
    def add_evidence(self, item: EvidenceItem) -> None:
        if item.category not in EVIDENCE_CATEGORY_LABELS:
            raise IntakeError("Choose what kind of file this is.")
        if any(e.id == item.id for e in self.evidence):
            raise IntakeError("That file is already listed.")
        self.evidence.append(item)
        self.updated_at = now_iso()

    # -- serialisation ------------------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["answers"] = {k: {**asdict(a), "status": a.status.value} for k, a in self.answers.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "IncidentIntake":
        d = dict(d)
        if d.get("schema") != SCHEMA_VERSION:
            raise IntakeError("This intake was saved by a different version of Laylaw.")
        answers = {k: Answer(step_id=v["step_id"], status=AnswerStatus(v["status"]), value=v["value"],
                             answered_at=v["answered_at"], history=list(v.get("history", [])))
                   for k, v in d.pop("answers", {}).items()}
        evidence = [EvidenceItem(**e) for e in d.pop("evidence", [])]
        return cls(answers=answers, evidence=evidence, **d)
