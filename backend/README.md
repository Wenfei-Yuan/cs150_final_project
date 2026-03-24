# ADHD Reading Companion — Backend

> AI-powered academic paper reading companion that guides users through PDFs chunk-by-chunk with forced recall (retell), Socratic quick-check Q&A, grounded AI feedback, and persistent cross-session learning memory.

## Architecture

```
ReadingAgent (orchestrator)
│
├── DocumentService   ─── PDF upload, extraction (pdfplumber), cleaning, paragraph-aware chunking
├── ChunkService      ─── Chunk CRUD, lock enforcement, cached summary/key-term storage
├── RagService        ─── ChromaDB vector retrieval (one collection per doc, cosine similarity)
├── SummaryService    ─── LLM-generated annotated summaries with key terms (DB-cached)
├── QuestionService   ─── LLM-generated Socratic questions, 5 types (in-memory cached)
├── FeedbackService   ─── LLM-as-judge: retell scoring (1–5 rubric) & answer evaluation
├── MemoryService     ─── Short-term session / mid-term interactions / long-term user profile
│
├── InputGuard        ─── PDF validation, retell min-length, copy-paste detection (difflib)
├── OutputGuard       ─── JSON Schema enforcement on every LLM response (jsonschema)
└── GroundingGuard    ─── Second-pass LLM fact-checker (strict/soft/feedback-aware modes)
```

## Module → Course Requirement Mapping

| Requirement | Implementation | Details |
|---|---|---|
| **Agent** | `ReadingAgent` | Orchestrates 7 services — chunk delivery, retell evaluation, quiz grading, chunk unlocking, profile updates |
| **RAG** | `RagService` + `ChromaAdapter` | Document-grounded only. Cosine-similarity retrieval for retell evidence + adjacent-chunk context for summaries |
| **Guardrail** | 3-layer stack | `InputGuard` (pre-LLM), `OutputGuard` (post-LLM schema), `GroundingGuard` (post-LLM fact-check) |
| **Memory** | `MemoryService` | Session state → interaction history → user profile (weak concepts, feedback style). Injected into prompts via `build_prompt_memory()` |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check → `{"status": "ok", "service": "ADHD Reading Companion"}` |
| `POST` | `/documents/upload` | Upload PDF — validate, extract, clean, chunk, vector-index |
| `GET` | `/documents/{id}` | Document status (uploaded → parsed → chunked → indexed) & chunk count |
| `POST` | `/sessions` | Create a reading session for a document |
| `GET` | `/sessions/{id}/current` | Current chunk packet: text + annotated summary + key terms + questions + progress |
| `POST` | `/sessions/{id}/retell` | Submit free-text retell → LLM judge returns score (1–5), pass/fail, covered/missing points, feedback |
| `POST` | `/sessions/{id}/quick-check` | Submit quiz answers → unlocks next chunk on pass (≥50% correct) |
| `POST` | `/sessions/{id}/next` | Advance to next unlocked chunk |
| `GET` | `/sessions/{id}/progress` | Progress: current/unlocked/total chunks, completed interactions |
| `GET` | `/sessions/{id}/history` | Interaction history (last 50 entries) |
| `GET` | `/users/{id}/memory` | User learning profile: weak concepts, common mistakes, feedback style, last document |
| `POST` | `/eval/summary` | Dev/TA: test summary generation for a specific chunk |
| `POST` | `/eval/questions` | Dev/TA: test question generation for a specific chunk |
| `POST` | `/eval/retell` | Dev/TA: test retell evaluation for a specific chunk |

## Key Implementation Details

### ReadingAgent — Orchestrator

The `ReadingAgent` class is the central coordinator. It does not perform LLM calls directly; instead, it delegates to specialized services:

- **`get_chunk_packet(session_id)`** — Fetches chunk text, generates summary (with RAG neighbor context), creates questions, assembles progress info
- **`handle_retell(session_id, user_retell)`** — Input validation (length + copy detection) → RAG evidence retrieval → prompt memory injection → LLM judge evaluation → interaction recording → weak-concept profile update
- **`handle_quick_check(session_id, answers)`** — LLM answer evaluation → interaction recording → **auto-unlock next chunk on pass**
- **`next_chunk(session_id)`** — Advances `current_chunk_index` if next chunk is unlocked
- **`get_progress(session_id)`** — Returns current/unlocked/total chunks + interaction count

### Three-Layer Guardrails

