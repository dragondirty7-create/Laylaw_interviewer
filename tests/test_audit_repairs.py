"""Regression tests for the Soul audit of PR #1 at fdd7d449 (seven HIGH/MEDIUM items).

Every test reproduces the audit's example (or its required coverage) and fails on
fdd7d449. ALL DATA IS SYNTHETIC AND FICTIONAL.

Numbering follows the repair order requested for this pass:
  1 provenance   2 unknown basis   3 ack/addition/correction   4 discrepancy binding
  5 attributed wording vs advocacy guard   6 immediate-danger preflight   7 conflict labels
"""
import json

import pytest

from conftest import new_session
from laylaw.interviewer import (
    Mode, ModeViolation, SessionStatus, SourceOfKnowledge, outputs, paths,
)
from laylaw.interviewer.guard import assert_no_advocacy
from laylaw.interviewer.models import FactStatus
from laylaw.interviewer.session import ProvenanceError, SAFETY_QUESTION

RECAP_WRONG = "Did I get anything wrong?"
RECAP_CERTAIN = "Did I make anything sound more certain than you intended?"
RECAP_MISSED = "Is there anything important I missed?"
FINAL_CORRECT = "Is there anything we discussed that you want to correct?"
FINAL_DEFINITE = "Did I make anything sound more definite than you remember it?"
DANGER_Q = "Is anyone in immediate danger right now?"


def advance_to(s, predicate, filler="skip"):
    """Answer every question with `filler` until one matches `predicate`; return it."""
    for _ in range(200):
        q = s.next_question()
        assert q is not None, "interview ended before the expected question"
        if predicate(q):
            return q
        s.answer(filler)
    raise AssertionError("expected question never came")


def ends(text):
    return lambda q: q.endswith(text)


def assert_every_fact_traceable(s):
    """Each fact is an exact slice of a logged answer, tied to a real turn."""
    turn_answers = {t.index: t.answer for t in s.turns}
    for f in s.facts:
        assert f.raw_answer_id is not None and f.span is not None, f.id
        raw = next(r for r in s.raw_answers if r.id == f.raw_answer_id)
        assert raw.text[f.span[0]:f.span[1]] == f.statement, f.id
        assert raw.turn_index in turn_answers, f.id
        assert raw.text in turn_answers[raw.turn_index], f.id


# ======================================================== 1. provenance
def test_1_generated_text_cannot_be_recorded_as_an_interview_fact(session):
    # Audit reproduction: this succeeded with INTERVIEW provenance, no answer, no turn.
    with pytest.raises(ProvenanceError):
        session.record_fact("Generated sentence with no human answer.", topic="Specific incidents")
    assert session.facts == [] and session.raw_answers == [] and session.turns == []


def test_1_corrections_and_alternate_accounts_require_traceable_source_text(session):
    session.next_question()
    session.answer("I saw a blue car.")
    fid = session.facts[0].id
    with pytest.raises(ProvenanceError):
        session.correct_fact(fid, "Generated correction with no human answer.")
    with pytest.raises(ProvenanceError):
        session.record_conflicting_account(fid, "Generated alternate account with no human answer.")
    assert [f.id for f in session.facts] == [fid]
    assert session.facts[0].status == FactStatus.CURRENT and session.corrections == []


def test_1_paraphrases_of_a_logged_answer_are_refused_everywhere(session):
    session.next_question()
    session.answer("I saw a blue car.")
    raw = session.raw_answers[0]
    fid = session.facts[0].id
    with pytest.raises(ProvenanceError):
        session.record_fact("The interviewee observed a blue vehicle.", topic="Specific incidents",
                            raw_answer_id=raw.id, span=[0, len(raw.text)])
    alt = session.log_answer("It might have been a van.", question="Was it a car?")
    with pytest.raises(ProvenanceError):
        session.correct_fact(fid, "The vehicle was a van.", raw_answer_id=alt.id)
    with pytest.raises(ProvenanceError):
        session.record_conflicting_account(fid, "The vehicle was a van.", raw_answer_id=alt.id)
    # The verbatim words are accepted, linked, and the original is kept.
    new = session.record_conflicting_account(fid, "It might have been a van.", raw_answer_id=alt.id)
    assert new.raw_answer_id == alt.id and session.get_fact(fid).status == FactStatus.CURRENT
    assert_every_fact_traceable(session)


