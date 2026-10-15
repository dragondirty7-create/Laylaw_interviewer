"""Outputs for the Rapid Criminal & Supervision Intake.

Every value says what it rests on:

  CLIENT REPORTED      the person filling this out said it
  DOCUMENT STATES      wording the person copied from a paper, typed in. Laylaw
                       does not read uploaded files, so this is what they typed.
  OFFICIALLY VERIFIED  confirmed with the issuing court or agency. Laylaw never
                       sets this itself; nothing in an intake is officially verified.
  CONFLICT             two things the person provided point different ways; both kept
  UNKNOWN              not known, not sure, skipped, or not asked yet

Artifacts: Rapid Situation Summary, Evidence & Orders Inventory, Time-Sensitive
Dates, Requirement Source Map, Nonresidential Options Comparison, Open
Questions, Chronology, and topics for a reviewer. None of it says what the law
allows, whether anyone qualifies for anything, or what anyone should do.
Laylaw's own wording is checked by the Interviewer's advocacy guard and a list
of conclusion words before anything is returned.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..interviewer.guard import find_advocacy
from .model import AnswerStatus, IncidentIntake
from .packet import PacketError as HousingPacketError
from .supervision_steps import NONRES_KEYS, NONRES_OPTIONS

CLIENT_REPORTED = "CLIENT_REPORTED"
DOCUMENT_STATES = "DOCUMENT_STATES"
OFFICIALLY_VERIFIED = "OFFICIALLY_VERIFIED"
CONFLICT = "CONFLICT"
UNKNOWN = "UNKNOWN"

BASIS_LABELS = {
    CLIENT_REPORTED: "CLIENT REPORTED",
    DOCUMENT_STATES: "DOCUMENT STATES (as typed in)",
    OFFICIALLY_VERIFIED: "OFFICIALLY VERIFIED",
    CONFLICT: "CONFLICT",
    UNKNOWN: "UNKNOWN",
}

HEADER = ("Put together with Laylaw, an organizing tool. It does not give advice about the law, is not a legal "
          "opinion, and is not representation. Everything here comes from what the person filling it out entered. Nothing has been "
          "confirmed with any court or agency, and uploaded files are listed by the details entered for them; "
          "their contents have not been read.")

NONRES_CAVEAT = ("Being available or discussed is not the same as being approved in place of a written "
                 "requirement. Laylaw has not confirmed any approval.")

ADULT_STOP = "Stopped: the person this is about was reported as under 18. Laylaw is for adults; nothing more was asked."

#: Words Laylaw must never write on its own. The person may use them; Laylaw may not.
CONCLUSION_WORDS = re.compile(
    r"\b(?:violat(?!ion report)\w*|illegal\w*|unlawful\w*|guilty|innocent|eligib\w*|ineligib\w*|qualif\w*|exempt\w*|"
    r"waiv\w*|entitle\w*|liab\w*|you should|you must|must not|you have a case|will be approved|"
    r"can refuse|can't refuse|cannot refuse|substitute[sd]? for|satisf(?:y|ies|ied) the|dismiss\w*|"
    r"probation violation|parole violation|recommend\w*)\b",
    re.IGNORECASE,
)

#: Wording that names residential care, used only to point out a mismatch between two things the person entered.
RESIDENTIAL_WORDS = re.compile(r"\b(?:residential|in-?patient|live-?in|sober living|in-?house)\b", re.IGNORECASE)


class PacketError(HousingPacketError):
    """Laylaw's own wording tripped a neutrality check. Nothing is produced."""


@dataclass(frozen=True)
class Item:
    label: str
    value: str
    basis: str


# -- reading answers -----------------------------------------------------------------
def _answer(intake: IncidentIntake, sid: str):
    return intake.answers.get(sid)


