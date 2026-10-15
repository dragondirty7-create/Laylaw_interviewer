"""Rapid Criminal & Supervision Intake: engine, outputs, storage and the local app.

ALL DATA IS SYNTHETIC AND FICTIONAL. Marker strings stand in for anything a
real person might enter, so tests can prove those values never reach the audit
log, the vault's files on disk, or another matter.

Test names carry the acceptance letter from Soul's 2026-10-15 handoff (A-H).
"""
import hashlib
import html
import re
import uuid
from pathlib import Path

import pytest

from laylaw.intake import service
from laylaw.intake import supervision_outputs as out
from laylaw.intake.model import AnswerStatus as S, IncidentIntake, IntakeError
from laylaw.intake.supervision_outputs import (CLIENT_REPORTED, CONFLICT, DOCUMENT_STATES, OFFICIALLY_VERIFIED,
                                               UNKNOWN, PacketError, build_packet)
from laylaw.intake.supervision_steps import STEP_BY_ID, STEPS

from test_local_app import PASS, launch_and_unlock
from test_rapid_intake import _post, _upload, running, store  # noqa: F401  (fixtures)

DOC_WORDS_GENERIC = "FICTIONAL-ORDER: shall enroll in and complete a treatment program as directed"
DOC_WORDS_RESIDENTIAL = "FICTIONAL-ORDER: shall enter a residential treatment program"
RECOLLECTION = "FICTIONAL-RECOLLECTION-MV3 the officer said I have to go live-in"
CASE_REF = "FICTIONAL-CASE-REF-9Q2"
CHARGE = "FICTIONAL-CHARGE-TEXT-H8"
HOPE = "FICTIONAL-HOPE-T5 whether outpatient could be considered"
ORDER_BYTES = b"FICTIONAL-ORDER-PDF-BYTES-0001"


def new(**kw) -> IncidentIntake:
    return IncidentIntake.new("matter-000000000000", kw.pop("nick", "fictional"), synthetic=True,
                              flow="supervision")


def answer(it, sid, value=None, status=S.ANSWERED):
    assert it.current == sid, (it.current, sid)
    it.respond(sid, status, value)


def stage_one(it, *, matter="not_sure", rehab="yes", who="parole", form="written_condition",
              words=DOC_WORDS_GENERIC, level="generic", date="2026-11-03", gate="now", danger="no"):
    answer(it, "danger_now", danger)
    answer(it, "about_adult", "yes")
    answer(it, "filled_by", "helper")
    if matter is None:
        answer(it, "matter_type", status=S.SKIPPED)
    else:
        answer(it, "matter_type", matter)
    answer(it, "held_now", "no")
    if date:
        answer(it, "deadline_date", date)
    else:
        answer(it, "deadline_date", status=S.NOT_SURE)
        answer(it, "deadline_rough", "sometime next week")
    answer(it, "deadline_what", "enroll")
    answer(it, "deadline_source", "officer")
    answer(it, "deadline_consequence", "nothing was said")
    answer(it, "rehab_said", rehab)
    if rehab in ("yes", "not_sure"):
        answer(it, "rehab_who", who)
        answer(it, "rehab_form", form)
        if form in ("signed_order", "written_condition", "referral", "not_sure"):
            if words:
                answer(it, "rehab_doc_words", words)
            else:
                answer(it, "rehab_doc_words", status=S.SKIPPED)
        answer(it, "rehab_recollection", RECOLLECTION)
        answer(it, "rehab_level", level)
    answer(it, "first_files", status=S.SKIPPED)
    answer(it, "hoping_for", HOPE)
    answer(it, "stage_gate", gate)


def finish(it, overrides=None):
    overrides = overrides or {}
    while it.current:
        sid = it.current
        step = STEP_BY_ID[sid]
        if sid in overrides:
            v = overrides[sid]
            it.respond(sid, S.NOT_SURE if v == "not_sure" and step.kind == "date" else S.ANSWERED, v)
        elif sid == "charge_text":
            it.respond(sid, S.ANSWERED, CHARGE)
        elif sid == "case_ref":
            it.respond(sid, S.ANSWERED, CASE_REF)
        elif step.kind in ("choice", "multi"):
            it.respond(sid, S.NOT_SURE)
        elif step.kind == "date":
            it.respond(sid, S.NOT_SURE)
        else:
            it.respond(sid, S.ANSWERED, f"fictional {sid}")


