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

export type KeyTerm = { term: string; note: string }
export type Question = { id: string; question: string; question_type: string }
export type ProgressInfo = { current: number; total: number; unlocked_until: number }

export type ChunkPacket = {
  session_id: string
  document_id: string
  chunk_index: number
  text: string
  annotated_summary: string[]
  key_terms: KeyTerm[]
  quick_check_questions: Question[]
  progress: ProgressInfo
  can_continue: boolean
  mode?: string
  retell_required?: boolean
}

export type MindMapSubChunk = {
  chunk_index: number
  brief_summary: string
}

export type MindMapSection = {
  section_index: number
  section_type: string
  title: string
  summary: string
  chunk_indices: number[]
  sub_chunks: MindMapSubChunk[]
}

export type MindMapResponse = {
  document_id: string
  sections: MindMapSection[]
}

export type RetellResult = {
  score: number
  passed: boolean
  covered_points: string[]
  missing_points: string[]
  misconceptions: string[]
  feedback_text: string
}

export type QuickCheckResult = {
  passed: boolean
  score: number
  results: { question_id: string; correct: boolean; explanation: string }[]
  feedback_text: string
}

export const api = {
  uploadDocument: (file: File, userId = '1') => {
    const form = new FormData()
    form.append('file', file)
    return request<{ document_id: string; filename: string; status: string; chunk_count: number }>(
      'POST', `/documents/upload?user_id=${userId}`, form, true
    )
  },
  createSession: (documentId: string, userId = '1') =>
    request<{ session_id: string; document_id: string; total_chunks: number; current_chunk_index: number }>(
      'POST', '/sessions', { document_id: documentId, user_id: userId }
    ),
  getMindMap: (sessionId: string) =>
    request<MindMapResponse>('GET', `/sessions/${sessionId}/mind-map`),
  getCurrentChunk: (sessionId: string) =>
    request<ChunkPacket>('GET', `/sessions/${sessionId}/current`),
  jumpToSection: (sessionId: string, sectionIndex: number) =>
    request<{ session_id?: string; jumped_to_chunk?: number; section_index?: number; error?: string }>(
      'POST', `/sessions/${sessionId}/jump`, { section_index: sectionIndex }
    ),
  submitRetell: (sessionId: string, text: string) =>
    request<RetellResult>('POST', `/sessions/${sessionId}/retell`, { text }),
  submitQuickCheck: (sessionId: string, answers: { question_id: string; answer: string }[]) =>
    request<QuickCheckResult>('POST', `/sessions/${sessionId}/quick-check`, { answers }),
  nextChunk: (sessionId: string) =>
    request<{ current_chunk_index: number; total_chunks: number }>(
      'POST', `/sessions/${sessionId}/next`
    ),
  skipChunk: (sessionId: string) =>
    request<{ current_chunk_index: number; total_chunks: number }>(
      'POST', `/sessions/${sessionId}/skip`
    ),
  getPdfUrl: (documentId: string) => `${BASE_URL}/documents/${documentId}/pdf`,
}
