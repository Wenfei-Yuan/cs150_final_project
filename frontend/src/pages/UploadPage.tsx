import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { api } from '@/lib/api'

type ReadingMode = 'default' | 'skim'

const MODE_INFO: Record<ReadingMode, { label: string; labelZh: string; desc: string }> = {
  skim: {
    label: 'Quick Overview',
    labelZh: '快速了解',
    desc: 'Get the big picture first. Free navigation, no quizzes — just read and self-assess.',
  },
  default: {
    label: 'Deep Reading',
    labelZh: '深度阅读',
    desc: 'Read chunk by chunk with retell and quiz to unlock each next section.',
  },
}

export default function UploadPage() {
  const [dragging, setDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedMode, setSelectedMode] = useState<ReadingMode>('skim')
  const [uploadedDocId, setUploadedDocId] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  async function handleFile(file: File) {
    if (!file.name.endsWith('.pdf')) {
      setError('Only PDF files are supported.')
      return
    }
    setLoading(true)
    setError(null)
    const toastId = toast.loading('Uploading and processing PDF…')
    try {
      const doc = await api.uploadDocument(file)
      toast.success(`${doc.filename} ready — ${doc.chunk_count} sections`, { id: toastId })
      setUploadedDocId(doc.document_id)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Upload failed.'
      toast.error(msg, { id: toastId })
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  async function handleStart() {
    if (!uploadedDocId) return
    setLoading(true)
    const toastId = toast.loading('Creating reading session…')
    try {
      const session = await api.createSession(uploadedDocId, '1', selectedMode)
      toast.success('Session created!', { id: toastId })
      navigate(`/read/${session.session_id}`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to create session.'
      toast.error(msg, { id: toastId })
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-lg space-y-8">
        <div className="space-y-2">
          <h1 className="text-2xl font-medium tracking-tight text-foreground">
            Reading companion
          </h1>
          <p className="text-sm text-muted-foreground">
            Upload a paper and choose how you want to read it.
          </p>
        </div>

        {/* Upload area */}
        <div
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`
            border rounded-lg p-12 text-center cursor-pointer transition-colors
            ${dragging ? 'border-foreground bg-muted' : 'border-border hover:border-muted-foreground'}
            ${uploadedDocId ? 'border-foreground/30 bg-muted/30' : ''}
          `}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf"
            className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
          />
          {loading ? (
            <p className="text-sm text-muted-foreground">Processing…</p>
          ) : uploadedDocId ? (
            <>
              <p className="text-sm text-foreground">PDF uploaded</p>
              <p className="text-xs text-muted-foreground mt-1">Choose a reading mode below</p>
            </>
          ) : (
            <>
              <p className="text-sm text-foreground">Drop a PDF here</p>
              <p className="text-xs text-muted-foreground mt-1">or click to browse</p>
            </>
          )}
        </div>

        {/* Mode selection (shown after upload) */}
        {uploadedDocId && (
          <div className="space-y-4">
            <p className="text-xs uppercase tracking-widest text-muted-foreground">Reading mode</p>
            <div className="grid grid-cols-2 gap-3">
              {(Object.keys(MODE_INFO) as ReadingMode[]).map((mode) => {
                const info = MODE_INFO[mode]
                const selected = selectedMode === mode
                return (
                  <button
                    key={mode}
                    onClick={() => setSelectedMode(mode)}
                    className={`
                      text-left p-4 rounded-lg border transition-colors
                      ${selected
                        ? 'border-foreground bg-muted'
                        : 'border-border hover:border-muted-foreground'
                      }
                    `}
                  >
                    <p className="text-sm font-medium text-foreground">
                      {info.label}
                      <span className="text-muted-foreground ml-1.5">{info.labelZh}</span>
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">{info.desc}</p>
                  </button>
                )
              })}
            </div>

            <button
              onClick={handleStart}
              disabled={loading}
              className="w-full py-3 rounded-lg bg-foreground text-background text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-30"
            >
              {loading ? 'Starting…' : `Start ${MODE_INFO[selectedMode].label}`}
            </button>
          </div>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
    </div>
  )
}
