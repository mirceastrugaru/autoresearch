import type { Stage } from '../types'

const STAGES: Array<{ key: Stage; label: string; icon: string }> = [
  { key: 'design', label: 'Design', icon: '🧪' },
  { key: 'run', label: 'Execution', icon: '📊' },
  { key: 'review', label: 'Review', icon: '📄' },
  { key: 'roadmap', label: 'Roadmap', icon: '🗺' },
]

const COMPLETED_ORDER = ['design', 'run', 'review', 'roadmap']

export function StageSwitcher({ current, maxReached, isRunning, onSwitch }: {
  current: Stage
  maxReached: Stage
  isRunning: boolean
  onSwitch: (s: Stage) => void
}) {
  const maxIdx = COMPLETED_ORDER.indexOf(maxReached)

  return (
    <div className="flex flex-col gap-1 p-3">
      {STAGES.map((s) => {
        const idx = COMPLETED_ORDER.indexOf(s.key)
        const isActive = s.key === current
        const isCompleted = idx < maxIdx
        const isAccessible = idx <= maxIdx

        return (
          <button
            key={s.key}
            onClick={() => isAccessible && onSwitch(s.key)}
            className={`
              flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-[13px] font-medium text-left transition-all
              ${isActive ? 'bg-surface shadow-sm text-text' : isAccessible ? 'text-text-2 hover:bg-surface-2 cursor-pointer' : 'text-text-3 opacity-50 cursor-not-allowed'}
            `}
          >
            <span className="text-sm">{s.icon}</span>
            <span className="flex-1">{s.label}</span>
            {isCompleted && <span className="text-pro text-xs">✓</span>}
            {s.key === 'run' && isRunning && (
              <span className="w-2 h-2 rounded-full bg-pro dot-live" />
            )}
          </button>
        )
      })}
    </div>
  )
}
