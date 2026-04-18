import { useState, useEffect } from 'react'
import type { Stage } from './types'
import { ChatRail } from './components/ChatRail'
import { Design } from './stages/Design'
import { Execution } from './stages/Execution'
import { Review } from './stages/Review'
import { Roadmap } from './stages/Roadmap'
import { useSession } from './hooks/useSession'
import { createSession, listSessions } from './api'

const STAGE_META: Record<Stage, { label: string; desc: string }> = {
  design:  { label: 'Design',    desc: 'Frame the thesis, set the agenda and rubric' },
  run:     { label: 'Execution', desc: 'Workers argue; judge synthesizes' },
  review:  { label: 'Review',    desc: 'Read the report and drill in' },
  roadmap: { label: 'Roadmap',   desc: 'Direction queue — judge-curated' },
}

export function App() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessions, setSessions] = useState<Array<{ id: string; thesis: string; stage: string }>>([])
  const [thesis, setThesis] = useState('')
  const [creating, setCreating] = useState(false)
  const { session, config, directions, stage, maxReached, isRunning, loading, switchStage, refresh } = useSession(sessionId)

  const loadSessions = () => {
    listSessions().then(d => setSessions(d.items)).catch(() => {})
  }

  useEffect(() => {
    loadSessions()
    const hash = window.location.hash.slice(1)
    if (hash) {
      setSessionId(hash)
      return
    }
    listSessions().then(d => {
      if (d.items.length > 0) {
        setSessionId(d.items[0].id)
      }
    }).catch(() => {})
  }, [])

  const handleCreate = async () => {
    if (!thesis.trim()) return
    setCreating(true)
    try {
      const s = await createSession(thesis)
      setSessionId(s.id)
      setThesis('')
      loadSessions()
    } catch (e) {
      console.error('Failed to create session:', e)
    }
    setCreating(false)
  }

  if (!sessionId) {
    return (
      <div className="h-screen flex items-center justify-center bg-bg">
        <div className="max-w-lg w-full p-8">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-lg bg-accent flex items-center justify-center text-white serif text-lg font-medium">A</div>
            <div className="text-xl font-semibold">Autoresearch</div>
          </div>
          <div className="label mb-2">New investigation</div>
          <textarea
            value={thesis}
            onChange={e => setThesis(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleCreate() } }}
            placeholder="What do you want to investigate?"
            rows={3}
            className="w-full bg-surface border border-border rounded-lg p-3 text-sm outline-none resize-none text-text placeholder:text-text-3 mb-3"
          />
          <button
            onClick={handleCreate}
            disabled={creating || !thesis.trim()}
            className="w-full px-4 py-2.5 rounded-md bg-accent text-white font-medium text-sm hover:bg-accent-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {creating ? 'Creating…' : 'Start'}
          </button>

          {sessions.length > 0 && (
            <div className="mt-8 border-t border-border pt-6">
              <div className="label mb-3">Or continue an existing investigation</div>
              <div className="flex flex-col gap-2">
                {sessions.map(s => (
                  <button
                    key={s.id}
                    onClick={() => { setSessionId(s.id); window.location.hash = s.id }}
                    className="w-full text-left p-3 rounded-lg border border-border bg-surface hover:bg-surface-2 transition-colors"
                  >
                    <div className="text-sm font-medium text-text">{s.thesis}</div>
                    <div className="text-[11px] text-text-3 mt-1 capitalize">{s.stage}</div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  if (loading && !session) {
    return (
      <div className="h-screen flex items-center justify-center bg-bg text-text-3 text-sm">
        Loading session…
      </div>
    )
  }

  const meta = STAGE_META[stage]
  const StageView = { design: Design, run: Execution, review: Review, roadmap: Roadmap }[stage]

  return (
    <div className="h-screen flex">
      <ChatRail
        sessionId={sessionId}
        stage={stage}
        maxReached={maxReached}
        isRunning={isRunning}
        onStageSwitch={switchStage}
        sessions={sessions}
        onSessionSwitch={(id) => { setSessionId(id); window.location.hash = id }}
        onRefresh={refresh}
      />
      <div className="flex-1 flex flex-col h-full overflow-hidden bg-bg">
        <div className="border-b border-border px-7 py-3.5 flex items-center gap-3.5">
          <div className="flex-1">
            <div className="text-sm font-semibold">{meta.label}</div>
            <div className="text-xs text-text-3">{meta.desc}</div>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          <StageView sessionId={sessionId} config={config} directions={directions} isRunning={isRunning} onRefresh={refresh} />
        </div>
      </div>
    </div>
  )
}