def test_1_valid_verbatim_answers_and_linked_corrections_still_work(ws):
    s = new_session(ws)
    s.next_question()
    s.answer("I saw a blue car.")
    advance_to(s, ends(RECAP_WRONG))
    s.answer("It was a green car.")
    orig, new = s.facts[0], s.facts[1]
    assert orig.status == FactStatus.SUPERSEDED and new.correction_of == orig.id
    assert new.statement == "It was a green car."
    assert new.provenance.turn_index == s.turns[-1].index
    assert_every_fact_traceable(s)
    f = s.record_statement("Sam Rowe drove it.", topic="Specific incidents", question="Who drove?")
    assert f.provenance.turn_index == s.turns[-1].index and s.turns[-1].question == "Who drove?"
    assert_every_fact_traceable(s)


# ======================================================== 2. unknown basis of knowledge
def test_2_unsourced_claim_stays_unknown_everywhere_and_after_reload(ws, store):
    s = new_session(ws)
    s.next_question()
    s.answer("They were using drugs.")                     # audit reproduction
    f = s.facts[0]
    assert f.source == SourceOfKnowledge.UNKNOWN            # not PERSONAL_OBSERVATION
    assert any(q.kind == "clarify" and q.field == "source" and q.text == "How do you know that?"
               for q in s.queue)
    out = outputs.all_outputs(s)
    assert out["fact_table"][0]["KNOWLEDGE SOURCE"] == "UNKNOWN"
    assert out["timeline"][0]["SOURCE OF KNOWLEDGE"] == "UNKNOWN"
    assert "[UNKNOWN] | Recollection" in out["interview_record"]
    assert "UNKNOWN 1" in out["handoff_summary"]
    assert "PERSONAL-OBSERVATION" not in json.dumps(out, default=str)
    again = store.workspace(ws.client_id).load_session(s.interview_id)
    assert again.facts[0].source == SourceOfKnowledge.UNKNOWN


@pytest.mark.parametrize("basis, expected", [
    ("I was there and saw it.", SourceOfKnowledge.PERSONAL_OBSERVATION),
    ("My cousin told me.", SourceOfKnowledge.SECONDHAND),
    ("I assumed it.", SourceOfKnowledge.INFERENCE),
    ("I just know.", SourceOfKnowledge.UNKNOWN),
])
def test_2_how_do_you_know_answer_sets_the_basis_without_assuming(session, basis, expected):
    session.next_question()
    session.answer("They were using drugs.")
    advance_to(session, lambda q: q == "How do you know that?")
    session.answer(basis)
    assert session.facts[0].source == expected


@pytest.mark.parametrize("said, expected", [
    ("I saw a blue car.", SourceOfKnowledge.PERSONAL_OBSERVATION),
    ("My sister told me the gate was open.", SourceOfKnowledge.SECONDHAND),
    ("He must have left early.", SourceOfKnowledge.INFERENCE),
    ("The email said the meeting moved.", SourceOfKnowledge.DOCUMENT_RECOLLECTION),
    ("Sam Rowe was late again.", SourceOfKnowledge.UNKNOWN),
])
def test_2_explicit_sources_are_still_typed_correctly(session, said, expected):
    session.next_question()
    session.answer(said)
    assert session.facts[0].source == expected


# ======================================================== 3. ack / addition / correction
@pytest.mark.parametrize("ack", ["Yes", "yes.", "Yeah", "Yep", "Actually, yes"])
def test_3_bare_yes_at_recap_never_replaces_a_single_fact(session, ack):
    session.next_question()
    session.answer("I saw a blue car.")                     # audit reproduction
    advance_to(session, ends(RECAP_WRONG))
    session.answer(ack)
    f = session.facts[0]
    assert len(session.facts) == 1 and f.status == FactStatus.CURRENT
    assert f.statement == "I saw a blue car." and session.corrections == []
    assert session.next_question() == "What should I change?"
    session.answer("It was a green car.")
    assert session.facts[-1].statement == "It was a green car."
    assert session.facts[-1].correction_of == f.id and f.status == FactStatus.SUPERSEDED


def test_3_bare_yes_with_multiple_candidates_asks_for_content_before_the_item(session):
    session.next_question()
    session.answer("I saw a blue car. Sam Rowe was driving it.")
    advance_to(session, ends(RECAP_WRONG))
    session.answer("Yes")
    assert session.next_question() == "What should I change?"   # not the numbered list
    session.answer("The car was green.")
    q = session.next_question()
    assert q.endswith("Which numbered item does that change?")
    session.answer("1")
    first, new = session.facts[0], session.facts[-1]
    assert new.statement == "The car was green." and new.correction_of == first.id
    assert all(f.statement.lower().strip(". ") != "yes" for f in session.facts)
    assert session.facts[1].status == FactStatus.CURRENT