def basis_of(items, label):
    return next(i for i in items if i.label == label)


# -- the question flow ------------------------------------------------------------------

def test_first_five_minutes_order_and_every_question_can_be_unsure_or_skipped():
    stage1 = [s.id for s in STEPS if s.stage == 1]
    assert stage1[:2] == ["danger_now", "about_adult"]
    assert stage1.index("deadline_date") < stage1.index("rehab_who") < stage1.index("first_files")
    for s in STEPS:
        if s.kind in ("choice", "multi") and s.id != "stage_gate" and s.id != "filled_by":
            assert "not_sure" in dict(s.choices) or s.choices == (), s.id
    # No question asks for an account of alleged conduct.
    for s in STEPS:
        assert not re.search(r"\bwhat did (?:you|they|he|she) do\b|\bdescribe what happened\b", s.prompt, re.I)


def test_A_matter_type_defaults_to_not_sure_and_stays_not_sure_through_save_and_resume():
    assert STEP_BY_ID["matter_type"].default == "not_sure"
    it = new()
    stage_one(it, matter=None)  # skipped
    assert out.shown(it, "matter_type") == ("Not sure (skipped)", UNKNOWN)
    # Skipping is "not sure", never "no supervision": the supervision questions are still asked.
    finish(it)
    assert it.answers["supervision_kinds"].status == S.NOT_SURE
    back = IncidentIntake.from_dict(it.to_dict())
    p = build_packet(back)
    assert "What this is about: Not sure (skipped) [UNKNOWN]" in p["text"]
    assert "Kind of supervision: Not sure [UNKNOWN]" in p["text"]
    summary_lines = p["text"].split("TIME-SENSITIVE DATES")[0]
    for kind in ("state parole", "County probation", "PRCS", "Mandatory supervision", "Federal"):
        assert kind not in summary_lines, kind


def test_A_new_intake_preview_says_not_sure_before_anything_is_answered():
    it = new()
    item = basis_of(out.situation_summary(it), "What this is about")
    assert item.value.startswith("Not sure") and item.basis == UNKNOWN


@pytest.mark.parametrize("kind,label", [("state_parole", "California state parole"),
                                        ("probation", "County probation"),
                                        ("prcs", "Post-release community supervision (PRCS)")])
def test_each_supervision_kind_is_recorded_exactly_as_chosen_and_nothing_else_is_named(kind, label):
    it = new()
    stage_one(it, matter="supervision", who="other")
    finish(it, {"supervision_kinds": kind})
    item = basis_of(out.situation_summary(it), "Kind of supervision")
    assert item == out.Item("Kind of supervision", label, CLIENT_REPORTED)
    others = {"California state parole", "County probation", "Post-release community supervision (PRCS)"} - {label}
    summary = build_packet(it)["text"].split("TIME-SENSITIVE DATES")[0]
    assert not any(o in summary for o in others)


def test_B_verbal_instruction_is_never_shown_as_an_order_and_document_words_are_not_asked():
    it = new()
    stage_one(it, form="verbal", level="nothing_written")
    assert "rehab_doc_words" not in it.answers
    finish(it)
    m = out.requirement_source_map(it)
    assert basis_of(m, "How it was given").value == "Someone said it; nothing written"
    assert basis_of(m, "What the paper says, word for word").basis == UNKNOWN
    text = build_packet(it)["text"]
    assert "signed court order" not in text.lower() and "written supervision condition" not in text.lower()


