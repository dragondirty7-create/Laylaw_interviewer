"""Text classifiers used during INTERVIEW.

These are deliberately conservative. When a classifier is unsure it returns the
*less* certain answer (UNCERTAIN / APPROXIMATE / SECONDHAND). They only ever
describe what was said; they never add facts.
"""
from __future__ import annotations

import re
from typing import Optional

from .models import Certainty, DatePrecision, DateValue, SourceOfKnowledge

HEDGE_PATTERNS = [
    r"\bi think\b", r"\bi believe\b", r"\bmaybe\b", r"\bprobably\b", r"\bperhaps\b",
    r"\bpossibly\b", r"\bmight have\b", r"\bmight\b", r"\bi guess\b", r"\bsort of\b",
    r"\bkind of\b", r"\bi'?m not (?:totally |completely |100% )?sure\b",
    r"\bif i remember (?:right|correctly)\b", r"\bi could be wrong\b", r"\bseems like\b",
    r"\baround\b", r"\babout\b(?= \d| (?:a|one|two|three|four|five|six|seven|eight|nine|ten|a few) )", r"\broughly\b", r"\bapproximately\b", r"\bor so\b", r"\bsomething like\b",
]
UNSURE_PATTERNS = [
    r"\bi don'?t know\b", r"\bi don'?t remember\b", r"\bi can'?t remember\b",
    r"\bno idea\b", r"\bi'?m not sure (?:when|who|what|where|if)\b",
]
SECONDHAND_PATTERNS = [
    r"\b(?:she|he|they|someone|somebody|[a-z]+) (?:told|tells) me\b",
    r"\bi (?:was told|heard|found out from)\b",
    r"\b(?:she|he|they|my \w+|[A-Z][a-z]+) said (?:that )?\b",
    r"\baccording to\b", r"\bapparently\b", r"\bsupposedly\b",
]
INFERENCE_PATTERNS = [
    r"\bmust have\b", r"\bi assumed?\b", r"\bi figured\b", r"\bi guess(?:ed)? (?:that|he|she|they)\b",
    r"\bprobably because\b", r"\bi suspect\b",
]
DOCUMENT_PATTERNS = [
    r"\bthe (?:email|text|letter|message|report|receipt|order|record|document) (?:said|says|showed)\b",
    r"\bi (?:read|saw) (?:it )?in (?:the|an?|his|her) (?:email|text|letter|report|document|message)\b",
]
REQUEST_PATTERNS = [
    r"\bi want\b", r"\bi'?d like\b", r"\bi would like\b", r"\bi'?m asking for\b",
    r"\bi hope (?:to|that|the court)\b", r"\bi need (?:the court|them|him|her) to\b",
    r"\bwhat i'?m hoping for\b", r"\bgoing forward i want\b",
]
SAFETY_PATTERNS = [
    r"\b(?:i'?m|i am|we'?re|we are) (?:in danger|not safe|scared for my life)\b",
    r"\b(?:he|she|they)'?s? (?:outside|here|at the door|in the house) (?:right )?now\b",
    r"\b(?:going|gonna|threatening) to (?:hurt|kill) (?:me|us|my)\b",
    r"\bright now\b.*\b(?:hurt|danger|weapon|gun|knife)\b",
    r"\b(?:hurt|danger|weapon|gun|knife)\b.*\bright now\b",
    r"\bi want to (?:hurt|kill) myself\b",
]

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
MONTH_RE = "|".join(MONTHS)
APPROX_WORDS = r"(?:around|about|roughly|approximately|early|mid|late|sometime in|some time in|before|after|near|towards?)"
SEASONS = r"(?:spring|summer|fall|autumn|winter)"


def _find(patterns: list[str], text: str) -> list[str]:
    hits = []
    for p in patterns:
        for m in re.finditer(p, text, flags=re.IGNORECASE):
            hits.append(m.group(0))
    return hits


def detect_hedges(text: str) -> list[str]:
    return _find(HEDGE_PATTERNS, text)


