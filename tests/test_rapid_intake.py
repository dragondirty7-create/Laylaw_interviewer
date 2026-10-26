"""Rapid Incident Intake: engine, storage and the local app, end to end.

ALL DATA IS SYNTHETIC AND FICTIONAL. Distinctive marker strings are used for
the child-related answers so tests can prove they never reach the audit log,
the vault's files on disk, or any other matter.
"""
import hashlib
import html
import re
import threading
import uuid
from pathlib import Path

import pytest

from laylaw.app.server import LaylawApp, launch_url, make_server
from laylaw.intake import service
from laylaw.intake.chronology import CONFLICT, EVIDENCE, INFERENCE, UNKNOWN, USER_STATEMENT, chronology, conflicts
from laylaw.intake.model import AnswerStatus as S, IncidentIntake, IntakeError
from laylaw.intake.packet import CONCLUSION_WORDS, build_packet, counsel_topics, HEADER
from laylaw.intake.steps import STEP_BY_ID, STEPS
from laylaw.interviewer.guard import find_advocacy
from laylaw.secure.mode import AccessGate
from laylaw.secure.secrets_store import MemorySecretStore
from laylaw.secure.vault import init_vault

from test_local_app import PASS, Client, launch_and_unlock

CHILD_SITUATION = "FICTIONAL-CHILD-SITUATION-QX7"
CHILD_WORDS = "FICTIONAL-CHILD-WORDS-ZK4"
HEARD_BY = "FICTIONAL-HEARD-BY-PL2"
EVIDENCE_BYTES = b"FICTIONAL-DOORBELL-CLIP-BYTES-0001"


def stage_one(it: IncidentIntake, *, notice="no", consent="no", gate="now"):
    for sid, st, v in [("danger_now", S.ANSWERED, "no"),
                       ("summary", S.ANSWERED, "A fictional worker came into the fictional apartment."),
                       ("incident_date", S.ANSWERED, "2026-10-01"),
                       ("entrant", S.ANSWERED, "fictional maintenance worker"),
                       ("notice_given", S.ANSWERED, notice),
                       ("consent_given", S.ANSWERED, consent),
                       ("first_files", S.SKIPPED, None),
                       ("stage_gate", S.ANSWERED, gate)]:
        assert it.current == sid, (it.current, sid)
        it.respond(sid, st, v)


def finish(it: IncidentIntake, *, child=True, child_spoke=True):
    while it.current:
        sid = it.current
        step = STEP_BY_ID[sid]
        if sid == "child_present":
            it.respond(sid, S.ANSWERED, "yes" if child else "no")
        elif sid == "child_situation":
            it.respond(sid, S.ANSWERED, CHILD_SITUATION)
        elif sid == "child_spoke":
            it.respond(sid, S.ANSWERED, "yes" if child_spoke else "no")
        elif sid == "child_words":
            it.respond(sid, S.ANSWERED, CHILD_WORDS)
        elif sid == "child_words_heard_by":
            it.respond(sid, S.ANSWERED, HEARD_BY)
        elif sid == "what_happened":
            it.respond(sid, S.ANSWERED, "10:15 knock at the door\nthe door opened\nabout 10:17 - he left")
        elif step.kind == "choice":
            it.respond(sid, S.NOT_SURE)
        else:
            it.respond(sid, S.ANSWERED, f"fictional {sid}")


# -- the question flow ---------------------------------------------------------

def test_stage_one_is_the_light_first_pass_and_asks_danger_first():
    stage1 = [s.id for s in STEPS if s.stage == 1]
    assert stage1[0] == "danger_now"
    assert stage1 == ["danger_now", "summary", "incident_date", "entrant", "notice_given", "consent_given",
                      "first_files", "stage_gate"]
    it = IncidentIntake.new("matter-000000000001", "x", synthetic=True)
    stage_one(it)
    assert STEP_BY_ID[it.current].stage == 2


