"""Local app: an answer is bound to the question that was on screen (isolation review finding L1).

A stale tab, a back button or a double submit is refused before anything is recorded or asked,
so a "Yes" to the immediate-danger question can never land on another question or skip the
safety pause. Over real HTTP on 127.0.0.1. ALL DATA IS SYNTHETIC AND FICTIONAL.
"""
import pytest

from laylaw.interviewer.models import SessionStatus
from test_local_app import launch_and_unlock, post_answer, qtoken_of, question_of, running  # noqa: F401

DANGER = "Is anyone in immediate danger right now?"
STALE = "That page was out of date, so nothing was saved."


@pytest.fixture
def at_danger(running):
    """An interview whose danger question is on screen in tab A."""
    app, c, *_ = running
    launch_and_unlock(app, c)
    _, h, _ = c.req("POST", "/new", {"csrf": app.csrf, "client_id": "client-fictional-a",
                                     "case_id": "CASE-FICTIONAL-777", "interviewee": "Jordan Avery",
                                     "path_name": "family_law", "adult": "yes"})
    url = h["Location"]
    post_answer(app, c, url, action="answer", answer="Yes, that's right.")    # confirm workspace
    _, _, tab_a = c.req("GET", url)
    assert question_of(tab_a) == DANGER
    session = app.session(*url.split("/")[2:4])
    return app, c, url, tab_a, session


def _tab_b(app, c, url, **form):
    """Another tab answers and follows the redirect, so the next question is now on screen."""
    post_answer(app, c, url, **form)
    return c.req("GET", url)[2]


def _snapshot(s):
    return (len(s.turns), [(i.key, i.answer) for i in s.intake], s.pending.text if s.pending else None,
            s.status, list(s.safety_notes))


@pytest.mark.parametrize("reply", ["Yes", "Yes, my neighbour Sam Rowe"])
def test_stale_yes_to_danger_is_refused_and_recorded_nowhere(at_danger, reply):
    app, c, url, tab_a, s = at_danger
    _tab_b(app, c, url, action="answer", answer="No.")                        # tab B answers the danger question
    assert s.pending.field == "urgent"
    before = _snapshot(s)
    status, headers, _ = post_answer(app, c, url, page=tab_a, action="answer", answer=reply)   # tab A, stale
    assert status == 303 and headers["Location"] == url
    assert _snapshot(s) == before                               # nothing recorded, nothing asked or advanced
    assert not any(t.answer == reply for t in s.turns)
    assert not any(i.answer == reply for i in s.intake)         # never assigned to "another urgent concern"
    _, _, page = c.req("GET", url)
    assert STALE in page and question_of(page) == s.pending.text   # told, and shown the current question


def test_yes_to_danger_from_the_current_page_still_pauses_for_safety(at_danger):
    app, c, url, tab_a, s = at_danger
    post_answer(app, c, url, page=tab_a, action="answer", answer="Yes")
    assert s.status == SessionStatus.PAUSED_FOR_SAFETY
    assert [(i.key, i.answer) for i in s.intake if i.key == "danger"] == [("danger", "Yes")]
    _, _, page = c.req("GET", url)
    assert "call 911" in page


def test_stale_tab_cannot_bypass_the_safety_pause_after_it_starts(at_danger):
    """Tab B says yes and the interview pauses; tab A's stale answer must not answer the safety check."""
    app, c, url, tab_a, s = at_danger
    safety_page = _tab_b(app, c, url, action="answer", answer="Yes")
    assert s.status == SessionStatus.PAUSED_FOR_SAFETY
    before = _snapshot(s)
    post_answer(app, c, url, page=tab_a, action="answer", answer="No, everyone is fine.")
    assert _snapshot(s) == before and s.status == SessionStatus.PAUSED_FOR_SAFETY
    post_answer(app, c, url, page=safety_page, action="answer", answer="Everyone is safe now.")
    assert s.status == SessionStatus.ACTIVE                     # the current safety page still works


@pytest.mark.parametrize("action", ["skip", "not_sure", "save_later"])
def test_stale_controls_are_refused_too(at_danger, action):
    app, c, url, tab_a, s = at_danger
    _tab_b(app, c, url, action="answer", answer="No.")
    before = _snapshot(s)
    post_answer(app, c, url, page=tab_a, action=action)
    assert _snapshot(s) == before


@pytest.mark.parametrize("token", ["", "0" * 32, "not-a-token"])
def test_missing_or_forged_token_is_refused(at_danger, token):
    app, c, url, _tab_a, s = at_danger
    before = _snapshot(s)
    c.req("POST", f"{url}/answer", {"csrf": app.csrf, "qtoken": token, "action": "answer", "answer": "Yes"})
    assert _snapshot(s) == before and s.status == SessionStatus.ACTIVE


def test_double_submit_records_the_answer_once(at_danger):
    app, c, url, tab_a, s = at_danger
    post_answer(app, c, url, page=tab_a, action="answer", answer="No.")
    c.req("GET", url)
    after_first = _snapshot(s)
    post_answer(app, c, url, page=tab_a, action="answer", answer="No.")
    assert _snapshot(s) == after_first
    assert [i.key for i in s.intake].count("danger") == 1


def test_reloading_keeps_the_same_token_and_an_answer_with_no_question_is_refused(at_danger):
    app, c, url, tab_a, s = at_danger
    _, _, again = c.req("GET", url)
    assert qtoken_of(again) == qtoken_of(tab_a) != ""           # a reload is not a new question
    s.pending = None                                            # nothing on screen to answer
    before = (len(s.turns), list(s.intake))
    post_answer(app, c, url, page=tab_a, action="answer", answer="Yes")
    assert (len(s.turns), list(s.intake)) == before             # never answers a question the person never saw


def test_stale_page_after_save_and_resume_is_refused(at_danger):
    app, c, url, tab_a, s = at_danger
    post_answer(app, c, url, page=tab_a, action="save_later")
    c.req("POST", f"{url}/resume", {"csrf": app.csrf})
    s = app.session(*url.split("/")[2:4])
    _, _, fresh = c.req("GET", url)
    assert question_of(fresh) == DANGER
    before = _snapshot(s)
    post_answer(app, c, url, page=tab_a, action="answer", answer="Yes")      # the pre-save page
    assert _snapshot(s) == before
    post_answer(app, c, url, page=fresh, action="answer", answer="Yes")
    assert s.status == SessionStatus.PAUSED_FOR_SAFETY