def shown(intake: IncidentIntake, sid: str) -> tuple[str, str]:
    """(display text, basis) for one answer. Choices are shown with their exact label, never upgraded."""
    a = _answer(intake, sid)
    step = intake.step_by_id[sid]
    applies = step in intake.applicable_steps()
    if a is None or not applies:
        if step.default == "not_sure" and applies:
            return "Not sure (nothing chosen yet)", UNKNOWN
        return ("Not answered yet" if applies else "Not asked"), UNKNOWN
    if a.status == AnswerStatus.NOT_SURE:
        return "Not sure", UNKNOWN
    if a.status == AnswerStatus.SKIPPED:
        return ("Not sure (skipped)" if step.default == "not_sure" else "Skipped"), UNKNOWN
    labels = dict(step.choices)
    if step.kind == "choice":
        return labels.get(a.value or "", a.value or ""), CLIENT_REPORTED
    if step.kind == "multi":
        return "; ".join(labels.get(v, v) for v in (a.value or "").split(",") if v), CLIENT_REPORTED
    return a.value or "", CLIENT_REPORTED


def _v(intake: IncidentIntake, sid: str) -> str | None:
    return intake.value(sid) if intake.step_by_id[sid] in intake.applicable_steps() else None


def _multi(intake: IncidentIntake, sid: str) -> set[str]:
    return set((_v(intake, sid) or "").split(",")) - {""}


def stopped_under_18(intake: IncidentIntake) -> bool:
    return intake.value("about_adult") == "no"


def _cats(intake: IncidentIntake) -> set[str]:
    return {e.category for e in intake.evidence}


# -- conflicts and open questions --------------------------------------------------------
def conflicts(intake: IncidentIntake) -> list[str]:
    """Places where two things the person provided point different ways. Both are kept; neither is chosen."""
    out: list[str] = []
    words, level, form = _v(intake, "rehab_doc_words"), _v(intake, "rehab_level"), _v(intake, "rehab_form")
    if words and level == "residential" and not RESIDENTIAL_WORDS.search(words):
        out.append("The paper was described as saying residential, inpatient or live-in, but the words copied from "
                   "it don't include those words. Both are kept as given.")
    if words and level == "generic" and RESIDENTIAL_WORDS.search(words):
        out.append("The paper was described as saying only treatment or a program, but the words copied from it "
                   "mention residential, inpatient or live-in care. Both are kept as given.")
    if words and level == "nothing_written":
        out.append("It was described as not written down, and wording from a paper was also entered. Both are "
                   "kept as given.")
    cats = _cats(intake)
    if form in ("verbal", "proposal") and cats & {"court_order", "conditions"}:
        how = "spoken only" if form == "verbal" else "suggested or proposed"
        out.append(f"The treatment requirement was described as {how}, and a file was added as a court order or "
                   f"written conditions. Both are kept as given.")
    kinds = _multi(intake, "supervision_kinds")
    if "state_parole" in kinds and kinds & {"probation", "prcs", "mandatory"}:
        out.append("State parole and a county form of supervision were both chosen. These are run by different "
                   "agencies (state and county), so which applies needs confirming from paperwork. Both are kept.")
    who = _v(intake, "rehab_who")
    if who == "parole" and kinds and not kinds & {"state_parole", "not_sure"} and kinds & {"probation", "prcs",
                                                                                          "mandatory"}:
        out.append("Treatment was said to come from parole or CDCR, but the supervision chosen is county "
                   "supervision only. Both are kept as given.")
    if who == "probation" and kinds == {"state_parole"}:
        out.append("Treatment was said to come from county probation or PRCS, but the supervision chosen is state "
                   "parole only. Both are kept as given.")
    if _v(intake, "matter_type") == "criminal" and _v(intake, "rehab_who") in ("parole", "probation"):
        out.append("This was described as criminal charges only, and treatment was said to come from a "
                   "supervising agency. Both are kept as given.")
    return out


def open_questions(intake: IncidentIntake) -> list[str]:
    if stopped_under_18(intake):
        return [ADULT_STOP]
    out: list[str] = []
    for step in intake.applicable_steps():
        if step.kind == "upload" or step.id == "stage_gate":
            continue
        a = intake.answers.get(step.id)
        if a is None:
            out.append(f"Not answered yet: {step.prompt}")
        elif a.status == AnswerStatus.NOT_SURE:
            out.append(f"Not sure: {step.prompt}")
        elif a.status == AnswerStatus.SKIPPED:
            out.append(f"Skipped: {step.prompt}")
    cats = _cats(intake)
    if _v(intake, "deadline_source") == "paper" and not cats & {"notice", "court_order", "conditions", "messages"}:
        out.append("The next date was described as being on paperwork; no copy has been added yet.")
    if _v(intake, "rehab_form") in ("signed_order", "written_condition", "referral") and not _v(intake, "rehab_doc_words"):
        out.append("The requirement was described as written; its exact wording hasn't been entered yet.")
    if _v(intake, "nonres_approval") == "written" and not cats & {"program", "messages", "court_order", "conditions"}:
        out.append("An approval was described as in writing; no copy has been added yet.")
    if _v(intake, "hold_on_paper") == "paper" and not intake.evidence:
        out.append("The hold, warrant, report or hearing was described as on paperwork; no copy has been added yet.")
    flagged = _v(intake, "unresolved")
    if flagged:
        out.append(f"The person noted: {flagged}")
    return out + [f"Differs: {c}" for c in conflicts(intake)]


