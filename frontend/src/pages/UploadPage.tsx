import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { api } from '@/lib/api'

type Persona = 'professor' | 'peer'

const PERSONA_INFO: Record<Persona, { label: string; tagline: string; description: string }> = {
  professor: {
    label: 'Professor',
    tagline: 'Formal & precise',
    description: 'Structured explanations with academic depth. Great for building rigorous understanding.',
  },
  peer: {
    label: 'ADHD Peer',
    tagline: 'Casual & relatable',
    description: 'Friendly, energetic breakdowns from someone who gets it. Great for staying engaged.',
  },
}

const STORAGE_KEY = 'upload_form'

function loadSaved() {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? 'null')
  } catch {
    return null
  }
}

function save(data: object) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data))
}

export default function UploadPage() {
  const saved = loadSaved()
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uploadedDocId, setUploadedDocId] = useState<string | null>(saved?.uploadedDocId ?? null)
  const [uploadedFilename, setUploadedFilename] = useState<string | null>(saved?.uploadedFilename ?? null)
  const [username, setUsername] = useState<string>(saved?.username ?? '')
  const [selectedPersona, setSelectedPersona] = useState<Persona | null>(saved?.selectedPersona ?? null)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  async function handleFile(file: File) {
    if (!file.name.endsWith('.pdf') && !file.name.endsWith('.md')) {
      setError('Only PDF and Markdown files are supported.')
      return
    }
    setUploading(true)
    setError(null)
    const toastId = toast.loading('Uploading and processing file…')
    try {
      const doc = await api.uploadDocument(file)
      toast.success(`Ready — ${doc.chunk_count} sections`, { id: toastId })
      setUploadedDocId(doc.document_id)
      setUploadedFilename(doc.filename)
      save({ uploadedDocId: doc.document_id, uploadedFilename: doc.filename, username, selectedPersona })
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Upload failed.'
      toast.error(msg, { id: toastId })
      setError(msg)
    } finally {
      setUploading(false)
    }
  }

  async function handleStart() {
    if (!uploadedDocId || !username.trim() || !selectedPersona) return
    setStarting(true)
    const toastId = toast.loading('Setting up your session…')
    try {
      const session = await api.createSession(uploadedDocId, username.trim())
      const personaRes = await api.selectPersona(session.session_id, selectedPersona)
      toast.success('Ready!', { id: toastId })
      navigate(`/intro/${session.session_id}`, {
        state: {
          document_id: uploadedDocId,
          filename: uploadedFilename,
          user_name: username.trim(),
          persona: selectedPersona,
          persona_name: personaRes.name,
          intro: personaRes.intro,
        },
      })
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to create session.'
      toast.error(msg, { id: toastId })
      setError(msg)
    } finally {
      setStarting(false)
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  const canStart = !!uploadedDocId && username.trim().length > 0 && !!selectedPersona

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-lg space-y-8">
        <div className="space-y-2">
          <h1 className="text-2xl font-medium tracking-tight text-foreground">
            ADHD Reading Companion
          </h1>
          <p className="text-sm text-muted-foreground">
            Learn at your own pace.
          </p>
        </div>

        {/* Username — always visible */}
        <div className="space-y-1.5">
          <label className="text-xs uppercase tracking-widest text-muted-foreground">
            Enter your name
          </label>
          <input
            type="text"
            value={username}
            onChange={(e) => { setUsername(e.target.value); save({ uploadedDocId, uploadedFilename, username: e.target.value, selectedPersona }) }}
            onKeyDown={(e) => e.key === 'Enter' && canStart && handleStart()}
            placeholder="Enter your name"
            className="w-full px-3 py-2.5 rounded-lg border border-border bg-background text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-foreground transition-colors"
          />
        </div>

        {/* Upload area */}
        <div className="space-y-1.5">
          <label className="text-xs uppercase tracking-widest text-muted-foreground">
            Upload your paper
          </label>
          <div
            onClick={() => !uploadedDocId && inputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`
              border rounded-lg p-8 text-center transition-colors
              ${uploadedDocId
                ? 'border-foreground/20 bg-muted/30'
                : `cursor-pointer ${dragging ? 'border-foreground bg-muted' : 'border-border hover:border-muted-foreground'}`
              }
            `}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.md"
              className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
            />
            {uploading ? (
              <p className="text-sm text-muted-foreground">Processing…</p>
            ) : uploadedDocId && uploadedFilename ? (
              <div className="flex items-center justify-center gap-3">
                <div className="flex items-center justify-center w-9 h-9 rounded-md bg-foreground/10 shrink-0">
                  <svg className="w-5 h-5 text-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                </div>
                <div className="text-left">
                  <p className="text-sm font-medium text-foreground truncate max-w-xs">{uploadedFilename}</p>
                  <button
                    onClick={(e) => { e.stopPropagation(); setUploadedDocId(null); setUploadedFilename(null); save({ uploadedDocId: null, uploadedFilename: null, username, selectedPersona }); inputRef.current?.click() }}
                    className="text-xs text-muted-foreground hover:text-foreground transition-colors mt-0.5"
                  >
                    Replace file
                  </button>
                </div>
              </div>
            ) : (
              <>
                <p className="text-sm text-foreground">Upload your paper here</p>
                <p className="text-xs text-muted-foreground mt-1">PDF or Markdown · or click to browse</p>
              </>
            )}
          </div>
        </div>

        {/* Persona selection — always visible */}
        <div className="space-y-3">
          <label className="text-xs uppercase tracking-widest text-muted-foreground">
            Pick your guide
          </label>
          <div className="grid grid-cols-2 gap-3">
            {(Object.keys(PERSONA_INFO) as Persona[]).map((persona) => {
              const info = PERSONA_INFO[persona]
              const isSelected = selectedPersona === persona
              return (
                <button
                  key={persona}
                  onClick={() => { setSelectedPersona(persona); save({ uploadedDocId, uploadedFilename, username, selectedPersona: persona }) }}
                  className={`
                    text-left p-4 rounded-lg border transition-colors
                    ${isSelected
                      ? 'border-foreground bg-muted'
                      : 'border-border hover:border-muted-foreground'
                    }
                  `}
                >
                  <p className="text-sm font-medium text-foreground">{info.label}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{info.tagline}</p>
                  <p className="text-xs text-muted-foreground mt-2 leading-relaxed">{info.description}</p>
                </button>
              )
            })}
          </div>

        </div>

        {/* Continue */}
        <button
          onClick={handleStart}
          disabled={!canStart || starting}
          className="w-full py-3 rounded-lg bg-foreground text-background text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-30"
        >
          {starting ? 'Setting up…' : 'Continue'}
        </button>

        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
    </div>
  )
}
