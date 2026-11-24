"""Seam: SessionStartData's interview field and the v2 client event envelope."""

import pytest
from pydantic import ValidationError

from app.realtime.events import SessionStartData, V2ClientEvent

PLAN = {"interview_id": "abc", "question_ids": ["q1", "q2"]}


def test_interview_field_parses_for_interview_mode() -> None:
    data = SessionStartData.model_validate({"mode": "interview", "interview": PLAN})
    assert data.interview is not None
    assert data.interview.interview_id == "abc"
    assert data.interview.question_ids == ["q1", "q2"]


def test_interview_mode_without_the_field_stays_questionless() -> None:
    assert SessionStartData.model_validate({"mode": "interview"}).interview is None


@pytest.mark.parametrize("mode", ["presentation", None])
def test_interview_field_needs_interview_mode(mode: str | None) -> None:
    data = {"interview": PLAN, **({"mode": mode} if mode else {})}
    with pytest.raises(ValidationError):
        SessionStartData.model_validate(data)


@pytest.mark.parametrize(
    "interview",
    [
        {"interview_id": "abc", "question_ids": []},
        {"interview_id": "abc", "question_ids": ["q1", "q1"]},
        {"interview_id": "", "question_ids": ["q1"]},
        {"question_ids": ["q1"]},
        {"interview_id": "abc"},
    ],
)
def test_malformed_interview_field_is_rejected(interview: dict) -> None:
    with pytest.raises(ValidationError):
        SessionStartData.model_validate({"mode": "interview", "interview": interview})


def test_replay_is_a_v2_client_event() -> None:
    event = V2ClientEvent.model_validate(
        {
            "event": "interview.replay",
            "version": 2,
            "session_id": None,
            "sequence": 1,
            "module": "system",
            "level": "info",
            "data": {"question_id": "q1"},
        }
    )
    assert event.data == {"question_id": "q1"}
