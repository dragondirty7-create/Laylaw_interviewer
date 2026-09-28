"""Tests for the PR #1 repair pass (P0-P2). ALL DATA IS SYNTHETIC AND FICTIONAL."""
import json

import pytest

from conftest import new_session
from laylaw.interviewer import (
    DatePrecision, ModeViolation, SessionStatus, SourceOfKnowledge, VerificationStatus, outputs, paths,
)
from laylaw.interviewer.guard import find_advocacy
from laylaw.interviewer.models import FactStatus, ProvenanceType, SupportingSourceType
from laylaw.interviewer.session import SAVED_FOR_LATER, ProvenanceError


def advance_to(s, predicate, filler="skip"):
    """Answer every question with `filler` until one matches `predicate`; return it."""
    for _ in range(200):
        q = s.next_question()
        assert q is not None, "interview ended before the expected question"
        if predicate(q):
            return q
        s.answer(filler)
    raise AssertionError("expected question never came")


# ============================================================ P0-1 corrections
def test_recap_correction_preserves_original_and_corrected_version(ws, store):
    s = new_session(ws)
    s.next_question()
    s.answer("Sam Rowe arrived at the library for the exchange.")
    advance_to(s, lambda q: q.endswith("Did I get anything wrong?"))
    s.answer("It was the community center, not the library.")

    orig, new = s.facts[0], s.facts[1]
    assert orig.statement == "Sam Rowe arrived at the library for the exchange."      # untouched
    assert orig.status == FactStatus.SUPERSEDED and orig.superseded_by == new.id
    assert new.correction_of == orig.id and new.status == FactStatus.CURRENT
    assert new.statement == "It was the community center, not the library."           # interviewee's words
    c = s.corrections[0]
    assert (c.via, c.target_fact_id, c.new_fact_id, c.status) == ("recap", orig.id, new.id, "applied")

    rows = {r["FACT ID"]: r for r in outputs.fact_table(s)}
    assert rows[orig.id]["VERSION"].startswith("SUPERSEDED by interviewee correction " + new.id)
    assert rows[new.id]["VERSION"] == f"CORRECTION of {orig.id} (interviewee's words)"
    tl = [e["EVENT ID"] for e in outputs.timeline(s)]
    assert tl.index(new.id) == tl.index(orig.id) + 1                 # history kept, shown together
    record = outputs.interview_record(s)
    assert f"{c.id} via recap: {orig.id} -> {new.id}" in record
    assert "1 applied" in outputs.handoff_summary(s)
    # The recap for the section now shows the current version, marked as a correction.
    assert "CORRECTION of F-001" in s.section_recap()
    # Survives save/load.
    again = store.workspace(ws.client_id).load_session(s.interview_id)
    assert again.get_fact(orig.id).superseded_by == new.id and again.corrections[0].status == "applied"


def test_final_check_correction_asks_which_item_then_links_versions(ws):
    s = new_session(ws)
    s.next_question()
    s.answer("Sam Rowe picked up the kids on a Monday. Casey Lin dropped off the backpacks.")
    assert len(s.facts) == 2
    advance_to(s, lambda q: q == "Is there anything we discussed that you want to correct?", filler="No")
    s.answer("It was a Tuesday, not a Monday.")                 # no explicit item -> ask which one

    q = s.next_question()
    assert "1. Sam Rowe picked up the kids on a Monday." in q and q.endswith("Which numbered item does that change?")
    assert s.corrections[0].status == "needs_target"
    s.answer("1")
    first, new = s.facts[0], s.facts[-1]
    assert first.status == FactStatus.SUPERSEDED and new.correction_of == first.id
    assert new.statement == "It was a Tuesday, not a Monday."
    assert s.facts[1].status == FactStatus.CURRENT            # the other item is untouched
    assert s.corrections[0].via == "final_check" and s.corrections[0].status == "applied"
    assert not any("awaiting" in o for o in outputs.open_questions(s))


def test_correction_numbers_in_text_are_not_mistaken_for_item_numbers(ws):
    s = new_session(ws)
    s.next_question()
    s.answer("Two adults were at the park. Casey Lin was on the bench.")
    advance_to(s, lambda q: q.endswith("Did I get anything wrong?"))
    s.answer("2 kids were also there, I forgot.")
    assert s.corrections[0].status == "needs_target"            # "2" was NOT read as item 2
    assert all(f.status == FactStatus.CURRENT for f in s.facts[:2])


