import { useState, useEffect, useRef } from 'react'
import type { Stage, ChatMessage } from '../types'
import { getMessages, sendMessage } from '../api'
import { StageSwitcher } from './StageSwitcher'
import { Button } from './shared'
import { Md } from './Markdown'

const SUGGESTED: Record<string, string[]> = {
  design: ['Add a pro direction about…', 'Add a con direction about…', 'Tighten the rubric', 'Start the investigation'],
  run: ['Why did that worker fail?', 'Pause after this round', "What's the current tension?"],
  review: ["What's the weakest argument?", 'Summarize the verdict', 'Export the report'],
  roadmap: ['Re-rank directions', "What hasn't been covered?", 'Add 2 more rounds'],
}

export function ChatRail({ sessionId, stage, maxReached, isRunning, onStageSwitch, sessions, onSessionSwitch, onRefresh }: {
  sessionId: string
  stage: Stage
  maxReached: Stage
  isRunning: boolean
  onStageSwitch: (s: Stage) => void
  sessions: Array<{ id: string; thesis: string; stage: string }>
  onSessionSwitch: (id: string) => void
  onRefresh?: () => void
}) {
  const [showSessions, setShowSessions] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!sessionId) return
    getMessages(sessionId).then(d => setMessages(d.items.reverse()))
  }, [sessionId])

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight
  }, [messages])

  const send = async (text: string) => {
    if (!text.trim() || sending) return
    setSending(true)
    setInput('')

    const userMsg: ChatMessage = { id: Date.now().toString(), role: 'user', stage, text, createdAt: new Date().toISOString() }
    setMessages(prev => [...prev, userMsg])

    let assistantText = ''
    const assistantMsg: ChatMessage = { id: '', role: 'assistant', stage, text: '', createdAt: new Date().toISOString() }
    setMessages(prev => [...prev, assistantMsg])

    try {
      for await (const event of sendMessage(sessionId, text)) {
        if (event.type === 'message.delta') {
          const delta = (event.data as { textDelta: string }).textDelta
          assistantText += delta
          setMessages(prev => {
            const copy = [...prev]
            copy[copy.length - 1] = { ...copy[copy.length - 1], text: assistantText }
            return copy
          })
        } else if (event.type === 'message.complete') {
          const complete = event.data as { id: string; fullText: string }
          setMessages(prev => {
            const copy = [...prev]
            copy[copy.length - 1] = { ...copy[copy.length - 1], id: complete.id, text: complete.fullText }
            return copy
          })
        }
      }
    } catch (e) {
      setMessages(prev => {
        const copy = [...prev]
        copy[copy.length - 1] = { ...copy[copy.length - 1], text: 'Error: ' + (e as Error).message }
        return copy
      })
    }
    setSending(false)
    onRefresh?.()
  }

  return (
    <div className="w-80 border-r border-border bg-surface-2 flex flex-col h-full shrink-0">
      {/* Header */}
      <div className="p-4 border-b border-border flex items-center gap-3 relative">
        <div className="w-7 h-7 rounded-md bg-accent flex items-center justify-center text-white serif text-sm font-medium">A</div>
        <div className="flex-1 min-w-0 cursor-pointer" onClick={() => setShowSessions(!showSessions)}>
          <div className="text-[13px] font-semibold text-text flex items-center gap-1">
            Autoresearch
            <span className="text-text-3 text-[10px]">▼</span>
          </div>
          <div className="mono text-[11px] text-text-3 truncate">
            {sessions.find(s => s.id === sessionId)?.thesis.slice(0, 30) || sessionId.slice(0, 12)}
          </div>
        </div>
        {showSessions && (
          <div className="absolute top-full left-0 right-0 z-50 bg-surface border border-border rounded-b-lg shadow-lg max-h-80 overflow-y-auto">
            {sessions.map(s => (
              <button
                key={s.id}
                onClick={() => { onSessionSwitch(s.id); setShowSessions(false) }}
                className={`w-full text-left px-4 py-2.5 border-b border-border hover:bg-surface-2 transition-colors ${
                  s.id === sessionId ? 'bg-surface-2' : ''
                }`}
              >
                <div className="text-[12px] font-medium text-text truncate">{s.thesis}</div>
                <div className="text-[10px] text-text-3 mt-0.5">{s.stage}</div>
              </button>
            ))}
            <button
              onClick={() => { onSessionSwitch(''); setShowSessions(false) }}
              className="w-full text-left px-4 py-2.5 hover:bg-surface-2 transition-colors text-[12px] font-medium text-accent"
            >
              + New investigation
            </button>
          </div>
        )}
      </div>

      {/* Stage switcher */}
      <StageSwitcher current={stage} maxReached={maxReached} isRunning={isRunning} onSwitch={onStageSwitch} />

      {/* Divider */}
      <div className="border-t border-border" />

      {/* Messages */}
      <div ref={listRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {messages.map((msg, i) => (
          <div key={msg.id || i} className="flex gap-2">
            <div className={`w-[18px] h-[18px] rounded-md flex items-center justify-center shrink-0 mt-0.5 text-[10px] font-medium ${
              msg.role === 'assistant' ? 'bg-accent text-white' : 'bg-surface-3 text-text-2'
            }`}>
              {msg.role === 'assistant' ? 'A' : 'U'}
            </div>
            <div className="min-w-0">
              <div className="text-[11px] text-text-3 font-medium mb-0.5">
                {msg.role === 'assistant' ? 'Claude' : 'You'}
              </div>
              <div className={`text-[13.5px] leading-relaxed ${msg.role === 'assistant' ? 'serif text-sm' : ''}`}>
                {msg.text ? (
                  msg.role === 'assistant' ? <Md>{msg.text}</Md> : msg.text
                ) : <span className="text-text-3">…</span>}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Suggested chips */}
      <div className="px-4 py-2 flex flex-wrap gap-1.5">
        {(SUGGESTED[stage] || []).map(s => (
          <button
            key={s}
            onClick={() => send(s)}
            className="text-[11px] text-text-2 bg-surface border border-border rounded-full px-2.5 py-1 hover:bg-surface-2 transition-colors whitespace-nowrap"
          >
            {s}
          </button>
        ))}
      </div>

      {/* Composer */}
      <div className="p-3 border-t border-border">
        <div className="bg-surface rounded-lg border border-border p-2">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
            placeholder="Message Claude…"
            rows={2}
            className="w-full resize-none bg-transparent text-sm outline-none text-text placeholder:text-text-3"
          />
          <div className="flex justify-between items-center mt-1">
            <span className="text-[11px] text-text-3">Enter to send</span>
            <Button variant="primary" size="sm" onClick={() => send(input)} disabled={sending || !input.trim()}>
              Send
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