# -- artifacts ---------------------------------------------------------------------------
def deadline(intake: IncidentIntake) -> Item:
    exact, rough = _v(intake, "deadline_date"), _v(intake, "deadline_rough")
    if exact:
        return Item("Next required date", f"{exact} (exact date as entered)", CLIENT_REPORTED)
    if rough:
        return Item("Next required date", f"{rough} (approximate, in the person's words)", CLIENT_REPORTED)
    return Item("Next required date", "Not known", UNKNOWN)


def time_sensitive_dates(intake: IncidentIntake) -> list[dict]:
    if stopped_under_18(intake):
        return []
    d = deadline(intake)
    what, what_basis = shown(intake, "deadline_what")
    src, src_basis = shown(intake, "deadline_source")
    said, said_basis = shown(intake, "deadline_consequence")
    rows = [{"date": d.value, "what": what, "who_said": src, "if_missed": said,
             "basis": d.basis if d.basis == UNKNOWN else CLIENT_REPORTED,
             "precision": "exact" if _v(intake, "deadline_date") else ("approximate" if _v(intake, "deadline_rough")
                                                                         else "unknown")}]
    nxt = _v(intake, "next_appearance")
    if nxt:
        rows.append({"date": f"{nxt} (exact date as entered)", "what": "Next court date", "who_said": "Not given",
                     "if_missed": "Not asked", "basis": CLIENT_REPORTED, "precision": "exact"})
    return rows


def requirement_source_map(intake: IncidentIntake) -> list[Item]:
    if stopped_under_18(intake) or intake.plain_answers().get("rehab_said") not in ("yes", "not_sure"):
        said, basis = shown(intake, "rehab_said")
        return [Item("Has anyone said treatment is required", said, basis)]
    items = [Item("Has anyone said treatment is required", *shown(intake, "rehab_said")),
             Item("Who said it", *shown(intake, "rehab_who")),
             Item("How it was given", *shown(intake, "rehab_form"))]
    words = _v(intake, "rehab_doc_words")
    items.append(Item("What the paper says, word for word", f"“{words}”" if words else "Not entered",
                      DOCUMENT_STATES if words else UNKNOWN))
    items.append(Item("What the person remembers being told", *shown(intake, "rehab_recollection")))
    level, level_basis = shown(intake, "rehab_level")
    if any("residential, inpatient or live-in" in c or "only treatment or a program" in c
           or "not written down" in c for c in conflicts(intake)):
        level_basis = CONFLICT
    items.append(Item("Level of care named, as described", level, level_basis))
    if _v(intake, "assessment_words"):
        items.append(Item("Level of care named in a written assessment, as typed in",
                          f"“{_v(intake, 'assessment_words')}”", DOCUMENT_STATES))
    elif _answer(intake, "assessment") is not None:
        items.append(Item("Written assessment naming a level of care", *shown(intake, "assessment")))
    kinds_text, kinds_basis = shown(intake, "supervision_kinds")
    if any("supervision" in c and "Both are kept" in c for c in conflicts(intake)):
        kinds_basis = CONFLICT
    items.append(Item("Kind of supervision", kinds_text, kinds_basis))
    on_paper = [e for e in intake.evidence if e.category in ("court_order", "conditions", "referral")]
    items.append(Item("Files added as an order, conditions, or referral",
                      ", ".join(e.filename for e in on_paper) or "None yet",
                      CLIENT_REPORTED if on_paper else UNKNOWN))
    items.append(Item("Confirmed with the issuing court or agency", "No. Laylaw has not confirmed anything.", UNKNOWN))
    return items


