"""Shared fixtures. ALL DATA IS SYNTHETIC AND FICTIONAL.

No real person's case facts appear anywhere in this test suite. Names such as
"Jordan Avery", "Sam Rowe", "Casey Lin" and child "Pip" are invented.
"""
import pytest

from laylaw.interviewer import InterviewSession, WorkspaceStore


@pytest.fixture
def store(tmp_path):
    return WorkspaceStore(tmp_path / "laylaw-data")


@pytest.fixture
def ws(store):
    return store.workspace("client-fictional-a")


def new_session(ws, sections=("Specific incidents",), interviewee="Jordan Avery"):
    return InterviewSession.start(
        ws, case_id="CASE-FICTIONAL-001", interviewee=interviewee, interviewer="Laylaw Interviewer",
        purpose="Synthetic test interview", sections=list(sections), interviewee_is_adult=True)


@pytest.fixture
def session(ws):
    return new_session(ws)
