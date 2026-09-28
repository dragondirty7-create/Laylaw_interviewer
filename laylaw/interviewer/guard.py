"""INTERVIEW-mode guard.

Every piece of text the interviewer produces while in INTERVIEW mode (questions,
recaps, outputs) passes through `assert_no_advocacy`. Legal strategy, advocacy,
and legal analysis belong to later Laylaw stages and are refused here.
"""
from __future__ import annotations

import re

from .models import Mode


class ModeViolation(RuntimeError):
    """Raised when INTERVIEW mode would emit advocacy/strategy/analysis."""


ADVOCACY_PATTERNS = [
    r"\byou should (?:argue|claim|say|tell the (?:court|judge)|file|allege|emphasi[sz]e|push for)\b",
    r"\b(?:legal |litigation |case |winning )strategy\b",
    r"\bstrateg(?:y|ic) (?:for|to) (?:win|the case|court)\b",
    r"\b(?:strong|weak|strongest|best|good) (?:case|argument|claim)\b",
    r"\byour best (?:argument|shot|angle)\b",
    r"\b(?:this|that) (?:helps|hurts) (?:your|the) case\b",
    r"\bto (?:win|strengthen|bolster) (?:your|the) case\b",
    r"\b(?:the )?judge will (?:likely|probably)\b",
    r"\bcourts? (?:usually|typically|tend to) (?:rule|side|find)\b",
    r"\bunder (?:the )?(?:law|statute|code|section)\b",
    r"\bthis (?:proves|establishes|shows) (?:that|he|she|they)\b",
    r"\bthat (?:sounds|looks) better\b",
    r"\blegal advice\b(?! is not)",
    r"\b(?:is|was) (?:abusive|a narcissist|an addict|dangerous|lying)\b",
]


def find_advocacy(text: str) -> list[str]:
    hits: list[str] = []
    for p in ADVOCACY_PATTERNS:
        hits += [m.group(0) for m in re.finditer(p, text, flags=re.IGNORECASE)]
    return hits


def assert_no_advocacy(text: str, mode: Mode) -> str:
    if mode == Mode.INTERVIEW:
        hits = find_advocacy(text)
        if hits:
            raise ModeViolation(f"advocacy/strategy language in INTERVIEW mode: {hits}")
    return text