def test_every_question_offers_not_sure_or_skip_and_none_asks_for_a_legal_classification():
    for step in STEPS:
        if step.kind == "choice" and step.id != "stage_gate":
            assert "not_sure" in dict(step.choices), step.id
        text = " ".join([step.prompt, step.help, step.example]).lower()
        for legal in ("trespass", "violation", "unlawful", "illegal", "statute", "cause of action", "claim"):
            assert legal not in text, (step.id, legal)


def test_child_questions_appear_only_when_a_child_was_there_and_are_minimal():
    it = IncidentIntake.new("matter-000000000002", "x", synthetic=True)
    stage_one(it)
    finish(it, child=False)
    asked = set(it.answers)
    assert not asked & {"child_age_range", "child_situation", "child_spoke", "child_words"}
    minor_steps = [s for s in STEPS if "minor" in s.tags]
    assert {s.id for s in minor_steps} == {"child_age_range", "child_situation", "child_spoke", "child_words",
                                           "child_words_heard_by"}
    for s in minor_steps:
        assert "name" not in s.prompt.lower() and "photo" not in s.prompt.lower()
        assert s.max_len <= 300
    assert all(s.why for s in minor_steps if s.id in ("child_age_range", "child_situation"))


def test_childs_words_are_recorded_once_and_never_replaced():
    it = IncidentIntake.new("matter-000000000003", "x", synthetic=True)
    stage_one(it)
    finish(it)
    assert it.child_statement["words"] == CHILD_WORDS
    it.edit("child_words")
    with pytest.raises(IntakeError):
        it.respond("child_words", S.ANSWERED, "a different version")
    assert it.child_statement["words"] == CHILD_WORDS


def test_a_change_keeps_the_earlier_answer_and_opens_newly_relevant_questions():
    it = IncidentIntake.new("matter-000000000004", "x", synthetic=True)
    stage_one(it)
    finish(it, child=False)
    assert it.finished
    it.edit("child_present")
    it.respond("child_present", S.ANSWERED, "yes")
    assert it.answers["child_present"].history[0]["value"] == "no"
    assert it.current == "child_age_range"


def test_answers_to_questions_that_stop_applying_are_set_aside_not_kept_as_facts():
    it = IncidentIntake.new("matter-000000000005", "x", synthetic=True)
    stage_one(it, notice="yes")
    finish(it)
    assert it.value("notice_details") == "fictional notice_details"
    it.edit("notice_given")
    it.respond("notice_given", S.ANSWERED, "no")
    assert "notice_details" not in it.answers
    assert it.answers["_set_aside_notice_details"].history[0]["value"] == "fictional notice_details"


def test_validation_explains_what_is_missing():
    it = IncidentIntake.new("matter-000000000006", "x", synthetic=True)
    with pytest.raises(IntakeError, match="not sure"):
        it.respond("danger_now", S.ANSWERED, "")
    with pytest.raises(IntakeError, match="options"):
        it.respond("danger_now", S.ANSWERED, "maybe")
    with pytest.raises(IntakeError, match="isn't the one being asked"):
        it.respond("summary", S.ANSWERED, "out of order")
    it.respond("danger_now", S.ANSWERED, "no")
    it.respond("summary", S.ANSWERED, "fictional")
    with pytest.raises(IntakeError, match="date"):
        it.respond("incident_date", S.ANSWERED, "last tuesday")


def test_save_and_resume_round_trip_preserves_everything():
    it = IncidentIntake.new("matter-000000000007", "x", synthetic=True)
    stage_one(it)
    finish(it)
    again = IncidentIntake.from_dict(it.to_dict())
    assert again.to_dict() == it.to_dict()


# -- chronology and packet ---------------------------------------------------------

def test_chronology_labels_what_each_row_rests_on():
    it = IncidentIntake.new("matter-000000000008", "x", synthetic=True)
    stage_one(it)
    finish(it)
    rows = chronology(it)
    assert rows[0].when == "2026-10-01, 10:15" and rows[0].basis == USER_STATEMENT
    assert rows[1].when.endswith("time not given") and rows[1].when_basis == INFERENCE
    assert rows[2].when == "2026-10-01, about 10:17"  # the hedge is kept
    assert any(r.when_basis == UNKNOWN for r in rows)  # management response, no date


