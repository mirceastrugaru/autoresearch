import { useState } from 'react'
import type { SessionConfig, Direction } from '../types'
import { startRun, getEstimate, addDirection } from '../api'
import { Card, StanceDot, Button } from '../components/shared'

export function Design({ sessionId, config, directions }: {
  sessionId: string
  config: SessionConfig | null
  directions: Direction[]
  isRunning: boolean
  onRefresh: () => void
}) {
  const [estimate, setEstimate] = useState<{ estimatedCost: number } | null>(null)
  const [starting, setStarting] = useState(false)
  const [newDir, setNewDir] = useState<{ stance: string; text: string } | null>(null)

  const pros = directions.filter(d => d.stance === 'pro')
  const cons = directions.filter(d => d.stance === 'con')

  const handleEstimate = async () => {
    try {
      const e = await getEstimate(sessionId)
      setEstimate(e)
    } catch {}
  }

  const handleStart = async () => {
    setStarting(true)
    try {
      await startRun(sessionId)
    } catch (e) {
      console.error('Failed to start:', e)
    }
    setStarting(false)
  }

  const handleAddDirection = async () => {
    if (!newDir || !newDir.text.trim()) return
    try {
      await addDirection(sessionId, newDir.stance, newDir.text)
      setNewDir(null)
      window.location.reload()
    } catch (e) {
      console.error('Failed to add direction:', e)
    }
  }

  if (!config) return null

  return (
    <div className="p-8 max-w-[880px] mx-auto">
      <div className="mb-7">
        <div className="label mb-2">Thesis</div>
        <h1 className="serif text-[28px] leading-tight font-medium m-0 tracking-tight">
          {config.thesis}
        </h1>
        <div className="text-text-3 text-[13px] mt-2">
          Tell Claude to rephrase, narrow, or invert it.
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 mb-7">
        <Card className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <StanceDot stance="pro" />
            <div className="font-semibold text-sm">Arguing for</div>
            <span className="ml-auto text-xs text-text-3">{pros.length} directions</span>
          </div>
          <div className="flex flex-col gap-0.5">
            {pros.map(d => (
              <div key={d.id} className="flex items-center gap-2 py-2 px-1 border-b border-border text-[13.5px]">
                <span className="text-text-3">·</span>
                <span>{d.text}</span>
              </div>
            ))}
          </div>
          <button
            onClick={() => setNewDir({ stance: 'pro', text: '' })}
            className="mt-2 text-xs text-accent font-medium hover:underline"
          >
            + Add
          </button>
        </Card>

        <Card className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <StanceDot stance="con" />
            <div className="font-semibold text-sm">Arguing against</div>
            <span className="ml-auto text-xs text-text-3">{cons.length} directions</span>
          </div>
          <div className="flex flex-col gap-0.5">
            {cons.map(d => (
              <div key={d.id} className="flex items-center gap-2 py-2 px-1 border-b border-border text-[13.5px]">
                <span className="text-text-3">·</span>
                <span>{d.text}</span>
              </div>
            ))}
          </div>
          <button
            onClick={() => setNewDir({ stance: 'con', text: '' })}
            className="mt-2 text-xs text-accent font-medium hover:underline"
          >
            + Add
          </button>
        </Card>
      </div>

      {newDir && (
        <Card className="p-4 mb-5">
          <div className="flex items-center gap-3 mb-3">
            <StanceDot stance={newDir.stance} />
            <span className="text-sm font-medium">New {newDir.stance} direction</span>
          </div>
          <input
            value={newDir.text}
            onChange={e => setNewDir({ ...newDir, text: e.target.value })}
            onKeyDown={e => { if (e.key === 'Enter') handleAddDirection() }}
            placeholder="Describe the direction…"
            className="w-full bg-surface-2 border border-border rounded-md px-3 py-2 text-sm outline-none"
            autoFocus
          />
          <div className="flex gap-2 mt-3">
            <Button size="sm" variant="primary" onClick={handleAddDirection}>Add</Button>
            <Button size="sm" onClick={() => setNewDir(null)}>Cancel</Button>
          </div>
        </Card>
      )}

      {config.rubric && (
        <Card className="p-5 mb-5">
          <div className="label mb-3.5">Rubric</div>
          <div className="grid grid-cols-2 gap-5">
            <div>
              <div className="text-xs font-semibold text-con mb-1.5">HARD GATES · score 0 if any fail</div>
              <div className="flex flex-col gap-1.5 text-[13px]">
                {config.rubric.hardGates.map(g => (
                  <div key={g} className="flex items-center gap-1.5">
                    <span className="text-pro">✓</span>
                    <span>{g}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold text-blue mb-1.5">SOFT GATES · +1 per pass</div>
              <div className="flex flex-col gap-1.5 text-[13px]">
                {Object.entries(config.rubric.softGates).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-4">
                    <span className="shrink-0">{k.replace(/_/g, ' ')}</span>
                    <span className="mono text-text-3 text-right text-[11px]">{v}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Card>
      )}

      <Card className="p-[18px] flex items-center gap-5">
        <div>
          <div className="label">Rounds</div>
          <div className="serif text-[22px] font-medium mt-0.5">{config.rounds}</div>
        </div>
        <div className="w-px h-8 bg-border" />
        <div>
          <div className="label">Workers / round</div>
          <div className="serif text-[22px] font-medium mt-0.5">
            {config.workersPerRound} <span className="text-text-3 text-sm">total</span>
          </div>
        </div>
        <div className="w-px h-8 bg-border" />
        <div>
          <div className="label">Estimated cost</div>
          <div className="serif text-[22px] font-medium mt-0.5">
            {estimate ? `~$${estimate.estimatedCost.toFixed(2)}` : (
              <button onClick={handleEstimate} className="text-sm text-accent hover:underline">Calculate</button>
            )}
          </div>
        </div>
        <Button variant="primary" className="ml-auto" onClick={handleStart} disabled={starting}>
          {starting ? 'Starting…' : '▶ Start investigation'}
        </Button>
      </Card>
    </div>
  )
}
