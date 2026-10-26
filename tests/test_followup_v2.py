"""Brief A2, P0: follow-up v2. Synthetic data only.

Names ("Jordan Avery", "Sam Rowe", child "Pip") are invented.
"""
import re
from collections import Counter

import pytest

from conftest import new_session
from laylaw.interviewer import SourceOfKnowledge, classify, outputs
from laylaw.interviewer.session import (
    _CHECK_FOLLOWUPS, END_OF_SECTION_QUESTIONS, FINAL_CHECK_QUESTIONS, GROUP_SOURCE_QUESTION, OFFER_SKIP_TEXT,
    RECORD_HOOK_QUESTION, REPHRASE_PREFIX, REPHRASED, REPHRASED_ROUTINE_NEXT, SECTION_RECORD_HOOK_QUESTION,
    PendingQuestion,
)
from test_lighter_questions import run_five_fact_transcript

THREE = "Sam Rowe arrived an hour late. Pip waited with me in the car. Sam Rowe sent a text about the car."
PROVENANCE_FIELDS = ("source", "source_group", "source_scope")


def _to(s, pred, filler="No."):
    for _ in range(60):
        q = s.next_question()
        assert q is not None, "interview ended first"
        if pred(s.pending):
            return q
        s.answer(filler)
    raise AssertionError("question never came")


def _group(session, text=THREE):
    session.next_question()
    session.answer(text)
    return _to(session, lambda p: p.field == "source_group")


def assert_no_repeat(s):
    """No (item, intent) pair is asked twice unless the repeat carries its reason."""
    plain = Counter((a["fact"], a["intent"]) for a in s.asked if not a["why"])
    assert all(n == 1 for n in plain.values()), [k for k, n in plain.items() if n > 1]


def assert_provenance_traceable(s):
    """Every recorded basis points to a turn in which the interviewee spoke."""
    turns = {t.index: t for t in s.turns}
    for f in s.facts:
        if f.source != SourceOfKnowledge.UNKNOWN or f.source_scope in ("answered", "confirmed_all",
                                                                        "confirmed_except", "own_words"):
            assert f.source_turn in turns, f.id
            assert turns[f.source_turn].answer.strip() and turns[f.source_turn].control != "save_later"


# ============================================================ 0.1 provenance for several items
def test_one_provenance_question_for_a_three_event_answer(session):
    assert _group(session) == GROUP_SOURCE_QUESTION
    fields = [q.field for q in session.queue if q.kind == "clarify"] + [session.pending.field]
    assert fields.count("source") == 0 and fields.count("source_group") == 1


def test_answer_that_covers_all_applies_to_every_event(session):
    _group(session)
    session.answer("I was there for all of them.")
    t = session.turns[-1].index
    assert all(f.source == SourceOfKnowledge.PERSONAL_OBSERVATION and f.source_scope == "confirmed_all"
               and f.source_turn == t for f in session.facts)
    assert not any(q.field == "source_scope" for q in session.queue)        # one provenance turn
    assert_provenance_traceable(session)


def test_scope_is_confirmed_in_the_persons_own_words(session):
    _group(session)
    session.answer("I saw it.")
    assert all(f.source == SourceOfKnowledge.UNKNOWN for f in session.facts)   # nothing inherited yet
    q = session.next_question()
    assert session.pending.field == "source_scope"
    for f in session.facts:
        assert " ".join(f.statement.split()[:3]) in q                            # their words as labels
    assert "or is any of them different?" in q and "not sure" in q
    assert "same for all of them?" not in q.lower()
    session.answer("All of them.")
    assert all(f.source == SourceOfKnowledge.PERSONAL_OBSERVATION and f.source_scope == "confirmed_all"
               for f in session.facts)
    assert all(f.source_turn == session.turns[-2].index for f in session.facts)   # the basis turn
    assert_provenance_traceable(session)