def test_3_yes_with_content_uses_only_the_content(session):
    session.next_question()
    session.answer("I saw a blue car.")
    advance_to(session, ends(RECAP_WRONG))
    session.answer("Yes, it was a green car.")
    new = session.facts[-1]
    assert new.statement == "it was a green car." and new.correction_of == session.facts[0].id
    assert session.corrections[-1].raw_text == "Yes, it was a green car."    # full words kept


@pytest.mark.parametrize("neg", ["No", "No, that's right.", "Looks good"])
def test_3_bare_no_at_recap_changes_nothing(session, neg):
    session.next_question()
    session.answer("I saw a blue car.")
    advance_to(session, ends(RECAP_WRONG))
    session.answer(neg)
    assert len(session.facts) == 1 and session.corrections == []


def test_3_bare_yes_to_certainty_question_asks_which_part(session):
    session.next_question()
    session.answer("I saw a blue car.")
    advance_to(session, ends(RECAP_CERTAIN))
    session.answer("Yes")
    assert len(session.facts) == 1 and session.corrections == []
    assert session.next_question() == "Which part did I make sound more certain than you meant?"


def test_3_missed_items_are_recorded_as_additions_not_replacements(session):
    session.next_question()
    session.answer("I saw a blue car.")
    advance_to(session, ends(RECAP_MISSED))
    session.answer("Sam Rowe also honked the horn.")        # audit: routed into replacement
    first = session.facts[0]
    assert first.status == FactStatus.CURRENT and session.corrections == []
    added = session.facts[1]
    assert added.statement == "Sam Rowe also honked the horn." and added.correction_of is None
    assert added.status == FactStatus.CURRENT
    assert_every_fact_traceable(session)


def test_3_bare_yes_to_missed_asks_what_was_missed_then_adds(session):
    session.next_question()
    session.answer("I saw a blue car.")
    advance_to(session, ends(RECAP_MISSED))
    session.answer("Yes")
    assert len(session.facts) == 1
    assert session.next_question() == "What did I miss?"
    session.answer("Sam Rowe honked the horn.")
    assert [f.status for f in session.facts] == [FactStatus.CURRENT, FactStatus.CURRENT]
    assert session.corrections == []


@pytest.mark.parametrize("question, follow", [
    (FINAL_CORRECT, "What should I change?"),
    (FINAL_DEFINITE, "Which part did I make sound more certain than you meant?"),
])
def test_3_bare_yes_at_final_check_never_replaces_a_fact(ws, question, follow):
    for facts_text in ("I saw a blue car.", "I saw a blue car. Sam Rowe was driving it."):
        s = new_session(ws)
        s.next_question()
        s.answer(facts_text)
        advance_to(s, lambda q: q.endswith(question), filler="No")
        before = [(f.statement, f.status) for f in s.facts]
        s.answer("Yes")
        assert [(f.statement, f.status) for f in s.facts] == before and s.corrections == []
        assert s.next_question() == follow


def test_3_bare_no_at_final_check_changes_nothing(session):
    session.next_question()
    session.answer("I saw a blue car.")
    advance_to(session, lambda q: q == FINAL_CORRECT, filler="No")
    session.answer("No")
    assert len(session.facts) == 1 and session.corrections == []


# ======================================================== 4. discrepancy binding
def _two_conflicts(s, order):
    s.next_question()
    s.answer("I saw a blue car.")
    fid = s.facts[0].id
    for which in order:
        if which == "location":
            s.set_fact_location(fid, "the Library")
            s.set_fact_location(fid, "the Park")
        else:
            s.set_people_present(fid, "Alex")
            s.set_people_present(fid, "Taylor")
    return {d.field: d for d in s.discrepancies}


def test_4_answer_resolves_the_discrepancy_that_was_asked_about(session):
    ds = _two_conflicts(session, ["location", "people"])          # audit reproduction
    q = session.next_question()
    assert '"Alex"' in q and '"Taylor"' in q
    session.answer("Taylor was there.")
    assert ds["people_present"].status == "clarified by interviewee"
    assert ds["location"].status == "unresolved"
    q2 = session.next_question()
    assert '"the Library"' in q2 and '"the Park"' in q2
    session.answer("It was the Park.")
    assert ds["location"].status == "clarified by interviewee"