def test_B_generic_treatment_is_never_upgraded_to_residential():
    it = new()
    stage_one(it, level="generic", words=DOC_WORDS_GENERIC)
    finish(it)
    m = out.requirement_source_map(it)
    lvl = basis_of(m, "Level of care named, as described")
    assert lvl.value == "It only says treatment or a program" and lvl.basis == CLIENT_REPORTED
    words = basis_of(m, "What the paper says, word for word")
    assert words.value == f"“{DOC_WORDS_GENERIC}”" and words.basis == DOCUMENT_STATES
    assert not any("residential" in i.value.lower() for i in out.situation_summary(it))
    assert out.conflicts(it) == []


def test_B_document_words_and_recollection_are_kept_separately_and_both_survive():
    it = new()
    stage_one(it, level="generic", words=DOC_WORDS_GENERIC)
    finish(it)
    m = out.requirement_source_map(it)
    assert basis_of(m, "What the person remembers being told").value == RECOLLECTION
    assert basis_of(m, "What the person remembers being told").basis == CLIENT_REPORTED
    # The recollection says "live-in"; the paper doesn't. That's not overwritten either way.
    assert DOC_WORDS_GENERIC in build_packet(it)["text"] and RECOLLECTION in build_packet(it)["text"]


@pytest.mark.parametrize("level,words", [("generic", DOC_WORDS_RESIDENTIAL), ("residential", DOC_WORDS_GENERIC)])
def test_B_wording_mismatch_is_a_conflict_with_both_kept(level, words):
    it = new()
    stage_one(it, level=level, words=words)
    finish(it)
    assert len(out.conflicts(it)) == 1
    m = out.requirement_source_map(it)
    assert basis_of(m, "Level of care named, as described").basis == CONFLICT
    assert basis_of(m, "What the paper says, word for word").value == f"“{words}”"
    assert any(q.startswith("Differs:") for q in out.open_questions(it))


def test_B_verbal_requirement_plus_an_uploaded_order_is_a_conflict(store):
    st, _ = store
    ws, it = service.new_matter(st, "fictional", synthetic=True, flow="supervision")
    stage_one(it, form="verbal", level="nothing_written")
    service.add_evidence(ws, it, filename="order.pdf", data=ORDER_BYTES, category="court_order")
    assert any("spoken only" in c for c in out.conflicts(it))


def test_C_unknown_and_approximate_deadlines_stay_that_way():
    it = new()
    stage_one(it, date=None)
    finish(it)
    d = out.deadline(it)
    assert d.value == "sometime next week (approximate, in the person's words)"
    assert out.time_sensitive_dates(it)[0]["precision"] == "approximate"
    assert not re.search(r"\d{4}-\d{2}-\d{2}", d.value)
    it2 = new()
    for sid, v in [("danger_now", "no"), ("about_adult", "yes"), ("filled_by", "self"), ("matter_type", "both"),
                   ("held_now", "no")]:
        answer(it2, sid, v)
    answer(it2, "deadline_date", status=S.NOT_SURE)
    answer(it2, "deadline_rough", status=S.SKIPPED)
    assert out.deadline(it2) == out.Item("Next required date", "Not known", UNKNOWN)
    assert out.time_sensitive_dates(it2)[0]["precision"] == "unknown"


def test_C_danger_shows_the_safety_message_without_false_assurance():
    from laylaw.intake.supervision_steps import SAFETY_MESSAGE
    assert "911" in SAFETY_MESSAGE and "988" in SAFETY_MESSAGE
    assert not re.search(r"\byou(?:'re| are) safe\b|\bwill be fine\b|\bnothing will happen\b", SAFETY_MESSAGE, re.I)


def test_under_18_stops_the_intake_and_asks_nothing_else():
    it = new()
    answer(it, "danger_now", "no")
    answer(it, "about_adult", "no")
    assert it.finished and it.applicable_steps()[-1].id == "about_adult"
    p = build_packet(it)
    assert out.ADULT_STOP in p["text"] and p["open_questions"] == [out.ADULT_STOP] and p["counsel_topics"] == []


