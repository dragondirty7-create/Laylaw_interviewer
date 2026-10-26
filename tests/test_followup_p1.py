"""Brief A2 P1 (docs/briefs/A2-P1-and-recap-wording.md). Synthetic data only.

Names ("Jordan Avery", "Sam Rowe", "Casey Lin", child "Pip") are invented.
"""
import json
from collections import Counter

import pytest

from conftest import new_session
from laylaw.interviewer import EventKind, SessionStatus, SourceOfKnowledge, outputs, paths
from laylaw.interviewer.session import (
    BREAK_OFFER, KEEP_SHORT_NOTICE, OFFER_SKIP_TEXT, PATTERN_INSTANCE_QUESTION, REPHRASE_PREFIX, SAFETY_QUESTION,
    SAVED_FOR_LATER,
)

THREE = "Sam Rowe arrived an hour late. Pip waited with me in the car. Sam Rowe sent a text about the car."
SIX = ("Sam Rowe arrived late. Pip cried in the car. Casey Lin came outside. Sam Rowe yelled at Casey Lin. "
       "Casey Lin went back inside. Sam Rowe drove away.")
PROVENANCE_DONE = {"own_words", "answered", "confirmed_all", "confirmed_except", "unspecified"}


def _to(s, pred, filler="No."):
    for _ in range(80):
        q = s.next_question()
        assert q is not None, "interview ended first"
        if pred(s.pending):
            return q
        s.answer(filler)
    raise AssertionError("question never came")


def _scope(session, reply, text=THREE):
    session.next_question()
    session.answer(text)
    _to(session, lambda p: p.field == "source_group")
    session.answer("I saw it.")
    q = session.next_question()
    assert session.pending.field == "source_scope"
    session.answer(reply)
    return q


def assert_no_repeat(s):
    plain = Counter((a["fact"], a["intent"]) for a in s.asked if not a["why"])
    assert all(n == 1 for n in plain.values()), [k for k, n in plain.items() if n > 1]


def assert_provenance_closed(s):
    """Every item ends with a confirmed basis or one that is explicitly unspecified."""
    for f in s.facts:
        assert f.source != SourceOfKnowledge.UNKNOWN or f.source_scope in PROVENANCE_DONE, f.id


# ============================================================ 1.1 free-recall opener
@pytest.mark.parametrize("section", ["Current household", "Specific incidents", "Current parenting routine",
                                     "Housing", "Procedural history"])
def test_each_account_section_opens_with_a_free_recall_invitation(ws, section):
    s = new_session(ws, sections=[section])
    q = s.next_question()
    assert s.pending.kind == "free_account"                   # no item probe comes first
    assert "in your own words" in q.lower() and "in any order" in q.lower()
    assert "from the beginning" not in q.lower()


def test_incidents_opener_still_allows_none(ws):
    assert "It's fine to say there aren't any." in new_session(ws).free_account_prompt("Specific incidents")


@pytest.mark.parametrize("section", ["Charges as shown on paperwork", "Current requested arrangement",
                                     "Available records"])
def test_paperwork_request_and_records_prompts_are_unchanged(section):
    assert "any order" not in paths.spec_for(section).prompt
    from laylaw.interviewer.session import InterviewSession
    assert InterviewSession.free_account_prompt(section) == paths.spec_for(section).prompt


def test_follow_ups_finish_one_event_before_the_next(session):
    session.next_question()
    session.answer("On March 3, 2025, I saw Sam Rowe arrive. I saw Pip get out of the car.")
    order = [q.fact_id for q in session.queue if q.kind == "clarify"]
    assert order == sorted(order)                              # in the person's order, grouped by item


# ============================================================ scope wording (Soul's decision 1)
def test_scope_question_uses_soul_wording_and_their_words(session):
    q = _scope(session, "All of them.")
    assert q.startswith("Which of those events does that explanation apply to:")
    assert '"Sam Rowe arrived an hour late"' in q
    assert all(f.source_scope == "confirmed_all" for f in session.facts)


@pytest.mark.parametrize("reply, covered", [
    ("Just the first two.", [0, 1]), ("The first two.", [0, 1]), ("Only the last two.", [1, 2]),
    ("The first one.", [0]), ("The text one.", [2]), ("Item 2.", [1]),
])
def test_partial_scope_applies_only_to_the_events_named(session, reply, covered):
    _scope(session, reply)
    for n, f in enumerate(session.facts):
        if n in covered:
            assert f.source == SourceOfKnowledge.PERSONAL_OBSERVATION and f.source_scope.startswith("confirmed")
        else:
            assert f.source == SourceOfKnowledge.UNKNOWN and f.source_scope is None
            assert any(q.fact_id == f.id and q.field == "source" and q.why for q in session.queue)
    assert_no_repeat(session)