def test_4_reversed_queue_order_binds_correctly(session):
    ds = _two_conflicts(session, ["people", "location"])
    q = session.next_question()
    assert '"the Library"' in q and '"the Park"' in q
    session.answer("It was the Park.")
    assert ds["location"].status == "clarified by interviewee"
    assert ds["people_present"].status == "unresolved"


def test_4_skip_is_noted_on_the_asked_discrepancy_only(session):
    ds = _two_conflicts(session, ["location", "people"])
    session.next_question()
    session.skip()
    assert ds["people_present"].resolution_note == "Interviewee: skipped"
    assert ds["location"].resolution_note is None


def test_4_binding_survives_interrupt_and_resume(ws, store):
    s = new_session(ws)
    ds = _two_conflicts(s, ["location", "people"])
    asked = s.next_question()
    assert '"Taylor"' in asked
    s.save_and_finish_later()
    again = store.workspace(ws.client_id).load_session(s.interview_id)
    again.resume()
    assert again.next_question() == asked
    again.answer("Taylor was there.")
    got = {d.field: d for d in again.discrepancies}
    assert got["people_present"].status == "clarified by interviewee"
    assert got["location"].status == "unresolved"
    assert ds["location"].id == got["location"].id


# ======================================================== 5. attributed wording vs guard
def test_5_client_wording_is_preserved_in_recaps_and_all_seven_outputs(session):
    session.next_question()
    session.answer("He was abusive.")                      # audit reproduction
    fid = session.facts[0].id
    alt = session.log_answer("He was abusive toward the dog.", question="Tell me about that.")
    session.record_conflicting_account(fid, alt.text, raw_answer_id=alt.id)
    session.record_request("I want the court to know he was abusive.")
    session._apply_record_hook(type("Q", (), {"fact_id": fid})(), "My neighbor says he was abusive")
    rec = session.add_upload("report-FICTIONAL.pdf", b"fictional", label="Report (fictional)",
                             related_fact_ids=[fid])
    session.mark_record_reviewed(rec.id)
    session.add_document_finding(fid, rec.id, "The report says he was abusive.")

    recap_q = advance_to(session, ends(RECAP_WRONG))
    assert "He was abusive." in recap_q
    assert "He was abusive." in session.section_recap()
    assert "He was abusive." in session.summary_review()
    out = outputs.all_outputs(session)                     # raised ModeViolation at fdd7d449
    assert "He was abusive." in out["interview_record"]
    assert "The report says he was abusive." in out["interview_record"]
    assert any("He was abusive." in r["STATEMENT"] for r in out["fact_table"])
    assert any("He was abusive." in e["WHAT HAPPENED"] for e in out["timeline"])
    assert any("he was abusive" in x for x in out["evidence_followup"])
    assert any("He was abusive." in x for x in out["open_questions"])
    assert out["requested_outcomes"][0]["REQUEST"] == "I want the court to know he was abusive."
    assert "HANDOFF SUMMARY" in out["handoff_summary"]
    # Attribution is kept: the wording is labeled as the interviewee's recollection.
    assert "Recollection (paraphrase of interviewee's answer): He was abusive." in out["interview_record"]


def test_5_assistant_authored_advocacy_still_fails(session, monkeypatch):
    session.next_question()
    session.answer("He was abusive.")
    with pytest.raises(ModeViolation):
        assert_no_advocacy("He was abusive.", Mode.INTERVIEW)            # no attribution given
    with pytest.raises(ModeViolation):
        assert_no_advocacy("This helps your case.", Mode.INTERVIEW, attributed=["He was abusive."])
    with pytest.raises(ModeViolation):
        session._emit("You should argue that he was abusive.")
    with pytest.raises(ModeViolation):
        session._emit("He is dangerous.")
    # Generated renderer text is still checked in every output.
    monkeypatch.setattr(outputs, "date_text", lambda f: "The judge will likely agree")
    for render in (outputs.interview_record, outputs.fact_table, outputs.timeline):
        with pytest.raises(ModeViolation):
            render(session)


# ======================================================== 6. immediate danger
def _family(ws, case="CASE-FICTIONAL-DANGER"):
    s, _ = paths.start_path("family_law", ws, case_id=case, interviewee="Jordan Avery",
                            interviewer="Laylaw Interviewer", purpose="Synthetic intake",
                            interviewee_is_adult=True)
    s.next_question()
    s.answer("Yes")                                          # workspace confirmed
    return s


