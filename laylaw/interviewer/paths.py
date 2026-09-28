"""Question paths. Every path runs on the same InterviewSession engine with the
same rules; a path only chooses which sections to cover and what notice to show.
"""
from __future__ import annotations

from .session import InterviewSession
from .models import TranscriptStatus

FAMILY_LAW_SECTIONS = [
    "Case basics", "Relationship / family history", "Current household", "Current parenting routine",
    "Historical caregiving", "Children's schooling", "Medical care", "Major parenting decisions",
    "Communication between parents", "Exchanges / transportation", "Work schedules", "Housing",
    "Finances relevant to family issues", "Support history", "Property / debts", "Specific safety concerns",
    "Specific incidents", "Other caregivers", "Court orders", "Court filings", "Service status",
    "Prior agreements", "Current requested arrangement", "Available records", "Witnesses", "Open questions",
]

# Neutral fact-gathering topics only. No defense theory, no advice on what to
# say, and no suggestion that anything here is privileged.
CRIMINAL_DEFENSE_SECTIONS = [
    "Case basics", "The events in question", "Where you were and who was with you",
    "Contact with police or investigators", "Paperwork you received", "Court dates and conditions",
    "Available records", "Witnesses", "Open questions",
]

CRIMINAL_DEFENSE_NOTICE = (
    "Before we start: Laylaw is not a lawyer, and using it does not create an attorney-client "
    "relationship. What you enter here is not protected by attorney-client privilege and could be "
    "requested by others in a legal case. If you have been charged or are under investigation, "
    "consider talking with a criminal defense attorney or public defender before recording details."
)

PATHS = {
    "family_law": {"sections": FAMILY_LAW_SECTIONS, "notice": None},
    "criminal_defense": {"sections": CRIMINAL_DEFENSE_SECTIONS, "notice": CRIMINAL_DEFENSE_NOTICE},
}


def start_path(path_name: str, workspace, *, case_id: str, interviewee: str, interviewer: str,
               purpose: str, interviewee_is_adult: bool, sections: list[str] | None = None,
               transcript_status: TranscriptStatus = TranscriptStatus.STRUCTURED_NOTES):
    """Returns (session, notice_or_None). `sections` may narrow the path to the
    topics relevant to this case -- the spec says adapt, don't ask mechanically."""
    cfg = PATHS[path_name]
    chosen = sections or cfg["sections"]
    unknown = [x for x in chosen if x not in cfg["sections"]]
    if unknown:
        raise ValueError(f"not sections of {path_name}: {unknown}")
    session = InterviewSession.start(
        workspace, case_id=case_id, interviewee=interviewee, interviewer=interviewer, purpose=purpose,
        sections=chosen, interviewee_is_adult=interviewee_is_adult,
        transcript_status=transcript_status, path_name=path_name)
    return session, cfg["notice"]