@pytest.mark.parametrize("reply", ["Most of them.", "I think so.", "Probably all of them.", "Some of them.",
                                   "Maybe the first two.", "Yes.", "No."])
def test_ambiguous_scope_never_applies_a_basis(session, reply):
    _scope(session, reply)
    for f in session.facts:
        assert f.source == SourceOfKnowledge.UNKNOWN and f.source_scope == "unspecified"
        assert any(o.startswith(f"{f.id}: how the interviewee knows this is unspecified")
                   for o in outputs.open_questions(session))


def test_all_except_one_names_the_one_left_out(session):
    _scope(session, "All of them except the text.")
    a, b, c = session.facts
    assert a.source_scope == b.source_scope == "confirmed_except" and c.source_scope is None


# ============================================================ "Huh?" outside follow-ups (decision 6)
def _no_new_record(s, before):
    assert (len(s.facts), len(s.corrections), len(s.outcomes), len(s.records)) == before


@pytest.mark.parametrize("kind, field", [("recap", "0"), ("recap", "1"), ("recap", "2"), ("final", "0"),
                                         ("final", "1"), ("final", "3"), ("record_hook", "section")])
def test_huh_at_recap_final_or_record_question_is_never_stored(session, kind, field):
    session.next_question()
    session.answer("Sam Rowe arrived late.")
    _to(session, lambda p: p.kind == kind and p.field == field)
    before = (len(session.facts), len(session.corrections), len(session.outcomes), len(session.records))
    session.answer("Huh?")
    _no_new_record(session, before)
    assert REPHRASE_PREFIX in session.next_question()
    assert session.pending.why.startswith("rephrased") and session.pending.kind == kind
    session.answer("What do you mean?")
    assert session.next_question().endswith(OFFER_SKIP_TEXT)
    session.answer("I'm confused")
    _no_new_record(session, before)
    assert session.asked[-1]["outcome"] == "skipped" and session.asked[-1]["intent"].startswith(kind)
    assert any("not understood, then skipped" in o for o in session.open_questions)
    assert_no_repeat(session)


def test_huh_then_an_answer_at_the_recap_is_handled_normally(session):
    session.next_question()
    session.answer("Sam Rowe arrived late.")
    _to(session, lambda p: p.kind == "recap" and p.field == "2")
    session.answer("Huh?")
    session.next_question()
    session.answer("Pip cried in the car.")
    assert [f.statement for f in session.facts][-1] == "Pip cried in the car."


def test_huh_at_the_opening_prompt_twice_then_skip(session):
    session.next_question()
    for reply in ("Huh?", "Huh?", "Huh?"):
        session.answer(reply)
        session.next_question()
    assert session.facts == [] and session.raw_answers == []
    assert any("free account question (not understood, then skipped)" in o for o in session.open_questions)


def test_huh_to_the_danger_question_still_pauses_for_safety(ws):
    from laylaw.interviewer import InterviewSession
    s = InterviewSession.start(ws, case_id="CASE-FICTIONAL-001", interviewee="Jordan Avery",
                               interviewer="Laylaw Interviewer", purpose="Synthetic test",
                               sections=["Specific incidents"], interviewee_is_adult=True,
                               preflight=["danger"])
    s.next_question()
    s.answer("Huh?")
    assert s.status == SessionStatus.PAUSED_FOR_SAFETY
    assert s.next_question() == SAFETY_QUESTION


# ============================================================ 1.2 deferred questions at the recap
def _over_the_limit(session):
    session.next_question()
    session.answer("They were probably arguing in the kitchen.")      # date, source, certainty asked; next held
    return session.facts[0]


def test_held_questions_are_offered_once_at_the_recap_with_permission(session):
    f = _over_the_limit(session)                                # who, where and what next held back
    q = _to(session, lambda p: p.kind == "deferred_permission")
    assert q == "Two quick ones before we wrap this part — OK, or save them for later?"
    session.answer("OK")
    for field in ("people_present", "location"):                # at most two, in the order held
        session.next_question()
        assert session.pending.field == field and session.pending.fact_id == f.id and session.pending.why
        session.answer("Just me")
    assert session.next_question().endswith("Did I get anything wrong?")
    held = [o for o in session.open_questions if o.startswith(f"{f.id}: not asked")]
    assert held == [f"{f.id}: not asked, to keep the interview short: What happened next?"]   # the third stays listed
    assert_no_repeat(session)