| Guard | When | Behavior |
|---|---|---|
| **InputGuard** | Pre-LLM | Validates PDF extension/size (≤20 MB, ≤100 pages), retell length (≥50 chars), copy-paste ratio (≤70% via `difflib.SequenceMatcher`). Raises typed exceptions → HTTP 413/422 |
| **OutputGuard** | Post-LLM | Validates every LLM JSON response against strict schemas (5 schemas: summary, questions, retell feedback, answer eval, grounding check). Raises `LLMOutputSchemaError` → HTTP 502 |
| **GroundingGuard** | Post-LLM | Second-pass LLM checks all claims against source text. **Strict** for summaries (raises `GroundingViolationError`), **soft** for questions (warn-only), **specialized** for feedback (ignores evaluative language, only flags factual claims) |

### Three-Tier Memory

| Tier | Storage | What's Tracked | How It's Used |
|---|---|---|---|
| Short-term | `ReadingSession` | current_chunk_index, unlocked_chunk_index, status (active/paused/completed) | Session state & gating |
| Mid-term | `Interaction` | type (retell/quick_check), user_input, model_output, score, passed | Recent fail patterns |
| Long-term | `UserProfileMemory` | weak_concepts (JSON, frequency-tracked), common_mistakes, preferred_feedback_style | Injected into prompt: top-3 weak concepts + style |

### RAG — Document-Grounded Retrieval

- **ChromaDB** with persistent storage (`chroma_db/`), one collection per document (`doc_{uuid}`)
- **Embeddings**: ChromaDB's built-in `all-MiniLM-L6-v2` (ONNX runtime, local, no API key)
- **Summary context**: `retrieve_context_for_summary()` — current chunk + adjacent chunks (window=1)
- **Retell evidence**: `retrieve_for_chunk_feedback()` — embed user retell, cosine search top-k=3
- **Adapter pattern**: `ChromaAdapter` wraps ChromaDB; FAISS/pgvector adapters planned

### PDF Processing Pipeline

1. **Extract** — `pdfplumber` page-by-page text extraction
2. **Clean** — `TextCleaner`: strip page numbers, headers/footers (arXiv, proceedings, copyright), re-join hyphenated words, collapse whitespace
3. **Remove references** — Strip everything after References/Bibliography/Works Cited
4. **Section detection** — Heuristic keyword matching (abstract, introduction, methods, results, discussion, conclusion)
5. **Chunk** — `Chunker(max_tokens=400, max_paragraphs=2)`: paragraph-aware, prefers section boundaries, sentence-splits oversized paragraphs

### LLM Integration

- All calls go through school's **LLMProxy** (not direct OpenAI API)
- Model: `gpt-4o-mini`, temperature: `0.2`, max tokens: `1024`
- `chat_completion_json()` — calls LLM → strips markdown code blocks → parses JSON
- Runs sync `proxy.generate()` via `asyncio.to_thread()` for async compatibility

## Database Schema

Five PostgreSQL tables (SQLAlchemy 2.0 async ORM, auto-created on startup):

| Table | Key Columns |
|---|---|
| `documents` | id (UUID), user_id, filename, file_path, raw_text, status, page_count, created_at |
| `chunks` | id (UUID), document_id (FK), chunk_index, text, token_count, section, prev/next_chunk_id, summary_cached, key_terms_cached |
| `reading_sessions` | id (UUID), user_id, document_id (FK), current_chunk_index, unlocked_chunk_index, total_chunks, status, started_at |
| `interactions` | id (UUID), session_id (FK), chunk_id (FK), interaction_type, user_input, model_output (JSON), score, passed |
| `user_profile_memory` | id (UUID), user_id (unique), weak_concepts (JSON), common_mistakes (JSON), preferred_feedback_style |

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (or standalone PostgreSQL 16 + Redis 7)
- LLMProxy API key (school-provided)

### Run with Docker (recommended)

```bash
cd backend

# Configure environment
cp .env.example .env
# Edit .env — set OPENAI_API_KEY (your LLMProxy key)

# Start 3-service stack
docker compose up --build
```

- API: http://localhost:8000
- Interactive Swagger docs: http://localhost:8000/docs

### Run Locally

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — set OPENAI_API_KEY, DATABASE_URL, REDIS_URL

# Start PostgreSQL + Redis separately, then:
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Interactive Demo CLI

```bash
cd backend
python demo_cli.py
```

12-command interactive menu (pure Python stdlib, zero extra dependencies):
1. Health check
2. Upload document
3. Get document info
4. Create session
5. Get current chunk (summary + key terms + questions)
6. Submit retell
7. Submit quick-check (auto-fetches questions, presents interactively)
8. Next chunk
9. Show progress
10. Show history
11. Show user memory
12. Custom request (any method/path)

