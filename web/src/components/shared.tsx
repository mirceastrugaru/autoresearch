export function StatusPill({ status }: { status: string }) {
  const colors: Record<string, string> = {
    covered: 'bg-[#eef2ea] text-[#3f5f3a]',
    'in-progress': 'bg-[#e9f0f7] text-[#3b6fa5]',
    queued: 'bg-[#f0ede4] text-[#7a7360]',
    proposed: 'bg-[#faf0d4] text-[#8a6c15]',
    rejected: 'bg-[#f4ebe7] text-[#a05b42]',
    running: 'bg-[#eef2ea] text-[#3f5f3a]',
    scoring: 'bg-[#e9f0f7] text-[#3b6fa5]',
    failed: 'bg-[#f4ebe7] text-[#a05b42]',
    keep: 'bg-[#eef2ea] text-[#3f5f3a]',
    discard: 'bg-[#f4ebe7] text-[#a05b42]',
    done: 'bg-[#eef2ea] text-[#3f5f3a]',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${colors[status] || 'bg-surface-2 text-text-2'}`}>
      {status}
    </span>
  )
}

export function StanceDot({ stance }: { stance: string }) {
  const color = stance === 'pro' ? 'bg-pro' : stance === 'con' ? 'bg-con' : 'bg-text-3'
  return <span className={`w-1.5 h-1.5 rounded-full inline-block ${color}`} />
}

export function TensionBar({ pro, con }: { pro: number; con: number }) {
  return (
    <div>
      <div className="flex justify-between items-center text-[11px] leading-none mb-1">
        <span className="text-pro font-medium whitespace-nowrap">PRO {pro}</span>
        <span className="text-con font-medium whitespace-nowrap">{con} CON</span>
      </div>
      <div className="h-1.5 bg-surface-3 rounded-sm flex overflow-hidden">
        <div className="bg-pro rounded-l-sm" style={{ width: `${pro}%` }} />
        <div className="bg-con rounded-r-sm" style={{ width: `${con}%` }} />
      </div>
    </div>
  )
}

export function Card({ children, className = '', style }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <div className={`bg-surface border border-border rounded-[10px] ${className}`} style={style}>
      {children}
    </div>
  )
}

export function Button({ children, variant = 'default', size = 'md', onClick, className = '', disabled }: {
  children: React.ReactNode
  variant?: 'default' | 'primary' | 'ghost'
  size?: 'sm' | 'md'
  onClick?: () => void
  className?: string
  disabled?: boolean
}) {
  const base = 'inline-flex items-center gap-1.5 rounded-[6px] font-medium border transition-all whitespace-nowrap'
  const sizes = { sm: 'px-2.5 py-1 text-xs', md: 'px-3 py-[7px] text-[13px]' }
  const variants = {
    default: 'border-border bg-surface text-text hover:border-border-strong hover:bg-surface-2',
    primary: 'border-accent bg-accent text-white hover:bg-accent-2 hover:border-accent-2',
    ghost: 'border-transparent bg-transparent text-text-2 hover:bg-surface-2 hover:text-text',
  }
  return (
    <button
      className={`${base} ${sizes[size]} ${variants[variant]} ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'} ${className}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  )
}
