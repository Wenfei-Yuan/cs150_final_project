import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { api } from '@/lib/api'

export default function UploadPage() {
  const [dragging, setDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
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
      const session = await api.createSession(doc.document_id)
      navigate(`/read/${session.session_id}`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Upload failed.'
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
            Upload a paper and read it chunk by chunk.
          </p>
        </div>

        <div
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`
            border rounded-lg p-12 text-center cursor-pointer transition-colors
            ${dragging ? 'border-foreground bg-muted' : 'border-border hover:border-muted-foreground'}
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
          ) : (
            <>
              <p className="text-sm text-foreground">Drop a PDF here</p>
              <p className="text-xs text-muted-foreground mt-1">or click to browse</p>
            </>
          )}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
    </div>
  )
}
