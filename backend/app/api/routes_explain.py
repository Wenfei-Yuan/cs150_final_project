"""
Routes: /explain
  POST /explain/selection   — neutral chatbot: explain a highlighted passage
  POST /explain/follow-up   — answer a follow-up question about the explanation
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.explain_service import ExplainService

router = APIRouter()


class ExplainRequest(BaseModel):
    document_id: str
    selected_text: str = Field(..., min_length=1, max_length=2000)
    surrounding_text: str = Field(
        default="",
        description="Optional: text surrounding the selection to provide context.",
    )


class ExplainResponse(BaseModel):
    selected_text: str
    explanation: str


class FollowUpTurn(BaseModel):
    question: str
    answer: str


class FollowUpRequest(BaseModel):
    selected_text: str = Field(..., min_length=1, max_length=2000)
    explanation: str = Field(..., min_length=1, max_length=4000)
    question: str = Field(..., min_length=1, max_length=1000)
    history: list[FollowUpTurn] = Field(default_factory=list)


class FollowUpResponse(BaseModel):
    answer: str


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
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return ExplainResponse(
        selected_text=payload.selected_text,
        explanation=explanation,
    )


@router.post(
    "/follow-up",
    response_model=FollowUpResponse,
    summary="Answer a follow-up question about an explanation",
)
async def explain_follow_up(
    payload: FollowUpRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Accepts a follow-up question from the user along with the original selected
    text, the explanation already given, and any prior Q&A history.
    Returns a concise, neutral answer.
    """
    svc = ExplainService(db)
    answer = await svc.follow_up(
        selected_text=payload.selected_text,
        explanation=payload.explanation,
        question=payload.question,
        history=[t.model_dump() for t in payload.history],
    )
    return FollowUpResponse(answer=answer)
