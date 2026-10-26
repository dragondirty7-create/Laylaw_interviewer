"""P1 session state across save and resume (verification follow-up Gap A). Synthetic data only.

Each test saves the interview mid-way, loads a fresh copy from the workspace store,
resumes it and keeps going. Run under LAYLAW_TEST_STORE=encrypted too.
Names ("Jordan Avery", "Sam Rowe", "Casey Lin", child "Pip") are invented.
"""
import pytest

from conftest import new_session
from laylaw.interviewer import SessionStatus
from laylaw.interviewer.models import FactStatus
from laylaw.interviewer.session import BREAK_OFFER, KEEP_SHORT_NOTICE, WHICH_KIND_QUESTION
from test_followup_p1 import THREE, _over_the_limit, _to, assert_no_repeat, assert_provenance_closed

RECAP = "What did I get wrong or leave out?"
VIA = ["save_later", "interrupt"]


def _reload(s, via):
    """Save the interview the way the interviewee or the app would, then load and resume a fresh copy."""
    if via == "save_later":
        s.answer("save and finish later")
    else:
        s.interrupt()
    assert s.status == SessionStatus.PAUSED
    again = s.workspace.load_session(s.interview_id)
    assert again is not s and again.status == SessionStatus.PAUSED
    again.resume()
    assert again.status == SessionStatus.ACTIVE and again.is_continuation
    return again


def _permission_offers(s):
    """Answered offers; the "save and finish later" turn at the same question is not a second offer."""
    return [t for t in s.turns if t.control != "save_later" and t.question
            and t.question.endswith(("save them for later?", "save it for later?"))]


# ============================================================ 1. held questions
@pytest.mark.parametrize("via", VIA)
def test_held_questions_survive_resume_before_the_recap(session, via):
    f = _over_the_limit(session)
    held = [(d.fact_id, d.field) for d in session.deferred]
    assert len(held) == 3
    session.next_question()                                      # some question before the recap is pending
    assert session.pending.kind != "deferred_permission"
    s = _reload(session, via)
    assert [(d.fact_id, d.field) for d in s.deferred] == held and all(d.why for d in s.deferred)
    q = _to(s, lambda p: p.kind == "deferred_permission")
    assert q.startswith("Two quick ones")
    s.answer("OK")
    for field in ("people_present", "location"):
        s.next_question()
        assert s.pending.field == field and s.pending.fact_id == f.id
        s.answer("Just me")
    assert s.next_question().endswith(RECAP)
    assert len(_permission_offers(s)) == 1                       # offered once, max two
    assert f"{f.id}: not asked, to keep the interview short: What happened next?" in s.open_questions
    assert_no_repeat(s)


@pytest.mark.parametrize("via", VIA)
def test_resume_at_the_permission_question_asks_it_once(session, via):
    f = _over_the_limit(session)
    _to(session, lambda p: p.kind == "deferred_permission")
    s = _reload(session, via)
    assert s.next_question().startswith("Two quick ones") and s.pending.kind == "deferred_permission"
    s.answer("Sure.")
    asked = []
    for _ in range(2):
        s.next_question()
        asked.append((s.pending.fact_id, s.pending.field))
        s.answer("Just me")
    assert asked == [(f.id, "people_present"), (f.id, "location")]
    assert s.next_question().endswith(RECAP)
    assert len(_permission_offers(s)) == 1
    assert_no_repeat(s)


@pytest.mark.parametrize("via", VIA)
def test_resume_between_the_two_held_questions_never_offers_again(session, via):
    f = _over_the_limit(session)
    _to(session, lambda p: p.kind == "deferred_permission")
    session.answer("OK")
    session.next_question()
    assert session.pending.field == "people_present"
    session.answer("Just me")
    session.next_question()
    assert session.pending.field == "location"
    s = _reload(session, via)
    assert s.next_question() and s.pending.field == "location" and s.pending.fact_id == f.id
    s.answer("At the library.")
    q = s.next_question()
    assert q.endswith(RECAP) and s.pending.kind != "deferred_permission"
    assert len(_permission_offers(s)) == 1
    assert_no_repeat(s)


