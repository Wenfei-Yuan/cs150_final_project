# ADHD Reading Companion

> An AI-powered academic paper reading assistant that helps users with ADHD read, comprehend, and retain information from research papers through structured, gated reading flows with active recall techniques.

## Overview

ADHD Reading Companion breaks academic PDFs into manageable chunks and guides users through a structured **Read → Retell → Quiz → Advance** loop:

1. **Read** — View a chunk with an LLM-generated annotated summary and key terms
2. **Retell** — Paraphrase the chunk in your own words; an LLM judge evaluates comprehension
3. **Quick-check Quiz** — Answer 1–3 Socratic-style comprehension questions
4. **Advance** — Unlock the next chunk only after demonstrating understanding

This gated progression prevents skipping ahead — an evidence-based strategy for ADHD reading support.

## Architecture

```
ReadingAgent (orchestrator)
│
├── DocumentService   ─── PDF parsing, chunking, DB persistence
├── ChunkService      ─── Chunk CRUD & lock enforcement
├── RagService        ─── Document-grounded vector retrieval (ChromaDB)
├── SummaryService    ─── LLM-generated annotated summaries (cached)
├── QuestionService   ─── LLM-generated quick-check questions (cached)
├── FeedbackService   ─── LLM-as-judge retell & answer evaluation
├── MemoryService     ─── Short / mid / long-term memory (DB + profile)
│
├── InputGuard        ─── File type, size, retell length, copy detection
├── OutputGuard       ─── JSON Schema validation on every LLM response
└── GroundingGuard    ─── Second-pass grounding verification (no hallucination)
```

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI (async, Python 3.11) |
| Database | PostgreSQL 16 (asyncpg + SQLAlchemy async ORM) |
| Cache / State | Redis 7 |
| Vector Store | ChromaDB (pluggable for FAISS / pgvector) |
| Embeddings | all-MiniLM-L6-v2 (local, no API key needed) |
| LLM | LLMProxy (defaults to gpt-4o-mini) |
| PDF Parsing | pdfplumber |
| Containerization | Docker Compose |
| Testing | pytest + pytest-asyncio + httpx |

## Project Structure

```
├── backend/                    # Core backend API
│   ├── app/
│   │   ├── agents/             # ReadingAgent orchestrator + prompt templates
│   │   ├── api/                # FastAPI route handlers
│   │   ├── core/               # Config, exceptions, logging
│   │   ├── db/                 # Database models & session management
│   │   ├── guardrails/         # Input / Output / Grounding guards
│   │   ├── llm/                # LLM client, embeddings, response parser
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   ├── services/           # Business logic layer
│   │   └── utils/              # PDF parser, text chunker, cleaner
│   ├── tests/                  # pytest test suite
│   ├── docker-compose.yml      # 3-service stack (backend + postgres + redis)
│   ├── demo_cli.py             # Interactive CLI demo
│   └── requirements.txt
│
└── backend-cli-demo/           # Standalone Click-based CLI client
    └── src/
        ├── main.py             # CLI entry point
        ├── client/api.py       # HTTP API client
        └── commands/           # CLI subcommands
```

## Course Requirement Mapping

| Requirement | Implementation |
|---|---|
| **Agent** | `ReadingAgent` orchestrates all tools based on session state |
| **RAG** | `RagService` — document-grounded retrieval only, no external knowledge |
| **Guardrail** | `InputGuard`, `OutputGuard`, `GroundingGuard` — 3 distinct layers |
| **Memory** | `MemoryService` — short-term session, mid-term history, long-term profile |

## Key Features

### Three-Layer Guardrail Stack

- **Input Guard** — Validates PDF uploads (file type, size) and user inputs (retell length, copy detection)
- **Output Guard** — Enforces strict JSON schema validation on every LLM response via `jsonschema`
- **Grounding Guard** — A second-pass LLM judge that checks whether all factual claims are supported by the source text, preventing hallucination

### Three-Tier Memory System

| Tier | Scope | Storage |
|---|---|---|
| Short-term | Current session context | `ReadingSession` table (current/unlocked chunk, status) |
| Mid-term | Per-document interaction history | `Interaction` table (type, input, output, score, pass) |
| Long-term | Cross-document user profile | `UserProfileMemory` table (weak concepts, common mistakes, feedback style) |

User memory is injected into LLM prompts for personalized feedback — weak concepts, feedback preferences, and interaction history inform each response.

### RAG — Document-Grounded Retrieval

- One ChromaDB collection per document (namespace isolation)
- Cosine-similarity search on user retells to find supporting evidence for evaluation
- Adjacent-chunk retrieval for summary context
- Pluggable adapter pattern (ChromaDB / FAISS / pgvector)

## API Endpoints

| Method | Path | Description |
|---|---|---|
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

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- An API key for the LLM proxy

### Run with Docker (recommended)

```bash
cd backend

# Configure environment
cp .env.example .env
# Edit .env — set your API key and other configs

# Start the stack
docker compose up --build
```

- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs

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
# Edit .env — set API key, DATABASE_URL, REDIS_URL

# Start PostgreSQL + Redis separately, then:
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Demo CLI

```bash
cd backend
python demo_cli.py
```

An interactive menu will guide you through the full reading flow: upload → create session → read chunk → retell → quiz → advance.

### Run Tests

```bash
cd backend
pytest tests/ -v
```

## Docker Services

The `docker-compose.yml` defines three services:

| Service | Image | Purpose |
|---|---|---|
| **db** | `pgvector/pgvector:pg16` | PostgreSQL with pgvector extension |
| **redis** | `redis:7-alpine` | Caching and session state |
| **backend** | Custom (Python 3.11-slim) | FastAPI application |

## License

MIT
