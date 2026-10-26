"""Local app: one workspace label, one client (isolation review findings L3, L4, L5).

A label already in use, or one that could collide with an incident intake ("matter-..."), is
refused before anything is created; the opening confirmation names the workspace; every
interview shows on Home; and deleting one thing never erases another's interview.
Over real HTTP on 127.0.0.1. ALL DATA IS SYNTHETIC AND FICTIONAL.
"""
import pytest

from laylaw.intake import service as intake_service
from laylaw.intake.model import IntakeError
from laylaw.interviewer.paths import start_path
from test_local_app import launch_and_unlock, post_answer, question_of, running  # noqa: F401

IN_USE = "is already in use, so nothing was started"
RESERVED = "that name is kept for incident intakes"


@pytest.fixture
def app_c(running):
    app, c, *_ = running
    launch_and_unlock(app, c)
    return app, c


def new(app, c, label, who="Jordan Avery", case="CASE-FICTIONAL-001"):
    return c.req("POST", "/new", {"csrf": app.csrf, "client_id": label, "case_id": case, "interviewee": who,
                                  "path_name": "family_law", "adult": "yes"})


def started(app, c, label, **kw):
    status, h, _ = new(app, c, label, **kw)
    assert status == 303 and h["Location"].startswith(f"/i/{label}/INT-"), h.get("Location")
    return h["Location"]


def new_intake(app, c):
    _, h, _ = c.req("POST", "/intake/new", {"csrf": app.csrf, "adult": "yes", "nickname": "fictional", "flow": "housing"})
    _, cid, mid = h["Location"].split("/")[1:]
    return cid, mid


def counts(app):
    return {cid: len(app.store.existing_workspace(cid).list_sessions()) for cid in app.store.list_clients()}


# ============================================================ accidental reuse
@pytest.mark.parametrize("again", ["client-fictional-a", "CLIENT-Fictional-A"])
def test_reusing_a_label_is_refused_and_creates_nothing(app_c, again):
    app, c = app_c
    first = started(app, c, "client-fictional-a")
    before = counts(app)
    status, h, _ = new(app, c, again, who="Casey Lin", case="CASE-FICTIONAL-002")
    assert status == 303 and h["Location"] == "/"
    assert counts(app) == before                                 # no interview, no new workspace
    _, _, home = c.req("GET", "/")
    assert IN_USE in home and "Casey Lin" not in home
    ws = app.store.existing_workspace("client-fictional-a")
    assert [m["interviewee"] for m in ws.session_summaries()] == ["Jordan Avery"]
    assert c.req("GET", first)[0] == 200                         # the first client's interview is untouched


def test_different_labels_still_start_separate_workspaces(app_c):
    app, c = app_c
    started(app, c, "client-fictional-a")
    started(app, c, "client-fictional-b", who="Casey Lin")
    assert counts(app) == {"client-fictional-a": 1, "client-fictional-b": 1}


# ============================================================ intake collision
def test_label_equal_to_an_intake_id_is_refused(app_c):
    app, c = app_c
    matter_cid, mid = new_intake(app, c)
    status, h, _ = new(app, c, matter_cid)
    assert h["Location"] == "/"
    assert app.store.existing_workspace(matter_cid).list_sessions() == []    # nothing placed in the intake
    assert intake_service.load(app.store.existing_workspace(matter_cid), mid).matter_id == mid
    assert RESERVED in c.req("GET", "/")[2]


@pytest.mark.parametrize("label", ["matter-smith", "Matter-Smith", "MATTER-0123456789ab"])
def test_matter_prefixed_labels_are_refused(app_c, label):
    app, c = app_c
    new(app, c, label)
    assert label not in app.store.list_clients() and counts(app) == {}