def test_unknown_date_is_unknown_and_conflicts_are_kept_not_resolved():
    it = IncidentIntake.new("matter-000000000009", "x", synthetic=True)
    it.respond("danger_now", S.ANSWERED, "no")
    it.respond("summary", S.ANSWERED, "fictional")
    it.respond("incident_date", S.NOT_SURE)
    assert chronology(it)[0].when_basis == UNKNOWN
    it.respond("entrant", S.ANSWERED, "fictional")
    it.respond("notice_given", S.ANSWERED, "no")
    from laylaw.intake.model import EvidenceItem
    it.add_evidence(EvidenceItem(id="R-1", category="entry_notice", filename="n.jpg", sha256="0" * 64, size=1,
                                 stored_at="t", date_text="2026-09-30"))
    found = conflicts(it)
    assert found and "Both are kept" in found[0]
    assert any(r.basis == EVIDENCE for r in chronology(it))


def test_packet_is_neutral_and_contains_every_required_section():
    it = IncidentIntake.new("matter-000000000010", "x", synthetic=True)
    stage_one(it)
    finish(it)
    p = build_packet(it)
    for heading in ("CHRONOLOGY", "EVIDENCE INDEX", "OPEN QUESTIONS", "TOPICS FOR A LICENSED LAWYER TO EVALUATE"):
        assert heading in p["text"]
    assert "SYNTHETIC TEST DATA" in p["text"]
    for text in [HEADER, *counsel_topics(it)]:
        assert not find_advocacy(text), text
        assert not CONCLUSION_WORDS.search(text), text
    assert f"“{CHILD_WORDS}”" in p["text"]


def test_packet_refuses_to_render_if_laylaws_own_wording_drifts(monkeypatch):
    import laylaw.intake.packet as packet
    it = IncidentIntake.new("matter-000000000011", "x", synthetic=True)
    stage_one(it)
    monkeypatch.setattr(packet, "counsel_topics", lambda _it: ["This was a clear violation."])
    with pytest.raises(packet.PacketError):
        packet.build_packet(it)


def test_the_persons_own_words_are_quoted_even_if_they_use_strong_language():
    it = IncidentIntake.new("matter-000000000012", "x", synthetic=True)
    it.respond("danger_now", S.ANSWERED, "no")
    it.respond("summary", S.ANSWERED, "I think it was illegal and a violation.")
    assert "I think it was illegal and a violation." in build_packet(it)["text"]


# -- storage: isolation, originals, logs -----------------------------------------------

@pytest.fixture
def store(tmp_path):
    ss = MemorySecretStore()
    root = tmp_path / "vault"
    v, _ = init_vault(root, PASS, secret_store=ss, mode="synthetic", kdf_n=2 ** 12)
    v.lock()
    st = AccessGate(root, ss).open(PASS)
    yield st, root
    st.vault.lock()


def test_each_intake_is_its_own_matter_and_cannot_be_read_from_another(store):
    st, _ = store
    ws_a, a = service.new_matter(st, "A", synthetic=True)
    ws_b, b = service.new_matter(st, "B", synthetic=True)
    assert ws_a.client_id != ws_b.client_id
    with pytest.raises(FileNotFoundError):
        service.load(ws_b, a.matter_id)
    with pytest.raises(IntakeError):
        service.save(ws_b, a)
    other = st.workspace("client-chelsea-fictional")
    assert other.list_records("intake") == []


def test_originals_are_kept_byte_for_byte_and_notes_live_beside_them(store):
    st, _ = store
    ws, it = service.new_matter(st, "A", synthetic=True)
    item = service.add_evidence(ws, it, filename="doorbell.mp4", data=EVIDENCE_BYTES, category="footage",
                                source="fictional phone", date_text="2026-10-01 10:20", notes="fictional note")
    assert item.sha256 == hashlib.sha256(EVIDENCE_BYTES).hexdigest()
    reloaded = service.load(ws, it.matter_id)
    reloaded.evidence[0].notes = "edited fictional note"
    service.save(ws, reloaded)
    assert service.verify_evidence(ws, reloaded) == {item.id: True}
    with pytest.raises(IntakeError):
        service.add_evidence(ws, reloaded, filename="x", data=b"y", category="not-a-category")


