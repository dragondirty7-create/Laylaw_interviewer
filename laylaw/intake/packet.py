"""Referral packet: a neutral summary for a licensed lawyer to read.

Contents: the facts as given (each labelled with what it rests on), the
chronology, the evidence index, open questions, and a short list of topics for
counsel to evaluate. The topics are questions, never answers: no conclusion
that anything was unlawful, no damages, no criminal labels, no advice.

Text Laylaw writes itself is checked by the Interviewer's advocacy guard and a
list of conclusion words before the packet is returned. The person's own words
are quoted as theirs and are not altered.
"""
from __future__ import annotations

import re

from ..interviewer.guard import find_advocacy
from .chronology import BASIS_LABELS, chronology, evidence_inventory, open_questions
from .model import AnswerStatus, IncidentIntake
from .steps import STEP_BY_ID

#: Words Laylaw must never write on its own in a packet. The person may use them; Laylaw may not.
CONCLUSION_WORDS = re.compile(
    r"\b(?:violat\w*|illegal\w*|unlawful\w*|trespass\w*|liab\w*|damages|negligen\w*|criminal\w*|crime\w*|"
    r"guilty|fault|harass\w*|abus\w*|assault\w*|invasion of privacy|you should|you must|you have a case)\b",
    re.IGNORECASE,
)

HEADER = ("This packet was put together with Laylaw, an organizing tool. It does not give advice about the "
          "law and is not a legal opinion. Everything in it comes from what the person filling it out entered. Laylaw has not "
          "checked any of it, and files are listed by the details entered for them; their contents have not "
          "been reviewed.")

FACT_ORDER = ("summary", "incident_date", "incident_time", "location", "reporting_adult", "people_present",
              "child_present", "child_age_range", "child_situation", "entrant", "entry_method",
              "entry_method_other", "notice_given", "notice_details", "consent_given", "emergency_claimed",
              "emergency_details", "open_request", "open_request_details", "witnesses", "contacted")


class PacketError(RuntimeError):
    """Laylaw's own text in the packet tripped a guard. Nothing is produced."""


def _shown(intake: IncidentIntake, step_id: str) -> str | None:
    a = intake.answers.get(step_id)
    if a is None:
        return None
    if a.status == AnswerStatus.NOT_SURE:
        return "Not sure"
    if a.status == AnswerStatus.SKIPPED:
        return "Skipped"
    step = STEP_BY_ID[step_id]
    if step.kind == "choice":
        return dict(step.choices).get(a.value or "", a.value)
    return a.value


def counsel_topics(intake: IncidentIntake) -> list[str]:
    v = intake.plain_answers()
    topics = ["What should be kept, and how, so nothing is lost (for example messages, entry logs and any "
              "doorbell or security video)."]
    if v.get("notice_given") in ("no", "not_sure"):
        topics.append("Whether notice was given before the entry, and what notice applies to this home.")
    if v.get("consent_given") in ("no", "not_sure"):
        topics.append("Whether anyone gave permission for the entry.")
    if v.get("emergency_claimed") == "yes":
        topics.append("How the reason given for entering (an emergency was mentioned) bears on the situation.")
    if v.get("open_request") in ("yes", "not_sure"):
        topics.append("How the open repair or maintenance request relates to the entry.")
    if v.get("child_present") == "yes":
        topics.append("How information about the child should be protected, and who it may be shared with.")
    topics.append("How to communicate with the property manager or landlord from here.")
    topics.append("Whether to contact any agency, and which one.")
    return topics


def build_packet(intake: IncidentIntake) -> dict:
    """Return the packet as structured sections plus a plain-text rendering."""
    facts = [(STEP_BY_ID[sid].prompt, _shown(intake, sid)) for sid in FACT_ORDER if _shown(intake, sid)]
    if intake.child_statement:
        heard = intake.value("child_words_heard_by") or "Not given"
        facts.append(("The child's own words, recorded once, exactly as entered",
                      f"“{intake.child_statement['words']}” (heard by / when: {heard})"))
    rows = chronology(intake)
    inventory = evidence_inventory(intake)
    questions = open_questions(intake)
    topics = counsel_topics(intake)

    authored = [HEADER, *topics, *BASIS_LABELS.values(), *(p for p, _ in facts)]
    for text in authored:
        if find_advocacy(text) or CONCLUSION_WORDS.search(text):
            raise PacketError("Laylaw's own wording in the packet failed a neutrality check.")

    lines = ["REFERRAL PACKET (organizing summary only)"]
    if intake.synthetic:
        lines.append("SYNTHETIC TEST DATA: NOT A REAL MATTER")
    lines += ["", HEADER, "", f"Matter: {intake.nickname or 'Incident intake'} ({intake.matter_id})",
              f"Prepared from entries last updated {intake.updated_at} (UTC)", "", "FACTS AS GIVEN (all: the person said)"]
    lines += [f"- {q}\n  {a}" for q, a in facts] or ["- None yet."]
    lines += ["", "CHRONOLOGY"]
    for r in rows:
        when_note = "" if r.when_basis == r.basis else f" [time: {BASIS_LABELS[r.when_basis].lower()}]"
        lines.append(f"- {r.when}{when_note}: {r.what} [{BASIS_LABELS[r.basis]}]")
    lines += ["", "EVIDENCE INDEX"]
    lines += [f"- {i['file']} | {i['kind']} | from: {i['source']} | dated: {i['date']} | {i['original']} | "
              f"SHA-256 {i['sha256']}" + (f" | notes: {i['notes']}" if i["notes"] else "") for i in inventory] \
        or ["- No files added."]
    lines += ["", "OPEN QUESTIONS"] + ([f"- {q}" for q in questions] or ["- None."])
    lines += ["", "TOPICS FOR A LICENSED LAWYER TO EVALUATE"] + [f"- {t}" for t in topics]
    return {"facts": facts, "chronology": rows, "evidence": inventory, "open_questions": questions,
            "counsel_topics": topics, "header": HEADER, "text": "\n".join(lines)}
