# ADHD Reading Companion — Backend

FastAPI + SQLAlchemy (async) + ChromaDB backend for an AI-powered reading companion designed for users with ADHD.

## Entry Point

```
backend/app/main.py
```

Start the server (run from the `backend/` directory):

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Once running:
- Interactive API docs (Swagger): http://localhost:8000/docs
- Health check: http://localhost:8000/health

---

## Setup

```bash
# 1. Create and activate a virtual environment from the project root
python -m venv .venv
source .venv/bin/activate      # macOS / Linux

# 2. Install dependencies
cd backend
pip install -r requirements.txt
```

Key configuration options (defaults in `backend/app/core/config.py`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./reading_companion.db` | SQLite (dev) or PostgreSQL (prod) |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | ChromaDB vector store directory |
| `UPLOAD_DIR` | `uploads` | PDF / Markdown upload directory |
| `OPENAI_MODEL` | `gpt-5-mini` | LLM model (called via school LLMProxy) |
| `LLM_TEMPERATURE` | `0.2` | LLM temperature |

---

## Directory Structure

```
backend/
├── app/
│   ├── main.py                      ← Entry point; registers all routers
│   ├── api/
│   │   ├── routes_upload.py         POST /documents/upload
│   │   ├── routes_session.py        POST /sessions
│   │   ├── routes_persona.py        POST /persona/select
│   │   ├── routes_explain.py        POST /explain/selection
│   │   ├── routes_learning_test.py  POST /learning-test/*
│   │   └── routes_adhd.py           GET  /adhd/chunks/{id}
│   │                                POST /adhd/annotate     ← ADHD (new)
│   ├── services/
│   │   ├── document_service.py
│   │   ├── section_chunking_service.py
│   │   ├── chunk_service.py
│   │   ├── rag_service.py
│   │   ├── explain_service.py
│   │   ├── learning_test_service.py
│   │   ├── persona_service.py
│   │   └── adhd_annotation_service.py  ← ADHD (new)
│   ├── schemas/
│   │   └── adhd.py                  ← ADHD (new)
│   ├── db/models/                   ORM models (Document, Chunk, ReadingSession…)
│   ├── llm/
│   │   ├── client.py                LLMProxy wrapper (chat_completion_json, etc.)
│   │   └── embeddings.py
│   └── guardrails/
│       ├── input_guard.py
│       ├── output_guard.py
│       └── grounding_guard.py
├── requirements.txt
└── README.md
```

---

## Full API Reference

### Core Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/documents/upload` | Upload PDF / Markdown; triggers parsing, chunking, and vectorization |
| `GET` | `/documents/{id}` | Poll document status (uploaded → chunked → indexed) |
| `GET` | `/documents/{id}/full-text` | Get full document text |
| `GET` | `/documents/{id}/pdf` | Download original PDF |
| `POST` | `/sessions` | Create a reading session (binds user_id + document_id) |
| `GET` | `/sessions/{id}` | Get session info |
| `POST` | `/persona/select` | Select a persona (professor / peer) and generate its intro |
| `POST` | `/persona/intro` | Generate persona intro separately |
| `POST` | `/explain/selection` | Explain highlighted text (neutral tone) |
| `POST` | `/learning-test/generate` | Generate 9 MCQ questions |
| `POST` | `/learning-test/answer` | Save a single answer |
| `POST` | `/learning-test/submit` | Submit quiz; returns score and per-question explanations |

### ADHD Progressive Reading (New)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/adhd/chunks/{document_id}` | Return all chunks for a document, each split into a list of paragraphs |
| `POST` | `/adhd/annotate` | Receive currently visible paragraphs; return per-sentence highlight / fade / normal labels |

---

## ADHD Feature Details

### Progressive Reading (frontend-driven, backend provides data)

Documents are paged by existing **chunk boundaries**. `GET /adhd/chunks/{document_id}` splits each chunk's text on `\n\n` into a paragraph list. The frontend displays one paragraph at a time — clicking **Read More** reveals the next paragraph within the current chunk; clicking **Next Page** advances to the next chunk and resets to its first paragraph.

### Sentence Importance Annotation Pipeline (`POST /adhd/annotate`)

```
Frontend sends visible_blocks (list of paragraphs currently on screen)
        |
  Split into a flat sentence list
  (fixed regex, must match frontend split to guarantee positional alignment)
        |
  RAG retrieval: fetch top-3 relevant chunks from ChromaDB as full-document context
  (helps LLM judge each sentence's importance relative to the whole document)
        |
  LLM scoring: assign highlight / fade / normal label to each sentence
        |
  Guardrail enforcement: highlight ≤ 30%, fade ≤ 20%
  (excess sentences demoted to normal from the tail — prevents screen flooding)
        |
  Return annotations list (order matches input sentences 1-to-1)
```

`/adhd/annotate` is called on every **Read More** click, passing all currently visible paragraphs (including the newly revealed one). Importance weights are redistributed across all visible content each time.

### Label Meanings

| Label | Meaning | Suggested rendering |
|-------|---------|---------------------|
| `highlight` | Core argument / key definition / section claim | Yellow background `#FEF08A` |
| `fade` | Minor detail / aside / statistic | Gray text + reduced opacity |
| `normal` | Regular explanatory text | No special style |

---

## Example Requests

### `GET /adhd/chunks/{document_id}`

```bash
curl http://localhost:8000/adhd/chunks/3fa85f64-5717-4562-b3fc-2c963f66afa6
```

```json
{
  "document_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "total_chunks": 8,
  "chunks": [
    {
      "chunk_index": 0,
      "chunk_id": "c1d2e3f4-...",
      "section": "Introduction",
      "paragraphs": [
        "Attention deficit hyperactivity disorder (ADHD) affects roughly 5% of adults worldwide.",
        "Previous research has shown that chunked reading reduces cognitive overload significantly."
      ]
    }
  ]
}
```

### `POST /adhd/annotate`

```bash
curl -X POST http://localhost:8000/adhd/annotate \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "visible_blocks": [
      "Attention deficit hyperactivity disorder (ADHD) affects roughly 5% of adults worldwide.",
      "Previous research has shown that chunked reading reduces cognitive overload significantly."
    ]
  }'
```

```json
{
  "annotations": [
    {
      "text": "Attention deficit hyperactivity disorder (ADHD) affects roughly 5% of adults worldwide.",
      "label": "highlight"
    },
    {
      "text": "Previous research has shown that chunked reading reduces cognitive overload significantly.",
      "label": "normal"
    }
  ]
}
```

---

## New Files (ADHD Feature)

| File | Description |
|------|-------------|
| `app/schemas/adhd.py` | Pydantic schemas: `AnnotationLabel`, `AnnotateRequest/Response`, `ChunksResponse` |
| `app/services/adhd_annotation_service.py` | Annotation service: RAG + LLM + Guardrail pipeline |
| `app/api/routes_adhd.py` | Routes for `/adhd/chunks` and `/adhd/annotate` |
| `app/main.py` | Added `adhd_router` registration (all other code unchanged) |

---

## Database

Defaults to **SQLite** (development/demo); file is created automatically:

```
backend/reading_companion.db
```

To switch to PostgreSQL (Docker):

```bash
docker-compose up -d db
# Set in .env:
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/reading_companion
```

Tables are created automatically on startup (`Base.metadata.create_all`). Use Alembic migrations for production.

---

## Running Tests

```bash
cd backend
pytest tests/ -v
```

---

## Key Dependencies

| Component | Purpose |
|-----------|---------|
| FastAPI | Web framework |
| SQLAlchemy (async) | ORM |
| aiosqlite / asyncpg | Database drivers |
| ChromaDB | Local vector store (RAG) |
| LLMProxy | School-provided LLM proxy |
| pdfplumber | PDF text extraction |
| pydantic-settings | Environment variable management |