@pytest.mark.parametrize("reply", ["Yes", "yes.", "Yeah", "I think so", "Maybe", "I'm not sure", "not sure"])
def test_6_affirmative_or_uncertain_danger_answer_pauses(ws, reply):
    s = _family(ws)
    assert s.next_question() == DANGER_Q                     # asked on its own
    s.answer(reply)                                          # audit: "Yes" left it ACTIVE
    assert s.status == SessionStatus.PAUSED_FOR_SAFETY
    assert s.next_question() == SAFETY_QUESTION
    assert s.facts == []


def test_6_no_danger_then_ordinary_urgency_does_not_pause(ws):
    s = _family(ws)
    assert s.next_question() == DANGER_Q
    s.answer("No")
    assert s.status == SessionStatus.ACTIVE
    q = s.next_question()
    assert "urgent concern" in q and "danger" not in q
    s.answer("Yes, a filing is due tomorrow.")
    assert s.status == SessionStatus.ACTIVE
    assert s.next_question().startswith("Is there a court hearing or other deadline")
    assert [i.key for i in s.intake] == ["confirm_workspace", "danger", "urgent"]
    assert s.facts == []                                     # administrative intake only


def test_6_skipping_the_danger_question_is_recorded_not_treated_as_safe(ws):
    s = _family(ws)
    s.next_question()
    s.skip()
    assert s.intake[-1].key == "danger" and s.intake[-1].status == "skipped"
    assert any("danger" in n for n in s.safety_notes)


def test_6_pause_survives_reload_and_resumes_after_safety_check(ws, store):
    s = _family(ws)
    s.next_question()
    s.answer("Yes")
    again = store.workspace(ws.client_id).load_session(s.interview_id)
    again.resume()
    assert again.status == SessionStatus.PAUSED_FOR_SAFETY
    assert again.next_question() == SAFETY_QUESTION
    again.answer("No")                                       # not safe yet -> stays paused
    assert again.status == SessionStatus.PAUSED_FOR_SAFETY
    assert again.next_question() == SAFETY_QUESTION
    again.answer("I'm safe now.")
    assert again.status == SessionStatus.ACTIVE
    q = again.next_question()
    assert "urgent concern" in q                             # danger is not re-asked


# ======================================================== 7. discrepancy labels
def _build(s, field):
    s.next_question()
    s.answer("I saw a blue car. Sam Rowe was driving it.")
    a, b = s.facts[0].id, s.facts[1].id
    if field == "location":
        s.set_fact_location(a, "Library")
        s.set_fact_location(a, "Park")
    elif field == "people_present":
        s.set_people_present(a, "Alex")
        s.set_people_present(a, "Taylor")
    elif field == "sequence":
        s.record_sequence(a, "before", b)
        s.record_sequence(a, "after", b)
    elif field == "account":
        alt = s.log_answer("I saw a red truck.", question="Tell me again what you saw.")
        s.record_conflicting_account(a, alt.text, raw_answer_id=alt.id)
    elif field == "date":
        s.set_fact_date(a, "around March 2025")
        s.set_fact_date(a, "maybe May 2025")
    assert [d.field for d in s.discrepancies] == [field]
    return s.discrepancies[0]


LABELS = {"location": "[UNRESOLVED LOCATION DISCREPANCY]",
          "people_present": "[UNRESOLVED PEOPLE PRESENT DISCREPANCY]",
          "sequence": "[UNRESOLVED SEQUENCE DISCREPANCY]",
          "account": "[UNRESOLVED ACCOUNT DISCREPANCY]",
          "date": "[UNRESOLVED DATE DISCREPANCY]"}


@pytest.mark.parametrize("field", list(LABELS))
def test_7_each_output_labels_the_actual_conflicting_field(session, field):
    d = _build(session, field)
    label = LABELS[field]
    rows = [r for r in outputs.fact_table(session) if r["FACT ID"] in d.fact_ids]
    assert rows and all(any(label in n for n in r["NOTES"]) for r in rows)
    events = [e for e in outputs.timeline(session) if e["EVENT ID"] in d.fact_ids]
    assert events and all(any(label in u for u in e["UNRESOLVED QUESTIONS"]) for e in events)
    assert any(x.startswith(f"{d.id}: {label}") for x in outputs.open_questions(session))
    assert f"{d.id} {label}" in outputs.interview_record(session)
    everything = json.dumps(outputs.all_outputs(session), default=str)
    if field != "date":                                      # audit: location was labeled DATE
        assert "UNRESOLVED DATE DISCREPANCY" not in everything
    for other, other_label in LABELS.items():
        if other != field:
            assert other_label not in everything
