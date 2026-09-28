"""The 11 tests required by the Claude Code handoff (Laylaw Interviewer).

Each test is named after the behavior the handoff says must be proven.
All data is synthetic and fictional.
"""
import json

import pytest

from conftest import new_session
from laylaw.interviewer import (
    Certainty, DatePrecision, Mode, ModeViolation, ReviewStatus, SessionStatus, SourceOfKnowledge,
    TranscriptStatus, VerificationStatus, WorkspaceIsolationError, outputs,
)
from laylaw.interviewer.guard import find_advocacy


def _walk(session, answers):
    for a in answers:
        assert session.next_question() is not None
        session.answer(a)


# 1 ---------------------------------------------------------------------------
def test_01_interrupted_interview_saves_and_resumes_correctly(ws, store):
    s = new_session(ws, sections=["Specific incidents", "Exchanges / transportation"])
    s.next_question()
    s.answer("Sam Rowe arrived at the library parking lot for the exchange and waited in the car.")
    q_date = s.next_question()
    assert q_date == "About when was this?"
    s.answer("around April 2025")
    pending = s.next_question()                  # asked, but not yet answered...
    s.interrupt()                                # ...and the session is interrupted.
    sid, facts_before = s.interview_id, [f.statement for f in s.facts]

    # A fresh process: reopen from disk through the same client's workspace.
    reopened = store.workspace("client-fictional-a").load_session(sid)
    assert reopened.status == SessionStatus.PAUSED
    assert [f.statement for f in reopened.facts] == facts_before
    assert reopened.facts[0].date.precision == DatePrecision.APPROXIMATE
    assert reopened.current_section == "Specific incidents"
    assert reopened.last_question_answered == "About when was this?"

    prompt = reopened.resume()
    assert prompt.startswith("I have us stopped at Specific incidents. The last thing we covered was")
    assert prompt.endswith("Shall we continue there?")
    assert reopened.is_continuation and reopened.status == SessionStatus.ACTIVE
    # It continues from the same unanswered question -- it does not restart.
    assert reopened.next_question() == pending
    reopened.answer("Just me")
    assert reopened.facts[0].people_present == ["interviewee"]
    assert len(reopened.turns) == 3


# 2 ---------------------------------------------------------------------------
@pytest.mark.parametrize("said, precision", [
    ("maybe six months ago", DatePrecision.RELATIVE),
    ("around March 2024", DatePrecision.APPROXIMATE),
    ("I think it was early June 2024", DatePrecision.APPROXIMATE),
    ("sometime in 2023", DatePrecision.APPROXIMATE),
    ("spring 2023", DatePrecision.SEASON_YEAR),
    ("May 2024", DatePrecision.MONTH_ONLY),
    ("I don't remember", DatePrecision.UNKNOWN),
])
def test_02_uncertain_and_approximate_dates_remain_uncertain(session, said, precision):
    f = session.record_statement("Casey Lin dropped off a backpack at the house.", topic="Specific incidents",
                            date_text=said)
    assert f.date.precision == precision
    assert f.date.original_text == said                       # the words are kept
    assert f.date.precision != DatePrecision.EXACT                   # never manufactured
    # Survives a save/load round trip unchanged.
    again = session.workspace.load_session(session.interview_id).facts[0]
    assert again.date.precision == precision and again.date.original_text == said
    # And every output shows the uncertainty rather than a clean calendar date.
    row = outputs.fact_table(session)[0]
    assert precision.value in row["DATE / DATE PRECISION"]


def test_02b_hedged_statement_keeps_hedge_and_never_gets_exact_date(session):
    f = session.record_statement("I think the car was parked on the street.", topic="Specific incidents",
                            date_text="March 3, 2024")
    assert f.certainty == Certainty.HEDGED and "I think" in f.hedges
    assert f.statement == "I think the car was parked on the street."   # not "The car was parked..."
    assert f.date.precision == DatePrecision.APPROXIMATE                 # hedged -> not EXACT
    assert "Interviewee uncertainty preserved" in outputs.neutral_fact_line(f, session)


