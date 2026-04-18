import { useEffect, useRef, useState } from 'react'
import type { Worker, ActivityEntry } from '../types'
import { getWorkers, getActivity, openStream } from '../api'

export function useRunState(sessionId: string | null, isRunning: boolean) {
  const [workers, setWorkers] = useState<Worker[]>([])
  const [activity, setActivity] = useState<ActivityEntry[]>([])
  const [round, setRound] = useState(0)
  const [tension, setTension] = useState({ pro: 50, con: 50 })
  const [cost, setCost] = useState(0)
  const [tokens, setTokens] = useState(0)
  const [stallStreak, setStallStreak] = useState(0)
  const closeRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    if (!sessionId) return
    getWorkers(sessionId).then(d => {
      setWorkers(d.workers)
      setRound(d.round)
      setTension(d.tension)
      setCost(d.cost)
      setTokens(d.tokens)
      setStallStreak(d.stallStreak)
    }).catch(() => {})
    getActivity(sessionId).then(d => setActivity(d.items)).catch(() => {})
  }, [sessionId])

  // Poll worker snapshot every 3s while running
  useEffect(() => {
    if (!sessionId || !isRunning) return
    const interval = setInterval(() => {
      getWorkers(sessionId).then(d => {
        setWorkers(d.workers)
        setRound(d.round)
        setTension(d.tension)
        setCost(d.cost)
        setTokens(d.tokens)
        setStallStreak(d.stallStreak)
      }).catch(() => {})
      getActivity(sessionId).then(d => {
        if (d.items.length > 0) setActivity(d.items)
      }).catch(() => {})
    }, 3000)
    return () => clearInterval(interval)
  }, [sessionId, isRunning])

  useEffect(() => {
    if (!sessionId || !isRunning) return
    const close = openStream(sessionId, (type, data) => {
      if (type === 'worker.update') {
        const w = data as Worker
        setWorkers(prev => {
          const idx = prev.findIndex(x => x.id === w.id)
          if (idx >= 0) {
            const copy = [...prev]
            copy[idx] = w
            return copy
          }
          return [...prev, w]
        })
      }
      if (type === 'activity') {
        const a = data as ActivityEntry
        setActivity(prev => [a, ...prev].slice(0, 50))
      }
      if (type === 'round.start') {
        const d = data as { round: number }
        setRound(d.round)
      }
      if (type === 'round.complete') {
        const d = data as { tension?: { pro: number; con: number }; cost?: number }
        if (d.tension) setTension(d.tension)
        if (d.cost) setCost(d.cost)
      }
      if (type === 'stall.update') {
        const d = data as { stallStreak: number }
        setStallStreak(d.stallStreak)
      }
      if (type === 'judge.score') {
        getWorkers(sessionId).then(d => {
          setWorkers(d.workers)
          setTension(d.tension)
          setCost(d.cost)
          setTokens(d.tokens)
        }).catch(() => {})
      }
    })
    closeRef.current = close
    return () => close()
  }, [sessionId, isRunning])

  return { workers, activity, round, tension, cost, tokens, stallStreak }
}
