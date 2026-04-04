from unittest.mock import AsyncMock

import pytest

from app.api.routes_session import submit_takeaway
from app.schemas.mode import TakeawayRequest, TakeawayResponse


@pytest.mark.asyncio
async def test_takeaway_route_preserves_goal_feedback_shape():
    """Route contract should preserve strengths and limitations for goal mode."""

    fake_agent = type("FakeAgent", (), {})()
    fake_agent.handle_takeaway = AsyncMock(return_value={
        "feedback": "You extracted the target information and answered the question well.",
        "strengths": ["Captured the main finding"],
        "limitations": ["Could add more evidence from the methods section"],
        "status": "completed",
    })

    result = await submit_takeaway(
        session_id="test-session",
        payload=TakeawayRequest(text="Yes, I found it. The paper uses interviews."),
        agent=fake_agent,
    )
    serialized = TakeawayResponse.model_validate(result).model_dump()

    assert serialized == {
        "feedback": "You extracted the target information and answered the question well.",
        "status": "completed",
        "strengths": ["Captured the main finding"],
        "limitations": ["Could add more evidence from the methods section"],
    }