@pytest.mark.parametrize("via", VIA)
def test_saving_held_questions_for_later_survives_resume(session, via):
    f = _over_the_limit(session)
    _to(session, lambda p: p.kind == "deferred_permission")
    session.answer("Save it for later.")
    session.next_question()
    s = _reload(session, via)
    assert s.next_question().endswith(RECAP)
    assert len(_permission_offers(s)) == 1
    assert f"{f.id}: not asked, to keep the interview short: Where did this happen?" in s.open_questions


@pytest.mark.parametrize("via", VIA)
def test_basis_is_still_first_among_held_questions_after_resume(session, via):
    session.next_question()
    session.answer(THREE)
    _to(session, lambda p: p.field == "source_group", filler="around March 2025")
    session.answer("I'm tired.")
    assert session.next_question() == BREAK_OFFER
    session.answer("Keep going.")
    session.next_question()
    s = _reload(session, via)
    assert any(d.field == "source_group" for d in s.deferred)
    _to(s, lambda p: p.kind == "deferred_permission")
    assert s.pending.text.startswith("Two quick ones")
    s.answer("Sure.")
    asked = []
    for _ in range(2):
        s.next_question()
        asked.append(s.pending.field)
        s.answer("I was there for all of them.")
    assert asked[0] == "source_group"
    assert s.next_question().endswith(RECAP)
    assert len(_permission_offers(s)) == 1
    assert_no_repeat(s)
    assert_provenance_closed(s)


# ============================================================ 2. one break per section
def _break_offers(s):
    return [t for t in s.turns if t.control != "save_later" and t.question == BREAK_OFFER]


@pytest.mark.parametrize("via", VIA)
def test_keep_going_then_resume_never_offers_a_second_break_in_the_section(session, via):
    session.next_question()
    session.answer("Sam Rowe arrived late. This is hard.")
    assert session.next_question() == BREAK_OFFER
    session.answer("Keep going")
    assert session.next_question().startswith(KEEP_SHORT_NOTICE)
    s = _reload(session, via)
    assert "Specific incidents" in s.fatigue_sections
    for _ in range(10):
        q = s.next_question()
        if q is None or s.current_section != "Specific incidents":
            break
        assert s.pending.kind != "break_offer"
        s.answer("I'm tired.")
    assert len(_break_offers(s)) == 1


@pytest.mark.parametrize("via", VIA)
def test_resume_at_a_pending_break_offer_asks_it_once(session, via):
    session.next_question()
    session.answer("Sam Rowe arrived late.")
    session.next_question()
    session.answer("I'm tired.")
    assert session.next_question() == BREAK_OFFER
    s = _reload(session, via)
    assert s.next_question() == BREAK_OFFER                      # the resume point is the same offer
    s.answer("I'm okay, keep going.")
    assert s.next_question().startswith(KEEP_SHORT_NOTICE)
    for _ in range(10):
        if s.current_section != "Specific incidents":
            break
        assert s.pending.kind != "break_offer"
        s.answer("I'm tired.")
        if s.next_question() is None:
            break
    assert len(_break_offers(s)) == 1


def test_pausing_at_a_break_then_resuming_does_not_offer_another_in_the_section(session):
    session.next_question()
    session.answer("Sam Rowe arrived late.")
    session.next_question()
    session.answer("I'm tired, can we stop?")
    assert session.next_question() == BREAK_OFFER
    session.answer("Yes, let's pause.")                         # the break itself saves the interview
    s = session.workspace.load_session(session.interview_id)
    s.resume()
    s.next_question()
    assert s.pending.why == "asked again after a break offer"
    s.answer("I'm tired.")
    assert s.next_question() != BREAK_OFFER
    assert len(_break_offers(s)) == 1


def test_a_new_section_after_resume_can_still_offer_its_own_break(ws):
    s = new_session(ws, sections=["Specific incidents", "Housing"])
    s.next_question()
    s.answer("Sam Rowe arrived late. This is hard.")
    assert s.next_question() == BREAK_OFFER
    s.answer("Keep going")
    s.next_question()
    s = _reload(s, "save_later")
    _to(s, lambda p: p.kind == "free_account" and s.current_section == "Housing")
    s.answer("We moved in March. This is hard.")
    assert s.next_question() == BREAK_OFFER and s.current_section == "Housing"
    assert len(_break_offers(s)) == 1                           # the first section's, answered before the resume


