# ADHD Reading Companion

> A research system studying the effect of different LLM-side personas on reading comprehension for users with ADHD. The user uploads a PDF, selects a persona (Professor or ADHD Peer), reads the full document with inline AI explanation support, then takes a persona-toned comprehension quiz.

---

## Table of Contents

- [Research Focus](#research-focus)
- [User Flow — 5 Stages](#user-flow--5-stages)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [Course Requirement Mapping](#course-requirement-mapping)
- [Running Tests](#running-tests)
- [License](#license)

---

## Research Focus

This project investigates how the **tone and personality of an LLM persona** affects ADHD users' reading comprehension and engagement. Two personas are compared:

| Persona | Description |
|---|---|
| **Professor** | Formal academic tone; explains concepts with precision and authority |
| **ADHD Peer** | Casual, empathetic tone; speaks as a same-age person who also has ADHD |

Each session is logged with the user's name, chosen persona, per-question outcomes, and overall accuracy, enabling downstream analysis of persona effects.

---

## User Flow — 5 Stages

### Stage 1 — Upload Material
The user uploads a PDF.

**Backend processing:**
- Extract full document text
- Chunk internally for RAG indexing
- Build ChromaDB vector index
- Store `document_id` for the session

**Frontend display:**
- Upload success confirmation
- Document title
- "Next" button

---

### Stage 2 — Enter Username
The user enters a name used to identify this session.

- `name` is a human-readable identifier
- A unique `session_id` / `run_id` is also generated so the same user can have multiple independent sessions

---

### Stage 3 — Choose Persona
Two card buttons are presented:

- **Professor**
- **ADHD Peer**

The user selects one and continues.

---

### Stage 4 — Persona Introduction + Reading
After persona selection, the chosen persona delivers a **detailed self-introduction** in character (Professor tone vs. peer tone), then the full document is displayed.

**Page layout (two-column):**

| Left column | Right column |
|---|---|
| Persona self-introduction | Chatbot panel |
| Current persona label | Prompt: "Highlight a sentence for an explanation" |
| Full article text | Explanation of the highlighted selection |

**Reading page logic:**
- Full document text is shown without chunk boundaries
- When the user highlights any text, the selection is sent to a **plain LLM call** (no persona) which returns an inline explanation
- The user reads at their own pace and clicks "Next" to proceed to the quiz

---

### Stage 5 — Comprehension Quiz
Nine MCQs are generated from the document via RAG, divided by difficulty:

- Easy × 3
- Medium × 3
- Hard × 3

Questions are phrased in the **tone of the chosen persona** (formal/academic for Professor, casual/supportive for ADHD Peer).

**Rules:**
- The chatbot is **disabled** during the quiz
- The user may return to the reading page at any time
- Previously selected answers are **preserved** when returning to the quiz
- The quiz can be completed in multiple visits

**Results display:**
- Incorrect answers highlighted in **red**
- Correct answers highlighted in **green**
- Total score and accuracy rate shown

**Session log saved per run:**

| Field | Description |
|---|---|
| `name` | User-provided name |
| `persona` | Selected persona (`professor` / `adhd_peer`) |
| `answers` | Per-question correct/incorrect outcome |
| `accuracy` | Overall correct rate |

---

## Features

### Persona System
- Two distinct LLM personas with different system prompts
- Persona self-introduction generated at session start
- Quiz questions rephrased to match persona tone
- Plain (persona-less) chatbot for inline reading explanations

### RAG — Document-Grounded Retrieval
- One ChromaDB collection per document
- Vector index built on upload; used at quiz generation time to produce grounded MCQs
- Cosine-similarity retrieval ensures questions are anchored to document content

### Inline Explanation Chatbot
- Active only during the reading stage
- Triggered by text highlight; sends `{highlighted_text, document_context}` to a standard LLM call
- Returns a plain-language explanation with no persona influence

### Learning Test
- 9 MCQs (3 easy / 3 medium / 3 hard) generated per session
- Persona-toned question phrasing
- Answer state persisted client-side across reading-page round trips
- Colour-coded results on submission

### Session Logging
- One log record per user run
- Captures: `name`, `persona`, per-question outcomes, accuracy rate

---

## Architecture

```
Upload
  └── DocumentService     ── PDF parsing, chunking, ChromaDB indexing

Session Init
  └── SessionService      ── Create session (user name + session_id + document_id + persona)

Persona Intro
  └── PersonaService      ── Generate in-character self-introduction via LLM

Reading Stage
  ├── DocumentService     ── Serve full document text
  └── ExplainService      ── Plain LLM call: highlight → explanation

Quiz Stage
  ├── QuestionService     ── RAG-grounded MCQ generation (persona-toned)
  ├── ScoringService      ── Score submission, record outcomes
  └── LogService          ── Persist session log (name, persona, answers, accuracy)
```

---

## Tech Stack

### Backend

| Layer | Technology |
|---|---|
| API framework | FastAPI (async, Python 3.11+) |
| ORM | SQLAlchemy async + aiosqlite (dev) / asyncpg + PostgreSQL (prod) |
| Vector store | ChromaDB (local ONNX embeddings, no API key needed) |
| LLM | School LLM Proxy (OpenAI-compatible, defaults to `gpt-4o-mini`) |
| PDF parsing | pdfplumber |
| Schema validation | Pydantic v2 |
| Containerization | Docker Compose |
| Testing | pytest + pytest-asyncio + httpx |

### Frontend

| Layer | Technology |
|---|---|
| Framework | React 19 + TypeScript |
| Build tool | Vite |
| Styling | Tailwind CSS v4 |
| Components | shadcn/ui |
| Routing | React Router v7 |
| Notifications | Sonner |

---

## Project Structure

```
.
├── backend/                        # FastAPI backend
│   ├── app/
│   │   ├── api/                    # Route handlers (upload, session, persona, explain, quiz, log)
│   │   ├── core/                   # Config, exceptions, logging
│   │   ├── db/                     # SQLAlchemy models & async session
│   │   ├── llm/                    # LLM client, embeddings, response parser
│   │   ├── schemas/                # Pydantic request/response schemas
│   │   ├── services/               # Business logic (DocumentService, PersonaService, …)
│   │   └── utils/                  # PDF parser, text chunker, cleaner
│   ├── tests/                      # pytest test suite
│   ├── docker-compose.yml          # Backend + PostgreSQL stack
│   └── requirements.txt
│
└── frontend/                       # React + Vite frontend
    ├── src/
    │   ├── pages/                  # UploadPage, UsernamePage, PersonaPage, ReadPage, QuizPage
    │   ├── components/             # Shared UI components (ChatBot, PersonaCard, QuizQuestion, …)
    │   └── lib/                    # API helpers, state utilities
    └── package.json
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ and npm
- (Optional) Docker & Docker Compose for the full production stack

### 1. Backend — Local Development

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env from example and fill in your API key
cp .env.example .env

# Start the API server (SQLite is used by default — no DB setup needed)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs available at **http://localhost:8000/docs**

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

App runs at **http://localhost:5173**

### 3. Full Stack with Docker

```bash
cd backend
cp .env.example .env   # set OPENAI_API_KEY and other vars
docker compose up --build
```

| Service | URL |
|---|---|
| Backend API | http://localhost:8000 |
| Interactive API docs | http://localhost:8000/docs |

---

## Environment Variables

Create `backend/.env` (copy from `.env.example`):

```ini
# LLM proxy
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4o-mini

# Database (default: local SQLite — no setup needed for dev)
DATABASE_URL=sqlite+aiosqlite:///./reading_companion.db

# Vector store
CHROMA_PERSIST_DIR=chroma_db

# Upload limits
MAX_FILE_SIZE_MB=20
```

---

## API Reference

### Documents

| Method | Path | Description |
|---|---|---|
| `POST` | `/documents/upload` | Upload PDF, extract text, build vector index |
| `GET` | `/documents/{id}` | Document metadata and full text |

### Sessions

| Method | Path | Description |
|---|---|---|
| `POST` | `/sessions` | Create session (name + document_id + persona) |
| `GET` | `/sessions/{id}` | Session state |

### Persona

| Method | Path | Description |
|---|---|---|
| `GET` | `/persona/{session_id}/intro` | Generate persona self-introduction |

### Explain (Reading Stage)

| Method | Path | Description |
|---|---|---|
| `POST` | `/explain` | Send highlighted text → get plain LLM explanation |

### Quiz

| Method | Path | Description |
|---|---|---|
| `POST` | `/learning-test/generate` | Generate 9 persona-toned MCQs from document |
| `POST` | `/learning-test/submit` | Submit answers, receive scored results |

### Logs

| Method | Path | Description |
|---|---|---|
| `POST` | `/logs` | Save session log (name, persona, answers, accuracy) |
| `GET` | `/logs/{name}` | Retrieve all logs for a user |

---

## Course Requirement Mapping

| Requirement | Implementation |
|---|---|
| **Agent** | Persona-driven LLM orchestration; different system prompts produce meaningfully different reading/quiz experiences |
| **RAG** | `RagService` — ChromaDB retrieval grounding all MCQ generation in document content |
| **Guardrails** | Input validation on upload (file type/size); output schema validation on LLM responses |
| **Memory** | Per-session state (name, persona, document); session log persisted per run for research analysis |

---

## Running Tests

```bash
cd backend
pytest tests/ -v
```

---

## License

MIT
