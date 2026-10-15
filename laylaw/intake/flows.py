"""Question sets ("flows") the intake engine can run.

One engine, several flows. Each flow has its own questions, its own file
categories and its own safety wording, and is stored in the same encrypted
vault, one matter per workspace. Nothing is shared between matters.

  housing      Rapid Incident Intake: an entry into a home (PR #11)
  supervision  Rapid Criminal & Supervision Intake: charges and/or parole,
               probation or other supervision, with a treatment branch

Saves made before flows existed carry no flow and load as "housing".
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import steps as housing
from . import supervision_steps as supervision

DEFAULT_FLOW = "housing"

#: Housing file categories. Kept under these names because PR #11 code and tests import them.
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


@dataclass(frozen=True)
class Flow:
    name: str
    #: Shown on the home page and as the default title.
    title: str
    steps: tuple
    evidence_categories: tuple[tuple[str, str], ...]
    safety_message: str
    #: The step after which the full safety message is shown (the one that follows the danger question).
    safety_step: str
    step_by_id: dict = field(default_factory=dict)


def _flow(name, title, steps, categories, safety, safety_step) -> Flow:
    ids = [s.id for s in steps]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"Flow {name} has duplicate step ids.")
    return Flow(name, title, steps, categories, safety, safety_step, {s.id: s for s in steps})


FLOWS: dict[str, Flow] = {
    "housing": _flow("housing", "Incident intake", housing.STEPS, EVIDENCE_CATEGORIES,
                     housing.SAFETY_MESSAGE, "summary"),
    "supervision": _flow("supervision", "Criminal & supervision intake", supervision.STEPS,
                         supervision.EVIDENCE_CATEGORIES, supervision.SAFETY_MESSAGE, "about_adult"),
}


def get_flow(name: str) -> Flow:
    try:
        return FLOWS[name]
    except KeyError:
        from .model import IntakeError  # local import: model imports this module
        raise IntakeError("That kind of intake isn't available.") from None