# ============================================================ P0-2 controls
def test_skip_is_never_stored_as_a_fact(session):
    session.next_question()
    session.answer("Skip")                                     # free account
    assert session.facts == [] and session.raw_answers == []
    assert session.turns[-1].control == "skip"
    assert any("Skipped by interviewee" in o for o in session.open_questions)

    s = session
    s.add_section("Current household")
    s.next_question()
    s.answer("Jordan Avery lives with two roommates.")
    s.next_question()                                          # clarification
    s.skip()
    assert len(s.facts) == 1
    assert "Skipped by interviewee: About when was this?" in s.facts[0].open_questions
    assert s.facts[0].date is None
    everything = json.dumps(outputs.all_outputs(s), default=str)
    assert '"STATEMENT": "Recollection (paraphrase of interviewee\'s answer): Skip"' not in everything
    assert all(f.statement.lower() not in ("skip", "not sure") for f in s.facts)


def test_not_sure_is_never_upgraded_into_a_factual_assertion(session):
    session.next_question()
    session.answer("I don't know")                             # free account: nothing recorded as fact
    assert session.facts == []
    assert session.turns[-1].control == "not_sure"
    session.add_section("Exchanges / transportation")
    session.next_question()
    session.answer("Casey Lin drove to the exchange.")
    assert session.next_question() == "About when was this?"
    session.answer("Not sure")
    f = session.facts[0]
    assert f.date.precision == DatePrecision.UNKNOWN            # unknown stays unknown
    assert f.statement == "Casey Lin drove to the exchange."
    assert len(session.facts) == 1                             # "Not sure" did not become a fact
    row = outputs.fact_table(session)[0]
    assert "[UNKNOWN]" in row["DATE / DATE PRECISION"]


def test_save_and_finish_later_resumes_at_the_exact_pending_question(ws, store):
    # during the free account
    s = new_session(ws, sections=["Specific incidents"])
    first = s.next_question()
    assert s.answer("Save and finish later") == SAVED_FOR_LATER
    assert s.status == SessionStatus.PAUSED and s.facts == [] and s.turns[-1].control == "save_later"
    again = store.workspace(ws.client_id).load_session(s.interview_id)
    again.resume()
    assert again.next_question() == first.split("\n\n")[-1]    # same question (orientation shown once)
    again.answer("Casey Lin arrived late to the school pickup.")

    # during a clarification question
    q = again.next_question()
    assert q == "About when was this?"
    again.save_and_finish_later()
    third = store.workspace(ws.client_id).load_session(again.interview_id)
    assert third.pending.text == "About when was this?"
    third.resume()
    assert third.next_question() == "About when was this?"
    third.answer("around April 2025")
    assert third.facts[0].date.precision == DatePrecision.APPROXIMATE
    assert len(third.facts) == 1


# ============================================================ P0-3/4 criminal path + preflight
def test_criminal_path_starts_with_paperwork_and_never_requires_conduct_narrative(ws):
    s, notice = paths.start_path("criminal_defense", ws, case_id="CASE-FICTIONAL-CD2",
                                 interviewee="Jordan Avery", interviewer="Laylaw Interviewer",
                                 purpose="Synthetic intake", interviewee_is_adult=True)
    assert s.sections == ["Charges as shown on paperwork", "Court, case number, and next hearing",
                          "Custody or release conditions", "Attorney or public defender status",
                          "Procedural history", "Available records"]
    assert "Events in question (optional)" in paths.available_sections("criminal_defense")
    assert "privilege" in notice and "not protected by attorney-client privilege" in notice

    asked = []
    answers = {
        "is anyone in immediate danger": "No",
        "hearing or other deadline": "An arraignment around October 15, 2026",
        "help with first": "Understanding my paperwork",
        "in custody, or out": "Out of custody",
        "lawyer or public defender?": "Not yet",
        "charges are listed": "It says misdemeanor vandalism, fictional code 000.0",
        "reading that from the paperwork": "Reading it from the paperwork",
        "paperwork called": "Notice to Appear",
        "Which court": "Fictional County Superior Court",
        "case number": "FIC-0001",
        "next hearing": "an arraignment on October 15, 2026",
    }
    for _ in range(80):
        q = s.next_question()
        if q is None:
            break
        asked.append(q)
        s.answer(next((v for k, v in answers.items() if k.lower() in q.lower()), "skip"))

    # Intake first, then paperwork -- the charges question is the first interview question.
    first_section_q = next(i for i, q in enumerate(asked) if "charges are listed" in q)
    assert first_section_q == 5                                     # after the 5 preflight questions
    joined = "\n".join(asked).lower()
    assert "events in question" not in joined and "what happened" not in joined.split("procedural history")[0]
    # Intake answers are administrative metadata, not historical facts.
    assert {i.key for i in s.intake} == {"urgent", "deadline", "help_first", "custody", "counsel"}
    assert all(f.statement != "Out of custody" for f in s.facts)
    charge = next(f for f in s.facts if "misdemeanor" in f.statement)
    assert charge.source == SourceOfKnowledge.DOCUMENT_RECOLLECTION
    assert charge.question_context.startswith("What charges are listed")
    case_no = next(f for f in s.facts if f.statement == "FIC-0001")
    assert case_no.question_context.startswith("What is the case number")
    hearing = next(f for f in s.facts if "arraignment" in f.statement)
    assert hearing.date.precision == DatePrecision.EXACT
    assert "INTAKE (administrative; not historical findings)" in outputs.interview_record(s)
    for text in asked:
        assert find_advocacy(text) == []


