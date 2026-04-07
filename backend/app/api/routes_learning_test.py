"""
Routes: /learning-test — generate MCQs from a document, submit answers, get score.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.learning_test_service import LearningTestService
from app.schemas.learning_test import (
    GenerateTestRequest,
    GenerateTestResponse,
    TestQuestion,
    SubmitTestRequest,
    SubmitTestResponse,
    QuestionResult,
)

router = APIRouter()


@router.post("/generate", response_model=GenerateTestResponse, summary="Generate 9 MCQs")
async def generate_test(
    payload: GenerateTestRequest,
    db: AsyncSession = Depends(get_db),
):
    svc = LearningTestService(db)
    questions = await svc.generate_questions(payload.document_id)
    return GenerateTestResponse(
        document_id=payload.document_id,
        questions=[TestQuestion(**q) for q in questions],
    )


@router.post("/submit", response_model=SubmitTestResponse, summary="Submit answers and get score")
async def submit_test(
    payload: SubmitTestRequest,
    db: AsyncSession = Depends(get_db),
):
    svc = LearningTestService(db)

    questions_dicts = [q.model_dump() for q in payload.questions]
    answers_dicts = [a.model_dump() for a in payload.answers]

    results, feedback = await svc.evaluate_answers(questions_dicts, answers_dicts)

    total_score = sum(1 for r in results if r["is_correct"])
    max_score = len(results)

    # Persist score into user profile
    await svc.record_score(payload.user_id, total_score, max_score)

    return SubmitTestResponse(
        total_score=total_score,
        max_score=max_score,
        results=[QuestionResult(**r) for r in results],
        feedback=feedback,
    )
