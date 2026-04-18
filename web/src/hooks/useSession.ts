import { useState, useEffect, useCallback, useRef } from 'react'
import type { Session, Stage, SessionConfig, Direction } from '../types'
import { getSession, getConfig, getDirections, openStream } from '../api'

export function useSession(sessionId: string | null) {
  const [session, setSession] = useState<Session | null>(null)
  const [config, setConfig] = useState<SessionConfig | null>(null)
  const [directions, setDirections] = useState<Direction[]>([])
  const [stage, setStage] = useState<Stage>('design')
  const [maxReached, setMaxReached] = useState<Stage>('design')
  const [isRunning, setIsRunning] = useState(false)
  const [loading, setLoading] = useState(false)
  const closeStream = useRef<(() => void) | null>(null)

  const STAGE_ORDER: Stage[] = ['design', 'run', 'review', 'roadmap']

  const refresh = useCallback(async () => {
    if (!sessionId) return
    setLoading(true)
    try {
      const [s, c, d] = await Promise.all([
        getSession(sessionId),
        getConfig(sessionId),
        getDirections(sessionId),
      ])
      setSession(s)
      setConfig(c)
      setDirections(d.items)
      const inferredStage = (s.stage || 'design') as Stage
      setStage(inferredStage)
      const idx = STAGE_ORDER.indexOf(inferredStage)
      if (idx > STAGE_ORDER.indexOf(maxReached)) {
        setMaxReached(inferredStage)
      }
      setIsRunning(s.run !== undefined && s.stage === 'run')
    } catch (e) {
      console.error('Failed to load session:', e)
    }
    setLoading(false)
  }, [sessionId])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    if (!sessionId) return
    const close = openStream(sessionId, (type, data) => {
      if (type === 'stage') {
        const d = data as { stage: string }
        const newStage = d.stage as Stage
        setStage(newStage)
        setMaxReached(prev => {
          const newIdx = STAGE_ORDER.indexOf(newStage)
          const prevIdx = STAGE_ORDER.indexOf(prev)
          return newIdx > prevIdx ? newStage : prev
        })
      }
      if (type === 'run.complete') {
        setIsRunning(false)
        refresh()
      }
      if (type === 'round.start') {
        setIsRunning(true)
      }
    })
    closeStream.current = close
    return () => close()
  }, [sessionId, refresh])

  // Auto-refresh config/directions on design stage (chat may add directions)
  useEffect(() => {
    if (!sessionId || stage !== 'design') return
    const interval = setInterval(() => {
      Promise.all([
        getConfig(sessionId),
        getDirections(sessionId),
      ]).then(([c, d]) => {
        setConfig(c)
        setDirections(d.items)
      }).catch(() => {})
    }, 5000)
    return () => clearInterval(interval)
  }, [sessionId, stage])

  const switchStage = useCallback((s: Stage) => {
    const idx = STAGE_ORDER.indexOf(s)
    const maxIdx = STAGE_ORDER.indexOf(maxReached)
    if (idx <= maxIdx) setStage(s)
  }, [maxReached])

  return { session, config, directions, stage, maxReached, isRunning, loading, switchStage, refresh }
}
