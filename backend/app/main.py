"""
Application entry point.
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
from app.api.routes_reading import router as reading_router
from app.api.routes_eval import router as eval_router

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
        "Backend for the AI-powered paper reading companion. "
        "Implements Document Processing, RAG, Agent Orchestration, "
        "Guardrails, and User Memory."
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

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(upload_router, prefix="/documents", tags=["documents"])
app.include_router(session_router, prefix="/sessions", tags=["sessions"])
app.include_router(reading_router, prefix="/users", tags=["users"])
app.include_router(eval_router, prefix="/eval", tags=["eval"])

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
