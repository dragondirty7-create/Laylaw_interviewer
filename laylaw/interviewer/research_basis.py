"""Research Basis for interviewing methodology (canonical spec, RESEARCH PROTOCOL).

A record of sources, kept separate from the engine. Nothing in the interview
engine reads this file: interview behavior changes only when a reviewed entry
is turned into a code change by a person. Unreviewed entries can never be
marked as applied.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

FIELDS = (
    "TITLE", "AUTHOR / ORGANIZATION", "DATE", "LINK / SOURCE", "TYPE OF SOURCE", "KEY FINDING",
    "HOW IT AFFECTS THE INTERVIEW PROTOCOL", "DATE REVIEWED",
)

# Spec: give greater weight to these; a single blog post or advocacy source
# must not change core behavior.
SOURCE_TYPES = (
    "peer-reviewed research", "official court", "government source", "professional interviewing guidance",
    "forensic interviewing research", "jurisdiction-specific procedural authority", "blog / opinion",
    "advocacy source", "other",
)
LOW_WEIGHT_TYPES = {"blog / opinion", "advocacy source"}


@dataclass
class ResearchEntry:
    title: str
    author_or_organization: str
    date: str
    link_or_source: str
    type_of_source: str
    key_finding: str
    how_it_affects_protocol: str
    date_reviewed: Optional[str] = None          # None -> not reviewed
    reviewed_by: Optional[str] = None
    applied_to_protocol: bool = False
    conflicts_with: list[str] = field(default_factory=list)  # titles of disagreeing entries

    def __post_init__(self):
        if self.type_of_source not in SOURCE_TYPES:
            raise ValueError(f"type_of_source must be one of {SOURCE_TYPES}")

    @property
    def reviewed(self) -> bool:
        return bool(self.date_reviewed and self.reviewed_by)

    def as_template_row(self) -> dict:
        return dict(zip(FIELDS, (self.title, self.author_or_organization, self.date, self.link_or_source,
                                 self.type_of_source, self.key_finding, self.how_it_affects_protocol,
                                 self.date_reviewed or "NOT YET REVIEWED")))


class ResearchBasis:
    def __init__(self, entries: Optional[list[ResearchEntry]] = None):
        self.entries = list(entries or [])

    def add(self, entry: ResearchEntry) -> ResearchEntry:
        self.entries.append(entry)
        return entry

    def mark_reviewed(self, title: str, *, date_reviewed: str, reviewed_by: str) -> ResearchEntry:
        e = self._get(title)
        e.date_reviewed, e.reviewed_by = date_reviewed, reviewed_by
        return e

    def mark_applied(self, title: str) -> ResearchEntry:
        """Record that a reviewed finding was turned into a protocol change."""
        e = self._get(title)
        if not e.reviewed:
            raise PermissionError("unreviewed research cannot change interviewing behavior")
        if e.type_of_source in LOW_WEIGHT_TYPES:
            raise PermissionError("a single blog/advocacy source cannot change core interview behavior")
        e.applied_to_protocol = True
        return e

    def flag_conflict(self, title_a: str, title_b: str) -> None:
        """Spec: when research conflicts, preserve the disagreement and flag it for review."""
        self._get(title_a).conflicts_with.append(title_b)
        self._get(title_b).conflicts_with.append(title_a)

    def _get(self, title: str) -> ResearchEntry:
        return next(e for e in self.entries if e.title == title)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps([asdict(e) for e in self.entries], indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "ResearchBasis":
        return cls([ResearchEntry(**e) for e in json.loads(Path(path).read_text("utf-8"))])
