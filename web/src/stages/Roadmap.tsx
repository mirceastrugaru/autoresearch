import { useState, useEffect } from 'react'
import type { Direction, BurndownData } from '../types'
import { getDirections, getBurndown, rejectDirection } from '../api'
import { Card, StatusPill, StanceDot } from '../components/shared'
import { BurndownChart } from '../components/BurndownChart'

export function Roadmap({ sessionId }: {
  sessionId: string
  config: unknown
  directions: Direction[]
  isRunning: boolean
  onRefresh: () => void
}) {
  const [dirs, setDirs] = useState<Direction[]>([])
  const [burndown, setBurndown] = useState<BurndownData | null>(null)
  const [filter, setFilter] = useState('all')

  useEffect(() => {
    getDirections(sessionId).then(d => setDirs(d.items)).catch(() => {})
    getBurndown(sessionId).then(setBurndown).catch(() => {})
  }, [sessionId])

  const counts: Record<string, number> = {}
  dirs.forEach(d => { counts[d.status] = (counts[d.status] || 0) + 1 })

  const visible = filter === 'all' ? dirs : dirs.filter(d => d.status === filter)

  const handleReject = async (dirId: string) => {
    try {
      await rejectDirection(sessionId, dirId)
      setDirs(prev => prev.map(d => d.id === dirId ? { ...d, status: 'rejected' } : d))
    } catch {}
  }

  const filters = [
    ['all', 'All', dirs.length],
    ['covered', 'Covered', counts['covered'] || 0],
    ['in-progress', 'In progress', counts['in-progress'] || 0],
    ['queued', 'Queued', counts['queued'] || 0],
    ['proposed', 'Proposed', counts['proposed'] || 0],
    ['rejected', 'Rejected', counts['rejected'] || 0],
  ] as const

  return (
    <div className="p-7 max-w-[1060px] mx-auto">
      <div className="flex items-baseline gap-4 mb-[18px]">
        <div>
          <div className="label">Roadmap</div>
          <h1 className="serif text-[22px] font-medium mt-1 m-0 tracking-tight">
            {dirs.length} directions — judge-curated
          </h1>
        </div>
      </div>

      <div className="flex gap-1.5 mb-4 items-center flex-wrap">
        {filters.map(([k, l, n]) => (
          <button
            key={k}
            onClick={() => setFilter(k)}
            className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
              filter === k
                ? 'border-text bg-text text-bg'
                : 'border-border bg-surface text-text-2 hover:bg-surface-2'
            }`}
          >
            {l} <span className="opacity-60 ml-1">{n}</span>
          </button>
        ))}
      </div>

      <Card className="overflow-hidden mb-5">
        <div className="grid gap-3 px-4 py-2.5 border-b border-border text-[11px] text-text-3 font-semibold uppercase tracking-wide bg-surface-2"
          style={{ gridTemplateColumns: '28px 68px minmax(0, 1fr) 110px 72px 32px' }}>
          <span>#</span>
          <span>Stance</span>
          <span>Direction</span>
          <span>Status</span>
          <span>Score</span>
          <span></span>
        </div>
        {visible.map((d, i) => (
          <div key={d.id}
            className={`grid gap-3 px-4 py-3 items-center text-[13.5px] border-b border-border last:border-0 ${
              d.status === 'in-progress' ? 'bg-blue-soft' : 'bg-surface'
            } ${d.status === 'rejected' ? 'opacity-60' : ''}`}
            style={{ gridTemplateColumns: '28px 68px minmax(0, 1fr) 110px 72px 32px' }}>
            <span className="mono text-text-3">{String(i + 1).padStart(2, '0')}</span>
            <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium border ${
              d.stance === 'pro'
                ? 'bg-pro-soft text-pro border-pro/20'
                : 'bg-con-soft text-con border-con/20'
            }`}>
              <StanceDot stance={d.stance} />
              {d.stance}
            </span>
            <span className={d.status === 'rejected' ? 'line-through' : ''} style={{ overflowWrap: 'anywhere' }}>
              {d.text}
            </span>
            <StatusPill status={d.status} />
            <span className="mono text-text-2">
              {d.score !== null && d.score !== undefined ? (
                <>{d.score.toFixed(2)} {d.coverage > 0 && <span className="text-text-3">· {d.coverage}×</span>}</>
              ) : <span className="text-text-3">—</span>}
            </span>
            <button
              onClick={() => handleReject(d.id)}
              className="text-text-3 hover:text-con text-xs"
              title="Reject"
            >
              ×
            </button>
          </div>
        ))}
      </Card>

      {burndown && <BurndownChart data={burndown} />}
    </div>
  )
}
