# ADHD Reading Companion — Backend

> AI-powered paper reading companion that guides users through academic PDFs chunk-by-chunk, with forced recall (retell), quick-check Q&A, grounded AI feedback, and persistent learning memory.

## Architecture

```
ReadingAgent (orchestrator)
│
├── DocumentService   ─── PDF parsing, chunking, DB persistence
├── ChunkService      ─── Chunk CRUD & lock enforcement
├── RagService        ─── Document-grounded vector retrieval (ChromaDB / FAISS)
├── SummaryService    ─── LLM-generated annotated summaries (cached)
├── QuestionService   ─── LLM-generated quick-check questions (cached)
├── FeedbackService   ─── LLM-as-judge retell & answer evaluation
├── MemoryService     ─── Short / mid / long-term memory (DB + profile)
│
├── InputGuard        ─── File type, size, retell length, copy detection
├── OutputGuard       ─── JSON Schema validation on every LLM response
└── GroundingGuard    ─── Second-pass grounding verification (no hallucination)
```

## Module → Course Requirement Mapping

| Requirement | Implementation |
|-------------|---------------|
| **Agent** | `ReadingAgent` orchestrates all tools based on session state |
| **RAG** | `RagService` — document-grounded retrieval only, no external knowledge |
| **Guardrail** | `InputGuard`, `OutputGuard`, `GroundingGuard` — 3 distinct layers |
| **Memory** | `MemoryService` — short-term session, mid-term history, long-term profile |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/documents/upload` | Upload + process a PDF |
| `GET` | `/documents/{id}` | Document status & chunk count |
| `POST` | `/sessions` | Create a reading session |
| `GET` | `/sessions/{id}/current` | Get current chunk packet |
| `POST` | `/sessions/{id}/retell` | Submit free-text retell |
| `POST` | `/sessions/{id}/quick-check` | Submit Q&A answers |
| `POST` | `/sessions/{id}/next` | Advance to next chunk |
| `GET` | `/sessions/{id}/progress` | Reading progress |
| `GET` | `/sessions/{id}/history` | Interaction history |
| `GET` | `/users/{id}/memory` | User learning profile |
| `POST` | `/eval/summary` | Dev: test summary generation |
| `POST` | `/eval/questions` | Dev: test question generation |
| `POST` | `/eval/retell` | Dev: test retell evaluation |
| `GET` | `/health` | Health check |

## Quick Start

### 1. Prerequisites

- Python 3.11+
- PostgreSQL 16 (or Docker)
- An OpenAI API key

### 2. Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — set OPENAI_API_KEY and DATABASE_URL
```

### 3. Run with Docker (easiest)

```bash
cp .env.example .env        # fill in OPENAI_API_KEY
docker-compose up --build
```

API available at http://localhost:8000  
Interactive docs at http://localhost:8000/docs

### 4. Run locally (without Docker)

```bash
# Start Postgres + Redis separately, then:
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Run tests

```bash
pytest tests/ -v
```

## Implementation Phases

### Phase 1 — Core reading loop ✅
- PDF upload + validation
- Text extraction + cleaning
- Paragraph-aware chunking
- Session creation + lock enforcement
- Retell submission + LLM feedback
- Quick-check Q&A + chunk unlock

### Phase 2 — RAG + Guardrails
- Vector indexing on upload
- Neighbor retrieval for summaries
- Evidence retrieval for retell grading
- JSON Schema output validation
- Grounding verification pass

### Phase 3 — Memory + Eval
- Interaction history recording
- Resume reading (persistent session)
- User learning profile (weak concepts, style)
- Offline eval pipeline (`/eval/*`)

## Directory Structure

```
backend/
├── app/
│   ├── main.py                  # FastAPI app entry point
│   ├── api/                     # Route handlers
│   ├── core/                    # Config, logging, exceptions
│   ├── db/                      # SQLAlchemy models & session
│   ├── schemas/                 # Pydantic request/response + LLM JSON schemas
│   ├── services/                # Business logic services
│   ├── agents/                  # ReadingAgent orchestrator + prompts
│   ├── guardrails/              # Input, output, grounding guards
│   ├── llm/                     # OpenAI client, parser, embeddings
│   └── utils/                   # PDF parser, chunker, text cleaner
├── tests/
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```
