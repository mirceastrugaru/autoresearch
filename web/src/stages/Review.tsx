import { useState, useEffect } from 'react'
import type { Verdict, WriteupSummary } from '../types'
import { getVerdict, getWriteups, getMainDoc, getMetaDoc } from '../api'
import { Card, StanceDot, TensionBar } from '../components/shared'
import { Md } from '../components/Markdown'

export function Review({ sessionId }: {
  sessionId: string
  config: unknown
  directions: unknown[]
  isRunning: boolean
  onRefresh: () => void
}) {
  const [verdict, setVerdict] = useState<Verdict | null>(null)
  const [writeups, setWriteups] = useState<WriteupSummary[]>([])
  const [showDoc, setShowDoc] = useState<'main' | 'meta' | null>(null)
  const [docContent, setDocContent] = useState('')
  const [showWriteups, setShowWriteups] = useState(false)
  const [expandedWriteup, setExpandedWriteup] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      getVerdict(sessionId).catch(() => null),
      getWriteups(sessionId).catch(() => ({ items: [] })),
    ]).then(([v, w]) => {
      setVerdict(v)
      setWriteups(w.items)
      setLoading(false)
    })
  }, [sessionId])

  const handleShowDoc = async (which: 'main' | 'meta') => {
    if (showDoc === which) { setShowDoc(null); return }
    const fn = which === 'main' ? getMainDoc : getMetaDoc
    const content = await fn(sessionId)
    setDocContent(content)
    setShowDoc(which)
  }

  if (loading) {
    return <div className="p-7 text-text-3 text-sm">Loading review…</div>
  }

  if (!verdict) {
    return (
      <div className="p-7 max-w-[1060px] mx-auto">
        <div className="text-center py-16 text-text-3">
          <div className="text-lg mb-2">No verdict yet</div>
          <div className="text-sm">Run an investigation first to generate a review.</div>
        </div>
      </div>
    )
  }

  const leanColor = verdict.leaning === 'pro' ? 'text-pro' : verdict.leaning === 'con' ? 'text-con' : 'text-text-2'

  return (
    <div className="p-7 max-w-[1060px] mx-auto">
      {/* Verdict hero */}
      <Card className="p-7 mb-5" style={{ background: 'linear-gradient(180deg, var(--color-surface) 0%, var(--color-bg) 100%)' }}>
        <div className="flex items-start gap-6">
          <div className="flex-1">
            <div className="label mb-2">Verdict · {verdict.stats.rounds} round{verdict.stats.rounds !== 1 ? 's' : ''} · {verdict.stats.writeups} write-up{verdict.stats.writeups !== 1 ? 's' : ''}</div>
            <h1 className="serif text-[32px] leading-tight font-medium m-0 tracking-tight">
              {verdict.headline.split(/(pro|con)/i).map((part, i) => {
                if (part.toLowerCase() === 'pro') return <span key={i} className="text-pro">{part}</span>
                if (part.toLowerCase() === 'con') return <span key={i} className="text-con">{part}</span>
                return part
              })}
            </h1>
            <p className="serif text-base text-text-2 leading-relaxed mt-2.5 max-w-[620px]">
              {verdict.subtitle}
            </p>
          </div>
          <div className="w-[220px] shrink-0">
            <TensionBar pro={verdict.tension.pro} con={verdict.tension.con} />
            <div className="mt-3.5 grid grid-cols-2 gap-2.5">
              <div><div className="label">Writeups</div><div className="serif text-[20px] font-medium">{verdict.stats.writeups}</div></div>
              <div><div className="label">Avg score</div><div className="serif text-[20px] font-medium">{verdict.stats.avgScore.toFixed(2)}</div></div>
              <div><div className="label">Rounds</div><div className="serif text-[20px] font-medium">{verdict.stats.rounds}</div></div>
              <div><div className="label">Cost</div><div className="serif text-[20px] font-medium">${verdict.stats.cost.toFixed(2)}</div></div>
            </div>
          </div>
        </div>
      </Card>

      {/* Findings + Next Actions */}
      <div className="grid gap-4 mb-5" style={{ gridTemplateColumns: '1.3fr 1fr' }}>
        <Card className="p-[22px]">
          <div className="label mb-3.5">Key findings</div>
          {verdict.findings.length > 0 ? (
            <ol className="serif m-0 pl-5 text-[14.5px] leading-relaxed">
              {verdict.findings.map((f, i) => (
                <li key={i} className="mb-3">
                  <b>{f.leadWord}.</b>{' '}
                  <span className="text-text-2">{f.text}</span>
                  {f.sourceWriteups.length > 0 && (
                    <span className="ml-1.5 mono text-[10px] text-text-3">
                      [{f.sourceWriteups.join(', ')}]
                    </span>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <div className="text-sm text-text-3 py-4 text-center">No findings extracted yet</div>
          )}
        </Card>
        <Card className="p-[22px]">
          <div className="label mb-3.5">Next actions</div>
          {verdict.nextActions.length > 0 ? (
            <div className="flex flex-col gap-2.5 text-[13.5px]">
              {verdict.nextActions.map((a, i) => (
                <div key={i} className="flex items-start gap-2.5 py-2 border-b border-border">
                  <span className="w-3.5 h-3.5 border-[1.5px] border-border-strong rounded-sm shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <div>{a.text}</div>
                    {a.rationale && a.rationale !== a.text && (
                      <div className="text-[11px] text-text-3 mt-0.5">{a.rationale}</div>
                    )}
                  </div>
                  <span className={`text-[10px] rounded-full px-2 py-0.5 border shrink-0 ${
                    a.priority === 'high' ? 'bg-con-soft text-con border-con/20' :
                    a.priority === 'med' ? 'bg-surface-2 text-text-2 border-border' :
                    'bg-surface text-text-3 border-border'
                  }`}>{a.priority}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-text-3 py-4 text-center">All directions covered</div>
          )}
        </Card>
      </div>

      {/* Pro vs Con arguments */}
      <div className="grid grid-cols-2 gap-4 mb-5">
        <Card className="p-5">
          <div className="flex items-center gap-2 mb-3.5">
            <StanceDot stance="pro" />
            <div className="text-[13px] font-semibold text-pro">STRONGEST FOR</div>
            <span className="ml-auto mono text-[11px] text-text-3">{verdict.arguments.pro.length} args</span>
          </div>
          {verdict.arguments.pro.length > 0 ? verdict.arguments.pro.map((a, i) => (
            <div key={i} className="py-2.5 border-b border-border last:border-0">
              <div className="flex justify-between mb-1 gap-2">
                <span className="font-medium text-[13.5px] leading-snug">{a.title}</span>
                <span className="mono text-pro text-xs shrink-0">{a.score.toFixed(1)}</span>
              </div>
              {a.evidence && (
                <div className="text-[12.5px] text-text-2 leading-relaxed">{a.evidence}</div>
              )}
            </div>
          )) : (
            <div className="text-sm text-text-3 py-4 text-center">No pro arguments</div>
          )}
        </Card>
        <Card className="p-5">
          <div className="flex items-center gap-2 mb-3.5">
            <StanceDot stance="con" />
            <div className="text-[13px] font-semibold text-con">STRONGEST AGAINST</div>
            <span className="ml-auto mono text-[11px] text-text-3">{verdict.arguments.con.length} args</span>
          </div>
          {verdict.arguments.con.length > 0 ? verdict.arguments.con.map((a, i) => (
            <div key={i} className="py-2.5 border-b border-border last:border-0">
              <div className="flex justify-between mb-1 gap-2">
                <span className="font-medium text-[13.5px] leading-snug">{a.title}</span>
                <span className="mono text-con text-xs shrink-0">{a.score.toFixed(1)}</span>
              </div>
              {a.evidence && (
                <div className="text-[12.5px] text-text-2 leading-relaxed">{a.evidence}</div>
              )}
            </div>
          )) : (
            <div className="text-sm text-text-3 py-4 text-center">No con arguments</div>
          )}
        </Card>
      </div>

      {/* Drill-into bar */}
      <Card className="p-4 flex gap-2 items-center flex-wrap">
        <span className="text-xs text-text-3 mr-2">DRILL INTO</span>
        <button onClick={() => handleShowDoc('main')} className={`text-xs px-2.5 py-1 rounded-md border transition-colors ${
          showDoc === 'main' ? 'border-accent bg-accent/10 text-accent' : 'border-border bg-surface hover:bg-surface-2'
        }`}>
          main.md
        </button>
        <button onClick={() => handleShowDoc('meta')} className={`text-xs px-2.5 py-1 rounded-md border transition-colors ${
          showDoc === 'meta' ? 'border-accent bg-accent/10 text-accent' : 'border-border bg-surface hover:bg-surface-2'
        }`}>
          meta.md
        </button>
        <button
          onClick={() => setShowWriteups(!showWriteups)}
          className={`text-xs px-2.5 py-1 rounded-md border transition-colors ${
            showWriteups ? 'border-accent bg-accent/10 text-accent' : 'border-border bg-surface hover:bg-surface-2'
          }`}
        >
          {writeups.length} write-ups
        </button>
      </Card>

      {/* Document viewer */}
      {showDoc && (
        <Card className="mt-4 p-6">
          <div className="flex items-center mb-3">
            <div className="label">{showDoc}.md</div>
            <button onClick={() => setShowDoc(null)} className="ml-auto text-xs text-text-3 hover:text-text">Close</button>
          </div>
          <div className="serif text-sm leading-relaxed text-text max-h-[600px] overflow-y-auto">
            <Md>{docContent || 'No content'}</Md>
          </div>
        </Card>
      )}

      {/* Writeups list */}
      {showWriteups && (
        <Card className="mt-4 p-5">
          <div className="flex items-center mb-3.5">
            <div className="label">Write-ups</div>
            <button onClick={() => setShowWriteups(false)} className="ml-auto text-xs text-text-3 hover:text-text">Close</button>
          </div>
          {writeups.length === 0 ? (
            <div className="text-sm text-text-3 py-4 text-center">No write-ups persisted</div>
          ) : (
            <div className="flex flex-col">
              {writeups.map(w => (
                <div key={w.id} className="border-b border-border last:border-0">
                  <button
                    onClick={() => setExpandedWriteup(expandedWriteup === w.id ? null : w.id)}
                    className="w-full text-left py-3 px-1 flex items-center gap-3 hover:bg-surface-2 transition-colors rounded"
                  >
                    <StanceDot stance={w.stance} />
                    <span className="mono text-[11px] text-text-3 w-16 shrink-0">{w.id}</span>
                    <span className="text-[13px] flex-1 min-w-0 truncate">{w.dir || w.excerpt || 'No direction'}</span>
                    <span className={`mono text-xs ${w.status === 'keep' ? 'text-pro' : 'text-text-3'}`}>
                      {w.score.toFixed(1)}
                    </span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
                      w.status === 'keep' ? 'border-pro/20 bg-pro-soft text-pro' : 'border-border bg-surface-2 text-text-3'
                    }`}>{w.status}</span>
                    <span className="text-text-3 text-xs">{expandedWriteup === w.id ? '▲' : '▼'}</span>
                  </button>
                  {expandedWriteup === w.id && (
                    <div className="px-6 pb-3 text-[13px] text-text-2 leading-relaxed">
                      <Md>{w.excerpt || 'No content available'}</Md>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
