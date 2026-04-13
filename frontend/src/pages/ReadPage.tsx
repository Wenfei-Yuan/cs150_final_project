import { useState, useEffect, useRef, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { toast } from 'sonner'
import { api } from '@/lib/api'

type Heading = { id: string; text: string }
type Highlight = { id: string; text: string }

function slugify(text: string) {
  return text.toLowerCase().replace(/[^\w\s-]/g, '').replace(/\s+/g, '-')
}

export default function ReadPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state as { document_id?: string; filename?: string; persona?: string; persona_name?: string; user_name?: string } | null

  const [documentId, setDocumentId] = useState<string | null>(state?.document_id ?? null)
  const [fullText, setFullText] = useState<string | null>(null)
  const [loadingText, setLoadingText] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeHeading, setActiveHeading] = useState<string | null>(null)
  const [highlights, setHighlights] = useState<Highlight[]>([])
  const [highlightsPanelOpen, setHighlightsPanelOpen] = useState(false)
  const [highlightPopover, setHighlightPopover] = useState<{ id: string; x: number; y: number } | null>(null)

  // Explain state
  const [selection, setSelection] = useState<{ text: string; x: number; y: number } | null>(null)
  const [explanation, setExplanation] = useState<string | null>(null)
  const [explaining, setExplaining] = useState(false)
  const [explainPanelOpen, setExplainPanelOpen] = useState(false)
  const articleRef = useRef<HTMLDivElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)

  const isMarkdown = !!state?.filename?.endsWith('.md')

  // Resolve document_id from session if not in route state
  useEffect(() => {
    if (documentId || !sessionId) return
    api.getSession(sessionId)
      .then((s) => setDocumentId(s.document_id))
      .catch(() => setError('Could not load session.'))
  }, [sessionId, documentId])

  // Fetch full text
  useEffect(() => {
    if (!documentId) return
    setLoadingText(true)
    api.getFullText(documentId)
      .then((res) => setFullText(res.full_text))
      .catch(() => setError('Could not load document text.'))
      .finally(() => setLoadingText(false))
  }, [documentId])

  // Extract H2 headings from markdown
  const headings = useMemo<Heading[]>(() => {
    if (!isMarkdown || !fullText) return []
    return fullText
      .split('\n')
      .filter((line) => /^## /.test(line))
      .map((line) => {
        const text = line.replace(/^## /, '').trim()
        return { id: slugify(text), text }
      })
  }, [fullText, isMarkdown])

  // Track active heading while scrolling
  useEffect(() => {
    if (headings.length === 0) return
    function onScroll() {
      for (let i = headings.length - 1; i >= 0; i--) {
        const el = document.getElementById(headings[i].id)
        if (el && el.getBoundingClientRect().top <= 120) {
          setActiveHeading(headings[i].id)
          return
        }
      }
      setActiveHeading(null)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [headings])

  function scrollToHeading(id: string) {
    const el = document.getElementById(id)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  // Handle text selection
  function handleMouseUp() {
    const sel = window.getSelection()
    const text = sel?.toString().trim()
    if (!text || text.length < 3) { setSelection(null); return }
    const range = sel!.getRangeAt(0)
    const rect = range.getBoundingClientRect()
    setSelection({ text, x: rect.left + rect.width / 2, y: rect.top + window.scrollY - 8 })
  }

  // Close explain panel on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (
        popoverRef.current && !popoverRef.current.contains(e.target as Node) &&
        articleRef.current && !articleRef.current.contains(e.target as Node)
      ) {
        setSelection(null)
        setExplanation(null)
        setExplainPanelOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  function handleHighlight() {
    const sel = window.getSelection()
    if (!sel || sel.rangeCount === 0) return
    const range = sel.getRangeAt(0)
    const text = sel.toString().trim()
    const id = `hl-${Date.now()}`
    const mark = document.createElement('mark')
    mark.id = id
    mark.style.backgroundColor = '#FDE68A'
    mark.style.borderRadius = '2px'
    mark.style.padding = '0 1px'
    mark.style.cursor = 'pointer'
    mark.addEventListener('click', (e) => {
      e.stopPropagation()
      setHighlightPopover({ id, x: (e as MouseEvent).clientX, y: (e as MouseEvent).clientY + window.scrollY })
    })
    try {
      range.surroundContents(mark)
      setHighlights((prev) => [...prev, { id, text }])
    } catch {
      toast.error('Cannot highlight across multiple elements.')
    }
    sel.removeAllRanges()
    setSelection(null)
  }

  function removeHighlight(id: string) {
    const mark = document.getElementById(id)
    if (mark) {
      const parent = mark.parentNode!
      while (mark.firstChild) parent.insertBefore(mark.firstChild, mark)
      parent.removeChild(mark)
    }
    setHighlights((prev) => prev.filter((h) => h.id !== id))
    setHighlightPopover(null)
  }

  function scrollToHighlight(id: string) {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  async function handleExplain() {
    if (!selection || !documentId) return
    setExplaining(true)
    setExplanation(null)
    setExplainPanelOpen(true)
    const surroundingText = fullText ? (() => {
      const idx = fullText.indexOf(selection.text)
      if (idx === -1) return ''
      return fullText.slice(Math.max(0, idx - 200), idx + selection.text.length + 200)
    })() : ''
    try {
      const res = await api.explainSelection(documentId, selection.text, surroundingText)
      setExplanation(res.explanation)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not explain selection.')
      setExplainPanelOpen(false)
    } finally {
      setExplaining(false)
      setSelection(null)
      window.getSelection()?.removeAllRanges()
    }
  }

  function handleTakeQuiz() {
    navigate(`/quiz/${sessionId}`, {
      state: { document_id: documentId, persona: state?.persona, user_name: state?.user_name },
    })
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    )
  }

  // Custom h2 renderer — injects id for scroll targeting
  const mdComponents = {
    h2: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => {
      const text = typeof children === 'string' ? children : String(children)
      const id = slugify(text)
      return <h2 id={id} {...props}>{children}</h2>
    },
  }

  return (
    <div className="reading-page">
      {/* Top bar */}
      <header className="sticky top-0 z-10 bg-[#FAFAF7]/90 backdrop-blur border-b border-border">
        <div className="py-3 flex items-center justify-between" style={{ width: '90vw', margin: '0 auto' }}>
            <button onClick={() => navigate(-1)} className="text-sm text-muted-foreground hover:text-foreground transition-colors shrink-0">
              ← Back
            </button>
            <p className="text-sm text-muted-foreground truncate max-w-xs">{state?.filename ?? 'Reading'}</p>
          <button onClick={handleTakeQuiz} className="px-6 py-3 rounded-lg bg-foreground text-background text-sm font-medium hover:opacity-90 transition-opacity">
            Take quiz
          </button>
        </div>
      </header>

      {/* 3-column layout: outline | article | explain */}
      <div className="py-10" style={{ display: 'grid', gridTemplateColumns: '180px 600px 320px', justifyContent: 'space-between', width: '90vw', margin: '0 auto' }}>

        {/* Left: H2 outline + highlights */}
        <aside>
          <div className="sticky top-20 space-y-6">
            {headings.length > 0 && (
              <div className="space-y-1">
                <p className="text-[10px] uppercase tracking-widest text-muted-foreground mb-3">Contents</p>
                {headings.map((h) => (
                  <button
                    key={h.id}
                    onClick={() => scrollToHeading(h.id)}
                    className={`block w-full text-left text-xs leading-snug px-2 py-1.5 rounded transition-colors ${
                      activeHeading === h.id
                        ? 'text-foreground font-medium bg-black/5'
                        : 'text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    {h.text}
                  </button>
                ))}
              </div>
            )}

            {highlights.length > 0 && (
              <button
                onClick={() => setHighlightsPanelOpen(true)}
                className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1.5 rounded hover:bg-black/5 w-full text-left"
              >
                <span style={{ width: 10, height: 10, borderRadius: 2, backgroundColor: '#FDE68A', display: 'inline-block', flexShrink: 0 }} />
                {highlights.length} highlight{highlights.length !== 1 ? 's' : ''}
              </button>
            )}
          </div>
        </aside>

        {/* Center: article — always 600px */}
        <div>
          {loadingText ? (
            <div className="space-y-3">
              {[...Array(6)].map((_, i) => (
                <div key={i} className={`h-4 rounded bg-muted animate-pulse ${i % 4 === 3 ? 'w-2/3' : 'w-full'}`} />
              ))}
            </div>
          ) : (
            <div ref={articleRef} onMouseUp={handleMouseUp} className="prose reading-prose select-text">
              {isMarkdown
                ? <ReactMarkdown components={mdComponents}>{fullText ?? ''}</ReactMarkdown>
                : <span style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{fullText}</span>
              }
            </div>
          )}

          {!loadingText && fullText && (
            <div className="mt-16 pt-8 border-t border-border text-center">
              <p className="text-sm text-muted-foreground mb-4">
                {state?.persona === 'professor'
                  ? `Finished the material? Let's assess your comprehension with Prof. ${state.persona_name ?? 'Chen'}.`
                  : state?.persona === 'peer'
                  ? `${state.persona_name ?? 'Alex'}: nice work getting through it! Wanna see how much stuck?`
                  : "Done reading? Test your understanding."}
              </p>
              <button onClick={handleTakeQuiz} className="px-6 py-2.5 rounded-lg bg-foreground text-background text-sm font-medium hover:opacity-90 transition-opacity">
                Take the quiz
              </button>
            </div>
          )}
        </div>

        {/* Right: hint + explain panel */}
        <div>
          {!loadingText && !explainPanelOpen && (
            <div className="sticky top-20 rounded-lg border border-border bg-muted/30 p-4 space-y-1">
              <p className="text-xs uppercase tracking-widest text-muted-foreground">Tip</p>
              <p className="text-sm text-foreground leading-relaxed">
                Highlight any text to <span className="font-medium">save it</span> or ask for an <span className="font-medium">AI explanation</span>.
              </p>
            </div>
          )}
          {explainPanelOpen && (
            <div className="sticky top-20 rounded-lg border border-border bg-white/60 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs uppercase tracking-widest text-muted-foreground">Explanation</p>
                <button onClick={() => { setExplainPanelOpen(false); setExplanation(null) }} className="text-muted-foreground hover:text-foreground text-xs">✕</button>
              </div>
              {explaining ? (
                <div className="space-y-2">
                  {[...Array(4)].map((_, i) => (
                    <div key={i} className={`h-3 rounded bg-muted animate-pulse ${i === 3 ? 'w-3/4' : 'w-full'}`} />
                  ))}
                </div>
              ) : explanation ? (
                <p className="text-sm leading-relaxed" style={{ color: '#2D2D2D' }}>{explanation}</p>
              ) : null}
            </div>
          )}
        </div>
      </div>{/* end grid */}

      {/* Floating action popover on selection */}
      {selection && !explainPanelOpen && (
        <div ref={popoverRef} style={{ position: 'absolute', top: selection.y, left: selection.x, transform: 'translate(-50%, -100%)', zIndex: 50 }}>
          <div className="flex items-center gap-1 rounded-lg bg-foreground shadow-lg p-1">
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={handleHighlight}
              className="px-3 py-1.5 rounded-md text-background text-xs font-medium hover:bg-white/10 transition-colors"
            >
              Highlight
            </button>
            <div className="w-px h-4 bg-white/20" />
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={handleExplain}
              className="px-3 py-1.5 rounded-md text-background text-xs font-medium hover:bg-white/10 transition-colors"
            >
              Explain
            </button>
          </div>
        </div>
      )}

      {/* Highlight action popover (click on mark in article) */}
      {highlightPopover && (
        <div
          style={{ position: 'absolute', top: highlightPopover.y, left: highlightPopover.x, transform: 'translate(-50%, -110%)', zIndex: 50 }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <div className="flex items-center gap-1 rounded-lg bg-foreground shadow-lg p-1">
            <button
              onClick={() => { scrollToHighlight(highlightPopover.id); setHighlightsPanelOpen(true); setHighlightPopover(null) }}
              className="px-3 py-1.5 rounded-md text-background text-xs font-medium hover:bg-white/10 transition-colors"
            >
              View all
            </button>
            <div className="w-px h-4 bg-white/20" />
            <button
              onClick={() => removeHighlight(highlightPopover.id)}
              className="px-3 py-1.5 rounded-md text-background text-xs font-medium hover:bg-white/10 transition-colors"
            >
              Remove
            </button>
          </div>
        </div>
      )}

      {/* Highlights panel modal */}
      {highlightsPanelOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ backgroundColor: 'rgba(0,0,0,0.3)' }}
          onClick={() => setHighlightsPanelOpen(false)}
        >
          <div
            className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-border">
              <p className="text-sm font-medium text-foreground">Highlights</p>
              <button onClick={() => setHighlightsPanelOpen(false)} className="text-muted-foreground hover:text-foreground text-xs">✕</button>
            </div>
            <div className="divide-y divide-border max-h-96 overflow-y-auto">
              {highlights.length === 0 ? (
                <p className="text-sm text-muted-foreground px-5 py-6 text-center">No highlights yet.</p>
              ) : highlights.map((h) => (
                <div key={h.id} className="flex items-start gap-3 px-5 py-3 group hover:bg-muted/30 transition-colors">
                  <span style={{ width: 10, height: 10, borderRadius: 2, backgroundColor: '#FDE68A', flexShrink: 0, marginTop: 3 }} />
                  <button
                    onClick={() => { scrollToHighlight(h.id); setHighlightsPanelOpen(false) }}
                    className="flex-1 text-left text-sm text-foreground leading-snug hover:underline"
                  >
                    {h.text}
                  </button>
                  <button
                    onClick={() => removeHighlight(h.id)}
                    className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground text-xs transition-opacity shrink-0"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