def nonresidential_comparison(intake: IncidentIntake) -> list[dict]:
    discussed = _multi(intake, "nonres_discussed") & set(NONRES_KEYS)
    if not discussed:
        return []
    approval, approval_basis = shown(intake, "nonres_approval")
    who = _v(intake, "nonres_who")
    labels = dict(NONRES_OPTIONS)
    return [{"option": labels[k], "discussed": "Reported as discussed", "discussed_basis": CLIENT_REPORTED,
             "approval": approval + (f" ({who})" if who else ""), "approval_basis": approval_basis,
             "officially_verified": "No", "note": NONRES_CAVEAT}
            for k in NONRES_KEYS if k in discussed]


def evidence_inventory(intake: IncidentIntake) -> list[dict]:
    return [{
        "file": ev.filename, "kind": intake.category_label(ev.category), "source": ev.source or "Not given",
        "date": ev.date_text or "Not given",
        "original": "Original kept unchanged" if ev.original_preserved else "Changed",
        "sha256": ev.sha256, "size": ev.size, "notes": ev.notes, "added": ev.stored_at,
    } for ev in intake.evidence]


def chronology(intake: IncidentIntake) -> list[dict]:
    """Dated items only, in date order where the date is exact. Undated items are not placed."""
    rows: list[dict] = []
    for sid, what in (("arrest_date", "Arrest or citation"), ("deadline_date", "Next required date"),
                      ("next_appearance", "Next court date")):
        v = _v(intake, sid)
        if v:
            rows.append({"when": v, "what": what, "basis": CLIENT_REPORTED})
    rows.sort(key=lambda r: r["when"])
    rough = _v(intake, "deadline_rough")
    if rough:
        rows.append({"when": f"{rough} (approximate)", "what": "Next required date", "basis": CLIENT_REPORTED})
    for ev in intake.evidence:
        if ev.date_text:
            rows.append({"when": ev.date_text, "what": f"File: {intake.category_label(ev.category)} ({ev.filename})",
                         "basis": CLIENT_REPORTED})
    return rows


def situation_summary(intake: IncidentIntake) -> list[Item]:
    if stopped_under_18(intake):
        return [Item("Status", ADULT_STOP, CLIENT_REPORTED)]
    d = deadline(intake)
    return [
        Item("What this is about", *shown(intake, "matter_type")),
        Item("Immediate danger", *shown(intake, "danger_now")),
        Item("In custody or held now", *shown(intake, "held_now")),
        d,
        Item("What has to happen by then", *shown(intake, "deadline_what")),
        Item("Where the date comes from", *shown(intake, "deadline_source")),
        Item("Treatment said to be required", *shown(intake, "rehab_said")),
        Item("Who said it", *shown(intake, "rehab_who")),
        Item("How it was given", *shown(intake, "rehab_form")),
        Item("Level of care named, as described", *shown(intake, "rehab_level")),
        Item("Kind of supervision", *shown(intake, "supervision_kinds")),
        Item("Hold, warrant, violation report or hearing", *shown(intake, "hold")),
        Item("Files added", str(len(intake.evidence)), CLIENT_REPORTED),
    ]


def counsel_topics(intake: IncidentIntake) -> list[str]:
    """Questions for a reviewer. Never answers."""
    if stopped_under_18(intake):
        return []
    topics = ["Which court or agency issued any treatment requirement, and which document shows it."]
    if _v(intake, "rehab_level") != "residential" or not _v(intake, "rehab_doc_words"):
        topics.append("Whether the written requirement names a level of care, or only treatment.")
    if deadline(intake).basis != UNKNOWN or _v(intake, "next_appearance"):
        topics.append("What has to happen by the next date, and who to contact about it.")
    else:
        topics.append("Whether any date is coming up, and where it would be written down.")
    kinds = _multi(intake, "supervision_kinds")
    if not kinds or "not_sure" in kinds or any("supervision" in c for c in conflicts(intake)):
        topics.append("Which kind of supervision applies; the process differs by kind.")
    if _multi(intake, "nonres_discussed") & set(NONRES_KEYS):
        topics.append("Whether a request to consider a nonresidential option could be made through the proper "
                      "process, and who would decide it.")
    if _v(intake, "hold") in ("yes", "not_sure"):
        topics.append("The current status of the reported hold, warrant, violation report or hearing.")
    topics.append("Which paperwork to request or keep.")
    return topics


