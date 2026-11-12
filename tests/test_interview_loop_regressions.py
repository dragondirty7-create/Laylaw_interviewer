"""Synthetic regression coverage for short, accurate interviewer turns.

This file contains no client records or real-world case material.
"""
import pytest

from conftest import new_session
from laylaw.interviewer import SessionStatus
from laylaw.interviewer.session import _is_nothing_more


@pytest.mark.parametrize("answer", [
    "No", "No.", "No, that's all.", "No that's all", "No, that's it.",
    "No that is all", "Nope, nothing else.", "Nah, nothing more.",
    "That's everything.", "That's all.", "That is all.", "I think that's it.",
    "Nothing else", "Nothing more", "No, I think that's it.", "Nope, that's everything!",
])
def test_completion_phrases_are_not_recorded_as_facts(ws, answer):
    s = new_session(ws, sections=["Specific incidents"])
    assert _is_nothing_more(answer)
    s.next_question()
    s.answer(answer)
    assert s.facts == []
    assert s.raw_answers == []
    assert not any(q.kind == "clarify" for q in s.queue)
    assert s.next_question() == "Did I get anything wrong?" or s.next_question() is not None


@pytest.mark.parametrize("answer", [
    "No, then a neighbor came by.",
    "No, the gate was left open.",
    "No, that's all I could see before the lights went out.",
    "Nothing else happened until the following morning.",
    "Nope, nothing more was said but the car was gone.",
])
def test_content_qualifications_are_not_treated_as_endings(ws, answer):
    assert not _is_nothing_more(answer)
    s = new_session(ws)
    s.next_question()
    s.answer(answer)
    assert any(f.statement == answer for f in s.facts)


def test_five_incidents_cap_clarifications_and_keep_deferred_questions(ws):
    s = new_session(ws)
    s.next_question()
    s.answer(
        "A package was left at the gate. A courier called the office. "
        "A receptionist signed the log. The delivery van left. A supervisor called back."
    )
    followups = [q for q in s.queue if q.kind == "clarify"]
    hooks = [q for q in s.queue if q.kind == "record_hook"]
    assert len(s.facts) == 5
    assert len(followups) <= 15
    assert len(hooks) == 1
    assert any("Deferred for follow-up" in item for f in s.facts for item in f.open_questions)


def test_routine_does_not_prompt_event_location_or_sequence(ws):
    s = new_session(ws, sections=["Current parenting routine"])
    s.next_question()
    s.answer("I usually check the shared calendar every Tuesday.")
    prompts = [q.text for q in s.queue]
    assert "Where did this happen?" not in prompts
    assert "Who else was there?" not in prompts
    assert "What happened next?" not in prompts
    assert "Was there a particular time that was different?" in prompts


def test_section_record_hook_is_asked_once_even_with_multiple_facts(ws):
    s = new_session(ws)
    s.next_question()
    s.answer("I saw a blue truck. I heard a horn.")
    assert sum(q.kind == "record_hook" for q in s.queue) == 1
    prompts = [q.text for q in s.queue]
    assert prompts.index("Is there anything that might help document or date this?") > max(
        i for i, q in enumerate(s.queue) if q.kind == "clarify"
    )


@pytest.mark.parametrize("answer", [
    "Can we pause right now?", "Could we stop here?", "I want to pause for now.",
    "I need to stop right now.", "Let's stop for now.",
])
def test_natural_pause_intents_save_without_making_facts(ws, answer):
    s = new_session(ws)
    first = s.next_question()
    assert first is not None
    assert s.answer(answer) == "Saved. When you come back, we'll pick up at the same question."
    assert s.status == SessionStatus.PAUSED
    assert s.facts == []
    reopened = s.workspace.load_session(s.interview_id)
    assert reopened.status == SessionStatus.PAUSED
    assert reopened.pending.text == first