# ============================================================ the opening confirmation names the workspace
def test_opening_confirmation_names_the_workspace_case_and_person(app_c):
    app, c = app_c
    url = started(app, c, "client-fictional-a", case="CASE-FICTIONAL-777")
    _, _, page = c.req("GET", url)
    q = question_of(page)
    assert q == ('Just to confirm before we begin: this interview is for Jordan Avery (case CASE-FICTIONAL-777), '
                 'in the workspace "client-fictional-a". Is that right?')
    post_answer(app, c, url, page=page, action="answer", answer="Yes, that's right.")
    s = app.session(*url.split("/")[2:4])
    item = next(i for i in s.intake if i.key == "confirm_workspace")
    assert '"client-fictional-a"' in item.question                # the record keeps what was asked
    assert s.workspace_confirmed is True


def test_without_a_label_the_confirmation_wording_is_unchanged(store):
    """The web app's workspace id is opaque, so it is not shown to the interviewee."""
    s, _ = start_path("family_law", store.workspace("client-fictional-a"), case_id="CASE-FICTIONAL-001",
                      interviewee="Jordan Avery", interviewer="x", purpose="p", interviewee_is_adult=True)
    assert s.next_question() == ("Just to confirm before we begin: this interview is for Jordan Avery "
                                 "(case CASE-FICTIONAL-001). Is that right?")


# ============================================================ Home visibility
def test_every_interview_shows_on_home_with_its_workspace(app_c):
    app, c = app_c
    new_intake(app, c)
    urls = [started(app, c, label, who=who) for label, who in
            (("client-fictional-a", "Jordan Avery"), ("client-fictional-b", "Casey Lin"))]
    new(app, c, "client-fictional-a", who="Sam Rowe")            # refused: never hidden, never mixed
    new(app, c, "matter-fictional", who="Pat Doe")               # refused
    _, _, home = c.req("GET", "/")
    for url, who in zip(urls, ("Jordan Avery", "Casey Lin")):
        assert f"href='{url}'>{who}</a>" in home
    assert "Sam Rowe" not in home and "Pat Doe" not in home
    listed = sum(counts(app)[cid] for cid in app.store.list_clients() if not cid.startswith("matter-"))
    assert listed == home.count("href='/i/") == 2               # nothing exists that Home doesn't show


# ============================================================ deletion isolation
def test_deleting_an_intake_leaves_every_interview(app_c):
    app, c = app_c
    url = started(app, c, "client-fictional-a")
    matter_cid, mid = new_intake(app, c)
    c.req("POST", f"/n/{matter_cid}/{mid}/delete", {"csrf": app.csrf, "confirm": "DELETE"})
    assert matter_cid not in app.store.list_clients()
    app.sessions.clear()
    assert c.req("GET", url)[0] == 200 and counts(app) == {"client-fictional-a": 1}


def test_deleting_one_interview_leaves_the_other_clients(app_c):
    app, c = app_c
    ua = started(app, c, "client-fictional-a")
    ub = started(app, c, "client-fictional-b", who="Casey Lin")
    c.req("POST", ua.replace("/i/", "/d/"), {"csrf": app.csrf, "confirm": "DELETE"})
    app.sessions.clear()
    assert c.req("GET", ua)[0] == 404 and c.req("GET", ub)[0] == 200


def test_an_older_vault_with_an_interview_inside_an_intake_refuses_to_delete_it(app_c):
    """Vaults from before labels were checked may already hold one; deleting the intake must not erase it."""
    app, c = app_c
    matter_cid, mid = new_intake(app, c)
    s, _ = start_path("family_law", app.store.existing_workspace(matter_cid), case_id="CASE-FICTIONAL-001",
                      interviewee="Jordan Avery", interviewer="x", purpose="p", interviewee_is_adult=True)
    with pytest.raises(IntakeError):
        intake_service.delete_matter(app.store, matter_cid)
    c.req("POST", f"/n/{matter_cid}/{mid}/delete", {"csrf": app.csrf, "confirm": "DELETE"})
    ws = app.store.existing_workspace(matter_cid)
    assert ws.list_sessions() == [s.interview_id] and ws.list_records("intake") == [mid]
    assert "also holds an interview, so nothing was deleted" in c.req("GET", f"/n/{matter_cid}/{mid}")[2]
