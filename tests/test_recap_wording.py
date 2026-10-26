"""Brief A2-next, part 2: recap, record and closing wording (Soul, decision 5). Synthetic data only.

Names ("Jordan Avery", "Sam Rowe", "Casey Lin", child "Pip") are invented.
"""
import re

import pytest

from conftest import new_session
from laylaw.interviewer.models import FactStatus
from laylaw.interviewer.session import (
    _CHECK_FOLLOWUPS, END_OF_SECTION_QUESTIONS, FINAL_CHECK_QUESTIONS, OFFER_SKIP_TEXT, RECORD_HOOK_QUESTION,
    REPHRASE_PREFIX, SECTION_RECORD_HOOK_QUESTION, WHICH_KIND_QUESTION, PendingQuestion,
)

RECAP = "What did I get wrong or leave out?"


def _to(s, pred, filler="No."):
    for _ in range(60):
        q = s.next_question()
        assert q is not None
        if pred(q):
            return q
        s.answer(filler)
    raise AssertionError("question never came")


def _at_recap(session, account="I saw a blue car."):
    session.next_question()
    session.answer(account)
    return _to(session, lambda q: q.endswith(RECAP))


# ============================================================ wording
def test_recap_is_one_open_check_plus_the_separate_certainty_check():
    assert END_OF_SECTION_QUESTIONS == [RECAP, "Did I make anything sound more certain than you intended?"]


def test_record_and_final_questions_say_something_not_anything():
    assert RECORD_HOOK_QUESTION == "Is there something else that might help document this?"
    assert SECTION_RECORD_HOOK_QUESTION.startswith("Is there something else that might help document")
    for q in FINAL_CHECK_QUESTIONS[:3] + [RECORD_HOOK_QUESTION, SECTION_RECORD_HOOK_QUESTION]:
        assert "something" in q and not re.search(r"\banything\b", q), q
    assert "more definite than you remember" in FINAL_CHECK_QUESTIONS[2]      # certainty check kept at the end too


BANNED = [r"\bis that right\?", r"(?:^|[.!?]\s+)correct\?", r"\banything else\b"]


def test_lint_recap_and_closing_templates(session):
    _at_recap(session, "I saw a blue car. Sam Rowe was driving it.")
    texts = (END_OF_SECTION_QUESTIONS + FINAL_CHECK_QUESTIONS + list(_CHECK_FOLLOWUPS.values())
             + [WHICH_KIND_QUESTION, RECORD_HOOK_QUESTION, SECTION_RECORD_HOOK_QUESTION, session.section_recap(),
                session.summary_review()])
    for text in texts:
        for pat in BANNED:
            assert not re.search(pat, text, flags=re.I), (pat, text)


def test_record_question_is_still_asked_once_before_the_recap(session):
    """The optional move to after the recap was not made (see PR); position and once-only are unchanged."""
    session.next_question()
    session.answer("Sam Rowe arrived late. Pip waited in the car.")
    kinds = [q.kind for q in session.queue]
    assert kinds.count("record_hook") == 1 and kinds.index("record_hook") < kinds.index("recap")


# ============================================================ one open check: correction or addition, never guessed
@pytest.mark.parametrize("reply", ["It was a green car.", "Actually the car was green.", "The car wasn't blue.",
                                   "No, it was green, not blue."])
def test_clear_correction_words_go_to_a_correction(session, reply):
    _at_recap(session)
    session.answer(reply)
    orig, new = session.facts[0], session.facts[-1]
    assert orig.status == FactStatus.SUPERSEDED and new.correction_of == orig.id


@pytest.mark.parametrize("reply", ["Sam Rowe also honked the horn.", "I forgot, Pip was in the back seat.",
                                   "You left out the rain.", "One more thing: the lights were off."])
def test_clear_addition_words_go_to_an_addition(session, reply):
    _at_recap(session)
    session.answer(reply)
    assert session.facts[0].status == FactStatus.CURRENT and session.corrections == []
    assert session.facts[-1].correction_of is None and len(session.facts) >= 2


@pytest.mark.parametrize("reply", ["The car was green.", "Sam Rowe honked the horn.",
                                   "Actually, Pip was also there."])            # neither, or both
def test_unclear_content_asks_change_or_add_and_changes_nothing_yet(session, reply):
    _at_recap(session)
    before = [(f.statement, f.status) for f in session.facts]
    session.answer(reply)
    assert session.next_question() == WHICH_KIND_QUESTION
    assert [(f.statement, f.status) for f in session.facts] == before and session.corrections == []


def test_change_routes_the_earlier_words_as_a_correction_with_their_turn(session):
    _at_recap(session)
    session.answer("The car was green.")
    said = session.turns[-1].index
    session.next_question()
    session.answer("Change something you have.")
    orig, new = session.facts[0], session.facts[-1]
    assert new.statement == "The car was green." and new.correction_of == orig.id
    assert new.provenance.turn_index == said                   # traced to the words, not to "change it"
    assert session.corrections[-1].raw_text == "The car was green."


def test_new_routes_the_earlier_words_as_an_addition_with_their_turn(session):
    _at_recap(session)
    session.answer("Sam Rowe honked the horn.")
    said = session.turns[-1].index
    session.next_question()
    session.answer("It's something new.")
    assert session.facts[0].status == FactStatus.CURRENT and session.corrections == []
    added = session.facts[-1]
    assert added.statement == "Sam Rowe honked the horn." and added.provenance.turn_index == said


@pytest.mark.parametrize("reply", ["Not sure", "No.", "Hmm.", "Both, kind of."])
def test_unclear_change_or_add_keeps_the_words_and_guesses_nothing(session, reply):
    _at_recap(session)
    session.answer("The car was green.")
    session.next_question()
    session.answer(reply)
    assert len(session.facts) == 1 and session.corrections == []
    assert any(o.startswith("Recap - not yet matched as a change or an addition") and o.endswith("The car was green.")
               for o in session.open_questions)


def test_huh_at_change_or_add_is_rephrased_never_stored(session):
    _at_recap(session)
    session.answer("The car was green.")
    session.next_question()
    session.answer("Huh?")
    assert REPHRASE_PREFIX in session.next_question()
    session.answer("What do you mean?")
    assert session.next_question() == OFFER_SKIP_TEXT
    assert len(session.facts) == 1 and session.corrections == []


def test_bare_yes_still_never_replaces_anything(session):
    _at_recap(session)
    session.answer("Yes")
    assert session.next_question() == "What should I change or add?"
    assert len(session.facts) == 1 and session.corrections == []


def test_legacy_session_with_the_separate_missed_check_still_adds(session):
    """Sessions saved before the two-check recap may still hold the old third check."""
    _at_recap(session)
    session.queue.insert(0, PendingQuestion("recap", "Is there anything important I missed?", field="2"))
    session.answer("No.")
    session.next_question()
    session.answer("Huh?")                                     # still rephrased, never stored
    assert REPHRASE_PREFIX in session.next_question() and len(session.facts) == 1
    session.answer("Sam Rowe honked the horn.")
    assert session.facts[-1].statement == "Sam Rowe honked the horn." and session.facts[0].status == FactStatus.CURRENT
