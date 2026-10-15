"""Rapid Criminal & Supervision Intake: the questions, one at a time.

Built from Soul's 2026-10-15 handoff ("NEEDS CLAUDE CODE — APPROVED
IMPLEMENTATION HANDOFF") and its addenda in the Laylaw Build Notes.

Ground rules, enforced here and in supervision_outputs.py:

* What this is about defaults to "I'm not sure". Laylaw never infers state
  parole, probation, PRCS or anything else from other answers.
* The treatment branch asks WHO said treatment is required, HOW it was given
  (signed order, written condition, referral, verbal, proposal) and WHAT the
  paper says, word for word, kept apart from what the person remembers being
  told. A verbal instruction is never shown as an order, and "treatment" is
  never shown as "residential".
* Outpatient, IOP and similar options are recorded as discussed or not, and
  approval is a separate question. Being available is not being approved.
* No question asks for an account of alleged conduct. Charges are copied from
  the paperwork if the person has it.
* Every question can be answered "I'm not sure" or skipped. Adults only.

Two stages like the housing intake: the first five minutes (safety, the next
date, who said treatment is required and what the paper says, files, what the
person hopes to change), then detail only where it applies.
"""
from __future__ import annotations

from typing import Callable

from .steps import YES_NO_UNSURE, Step

EVIDENCE_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("court_order", "Court order"),
    ("conditions", "Supervision or release conditions"),
    ("referral", "Referral or assessment"),
    ("notice", "Notice of a date, hearing or report"),
    ("messages", "Letters, texts or emails"),
    ("program", "Program acceptance or schedule"),
    ("charging", "Charging paper or citation"),
    ("other", "Something else"),
)

SAFETY_MESSAGE = ("If anyone is in danger right now, call 911. For a mental health or substance use crisis you "
                  "can call or text 988. You can keep going when you're ready.")


def _in(step_id: str, *values: str) -> Callable[[dict], bool]:
    return lambda a: a.get(step_id) in values


def _has(step_id: str, *values: str) -> Callable[[dict], bool]:
    """For choose-all-that-apply answers, stored as "a,b,c"."""
    return lambda a: bool(set((a.get(step_id) or "").split(",")) & set(values))


def _all(*conds: Callable[[dict], bool]) -> Callable[[dict], bool]:
    return lambda a: all(c(a) for c in conds)


def _any(*conds: Callable[[dict], bool]) -> Callable[[dict], bool]:
    return lambda a: any(c(a) for c in conds)


# Nothing past the adult check is asked if the person this is about is under 18.
ADULT = lambda a: a.get("about_adult") != "no"  # noqa: E731
TREATMENT = _all(ADULT, _in("rehab_said", "yes", "not_sure"))
WRITTEN_OR_UNSURE = _all(TREATMENT, _in("rehab_form", "signed_order", "written_condition", "referral", "not_sure"))
CRIMINAL = _all(ADULT, _any(_in("matter_type", "criminal", "both"), _in("criminal_case", "yes")))
# A skipped "What is this about?" carries no value; it is treated as "I'm not sure", never as "no supervision".
SUPERVISION = _all(ADULT, _in("matter_type", "supervision", "both", "not_sure", None))
NOT_YET_CRIMINAL = _all(ADULT, _in("matter_type", "supervision", "not_sure", None))

NONRES_OPTIONS = (
    ("outpatient", "Outpatient treatment"),
    ("iop", "Intensive outpatient (IOP)"),
    ("day_reporting", "Day reporting"),
    ("recovery", "Recovery support or meetings"),
    ("mat", "Medication-assisted treatment"),
    ("telehealth", "Telehealth"),
    ("other", "Something else"),
)
NONRES_KEYS = tuple(k for k, _ in NONRES_OPTIONS)