def test_saving_held_questions_for_later_keeps_them_in_open_questions(session):
    f = _over_the_limit(session)
    _to(session, lambda p: p.kind == "deferred_permission")
    session.answer("Save it for later.")
    assert session.next_question().endswith("Did I get anything wrong?")
    assert f"{f.id}: not asked, to keep the interview short: What happened next?" in session.open_questions
    assert f"{f.id}: not asked, to keep the interview short: Where did this happen?" in session.open_questions


def test_at_most_two_held_questions_and_the_basis_first(session):
    session.next_question()
    session.answer(THREE)
    _to(session, lambda p: p.field == "source_group", filler="around March 2025")
    session.answer("I'm tired.")
    assert session.next_question() == BREAK_OFFER
    session.answer("Keep going.")
    assert session.next_question().startswith(KEEP_SHORT_NOTICE)
    while session.pending.kind != "deferred_permission":
        session.answer("No.")
        session.next_question()
    assert session.pending.text.startswith("Two quick ones")
    session.answer("Sure.")
    asked = []
    for _ in range(2):
        session.next_question()
        asked.append(session.pending.field)
        session.answer("I was there for all of them.")
    assert asked[0] == "source_group"                         # unresolved provenance comes first
    assert session.next_question().endswith("Did I get anything wrong?")
    assert_no_repeat(session)
    assert_provenance_closed(session)


def test_a_held_question_already_answered_is_never_offered(session):
    _over_the_limit(session)
    for d in session.deferred:
        d.field = "date"                         # as if every held question were one already asked (date)
    _to(session, lambda p: p.kind == "recap")
    assert not any(a["intent"].startswith("deferred_permission") for a in session.asked)


# ============================================================ 1.3 tiredness and distress
def test_tired_in_words_offers_a_break_within_two_turns_and_is_not_a_fact(session):
    session.next_question()
    session.answer("Sam Rowe arrived late.")
    session.next_question()
    session.answer("I'm tired, can we stop?")
    assert len(session.facts) == 1
    assert session.next_question() == BREAK_OFFER
    session.answer("Yes, let's pause.")
    assert session.status == SessionStatus.PAUSED
    again = session.workspace.load_session(session.interview_id)
    again.resume()
    assert again.next_question() and again.pending.why == "asked again after a break offer"


def test_distress_inside_an_answer_is_recorded_and_still_offers_a_break(session):
    session.next_question()
    session.answer("Sam Rowe left. This is hard.")
    assert [f.statement for f in session.facts] == ["Sam Rowe left.", "This is hard."]
    assert session.next_question() == BREAK_OFFER


def test_keep_going_says_so_and_holds_the_rest_of_the_section(session):
    session.next_question()
    session.answer("Sam Rowe arrived late.")
    session.next_question()
    session.answer("This is a lot.")
    session.next_question()
    session.answer("I'm okay, keep going.")
    q = session.next_question()
    assert q.startswith(KEEP_SHORT_NOTICE)                     # the change of pace is said, not silent
    assert session.pending.kind in ("record_hook", "deferred_permission", "recap")
    f = session.facts[0]
    held = [o for o in session.open_questions if o.startswith(f"{f.id}: not asked, the interviewee was tired")]
    assert held                                                # nothing dropped silently
    assert "How do you know that?" in " ".join(held)           # protected checks are held, never lost


def test_two_skips_in_a_row_offer_a_break(session):
    session.next_question()
    session.answer("Sam Rowe arrived late.")
    session.next_question()
    session.answer("skip")
    session.next_question()
    session.answer("skip")
    assert session.next_question() == BREAK_OFFER


def test_three_minimal_answers_to_open_prompts_offer_a_break(ws):
    s = new_session(ws, sections=["Specific incidents", "Housing", "Current household"])
    for _ in range(3):
        s.next_question()
        assert s.pending.kind == "free_account"
        s.answer("No.")
    assert s.next_question() == BREAK_OFFER


def test_short_answers_to_closed_questions_are_not_tiredness(session):
    session.next_question()
    session.answer("On a Friday, Sam Rowe arrived late to the exchange.")
    for reply in ("March 2025", "Just me", "Library"):
        q = session.next_question()
        assert q != BREAK_OFFER
        session.answer(reply)
    assert BREAK_OFFER not in [t.question for t in session.turns]


def test_break_is_offered_once_per_section(session):
    session.next_question()
    session.answer("Sam Rowe arrived late. This is hard.")
    assert session.next_question() == BREAK_OFFER
    session.answer("Keep going")
    for _ in range(10):
        q = session.next_question()
        if q is None or session.current_section != "Specific incidents":
            break
        assert session.pending.kind != "break_offer"
        session.answer("I'm tired.")