# -- the packet -------------------------------------------------------------------------
def _authored(intake: IncidentIntake, topics: list[str]) -> list[str]:
    from .supervision_steps import EVIDENCE_CATEGORIES, SAFETY_MESSAGE
    texts = [HEADER, NONRES_CAVEAT, ADULT_STOP, SAFETY_MESSAGE, *topics, *BASIS_LABELS.values()]
    for s in intake.steps:
        texts += [s.prompt, s.help, s.example, s.why, *(label for _, label in s.choices)]
    texts += [label for _, label in EVIDENCE_CATEGORIES]
    return [t for t in texts if t]


def check_neutral(texts: list[str]) -> None:
    for text in texts:
        if find_advocacy(text) or CONCLUSION_WORDS.search(text):
            raise PacketError("Laylaw's own wording failed a neutrality check.")


def build_packet(intake: IncidentIntake) -> dict:
    summary = situation_summary(intake)
    dates = time_sensitive_dates(intake)
    source_map = requirement_source_map(intake)
    options = nonresidential_comparison(intake)
    inventory = evidence_inventory(intake)
    questions = open_questions(intake)
    chron = chronology(intake)
    topics = counsel_topics(intake)
    check_neutral(_authored(intake, topics) + [c for c in conflicts(intake)])

    def tag(basis: str) -> str:
        return f"[{BASIS_LABELS[basis]}]"

    lines = ["RAPID SITUATION SUMMARY (organizing summary only)"]
    if intake.synthetic:
        lines.append("SYNTHETIC TEST DATA: NOT A REAL MATTER")
    lines += ["", HEADER, "", f"Matter: {intake.nickname or 'Criminal & supervision intake'} ({intake.matter_id})",
              f"Prepared from entries last updated {intake.updated_at} (UTC)", ""]
    lines += [f"- {i.label}: {i.value} {tag(i.basis)}" for i in summary]
    hope = _v(intake, "hoping_for")
    lines += ["", "WHAT THE PERSON HOPES TO CHANGE OR CLARIFY (kept apart from the facts)",
              f"- {hope} {tag(CLIENT_REPORTED)}" if hope else "- Not given."]
    lines += ["", "TIME-SENSITIVE DATES"]
    lines += [f"- {r['date']} | {r['what']} | from: {r['who_said']} | if missed, what was said: {r['if_missed']} | "
              f"precision: {r['precision']} {tag(r['basis'])}" for r in dates] or ["- None given."]
    lines += ["", "REQUIREMENT SOURCE MAP"] + [f"- {i.label}: {i.value} {tag(i.basis)}" for i in source_map]
    lines += ["", "NONRESIDENTIAL OPTIONS COMPARISON"]
    if options:
        lines += [f"- {o['option']}: {o['discussed']} {tag(o['discussed_basis'])}; approval: {o['approval']} "
                  f"{tag(o['approval_basis'])}; officially verified: {o['officially_verified']}" for o in options]
        lines.append(f"  Note: {NONRES_CAVEAT}")
    else:
        lines.append("- None reported as discussed.")
    lines += ["", "EVIDENCE & ORDERS INVENTORY"]
    lines += [f"- {i['file']} | {i['kind']} | from: {i['source']} | dated: {i['date']} | {i['original']} | "
              f"SHA-256 {i['sha256']}" + (f" | notes: {i['notes']}" if i["notes"] else "") for i in inventory] \
        or ["- No files added."]
    lines += ["", "CHRONOLOGY (dated items only)"]
    lines += [f"- {r['when']}: {r['what']} {tag(r['basis'])}" for r in chron] or ["- No dates given."]
    lines += ["", "OPEN QUESTIONS"] + ([f"- {q}" for q in questions] or ["- None."])
    lines += ["", "TOPICS FOR A REVIEWER (questions, not answers)"] + ([f"- {t}" for t in topics] or ["- None."])
    return {"summary": summary, "dates": dates, "source_map": source_map, "options": options,
            "evidence": inventory, "chronology": chron, "open_questions": questions, "counsel_topics": topics,
            "conflicts": conflicts(intake), "header": HEADER, "text": "\n".join(lines)}
