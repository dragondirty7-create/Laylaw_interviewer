"""Brief A: lighter follow-ups and the "No, that's all." loop. Synthetic data only.

Names ("Jordan Avery", "Sam Rowe", child "Pip") are invented.
"""
import pytest

from conftest import new_session
from laylaw.interviewer import SourceOfKnowledge, VerificationStatus, outputs, paths
from laylaw.interviewer.paths import SectionSpec
from laylaw.interviewer.session import (
    PATTERN_INSTANCE_QUESTION, RECORD_HOOK_QUESTION, SECTION_RECORD_HOOK_QUESTION, _is_nothing_more, _is_no,
)

FOLLOW_UP_KINDS = ("clarify", "record_hook")

# Natural ways of saying "that's all". Each is a whole answer, so none is a fact.
ENDINGS = [
    "No.", "Nope.", "Nothing else.", "No, that's all.", "No that is all", "Nope, nothing else.",
    "That's everything.", "No, that's it.", "That's all.", "Nah, that's it.", "No, nothing more.",
    "I think that's it.", "No, I think that's it.", "That's about it.", "No, that's everything.",
    "Nothing more to add.", "No, that's all, thanks.", "nope nothing else", "No. That's all.",
    "There's nothing else.", "That's all I remember.",
]
# Answers that start the same way but carry content: each must be recorded.
CONTENT = [
    "No, then he left.", "No, he took the car.", "Nope, Sam Rowe drove off.",
    "No, that's all he said before leaving.", "That's when Pip started crying.",
    "No, after that we went home.", "Nothing else happened until Sam Rowe called the next day.",
    "No, but the neighbor came outside.", "That's it, then the police arrived.",
    "No. Then Sam Rowe sent a text.", "Nah, Pip went to bed.", "No, everything stopped after the call.",
    "Nope, he came back an hour later.", "That's all I know about the car, but Pip saw the argument.",
    "No, the exchange ended there and Sam Rowe left.",
]


def test_phrase_table_sizes():
    assert len(ENDINGS) >= 15 and len(CONTENT) >= 15


@pytest.mark.parametrize("text", ENDINGS)
def test_ending_phrase_means_nothing_more(text):
    assert _is_nothing_more(text)


@pytest.mark.parametrize("text", CONTENT)
def test_content_phrase_is_not_an_ending(text):
    assert not _is_nothing_more(text)
    assert not _is_no(text)


def _to(s, field):
    """Answer every question with "skip" until the follow-up for `field` comes."""
    for _ in range(100):
        q = s.next_question()
        assert q is not None
        if s.pending.kind == "clarify" and s.pending.field == field:
            return q
        s.answer("skip")
    raise AssertionError(f"no {field} follow-up")


@pytest.mark.parametrize("text", ENDINGS)
def test_ending_phrase_ends_the_follow_ups(session, text):
    session.next_question()
    session.answer("On March 3, 2025, I saw Sam Rowe arrive for the exchange.")
    _to(session, "next")
    session.answer(text)
    assert len(session.facts) == 1                       # not recorded as a new fact
    assert not any(q.kind == "clarify" for q in session.queue)   # the follow-ups did not restart


@pytest.mark.parametrize("text", CONTENT)
def test_content_phrase_is_recorded_as_a_fact(session, text):
    session.next_question()
    session.answer("On March 3, 2025, I saw Sam Rowe arrive for the exchange.")
    _to(session, "next")
    session.answer(text)
    assert len(session.facts) >= 2
    assert session.facts[1].statement in text and session.facts[1].provenance.turn_index is not None


@pytest.mark.parametrize("text", ["No, that's all.", "Nope, nothing else.", "That's everything."])
def test_ending_phrase_to_an_opening_prompt_records_nothing(session, text):
    session.next_question()
    session.answer(text)
    assert session.facts == [] and session.outcomes == []


@pytest.mark.parametrize("text", ["No, that's all.", "Nope, nothing else.", "That's everything."])
def test_ending_phrase_at_the_record_question_adds_no_record(session, text):
    session.next_question()
    session.answer("Sam Rowe arrived at the library for the exchange.")
    for _ in range(20):
        session.next_question()
        if session.pending.kind == "record_hook":
            break
        session.answer("skip")
    session.answer(text)
    assert session.records == []


# --------------------------------------------------------------- the five-fact transcript
def _reply(q, kind, field):
    if kind == "preflight":
        return "Yes." if field == "confirm_workspace" else "No."
    if kind == "clarify":
        return {"date": "around March 2025", "people_present": "Just me and Pip",
                "location": "At the library parking lot", "source": "I was there and saw it.",
                "certainty": "I'm sure about the time.", "next": "No, that's all."}.get(field, "No.")
    if kind == "record_hook":
        return "I still have the text message."
    return "No."


