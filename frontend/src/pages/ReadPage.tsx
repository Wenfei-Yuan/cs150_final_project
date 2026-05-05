import { useState, useEffect, useRef, useMemo, isValidElement } from 'react'
import ReactMarkdown from 'react-markdown'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { toast } from 'sonner'
import { api, type FollowUpTurn } from '@/lib/api'

type Heading = { id: string; text: string; chunkIndex: number }
type Highlight = { id: string; text: string; explanation?: string; followUpHistory?: FollowUpTurn[] }

function slugify(text: string) {
  return text.toLowerCase().replace(/[^\w\s-]/g, '').replace(/\s+/g, '-')
}

function extractText(node: React.ReactNode): string {
  if (typeof node === 'string') return node
  if (typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractText).join('')
  if (isValidElement(node)) return extractText((node.props as { children?: React.ReactNode }).children)
  return ''
}

function splitSentences(text: string): string[] {
  return text.split(/(?<=[.!?])\s+(?=[A-Z"])/).filter((s) => s.trim())
}

function renderWithKeyPhrases(text: string, keyPhrases: string[]) {
  if (keyPhrases.length === 0) return <>{text}</>
  const ranges: Array<{ start: number; end: number }> = []
  for (const phrase of keyPhrases) {
    const idx = text.toLowerCase().indexOf(phrase.toLowerCase())
    if (idx !== -1) ranges.push({ start: idx, end: idx + phrase.length })
  }
  if (ranges.length === 0) return <>{text}</>
  ranges.sort((a, b) => a.start - b.start)
  const merged: typeof ranges = []
  for (const r of ranges) {
    if (merged.length && r.start <= merged[merged.length - 1].end)
      merged[merged.length - 1].end = Math.max(merged[merged.length - 1].end, r.end)
    else merged.push({ ...r })
  }
  const segments: Array<{ text: string; isKey: boolean }> = []
  let cursor = 0
  for (const { start, end } of merged) {
    if (start > cursor) segments.push({ text: text.slice(cursor, start), isKey: false })
    segments.push({ text: text.slice(start, end), isKey: true })
    cursor = end
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), isKey: false })
  return (
    <>
      {segments.map((seg, i) =>
        seg.isKey
          ? <span key={i} style={{ fontWeight: 700, color: '#0F172A' }}>{seg.text}</span>
          : <span key={i}>{seg.text}</span>
      )}
    </>
  )
}

export default function ReadPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state as { document_id?: string; filename?: string; user_name?: string } | null

  const [documentId, setDocumentId] = useState<string | null>(state?.document_id ?? null)
  const [fullText, setFullText] = useState<string | null>(null)
  const [loadingText, setLoadingText] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeHeading, setActiveHeading] = useState<string | null>(null)
  const [highlights, setHighlights] = useState<Highlight[]>([])
  const [highlightsPanelOpen, setHighlightsPanelOpen] = useState(false)
  const [highlightPopover, setHighlightPopover] = useState<{ id: string; x: number; y: number } | null>(null)
  const [expandedHighlightId, setExpandedHighlightId] = useState<string | null>(null)

  // Explain state
  const [selection, setSelection] = useState<{ text: string; x: number; y: number } | null>(null)
  const [explanation, setExplanation] = useState<string | null>(null)
  const [explaining, setExplaining] = useState(false)
  const [explainPanelOpen, setExplainPanelOpen] = useState(false)
  const [explainPhase, setExplainPhase] = useState(0)
  const [explainFading, setExplainFading] = useState(false)
  const [explainedText, setExplainedText] = useState<string | null>(null)

  // Follow-up chat state
  const [followUpHistory, setFollowUpHistory] = useState<FollowUpTurn[]>([])
  const [followUpInput, setFollowUpInput] = useState('')
  const [followUpLoading, setFollowUpLoading] = useState(false)
  const [annotationMap, setAnnotationMap] = useState<Map<string, { label: 'fade' | 'normal'; keyPhrases: string[] }> | null>(null)
  const [visibleCount, setVisibleCount] = useState(1)
  const [revealing, setRevealing] = useState(false)
  // Reading preferences
  const [stepSize, setStepSize] = useState(1)
  const [fontSize, setFontSize] = useState(16)
  const [fontFamily, setFontFamily] = useState<'default' | 'lexend' | 'atkinson' | 'lora'>('default')
  const [stressingEnabled, setStressingEnabled] = useState(true)
  const [allRevealUnits, setAllRevealUnits] = useState<string[]>([])
  const [allChunkSections, setAllChunkSections] = useState<(string | null)[]>([])
  const [loadingChunks, setLoadingChunks] = useState(true)
  const preloadCache = useRef(new Map<number, Map<string, { label: 'fade' | 'normal'; keyPhrases: string[] }>>())
  const articleRef = useRef<HTMLDivElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const pendingScrollId = useRef<string | null>(null)
  const pendingRevealUnitIdx = useRef<number | null>(null)

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

  function buildAnnotationMap(res: Awaited<ReturnType<typeof api.annotateText>>) {
    const map = new Map<string, { label: 'fade' | 'normal'; keyPhrases: string[] }>()
    res.annotations.forEach(({ text, label, key_phrases }) =>
      map.set(text.trim().replace(/\s+/g, ' '), { label: label as 'fade' | 'normal', keyPhrases: key_phrases ?? [] })
    )
    return map
  }

  function mergeAnnotationMap(
    existing: Map<string, { label: 'fade' | 'normal'; keyPhrases: string[] }> | null,
    res: Awaited<ReturnType<typeof api.annotateText>>
  ) {
    const map = new Map(existing ?? [])
    res.annotations.forEach(({ text, label, key_phrases }) => {
      const key = text.trim().replace(/\s+/g, ' ')
      if (!map.has(key))
        map.set(key, { label: label as 'fade' | 'normal', keyPhrases: key_phrases ?? [] })
    })
    return map
  }

  function prefetch(docId: string, units: string[], count: number, baseMap: Map<string, { label: 'fade' | 'normal'; keyPhrases: string[] }> | null) {
    if (count > units.length || preloadCache.current.has(count)) return
    const prevMap = preloadCache.current.get(count - 1) ?? baseMap
    api.annotateText(docId, units.slice(0, count))
      .then((r) => preloadCache.current.set(count, mergeAnnotationMap(prevMap, r)))
      .catch(() => {})
  }

  // Fetch chunks, annotate first unit, then reveal — so highlights are always ready on load
  useEffect(() => {
    if (!documentId) return
    setLoadingChunks(true)
    preloadCache.current.clear()
    api.getAdhdChunks(documentId)
      .then(async (res) => {
        const HR_RE = /^[-*_](\s*[-*_]){2,}\s*$/
        const mergedUnits: string[] = []
        const mergedSections: (string | null)[] = []
        let carry: string[] = []

        for (const c of res.chunks) {
          const paras = c.paragraphs.map((p) => p.trim()).filter(Boolean)
          const isHrOnly = paras.length > 0 && paras.every((p) => HR_RE.test(p))
          if (isHrOnly) {
            carry.push(...paras)
            continue
          }

          const prefix = carry.length > 0 ? `${carry.join('\n\n')}\n\n` : ''
          mergedUnits.push(prefix + paras.join('\n\n'))
          mergedSections.push(c.section)
          carry = []
        }

        if (carry.length > 0 && mergedUnits.length > 0) {
          mergedUnits[mergedUnits.length - 1] = `${mergedUnits[mergedUnits.length - 1]}\n\n${carry.join('\n\n')}`
        }

        setAllRevealUnits(mergedUnits)
        setAllChunkSections(mergedSections)
        if (mergedUnits.length > 0) {
          try {
            const annotRes = await api.annotateText(documentId, mergedUnits.slice(0, 1))
            const map = buildAnnotationMap(annotRes)
            preloadCache.current.set(1, map)
            setAnnotationMap(map)
            prefetch(documentId, mergedUnits, 2, map)
          } catch {
            prefetch(documentId, mergedUnits, 2, null)
          }
        }
      })
      .catch(() => {})
      .finally(() => setLoadingChunks(false))
  }, [documentId])

  async function handleReadMore() {
    if (!documentId || revealing) return
    const nextCount = Math.min(allRevealUnits.length, visibleCount + stepSize)
    if (nextCount === visibleCount) return

    let nextBase: Map<string, { label: 'fade' | 'normal'; keyPhrases: string[] }> | null = null
    pendingRevealUnitIdx.current = nextCount - 1
    if (preloadCache.current.has(nextCount)) {
      nextBase = preloadCache.current.get(nextCount)!
      setAnnotationMap(nextBase)
      setVisibleCount(nextCount)
    } else {
      setRevealing(true)
      try {
        const res = await api.annotateText(documentId, allRevealUnits.slice(0, nextCount))
        const merged = mergeAnnotationMap(annotationMap, res)
        preloadCache.current.set(nextCount, merged)
        setAnnotationMap(merged)
        nextBase = merged
      } catch { /* reveal anyway */ }
      setVisibleCount(nextCount)
      setRevealing(false)
    }
    prefetch(documentId, allRevealUnits, nextCount + stepSize, nextBase)
  }

  function handleReadLess() {
    const prevCount = Math.max(1, visibleCount - stepSize)
    if (preloadCache.current.has(prevCount)) setAnnotationMap(preloadCache.current.get(prevCount)!)
    setVisibleCount(prevCount)
  }

  // Extract H2 headings and map each to its chunk index.
  // Primary: match against the chunk's section metadata field (works even when the
  // heading text isn't in the rendered chunk body).
  // Fallback: substring search of chunk text.
  const headings = useMemo<Heading[]>(() => {
    if (!isMarkdown || !fullText) return []
    return fullText
      .split('\n')
      .filter((line) => /^## /.test(line))
      .map((line) => {
        const text = line.replace(/^## /, '').trim()
        const needle = text.toLowerCase()
        const normalize = (s: string) =>
          s.replace(/^#+\s*/, '').replace(/^\d+(\.\d+)*\s+/, '').trim().toLowerCase()
        const bySection = allChunkSections.findIndex((s) => normalize(s ?? '') === needle)
        const chunkIndex = bySection !== -1
          ? bySection
          : allRevealUnits.findIndex((u) => u.includes(`## ${text}`))
        return { id: slugify(text), text, chunkIndex }
      })
  }, [fullText, isMarkdown, allRevealUnits, allChunkSections])

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

  const EXPLAIN_PHASES = [
    'Reading the selected text…',
    'Finding context in the document…',
    'Connecting ideas…',
    'Drafting an explanation…',
    'Polishing the response…',
  ]

  useEffect(() => {
    if (!explaining) { setExplainPhase(0); return }
    const cycle = () => {
      setExplainFading(true)
      setTimeout(() => {
        setExplainPhase((p) => (p + 1) % EXPLAIN_PHASES.length)
        setExplainFading(false)
      }, 300)
    }
    const id = setInterval(cycle, 1800)
    return () => clearInterval(id)
  }, [explaining])

  async function scrollToHeading(id: string, chunkIndex: number) {
    // chunkIndex === -1 means we couldn't find the chunk — try a direct scroll in case
    // the heading element already exists in the DOM (e.g. it's in a visible chunk).
    if (chunkIndex === -1) {
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      return
    }
    const requiredCount = chunkIndex + 1
    if (requiredCount > visibleCount) {
      setRevealing(true)
      try {
        let currentMap = annotationMap
        for (let n = visibleCount + 1; n <= requiredCount; n++) {
          if (preloadCache.current.has(n)) {
            currentMap = preloadCache.current.get(n)!
          } else if (documentId) {
            try {
              const res = await api.annotateText(documentId, allRevealUnits.slice(0, n))
              currentMap = mergeAnnotationMap(currentMap, res)
              preloadCache.current.set(n, currentMap)
            } catch { /* keep going */ }
          }
        }
        setAnnotationMap(currentMap)
        setVisibleCount(requiredCount)
        pendingScrollId.current = id
      } finally {
        setRevealing(false)
      }
    } else {
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  // Fire pending scroll after visibleCount DOM update
  useEffect(() => {
    if (!pendingScrollId.current) return
    const id = pendingScrollId.current
    pendingScrollId.current = null
    requestAnimationFrame(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }, [visibleCount])

  // After "Read More", scroll to the newly revealed unit with a top offset (~20vh).
  useEffect(() => {
    if (pendingRevealUnitIdx.current === null) return
    const unitIdx = pendingRevealUnitIdx.current
    pendingRevealUnitIdx.current = null
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-reveal-unit="${unitIdx}"]`)
      if (!el) return
      const top = el.getBoundingClientRect().top + window.scrollY
      const offset = window.innerHeight * 0.10
      window.scrollTo({ top: Math.max(0, top - offset), behavior: 'smooth' })
    })
  }, [visibleCount])

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
        setFollowUpHistory([])
        setFollowUpInput('')
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
      mark.appendChild(range.extractContents())
      range.insertNode(mark)
      setHighlights((prev) => [...prev, { id, text }])
    } catch {
      toast.error('Could not highlight selection.')
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
    setExplainedText(selection.text)
    setFollowUpHistory([])
    setFollowUpInput('')
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

  function saveExplainToHighlights() {
    if (!explainedText) return
    const id = `hl-${Date.now()}`
    setHighlights((prev) => [...prev, {
      id,
      text: explainedText,
      explanation: explanation ?? undefined,
      followUpHistory: followUpHistory.length > 0 ? [...followUpHistory] : undefined,
    }])
    toast.success('Saved to highlights')
  }

  async function handleFollowUp() {
    if (!followUpInput.trim() || !explainedText || !explanation || followUpLoading) return
    const question = followUpInput.trim()
    setFollowUpInput('')
    setFollowUpLoading(true)
    try {
      const res = await api.explainFollowUp(explainedText, explanation, question, followUpHistory)
      setFollowUpHistory((prev) => [...prev, { question, answer: res.answer }])
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not get follow-up answer.')
    } finally {
      setFollowUpLoading(false)
    }
  }

  // Stable across selection state changes — only recreates when annotations or stressing toggle changes.
  const annotatedParagraph = useMemo(() => (text: string) => {
    const sentences = splitSentences(text)
    if (!stressingEnabled || !annotationMap || sentences.length === 0) return <>{text}</>
    return (
      <>
        {sentences.map((s, i) => {
          const entry = annotationMap.get(s.trim().replace(/\s+/g, ' '))
          const label = entry?.label
          const keyPhrases = entry?.keyPhrases ?? []
          return (
            <span
              key={i}
              style={label === 'normal' ? { fontWeight: 300, color: '#0F172A' } : {}}
            >
              {renderWithKeyPhrases(s, keyPhrases)}{i < sentences.length - 1 ? ' ' : ''}
            </span>
          )
        })}
      </>
    )
  }, [annotationMap, stressingEnabled])

  const mdComponents = useMemo(() => ({
    h2: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => {
      const text = typeof children === 'string' ? children : String(children)
      const id = slugify(text)
      return <h2 id={id} {...props}>{children}</h2>
    },
    p: ({ children, ...props }: React.HTMLAttributes<HTMLParagraphElement>) => (
      <p {...props}>{annotatedParagraph(extractText(children))}</p>
    ),
  }), [annotatedParagraph])

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    )
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
          <div />
        </div>
      </header>

      {/* 3-column layout: outline | article | explain */}
      <div className="py-10" style={{ display: 'grid', gridTemplateColumns: '180px 600px 320px', justifyContent: 'space-between', width: '90vw', margin: '0 auto' }}>

        {/* Left: H2 outline + highlights */}
        <aside>
          <div className="sticky top-20 space-y-6">
            {headings.length > 0 && (
              <div className="space-y-1">
                <div className="flex items-center gap-2 mb-3">
                  <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Contents</p>
                  {revealing && (
                    <div className="w-3 h-3 rounded-full border-2 border-muted-foreground/30 border-t-muted-foreground animate-spin shrink-0" />
                  )}
                </div>
                {headings.map((h) => (
                  <button
                    key={h.id}
                    onClick={() => scrollToHeading(h.id, h.chunkIndex)}
                    disabled={revealing}
                    className={`block w-full text-left text-xs leading-snug px-2 py-1.5 rounded transition-colors disabled:opacity-50 ${
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

            {/* Reading preferences */}
            <div className="space-y-4 pt-1">
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Reading preferences</p>

              {/* Font family */}
              <div className="space-y-1.5">
                <p className="text-[11px] text-muted-foreground">Font</p>
                <div className="flex flex-wrap gap-1">
                  {([
                    ['default', 'Default'],
                    ['lexend', 'Lexend'],
                    ['atkinson', 'Atkinson'],
                    ['lora', 'Lora'],
                  ] as const).map(([f, label]) => (
                    <button
                      key={f}
                      onClick={() => setFontFamily(f)}
                      className={`text-[11px] px-2 py-0.5 rounded border transition-colors ${
                        fontFamily === f
                          ? 'border-foreground text-foreground font-medium'
                          : 'border-border text-muted-foreground hover:border-foreground/40'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Font size */}
              <div className="space-y-1.5">
                <p className="text-[11px] text-muted-foreground">Font size</p>
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => setFontSize((s) => Math.max(12, s - 2))}
                    className="w-6 h-6 flex items-center justify-center rounded border border-border hover:bg-muted/40 text-xs text-muted-foreground"
                  >–</button>
                  <span className="text-xs w-8 text-center tabular-nums">{fontSize}px</span>
                  <button
                    onClick={() => setFontSize((s) => Math.min(24, s + 2))}
                    className="w-6 h-6 flex items-center justify-center rounded border border-border hover:bg-muted/40 text-xs text-muted-foreground"
                  >+</button>
                </div>
              </div>

              {/* Chunk size */}
              <div className="space-y-1.5">
                <p className="text-[11px] text-muted-foreground">Chunk size</p>
                <p className="text-[10px] text-muted-foreground/60 leading-snug">Sections revealed per step</p>
                <div className="flex items-center gap-1">
                  {[1, 2, 3].map((n) => (
                    <button
                      key={n}
                      onClick={() => setStepSize(n)}
                      className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                        stepSize === n
                          ? 'border-foreground text-foreground font-medium'
                          : 'border-border text-muted-foreground hover:border-foreground/40'
                      }`}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>

              {/* Paragraph stressing toggle */}
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="text-[11px] text-foreground">Stressing</p>
                  <p className="text-[10px] text-muted-foreground/60 leading-snug">Highlights key sentences</p>
                </div>
                <button
                  onClick={() => setStressingEnabled((e) => !e)}
                  style={{
                    width: 32, height: 18, borderRadius: 9, flexShrink: 0,
                    backgroundColor: stressingEnabled ? '#0F172A' : '#CBD5E1',
                    position: 'relative', transition: 'background-color 0.2s',
                  }}
                >
                  <span style={{
                    position: 'absolute', top: 2, borderRadius: '50%',
                    width: 14, height: 14, backgroundColor: 'white',
                    left: stressingEnabled ? 16 : 2,
                    transition: 'left 0.2s',
                    boxShadow: '0 1px 2px rgba(0,0,0,0.15)',
                  }} />
                </button>
              </div>
            </div>

          </div>
        </aside>

        {/* Center: article — always 600px */}
        <div>
          {(loadingText || loadingChunks) ? (
            <div className="space-y-6 pt-2">
              <div className="flex items-center gap-3 pb-2">
                <div className="w-5 h-5 rounded-full border-2 border-muted-foreground/30 border-t-muted-foreground animate-spin shrink-0" />
                <span className="text-xs text-muted-foreground">Loading document…</span>
              </div>
              {[
                ['w-full','w-full','w-full','w-5/6'],
                ['w-full','w-full','w-4/5'],
                ['w-full','w-full','w-full','w-2/3'],
                ['w-full','w-3/4'],
              ].map((group, gi) => (
                <div key={gi} className="space-y-2.5">
                  {group.map((w, li) => (
                    <div key={li} className={`skeleton h-3.5 ${w}`} />
                  ))}
                </div>
              ))}
            </div>
          ) : (
            <div
              ref={articleRef}
              onMouseUp={handleMouseUp}
              className="prose reading-prose select-text"
              style={{
                fontSize: `${fontSize}px`,
                fontFamily: {
                  default: undefined,
                  lexend: "'Lexend Variable', 'Lexend', sans-serif",
                  atkinson: "'Atkinson Hyperlegible', sans-serif",
                  lora: "'Lora', serif",
                }[fontFamily],
              }}
            >
              {isMarkdown
                ? allRevealUnits.slice(0, visibleCount).map((unit, ui) => (
                  <div key={ui} data-reveal-unit={ui}>
                    <ReactMarkdown components={mdComponents}>{unit}</ReactMarkdown>
                  </div>
                ))
                : allRevealUnits.slice(0, visibleCount).map((unit, ui) => (
                  <div key={ui} data-reveal-unit={ui}>
                    {unit
                      .split(/\n\n+/)
                      .filter((p) => p.trim())
                      .map((para, pi) => (
                        <p key={`${ui}-${pi}`} className="mb-6">{annotatedParagraph(para.trim())}</p>
                      ))}
                  </div>
                ))
              }
            </div>
          )}

          {!loadingText && !loadingChunks && allRevealUnits.length > 0 && (
            <div className="mt-10 pt-6 border-t border-border flex flex-col items-center gap-4">
              <span className="text-xs text-muted-foreground">{visibleCount} / {allRevealUnits.length} sections</span>
              <div className="flex items-center gap-3">
                {visibleCount > 1 && (
                  <button
                    onClick={handleReadLess}
                    className="px-4 py-2 rounded-lg text-sm border border-border hover:bg-muted/40 transition-colors"
                  >
                    Read Less
                  </button>
                )}
                <button
                  onClick={handleReadMore}
                  disabled={visibleCount >= allRevealUnits.length || revealing}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm bg-foreground text-background hover:opacity-90 transition-opacity disabled:opacity-30"
                >
                  {revealing && <div className="w-3 h-3 rounded-full border-2 border-background/30 border-t-background animate-spin" />}
                  {visibleCount === 1 ? 'Start Reading' : 'Read More'}
                </button>
              </div>
              {visibleCount >= allRevealUnits.length && (
                <p className="text-xs text-muted-foreground italic">End of document.</p>
              )}
            </div>
          )}

        </div>

        {/* Right: highlights + hint + explain panel */}
        <div>
          {!loadingText && !explainPanelOpen && (
            <div className="sticky top-20 space-y-3">
              {highlights.length > 0 && (
                <button
                  onClick={() => setHighlightsPanelOpen(true)}
                  className="flex items-center gap-2 w-full rounded-lg border border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors text-left"
                >
                  <span style={{ width: 10, height: 10, borderRadius: 2, backgroundColor: '#FDE68A', display: 'inline-block', flexShrink: 0 }} />
                  {highlights.length} highlight{highlights.length !== 1 ? 's' : ''}
                </button>
              )}
              <div className="rounded-lg border border-border bg-muted/30 p-4 space-y-1">
                <p className="text-xs uppercase tracking-widest text-muted-foreground">Tip</p>
                <p className="text-sm text-foreground leading-relaxed">
                  Highlight any text to <span className="font-medium">save it</span> or ask for an <span className="font-medium">AI explanation</span>.
                </p>
              </div>
            </div>
          )}
          {explainPanelOpen && (
            <div className="sticky top-20 rounded-lg border border-border bg-white/60 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs uppercase tracking-widest text-muted-foreground">Explanation</p>
                <button
                  onClick={() => {
                    setExplainPanelOpen(false)
                    setExplanation(null)
                    setFollowUpHistory([])
                    setFollowUpInput('')
                  }}
                  className="text-muted-foreground hover:text-foreground text-xs"
                >✕</button>
              </div>
              {explaining ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-2.5">
                    <div className="w-3.5 h-3.5 rounded-full border-2 border-muted-foreground/30 border-t-muted-foreground animate-spin shrink-0" />
                    <p
                      className="text-xs text-muted-foreground transition-opacity duration-300"
                      style={{ opacity: explainFading ? 0 : 1 }}
                    >
                      {EXPLAIN_PHASES[explainPhase]}
                    </p>
                  </div>
                  <div className="space-y-2">
                    {['w-full','w-full','w-full','w-3/4'].map((w, i) => (
                      <div key={i} className={`skeleton h-3 ${w}`} />
                    ))}
                  </div>
                </div>
              ) : explanation ? (
                <div className="space-y-3">
                  {explainedText && (
                    <p className="text-xs text-muted-foreground italic border-l-2 border-border pl-2 leading-relaxed line-clamp-3">
                      "{explainedText}"
                    </p>
                  )}
                  <p className="text-sm leading-relaxed" style={{ color: '#2D2D2D' }}>{explanation}</p>
                  <button
                    onClick={saveExplainToHighlights}
                    className="text-xs text-muted-foreground hover:text-foreground transition-colors border border-border rounded-md px-2.5 py-1 hover:bg-muted/40"
                  >
                    + Save to highlights
                  </button>

                  {/* Follow-up Q&A section */}
                  {followUpHistory.length > 0 && (
                    <div className="space-y-3 pt-2 border-t border-border">
                      {followUpHistory.map((turn, i) => (
                        <div key={i} className="space-y-1">
                          <p className="text-xs font-medium text-foreground leading-snug">Q: {turn.question}</p>
                          <p className="text-xs text-muted-foreground leading-relaxed pl-2 border-l-2 border-border">{turn.answer}</p>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="pt-2 border-t border-border space-y-2">
                    <p className="text-xs text-muted-foreground">Ask a follow-up question</p>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={followUpInput}
                        onChange={(e) => setFollowUpInput(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') handleFollowUp() }}
                        placeholder="e.g. Can you give an example?"
                        disabled={followUpLoading}
                        className="flex-1 text-xs rounded-md border border-border bg-white px-2.5 py-1.5 placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-foreground/20 disabled:opacity-50"
                      />
                      <button
                        onClick={handleFollowUp}
                        disabled={!followUpInput.trim() || followUpLoading}
                        className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs bg-foreground text-background hover:opacity-90 transition-opacity disabled:opacity-30"
                      >
                        {followUpLoading
                          ? <div className="w-3 h-3 rounded-full border-2 border-background/30 border-t-background animate-spin" />
                          : 'Ask'
                        }
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </div>
      </div>{/* end grid */}

      {/* Floating action popover on selection */}
      {selection && (
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
                <div key={h.id} className="px-5 py-4 group hover:bg-muted/30 transition-colors">
                  <div className="flex items-start gap-3">
                    <span style={{ width: 10, height: 10, borderRadius: 2, backgroundColor: '#FDE68A', flexShrink: 0, marginTop: 4 }} />
                    <div className="flex-1 min-w-0 space-y-1.5">
                      <button
                        onClick={() => { scrollToHighlight(h.id); setHighlightsPanelOpen(false) }}
                        className="text-left text-sm text-foreground leading-snug hover:underline w-full"
                      >
                        {h.text}
                      </button>
                      {h.explanation && (
                        <p className="text-xs text-muted-foreground leading-relaxed border-l-2 border-border pl-2">
                          {h.explanation}
                        </p>
                      )}
                      {h.followUpHistory && h.followUpHistory.length > 0 && (
                        <div>
                          <button
                            onClick={() => setExpandedHighlightId(expandedHighlightId === h.id ? null : h.id)}
                            className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors mt-1"
                          >
                            <span style={{ display: 'inline-block', transition: 'transform 0.15s', transform: expandedHighlightId === h.id ? 'rotate(90deg)' : 'rotate(0deg)' }}>▶</span>
                            {h.followUpHistory.length} follow-up{h.followUpHistory.length !== 1 ? 's' : ''}
                          </button>
                          {expandedHighlightId === h.id && (
                            <div className="mt-2 space-y-2 pl-2 border-l-2 border-border">
                              {h.followUpHistory.map((turn, i) => (
                                <div key={i} className="space-y-0.5">
                                  <p className="text-[11px] font-medium text-foreground leading-snug">Q: {turn.question}</p>
                                  <p className="text-[11px] text-muted-foreground leading-relaxed">{turn.answer}</p>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                    <button
                      onClick={() => removeHighlight(h.id)}
                      className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground text-xs transition-opacity shrink-0 mt-0.5"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