def test_child_details_never_reach_the_audit_log_or_disk_in_plain_text(store):
    st, root = store
    ws, it = service.new_matter(st, "A", synthetic=True)
    stage_one(it)
    finish(it)
    service.save(ws, it)
    service.add_evidence(ws, it, filename="clip.mp4", data=EVIDENCE_BYTES, category="footage")
    raw = b"".join(p.read_bytes() for p in Path(root).rglob("*") if p.is_file())
    for marker in (CHILD_SITUATION, CHILD_WORDS, HEARD_BY, "fictional maintenance worker"):
        assert marker.encode() not in raw, marker
    assert EVIDENCE_BYTES not in raw


def test_deleting_a_matter_removes_its_record_and_files_only(store):
    st, _ = store
    ws_a, a = service.new_matter(st, "A", synthetic=True)
    ws_b, b = service.new_matter(st, "B", synthetic=True)
    service.add_evidence(ws_a, a, filename="a.txt", data=b"fictional a", category="other")
    counts = service.delete_matter(st, ws_a.client_id)
    assert counts["records"] == 1 and counts["uploads"] == 1
    assert ws_a.client_id not in st.list_clients()
    assert service.load(ws_b, b.matter_id).matter_id == b.matter_id
    with pytest.raises(IntakeError):
        service.delete_matter(st, "client-chelsea-fictional")


# -- the local app, over real HTTP --------------------------------------------------------