FIVE_FACT_SECTIONS = {
    "Current household": "Pip lives with me during the week.",
    "Current parenting routine": "Sam Rowe usually picks Pip up from school on Fridays.",
    "Specific incidents": ("Sam Rowe arrived an hour late to the exchange. Pip waited with me in the car. "
                           "Later that night Sam Rowe sent a text saying the car broke down."),
}


def run_five_fact_transcript(ws, limit=300):
    """Drive the synthetic five-fact family-law interview; return (follow-ups asked, finished)."""
    s, _ = paths.start_path("family_law", ws, case_id="CASE-FICTIONAL-A", interviewee="Jordan Avery",
                            interviewer="Laylaw Interviewer", purpose="Synthetic test",
                            interviewee_is_adult=True, sections=list(FIVE_FACT_SECTIONS))
    asked = []
    for _ in range(limit):
        q = s.next_question()
        if q is None:
            return s, asked, True
        p = s.pending
        if p.kind in FOLLOW_UP_KINDS:
            asked.append((s.current_section, p.fact_id, p.field, p.text))
        s.answer(FIVE_FACT_SECTIONS[s.current_section] if p.kind == "free_account" else
                 _reply(q, p.kind, p.field))
    return s, asked, False


def test_five_fact_transcript_asks_at_most_15_follow_ups(ws):
    s, asked, finished = run_five_fact_transcript(ws)
    assert finished
    assert len(s.facts) == 5
    assert len(asked) <= 15, asked
    # Nothing is asked twice about the same item, and the record question once per section.
    assert len({(fid, field) for _, fid, field, _ in asked if fid}) == len([a for a in asked if a[1]])
    hooks = [sec for sec, _, _, text in asked if text in (RECORD_HOOK_QUESTION, SECTION_RECORD_HOOK_QUESTION)]
    assert sorted(hooks) == sorted(FIVE_FACT_SECTIONS)


def test_no_follow_up_asks_for_what_the_answer_already_gave(session):
    session.next_question()
    session.answer("On March 3, 2025, I saw Sam Rowe and Casey Lin at the library parking lot.")
    f = session.facts[0]
    assert f.date is not None and f.source == SourceOfKnowledge.PERSONAL_OBSERVATION
    fields = [q.field for q in session.queue if q.kind == "clarify"]
    assert "date" not in fields and "source" not in fields


def test_routine_fact_gets_no_where_or_what_next(ws):
    s = new_session(ws, sections=["Current parenting routine"])
    s.next_question()
    s.answer("Sam Rowe usually picks Pip up from school on Fridays.")
    texts = [q.text for q in s.queue if q.kind == "clarify"]
    assert "Where did this happen?" not in texts and "What happened next?" not in texts
    assert "Who else was there?" not in texts
    assert PATTERN_INSTANCE_QUESTION in texts          # A2 P1 1.4: one time that stands out


def test_state_gets_no_who_else_where_or_next(ws):
    s = new_session(ws, sections=["Current household"])
    s.next_question()
    s.answer("Pip lives with me during the week.")
    texts = [q.text for q in s.queue if q.kind == "clarify"]
    assert texts == ["About when was this?", "How do you know that?"]


def test_unasked_follow_ups_go_to_open_questions(session):
    session.next_question()
    session.answer("They were probably arguing in the kitchen.")       # hedged, unknown basis
    fid = session.facts[0].id
    fields = [q.field for q in session.queue if q.kind == "clarify"]
    assert fields == ["date", "source", "certainty"]                     # three, in the usual order
    listed = outputs.open_questions(session)
    assert f"{fid}: not asked, to keep the interview short: What happened next?" in listed
    assert f"{fid}: who was present (not yet stated)" in listed


def test_source_and_certainty_are_asked_even_past_the_cap(session, monkeypatch):
    monkeypatch.setitem(paths.SECTION_SPECS, "Specific incidents",
                        SectionSpec("Specific incidents", max_followups=0))
    session.next_question()
    session.answer("They were probably arguing.")
    assert [q.field for q in session.queue if q.kind == "clarify"] == ["source", "certainty"]


def test_cap_is_set_per_section(session, monkeypatch):
    monkeypatch.setitem(paths.SECTION_SPECS, "Specific incidents",
                        SectionSpec("Specific incidents", max_followups=5))
    session.next_question()
    session.answer("Sam Rowe arrived for the exchange.")
    assert len([q for q in session.queue if q.kind == "clarify"]) == 5


