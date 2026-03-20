"""
Routes: /eval/* — offline evaluation endpoints (for grading the pipeline).
These are intended for developer/TA use, not end users.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.chunk_service import ChunkService
from app.services.summary_service import SummaryService
from app.services.question_service import QuestionService
from app.services.feedback_service import FeedbackService

router = APIRouter()


class ChunkEvalRequest(BaseModel):
    document_id: str
    chunk_index: int


class RetellEvalRequest(BaseModel):
    document_id: str
    chunk_index: int
    retell: str


@router.post("/summary", summary="Run summary generation for a specific chunk")
async def eval_summary(req: ChunkEvalRequest, db: AsyncSession = Depends(get_db)):
    chunk_svc = ChunkService(db)
    summary_svc = SummaryService(db)
    chunk = await chunk_svc.get_chunk_by_index(req.document_id, req.chunk_index)
    result = await summary_svc.get_or_create_summary(chunk)
    return result


@router.post("/questions", summary="Run question generation for a specific chunk")
async def eval_questions(req: ChunkEvalRequest, db: AsyncSession = Depends(get_db)):
    chunk_svc = ChunkService(db)
    question_svc = QuestionService(db)
    chunk = await chunk_svc.get_chunk_by_index(req.document_id, req.chunk_index)
    return await question_svc.get_or_create_questions(chunk)


@router.post("/retell", summary="Evaluate a retell against a specific chunk")
async def eval_retell(req: RetellEvalRequest, db: AsyncSession = Depends(get_db)):
    chunk_svc = ChunkService(db)
    feedback_svc = FeedbackService(db)
    chunk = await chunk_svc.get_chunk_by_index(req.document_id, req.chunk_index)
    result = await feedback_svc.evaluate_retell(
        chunk_text=chunk.text,
        retrieved_context=[],
        user_retell=req.retell,
    )
    return result