def test_preflight_captures_intake_separately_and_pauses_for_present_danger(ws):
    s, _ = paths.start_path("family_law", ws, case_id="CASE-FICTIONAL-FL", interviewee="Jordan Avery",
                            interviewer="Laylaw Interviewer", purpose="Synthetic intake",
                            interviewee_is_adult=True)
    q = s.next_question()
    assert q.startswith("Before we start: is anyone in immediate danger")
    s.answer("Yes, he is outside right now and threatening to hurt me.")
    assert s.status == SessionStatus.PAUSED_FOR_SAFETY
    assert "911" in s.next_question()
    s.answer("I'm safe now.")
    assert s.next_question().startswith("Is there a court hearing or other deadline")
    s.answer("A hearing sometime in November 2026")
    s.next_question()
    s.answer("Setting up a schedule")
    assert [i.key for i in s.intake] == ["deadline", "help_first"]
    assert s.facts == []                                    # intake is not historical fact
    assert "custody" not in [i.key for i in s.intake]       # criminal-only questions not asked here


# ============================================================ P1-5 propositions
def test_mixed_source_free_narrative_is_separable_by_provenance(session):
    session.next_question()
    answer = ("I saw Sam Rowe leave the house around March 2025. "
              "My sister told me he came back late that night.")
    session.answer(answer)
    raw = session.raw_answers[0]
    assert raw.text == answer                                   # raw answer preserved verbatim
    a, b = session.facts
    assert (a.raw_answer_id, b.raw_answer_id) == (raw.id, raw.id)
    assert raw.text[a.span[0]:a.span[1]] == a.statement == "I saw Sam Rowe leave the house around March 2025."
    assert raw.text[b.span[0]:b.span[1]] == b.statement
    assert a.source == SourceOfKnowledge.PERSONAL_OBSERVATION
    assert b.source == SourceOfKnowledge.SECONDHAND
    assert a.date.precision == DatePrecision.APPROXIMATE and a.date.original_text == "around March 2025"
    assert b.date is None                                       # no date carried over from the other part
    assert a.provenance.type == b.provenance.type == ProvenanceType.INTERVIEW
    # A paraphrase (e.g. from an LLM) can never be recorded as the interviewee's words.
    with pytest.raises(ProvenanceError):
        session.record_fact("Sam left the home in March.", topic="Specific incidents",
                            raw_answer_id=raw.id, span=list(a.span))
    # A caller-chosen split is allowed only as exact slices of the stored answer.
    f = session.record_proposition(raw.id, 0, 5)
    assert f.statement == "I saw"
    assert "ANSWERS AS ENTERED" in outputs.interview_record(session)


# ============================================================ P1-6 discrepancies
def test_non_date_discrepancies_preserve_both_recollections(session):
    f = session.record_fact("Casey Lin handed over the kids.", topic="Exchanges / transportation",
                            location="the library parking lot", people_present=["Casey Lin", "interviewee"])
    session.set_fact_location(f.id, "the grocery store")
    session.set_people_present(f.id, "Casey Lin and Morgan Ellis")
    g = session.record_fact("Morgan Ellis arrived.", topic="Exchanges / transportation")
    session.record_sequence(f.id, "before", g.id)
    session.record_sequence(f.id, "after", g.id)
    alt = session.record_conflicting_account(f.id, "Morgan Ellis handed over the kids.")

    fields = {d.field for d in session.discrepancies}
    assert fields == {"location", "people_present", "sequence", "account"}
    assert all(d.status == "unresolved" for d in session.discrepancies)
    assert f.location == "the library parking lot"              # first recollection kept
    assert {"field": "location", "value": "the grocery store", "turn": None} in f.alternate_recollections
    assert f.people_present == ["Casey Lin", "interviewee"]
    assert alt.statement == "Morgan Ellis handed over the kids." and f.statement == "Casey Lin handed over the kids."
    loc = next(d for d in session.discrepancies if d.field == "location")
    assert "the library parking lot" in loc.description and "the grocery store" in loc.description
    # Neutral clarification, no judgment about truthfulness.
    q = session.next_question()
    assert q.endswith("Which is closer to what you remember now?")
    for word in ("lie", "lying", "truth", "better", "believable", "wrong"):
        assert word not in q.lower().split()
    assert f.verification == VerificationStatus.DISPUTED
    tl = next(e for e in outputs.timeline(session) if e["EVENT ID"] == f.id)
    assert any("[UNRESOLVED LOCATION DISCREPANCY]" in u for u in tl["UNRESOLVED QUESTIONS"])