def test_D_dual_criminal_and_supervision_asks_both_branches_without_requiring_an_account_of_conduct():
    it = new()
    stage_one(it, matter="both")
    finish(it)
    for sid in ("charge_text", "court_county", "case_ref", "release_status", "counsel", "supervision_kinds"):
        assert sid in it.answers, sid
    assert "criminal_case" not in it.answers  # already known from "both"
    assert all(not s.prompt.lower().startswith("what did") for s in it.applicable_steps())


def test_D_supervision_only_asks_whether_there_is_a_case_before_any_charge_question():
    it = new()
    stage_one(it, matter="supervision")
    assert it.current == "criminal_case"
    it.respond("criminal_case", S.ANSWERED, "no")
    assert "charge_text" not in {s.id for s in it.applicable_steps()}


def test_D_matters_are_isolated_and_sensitive_values_never_reach_disk_or_the_audit_log(store):
    st, root = store
    ws_a, a = service.new_matter(st, "A", synthetic=True, flow="supervision")
    ws_b, b = service.new_matter(st, "B", synthetic=True, flow="supervision")
    stage_one(a, matter="both")
    finish(a)
    service.save(ws_a, a)
    item = service.add_evidence(ws_a, a, filename="order.pdf", data=ORDER_BYTES, category="court_order",
                                source="fictional mail")
    assert item.sha256 == hashlib.sha256(ORDER_BYTES).hexdigest()
    with pytest.raises(FileNotFoundError):
        service.load(ws_b, a.matter_id)
    with pytest.raises(IntakeError):
        service.save(ws_b, a)
    assert service.load(ws_b, b.matter_id).answers == {}
    raw = b"".join(p.read_bytes() for p in Path(root).rglob("*") if p.is_file())
    for marker in (CASE_REF, CHARGE, RECOLLECTION, HOPE, DOC_WORDS_GENERIC):
        assert marker.encode() not in raw, marker
    assert ORDER_BYTES not in raw
    assert service.verify_evidence(ws_a, service.load(ws_a, a.matter_id)) == {item.id: True}


def test_D_file_categories_are_per_intake(store):
    st, _ = store
    ws, it = service.new_matter(st, "A", synthetic=True, flow="supervision")
    with pytest.raises(IntakeError):
        service.add_evidence(ws, it, filename="x", data=b"y", category="footage")  # a housing category
    ws_h, h = service.new_matter(st, "H", synthetic=True)
    with pytest.raises(IntakeError):
        service.add_evidence(ws_h, h, filename="x", data=b"y", category="court_order")


def test_E_every_output_value_carries_a_basis_and_nothing_is_officially_verified():
    it = new()
    stage_one(it)
    finish(it, {"nonres_discussed": "outpatient,iop", "nonres_approval": "written", "nonres_who": "fictional"})
    p = build_packet(it)
    bases = [i.basis for i in p["summary"] + p["source_map"]] + [r["basis"] for r in p["dates"]] + \
            [o["approval_basis"] for o in p["options"]]
    assert bases and all(b in out.BASIS_LABELS for b in bases)
    assert OFFICIALLY_VERIFIED not in bases
    assert basis_of(p["source_map"], "Confirmed with the issuing court or agency").value.startswith("No.")
    assert all(o["officially_verified"] == "No" for o in p["options"])


def test_E_nonresidential_availability_is_kept_apart_from_approval():
    it = new()
    stage_one(it)
    finish(it, {"nonres_discussed": "outpatient,day_reporting", "nonres_approval": "mentioned"})
    opts = out.nonresidential_comparison(it)
    assert [o["option"] for o in opts] == ["Outpatient treatment", "Day reporting"]
    assert all(o["discussed"] == "Reported as discussed" and o["approval"] == "It was only mentioned"
               for o in opts)
    assert out.NONRES_CAVEAT in build_packet(it)["text"]
    assert "approved" not in " ".join(o["approval"].lower() for o in opts)


def test_E_none_discussed_skips_the_approval_question():
    it = new()
    stage_one(it)
    finish(it, {"nonres_discussed": "none"})
    assert "nonres_approval" not in it.answers and out.nonresidential_comparison(it) == []


