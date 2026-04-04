import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/TextLayer.css'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import {
  api,
  type ChunkPacket,
  type MindMapResponse,
  type MindMapSection,
  type QuickCheckResult,
  type RetellResult,
} from '@/lib/api'

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

function PdfViewer({ documentId }: { documentId: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState<number>(0)
  const [numPages, setNumPages] = useState<number>(0)

  useEffect(() => {
    if (!containerRef.current) return
    const observer = new ResizeObserver(([entry]) => {
      setContainerWidth(entry.contentRect.width)
    })
    observer.observe(containerRef.current)
    return () => observer.disconnect()
  }, [])

  return (
    <div ref={containerRef} className="w-full">
      <Document
        file={api.getPdfUrl(documentId)}
        onLoadSuccess={({ numPages }) => setNumPages(numPages)}
        loading={<p className="text-xs text-muted-foreground px-4 py-6">Loading PDF…</p>}
        error={<p className="text-xs text-destructive px-4 py-6">Failed to load PDF.</p>}
      >
        {Array.from({ length: numPages }, (_, i) => (
          <Page key={i + 1} pageNumber={i + 1} width={containerWidth || undefined} className="mb-2" />
        ))}
      </Document>
    </div>
  )
}

type Stage = 'read' | 'retell' | 'quiz'
const STAGE_ORDER: Stage[] = ['read', 'retell', 'quiz']

function Spinner() {
  return (
    <svg className="animate-spin size-4 text-muted-foreground" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  )
}


function HomeIcon() {
  return (
    <svg className="size-6" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.25">
      <path d="M3 9.5L10 3l7 6.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 8v8h4v-4h2v4h4V8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Progress({ current, total, stage }: { current: number; total: number; stage: Stage }) {
  const stageIndex = STAGE_ORDER.indexOf(stage)
  const window = 5
  const half = Math.floor(window / 2)
  const start = Math.max(0, Math.min(current - half, total - window))
  const end = Math.min(total, start + window)
  const visible = Array.from({ length: end - start }, (_, i) => start + i)

  return (
    <div className="flex flex-col items-center gap-1 w-[60%]">
      <div className="flex items-center justify-center gap-2 w-full">
        {start > 0 && <span className="text-xs text-muted-foreground/40">…</span>}
        {visible.map((chunkIdx) => (
          <div key={chunkIdx} className="flex items-center gap-0.5 shrink-0">
            {STAGE_ORDER.map((_, stepIdx) => {
              const isCurrentChunk = chunkIdx === current
              const isPastChunk = chunkIdx < current
              const filled = isPastChunk || (isCurrentChunk && stepIdx <= stageIndex)
              const isActive = isCurrentChunk && stepIdx === stageIndex
              return (
                <div
                  key={stepIdx}
                  className={`h-1.5 rounded-full transition-all ${
                    isActive       ? 'w-4 bg-foreground' :
                    filled         ? 'w-2 bg-foreground' :
                    isCurrentChunk ? 'w-2 bg-border' :
                    'w-2 bg-border opacity-40'
                  }`}
                />
              )
            })}
          </div>
        ))}
        {end < total && <span className="text-xs text-muted-foreground/40">…</span>}
      </div>
      <span className="text-xs text-muted-foreground">{current + 1} / {total}</span>
    </div>
  )
}

function MindMapPanel({
  mindMap,
  activeSectionIndex,
  loading,
  error,
  jumpingSection,
  onJump,
}: {
  mindMap: MindMapResponse | null
  activeSectionIndex: number | null
  loading: boolean
  error: string | null
  jumpingSection: number | null
  onJump: (section: MindMapSection) => Promise<void>
}) {
  return (
    <aside className="w-72 shrink-0 border-r border-border bg-muted/20 overflow-y-auto">
      <div className="px-4 py-5 space-y-4">
        <div className="space-y-1">
          <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">Mind Map</p>
          <p className="text-sm text-foreground">Navigate by section at any point in the reading flow.</p>
        </div>

        {loading && <p className="text-xs text-muted-foreground">Loading section map…</p>}
        {error && <p className="text-xs text-destructive">{error}</p>}
        {!loading && !error && (!mindMap || mindMap.sections.length === 0) && (
          <p className="text-xs text-muted-foreground">No section map is available for this document yet.</p>
        )}

        {mindMap?.sections.map((section) => {
          const isActive = section.section_index === activeSectionIndex
          const isJumping = section.section_index === jumpingSection

          return (
            <button
              key={section.section_index}
              onClick={() => void onJump(section)}
              disabled={isJumping}
              className={`w-full rounded-2xl border px-3 py-3 text-left transition-colors ${
                isActive
                  ? 'border-foreground bg-background shadow-sm'
                  : 'border-border bg-background/70 hover:border-foreground/40 hover:bg-background'
              } ${isJumping ? 'opacity-60' : ''}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                    {section.section_type.replaceAll('_', ' ')}
                  </p>
                  <p className="text-sm font-medium text-foreground">{section.title}</p>
                </div>
                <span className="text-[11px] text-muted-foreground">{section.chunk_indices.length} chunks</span>
              </div>

              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{section.summary}</p>

              {section.sub_chunks.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {section.sub_chunks.map((sub) => (
                    <span
                      key={sub.chunk_index}
                      className="rounded-full border border-border px-2 py-1 text-[11px] text-muted-foreground"
                    >
                      {sub.chunk_index + 1}
                    </span>
                  ))}
                </div>
              )}
            </button>
          )
        })}
      </div>
    </aside>
  )
}

export default function ReadPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()

  const [chunk, setChunk] = useState<ChunkPacket | null>(null)
  const [stage, setStage] = useState<Stage>('read')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [mindMap, setMindMap] = useState<MindMapResponse | null>(null)
  const [mindMapLoading, setMindMapLoading] = useState(false)
  const [mindMapError, setMindMapError] = useState<string | null>(null)
  const [jumpingSection, setJumpingSection] = useState<number | null>(null)

  const [retell, setRetell] = useState('')
  const [retellResult, setRetellResult] = useState<RetellResult | null>(null)
  const [retellLoading, setRetellLoading] = useState(false)

  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [quizResult, setQuizResult] = useState<QuickCheckResult | null>(null)
  const [quizLoading, setQuizLoading] = useState(false)
  const [pdfOpen, setPdfOpen] = useState(false)

  useEffect(() => {
    if (!sessionId) return
    void loadChunk()
    void loadMindMap()
  }, [sessionId])

  async function loadChunk() {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getCurrentChunk(sessionId!)
      setChunk(data)
      setStage('read')
      setRetell('')
      setRetellResult(null)
      setAnswers({})
      setQuizResult(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load chunk.')
    } finally {
      setLoading(false)
    }
  }

  async function loadMindMap() {
    setMindMapLoading(true)
    setMindMapError(null)
    try {
      const data = await api.getMindMap(sessionId!)
      setMindMap(data)
    } catch (e) {
      setMindMap(null)
      setMindMapError(e instanceof Error ? e.message : 'Failed to load mind map.')
    } finally {
      setMindMapLoading(false)
    }
  }

  async function handleRetellSubmit() {
    if (retell.trim().length < 50) return
    setRetellLoading(true)
    try {
      const result = await api.submitRetell(sessionId!, retell)
      setRetellResult(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Submission failed.')
    } finally {
      setRetellLoading(false)
    }
  }

  async function handleQuizSubmit() {
    if (!chunk) return
    setQuizLoading(true)
    try {
      const formatted = chunk.quick_check_questions.map((q) => ({
        question_id: q.id,
        answer: answers[q.id] ?? '',
      }))
      const result = await api.submitQuickCheck(sessionId!, formatted)
      setQuizResult(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Submission failed.')
    } finally {
      setQuizLoading(false)
    }
  }

  async function handleAdvance() {
    setLoading(true)
    try {
      await api.nextChunk(sessionId!)
      await loadChunk()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not advance.')
      setLoading(false)
    }
  }

  async function handleSkip() {
    setLoading(true)
    try {
      await api.skipChunk(sessionId!)
      await loadChunk()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not skip.')
      setLoading(false)
    }
  }

  async function handleJumpToSection(section: MindMapSection) {
    if (!sessionId) return

    setJumpingSection(section.section_index)
    setError(null)
    try {
      const result = await api.jumpToSection(sessionId, section.section_index)
      if (result.error) {
        throw new Error(result.error)
      }
      await loadChunk()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not jump to section.')
    } finally {
      setJumpingSection(null)
    }
  }

  // ── Loading / error ───────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center gap-3">
        <Spinner />
        <p className="text-xs text-muted-foreground">Generating summary and questions…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center px-4">
        <div className="space-y-4 text-center">
          <p className="text-sm text-destructive">{error}</p>
          <button onClick={() => navigate('/')} className="text-sm text-muted-foreground underline">
            Start over
          </button>
        </div>
      </div>
    )
  }

  if (!chunk) return null

  const { current, total } = chunk.progress
  const activeSectionIndex =
    mindMap?.sections.find((section) => section.chunk_indices.includes(chunk.chunk_index))?.section_index ?? null

  const retellPassed = retellResult?.passed ?? false
  const quizPassed = quizResult?.passed ?? false
  const allAnswersFilled = chunk.quick_check_questions.every(q => (answers[q.id] ?? '').trim().length > 0)
  const onSplitScreen = stage !== 'read'

  const nextDisabled =
    (stage === 'retell' && !retellPassed && (retell.trim().length < 50 || retellLoading)) ||
    (stage === 'retell' && retellResult !== null && !retellPassed) ||
    (stage === 'quiz'   && !quizPassed && (!allAnswersFilled || quizLoading))

  async function handleNavNext() {
    if (stage === 'read')                   { setStage('retell'); return }
    if (stage === 'retell' && retellPassed) { setStage('quiz'); return }
    if (stage === 'retell')                 { await handleRetellSubmit(); return }
    if (stage === 'quiz' && quizPassed)     {
      if (current + 1 < total) await handleAdvance()
      else navigate('/')
      return
    }
    if (stage === 'quiz')                   { await handleQuizSubmit(); return }
  }

  // ── Top bar ───────────────────────────────────────────────────────────────────

  const topBar = (
    <div className="flex items-center px-6 py-3 border-b border-border shrink-0">
      {/* Left side — home + back, space-between */}
      <div className="flex items-center justify-between w-[20%]">
        <button
          onClick={() => navigate('/')}
          className="text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Home"
        >
          <HomeIcon />
        </button>
        {onSplitScreen && (
          <button
            onClick={() => setStage(STAGE_ORDER[STAGE_ORDER.indexOf(stage) - 1])}
            style={{ fontSize: '14px' }}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            ← Back
          </button>
        )}
      </div>

      {/* Center — progress */}
      <div className="flex-1 flex justify-center">
        <Progress current={current} total={total} stage={stage} />
      </div>

      {/* Right side — next + skip, space-between */}
      <div className="flex items-center justify-between w-[20%]">
        <button
          onClick={handleNavNext}
          disabled={nextDisabled}
          style={{ fontSize: '14px' }}
          className="flex items-center gap-1 text-foreground disabled:opacity-30 transition-opacity"
        >
          {(retellLoading || quizLoading) && <Spinner />}
          Next →
        </button>
        {current + 1 < total && (
          <button
            onClick={handleSkip}
            style={{ fontSize: '14px' }}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            Skip
          </button>
        )}
      </div>
    </div>
  )

  // ── Screen 1: Read ────────────────────────────────────────────────────────────

  if (stage === 'read') {
    return (
      <div className="min-h-screen bg-background flex flex-col">
        {topBar}
        <div className="flex flex-1 overflow-hidden">
          <MindMapPanel
            mindMap={mindMap}
            activeSectionIndex={activeSectionIndex}
            loading={mindMapLoading}
            error={mindMapError}
            jumpingSection={jumpingSection}
            onJump={handleJumpToSection}
          />

          <div className="flex-1 overflow-y-auto">
            <div className="max-w-2xl mx-auto w-full px-6 py-12 space-y-8">
              <p className="text-base leading-relaxed text-foreground" style={{ fontFamily: 'Verdana, sans-serif' }}>
                {chunk.text}
              </p>

              {chunk.annotated_summary.length > 0 && (
                <div className="border-t border-border pt-6 space-y-2">
                  <p className="text-xs uppercase tracking-widest text-muted-foreground">Summary</p>
                  <ul className="space-y-1">
                    {chunk.annotated_summary.map((line, i) => (
                      <li key={i} className="text-sm leading-relaxed text-muted-foreground">{line}</li>
                    ))}
                  </ul>
                </div>
              )}

              {chunk.key_terms.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {chunk.key_terms.map((kt) => (
                    <span key={kt.term} title={kt.note} className="text-xs px-2 py-1 rounded border border-border text-muted-foreground cursor-default">
                      {kt.term}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    )
  }

  // ── Screen 2: Split ───────────────────────────────────────────────────────────

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      {topBar}

      <div className="flex flex-1 overflow-hidden">
        <MindMapPanel
          mindMap={mindMap}
          activeSectionIndex={activeSectionIndex}
          loading={mindMapLoading}
          error={mindMapError}
          jumpingSection={jumpingSection}
          onJump={handleJumpToSection}
        />

        {/* 1st column — PDF */}
        {pdfOpen && (
          <div className="w-[40%] border-r border-border overflow-y-auto px-2 py-4">
            <PdfViewer documentId={chunk.document_id} />
          </div>
        )}

        {/* 2nd column — chunk text + position strip */}
        <div className={`${pdfOpen ? 'w-[30%]' : 'w-1/2'} border-r border-border flex overflow-hidden`}>
          {/* Position strip — click to toggle PDF */}
          <button
            onClick={() => setPdfOpen(o => !o)}
            className="w-2 shrink-0 relative bg-muted/30 hover:bg-muted/60 transition-colors"
            title={pdfOpen ? 'Hide PDF' : 'Show PDF'}
          >
            <div
              className="absolute left-0 right-0 bg-foreground/40 rounded-sm"
              style={{
                top: `${(current / total) * 100}%`,
                height: `${(1 / total) * 100}%`,
                minHeight: '4px',
              }}
            />
          </button>

          {/* Text */}
          <div className="flex-1 overflow-y-auto px-8 py-10">
            <p className="text-foreground" style={{ fontFamily: 'Verdana, sans-serif', fontSize: '18px', lineHeight: '27px' }}>
              {chunk.text}
            </p>
          </div>
        </div>

        {/* 3rd column — interaction */}
        <div className={`${pdfOpen ? 'w-[30%]' : 'w-1/2'} overflow-y-auto px-8 py-10`}>

          {/* ── Retell ── */}
          {stage === 'retell' && (
            <div className="space-y-5">
              <div className="space-y-1">
                <p className="text-sm font-medium text-foreground">In your own words</p>
                <p className="text-xs text-muted-foreground">Write what you remember. At least 50 characters.</p>
              </div>

              <textarea
                value={retell}
                onChange={(e) => !retellPassed && setRetell(e.target.value)}
                readOnly={retellPassed}
                placeholder="What was this section about?"
                rows={8}
                className={`w-full bg-transparent border border-border rounded-lg px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground resize-none focus:outline-none transition-colors ${retellPassed ? 'opacity-60 cursor-default' : 'focus:border-foreground'}`}
              />

              {retellResult && (
                <div className="space-y-2 p-4 rounded-lg bg-muted">
                  <p className="text-xs text-muted-foreground">
                    Score: {retellResult.score}/5 — {retellPassed ? 'nice work' : 'try again'}
                  </p>
                  <p className="text-sm text-foreground">{retellResult.feedback_text}</p>
                  {retellResult.missing_points.length > 0 && (
                    <ul className="mt-2 space-y-1">
                      {retellResult.missing_points.map((p, i) => (
                        <li key={i} className="text-xs text-muted-foreground">· {p}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {!retellPassed && (
                <button
                  onClick={handleRetellSubmit}
                  disabled={retell.trim().length < 50 || retellLoading}
                  className="flex items-center gap-2 text-sm font-medium text-foreground underline underline-offset-4 disabled:opacity-30 disabled:no-underline"
                >
                  {retellLoading && <Spinner />}
                  {retellLoading ? 'Evaluating…' : 'Submit →'}
                </button>
              )}
            </div>
          )}

          {/* ── Quiz ── */}
          {stage === 'quiz' && (
            <div className="space-y-8">
              <div className="space-y-1">
                <p className="text-sm font-medium text-foreground">Quick check</p>
                <p className="text-xs text-muted-foreground">
                  {quizPassed ? 'Well done.' : 'Answer to unlock the next section.'}
                </p>
              </div>

              <div className="space-y-6">
                {chunk.quick_check_questions.map((q, i) => {
                  const res = quizResult?.results.find(r => r.question_id === q.id)
                  return (
                    <div key={q.id} className="space-y-2">
                      <p className="text-sm text-foreground">{i + 1}. {q.question}</p>
                      <textarea
                        value={answers[q.id] ?? ''}
                        onChange={(e) => !quizPassed && setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
                        readOnly={quizPassed}
                        rows={3}
                        className={`w-full bg-transparent border border-border rounded-lg px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground resize-none focus:outline-none transition-colors ${quizPassed ? 'opacity-60 cursor-default' : 'focus:border-foreground'}`}
                        placeholder="Your answer…"
                      />
                      {res && (
                        <div className="p-3 rounded-lg bg-muted space-y-1">
                          <p className="text-xs text-muted-foreground">{res.correct ? '✓ correct' : '✗ incorrect'}</p>
                          <p className="text-sm text-foreground">{res.explanation}</p>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>

              {quizResult && (
                <p className="text-xs text-muted-foreground">{quizResult.feedback_text}</p>
              )}

              {!quizPassed && (
                <button
                  onClick={handleQuizSubmit}
                  disabled={!allAnswersFilled || quizLoading}
                  className="flex items-center gap-2 text-sm font-medium text-foreground underline underline-offset-4 disabled:opacity-30 disabled:no-underline"
                >
                  {quizLoading && <Spinner />}
                  {quizLoading ? 'Checking…' : quizResult ? 'Try again →' : 'Submit →'}
                </button>
              )}
            </div>
          )}

        </div>


      </div>
    </div>
  )
}