# ============================================================ 3. tiredness counters
@pytest.mark.parametrize("via", VIA)
def test_skip_streak_survives_resume(session, via):
    session.next_question()
    session.answer("Sam Rowe arrived late.")
    session.next_question()
    session.answer("skip")
    assert session.skip_streak == 1
    session.next_question()
    s = _reload(session, via)
    assert s.skip_streak == 1                                   # saving and resuming is not an answer
    s.next_question()
    s.answer("skip")
    assert s.next_question() == BREAK_OFFER


@pytest.mark.parametrize("via", VIA)
def test_minimal_answer_streak_survives_resume(ws, via):
    s = new_session(ws, sections=["Specific incidents", "Housing", "Current household"])
    for _ in range(2):
        s.next_question()
        assert s.pending.kind == "free_account"
        s.answer("No.")
    assert s.minimal_streak == 2
    s.next_question()
    s = _reload(s, via)
    assert s.minimal_streak == 2
    assert s.next_question() and s.pending.kind == "free_account"
    s.answer("No.")
    assert s.next_question() == BREAK_OFFER


def test_a_real_answer_after_resume_still_resets_the_streaks(session):
    session.next_question()
    session.answer("Sam Rowe arrived late.")
    session.next_question()
    session.answer("skip")
    session.next_question()
    s = _reload(session, "save_later")
    s.next_question()
    s.answer("At the library on Main Street.")
    assert s.skip_streak == 0
    s.next_question()
    s.answer("skip")
    assert s.next_question() != BREAK_OFFER


# ============================================================ 4. change-or-add (#18) across resume
def _at_which_kind(session):
    session.next_question()
    session.answer("I saw a blue car.")
    _to(session, lambda p: p.kind == "recap" and p.text.endswith(RECAP))
    session.answer("The car was green.")
    said = session.turns[-1].index
    assert session.next_question() == WHICH_KIND_QUESTION
    return said


@pytest.mark.parametrize("via", VIA)
def test_pending_change_or_add_routes_a_change_after_resume(session, via):
    said = _at_which_kind(session)
    s = _reload(session, via)
    assert s.next_question() == WHICH_KIND_QUESTION
    s.answer("Change something you have.")
    orig, new = s.facts[0], s.facts[-1]
    assert orig.status != FactStatus.CURRENT
    assert new.statement == "The car was green." and new.correction_of == orig.id
    assert new.provenance.turn_index == said                    # still traced to the words, not the reply
    assert s.corrections[-1].raw_text == "The car was green."


@pytest.mark.parametrize("via", VIA)
def test_pending_change_or_add_routes_an_addition_after_resume(session, via):
    said = _at_which_kind(session)
    s = _reload(session, via)
    assert s.next_question() == WHICH_KIND_QUESTION
    s.answer("It's something new.")
    assert s.facts[0].status == FactStatus.CURRENT and s.corrections == []
    added = s.facts[-1]
    assert added.statement == "The car was green." and added.provenance.turn_index == said


def test_change_or_add_queued_but_not_yet_shown_survives_resume(session):
    session.next_question()
    session.answer("I saw a blue car.")
    _to(session, lambda p: p.kind == "recap" and p.text.endswith(RECAP))
    session.answer("The car was green.")
    said = session.turns[-1].index
    assert session.pending is None                              # saved before the next question is shown
    s = _reload(session, "interrupt")
    assert s.next_question() == WHICH_KIND_QUESTION
    s.answer("Change something you have.")
    assert s.facts[-1].correction_of == s.facts[0].id and s.facts[-1].provenance.turn_index == said


@pytest.mark.parametrize("via", VIA)
def test_unclear_change_or_add_after_resume_keeps_the_words(session, via):
    _at_which_kind(session)
    s = _reload(session, via)
    s.next_question()
    s.answer("Not sure")
    assert len(s.facts) == 1 and s.corrections == []
    assert any(o.startswith("Recap - not yet matched as a change or an addition") and o.endswith("The car was green.")
               for o in s.open_questions)
