const BASE_URL = 'http://localhost:8000'

async function request<T>(method: string, path: string, body?: unknown, isFormData = false): Promise<T> {
  const headers: HeadersInit = isFormData ? {} : { 'Content-Type': 'application/json' }
  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: isFormData ? (body as FormData) : body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

// ── Upload ─────────────────────────────────────────────────────────────────────

export type UploadResponse = {
  document_id: string
  filename: string
  status: string
  chunk_count: number
}

export type DocumentStatus = {
  document_id: string
  filename: string
  status: string
  chunk_count: number
  created_at: string
  updated_at: string
}

// ── Session ────────────────────────────────────────────────────────────────────

export type SessionResponse = {
  session_id: string
  document_id: string
  user_id: string
  status: string
  persona: string | null
}

// ── Persona ────────────────────────────────────────────────────────────────────

export type PersonaSelectResponse = {
  session_id: string
  persona: string
  name: string
  intro: string
}

export type PersonaIntroResponse = {
  persona: string
  name: string
  intro: string
}

// ── Explain ────────────────────────────────────────────────────────────────────

export type ExplainResponse = {
  selected_text: string
  explanation: string
}

// ── Learning Test ──────────────────────────────────────────────────────────────

export type TestQuestion = {
  id: string
  question: string
  difficulty: 'easy' | 'medium' | 'hard'
  options: string[]       // e.g. ["A. ...", "B. ...", "C. ...", "D. ..."]
  correct_answer: string  // "A" | "B" | "C" | "D"
}

export type GenerateTestResponse = {
  document_id: string
  questions: TestQuestion[]
}

export type AnswerItem = {
  question_id: string
  selected: string  // "A" | "B" | "C" | "D"
}

export type QuestionResult = {
  question_id: string
  question: string
  difficulty: string
  selected: string
  correct_answer: string
  is_correct: boolean
  explanation: string
}

export type SubmitTestResponse = {
  total_score: number
  max_score: number
  results: QuestionResult[]
  feedback: string
}

// ── API client ─────────────────────────────────────────────────────────────────

export const api = {
  // Stage 1: Upload
  uploadDocument: (file: File, userId = '1') => {
    const form = new FormData()
    form.append('file', file)
    return request<UploadResponse>('POST', `/documents/upload?user_id=${userId}`, form, true)
  },

  getDocument: (documentId: string) =>
    request<DocumentStatus>('GET', `/documents/${documentId}`),

  getFullText: (documentId: string) =>
    request<{ document_id: string; full_text: string }>('GET', `/documents/${documentId}/full-text`),

  getPdfUrl: (documentId: string) => `${BASE_URL}/documents/${documentId}/pdf`,

  // Stage 2: Create session (enter username)
  createSession: (documentId: string, userId = '1') =>
    request<SessionResponse>('POST', '/sessions', { document_id: documentId, user_id: userId }),

  getSession: (sessionId: string) =>
    request<SessionResponse>('GET', `/sessions/${sessionId}`),

  // Stage 3: Persona
  getPersonaIntro: (persona: string) =>
    request<PersonaIntroResponse>('POST', '/persona/intro', { persona }),

  selectPersona: (sessionId: string, persona: string) =>
    request<PersonaSelectResponse>('POST', '/persona/select', { session_id: sessionId, persona }),

  // Stage 4: Explain highlighted text
  explainSelection: (documentId: string, selectedText: string, surroundingText = '') =>
    request<ExplainResponse>('POST', '/explain/selection', {
      document_id: documentId,
      selected_text: selectedText,
      surrounding_text: surroundingText,
    }),

  // Stage 5: Learning test
  generateTest: (documentId: string, userId = '1', persona?: string) =>
    request<GenerateTestResponse>('POST', '/learning-test/generate', {
      document_id: documentId,
      user_id: userId,
      persona,
    }),

  saveAnswer: (sessionId: string, questionId: string, selectedAnswer: string, correctAnswer: string, difficulty: string) =>
    request<{ saved: boolean }>('POST', '/learning-test/answer', {
      session_id: sessionId,
      question_id: questionId,
      selected_answer: selectedAnswer,
      correct_answer: correctAnswer,
      difficulty,
    }),

  submitTest: (payload: {
    sessionId: string
    documentId: string
    userId: string
    userName: string
    persona: string
    questions: TestQuestion[]
    answers: AnswerItem[]
    startedAt?: string
  }) =>
    request<SubmitTestResponse>('POST', '/learning-test/submit', {
      session_id: payload.sessionId,
      document_id: payload.documentId,
      user_id: payload.userId,
      user_name: payload.userName,
      persona: payload.persona,
      questions: payload.questions,
      answers: payload.answers,
      started_at: payload.startedAt,
    }),
}
