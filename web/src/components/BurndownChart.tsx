import type { BurndownData } from '../types'
import { Card } from './shared'

const W = 640, H = 220
const padL = 40, padR = 24, padT = 20, padB = 36

export function BurndownChart({ data }: { data: BurndownData }) {
  const { rounds, velocity, projection } = data
  if (!rounds.length) return null

  const maxY = Math.max(10, ...rounds.map(r => r.covered + r.inProgress + r.queued + r.proposed))
  const plotW = W - padL - padR
  const plotH = H - padT - padB
  const x = (i: number) => padL + (i / Math.max(rounds.length - 1, 1)) * plotW
  const y = (v: number) => padT + (1 - v / maxY) * plotH

  const stack = rounds.map(d => {
    const a = d.covered
    const b = a + d.inProgress
    const c = b + d.queued
    const t = c + d.proposed
    return { ...d, a, b, c, t }
  })

  const bandPath = (hiKey: 'a' | 'b' | 'c' | 't', loKey: 'a' | 'b' | 'c' | 't' | 0) => {
    const hi = stack.map((d, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(d[hiKey])}`).join(' ')
    const lo = stack.slice().reverse().map((d, i) =>
      `L ${x(stack.length - 1 - i)} ${y(loKey === 0 ? 0 : d[loKey])}`
    ).join(' ')
    return hi + ' ' + lo + ' Z'
  }

  const coveredLine = stack.map((d, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(d.a)}`).join(' ')

  const totalCovered = stack.length > 0 ? stack[stack.length - 1].a : 0
  const totalDirs = stack.length > 0 ? stack[stack.length - 1].t : 0

  const gridLines = []
  for (let v = 0; v <= maxY; v += 2) gridLines.push(v)

  return (
    <Card className="p-[22px]">
      <div className="flex items-start gap-4 mb-3.5">
        <div>
          <div className="label">Burn-down</div>
          <div className="serif text-[18px] font-medium mt-1 tracking-tight">
            {totalCovered} of {totalDirs} directions covered
            {projection && ` — ${projection}`}
          </div>
        </div>
        <div className="ml-auto flex gap-[18px] items-end">
          <div className="text-right">
            <div className="label">Covered</div>
            <div className="serif text-[22px] font-medium">{totalCovered}</div>
          </div>
          <div className="text-right">
            <div className="label">Remaining</div>
            <div className="serif text-[22px] font-medium">{totalDirs - totalCovered}</div>
          </div>
          <div className="text-right">
            <div className="label">Velocity</div>
            <div className="serif text-[22px] font-medium">{velocity.toFixed(1)}</div>
            <div className="text-[11px] text-text-3">dir / round</div>
          </div>
        </div>
      </div>

      <div className="flex gap-3.5 text-[11px] text-text-2 mb-2.5 flex-wrap">
        <LegendSwatch color="var(--color-pro)" label="Covered" />
        <LegendSwatch color="var(--color-blue)" label="In progress" />
        <LegendSwatch color="var(--color-border-strong)" label="Queued" />
        <LegendSwatch color="var(--color-yellow-soft)" label="Proposed" stroke="#c9a94a" />
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto block">
        {gridLines.map(v => (
          <g key={v}>
            <line x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} stroke="var(--color-border)" strokeDasharray={v === 0 ? '' : '2 3'} />
            <text x={padL - 8} y={y(v) + 3.5} textAnchor="end" fontSize="10" fill="var(--color-text-3)" fontFamily="JetBrains Mono, monospace">{v}</text>
          </g>
        ))}

        {stack.some(d => d.projected) && (() => {
          const projIdx = stack.findIndex(d => d.projected)
          if (projIdx <= 0) return null
          return (
            <>
              <rect x={x(projIdx - 1)} y={padT} width={x(projIdx) - x(projIdx - 1)} height={plotH} fill="var(--color-surface-2)" opacity="0.5" />
              <text x={(x(projIdx - 1) + x(projIdx)) / 2} y={padT + 12} textAnchor="middle" fontSize="9.5" fill="var(--color-text-3)" fontFamily="JetBrains Mono, monospace" letterSpacing="0.08em">PROJECTED</text>
            </>
          )
        })()}

        <path d={bandPath('t', 'c')} fill="var(--color-yellow-soft)" stroke="#c9a94a" strokeWidth="1" opacity="0.9" />
        <path d={bandPath('c', 'b')} fill="var(--color-border-strong)" opacity="0.55" />
        <path d={bandPath('b', 'a')} fill="var(--color-blue-soft)" stroke="var(--color-blue)" strokeWidth="1" opacity="0.9" />
        <path d={bandPath('a', 0)} fill="var(--color-pro-soft)" stroke="var(--color-pro)" strokeWidth="1.5" />
        <path d={coveredLine} fill="none" stroke="var(--color-pro)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />

        {stack.map((d, i) => (
          <g key={i}>
            <line x1={x(i)} x2={x(i)} y1={y(0)} y2={y(0) + 4} stroke="var(--color-text-3)" />
            <text x={x(i)} y={y(0) + 18} textAnchor="middle" fontSize="10.5"
              fill={d.isNow ? 'var(--color-text)' : 'var(--color-text-3)'}
              fontWeight={d.isNow ? 600 : 400} fontFamily="Inter, sans-serif">
              {d.r === 0 ? 'Start' : `r${d.r}`}{d.isNow ? ' (now)' : ''}{d.projected ? ' (proj.)' : ''}
            </text>
            <circle cx={x(i)} cy={y(d.a)} r={d.isNow ? 4.5 : 3}
              fill={d.projected ? 'var(--color-surface)' : 'var(--color-pro)'}
              stroke="var(--color-pro)" strokeWidth="1.5" />
            {d.isNow && (
              <g>
                <line x1={x(i)} x2={x(i)} y1={padT} y2={y(0)} stroke="var(--color-accent)" strokeDasharray="3 3" strokeWidth="1" />
                <rect x={x(i) - 16} y={padT - 14} width="32" height="16" rx="3" fill="var(--color-accent)" />
                <text x={x(i)} y={padT - 3} textAnchor="middle" fontSize="9.5" fill="#fff" fontWeight="600" letterSpacing="0.05em" fontFamily="JetBrains Mono, monospace">NOW</text>
              </g>
            )}
            {d.a > 0 && !d.isNow && (
              <text x={x(i)} y={y(d.a) - 8} textAnchor="middle" fontSize="10" fill="var(--color-pro)" fontWeight="600" fontFamily="JetBrains Mono, monospace">{d.a}</text>
            )}
          </g>
        ))}

        <text x={padL - 32} y={padT + plotH / 2} transform={`rotate(-90, ${padL - 32}, ${padT + plotH / 2})`}
          textAnchor="middle" fontSize="10" fill="var(--color-text-3)" letterSpacing="0.08em" fontFamily="Inter, sans-serif">DIRECTIONS</text>
      </svg>

      {projection && (
        <div className="mt-2.5 p-2.5 px-3 bg-surface-2 rounded-md text-[12.5px] text-text-2">
          {projection}
        </div>
      )}
    </Card>
  )
}

function LegendSwatch({ color, label, stroke }: { color: string; label: string; stroke?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="w-3 h-3 rounded-sm inline-block" style={{ background: color, border: stroke ? `1px solid ${stroke}` : 'none' }} />
      {label}
    </span>
  )
}