def test_multi_answers_are_validated_and_stored_in_a_stable_order():
    it = new()
    stage_one(it, matter="supervision", who="other")
    it.respond("criminal_case", S.ANSWERED, "no")
    with pytest.raises(IntakeError):
        it.respond("supervision_kinds", S.ANSWERED, "probation,not_sure")
    with pytest.raises(IntakeError):
        it.respond("supervision_kinds", S.ANSWERED, "probation,made_up")
    it.respond("supervision_kinds", S.ANSWERED, "prcs,state_parole,prcs")
    assert it.answers["supervision_kinds"].value == "state_parole,prcs"
    assert any("different agencies" in c for c in out.conflicts(it))


def test_F_a_correction_after_resume_changes_only_that_answer_and_keeps_history():
    it = new()
    stage_one(it, form="verbal", level="nothing_written")
    finish(it)
    before = {k: (a.status, a.value) for k, a in it.answers.items()}
    it = IncidentIntake.from_dict(it.to_dict())
    it.edit("rehab_form")
    it.respond("rehab_form", S.ANSWERED, "signed_order")
    assert it.answers["rehab_form"].value == "signed_order"
    assert it.answers["rehab_form"].history[-1]["value"] == "verbal"
    # Newly relevant: the paper's exact words are asked next.
    assert it.current == "rehab_doc_words"
    for k, v in before.items():
        if k != "rehab_form":
            assert (it.answers[k].status, it.answers[k].value) == v, k


def test_G_laylaws_own_wording_is_neutral_across_scenarios():
    scenarios = [dict(), dict(matter="both", form="signed_order", level="residential", words=DOC_WORDS_RESIDENTIAL),
                 dict(rehab="no"), dict(rehab="not_sure", who="not_sure", form="not_sure", level="not_sure", words=None),
                 dict(date=None, matter=None)]
    for kw in scenarios:
        it = new()
        stage_one(it, **kw)
        finish(it, {"nonres_discussed": "outpatient", "nonres_approval": "verbal", "hold": "yes"})
        p = build_packet(it)
        for t in p["counsel_topics"]:
            assert not re.search(r"\b(should|must|eligible|qualif|exempt|waiv)", t, re.I), t


def test_G_drifting_wording_refuses_to_render(monkeypatch):
    it = new()
    stage_one(it)
    monkeypatch.setattr(out, "HEADER", out.HEADER + " The person is eligible for outpatient.")
    with pytest.raises(PacketError):
        build_packet(it)
    monkeypatch.setattr(out, "HEADER", out.HEADER.replace(" The person is eligible for outpatient.", ""))
    monkeypatch.setattr(out, "counsel_topics", lambda _it: ["You should ask for outpatient."])
    with pytest.raises(PacketError):
        build_packet(it)


def test_G_the_persons_own_strong_words_are_quoted_not_blocked():
    it = new()
    stage_one(it, words="FICTIONAL: failure to comply is a probation violation; you must enter residential")
    finish(it, {"unresolved": "I think I'm eligible for outpatient and the order is illegal"})
    text = build_packet(it)["text"]
    assert "you must enter residential" in text and "the order is illegal" in text


def test_old_housing_saves_without_a_flow_still_load_and_unknown_flows_are_refused():
    h = IncidentIntake.new("matter-000000000001", "h", synthetic=True)
    d = h.to_dict()
    d.pop("flow")
    assert IncidentIntake.from_dict(d).flow == "housing"
    d["flow"] = "made_up"
    with pytest.raises(IntakeError):
        IncidentIntake.from_dict(d)
    with pytest.raises(IntakeError):
        IncidentIntake.new("matter-000000000002", "x", synthetic=True, flow="made_up")


# -- the local app, over real HTTP ------------------------------------------------------

def _multi(c, app, path, step, values):
    from urllib.parse import quote_plus
    body = "&".join([f"csrf={quote_plus(app.csrf)}", f"step={step}", "action=answer"]
                    + [f"multi={quote_plus(v)}" for v in values]).encode()
    return c.req("POST", path, body=body, ctype="application/x-www-form-urlencoded")


