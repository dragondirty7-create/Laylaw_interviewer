"""The Rapid Incident Intake questions, one at a time, in plain language.

Two stages, per Soul's 2026-10-08 addendum: a light first pass (danger, what
happened, when, who came in, notice, consent, any files), then deeper questions
only once the essentials are saved. Danger is asked first rather than fifth, so
the safety prompt appears before anything else.

Facts first: nothing here asks the person to classify a legal issue. Every
question can be answered "I'm not sure" or skipped. Questions about a child are
asked only if a child was present, are kept to the minimum, and say why they
are asked.

Each step has a stable id. Answers are stored by id, so reordering or rewording
a question later never changes what an earlier answer meant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

YES_NO_UNSURE = (("yes", "Yes"), ("no", "No"), ("not_sure", "I'm not sure"))


@dataclass(frozen=True)
class Step:
    id: str
    prompt: str
    kind: str  # "text" | "long" | "choice" | "date" | "upload"
    help: str = ""
    example: str = ""
    choices: tuple[tuple[str, str], ...] = ()
    #: Shown when the question touches a child, explaining why it is asked.
    why: str = ""
    #: Shown only when this returns True for the answers so far.
    when: Optional[Callable[[dict], bool]] = None
    max_len: int = 2000
    #: Heading the step belongs to, for the progress line and the review page.
    section: str = ""
    tags: frozenset = field(default_factory=frozenset)
    #: 1 for the light first pass, 2 for the deeper questions that follow.
    stage: int = 2


def _is(step_id: str, *values: str) -> Callable[[dict], bool]:
    return lambda answers: answers.get(step_id) in values


CHILD_WHY = ("Laylaw asks only what a lawyer would need to understand the situation. Please keep this short. "
             "You don't need to describe more, and please don't ask the child to go over it again.")

STEPS: tuple[Step, ...] = (
    # ---- Stage 1: the essentials, kept deliberately light ----------------------
    Step("danger_now", "First, is anyone in danger right now, or is someone still getting in without permission?",
         "choice", choices=YES_NO_UNSURE, section="Safety", stage=1,
         help="If the answer is yes, you'll see who you can contact. You can keep going afterwards."),
    Step("summary", "In a sentence or two, what happened?", "long", section="The essentials", stage=1,
         max_len=1000, help="Just the main point for now. There's room for detail later.",
         example="For example: a maintenance worker came into our apartment without knocking while my "
                 "child was in the bathroom."),
    Step("incident_date", "What day did it happen?", "date", section="The essentials", stage=1,
         help="If you only know roughly, choose \"I'm not sure\". You can explain later."),
    Step("entrant", "Who came in? A person, a company, or both, if you know.", "text", section="The essentials",
         stage=1, max_len=200, example="For example: a maintenance worker from the property management company"),
    Step("notice_given", "Before they came in, were you told they were coming?", "choice", choices=YES_NO_UNSURE,
         section="The essentials", stage=1, help="For example a note, a text, an email or a phone call."),
    Step("consent_given", "Did anyone at home say it was OK for them to come in?", "choice",
         choices=YES_NO_UNSURE, section="The essentials", stage=1),
    Step("first_files", "Do you have anything already, like texts, photos, a notice or video?", "upload",
         section="The essentials", stage=1,
         help="Add what you have now, or skip. You can add more at any time. Your files are kept exactly as "
              "they are."),
    Step("stage_gate", "The essentials are saved. Would you like to add more detail now?", "choice",
         section="The essentials", stage=1,
         choices=(("now", "Yes, keep going"), ("later", "Not now, I'll come back")),
         help="More detail helps a lawyer understand what happened. It takes about 10 minutes."),
    # ---- Stage 2: detail, only what applies --------------------------------------
    Step("incident_time", "About what time was it?", "text", section="When and where", max_len=80,
         example="For example: about 10:15 in the morning"),
    Step("location", "Where did it happen?", "text", section="When and where", max_len=200,
         help="A short description is enough. You don't need the full address here.",
         example="For example: our apartment, the bathroom"),
    Step("reporting_adult", "Who is filling this out?", "text", section="People", max_len=120,
         help="Your role is enough, for example \"parent\" or \"grandparent\". You don't need to give a name.",
         example="For example: the child's mother"),
    Step("people_present", "Who was at home when it happened?", "text", section="People", max_len=300,
         help="Roles are enough, no names needed.", example="For example: me and my daughter"),
    Step("child_present", "Was a child there?", "choice", choices=YES_NO_UNSURE, section="People"),
    Step("child_age_range", "About how old is the child?", "choice", section="People",
         choices=(("under_5", "Under 5"), ("5_9", "5 to 9"), ("10_13", "10 to 13"), ("14_17", "14 to 17"),
                  ("not_sure", "I'm not sure")),
         why=CHILD_WHY, when=_is("child_present", "yes"), tags=frozenset({"minor"}), max_len=20),
    Step("child_situation", "In a few words, what was the child doing when the person came in?", "text",
         section="People", max_len=160, why=CHILD_WHY, when=_is("child_present", "yes"),
         example="For example: getting ready for a bath", tags=frozenset({"minor"})),
    Step("child_spoke", "Did the child say anything about it on their own, without being asked?", "choice",
         choices=YES_NO_UNSURE, section="People", when=_is("child_present", "yes"),
         help="Only if it happened on its own. Please don't ask the child about it.", tags=frozenset({"minor"}),
         max_len=20),
    Step("child_words", "What were the child's exact words, as best you remember them?", "text",
         section="People", max_len=300, why="Exact words are kept once, as you remember them, and never reworded.",
         when=_is("child_spoke", "yes"), tags=frozenset({"minor", "statement"})),
    Step("child_words_heard_by", "Who heard the child say that, and when?", "text", section="People",
         max_len=200, when=_is("child_spoke", "yes"), example="For example: I did, right after he left",
         tags=frozenset({"minor"})),
    Step("entry_method", "How did they get in?", "choice", section="The entry",
         choices=(("key", "With a key or code"), ("unlocked", "The door was unlocked and they opened it"),
                  ("knocked_entered", "They knocked and came in"), ("let_in", "Someone let them in"),
                  ("other", "Another way"), ("not_sure", "I'm not sure"))),
    Step("entry_method_other", "How did they get in?", "text", section="The entry", max_len=200,
         when=_is("entry_method", "other")),
    Step("notice_details", "How were you told, and when?", "text", section="The entry", max_len=300,
         when=_is("notice_given", "yes"), example="For example: a note on the door the day before"),
    Step("emergency_claimed", "Did they say it was an emergency?", "choice", choices=YES_NO_UNSURE,
         section="The entry"),
    Step("emergency_details", "What did they say about the emergency?", "text", section="The entry",
         max_len=300, when=_is("emergency_claimed", "yes")),
    Step("open_request", "Was there a repair or maintenance request open at the time?", "choice",
         choices=YES_NO_UNSURE, section="The entry"),
    Step("open_request_details", "What was the request for, and when was it made?", "text",
         section="The entry", max_len=300, when=_is("open_request", "yes")),
    Step("what_happened", "Now, step by step: what happened, in order?", "long", section="What happened",
         help="One moment per line. Start a line with a time if you know it.",
         example="For example:\n10:15 knock at the door\n10:16 the door opened\nhe said sorry and left",
         max_len=4000),
    Step("entrant_response", "What did the person who came in say or do when they saw someone was there?",
         "text", section="What happened", max_len=500),
    Step("resident_response", "What did you, or whoever was home, say or do?", "text",
         section="What happened", max_len=500),
    Step("witnesses", "Did anyone else see or hear what happened?", "text", section="Afterwards",
         max_len=300, help="Roles are enough, for example \"neighbor\".", example="For example: no one"),
    Step("management_response", "Have you heard from the property manager or landlord about it since?",
         "text", section="Afterwards", max_len=500, example="For example: not yet"),
    Step("contacted", "Have you contacted anyone else about it, like an agency, the police or a lawyer?",
         "text", section="Afterwards", max_len=300, example="For example: no one yet"),
    Step("unresolved", "Is there anything you're unsure about, or want a lawyer to know?", "long",
         section="Afterwards", max_len=2000),
)

STEP_BY_ID = {s.id: s for s in STEPS}

SAFETY_MESSAGE = ("If anyone is in danger right now, call 911. If someone keeps getting in without permission, "
                  "you can contact local law enforcement's non-emergency line, or a licensed lawyer. Laylaw "
                  "doesn't decide what to do; it helps you keep a clear record. You can keep going when "
                  "you're ready.")


def applicable(step: Step, answers: dict) -> bool:
    return step.when is None or bool(step.when(answers))
