export type Stage = 'design' | 'run' | 'review' | 'roadmap'

export interface Session {
  id: string
  thesis: string
  stage: Stage
  config?: SessionConfig
  run?: RunState
  verdict?: Verdict
  createdAt: string
  updatedAt: string
}

export interface SessionConfig {
  thesis: string
  directions: Direction[]
  rubric: Rubric | null
  rounds: number
  workersPerRound: number
  costCap: number | null
}

export interface Direction {
  id: string
  stance: string
  text: string
  status: string
  score: number | null
  coverage: number
}

export interface Rubric {
  hardGates: string[]
  softGates: Record<string, string>
}

export interface RunState {
  round: number
  experiment_count: number
  best_score: number
  active_branch: string
  discard_streak: number
}

export interface Worker {
  id: string
  stance: string
  dir: string
  status: string
  tool: string
  pct: number
}

export interface ActivityEntry {
  t: string
  who: string
  stance?: string
  msg: string
}

export interface Verdict {
  leaning: string
  tension: { pro: number; con: number }
  headline: string
  subtitle: string
  stats: { writeups: number; avgScore: number; rounds: number; cost: number }
  findings: Finding[]
  arguments: { pro: Argument[]; con: Argument[] }
  nextActions: NextAction[]
}

export interface Finding {
  leadWord: string
  text: string
  sourceWriteups: string[]
}

export interface Argument {
  title: string
  score: number
  evidence: string
  sourceWriteups: string[]
}

export interface NextAction {
  text: string
  priority: 'high' | 'med' | 'low'
  rationale: string
}

export interface WriteupSummary {
  id: string
  workerId: string
  round: number
  stance: string
  dir: string
  score: number
  status: string
  excerpt: string
}

export interface BurndownRound {
  r: number
  covered: number
  inProgress: number
  queued: number
  proposed: number
  isNow?: boolean
  projected?: boolean
}

export interface BurndownData {
  rounds: BurndownRound[]
  velocity: number
  projection: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  stage: string
  text: string
  toolCalls?: Array<{ name: string; args: Record<string, unknown>; result?: unknown }>
  createdAt: string
}