# 3 ---------------------------------------------------------------------------
def test_03_secondhand_information_remains_labeled_secondhand(session):
    f = session.record_statement("A neighbor told me the gate was left open overnight.", topic="Specific incidents")
    assert f.source == SourceOfKnowledge.SECONDHAND
    # Even if a caller (or a later stage) tries to relabel it as observation,
    # the engine refuses to upgrade a reported account.
    g = session.record_statement("The gate was left open overnight.", topic="Specific incidents",
                            told_by="neighbor (fictional)", source=SourceOfKnowledge.PERSONAL_OBSERVATION)
    assert g.source == SourceOfKnowledge.SECONDHAND
    session._set_source(g, SourceOfKnowledge.PERSONAL_OBSERVATION)
    assert g.source == SourceOfKnowledge.SECONDHAND
    for row in outputs.fact_table(session):
        assert row["KNOWLEDGE SOURCE"] == "SECONDHAND"
    for ev in outputs.timeline(session):
        assert ev["SOURCE OF KNOWLEDGE"] == "SECONDHAND"


# 4 ---------------------------------------------------------------------------
def test_04_conflicting_date_recollections_preserved_if_unresolved(session):
    session.next_question()
    session.answer("Sam Rowe missed the scheduled pickup at the school.")
    session.next_question()
    session.answer("around March 2025")
    fid = session.facts[0].id
    # Later in the interview the interviewee gives a different month for the same event.
    session.set_fact_date(fid, "maybe May 2025")

    assert len(session.discrepancies) == 1
    d = session.discrepancies[0]
    assert d.status == "unresolved" and d.field == "date"
    recollections = {session.get_fact(x).date.original_text for x in d.fact_ids}
    assert recollections == {"around March 2025", "maybe May 2025"}      # both kept
    assert session.facts[0].date.original_text == "around March 2025"   # first never overwritten

    # The neutral clarification is asked next, not an accusation.
    q = session.next_question()
    assert "Which is closer to what you remember now?" in q
    import re
    assert not re.search(r"\b(?:lie|lied|lying|wrong|contradict\w*|inconsistent)\b", q, re.I)

    session.answer("I honestly don't know, it could be either.")
    session.resolve_discrepancy(d.id, "I honestly don't know, it could be either.")
    assert d.status == "unresolved"
    assert "[UNRESOLVED DATE DISCREPANCY]" in outputs.interview_record(session)
    assert any("[UNRESOLVED DATE DISCREPANCY]" in q for q in outputs.open_questions(session))
    # Neither version is silently chosen for the timeline: both appear.
    assert {e["EVENT ID"] for e in outputs.timeline(session)} >= set(d.fact_ids)


# 5 ---------------------------------------------------------------------------
def test_05_document_reviewed_after_answer_does_not_overwrite_recollection(session):
    f = session.record_statement("The court hearing was continued to a later date.", topic="Court orders",
                            date_text="around June 2024")
    original = (f.statement, f.date.original_text, f.date.precision)

    rec = session.add_upload("minute-order-FICTIONAL.pdf", b"%PDF fictional minute order",
                             label="Minute order (fictional)", related_fact_ids=[f.id])
    session.mark_record_reviewed(rec.id)
    finding = session.add_document_finding(f.id, rec.id, "Hearing continued to a later date.",
                                           date_text="August 14, 2024", page="2")

    assert (f.statement, f.date.original_text, f.date.precision) == original
    assert finding.consistency == "different"
    assert f.verification == VerificationStatus.INCONSISTENT_WITH_DOCUMENT
    record = outputs.interview_record(session)
    assert "INTERVIEWEE RECOLLECTION: The court hearing was continued" in record
    assert "(date as recalled: Approximately: around June 2024" in record
    assert "DOCUMENT CONTENT [DOCUMENT:MINUTE-ORDER-FICTIONAL:PAGE-2]" in record
    assert "CONSISTENCY / DIFFERENCE: different" in record
    # Reloaded from disk, the recollection is still the original one.
    again = session.workspace.load_session(session.interview_id)
    assert again.get_fact(f.id).date.original_text == "around June 2024"


