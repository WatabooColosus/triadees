import { useState, useEffect, useRef, useCallback } from 'react'

const BASE = ''
const POLL_INTERVAL = 5000

export async function api(path: string, opts?: RequestInit) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    if (res.status === 428) {
      const body = await res.json().catch(() => ({}))
      const err: any = new Error(body.detail?.error || res.statusText)
      err.status = res.status
      err.detail = body.detail || body
      throw err
    }
    const text = await res.text().catch(() => res.statusText)
    const err: any = new Error(`${res.status}: ${text}`)
    err.status = res.status
    throw err
  }
  return res.json()
}

export interface DashboardData {
  status: string
  generated_at: string
  refresh_hint_seconds: number
  heartbeat?: any
  ollama_blood?: any
  observability?: any
  bodega_summary?: any
  learning_journal?: any
  technical_debt?: any
  git_status?: any
  workers?: any
  runtime_events?: any[]
  system_processes?: any
  autonomy_delegation?: any
  errors?: { block: string; error: string }[]
  policy?: any
}

export function useLiveDashboard(): {
  data: DashboardData | null
  loading: boolean
  error: string
  lastUpdated: string
  refresh: () => void
} {
  const [data, setData] = useState<DashboardData | null>(null)
  const [lastGoodData, setLastGoodData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [lastUpdated, setLastUpdated] = useState('')
  const mountedRef = useRef(true)

  const fetch = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api('/api/ui/react-dashboard')
      if (mountedRef.current) {
        setData(res)
        setLastGoodData(res)
        setError('')
        setLastUpdated(new Date().toLocaleTimeString())
      }
    } catch (e: any) {
      if (mountedRef.current) {
        setError(e.message)
        // keep lastGoodData — it's already set
      }
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    fetch()
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') fetch()
    }, POLL_INTERVAL)
    return () => { mountedRef.current = false; clearInterval(id) }
  }, [fetch])

  return { data: data || lastGoodData, loading, error, lastUpdated, refresh: fetch }
}