def test_an_event_said_to_be_different_gets_its_own_question(session):
    _group(session)
    session.answer("I saw it.")
    session.next_question()
    session.answer("The text one was different.")
    a, b, c = session.facts
    assert a.source_scope == b.source_scope == "confirmed_except"
    assert a.source == b.source == SourceOfKnowledge.PERSONAL_OBSERVATION
    assert c.source == SourceOfKnowledge.UNKNOWN and c.source_scope is None
    q = session.next_question()
    assert q.startswith("How do you know about \"Sam Rowe sent a text") and session.pending.why
    session.answer("My sister told me about it.")
    assert c.source == SourceOfKnowledge.SECONDHAND and c.source_scope == "answered"
    assert_no_repeat(session)
    assert_provenance_traceable(session)


def test_all_different_asks_each_once(session):
    _group(session)
    session.answer("I saw some of it.")
    session.next_question()
    session.answer("They're all different.")
    asked = [q for q in session.queue if q.field == "source"]
    assert [q.fact_id for q in asked] == [f.id for f in session.facts]
    assert all(q.why for q in asked)


@pytest.mark.parametrize("reply", ["Yes.", "No.", "Not sure", "skip", "Kind of.", "I guess."])
def test_unclear_scope_never_lets_events_inherit(session, reply):
    _group(session)
    session.answer("I saw it.")
    session.next_question()
    session.answer(reply)
    for f in session.facts:
        assert f.source == SourceOfKnowledge.UNKNOWN
        assert f.source_scope == "unspecified" or (reply == "Not sure" and f.source_scope == "answered")
    if reply != "Not sure":
        listed = outputs.open_questions(session)
        assert all(any(o.startswith(f"{f.id}: how the interviewee knows this is unspecified") for o in listed)
                   for f in session.facts)


def test_five_fact_sample_provenance_turns_drop_to_two(ws):
    s, asked, finished = run_five_fact_transcript(ws)
    assert finished
    incident = [a for a in asked if a[0] == "Specific incidents" and a[2] in PROVENANCE_FIELDS]
    assert len(incident) <= 2                                   # was 3: one per event
    assert len(asked) <= 13                                     # was 14 on PR #15
    assert_no_repeat(s)
    assert_provenance_traceable(s)


def test_basis_stated_in_the_answer_points_to_that_turn(session):
    session.next_question()
    session.answer("I saw Sam Rowe drive away.")
    f = session.facts[0]
    assert f.source_scope == "own_words" and f.source_turn == session.turns[-1].index


# ============================================================ 0.2 three ways out
@pytest.mark.parametrize("text, control", [
    ("I don't know", "not_sure"), ("No idea.", "not_sure"), ("Dunno", "not_sure"),
    ("Skip", "skip"), ("Pass", "skip"), ("Skip this one", "skip"),
    ("Huh?", "dont_understand"), ("What do you mean?", "dont_understand"),
    ("I don't understand the question.", "dont_understand"), ("I'm confused", "dont_understand"),
    ("Can you say that another way?", "dont_understand"), ("Not sure what you mean.", "dont_understand"),
])
def test_free_text_ways_out(text, control):
    assert classify.detect_control(text) == control


def _first_date_q(session):
    session.next_question()
    session.answer("Sam Rowe arrived for the exchange.")
    return _to(session, lambda p: p.field == "date")


def _rest_of_interview(session, filler="No."):
    asked = []
    for _ in range(80):
        q = session.next_question()
        if q is None:
            return asked
        asked.append((session.pending.fact_id, session.pending.field, session.pending.why))
        session.answer(filler)
    raise AssertionError("did not finish")


def test_dont_know_is_an_answer_and_closes_the_question(session):
    _first_date_q(session)
    session.answer("I don't know")
    f = session.facts[0]
    assert f.date.precision.value == "UNKNOWN"
    assert {"fact": f.id, "intent": "date", "outcome": "dont_know"}.items() <= session.asked[-1].items()
    assert f"{f.id}: when this happened (not yet known)" not in outputs.open_questions(session)
    assert not [a for a in _rest_of_interview(session) if a[0] == f.id and a[1] == "date"]
    assert_no_repeat(session)


