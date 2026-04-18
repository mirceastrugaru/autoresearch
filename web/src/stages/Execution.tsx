import { useState, useEffect } from 'react'
import type { SessionConfig } from '../types'
import { useRunState } from '../hooks/useSSE'
import { pauseRun, resumeRun, getMainDoc } from '../api'
import { Card, StatusPill, StanceDot, TensionBar, Button } from '../components/shared'
import { Md } from '../components/Markdown'

export function Execution({ sessionId, config, isRunning }: {
  sessionId: string
  config: SessionConfig | null
  directions: unknown[]
  isRunning: boolean
  onRefresh: () => void
}) {
  const { workers, activity, round, tension, cost, tokens, stallStreak } = useRunState(sessionId, isRunning)
  const [mainDoc, setMainDoc] = useState('')
  const [paused, setPaused] = useState(false)

  useEffect(() => {
    getMainDoc(sessionId).then(text => {
      if (!text.startsWith('{')) setMainDoc(text)
    }).catch(() => {})
    const interval = isRunning ? setInterval(() => {
      getMainDoc(sessionId).then(text => {
        if (!text.startsWith('{')) setMainDoc(text)
      }).catch(() => {})
    }, 10000) : undefined
    return () => clearInterval(interval)
  }, [sessionId, isRunning])

  const handlePause = async () => {
    try {
      if (paused) {
        await resumeRun(sessionId)
        setPaused(false)
      } else {
        await pauseRun(sessionId)
        setPaused(true)
      }
    } catch (e) {
      console.error('Pause/resume failed:', e)
    }
  }

  const thesis = config?.thesis || ''

  return (
    <div className="p-7 max-w-[1100px] mx-auto">
      <div className="flex items-start gap-6 mb-6">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5">
            {isRunning && <span className="w-2 h-2 rounded-full bg-pro dot-live" />}
            <span className="label" style={{ color: isRunning ? 'var(--color-pro)' : undefined }}>
              {isRunning ? `Running · Round ${round}` : `Completed · ${round} rounds`}
            </span>
          </div>
          <h1 className="serif text-[22px] font-medium m-0 tracking-tight leading-snug">{thesis}</h1>
        </div>
        {isRunning && (
          <Button onClick={handlePause}>
            {paused ? '▶ Resume' : '⏸ Pause'}
          </Button>
        )}
      </div>

      <div className="grid grid-cols-4 gap-3 mb-5">
        <Card className="p-3.5">
          <div className="label mb-1.5">Tension</div>
          <TensionBar pro={tension.pro} con={tension.con} />
        </Card>
        <Card className="p-3.5">
          <div className="label mb-1.5">Stall streak</div>
          <div className="serif text-[22px] font-medium">{stallStreak} / 5</div>
          <div className="text-[11px] text-text-3 mt-0.5">{stallStreak < 3 ? 'healthy' : 'warning'}</div>
        </Card>
        <Card className="p-3.5">
          <div className="label mb-1.5">Cost</div>
          <div className="serif text-[22px] font-medium">${cost.toFixed(2)}</div>
          <div className="text-[11px] text-text-3 mt-0.5">{config?.costCap ? `of $${config.costCap.toFixed(2)} cap` : 'no cap'}</div>
        </Card>
        <Card className="p-3.5">
          <div className="label mb-1.5">Tokens</div>
          <div className="serif text-[22px] font-medium">{tokens > 1000 ? `${Math.round(tokens / 1000)}k` : tokens}</div>
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-4 mb-5">
        <Card className="p-[18px]">
          <div className="flex items-center mb-3">
            <div className="label">Workers</div>
            <span className="ml-auto text-xs text-text-3">{workers.length} active</span>
          </div>
          <div className="flex flex-col gap-2.5">
            {workers.length === 0 && (
              <div className="text-sm text-text-3 py-4 text-center">No active workers</div>
            )}
            {workers.map(w => (
              <div key={w.id} className="p-2.5 px-3 border border-border rounded-lg bg-bg">
                <div className="flex items-center gap-2 mb-1.5">
                  <StanceDot stance={w.stance} />
                  <span className="mono text-text-3 text-[11px]">{w.id}</span>
                  <span className="text-[13px] font-medium">{w.dir}</span>
                  <span className="ml-auto"><StatusPill status={w.status} /></span>
                </div>
                <div className="mono text-text-3 text-[11px] mb-1.5">{w.tool || '—'}</div>
                <div className="h-1 bg-surface-3 rounded-sm overflow-hidden">
                  <div
                    className="h-full rounded-sm transition-all duration-300"
                    style={{
                      width: `${w.pct}%`,
                      background: w.stance === 'pro' ? 'var(--color-pro)' : 'var(--color-con)',
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-[18px]">
          <div className="flex items-center mb-3">
            <div className="label">Activity</div>
            <span className="ml-auto text-xs text-text-3">{isRunning ? 'Live' : 'History'}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            {activity.length === 0 && (
              <div className="text-sm text-text-3 py-4 text-center">No activity yet</div>
            )}
            {activity.slice(0, 15).map((a, i) => (
              <div key={i} className="flex items-baseline gap-2.5 py-1.5 px-0.5 text-[12.5px] border-b border-border last:border-0">
                <span className="mono text-text-3 text-[10.5px]">{a.t}</span>
                <span className="mono font-medium min-w-[44px] text-[11px]" style={{
                  color: a.who === 'judge' ? 'var(--color-blue)' : a.stance === 'pro' ? 'var(--color-pro)' : 'var(--color-con)',
                }}>{a.who}</span>
                <span className="flex-1 text-text-2">{a.msg}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {mainDoc && (
        <Card className="p-6">
          <div className="flex items-center mb-3.5">
            <div className="label">Main document</div>
            {isRunning && (
              <div className="ml-3 flex items-center gap-1.5 text-[11px] text-text-3">
                <span className="w-1.5 h-1.5 rounded-full bg-pro dot-live" /> writing live
              </div>
            )}
          </div>
          <div className="serif text-[15px] leading-relaxed text-text max-w-[720px]">
            <Md>{mainDoc.slice(0, 3000)}</Md>
            {mainDoc.length > 3000 && <div className="text-text-3 text-sm mt-2">… (truncated)</div>}
          </div>
        </Card>
      )}
    </div>
  )
}