def classify_certainty(text: str) -> tuple[Certainty, list[str]]:
    unsure = _find(UNSURE_PATTERNS, text)
    hedges = detect_hedges(text)
    if unsure:
        return Certainty.UNSURE, unsure + hedges
    if hedges:
        return Certainty.HEDGED, hedges
    return Certainty.STATED, []


def classify_source(text: str) -> SourceOfKnowledge:
    """Best-effort guess from wording. Callers may pass an explicit source; the
    session engine still refuses to *upgrade* a secondhand report."""
    if _find(REQUEST_PATTERNS, text):
        return SourceOfKnowledge.REQUEST
    if _find(DOCUMENT_PATTERNS, text):
        return SourceOfKnowledge.DOCUMENT_RECOLLECTION
    if _find(SECONDHAND_PATTERNS, text):
        return SourceOfKnowledge.SECONDHAND
    if _find(INFERENCE_PATTERNS, text):
        return SourceOfKnowledge.INFERENCE
    if _find(UNSURE_PATTERNS, text):
        return SourceOfKnowledge.UNCERTAIN
    return SourceOfKnowledge.PERSONAL_OBSERVATION


def is_request(text: str) -> bool:
    return bool(_find(REQUEST_PATTERNS, text))


def detect_present_safety_issue(text: str) -> bool:
    return bool(_find(SAFETY_PATTERNS, text))


def parse_date(text: Optional[str]) -> Optional[DateValue]:
    """Parse a date phrase WITHOUT adding precision the speaker didn't give."""
    if text is None:
        return None
    raw = text.strip()
    t = raw.lower()
    if not t:
        return None
    if re.search(r"\b(?:don'?t|do not|can'?t|cannot) (?:know|remember|recall)\b|\bunknown\b|\bno idea\b", t):
        return DateValue(raw, DatePrecision.UNKNOWN)

    approx = re.search(rf"\b{APPROX_WORDS}\b", t)
    hedged = bool(detect_hedges(t)) or bool(re.search(r"\bor so\b|\bish\b|\?", t))
    qualifier = approx.group(0) if approx else ("hedged" if hedged else None)

    # Relative dates ("six months ago", "two weeks after the party") stay
    # relative -- never converted into a calendar date.
    if re.search(r"\b(?:days?|weeks?|months?|years?) (?:after|before|later|earlier|ago)\b"
                 r"|\b(?:last|this|next) (?:week|month|year|summer|spring|fall|winter)\b"
                 r"|\byesterday\b|\btoday\b", t) \
            and not re.search(r"\b(19|20)\d{2}\b", t):
        return DateValue(raw, DatePrecision.RELATIVE, qualifier=qualifier)

    season = re.search(rf"\b{SEASONS}\b", t)
    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", t)
    year = int(year_m.group(1)) if year_m else None

    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    slash = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    mdy = re.search(rf"\b({MONTH_RE})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", t)
    my = re.search(rf"\b({MONTH_RE})\s*,?\s+(\d{{4}})\b", t)

    y = m = d = None
    if iso:
        y, m, d = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
    elif slash:
        m, d, y = int(slash.group(1)), int(slash.group(2)), int(slash.group(3))
    elif mdy:
        m, d, y = MONTHS[mdy.group(1)], int(mdy.group(2)), int(mdy.group(3))
    elif my:
        m, y = MONTHS[my.group(1)], int(my.group(2))
    else:
        y = year

    if y is None:
        return DateValue(raw, DatePrecision.UNKNOWN, qualifier=qualifier)

    if qualifier:
        # Keep only the parts actually said; mark the whole value approximate.
        return DateValue(raw, DatePrecision.APPROXIMATE, year=y, month=m, day=d,
                         qualifier=qualifier)
    if d is not None:
        return DateValue(raw, DatePrecision.EXACT, year=y, month=m, day=d)
    if m is not None:
        return DateValue(raw, DatePrecision.MONTH_ONLY, year=y, month=m)
    return DateValue(raw, DatePrecision.SEASON_YEAR, year=y,
                     qualifier=season.group(0) if season else None)