# 6 ---------------------------------------------------------------------------
def test_06_child_reported_statement_is_secondhand_unless_adult_witnessed(session):
    heard = session.record_statement("Pip said the dog got out of the yard at the other house.",
                                topic="Specific incidents", told_by="Pip", told_by_is_child=True,
                                source=SourceOfKnowledge.PERSONAL_OBSERVATION)
    assert heard.source == SourceOfKnowledge.SECONDHAND
    # A caller cannot quietly relabel it later.
    session._set_source(heard, SourceOfKnowledge.PERSONAL_OBSERVATION)
    assert heard.source == SourceOfKnowledge.SECONDHAND

    seen = session.record_statement("I saw the dog get out of the yard while Pip was with me.",
                               topic="Specific incidents", told_by="Pip", told_by_is_child=True,
                               witnessed_underlying_event=True,
                               source=SourceOfKnowledge.PERSONAL_OBSERVATION)
    assert seen.source == SourceOfKnowledge.PERSONAL_OBSERVATION
    assert "Reported to interviewee by: Pip (child)" in outputs.neutral_fact_line(heard, session)

    # The child rule stands on its own, even when no teller name was captured.
    unnamed = session.record_statement("The dog got out of the yard at the other house.",
                                  topic="Specific incidents", told_by_is_child=True,
                                  source=SourceOfKnowledge.PERSONAL_OBSERVATION)
    assert unnamed.source == SourceOfKnowledge.SECONDHAND

    # And the interviewer never interviews the child directly.
    from laylaw.interviewer import AdultInterviewOnly, InterviewSession
    with pytest.raises(AdultInterviewOnly):
        InterviewSession.start(session.workspace, case_id="C", interviewee="Pip", interviewer="Laylaw",
                               purpose="x", sections=["Specific incidents"], interviewee_is_adult=False)


# 7 ---------------------------------------------------------------------------
def test_07_unreviewed_records_not_described_as_proof_or_corroboration(session):
    f = session.record_statement("I sent a text asking to swap weekends.", topic="Communication between parents",
                            date_text="around May 2025")
    rec = session.add_upload("screenshot-FICTIONAL.png", b"\x89PNG fictional", label="Text screenshot",
                             related_fact_ids=[f.id])
    session.pending = None
    session._apply_record_hook(type("Q", (), {"fact_id": f.id})(), "There might be a calendar entry")

    assert rec.review_status == ReviewStatus.UNREVIEWED
    assert f.verification == VerificationStatus.DOCUMENT_LOCATED   # located, not reviewed, not "verified"
    everything = json.dumps(outputs.all_outputs(session), default=str).lower()
    for banned in ("corroborat", "proves", "proof", "verified", "confirms", "establishes"):
        assert banned not in everything, banned
    assert "potential supporting record" in everything
    with pytest.raises(ValueError):          # can't record what it says until reviewed
        session.add_document_finding(f.id, rec.id, "anything")


# 8 ---------------------------------------------------------------------------
def test_08_requested_outcomes_do_not_leak_into_timeline(ws):
    s = new_session(ws, sections=["Current parenting routine", "Current requested arrangement"])
    s.next_question()
    s.answer("The kids are usually with Sam Rowe about three or four nights a week.")
    while (q := s.next_question()) != "What would you like to happen going forward?":
        assert q is not None
        s.answer("No")
    s.answer("A predictable shared schedule with the same exchange day each week.")
    # Also a request volunteered mid-account in a factual section:
    s.record_request("I'd like the exchanges to happen at the library.")

    timeline_text = json.dumps(outputs.timeline(s))
    assert "predictable shared schedule" not in timeline_text
    assert "exchanges to happen at the library" not in timeline_text
    assert all(f.source != SourceOfKnowledge.REQUEST for f in s.facts)
    assert [o["REQUEST"] for o in outputs.requested_outcomes(s)] == [
        "A predictable shared schedule with the same exchange day each week.",
        "I'd like the exchanges to happen at the library."]
    with pytest.raises(ValueError):
        s.record_statement("I want the court to change the schedule.", topic="Current parenting routine")
    # Routine is kept as routine, not collapsed into an incident.
    assert s.facts[0].kind.value == "routine"


# 9 ---------------------------------------------------------------------------
def test_09_no_advocacy_or_legal_strategy_output_in_interview_mode(ws):
    s = new_session(ws, sections=["Specific incidents", "Current requested arrangement"])
    emitted = []
    answers = iter(["I think Sam Rowe was about an hour late to the exchange.", "around June 2025",
                    "Just me", "I was there", "The time, I'm less sure", "Nothing", "Maybe texts",
                    "No", "No", "No", "More consistent exchange times.", "No", "No", "No", "No"])
    while (q := s.next_question()) is not None:
        emitted.append(q)
        s.answer(next(answers, "No"))
    out = outputs.all_outputs(s)
    emitted += [out["interview_record"], out["handoff_summary"], json.dumps(out, default=str)]
    for text in emitted:
        assert find_advocacy(text) == [], text

    # Later stages are refused while in INTERVIEW mode.
    for stage in (Mode.ORGANIZE, Mode.VERIFY, Mode.ANALYZE, Mode.DRAFT):
        with pytest.raises(ModeViolation):
            s.request_stage_output(stage)
    # And the guard blocks advocacy text if anything tries to emit it.
    with pytest.raises(ModeViolation):
        s._emit("This helps your case. You should argue that he was late on purpose.")
    # Every question asked was a single question.
    for q in emitted[:-3]:
        last_block = q.split("\n\n")[-1]
        assert last_block.count("?") <= 1, q


