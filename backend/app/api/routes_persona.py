"""
Routes: /persona
  POST /persona/select      — set persona on a session + generate intro
  POST /persona/intro       — generate intro without persisting (for previewing)
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.persona_service import PersonaService, VALID_PERSONAS

router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────────

class PersonaSelectRequest(BaseModel):
    session_id: str
    persona: str  # "professor" | "peer"


class PersonaSelectResponse(BaseModel):
    session_id: str
    persona: str
    name: str
    intro: str


class PersonaIntroRequest(BaseModel):
    persona: str  # "professor" | "peer"


class PersonaIntroResponse(BaseModel):
    persona: str
    name: str
    intro: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/select",
    response_model=PersonaSelectResponse,
    summary="Select a persona for the session and receive a self-introduction",
)
async def select_persona(
    payload: PersonaSelectRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Persist the chosen persona (professor | peer) on the reading session,
    then return a generated self-introduction in that persona's voice.
    """
    if payload.persona not in VALID_PERSONAS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid persona '{payload.persona}'. Must be one of: {sorted(VALID_PERSONAS)}",
        )
    svc = PersonaService(db)
    try:
        await svc.set_persona(payload.session_id, payload.persona)
        intro, name = await svc.generate_intro(payload.persona)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return PersonaSelectResponse(
        session_id=payload.session_id,
        persona=payload.persona,
        name=name,
        intro=intro,
    )


@router.post(
    "/intro",
    response_model=PersonaIntroResponse,
    summary="Generate a persona self-introduction (preview, no session required)",
)
async def persona_intro(
    payload: PersonaIntroRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a persona self-introduction without attaching it to any session.
    Useful for the frontend to show a preview on the selection screen.
    """
    if payload.persona not in VALID_PERSONAS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid persona '{payload.persona}'. Must be one of: {sorted(VALID_PERSONAS)}",
        )
    svc = PersonaService(db)
    intro, name = await svc.generate_intro(payload.persona)
    return PersonaIntroResponse(persona=payload.persona, name=name, intro=intro)
