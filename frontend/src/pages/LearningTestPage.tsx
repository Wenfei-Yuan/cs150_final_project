import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { toast } from 'sonner'
import { api, type TestQuestion, type QuestionResult } from '@/lib/api'

const DIFFICULTY_COLORS: Record<string, string> = {
  easy: 'text-emerald-600 bg-emerald-50',
  medium: 'text-amber-600 bg-amber-50',
  hard: 'text-rose-600 bg-rose-50',
}

export default function LearningTestPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state as {
    document_id?: string
    persona?: string
    user_name?: string
  } | null

  const [documentId, setDocumentId] = useState<string | null>(state?.document_id ?? null)
  const [persona, setPersona] = useState<string | null>(state?.persona ?? null)
  const [userName] = useState<string>(state?.user_name ?? '1')

  const [questions, setQuestions] = useState<TestQuestion[]>([])
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [resultMap, setResultMap] = useState<Record<string, QuestionResult> | null>(null)
  const [totalScore, setTotalScore] = useState(0)
  const [maxScore, setMaxScore] = useState(0)
  const [feedback, setFeedback] = useState('')
  const [error, setError] = useState<string | null>(null)

  const startedAt = useRef<string>(new Date().toISOString())
  const submitted = resultMap !== null

  useEffect(() => {
    if ((documentId && persona) || !sessionId) return
    api.getSession(sessionId).then((s) => {
      if (!documentId) setDocumentId(s.document_id)
      if (!persona && s.persona) setPersona(s.persona)
    }).catch(() => setError('Could not load session.'))
  }, [sessionId, documentId, persona])

  useEffect(() => {
    if (!documentId) return
    setLoading(true)
    api.generateTest(documentId, '1', persona ?? undefined)
      .then((res) => { setQuestions(res.questions); startedAt.current = new Date().toISOString() })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to generate quiz.'))
      .finally(() => setLoading(false))
  }, [documentId, persona])

  async function handleSelect(question: TestQuestion, letter: string) {
    if (submitted) return
    setAnswers((prev) => ({ ...prev, [question.id]: letter }))
    if (!sessionId) return
    try {
      await api.saveAnswer(sessionId, question.id, letter, question.correct_answer, question.difficulty)
    } catch { /* non-blocking */ }
  }

  async function handleSubmit() {
    if (!sessionId || !documentId) return
    const unanswered = questions.filter((q) => !answers[q.id])
    if (unanswered.length > 0) {
      toast.error(`Please answer all questions (${unanswered.length} remaining).`)
      return
    }
    setSubmitting(true)
    try {
      const res = await api.submitTest({
        sessionId, documentId, userId: '1', userName,
        persona: persona ?? 'peer', questions,
        answers: questions.map((q) => ({ question_id: q.id, selected: answers[q.id] })),
        startedAt: startedAt.current,
      })
      const map: Record<string, QuestionResult> = {}
      res.results.forEach((r) => { map[r.question_id] = r })
      setResultMap(map)
      setTotalScore(res.total_score)
      setMaxScore(res.max_score)
      setFeedback(res.feedback)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Submission failed.')
    } finally {
      setSubmitting(false)
    }
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-10 bg-background/90 backdrop-blur border-b border-border">
        <div className="max-w-2xl mx-auto px-6 py-3 flex items-center justify-between">
          {/* <div className="flex items-center gap-4"> */}
            <button onClick={() => navigate(-1)} className="text-sm text-muted-foreground hover:text-foreground transition-colors shrink-0">
              ← Back
            </button>
            <p className="text-sm text-muted-foreground">Comprehension quiz</p>
          {/* </div> */}
          {submitted
            ? <p className="text-sm font-medium text-foreground">{totalScore}/{maxScore} correct</p>
            : <p className="text-xs text-muted-foreground">{Object.keys(answers).length}/{questions.length} answered</p>
          }
        </div>
      </header>

      <div className="max-w-2xl mx-auto px-6 py-10 space-y-8">
        {/* Score + feedback banner (shown after submit) */}
        {submitted && (
          <div className="rounded-xl border border-border bg-muted/30 px-5 py-4 space-y-1">
            <p className="text-2xl font-semibold tracking-tight text-foreground">
              {totalScore}/{maxScore} <span className="text-base font-normal text-muted-foreground">— {Math.round((totalScore / maxScore) * 100)}%</span>
            </p>
            {feedback && <p className="text-sm text-muted-foreground leading-relaxed">{feedback}</p>}
          </div>
        )}

        {loading ? (
          <div className="space-y-6">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="space-y-3">
                <div className="h-4 w-3/4 rounded bg-muted animate-pulse" />
                {[...Array(4)].map((_, j) => (
                  <div key={j} className="h-10 rounded-lg bg-muted animate-pulse" />
                ))}
              </div>
            ))}
          </div>
        ) : (
          <>
            {questions.map((q, i) => {
              const chosen = answers[q.id]
              const result = resultMap?.[q.id] ?? null

              return (
                <div key={q.id} className="space-y-3">
                  {/* Question */}
                  <div className="flex items-start gap-2">
                    <span className="text-sm font-medium text-foreground shrink-0">{i + 1}.</span>
                    <div className="flex-1 space-y-1">
                      <p className="text-sm font-medium text-foreground leading-snug">{q.question}</p>
                      <span className={`inline-block text-[10px] font-medium px-1.5 py-0.5 rounded ${DIFFICULTY_COLORS[q.difficulty] ?? 'text-muted-foreground bg-muted'}`}>
                        {q.difficulty}
                      </span>
                    </div>
                  </div>

                  {/* Options */}
                  <div className="space-y-2 pl-5">
                    {q.options.map((opt) => {
                      const letter = opt.charAt(0).toUpperCase()
                      const isChosen = chosen === letter

                      let optClass = 'border-border text-foreground'
                      let tag: string | null = null

                      if (result) {
                        const isCorrectAnswer = letter === result.correct_answer.toUpperCase()
                        const isWrongPick = isChosen && !result.is_correct
                        const isCorrectPick = isChosen && result.is_correct

                        if (isCorrectAnswer && isCorrectPick) {
                          optClass = 'border-emerald-400 bg-emerald-50 text-emerald-800 font-medium ring-2 ring-emerald-300'
                          tag = 'Your answer ✓'
                        } else if (isCorrectAnswer) {
                          optClass = 'border-emerald-400 bg-emerald-50 text-emerald-800 font-medium'
                          tag = 'Correct answer'
                        } else if (isWrongPick) {
                          optClass = 'border-rose-400 bg-rose-50 text-rose-800 ring-2 ring-rose-300'
                          tag = 'Your answer ✗'
                        } else {
                          optClass = 'border-border text-muted-foreground opacity-50'
                        }
                      } else if (isChosen) {
                        optClass = 'border-foreground bg-muted text-foreground font-medium'
                      }

                      return (
                        <button
                          key={opt}
                          onClick={() => handleSelect(q, letter)}
                          disabled={submitted}
                          className={`w-full text-left px-4 py-2.5 rounded-lg border text-sm transition-colors ${optClass} disabled:cursor-default`}
                        >
                          <span className="flex items-center justify-between gap-2">
                            <span>{opt}</span>
                            {tag && (
                              <span className="text-[10px] font-semibold shrink-0 opacity-80">{tag}</span>
                            )}
                          </span>
                        </button>
                      )
                    })}
                  </div>

                  {/* Explanation (shown after submit) */}
                  {result?.explanation && (
                    <p className="pl-5 text-xs text-muted-foreground leading-relaxed">
                      <span className={`font-bold mr-1 ${result.is_correct ? 'text-emerald-700' : 'text-rose-700'}`}>
                        {result.is_correct ? 'Correct.' : 'Incorrect.'}
                      </span>
                      {result.explanation}
                    </p>
                  )}
                </div>
              )
            })}

            {!submitted ? (
              <div className="pt-4 border-t border-border">
                <button
                  onClick={handleSubmit}
                  disabled={submitting || Object.keys(answers).length < questions.length}
                  className="w-full py-3 rounded-lg bg-foreground text-background text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-30"
                >
                  {submitting ? 'Submitting…' : 'Submit answers'}
                </button>
                {Object.keys(answers).length < questions.length && (
                  <p className="text-xs text-muted-foreground text-center mt-2">
                    Answer all {questions.length} questions to submit
                  </p>
                )}
              </div>
            ) : (
              <div className="pt-4 border-t border-border">
                <button
                  onClick={() => navigate('/')}
                  className="w-full py-3 rounded-lg bg-foreground text-background text-sm font-medium hover:opacity-90 transition-opacity"
                >
                  Start over
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
