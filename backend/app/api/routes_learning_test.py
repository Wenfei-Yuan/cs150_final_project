"""
Routes: /learning-test
  POST /learning-test/generate          — generate 9 MCQs (persona-aware)
  POST /learning-test/answer            — save / update a single answer (quiz state)
  GET  /learning-test/state             — retrieve saved answers for a session
  POST /learning-test/submit            — grade answers, write session log, return results
  GET  /learning-test/logs              — return all session logs (for research export)
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models.session_log import SessionLog
from app.services.learning_test_service import LearningTestService
from app.schemas.learning_test import (
    GenerateTestRequest,
    GenerateTestResponse,
    TestQuestion,
    SaveAnswerRequest,
    SaveAnswerResponse,
    QuizStateResponse,
    SubmitTestRequest,
    SubmitTestResponse,
    QuestionResult,
    SessionLogResponse,
)

router = APIRouter()


@router.post("/generate", response_model=GenerateTestResponse, summary="Generate 9 MCQs")
async def generate_test(
    payload: GenerateTestRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate 9 MCQs for the document. If a persona is provided (professor | peer),
    question stems are rewritten to match that persona's voice.
    Correct answers and options are never changed by the rewrite.
    """
    svc = LearningTestService(db)
    questions = await svc.generate_questions(
        document_id=payload.document_id,
        persona=payload.persona,
    )
    return GenerateTestResponse(
        document_id=payload.document_id,
        questions=[TestQuestion(**q) for q in questions],
    )


@router.post("/answer", response_model=SaveAnswerResponse, summary="Save or update a single answer")
async def save_answer(
    payload: SaveAnswerRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Persist (upsert) one MCQ answer for a session.
    Call this whenever the user selects or changes an option.
    This allows test state to survive navigation back to the reading page.
    """
    svc = LearningTestService(db)
    await svc.save_answer(
        session_id=payload.session_id,
        question_id=payload.question_id,
        selected_answer=payload.selected_answer,
        correct_answer=payload.correct_answer,
        difficulty=payload.difficulty,
    )
    return SaveAnswerResponse(saved=True)


@router.get("/state", response_model=QuizStateResponse, summary="Get saved answers for a session")
async def get_quiz_state(
    session_id: str = Query(..., description="Reading session ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the saved answer map {question_id: selected_answer} for a session.
    Use this when the user returns from the reading page back to the quiz.
    """
    svc = LearningTestService(db)
    answers = await svc.get_saved_answers(session_id)
    return QuizStateResponse(session_id=session_id, answers=answers)


@router.post("/submit", response_model=SubmitTestResponse, summary="Submit answers and get score")
async def submit_test(
    payload: SubmitTestRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Grade all answers, generate explanations, write the experiment session log,
    and persist the score in the user profile.
    """
    svc = LearningTestService(db)

    questions_dicts = [q.model_dump() for q in payload.questions]
    answers_dicts = [a.model_dump() for a in payload.answers]

    results, feedback = await svc.evaluate_answers(questions_dicts, answers_dicts)

    total_score = sum(1 for r in results if r["is_correct"])
    max_score = len(results)

    # Write experiment session log
    await svc.write_session_log(
        session_id=payload.session_id,
        user_name=payload.user_name,
        persona=payload.persona,
        document_id=payload.document_id,
        results=results,
        started_at=payload.started_at,
    )

    # Persist score into user profile (legacy)
    await svc.record_score(payload.user_id, total_score, max_score)

    return SubmitTestResponse(
        total_score=total_score,
        max_score=max_score,
        results=[QuestionResult(**r) for r in results],
        feedback=feedback,
    )


@router.get("/logs", response_model=list[SessionLogResponse], summary="Get all session logs")
async def get_session_logs(
    db: AsyncSession = Depends(get_db),
):
    """
    Return all experiment session logs ordered by submission time (newest first).
    Intended for research data export.
    """
    result = await db.execute(
        select(SessionLog).order_by(SessionLog.submitted_at.desc())
    )
    logs = result.scalars().all()
    return [
        SessionLogResponse(
            id=str(log.id),
            session_id=str(log.session_id),
            user_name=log.user_name,
            persona=log.persona,
            document_id=log.document_id,
            question_results=log.question_results,
            total_correct=log.total_correct,
            total_questions=log.total_questions,
            accuracy=log.accuracy,
            started_at=log.started_at,
            submitted_at=log.submitted_at,
        )
        for log in logs
    ]

