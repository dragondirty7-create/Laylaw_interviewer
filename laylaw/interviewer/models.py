"""Core record types for the Laylaw Interviewer.

Design rule (golden rule): DO NOT MAKE THE CASE BETTER. MAKE THE RECORD BETTER.
Every type here exists to preserve what the interviewee actually said, how they
know it, and how sure they are -- never to strengthen, summarize away, or
upgrade it.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class Mode(str, Enum):
    """Pipeline stages. INTERVIEW is kept separate from all later stages."""

    INTERVIEW = "INTERVIEW"
    ORGANIZE = "ORGANIZE"
    VERIFY = "VERIFY"
    ANALYZE = "ANALYZE"
    DRAFT = "DRAFT"


class SourceOfKnowledge(str, Enum):
    PERSONAL_OBSERVATION = "personal_observation"
    SECONDHAND = "secondhand"
    INFERENCE = "inference"
    DOCUMENT_RECOLLECTION = "document_recollection"
    UNCERTAIN = "uncertain"
    UNKNOWN = "unknown"
    REQUEST = "request"  # a requested future outcome, never a historical fact


class Certainty(str, Enum):
    """How sure the interviewee said they were. Only ever set from their words."""

    STATED = "stated"          # said plainly, with no hedge
    HEDGED = "hedged"          # "I think", "maybe", "probably", ...
    UNSURE = "unsure"          # "I don't know", "I can't remember"


class DatePrecision(str, Enum):
    """Spec: EXACT / APPROXIMATE / MONTH ONLY / SEASON/YEAR / RELATIVE DATE / UNKNOWN."""

    EXACT = "EXACT"                  # a specific calendar day, stated plainly
    APPROXIMATE = "APPROXIMATE"      # hedged or "around"/"early"/"late" ...
    MONTH_ONLY = "MONTH ONLY"        # month + year, no day
    SEASON_YEAR = "SEASON/YEAR"      # a season and/or a year only
    RELATIVE = "RELATIVE DATE"       # "six months ago", "two weeks after the party"
    UNKNOWN = "UNKNOWN"


class ProvenanceType(str, Enum):
    INTERVIEW = "interview"
    DOCUMENT = "document"
    EMAIL_TEXT = "email_text"
    COURT_RECORD = "court_record"


class ReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"


class TranscriptStatus(str, Enum):
    """Spec: exactly one of these. Reconstructed notes are never a transcript."""

    FULL_VERBATIM = "FULL VERBATIM TRANSCRIPT AVAILABLE"
    PARTIAL = "PARTIAL TRANSCRIPT AVAILABLE"
    STRUCTURED_NOTES = "STRUCTURED NOTES ONLY"
    RECONSTRUCTED = "RECONSTRUCTED FROM AVAILABLE SESSION DATA"
    UNKNOWN = "TRANSCRIPT STATUS UNKNOWN"


class VerificationStatus(str, Enum):
    """Spec fact-table statuses. There is deliberately no 'verified'."""

    INTERVIEW_ONLY = "INTERVIEW ONLY"
    DOCUMENT_LOCATED = "DOCUMENT LOCATED"
    DOCUMENT_REVIEWED = "DOCUMENT REVIEWED"
    CONSISTENT_WITH_DOCUMENT = "CONSISTENT WITH DOCUMENT"
    INCONSISTENT_WITH_DOCUMENT = "INCONSISTENT WITH DOCUMENT"
    WITNESS_IDENTIFIED = "WITNESS IDENTIFIED"
    DISPUTED = "DISPUTED"
    UNKNOWN = "UNKNOWN"


class EventKind(str, Enum):
    """Routine vs incident are asked about and recorded separately."""

    INCIDENT = "incident"
    ROUTINE = "routine"
    UNSPECIFIED = "unspecified"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"                 # interrupted; resumable
    PAUSED_FOR_SAFETY = "paused_for_safety"
    CLOSED = "closed"


@dataclass
class DateValue:
    """A date exactly as precise as the interviewee made it -- no more."""

    original_text: str
    precision: DatePrecision
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    qualifier: Optional[str] = None   # e.g. "around", "early", "spring"

    def sort_key(self) -> tuple:
        # Unknown parts sort to the start of their range, but are never filled in.
        return (self.year or 0, self.month or 0, self.day or 0)

    def display(self) -> str:
        if self.precision == DatePrecision.EXACT:
            return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
        if self.precision == DatePrecision.APPROXIMATE:
            return f"Approximately: {self.original_text} [{self.precision.value}]"
        return f"{self.original_text} [{self.precision.value}]"


@dataclass
class Provenance:
    """Traceable source, rendered like INTERVIEW:<INTERVIEWEE>:<YYYY-MM-DD>.

    Only human or document sources are ever recorded here; classifier output
    (source tags, date precision) is metadata, never attributed to a person.
    """

    type: ProvenanceType
    label: str                          # e.g. "INTERVIEW:JORDAN-AVERY:2026-09-28"
    session_id: Optional[str] = None
    turn_index: Optional[int] = None
    record_id: Optional[str] = None


@dataclass
class Fact:
    """A single thing the interviewee said happened.

    `statement` is always the interviewee's own words. Later document content
    is stored as a separate DocumentFinding linked to the fact -- it never edits
    the recollection.
    """

    id: str
    topic: str
    statement: str
    source: SourceOfKnowledge
    certainty: Certainty
    hedges: list[str]
    provenance: Provenance
    date: Optional[DateValue] = None
    location: Optional[str] = None
    people_present: list[str] = field(default_factory=list)
    kind: "EventKind" = None  # set in __post_init__
    told_by: Optional[str] = None          # who the interviewee heard it from
    told_by_is_child: bool = False
    witnessed_underlying_event: bool = False
    exact_wording_remembered: bool = False  # only then may it be quoted
    verification: "VerificationStatus" = None  # set in __post_init__
    correction_of: Optional[str] = None      # id of an earlier fact this corrects
    event_key: Optional[str] = None          # facts describing the same event share a key
    sequence_hint: Optional[str] = None     # "before X", "after Y"
    possible_records: list[str] = field(default_factory=list)  # SupportingRecord ids
    open_questions: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.kind is None:
            self.kind = EventKind.UNSPECIFIED
        if self.verification is None:
            self.verification = VerificationStatus.INTERVIEW_ONLY


@dataclass
class RequestedOutcome:
    id: str
    text: str
    provenance: Provenance


@dataclass
class SupportingRecord:
    """An uploaded or mentioned record. Unreviewed records are only *potential*
    support; nothing may describe them as corroboration."""

    id: str
    client_id: str
    session_id: str
    label: str
    provenance_type: ProvenanceType
    filename: Optional[str] = None
    sha256: Optional[str] = None
    stored_path: Optional[str] = None
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    related_fact_ids: list[str] = field(default_factory=list)

    def describe(self) -> str:
        if self.review_status == ReviewStatus.UNREVIEWED:
            return f"POTENTIAL SUPPORTING RECORD: {self.label} (not yet reviewed)"
        return f"REVIEWED RECORD: {self.label}"


@dataclass
class DocumentFinding:
    """Spec: INTERVIEWEE RECOLLECTION / DOCUMENT CONTENT / CONSISTENCY-DIFFERENCE,
    recorded separately. The recollection lives on the Fact and is never edited."""

    id: str
    fact_id: str
    record_id: str
    content: str
    provenance: Provenance
    date: Optional[DateValue] = None
    consistency: str = "not assessed"   # "consistent" | "different" | "not assessed"
    difference_note: Optional[str] = None


@dataclass
class Discrepancy:
    id: str
    topic: str
    fact_ids: list[str]
    field: str
    description: str
    status: str = "unresolved"
    resolution_note: Optional[str] = None  # interviewee's own explanation, if any


@dataclass
class Turn:
    index: int
    section: str
    question: Optional[str]
    answer: str


def to_jsonable(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj
