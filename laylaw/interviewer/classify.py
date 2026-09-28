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
# Firsthand knowledge must be established by the speaker's own words: their own
# perception ("I saw", "I was there") or their own act ("I sent a text"). A bare
# claim about someone else ("They were using drugs.") is NOT firsthand; its basis
# stays UNKNOWN until the interviewee says how they know.
FIRSTHAND_PATTERNS = [
    r"\b(?:i|we) (?:personally |actually |also |then )?(?:saw|see|watched|witnessed|noticed|observed)\b",
    r"\b(?:i|we) (?:was|were) (?:there|present|in the room|with (?:him|her|them))\b",
    r"\bwith my own eyes\b",
    r"^\s*(?:and |then |so )?(?:i|we) (?:personally |also |then |later )?"
    r"(?:sent|texted|emailed|called|asked|told|drove|went|walked|picked|dropped|paid|signed|filed|received|"
    r"got|found|took|left|arrived|spoke|talked|met|wrote|brought|moved|stayed|lived|live|worked|work|"
    r"waited|answered|opened|closed|heard (?:him|her|them|it) (?:say|yell|scream|shout))\b",
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
    session engine still refuses to *upgrade* a secondhand report. Firsthand
    knowledge is never assumed: with no cue in the words, the basis is UNKNOWN."""
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
    if _find(FIRSTHAND_PATTERNS, text):
        return SourceOfKnowledge.PERSONAL_OBSERVATION
    return SourceOfKnowledge.UNKNOWN


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


# ---------------------------------------------------------------------------
# Interview controls. Matched only when the WHOLE answer is the command, so a
# sentence that merely contains "skip" is never treated as a control.
# ---------------------------------------------------------------------------
_CONTROL_PATTERNS = {
    "save_later": r"(?:save(?: it)?(?: and| &)? (?:finish|continue|come back)(?: (?:it|this))? later"
                  r"|save and exit|let'?s stop (?:here|for now)(?: and continue later)?|pause (?:here|for now)"
                  r"|finish later)",
    "skip": r"(?:skip(?: (?:this|that|it|this one|this question))?|pass|next question"
            r"|i'?d rather not (?:say|answer)|prefer not to (?:say|answer))",
    "not_sure": r"(?:not sure|i'?m not sure|i don'?t know|dunno|i don'?t remember|i can'?t remember"
                r"|no idea|unsure|i'?m unsure|don'?t know)",
}


def detect_control(text: str) -> Optional[str]:
    t = re.sub(r"[.!]+$", "", text.strip().lower())
    for name, pattern in _CONTROL_PATTERNS.items():
        if re.fullmatch(pattern, t):
            return name
    return None


# ---------------------------------------------------------------------------
# Proposition spans. Splitting never rewrites words: each proposition is an
# exact [start, end) slice of the interviewee's own answer.
# ---------------------------------------------------------------------------
_ABBREV = r"(?:Mr|Mrs|Ms|Dr|Jr|Sr|St|vs|etc|No|approx|e\.g|i\.e)"


def proposition_spans(text: str) -> list[tuple[int, int]]:
    """Split an answer into sentence-level spans (verbatim slices).
    A deterministic suggestion only -- callers may pass their own spans."""
    spans, start = [], 0
    for m in re.finditer(r"[.!?]+[\"')\]]?(?=\s+[A-Z0-9\"'(])", text):
        end = m.end()
        before = text[max(0, m.start() - 6):m.start() + 1]
        if re.search(rf"\b{_ABBREV}\.$", before):
            continue
        if text[start:end].strip():
            spans.append((start, end))
        start = end
    if text[start:].strip():
        spans.append((start, len(text)))
    # trim whitespace inside each span
    out = []
    for a, b in spans:
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if a < b:
            out.append((a, b))
    return out


# ---------------------------------------------------------------------------
# Supporting-source typing for the record hook.
# ---------------------------------------------------------------------------
from .models import SupportingSourceType  # noqa: E402

_SUPPORT_PATTERNS = [
    (SupportingSourceType.COURT_RECORD,
     r"\b(?:court (?:record|file|filing|order|docket|paperwork|papers|minutes)s?|docket|minute order|"
     r"filing|filed|case file|court)\b"),
    (SupportingSourceType.EMAIL_TEXT,
     r"\b(?:e-?mails?|texts?|text messages?|texted|messages?|dms?|whatsapp|imessage|voicemails?|chat logs?)\b"),
    (SupportingSourceType.WITNESS,
     r"\b(?:witness(?:es)?|saw (?:it|that|what happened|everything)|was there|were there|can (?:tell|confirm|back)|"
     r"(?:my|a|the|our) (?:neighbou?r|friend|coworker|co-worker|mom|mother|dad|father|sister|brother|"
     r"aunt|uncle|cousin|teacher|coach|boss|roommate|babysitter|nanny|grandma|grandmother|grandpa|grandfather)\b"
     r"(?! (?:sent|texted|emailed)))"),
    (SupportingSourceType.DOCUMENT_FILE,
     r"\b(?:documents?|files?|pdfs?|receipts?|letters?|reports?|records?|photos?|pictures?|videos?|screenshots?|"
     r"calendar(?: entr(?:y|ies))?|invoices?|statements?|forms?|paperwork|notes?|logs?)\b"),
]


def classify_supporting_source(text: str) -> SupportingSourceType:
    for kind, pattern in _SUPPORT_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return kind
    return SupportingSourceType.OTHER


# ---------------------------------------------------------------------------
# Date phrases inside a longer sentence. Returns the interviewee's own words
# (a verbatim substring) or None. Only clear date expressions are picked up.
# ---------------------------------------------------------------------------
_QUAL = r"(?:(?:around|about|roughly|approximately|maybe|probably|early|mid|late|sometime in|some time in|in|on)\s+)?"
_DATE_PHRASES = [
    rf"{_QUAL}(?:{MONTH_RE})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+(?:19|20)\d{{2}}",
    rf"{_QUAL}(?:early |mid |late )?(?:{MONTH_RE}),?\s+(?:19|20)\d{{2}}",
    rf"{_QUAL}\d{{4}}-\d{{2}}-\d{{2}}",
    rf"{_QUAL}\d{{1,2}}/\d{{1,2}}/\d{{4}}",
    rf"{_QUAL}(?:{SEASONS})\s+(?:of\s+)?(?:19|20)\d{{2}}",
    rf"{_QUAL}(?:a|one|two|three|four|five|six|seven|eight|nine|ten|a few|several|\d+)\s+(?:days?|weeks?|months?|years?)\s+ago",
    r"(?:last|this)\s+(?:week|month|year|spring|summer|fall|autumn|winter)",
    r"yesterday",
]


def find_date_phrase(text: str) -> Optional[str]:
    for p in _DATE_PHRASES:
        m = re.search(rf"\b{p}\b", text, flags=re.IGNORECASE)
        if m:
            return text[m.start():m.end()]
    return None
