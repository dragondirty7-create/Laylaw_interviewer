"""INTERVIEW-mode guard.

Every piece of text the interviewer produces while in INTERVIEW mode (questions,
recaps, outputs) passes through `assert_no_advocacy`. Legal strategy, advocacy,
and legal analysis belong to later Laylaw stages and are refused here.
"""
from __future__ import annotations

import re
from typing import Iterable

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


def _raw_hits(text: str) -> list[str]:
    hits: list[str] = []
    for p in ADVOCACY_PATTERNS:
        hits += [m.group(0) for m in re.finditer(p, text, flags=re.IGNORECASE)]
    return hits


def _mask_attributed(text: str, attributed: Iterable[str]) -> str:
    """Set aside words that belong to the interviewee or a document.

    The interviewer may record and repeat an allegation *as the interviewee's
    words* ("He was abusive."), but may never author one. Only attributed
    strings that would themselves trip the guard are set aside, and only where
    they appear verbatim, so generated text around them is still checked."""
    risky = sorted({a for a in attributed if a and a.strip() and _raw_hits(a)}, key=len, reverse=True)
    for a in risky:
        text = text.replace(a, " … ")
    return text


def find_advocacy(text: str, attributed: Iterable[str] = ()) -> list[str]:
    return _raw_hits(_mask_attributed(text, attributed))


def assert_no_advocacy(text: str, mode: Mode, attributed: Iterable[str] = ()) -> str:
    """Refuse generated advocacy in INTERVIEW mode. `attributed` lists verbatim
    interviewee/document wording carried in `text`; it is preserved as-is and not
    treated as the interviewer's own statement. Everything else is checked."""
    if mode == Mode.INTERVIEW:
        hits = find_advocacy(text, attributed)
        if hits:
            raise ModeViolation(f"advocacy/strategy language in INTERVIEW mode: {hits}")
    return text