def test_skip_goes_to_open_questions_and_is_never_asked_again(session):
    _first_date_q(session)
    session.answer("Pass")
    f = session.facts[0]
    assert f"{f.id}: skipped: About when was this?" in outputs.open_questions(session)
    assert not [a for a in _rest_of_interview(session) if a[0] == f.id and a[1] == "date"]
    assert_no_repeat(session)


def test_dont_understand_rephrases_once_then_offers_skip(session):
    _first_date_q(session)
    f = session.facts[0]
    session.answer("Huh?")
    q = session.next_question()
    assert q == REPHRASE_PREFIX + REPHRASED["date"]                 # says why it is asked again
    session.answer("I don't understand")
    assert session.next_question() == OFFER_SKIP_TEXT
    session.answer("What?")
    assert f"{f.id}: skipped: when it happened (not understood, then skipped)" in session.open_questions
    assert not [a for a in _rest_of_interview(session) if a[0] == f.id and a[1] == "date"]
    assert_no_repeat(session)


def test_answer_after_a_rephrase_is_recorded(session):
    _first_date_q(session)
    session.answer("What do you mean?")
    session.next_question()
    session.answer("around April 2025")
    assert session.facts[0].date.precision.value == "APPROXIMATE"
    assert_no_repeat(session)


def test_no_to_the_offer_to_skip_is_a_skip(session):
    _first_date_q(session)
    session.answer("Huh?")
    session.next_question()
    session.answer("Huh?")
    session.next_question()
    session.answer("No.")
    assert session.facts[0].date is None
    assert any(o.startswith(f"{session.facts[0].id}: skipped") for o in session.open_questions)


def test_routine_rephrase_keeps_routine_wording(ws):
    s = new_session(ws, sections=["Current parenting routine"])
    s.next_question()
    s.answer("Sam Rowe usually picks Pip up on Fridays.")
    _to(s, lambda p: p.field == "next")
    s.answer("Huh?")
    assert s.next_question() == REPHRASE_PREFIX + REPHRASED_ROUTINE_NEXT


def test_dont_understand_outside_follow_ups_is_read_as_before(session):
    session.next_question()
    session.answer("What do you mean?")
    assert session.turns[-1].control is None                        # handled exactly as before this change
    assert not any(q.why for q in session.queue)                    # no rephrase of an opening prompt


# ============================================================ 0.3 never asked twice
PERSONAS = {
    "baseline": lambda p: "No.",
    "dont_know_repeater": lambda p: "I don't know",
    "skipper": lambda p: "skip",
    "confused": lambda p: "Huh?",
    "acquiescent": lambda p: "Yes.",
    "all_of_them": lambda p: "I was there for all of them." if p.field == "source_group" else "around May 2025",
}


@pytest.mark.parametrize("persona", PERSONAS)
def test_no_item_is_asked_the_same_thing_twice(ws, persona):
    s = new_session(ws, sections=["Specific incidents", "Current parenting routine"])
    reply = PERSONAS[persona]
    for _ in range(200):
        q = s.next_question()
        if q is None:
            break
        if s.pending.kind == "free_account":
            s.answer(THREE if s.current_section == "Specific incidents" else "Pip usually stays with me.")
        elif s.pending.kind in ("clarify", "record_hook"):
            s.answer(reply(s.pending))
        else:
            s.answer("No.")          # recap and final checks: the persona is about follow-ups
    else:
        raise AssertionError("interview did not finish")
    assert_no_repeat(s)
    assert_provenance_traceable(s)
    follow_ups = Counter(a["fact"] for a in s.asked if not a["why"] and a["intent"] != "source_scope")
    assert max(follow_ups.values()) <= 3


def test_a_stale_duplicate_in_a_saved_queue_is_not_asked(session):
    """E.g. a queue saved by an older version that still holds an answered question."""
    _first_date_q(session)
    fid = session.facts[0].id
    session.answer("around April 2025")
    session.queue.insert(0, PendingQuestion("clarify", "About when was this?", fid, "date"))
    session.next_question()
    assert not (session.pending.fact_id == fid and session.pending.field == "date")
    assert_no_repeat(session)