def test_discrepancy_check_is_never_capped(session, monkeypatch):
    monkeypatch.setitem(paths.SECTION_SPECS, "Specific incidents",
                        SectionSpec("Specific incidents", max_followups=0))
    session.next_question()
    session.answer("I saw a blue car.")
    fid = session.facts[0].id
    session.set_people_present(fid, "Alex")
    session.set_people_present(fid, "Taylor")
    session.queue = [q for q in session.queue if q.kind == "clarify"]
    assert [q.field for q in session.queue] == ["discrepancy"]
    assert '"Alex"' in session.next_question()


# --------------------------------------------------------------- record question once per section
def _answer_until_hook(s, filler="skip"):
    for _ in range(100):
        q = s.next_question()
        if s.pending.kind == "record_hook":
            return q
        s.answer(filler)
    raise AssertionError("no record question")


def test_record_question_is_asked_once_per_section_before_the_recap(session):
    session.next_question()
    session.answer("Sam Rowe arrived late. Pip waited in the car. Sam Rowe sent a text.")
    kinds = [q.kind for q in session.queue]
    assert kinds.count("record_hook") == 1
    assert kinds.index("record_hook") == kinds.index("recap") - 1
    assert _answer_until_hook(session) == SECTION_RECORD_HOOK_QUESTION


def test_record_question_keeps_the_per_fact_wording_and_link_for_one_item(session):
    session.next_question()
    session.answer("Casey Lin was late to the exchange.")
    assert _answer_until_hook(session) == RECORD_HOOK_QUESTION
    session.answer("My neighbor saw it happen from her porch.")
    assert session.facts[0].verification == VerificationStatus.WITNESS_IDENTIFIED


def test_record_named_in_the_answer_links_to_the_matching_item(session):
    session.next_question()
    session.answer("Sam Rowe arrived late. Pip waited in the car. Sam Rowe sent a text about the car.")
    _answer_until_hook(session)
    session.answer("I still have the text message.")
    rec = session.records[-1]
    texted = session.facts[2]
    assert rec.related_fact_ids == [texted.id] and rec.id in texted.possible_records
    assert session.facts[0].possible_records == [] and session.facts[1].possible_records == []


def test_unmatched_record_is_linked_to_the_section_not_guessed(session):
    session.next_question()
    session.answer("Sam Rowe arrived late. Pip waited in the car.")
    _answer_until_hook(session)
    session.answer("There might be a calendar entry.")
    rec = session.records[-1]
    assert rec.related_fact_ids == [f.id for f in session.facts]
    assert all(f.verification == VerificationStatus.INTERVIEW_ONLY for f in session.facts)
    assert any(o.startswith(f"{rec.id}: record mentioned") for o in session.open_questions)


def test_record_question_not_asked_again_after_an_addition(session):
    session.next_question()
    session.answer("Sam Rowe arrived late.")
    _answer_until_hook(session)
    session.answer("No.")
    for _ in range(20):
        q = session.next_question()
        if q == "Is there anything important I missed?":
            break
        assert session.pending.kind != "record_hook"
        session.answer("No.")
    session.answer("Pip cried in the car.")
    assert len(session.facts) == 2
    assert not any(q.kind == "record_hook" for q in session.queue)


def test_legacy_per_fact_record_question_still_answers(session):
    """A session saved before this change may hold a per-fact record question."""
    from laylaw.interviewer.session import PendingQuestion
    session.next_question()
    session.answer("Sam Rowe arrived late. Pip waited in the car.")
    fid = session.facts[1].id
    session.queue = [PendingQuestion("record_hook", RECORD_HOOK_QUESTION, fid)]
    session.pending = None
    session.next_question()
    session.answer("There's a photo of it.")
    assert session.records[-1].related_fact_ids == [fid]


def test_one_answer_is_one_account(session):
    """When, who and where are asked about the first item of an answer; "what
    happened next?" only after the last, since the next sentence already said."""
    session.next_question()
    session.answer("On March 3, 2025, I saw Sam Rowe arrive. Pip waited with me. I saw Sam Rowe leave.")
    first, middle, last = (f.id for f in session.facts)
    asked = {(q.fact_id, q.field) for q in session.queue if q.kind == "clarify"}
    assert (first, "people_present") in asked
    assert not {(middle, "date"), (middle, "people_present"), (middle, "location"), (last, "date")} & asked
    assert [fid for fid, field in asked if field == "next"] == [last]
    assert f"{middle}: when this happened (not yet known)" in outputs.open_questions(session)
