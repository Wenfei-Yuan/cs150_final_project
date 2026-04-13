import { useParams, useNavigate, useLocation } from 'react-router-dom'

export default function IntroPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state as {
    document_id?: string
    filename?: string
    user_name?: string
    persona?: string
    persona_name?: string
    intro?: string
  } | null

  const personaLabel = state?.persona === 'professor' ? 'Professor' : 'ADHD Peer'

  function handleStart() {
    navigate(`/read/${sessionId}`, { state })
  }

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center px-4">
      <button
        onClick={() => navigate(-1)}
        className="absolute top-6 left-6 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        ← Back
      </button>
      <div className="w-full max-w-lg space-y-8">
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-widest text-muted-foreground">{personaLabel}</p>
          <h1 className="text-2xl font-medium tracking-tight text-foreground">
            Meet your guide
          </h1>
        </div>

        {state?.intro ? (
          <div className="rounded-lg border border-border bg-muted/30 p-6">
            <p className="text-sm text-foreground leading-relaxed">{state.intro}</p>
          </div>
        ) : (
          <div className="rounded-lg border border-border bg-muted/30 p-6">
            <p className="text-sm text-muted-foreground italic">Your guide is ready.</p>
          </div>
        )}

        <button
          onClick={handleStart}
          className="w-full py-3 rounded-lg bg-foreground text-background text-sm font-medium hover:opacity-90 transition-opacity"
        >
          Start reading
        </button>
      </div>
    </div>
  )
}
