# ADHD Reading Companion Backend

This README is aligned with the current backend codebase only (FastAPI service in `backend/app`).

## What This Backend Provides

1. PDF upload, parsing, chunking, and indexing
2. Three reading modes:
   - `skim`
   - `goal_directed`
   - `deep_comprehension`
3. A standalone `learning test` feature
4. Long-term user memory/profile storage

## Tech Snapshot

- Framework: FastAPI (async)
- ORM: SQLAlchemy async
- Default local DB: SQLite (`reading_companion.db`)
- Docker stack: PostgreSQL + Redis + FastAPI
- Vector store: Chroma (default)
- LLM outputs are parsed + schema-validated

Main app entry: `app/main.py`

- `/documents` routes: upload and document status
- `/sessions` routes: reading sessions and mode interactions
- `/users` routes: user memory
- `/learning-test` routes: MCQ generation and scoring
- `/eval` routes: dev/testing endpoints

## Reading Modes

Mode enum is defined in `app/schemas/mode.py`:

- `skim`
- `goal_directed`
- `deep_comprehension`

All sessions start with setup and mode recommendation:

1. `POST /sessions` creates a new session (`status=setup`)
2. `GET /sessions/setup-questions` returns the 3 setup questions
3. `POST /sessions/{session_id}/setup` submits answers and gets recommended mode
4. Optional override: `POST /sessions/{session_id}/mode-override`

You can always check current state with:

- `GET /sessions/{session_id}/current`
- `GET /sessions/{session_id}/progress`

### 1) Skim Mode (`skim`)

Purpose: Quickly understand what the paper is about.

Strategy profile (from code):

- `allow_jump=True`
- `retell_required=False`
- `question_mode=self_assess`
- `gating_mode=none`
- `session_checkpoint=takeaway`

Detailed flow:

1. **Enter mode**
   - After setup/override, session mode becomes `skim`.
2. **Get paper-level overview**
   - `GET /sessions/{session_id}/full-summary`
   - Returns whole-paper summary fields (topic/question/method/findings).
3. **Read current chunk packet**
   - `GET /sessions/{session_id}/current`
   - Returns current chunk + helper content.
4. **Self-check comprehension**
   - `POST /sessions/{session_id}/self-assess` with `understood=true|false`
   - If `false`, user can ask a targeted question.
5. **Ask question when confused**
   - `POST /sessions/{session_id}/ask-question`
   - Backend answers based on current chunk text.
6. **Move forward**
   - `POST /sessions/{session_id}/next`
7. **Optional navigation jumps**
   - `POST /sessions/{session_id}/jump`
   - `POST /sessions/{session_id}/jump-back`
8. **Finish session**
   - `POST /sessions/{session_id}/takeaway`
   - Returns encouraging feedback (no hard scoring gate).

### 2) Goal-Directed Mode (`goal_directed`)

Purpose: Find goal-relevant information as efficiently as possible.

Strategy profile (from code):

- `allow_jump=True`
- `retell_required=False`
- `question_mode=goal_helpfulness`
- `gating_mode=none`
- `session_checkpoint=goal_answer`

Detailed flow:

1. **Enter mode**
   - Session mode becomes `goal_directed`.
2. **Set explicit goal**
   - `POST /sessions/{session_id}/goal` with free-text goal
   - Backend ranks chunks by relevance and sets reading order.
3. **Read goal-ranked chunks**
   - `GET /sessions/{session_id}/current`
4. **Chunk-level usefulness check**
   - `POST /sessions/{session_id}/goal-check` with `helpful=true|false`
   - Used to track whether this chunk contributed to the goal.
5. **Advance through ranked order**
   - `POST /sessions/{session_id}/next`
6. **Optional navigation jumps**
   - `POST /sessions/{session_id}/jump`
   - `POST /sessions/{session_id}/jump-back`
7. **Goal checkpoint at session end**
   - `POST /sessions/{session_id}/takeaway`
   - In this mode, takeaway is treated as goal-answer feedback input.
   - Response includes supportive feedback and may include strengths/limitations.

### 3) Deep Comprehension Mode (`deep_comprehension`)

Purpose: Maximize understanding and retention with active recall.

Strategy profile (from code):