@pytest.fixture
def running(tmp_path):
    ss = MemorySecretStore()
    root = tmp_path / "vault"
    v, _ = init_vault(root, PASS, secret_store=ss, mode="synthetic", kdf_n=2 ** 12)
    v.lock()
    app = LaylawApp(root, ss)
    server = make_server(app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield app, Client(app.port), root
    server.shutdown()
    server.server_close()


def _post(c, app, path, **form):
    return c.req("POST", path, {"csrf": app.csrf, **form})


def _upload(c, app, path, *, filename, data, category, back="step"):
    b = uuid.uuid4().hex
    parts = [("csrf", app.csrf), ("category", category), ("back", back), ("source", "fictional phone")]
    body = "".join(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n" for k, v in parts)
    body = (body.encode() + f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n".encode() + data + f"\r\n--{b}--\r\n".encode())
    return c.req("POST", path, body=body, ctype=f"multipart/form-data; boundary={b}")


def test_a_first_time_user_completes_the_whole_flow_in_the_app(running):
    app, c, root = running
    launch_and_unlock(app, c)
    _, _, home = c.req("GET", "/")
    assert "Start an incident intake" in home

    status, headers, _ = _post(c, app, "/intake/new", nickname="fictional entry", adult="yes")
    assert status == 303
    base = headers["Location"]
    assert re.fullmatch(r"/n/matter-[0-9a-f]{12}/N-[0-9a-f]{12}", base)

    _, _, page = c.req("GET", base)
    assert "is anyone in danger right now" in page and "The essentials" in page
    assert "<script" not in page.lower()

    # Danger: yes shows the neutral safety prompt on the next page, and the flow continues.
    _post(c, app, f"{base}/answer", step="danger_now", action="answer", value="yes")
    _, _, page = c.req("GET", base)
    page = html.unescape(page)
    assert "call 911" in page and "doesn't decide what to do" in page

    _post(c, app, f"{base}/answer", step="summary", action="answer", value="Fictional entry while bathing.")
    _post(c, app, f"{base}/answer", step="incident_date", action="not_sure")
    _post(c, app, f"{base}/answer", step="entrant", action="answer", value="fictional worker")
    _post(c, app, f"{base}/answer", step="notice_given", action="answer", value="no")
    _post(c, app, f"{base}/answer", step="consent_given", action="answer", value="no")

    _, _, page = c.req("GET", base)
    assert "Do you have anything already" in page
    status, headers, _ = _upload(c, app, f"{base}/evidence", filename="clip.mp4", data=EVIDENCE_BYTES,
                                 category="footage")
    assert status == 303 and headers["Location"] == base
    _, _, page = c.req("GET", base)
    assert "clip.mp4" in page and "original kept unchanged" in page
    _post(c, app, f"{base}/answer", step="first_files", action="done")

    # "Not now" at the gate saves and returns home; the intake resumes at the deeper questions.
    status, headers, _ = _post(c, app, f"{base}/answer", step="stage_gate", action="answer", value="later")
    assert headers["Location"] == "/"
    _, _, page = c.req("GET", base)
    assert "About what time was it?" in page

    # Gentle validation: an empty answer explains what's missing and stays on the question.
    _post(c, app, f"{base}/answer", step="incident_time", action="answer", value="")
    _, _, page = c.req("GET", base)
    assert "Add an answer" in html.unescape(page) and "About what time was it?" in page

    # A stale form (a question that is no longer current) is refused, not applied.
    _post(c, app, f"{base}/answer", step="location", action="answer", value="out of order")
    _, _, page = c.req("GET", base)
    assert "isn't the one being asked" in html.unescape(page)

    # Answer the rest the way a first-time user might: mostly skip or not sure.
    for _ in range(60):
        _, _, page = c.req("GET", base)
        m = re.search(r"name=step value='([a-z_]+)'", page)
        if not m:
            break
        sid = m.group(1)
        if sid == "child_present":
            _post(c, app, f"{base}/answer", step=sid, action="answer", value="yes")
        elif sid == "child_situation":
            _post(c, app, f"{base}/answer", step=sid, action="answer", value=CHILD_SITUATION)
        elif sid == "child_spoke":
            _post(c, app, f"{base}/answer", step=sid, action="answer", value="no")
        else:
            _post(c, app, f"{base}/answer", step=sid, action="skip")
    _, _, page = c.req("GET", base)
    assert "Everything has been asked" in page

    status, _, packet = c.req("GET", f"{base}/packet")
    assert status == 200 and "REFERRAL PACKET" in packet and "all unchanged" in packet
    assert "TOPICS FOR A LICENSED LAWYER TO EVALUATE" in packet

    # Nothing child-related, and no case wording, in the audit log.
    audit = b"".join(p.read_bytes() for p in Path(root).rglob("*audit*") if p.is_file())
    assert audit, "expected an audit log"
    for marker in (CHILD_SITUATION.encode(), b"Fictional entry while bathing", b"fictional worker", b"clip.mp4"):
        assert marker not in audit

    # The interview list doesn't show intake matters as interviews.
    _, _, home = c.req("GET", "/")
    assert "fictional entry" in home
    interviews = home.split("<h2>Incident intakes</h2>")[0]
    assert "matter-" not in interviews


def test_one_matter_cannot_be_reached_through_another_matters_url(running):
    app, c, _ = running
    launch_and_unlock(app, c)
    _, h1, _ = _post(c, app, "/intake/new", nickname="one", adult="yes")
    _, h2, _ = _post(c, app, "/intake/new", nickname="two", adult="yes")
    a_cid, a_mid = h1["Location"].split("/")[2:4]
    b_cid, b_mid = h2["Location"].split("/")[2:4]
    status, _, _ = c.req("GET", f"/n/{a_cid}/{b_mid}")
    assert status == 404
    status, _, _ = _post(c, app, f"/n/{a_cid}/{b_mid}/answer", step="danger_now", action="answer", value="no")
    assert status == 404
    status, _, _ = c.req("GET", f"/n/client-x/{a_mid}")
    assert status == 404


def test_intake_requires_the_adult_confirmation_and_csrf(running):
    app, c, _ = running
    launch_and_unlock(app, c)
    status, headers, _ = _post(c, app, "/intake/new", nickname="x")
    assert headers["Location"] == "/"
    _, _, home = c.req("GET", "/")
    assert "Confirm you're an adult" in html.unescape(home)
    status, _, _ = c.req("POST", "/intake/new", {"csrf": "wrong", "adult": "yes"})
    assert status == 403