# ============================================================ P1-7 source typing
def test_witness_record_hook_response_is_not_stored_as_a_document(session):
    session.next_question()
    session.answer("Casey Lin was late to the exchange.")
    advance_to(session, lambda q: q == "Is there anything that might help document or date this?")
    session.answer("My neighbor saw it happen from her porch.")
    rec = session.records[-1]
    assert rec.source_type == SupportingSourceType.WITNESS
    assert rec.provenance_type != ProvenanceType.DOCUMENT
    assert rec.describe().startswith("POTENTIAL WITNESS")
    assert session.facts[0].verification == VerificationStatus.WITNESS_IDENTIFIED
    follow = outputs.evidence_followup(session)
    assert any(x.startswith("[WITNESS/PERSON] POTENTIAL WITNESS") for x in follow)

    for text, kind in [("There are texts from him", SupportingSourceType.EMAIL_TEXT),
                       ("The court minute order", SupportingSourceType.COURT_RECORD),
                       ("A gas station receipt", SupportingSourceType.DOCUMENT_FILE),
                       ("Maybe the parking app", SupportingSourceType.OTHER)]:
        session._apply_record_hook(type("Q", (), {"fact_id": session.facts[0].id})(), text)
        assert session.records[-1].source_type == kind


# ============================================================ P1-8 adaptive paths
def test_section_selection_does_not_mechanically_require_every_family_law_section(ws):
    s, _ = paths.start_path("family_law", ws, case_id="CASE-FICTIONAL-FL2", interviewee="Jordan Avery",
                            interviewer="Laylaw Interviewer", purpose="x", interviewee_is_adult=True,
                            preflight=False)
    assert len(paths.available_sections("family_law")) == 26          # canonical set preserved
    assert len(s.sections) < 26 and s.sections == paths.default_sections("family_law")
    assert "Specific incidents" not in s.sections and "Specific safety concerns" not in s.sections
    suggested = paths.suggest_sections("family_law", "Mostly problems with school pickups and texts")
    assert "Children's schooling" in suggested and "Exchanges / transportation" in suggested
    assert "Children's schooling" not in s.sections                  # suggestions are never auto-added
    s.add_section("Children's schooling")
    assert s.sections[-1] == "Children's schooling"
    with pytest.raises(ValueError):
        s.add_section("Legal strategy")
    t, _ = paths.start_path("family_law", ws, case_id="CASE-FICTIONAL-FL3", interviewee="Jordan Avery",
                            interviewer="L", purpose="x", interviewee_is_adult=True, preflight=False,
                            sections=["Housing"])
    assert t.sections == ["Housing"]


# ============================================================ P2-9 document candidates
def test_document_derived_candidate_stays_candidate_until_client_confirms(session):
    f = session.record_fact("The hearing was continued.", topic="Court orders", date_text="around June 2024")
    rec = session.add_upload("order-FICTIONAL.pdf", b"fictional", label="Minute order (fictional)",
                             related_fact_ids=[f.id], source_type=SupportingSourceType.COURT_RECORD)
    cand = session.propose_document_candidate(rec.id, "date", "August 14, 2024", fact_id=f.id, page="2")
    assert cand.status == "candidate" and cand.provenance.label.startswith("COURT-RECORD:")
    assert f.date.original_text == "around June 2024"                   # recollection untouched
    assert "August 14, 2024" not in json.dumps(outputs.timeline(session))
    assert any("DOCUMENT-DERIVED CANDIDATE" in x for x in outputs.evidence_followup(session))

    session.respond_to_candidate(cand.id, "Yes, the order date is right, it was August 14, 2024.", "confirm")
    assert cand.status == "confirmed" and cand.resulting_fact_id
    new = session.get_fact(cand.resulting_fact_id)
    assert new.correction_of == f.id and new.date.precision == DatePrecision.EXACT
    assert f.date.original_text == "around June 2024" and f.status == FactStatus.SUPERSEDED
    assert session.corrections[-1].via == "document_candidate"