# 10 --------------------------------------------------------------------------
def test_10_two_client_workspaces_cannot_read_or_overwrite_each_other(store):
    a = store.workspace("client-fictional-a")
    b = store.workspace("client-fictional-b")
    sa = new_session(a, interviewee="Jordan Avery")
    sb = new_session(b, interviewee="Morgan Ellis")
    sa.record_statement("Client A fictional fact.", topic="Specific incidents"); sa.save()
    sb.record_statement("Client B fictional fact.", topic="Specific incidents"); sb.save()

    assert a.list_sessions() == [sa.interview_id] and b.list_sessions() == [sb.interview_id]
    with pytest.raises(FileNotFoundError):
        b.load_session(sa.interview_id)                 # B can't see A's session
    with pytest.raises(WorkspaceIsolationError):
        b.save_session(sa)                              # B can't write A's session
    sa.client_id = "client-fictional-b"                 # even if the object is tampered with...
    with pytest.raises(WorkspaceIsolationError):
        a.save_session(sa)
    sa.client_id = "client-fictional-a"
    for bad in ("../client-fictional-a", "..", "a/b", "", "x" * 80):
        with pytest.raises(WorkspaceIsolationError):
            store.workspace(bad)
        with pytest.raises(WorkspaceIsolationError):
            b.load_session(bad)
    # A forged file planted in B's folder claiming to be A's is rejected.
    forged = b.dir / "sessions" / "INT-forged0001.json"
    forged.write_text(json.dumps({**sa.to_dict(), "interview_id": "INT-forged0001"}))
    with pytest.raises(WorkspaceIsolationError):
        b.load_session("INT-forged0001")
    # A's data is intact.
    assert a.load_session(sa.interview_id).facts[0].statement == "Client A fictional fact."
    assert b.load_session(sb.interview_id).facts[0].statement == "Client B fictional fact."


# 11 --------------------------------------------------------------------------
def test_11_multiple_uploads_stay_attached_to_correct_client_and_session(store):
    a = store.workspace("client-fictional-a")
    b = store.workspace("client-fictional-b")
    s1 = new_session(a)
    s2 = new_session(a)
    s3 = new_session(b, interviewee="Morgan Ellis")

    f1 = s1.record_statement("I emailed about the school pickup.", topic="Specific incidents")
    # Uploads arrive at different points throughout the interview.
    r1 = s1.add_upload("email-FICTIONAL.eml", b"fictional email 1", related_fact_ids=[f1.id])
    s1.next_question(); s1.answer("Casey Lin brought the kids home after practice.")
    r2 = s1.add_upload("photo-FICTIONAL.jpg", b"fictional photo 2")
    r3 = s2.add_upload("receipt-FICTIONAL.pdf", b"fictional receipt 3")
    r4 = s3.add_upload("email-FICTIONAL.eml", b"fictional email 4")   # same filename, other client
    s1.next_question(); s1.answer("around May 2025")
    r5 = s1.add_upload("calendar-FICTIONAL.ics", b"fictional calendar 5")

    assert [r.id for r in s1.records if r.sha256] == [r1.id, r2.id, r5.id]
    assert [r.id for r in s2.records] == [r3.id]
    assert [r.id for r in s3.records] == [r4.id]
    for sess, ws_ in ((s1, a), (s2, a), (s3, b)):
        for r in sess.records:
            if not r.sha256:
                continue
            assert r.client_id == ws_.client_id and r.session_id == sess.interview_id
            assert ws_.read_upload(r)                    # readable by the owner
    assert a.read_upload(r1) == b"fictional email 1"
    assert b.read_upload(r4) == b"fictional email 4"
    with pytest.raises(WorkspaceIsolationError):
        b.read_upload(r1)                                # not readable by another client
    assert r1.id in f1.possible_records
    # Survives save/resume with attachments intact.
    reloaded = a.load_session(s1.interview_id)
    assert {r.id for r in reloaded.records if r.sha256} == {r1.id, r2.id, r5.id}
    assert all(r.session_id == s1.interview_id for r in reloaded.records)