STEPS: tuple[Step, ...] = (
    # ---- Stage 1: the first five minutes --------------------------------------------
    Step("danger_now", "First, is anyone in immediate danger right now?", "choice", choices=YES_NO_UNSURE,
         section="Safety", stage=1, help="If the answer is yes, you'll see who you can contact. You can keep "
                                         "going afterwards."),
    Step("about_adult", "Is the person this intake is about 18 or older?", "choice", choices=YES_NO_UNSURE,
         section="Safety", stage=1, help="Laylaw is for adults. If the person is under 18, nothing more is asked."),
    Step("filled_by", "Who is filling this out?", "choice", section="Safety", stage=1, when=ADULT,
         choices=(("self", "The person it's about"), ("helper", "Someone helping them"),
                  ("not_sure", "I'm not sure"))),
    Step("matter_type", "What is this about?", "choice", section="The essentials", stage=1, when=ADULT,
         default="not_sure",
         choices=(("criminal", "Criminal charges"), ("supervision", "Parole, probation or other supervision"),
                  ("both", "Both"), ("not_sure", "I'm not sure")),
         help="If you're not sure, that's fine. Laylaw won't guess."),
    Step("held_now", "Is the person in custody or being held right now?", "choice", choices=YES_NO_UNSURE,
         section="The essentials", stage=1, when=ADULT),
    Step("deadline_date", "What's the next date something has to happen? For example reporting in, starting a "
                          "program, a court date, or a reply.", "date", section="The next date", stage=1,
         when=ADULT, help="If there's no date, or you only know roughly, choose \"I'm not sure\"."),
    Step("deadline_rough", "Roughly when is it, or was no date given?", "text", section="The next date", stage=1,
         max_len=120, when=_all(ADULT, _in("deadline_date", "not_sure")),
         example="For example: \"sometime next week\" or \"no date was given\""),
    Step("deadline_what", "What has to happen by then?", "choice", section="The next date", stage=1, when=ADULT,
         choices=(("report", "Report or check in"), ("enroll", "Start or enter a program"),
                  ("court", "A court date"), ("reply", "Reply or turn something in"),
                  ("other", "Something else"), ("not_sure", "I'm not sure"))),
    Step("deadline_source", "Where does that date come from?", "choice", section="The next date", stage=1,
         when=ADULT,
         choices=(("paper", "It's on paperwork"), ("officer", "A parole or probation officer said it"),
                  ("court", "The court said it"), ("program", "A program or provider said it"),
                  ("other", "Someone else"), ("not_sure", "I'm not sure"))),
    Step("deadline_consequence", "Did anyone say what happens if it's missed? Only write what was actually said.",
         "text", section="The next date", stage=1, max_len=300, when=ADULT,
         example="For example: \"nothing was said\""),
    Step("rehab_said", "Has anyone said treatment or rehab is required?", "choice", choices=YES_NO_UNSURE,
         section="Treatment", stage=1, when=ADULT),
    Step("rehab_who", "Who said treatment or rehab is required?", "choice", section="Treatment", stage=1,
         when=TREATMENT,
         choices=(("court", "A court or judge"), ("parole", "Parole, the parole board, or CDCR"),
                  ("probation", "County probation or post-release supervision (PRCS)"),
                  ("program", "A treatment program or provider"), ("other", "Someone else"),
                  ("not_sure", "I'm not sure")),
         help="Pick who actually said it, even if you're not sure what kind of supervision this is."),
    Step("rehab_form", "How was it given?", "choice", section="Treatment", stage=1, when=TREATMENT,
         choices=(("signed_order", "A signed court order"), ("written_condition", "A written supervision condition"),
                  ("referral", "A referral or assessment"), ("verbal", "Someone said it; nothing written"),
                  ("proposal", "It was suggested or proposed"), ("not_sure", "I'm not sure")),
         help="Laylaw keeps this exactly as you choose it."),
    Step("rehab_doc_words", "If you have the paper, what does it say about treatment? Copy the exact words.",
         "long", section="Treatment", stage=1, max_len=600, when=WRITTEN_OR_UNSURE,
         help="Word for word, from the paper. If you don't have it in front of you, skip this. You can add the "
              "file itself in a moment.",
         example="For example: \"Defendant shall enroll in and complete a treatment program as directed.\""),
    Step("rehab_recollection", "In your own words, what were you told?", "long", section="Treatment", stage=1,
         max_len=600, when=TREATMENT, help="This is kept separately from what the paper says."),
    Step("rehab_level", "Does the paper or message say residential, inpatient or live-in, or only treatment or a "
                        "program?", "choice", section="Treatment", stage=1, when=TREATMENT,
         choices=(("residential", "It says residential, inpatient or live-in"),
                  ("generic", "It only says treatment or a program"),
                  ("nothing_written", "Nothing is written down"), ("not_sure", "I'm not sure"))),
    Step("first_files", "Do you have any paperwork or messages about this?", "upload", section="Files", stage=1,
         when=ADULT,
         help="Add what you have, or skip. Files are stored encrypted on this computer and kept exactly as they "
              "are. Nothing about what happened in the case itself is needed."),
    Step("hoping_for", "What are you hoping to change or get clarified?", "text", section="What you want", stage=1,
         max_len=500, when=ADULT, help="This is kept apart from the facts.",
         example="For example: \"whether an outpatient program could be considered\""),
    Step("stage_gate", "The essentials are saved. Would you like to add more detail now?", "choice",
         section="The essentials", stage=1, when=ADULT,
         choices=(("now", "Yes, keep going"), ("later", "Not now, I'll come back")),
         help="More detail helps whoever reviews this. It takes about 10 minutes."),

    # ---- Stage 2: only what applies --------------------------------------------------
    Step("criminal_case", "Is there an open criminal case with charges right now?", "choice",
         choices=YES_NO_UNSURE, section="Court case", when=NOT_YET_CRIMINAL),
    Step("charge_text", "What charge is listed on the paperwork? Copy it as written.", "text", section="Court case",
         max_len=300, when=CRIMINAL,
         help="Only what the paper says. You don't need to describe what happened. Skip this if you don't "
              "have the paper."),
    Step("court_county", "Which court or county is the case in?", "text", section="Court case", max_len=120,
         when=CRIMINAL, example="For example: \"San Diego Superior Court, Vista\""),
    Step("case_ref", "Case or citation number (optional)", "text", section="Court case", max_len=60,
         when=CRIMINAL, help="Optional. It's stored only in the encrypted vault on this computer.",
         tags=frozenset({"identifier"})),
    Step("arrest_date", "When was the arrest or citation?", "date", section="Court case", when=CRIMINAL),
    Step("next_appearance", "When is the next court date?", "date", section="Court case", when=CRIMINAL),
    Step("release_status", "What is the person's release status?", "choice", section="Court case", when=CRIMINAL,
         choices=(("custody", "In custody"), ("released", "Released, no bail"), ("bail", "Released on bail"),
                  ("conditions", "Released with conditions"), ("not_sure", "I'm not sure"))),
    Step("counsel", "Does the person have a lawyer for the case?", "choice", section="Court case", when=CRIMINAL,
         choices=(("public_defender", "A public defender"), ("private", "A private lawyer"),
                  ("none", "No lawyer yet"), ("not_sure", "I'm not sure"))),
    Step("supervision_kinds", "Which kind of supervision is involved?", "multi", section="Supervision",
         when=SUPERVISION,
         choices=(("state_parole", "California state parole"), ("probation", "County probation"),
                  ("prcs", "Post-release community supervision (PRCS)"), ("mandatory", "Mandatory supervision"),
                  ("pretrial", "Pretrial release, diversion, or a treatment court"),
                  ("federal", "Federal supervision"), ("other", "Something else"), ("not_sure", "I'm not sure")),
         help="If you're not sure, choose that. Laylaw won't guess from your other answers."),
    Step("supervision_on_paper", "Does any paperwork say which kind of supervision it is?", "choice",
         choices=YES_NO_UNSURE, section="Supervision", when=SUPERVISION),
    Step("led_to", "What led to treatment coming up? A short phrase is enough.", "text", section="Treatment detail",
         max_len=200, when=TREATMENT,
         help="You don't need to describe any alleged conduct.",
         example="For example: \"a new assessment\" or \"a missed check-in\""),
    Step("assessment", "Is there a written assessment that names a level of care?", "choice",
         choices=YES_NO_UNSURE, section="Treatment detail", when=TREATMENT,
         help="Only whether it exists. No medical details are needed."),
    Step("assessment_words", "What level of care does it name, as written?", "text", section="Treatment detail",
         max_len=200, when=_all(TREATMENT, _in("assessment", "yes"))),
    Step("nonres_discussed", "Has anyone discussed any of these?", "multi", section="Treatment detail",
         when=TREATMENT,
         choices=NONRES_OPTIONS + (("none", "None of these have been discussed"), ("not_sure", "I'm not sure")),
         help="This records what was discussed, not what's allowed."),
    Step("nonres_approval", "Has anyone with authority approved one of these instead, in writing?", "choice",
         section="Treatment detail", when=_all(TREATMENT, _has("nonres_discussed", *NONRES_KEYS)),
         choices=(("written", "Yes, in writing"), ("verbal", "Someone said yes, but not in writing"),
                  ("mentioned", "It was only mentioned"), ("no", "No"), ("not_sure", "I'm not sure"))),
    Step("nonres_who", "Who approved it, and when?", "text", section="Treatment detail", max_len=200,
         when=_all(TREATMENT, _has("nonres_discussed", *NONRES_KEYS), _in("nonres_approval", "written", "verbal"))),
    Step("supports", "Is there anything that affects what kind of program would be workable?", "multi",
         section="Treatment detail", when=TREATMENT,
         choices=(("transport", "Transportation"), ("housing", "Stable housing"), ("work", "A job"),
                  ("caregiving", "Caring for someone"), ("program_accepted", "Already accepted into a program"),
                  ("accommodation", "A disability accommodation"), ("none", "None of these"),
                  ("not_sure", "I'm not sure")),
         help="Optional. No details are needed here."),
    Step("hold", "Is there a hold, warrant, violation report, or hearing about this right now?", "choice",
         choices=YES_NO_UNSURE, section="Status", when=ADULT,
         help="Laylaw records what you know. It doesn't decide what any of it means."),
    Step("hold_on_paper", "Is that on paperwork, or something you were told?", "choice", section="Status",
         when=_all(ADULT, _in("hold", "yes")),
         choices=(("paper", "It's on paperwork"), ("told", "I was told"), ("not_sure", "I'm not sure"))),
    Step("unresolved", "Is there anything you're unsure about, or want a reviewer to know?", "long",
         section="Anything else", max_len=2000, when=ADULT),
)

STEP_BY_ID = {s.id: s for s in STEPS}
