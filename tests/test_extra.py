"""Extra coverage beyond the 11 required tests. Synthetic data only."""
import pytest

from laylaw.interviewer import SourceOfKnowledge, outputs, paths
from laylaw.interviewer.guard import find_advocacy


def test_criminal_defense_path_uses_same_engine_and_rules(ws):
    s, notice = paths.start_path(
        "criminal_defense", ws, case_id="CASE-FICTIONAL-CD", interviewee="Jordan Avery",
        interviewer="Laylaw Interviewer", purpose="Synthetic test", interviewee_is_adult=True,
        sections=["The events in question", "Open questions"])
    # Notice says plainly there is NO privilege; never implies there is.
    assert "not protected by attorney-client privilege" in notice
    assert "does not create an attorney-client" in notice
    assert type(s).__name__ == "InterviewSession" and s.path_name == "criminal_defense"

    s.next_question()
    s.answer("I heard from a coworker that someone reported a broken window.")
    f = s.facts[0]
    assert f.source == SourceOfKnowledge.SECONDHAND                    # same tagging rules
    assert s.next_question() == "About when was this?"                 # same one-at-a-time flow
    s.answer("maybe last month")
    assert f.date.precision.value == "RELATIVE DATE"
    assert find_advocacy(outputs.interview_record(s)) == []


def test_unknown_section_rejected_for_path(ws):
    with pytest.raises(ValueError):
        paths.start_path("criminal_defense", ws, case_id="C", interviewee="A", interviewer="L",
                         purpose="x", interviewee_is_adult=True, sections=["Your defense strategy"])


def test_present_danger_pauses_interview_and_returns_to_question(session):
    q = session.next_question()
    session.answer("He is outside right now and says he is going to hurt me.")
    assert session.status.value == "paused_for_safety"
    assert "911" in session.next_question()
    assert session.facts == []                                    # no facts collected mid-crisis
    session.answer("I'm safe now, a friend is here.")
    # Returns to the same question it paused on (orientation isn't repeated).
    assert session.next_question() == q.split("\n\n")[-1]