def test_a_corrected_item_is_not_asked_again(session):
    _first_date_q(session)
    fid = session.facts[0].id
    session.answer("around April 2025")
    raw = session.log_answer("It was Sam Rowe's brother who arrived.", question="What should I change?")
    new = session.correct_fact(fid, "It was Sam Rowe's brother who arrived.", raw_answer_id=raw.id)
    session.queue.insert(0, PendingQuestion("clarify", "About when was this?", new.id, "date"))
    session.next_question()
    assert not (session.pending.fact_id == new.id and session.pending.field == "date")


def test_register_survives_save_and_reload(ws, store):
    s = new_session(ws)
    _first_date_q(s)
    s.answer("around April 2025")
    again = store.workspace(ws.client_id).load_session(s.interview_id)
    assert again.asked == s.asked and again.asked[-1]["intent"] == "date"


# ============================================================ 0.4 recap in the person's words
def _recap_session(session):
    _group(session)
    session.answer("I was there for all of them.")
    return session


def test_every_recap_clause_traces_to_the_persons_turn(session):
    _recap_session(session)
    _to(session, lambda p: p.kind == "recap")
    answers = [t.answer for t in session.turns]
    for f in session._current_facts("Specific incidents"):
        for _, text in outputs.recap_clauses(f, session):
            assert any(text in a for a in answers), text
    recap = session.section_recap(with_questions=False)
    assert recap.startswith("Here's what I have for specific incidents, in your words:")
    # Nothing in the body but their words and the fixed clause labels.
    body = recap.split("\n", 1)[1]
    for line in body.splitlines():
        rest = line[2:]
        for f in session._current_facts("Specific incidents"):
            for _, text in outputs.recap_clauses(f, session):
                rest = rest.replace(text, "", 1)
        assert re.fullmatch(r"(?:;? ?(?:when|who was there|where|how you know):? ?)*", rest), rest


def test_recap_adds_no_app_labels_or_inferred_details(session):
    session.next_question()
    session.answer("They were using drugs.")
    recap = session.section_recap(with_questions=False)
    assert "UNKNOWN" not in recap and "Date:" not in recap and "PERSONAL" not in recap


# A bare "Correct?" confirmation, not the verb ("want to correct?").
BANNED = [r"\bis that right\?", r"(?:^|[.!?]\s+)correct\?", r"\banything else\b", r"\bsame for all of them\?"]


def _templates(session):
    session.next_question()
    session.answer(THREE)
    return (END_OF_SECTION_QUESTIONS + FINAL_CHECK_QUESTIONS + list(_CHECK_FOLLOWUPS.values())
            + list(REPHRASED.values()) + [REPHRASED_ROUTINE_NEXT, OFFER_SKIP_TEXT, GROUP_SOURCE_QUESTION,
                                          RECORD_HOOK_QUESTION, SECTION_RECORD_HOOK_QUESTION,
                                          session._scope_question([f.id for f in session.facts]),
                                          session.section_recap()])


def test_lint_no_bare_confirmations_or_anything_else_in_recap_and_closing(session):
    for text in _templates(session):
        for pat in BANNED:
            assert not re.search(pat, text, flags=re.I), (pat, text)


@pytest.mark.parametrize("reply", ["No.", "Huh?", "skip"])
def test_offered_skip_is_logged_as_skipped_and_survives_resume(ws, store, reply):
    """Soul, 2026-10-25: normalise the answer to the offer first, then log the real outcome."""
    s = new_session(ws)
    _first_date_q(s)
    s.answer("Huh?")
    s.next_question()
    s.answer("I don't understand")
    assert s.next_question() == OFFER_SKIP_TEXT
    s.answer(reply)
    last = s.asked[-1]
    assert (last["intent"], last["outcome"]) == ("date", "skipped") and last["why"].startswith("offer_skip")
    s.save_and_finish_later()
    again = store.workspace(ws.client_id).load_session(s.interview_id)
    assert again.asked[-1]["outcome"] == "skipped"
    assert not any(a["outcome"] == "answered" for a in again.asked if a["intent"] == "date")
    again.resume()
    assert not [a for a in _rest_of_interview(again) if a[0] == again.facts[0].id and a[1] == "date"]