# ============================================================ P2-10 ORGANIZE boundary
def test_organize_interface_is_separate_and_interview_keeps_seven_outputs(session):
    from laylaw.organize import ORGANIZE_PRODUCTS, NotImplementedOrganizer, export_for_organize
    session.record_fact("I think Casey Lin was late.", topic="Specific incidents", date_text="around May 2025")
    assert set(outputs.all_outputs(session)) == {
        "interview_record", "fact_table", "timeline", "evidence_followup", "open_questions",
        "requested_outcomes", "handoff_summary"}
    export = export_for_organize(session)
    assert export["schema"] == "laylaw.interview-export/1" and export["source_stage"] == "INTERVIEW"
    assert export["facts"][0]["hedges"] == ["I think"]                    # uncertainty survives
    assert "Never silently rewrite uncertain interview statements into definite allegations." \
        in export["downstream_rules"]
    assert set(ORGANIZE_PRODUCTS) == {"concise_overview", "dated_timeline", "document_index",
                                      "missing_information_checklist", "questions_for_counsel"}
    with pytest.raises(NotImplementedError):
        NotImplementedOrganizer().questions_for_counsel(export)
    from laylaw.interviewer import Mode
    with pytest.raises(ModeViolation):
        session.request_stage_output(Mode.ORGANIZE)


# ============================================================ P2-11 research basis
def test_research_basis_template_and_unreviewed_research_cannot_change_behavior(tmp_path):
    from laylaw.interviewer import research_basis as rb
    assert rb.FIELDS == ("TITLE", "AUTHOR / ORGANIZATION", "DATE", "LINK / SOURCE", "TYPE OF SOURCE",
                         "KEY FINDING", "HOW IT AFFECTS THE INTERVIEW PROTOCOL", "DATE REVIEWED")
    basis = rb.ResearchBasis()
    basis.add(rb.ResearchEntry("Fictional study A", "Fictional Org", "2026", "n/a", "peer-reviewed research",
                               "finding", "effect"))
    basis.add(rb.ResearchEntry("Fictional blog B", "Someone", "2026", "n/a", "blog / opinion", "claim", "effect"))
    with pytest.raises(PermissionError):
        basis.mark_applied("Fictional study A")                        # not reviewed
    basis.mark_reviewed("Fictional study A", date_reviewed="2026-09-28", reviewed_by="Reviewer")
    assert basis.mark_applied("Fictional study A").applied_to_protocol
    basis.mark_reviewed("Fictional blog B", date_reviewed="2026-09-28", reviewed_by="Reviewer")
    with pytest.raises(PermissionError):
        basis.mark_applied("Fictional blog B")                         # single blog can't change behavior
    basis.flag_conflict("Fictional study A", "Fictional blog B")
    basis.save(tmp_path / "rb.json")
    assert rb.ResearchBasis.load(tmp_path / "rb.json").entries[0].conflicts_with == ["Fictional blog B"]
    assert basis.entries[1].as_template_row()["TYPE OF SOURCE"] == "blog / opinion"
    # The engine does not read research at runtime.
    import laylaw.interviewer.session as sess
    assert "research_basis" not in open(sess.__file__).read()


# ============================================================ found in end-to-end run
def test_bare_no_to_opening_prompt_is_neither_fact_nor_request(ws):
    s = new_session(ws, sections=["Current requested arrangement", "Housing"])
    assert s.next_question().endswith("What would you like to happen going forward?")
    s.answer("No")
    assert s.outcomes == [] and s.facts == []
    s.next_question()
    s.answer("Nothing")
    assert s.facts == []
    assert any("nothing to add" in o for o in s.open_questions)


def test_hedge_covers_the_date_of_the_same_statement(session):
    session.next_question()
    session.answer("I think Sam Rowe moved to a new apartment in March 2025.")
    f = session.facts[0]
    assert f.date.original_text == "in March 2025"
    assert f.date.precision == DatePrecision.APPROXIMATE           # not MONTH ONLY
    firm = session.record_fact("Sam Rowe moved in March 2025.", topic="Housing", date_text="March 2025")
    assert firm.date.precision == DatePrecision.MONTH_ONLY          # unhedged keeps its precision
