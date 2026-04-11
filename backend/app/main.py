"""
Application entry point — ADHD Reading Companion (research build).

5-stage user flow
─────────────────
Stage 1  Upload Material      POST /documents/upload
Stage 2  Enter Username       POST /sessions
Stage 3  Choose Persona       POST /persona/select
Stage 4  Reading + Chatbot    GET  /documents/{id}/fulltext
                              POST /persona/intro
                              POST /explain/selection
Stage 5  Comprehension Quiz   POST /learning-test/generate
                              POST /learning-test/answer
                              POST /learning-test/submit
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logger import get_logger
from app.core.exceptions import LLMOutputSchemaError, GroundingViolationError
from app.api.routes_upload import router as upload_router
from app.api.routes_session import router as session_router
from app.api.routes_learning_test import router as learning_test_router
from app.api.routes_persona import router as persona_router
from app.api.routes_explain import router as explain_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s …", settings.APP_NAME)
    # Auto-create tables on startup (dev mode).
    # In production, use Alembic migrations instead.
    from app.db.session import engine
    from app.db.base import Base
    # Import all models so Base.metadata knows about them
    import app.db.models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured.")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Research system studying the effect of LLM personas (Professor vs. ADHD Peer) "
        "on reading comprehension for users with ADHD.\n\n"
        "**5-stage flow:** Upload PDF → Enter username → Choose persona → "
        "Read with inline AI explanation → Take persona-toned comprehension quiz.\n\n"
        "Each session is logged with the user's name, chosen persona, per-question outcomes, "
        "and overall accuracy to enable downstream analysis of persona effects."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers (5-stage flow) ────────────────────────────────────────────────────
# Stage 1 — Upload Material
app.include_router(upload_router, prefix="/documents", tags=["documents"])
# Stage 2 — Enter Username / create session
app.include_router(session_router, prefix="/sessions", tags=["sessions"])
# Stage 3 — Choose Persona + Stage 4 intro
app.include_router(persona_router, prefix="/persona", tags=["persona"])
# Stage 4 — Inline explanation chatbot
app.include_router(explain_router, prefix="/explain", tags=["explain"])
# Stage 5 — Comprehension quiz
app.include_router(learning_test_router, prefix="/learning-test", tags=["learning-test"])

# ── Global exception handlers ────────────────────────────────────────────────

@app.exception_handler(LLMOutputSchemaError)
async def llm_schema_error_handler(request: Request, exc: LLMOutputSchemaError):
    logger.error("LLM output schema error: %s", exc.detail)
    return JSONResponse(status_code=502, content={"detail": f"LLM output error: {exc.detail}"})


@app.exception_handler(GroundingViolationError)
async def grounding_error_handler(request: Request, exc: GroundingViolationError):
    logger.warning("Grounding violation: %s", exc.detail)
    return JSONResponse(status_code=502, content={"detail": exc.detail})


@app.get("/health", tags=["infra"])
async def health():
    return {"status": "ok", "service": settings.APP_NAME}
