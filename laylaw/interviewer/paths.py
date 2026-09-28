"""Question paths and section specs.

Every path runs on the same InterviewSession engine with the same rules. A
path only defines (a) the canonical set of sections that *may* be covered,
(b) a short default selection, and (c) per-section prompts/follow-ups.
Sections are chosen for the case -- the spec says adapt, don't ask mechanically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import SourceOfKnowledge, TranscriptStatus


@dataclass(frozen=True)
class SectionSpec:
    name: str
    prompt: Optional[str] = None       # free-account prompt; None -> generic
    kind: str = "narrative"            # narrative | procedural | routine | request
    followups: tuple = ()              # (field, question) pairs for procedural sections
    default_source: Optional[SourceOfKnowledge] = None
    optional_note: Optional[str] = None


# ---------------------------------------------------------------- family law
FAMILY_LAW_SECTIONS = [
    "Case basics", "Relationship / family history", "Current household", "Current parenting routine",
    "Historical caregiving", "Children's schooling", "Medical care", "Major parenting decisions",
    "Communication between parents", "Exchanges / transportation", "Work schedules", "Housing",
    "Finances relevant to family issues", "Support history", "Property / debts", "Specific safety concerns",
    "Specific incidents", "Other caregivers", "Court orders", "Court filings", "Service status",
    "Prior agreements", "Current requested arrangement", "Available records", "Witnesses", "Open questions",
]
# Default selection follows the Build Notes family-law path:
#   children and current arrangements -> existing orders and filed papers ->
#   service status -> income, expenses, and support -> relevant events and records,
# after the basics and before the requested arrangement (kept separate from facts).
# "Specific safety concerns" is NOT in the default: it is added only when the
# interviewee's own intake answer or account makes it relevant, and "Specific
# incidents" uses a neutral prompt that allows "none".
FAMILY_LAW_DEFAULT = ["Case basics", "Current household", "Current parenting routine", "Court orders",
                      "Court filings", "Service status", "Finances relevant to family issues",
                      "Support history", "Specific incidents", "Available records",
                      "Current requested arrangement"]

# ---------------------------------------------------------- criminal defense
# Procedural/paperwork intake first. A detailed account of the alleged conduct is
# NOT a required intake step; it is available only as an optional section.
CRIMINAL_DEFENSE_SECTIONS = [
    "Charges as shown on paperwork",
    "Court, case number, and next hearing",
    "Custody or release conditions",
    "Attorney or public defender status",
    "Procedural history",
    "Available records",
    "Witnesses",
    "Open questions",
    "Events in question (optional)",
]
CRIMINAL_DEFENSE_DEFAULT = CRIMINAL_DEFENSE_SECTIONS[:6]

CRIMINAL_DEFENSE_NOTICE = (
    "Before we start: Laylaw is not a lawyer, and using it does not create an attorney-client "
    "relationship. What you enter here is not protected by attorney-client privilege and could be "
    "requested by others in a legal case. If you have been charged or are under investigation, "
    "consider talking with a criminal defense attorney or public defender before recording details "
    "about the events themselves. This intake starts with your paperwork and court information."
)

SECTION_SPECS: dict[str, SectionSpec] = {
    "Charges as shown on paperwork": SectionSpec(
        "Charges as shown on paperwork",
        prompt=("What charges are listed on your paperwork? If you have it with you, please give them "
                "exactly as written."),
        kind="procedural", default_source=SourceOfKnowledge.DOCUMENT_RECOLLECTION,
        followups=(("basis", "Are you reading that from the paperwork, or going from memory?"),
                   ("paperwork_name", "What is the paperwork called, as shown at the top of it?"))),
    "Court, case number, and next hearing": SectionSpec(
        "Court, case number, and next hearing",
        prompt="Which court is your case in?",
        kind="procedural", default_source=SourceOfKnowledge.DOCUMENT_RECOLLECTION,
        followups=(("case_number", "What is the case number, as shown on your paperwork?"),
                   ("next_hearing", "When is your next hearing, and what is it called?"))),
    "Custody or release conditions": SectionSpec(
        "Custody or release conditions",
        prompt="Are you in custody right now, or released? If released, what conditions were you given?",
        kind="procedural",
        followups=(("conditions_source", "Where are those conditions written down, if anywhere?"),)),
    "Attorney or public defender status": SectionSpec(
        "Attorney or public defender status",
        prompt="Do you have a lawyer or public defender for this case right now?",
        kind="procedural",
        followups=(("counsel_contact", "Have you been able to speak with them yet?"),)),
    "Procedural history": SectionSpec(
        "Procedural history",
        prompt="What has happened in the case so far, in court or with paperwork, from the beginning?",
        kind="narrative"),
    "Available records": SectionSpec(
        "Available records",
        prompt="What paperwork, messages, or other records do you have that relate to this?",
        kind="records"),
    "Witnesses": SectionSpec(
        "Witnesses",
        prompt="Is there anyone who saw or heard any of this, or who might know about it?",
        kind="records"),
    "Events in question (optional)": SectionSpec(
        "Events in question (optional)",
        prompt=("Only if you choose to, and ideally after speaking with a lawyer: tell me what you "
                "remember about the events in question."),
        kind="narrative",
        optional_note="Optional. Not part of required intake."),
    "Current requested arrangement": SectionSpec(
        "Current requested arrangement", prompt="What would you like to happen going forward?", kind="request"),
    "Current household": SectionSpec(
        "Current household", prompt="Tell me about the children and the current living arrangements."),
    "Specific incidents": SectionSpec(
        "Specific incidents",
        prompt=("Are there particular events that matter for this case? If so, tell me about them from the "
                "beginning. It's fine to say there aren't any.")),
    "Current parenting routine": SectionSpec(
        "Current parenting routine", prompt="Tell me what normally happens with the current parenting routine.",
        kind="routine"),
}

PATHS = {
    "family_law": {"sections": FAMILY_LAW_SECTIONS, "default": FAMILY_LAW_DEFAULT, "notice": None,
                   "preflight": ["confirm_workspace", "danger", "urgent", "deadline", "help_first"]},
    "criminal_defense": {"sections": CRIMINAL_DEFENSE_SECTIONS, "default": CRIMINAL_DEFENSE_DEFAULT,
                         "notice": CRIMINAL_DEFENSE_NOTICE,
                         "preflight": ["confirm_workspace", "danger", "urgent", "deadline", "help_first",
                                       "custody", "counsel"]},
}

PREFLIGHT_QUESTIONS = {
    # Build Notes: "Choose the client and case type; confirm whose workspace is open."
    "confirm_workspace": "Just to confirm before we begin: this interview is for {interviewee} (case {case_id}). "
                         "Is that right?",
    # Immediate danger is asked on its own, so a plain "yes" can only mean danger.
    "danger": "Is anyone in immediate danger right now?",
    "urgent": "Is there another urgent concern we should know about before we start?",
    "deadline": "Is there a court hearing or other deadline coming up? If so, when?",
    "help_first": "What do you need help with first?",
    "custody": "Are you currently in custody, or out of custody?",
    "counsel": "Do you currently have a lawyer or public defender?",
}

# Neutral keyword hints used only to SUGGEST sections from the interviewee's own
# intake words. Suggestions are never auto-added; a person confirms them.
_SUGGEST = {
    "Children's schooling": r"school|teacher|class",
    "Medical care": r"doctor|medical|medicine|therap|hospital",
    "Exchanges / transportation": r"exchange|pick ?up|drop ?off|drive|transport",
    "Communication between parents": r"text|message|email|talk|communicat",
    "Support history": r"support|payment",
    "Housing": r"hous|apartment|move|moving|rent",
    "Specific incidents": r"incident|happened|event|fight|argument",
    "Specific safety concerns": r"safe|danger|threat|hurt",
    "Court filings": r"filed|filing|petition|motion|response",
    "Service status": r"served|service",
    "Work schedules": r"work|shift|job|schedule",
}


def spec_for(section: str) -> SectionSpec:
    return SECTION_SPECS.get(section, SectionSpec(section))


def available_sections(path_name: str) -> list[str]:
    """The full canonical set for a path (unchanged, for reference and selection)."""
    return list(PATHS[path_name]["sections"])


def default_sections(path_name: str) -> list[str]:
    return list(PATHS[path_name]["default"])


def validate_sections(path_name: str, sections: list[str]) -> list[str]:
    allowed = PATHS[path_name]["sections"]
    unknown = [x for x in sections if x not in allowed]
    if unknown:
        raise ValueError(f"not sections of {path_name}: {unknown}")
    return list(dict.fromkeys(sections))


def suggest_sections(path_name: str, intake_text: str) -> list[str]:
    """Suggest (never impose) extra sections based on the interviewee's own words."""
    import re
    allowed = PATHS[path_name]["sections"]
    return [name for name, pat in _SUGGEST.items()
            if name in allowed and re.search(pat, intake_text or "", re.IGNORECASE)]


def start_path(path_name: str, workspace, *, case_id: str, interviewee: str, interviewer: str,
               purpose: str, interviewee_is_adult: bool, sections: list[str] | None = None,
               preflight: bool = True,
               transcript_status: TranscriptStatus = TranscriptStatus.STRUCTURED_NOTES):
    """Returns (session, notice_or_None). With no `sections`, the path's short
    default selection is used -- never the whole canonical list."""
    from .session import InterviewSession

    cfg = PATHS[path_name]
    chosen = validate_sections(path_name, sections if sections is not None else cfg["default"])
    session = InterviewSession.start(
        workspace, case_id=case_id, interviewee=interviewee, interviewer=interviewer, purpose=purpose,
        sections=chosen, interviewee_is_adult=interviewee_is_adult,
        transcript_status=transcript_status, path_name=path_name,
        preflight=cfg["preflight"] if preflight else None)
    return session, cfg["notice"]
