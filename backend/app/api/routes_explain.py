"""
Routes: /explain
  POST /explain/selection   — neutral chatbot: explain a highlighted passage
"""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.explain_service import ExplainService

router = APIRouter()


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ExplainRequest(BaseModel):
    document_id: str
    selected_text: str = Field(..., min_length=1, max_length=2000)
    surrounding_text: str = Field(default="")
    conversation_history: list[ConversationMessage] = Field(default=[])
    follow_up_question: str | None = Field(default=None, max_length=1000)


class ExplainResponse(BaseModel):
    selected_text: str
    explanation: str


@router.post(
    "/selection",
    response_model=ExplainResponse,
    summary="Explain a highlighted passage (neutral chatbot, reading stage only)",
)
async def explain_selection(
    payload: ExplainRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Accepts the text the user has highlighted and returns a neutral explanation.
    This endpoint intentionally carries NO persona voice — it is a controlled
    variable in the experiment.
    """
    svc = ExplainService(db)
    try:
        explanation = await svc.explain_selection(
            document_id=payload.document_id,
            selected_text=payload.selected_text,
            surrounding_text=payload.surrounding_text,
            conversation_history=[m.model_dump() for m in payload.conversation_history],
            follow_up_question=payload.follow_up_question,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return ExplainResponse(
        selected_text=payload.selected_text,
        explanation=explanation,
    )
