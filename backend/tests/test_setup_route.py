from unittest.mock import AsyncMock, patch

import pytest

from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.session import AsyncSessionLocal


@pytest.mark.asyncio
@patch("app.services.session_setup_service.chat_completion_json", new_callable=AsyncMock)
async def test_setup_route_returns_cli_compatible_mode_choices(mock_chat_completion, client):
    mock_chat_completion.return_value = {
        "mode": "skim",
        "reasoning": "Skim fits a short overview session.",
        "mode_explanation": "Skim mode matches the user's limited time.",
        "mode_flow_description": "Read a few key sections -> get an overview -> continue if needed.",
    }

    async with AsyncSessionLocal() as db:
        document = Document(
            user_id="setup-route-user",
            filename="setup-route.pdf",
            file_path="setup-route.pdf",
            raw_text="Introduction text",
            status="indexed",
            page_count=1,
        )
        db.add(document)
        await db.commit()
        await db.refresh(document)

        db.add(
            Chunk(
                document_id=document.id,
                chunk_index=0,
                text="Introduction text",
                token_count=2,
                section="Introduction",
                section_type="introduction",
                section_index=0,
            )
        )
        await db.commit()

    create_response = await client.post(
        "/sessions",
        json={"user_id": "setup-route-user", "document_id": str(document.id)},
    )

    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]

    setup_response = await client.post(
        f"/sessions/{session_id}/setup",
        json={"reading_purpose": 0, "available_time": 0, "support_needed": 0},
    )

    assert setup_response.status_code == 200
    payload = setup_response.json()

    assert payload["recommended_mode"] == "skim"
    assert [choice["mode"] for choice in payload["available_modes"]] == [
        "skim",
        "goal_directed",
        "deep_comprehension",
    ]
    assert [choice["mode"] for choice in payload["alternative_modes"]] == [
        "goal_directed",
        "deep_comprehension",
    ]
    assert all(isinstance(choice["description"], str) for choice in payload["available_modes"])