# ============================================================ 1.4 patterns
def test_a_pattern_is_stored_as_a_pattern_and_asks_for_one_time(session):
    session.next_question()
    session.answer("Sam Rowe always picks Pip up late.")
    f = session.facts[0]
    assert f.kind == EventKind.ROUTINE
    texts = [q.text for q in session.queue if q.kind == "clarify"]
    assert PATTERN_INSTANCE_QUESTION in texts
    assert "Who else was there?" not in texts and "Where did this happen?" not in texts


def test_nothing_is_copied_from_a_pattern_to_the_time_that_stands_out(session):
    session.next_question()
    session.answer("Sam Rowe always picks Pip up late.")
    pattern = session.facts[0]
    session.set_people_present(pattern.id, "Casey Lin")
    session.set_fact_location(pattern.id, "the school")
    _to(session, lambda p: p.text == PATTERN_INSTANCE_QUESTION)
    session.answer("One time in March he came two hours late.")
    one = session.facts[-1]
    assert one.kind != EventKind.ROUTINE
    assert one.people_present == [] and one.location is None
    assert one.source == SourceOfKnowledge.UNKNOWN and one.source_scope is None


# ============================================================ 1.5 certainty asked once
def test_certainty_is_stored_once_in_their_words_with_time_and_scale(session):
    session.next_question()
    session.answer("They were probably arguing.")
    _to(session, lambda p: p.field == "certainty")
    session.answer("Pretty sure about the arguing.")
    f = session.facts[0]
    (reading,) = f.certainty_readings
    assert reading["text"] == "Pretty sure about the arguing." and reading["turn"] == session.turns[-1].index
    assert reading["at"] and reading["scale"] == "fairly sure"
    rest = []
    for _ in range(40):
        if session.next_question() is None:
            break
        rest.append((session.pending.fact_id, session.pending.field))
        session.answer("No.")
    assert (f.id, "certainty") not in rest                     # never re-asked, recap included


@pytest.mark.parametrize("text, scale", [("Very sure.", "sure"), ("I'm certain.", "sure"),
                                         ("Not very sure.", "unsure"), ("Sure about the time but not the place.", None),
                                         ("It was dark.", None)])
def test_certainty_scale_only_when_unambiguous(text, scale):
    from laylaw.interviewer.classify import certainty_scale
    assert certainty_scale(text) == scale


# ============================================================ "I don't know" stays visible (decision 2)
@pytest.mark.parametrize("field", ["date", "people_present"])
def test_dont_know_shows_on_the_record_and_in_every_output(session, field):
    session.next_question()
    session.answer("Sam Rowe arrived at the exchange.")
    _to(session, lambda p: p.field == field)
    session.answer("I don't know")
    out = outputs.all_outputs(session)
    f = session.facts[0]
    assert any("doesn't know" in n for n in f.open_questions)          # on the fact record itself
    for name in ("interview_record", "fact_table", "timeline"):        # every output that lists items
        assert "doesn't know" in json.dumps(out[name], default=str), name
    assert "Skipped or 'not sure' answers: 1" in out["handoff_summary"]


# ============================================================ §5.4 fixtures
def _rambler(p):
    return "Well, it was a long day and I remember a lot about it, the weather was grey and Pip was tired."


PERSONAS = {
    "rambler": (SIX, _rambler),
    "goes_quiet": (THREE, lambda p: "No."),
    "distressed": (THREE, lambda p: "I'm tired, can we stop?" if p.kind == "clarify" else "Keep going"),
    "dont_know_repeater": (THREE, lambda p: "I don't know"),
    "many_events": (SIX, lambda p: "I was there for all of them." if p.field == "source_group" else "No."),
}


def run_persona(ws, name, limit=300):
    opening, reply = PERSONAS[name]
    s = new_session(ws, sections=["Specific incidents"])
    asked = []
    for _ in range(limit):
        q = s.next_question()
        if q is None:
            return s, asked, True
        p = s.pending
        if p.kind in ("clarify", "record_hook"):
            asked.append((p.fact_id, p.field))
        if p.kind == "free_account":
            s.answer(opening)
        elif p.kind == "break_offer":
            s.answer("Keep going")
        elif p.kind in ("clarify", "record_hook", "deferred_permission"):
            s.answer(reply(p))
        else:
            s.answer("No.")
    return s, asked, False


@pytest.mark.parametrize("name", PERSONAS)
def test_fixture_invariants(ws, name):
    s, asked, finished = run_persona(ws, name)
    assert finished
    assert_no_repeat(s)
    assert_provenance_closed(s)
    per_fact = Counter(a["fact"] for a in s.asked if a["fact"] and not a["why"] and a["intent"] != "source_scope")
    assert max(per_fact.values(), default=0) <= 3
    assert not any(f.statement.lower().startswith(("huh", "i'm tired")) for f in s.facts)