- `allow_jump=False` (free jump disabled; controlled section-level behavior)
- `retell_required=True`
- `question_mode=quiz`
- `gating_mode=weak`
- `chunk_checkpoint=True`
- `section_checkpoint=True`
- `session_checkpoint=takeaway`

Detailed flow:

1. **Enter mode**
   - Session mode becomes `deep_comprehension`.
2. **Read chunk in sequence**
   - `GET /sessions/{session_id}/current`
3. **Retell checkpoint**
   - `POST /sessions/{session_id}/retell` with free-text retell
   - Empty text is accepted (skip behavior exists in schema/service logic).
4. **Quiz generation**
   - `GET /sessions/{session_id}/quiz`
   - Question type is randomized by backend (`true_false`, `multiple_choice`, `fill_blank`).
5. **Submit quiz answers**
   - `POST /sessions/{session_id}/quiz-answer`
   - Returns correctness per question + explanation and wrong-answer options.
6. **If answer is wrong, choose action**
   - `POST /sessions/{session_id}/quiz-action` with:
     - `retry`
     - `mark_for_later`
     - `skip`
7. **Advance**
   - `POST /sessions/{session_id}/next`
8. **Repeat for remaining chunks/sections**
9. **Finish session**
   - `POST /sessions/{session_id}/takeaway`
   - Returns supportive end feedback.

## Learning Test Feature

Route file: `app/api/routes_learning_test.py`  
Service file: `app/services/learning_test_service.py`

`learning test` is independent from the per-session mode loop.

### Behavior

- Generates exactly 9 MCQs from a document
- Difficulty split is fixed:
  - 3 `easy`
  - 3 `medium`
  - 3 `hard`
- Each question has exactly 4 options and one correct answer (`A/B/C/D`)
- On submission, backend returns:
  - total score
  - max score
  - per-question correctness
  - per-question explanation
  - overall feedback
- Score is persisted into user profile (`common_mistakes.test_scores`)

### API

1. Generate test

- `POST /learning-test/generate`

Example request:

```json
{
  "document_id": "<document_uuid>",
  "user_id": "1"
}
```

2. Submit answers and get score

- `POST /learning-test/submit`

Example request:

```json
{
  "document_id": "<document_uuid>",
  "user_id": "1",
  "questions": [
    {
      "id": "q1",
      "question": "...",
      "difficulty": "easy",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "correct_answer": "A"
    }
  ],
  "answers": [
    {
      "question_id": "q1",
      "selected": "B"
    }
  ]
}
```

## Core Backend Endpoints

### Documents

- `POST /documents/upload`
- `GET /documents/{document_id}`
- `GET /documents/{document_id}/pdf`

### Session Setup + Navigation

- `POST /sessions`
- `GET /sessions/setup-questions`
- `POST /sessions/{session_id}/setup`
- `POST /sessions/{session_id}/mode-override`
- `GET /sessions/{session_id}/mind-map`
- `GET /sessions/{session_id}/current`
- `POST /sessions/{session_id}/next`
- `POST /sessions/{session_id}/jump`
- `POST /sessions/{session_id}/jump-back`
- `POST /sessions/{session_id}/skip`
- `GET /sessions/{session_id}/progress`
- `GET /sessions/{session_id}/history`

### Mode-Specific Interactions

- `GET /sessions/{session_id}/full-summary`
- `POST /sessions/{session_id}/self-assess`
- `POST /sessions/{session_id}/ask-question`
- `POST /sessions/{session_id}/goal`
- `POST /sessions/{session_id}/goal-check`
- `POST /sessions/{session_id}/retell`
- `GET /sessions/{session_id}/quiz`
- `POST /sessions/{session_id}/quiz-answer`
- `POST /sessions/{session_id}/quiz-action`
- `POST /sessions/{session_id}/takeaway`

### Learning Test + User Memory

- `POST /learning-test/generate`
- `POST /learning-test/submit`
- `GET /users/{user_id}/memory`

### Infra

- `GET /health`

## Run Backend Locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API base: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`

## Run with Docker

```bash
cd backend
docker compose up --build
```

Ports:

- backend: `8000`
- postgres: `5432`
- redis: `6379`

## Tests

```bash
cd backend
pytest tests -v
```
