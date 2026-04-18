import type { Session, SessionConfig, Direction, Verdict, WriteupSummary, BurndownData, ChatMessage, Worker, ActivityEntry } from './types'

const BASE = '/api'

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

// Sessions
export const createSession = (thesis: string) =>
  fetchJson<{ id: string; thesis: string; stage: string }>('/sessions', {
    method: 'POST',
    body: JSON.stringify({ thesis }),
  })

export const listSessions = () =>
  fetchJson<{ items: Array<{ id: string; thesis: string; stage: string; updatedAt: string }>; nextCursor: string | null }>('/sessions')

export const getSession = (id: string) =>
  fetchJson<Session>(`/sessions/${id}`)

export const deleteSession = (id: string) =>
  fetch(`${BASE}/sessions/${id}`, { method: 'DELETE' })

// Config
export const getConfig = (id: string) =>
  fetchJson<SessionConfig>(`/sessions/${id}/config`)

export const updateConfig = (id: string, data: Partial<{ thesis: string; rounds: number; workersPerRound: number; costCap: number }>) =>
  fetchJson<SessionConfig>(`/sessions/${id}/config`, { method: 'PATCH', body: JSON.stringify(data) })

// Directions
export const addDirection = (id: string, stance: string, text: string) =>
  fetchJson<Direction>(`/sessions/${id}/directions`, { method: 'POST', body: JSON.stringify({ stance, text }) })

export const getDirections = (id: string) =>
  fetchJson<{ items: Direction[] }>(`/sessions/${id}/directions`)

// Rubric
export const updateRubric = (id: string, data: { hardGates?: string[]; softGates?: Record<string, string> }) =>
  fetchJson(`/sessions/${id}/rubric`, { method: 'PATCH', body: JSON.stringify(data) })

// Estimate
export const getEstimate = (id: string) =>
  fetchJson<{ estimatedCost: number; estimatedTokens: number; estimatedDurationSec: number }>(`/sessions/${id}/estimate`)

// Execution
export const startRun = (id: string) =>
  fetchJson<{ runId: string; startedAt: string }>(`/sessions/${id}/run`, { method: 'POST' })

export const pauseRun = (id: string) =>
  fetchJson(`/sessions/${id}/pause`, { method: 'POST' })

export const resumeRun = (id: string) =>
  fetchJson(`/sessions/${id}/resume`, { method: 'POST' })

export const stopRun = (id: string) =>
  fetchJson(`/sessions/${id}/stop`, { method: 'POST' })

export const getWorkers = (id: string) =>
  fetchJson<{ workers: Worker[]; round: number; tension: { pro: number; con: number }; cost: number; tokens: number; stallStreak: number }>(`/sessions/${id}/workers`)

export const getActivity = (id: string) =>
  fetchJson<{ items: ActivityEntry[] }>(`/sessions/${id}/activity`)

// SSE stream
export function openStream(id: string, onEvent: (type: string, data: unknown) => void): () => void {
  const es = new EventSource(`${BASE}/sessions/${id}/stream`)
  const types = ['stage', 'round.start', 'round.complete', 'worker.update', 'activity', 'judge.score', 'doc.update', 'stall.update', 'run.complete', 'error']
  for (const t of types) {
    es.addEventListener(t, (e) => {
      try { onEvent(t, JSON.parse((e as MessageEvent).data)) } catch {}
    })
  }
  return () => es.close()
}

// Review
export const getVerdict = (id: string) =>
  fetchJson<Verdict>(`/sessions/${id}/verdict`)

export const getFindings = (id: string) =>
  fetchJson<{ items: Array<{ leadWord: string; text: string }> }>(`/sessions/${id}/findings`)

export const getArguments = (id: string, stance?: string) =>
  fetchJson<{ items: Array<{ title: string; score: number; evidence: string }> }>(`/sessions/${id}/arguments${stance ? `?stance=${stance}` : ''}`)

export const getNextActions = (id: string) =>
  fetchJson<{ items: Array<{ text: string; priority: string; rationale: string }> }>(`/sessions/${id}/next-actions`)

export const getWriteups = (id: string) =>
  fetchJson<{ items: WriteupSummary[] }>(`/sessions/${id}/writeups`)

export const getMainDoc = async (id: string): Promise<string> => {
  const res = await fetch(`${BASE}/sessions/${id}/main.md`)
  return res.text()
}

export const getMetaDoc = async (id: string): Promise<string> => {
  const res = await fetch(`${BASE}/sessions/${id}/meta.md`)
  if (!res.ok) return ''
  return res.text()
}

// Roadmap
export const getBurndown = (id: string) =>
  fetchJson<BurndownData>(`/sessions/${id}/burndown`)

export const rejectDirection = (id: string, dirId: string) =>
  fetchJson(`/sessions/${id}/directions/${dirId}/reject`, { method: 'POST' })

// Chat
export const getMessages = (id: string) =>
  fetchJson<{ items: ChatMessage[] }>(`/sessions/${id}/messages`)

export async function* sendMessage(id: string, text: string): AsyncGenerator<{ type: string; data: unknown }> {
  const res = await fetch(`${BASE}/sessions/${id}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!res.body) return
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    let currentType = ''
    for (const line of lines) {
      if (line.startsWith('event: ')) currentType = line.slice(7)
      else if (line.startsWith('data: ') && currentType) {
        try { yield { type: currentType, data: JSON.parse(line.slice(6)) } } catch {}
      }
    }
  }
}