def test_H_a_first_time_user_completes_the_supervision_flow_in_the_app(running):
    app, c, root = running
    launch_and_unlock(app, c)
    _, _, home = c.req("GET", "/")
    assert "Start a criminal &amp; supervision intake" in home and "Start an incident intake" in home
    status, headers, _ = _post(c, app, "/intake/new", nickname="fictional treatment question", adult="yes",
                               flow="supervision")
    assert status == 303
    base = headers["Location"]
    ans = f"{base}/answer"

    def page():
        return c.req("GET", base)[2]

    p = page()
    assert "immediate danger" in p and "<script" not in p.lower() and 'name=viewport' in p
    _post(c, app, ans, step="danger_now", action="answer", value="no")
    _post(c, app, ans, step="about_adult", action="answer", value="yes")
    _post(c, app, ans, step="filled_by", action="answer", value="helper")
    p = page()
    assert "What is this about?" in p
    assert re.search(r"value='not_sure' checked", p), "Not sure must be pre-selected"
    _post(c, app, ans, step="matter_type", action="answer", value="not_sure")
    _post(c, app, ans, step="held_now", action="answer", value="no")
    _post(c, app, ans, step="deadline_date", action="answer", value="2026-11-03")
    for sid, v in [("deadline_what", "enroll"), ("deadline_source", "paper"), ("deadline_consequence", "nothing"),
                   ("rehab_said", "yes"), ("rehab_who", "probation"), ("rehab_form", "written_condition"),
                   ("rehab_doc_words", DOC_WORDS_GENERIC), ("rehab_recollection", RECOLLECTION),
                   ("rehab_level", "generic")]:
        _post(c, app, ans, step=sid, action="answer", value=v)
    assert "paperwork or messages" in page()
    status, _, _ = _upload(c, app, f"{base}/evidence", filename="conditions.pdf", data=ORDER_BYTES,
                           category="conditions")
    assert status == 303 and "conditions.pdf" in page()
    _post(c, app, ans, step="first_files", action="done")
    _post(c, app, ans, step="hoping_for", action="answer", value=HOPE)
    _post(c, app, ans, step="stage_gate", action="answer", value="now")
    _post(c, app, ans, step="criminal_case", action="answer", value="no")
    p = page()
    assert "Choose all that apply" in p and "type=checkbox name=multi" in p
    _multi(c, app, ans, "supervision_kinds", ["prcs", "probation"])
    while True:
        p = page()
        m = re.search(r"name=step value='([a-z_]+)'", p)
        if not m or "Everything has been asked" in p:
            break
        sid = m.group(1)
        if sid == "nonres_discussed":
            _multi(c, app, ans, sid, ["outpatient"])
        else:
            _post(c, app, ans, step=sid, action="not_sure" if sid != "nonres_approval" else "answer",
                  value="mentioned")
    _, _, review = c.req("GET", f"{base}/review")
    review = html.unescape(review)
    assert "Everything has been asked" in review
    assert "DOCUMENT STATES (as typed in)" in review and "CLIENT REPORTED" in review
    assert "County probation; Post-release community supervision (PRCS)" in review
    assert "Officially verified" in review
    status, _, packet = c.req("GET", f"{base}/packet")
    packet = html.unescape(packet)
    assert status == 200 and "RAPID SITUATION SUMMARY" in packet and "all unchanged" in packet
    assert "SYNTHETIC TEST DATA" in packet
    log = b"".join(p.read_bytes() for p in Path(root).rglob("*") if p.is_file())
    for marker in (DOC_WORDS_GENERIC, RECOLLECTION, HOPE):
        assert marker.encode() not in log


def test_H_an_unknown_flow_creates_nothing(running):
    app, c, _ = running
    launch_and_unlock(app, c)
    status, headers, _ = _post(c, app, "/intake/new", nickname="x", adult="yes", flow="made_up")
    assert status == 303 and headers["Location"] == "/"
    _, _, home = c.req("GET", "/")
    assert "isn't available" in html.unescape(home)
    assert not re.search(r"/n/matter-[0-9a-f]{12}/", home)