Base URL configurable via `DEMO_API_BASE` env var (default: `http://localhost:8000`).

### Run Tests

```bash
cd backend
pytest tests/ -v
```

| Test File | Coverage |
|---|---|
| `test_agent.py` | Retell too-short rejection, quick-check chunk unlocking (mocked services) |
| `test_guardrails.py` | 6 tests: retell length/copy, PDF type/size validation |
| `test_upload.py` | Non-PDF rejection, oversized file rejection, happy-path upload (async) |

## Docker Services

| Service | Image | Port | Health Check |
|---|---|---|---|
| **db** | `pgvector/pgvector:pg16` | 5432 | `pg_isready` |
| **redis** | `redis:7-alpine` | 6379 | — |
| **backend** | Python 3.11-slim + poppler-utils | 8000 | `GET /health` |

Volumes: `./uploads` (PDF files), `./chroma_db` (vector store)

## Directory Structure

```
backend/
├── app/
│   ├── main.py                  # FastAPI app: lifespan, CORS, routers, exception handlers
│   ├── agents/
│   │   ├── reading_agent.py     # ReadingAgent orchestrator (5 public methods)
│   │   └── prompts.py           # All LLM prompt templates
│   ├── api/
│   │   ├── routes_upload.py     # /documents/* (upload, status)
│   │   ├── routes_session.py    # /sessions/* (CRUD, retell, quiz, next, progress, history)
│   │   ├── routes_reading.py    # /users/* (memory/profile)
│   │   └── routes_eval.py       # /eval/* (dev/TA testing)
│   ├── core/
│   │   ├── config.py            # pydantic-settings: all env vars with defaults
│   │   ├── exceptions.py        # 10 custom exceptions with HTTP status codes
│   │   └── logger.py            # Structured logging setup
│   ├── db/
│   │   ├── base.py              # SQLAlchemy declarative base
│   │   ├── session.py           # Async session factory
│   │   └── models/              # 5 models: Document, Chunk, ReadingSession, Interaction, UserProfileMemory
│   ├── guardrails/
│   │   ├── input_guard.py       # PDF + retell validation
│   │   ├── output_guard.py      # JSON schema enforcement
│   │   └── grounding_guard.py   # LLM fact-checking (3 specialized modes)
│   ├── llm/
│   │   ├── client.py            # LLMProxy wrapper (async via to_thread)
│   │   ├── embeddings.py        # ChromaDB local embedder (all-MiniLM-L6-v2)
│   │   └── parser.py            # JSON parse + jsonschema validate
│   ├── schemas/
│   │   ├── llm.py               # 5 JSON schemas for LLM output validation
│   │   ├── reading.py           # Pydantic models for session/reading responses
│   │   └── upload.py            # Pydantic models for upload responses
│   ├── services/
│   │   ├── document_service.py  # Upload → extract → clean → chunk → index pipeline
│   │   ├── chunk_service.py     # Chunk CRUD + lock enforcement
│   │   ├── rag_service.py       # ChromaAdapter + vector retrieval
│   │   ├── summary_service.py   # LLM summary generation (DB-cached, grounding-checked)
│   │   ├── question_service.py  # LLM question generation (in-memory cached, soft grounding)
│   │   ├── feedback_service.py  # LLM retell/answer evaluation
│   │   └── memory_service.py    # Session + interaction + profile management
│   └── utils/
│       ├── pdf_parser.py        # pdfplumber extraction + section detection
│       ├── text_cleaner.py      # Header/footer stripping, reference removal
│       └── chunker.py           # Paragraph-aware chunking (400 tokens, 2 paragraphs max)
├── tests/
│   ├── conftest.py              # AsyncClient fixture with ASGITransport
│   ├── test_agent.py            # Agent integration tests (mocked services)
│   ├── test_guardrails.py       # InputGuard unit tests (6 cases)
│   └── test_upload.py           # Upload endpoint tests (async)
├── llmproxy/                    # School-provided LLM proxy package
├── uploads/                     # Uploaded PDF storage
├── chroma_db/                   # ChromaDB persistent vector store
├── docker-compose.yml           # 3-service stack definition
├── Dockerfile                   # Python 3.11-slim + poppler-utils
├── demo_cli.py                  # Interactive 12-command CLI demo
├── create_tables.py             # Standalone table creation script
├── make_test_pdf.py             # Test PDF generator
└── requirements.txt             # Python dependencies
```

## License

MIT
