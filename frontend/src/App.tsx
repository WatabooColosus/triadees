import { useState, useEffect, useRef, useCallback } from 'react'
import './index.css'

const BASE = ''

async function api(path: string, opts?: RequestInit) {
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

type Tab = 'chat' | 'system' | 'observability' | 'router' | 'models' | 'federation' | 'memory' | 'neurons'

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'chat', label: 'Chat', icon: '💬' },
  { key: 'system', label: 'Sistema', icon: '⚙' },
  { key: 'observability', label: 'Observabilidad', icon: '⌁' },
  { key: 'router', label: 'Router', icon: '🔀' },
  { key: 'models', label: 'Modelos', icon: '🧠' },
  { key: 'federation', label: 'Federación', icon: '🌐' },
  { key: 'memory', label: 'Memoria', icon: '📦' },
  { key: 'neurons', label: 'Neuronas', icon: '🧬' },
]

/* ─── Safety pending badge hook ───────────────────── */

function usePendingCount() {
  const [count, setCount] = useState(0)
  useEffect(() => {
    let mounted = true
    async function poll() {
      try {
        const res = await api('/api/safety/pending')
        if (mounted) setCount(res.count || 0)
      } catch { /* ignore */ }
    }
    poll()
    const id = setInterval(poll, 5000)
    return () => { mounted = false; clearInterval(id) }
  }, [])
  return count
}

/* ─── App ─────────────────────────────────────────── */

export default function App() {
  const [tab, setTab] = useState<Tab>(() => {
    const path = window.location.pathname.toLowerCase()
    if (path.includes('observabilidad') || path.includes('observability')) return 'observability'
    return 'chat'
  })
  const [health, setHealth] = useState<any>(null)
  const [apiKey, setApiKey] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const pendingCount = usePendingCount()

  useEffect(() => {
    api('/api/health').then(setHealth).catch(() => {})
  }, [])

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      <aside style={{
        width: sidebarOpen ? 220 : 60,
        background: 'var(--bg-surface)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        flexShrink: 0,
        transition: 'width var(--transition)',
        overflow: 'hidden',
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '16px 14px',
          borderBottom: '1px solid var(--border)',
        }}>
          <div style={{
            width: 32, height: 32, borderRadius: 10,
            background: 'linear-gradient(135deg, var(--accent), #a855f7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontWeight: 800, fontSize: 14, flexShrink: 0,
          }}>Ω</div>
          {sidebarOpen && <span style={{ fontWeight: 700, fontSize: 16, letterSpacing: '-0.3px' }}>Tríade</span>}
        </div>

        <nav style={{ flex: 1, padding: '8px 6px', display: 'flex', flexDirection: 'column', gap: 2 }}>
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)} style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '10px 10px', borderRadius: 8, border: 'none',
              background: tab === t.key ? 'var(--accent-glow)' : 'transparent',
              color: tab === t.key ? 'var(--accent)' : 'var(--text-secondary)',
              cursor: 'pointer', fontWeight: tab === t.key ? 600 : 400,
              fontSize: 13, textAlign: 'left', position: 'relative',
              transition: 'all var(--transition)',
            }}>
              <span style={{ fontSize: 16, width: 24, textAlign: 'center', flexShrink: 0 }}>{t.icon}</span>
              {sidebarOpen && <span>{t.label}</span>}
              {t.key === 'neurons' && pendingCount > 0 && (
                <span style={{
                  position: 'absolute', right: 8, top: 6,
                  background: 'var(--red)', color: '#fff', borderRadius: 10,
                  padding: '0 6px', fontSize: 10, fontWeight: 700, lineHeight: '16px',
                }}>{pendingCount}</span>
              )}
            </button>
          ))}
        </nav>

        <div style={{
          padding: '10px 8px', borderTop: '1px solid var(--border)',
          display: 'flex', flexDirection: 'column', gap: 6,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-muted)', padding: '4px 6px' }}>
            <span style={{
              width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
              background: health?.status === 'ok' ? 'var(--green)' : 'var(--red)',
            }} />
            {sidebarOpen && (health ? `${health.mode || 'ok'}` : 'connecting...')}
          </div>
          {sidebarOpen && (
            <input
              type="password" placeholder="API Key"
              value={apiKey} onChange={e => setApiKey(e.target.value)}
              style={{
                background: 'var(--bg-base)', border: '1px solid var(--border)',
                color: 'var(--text-primary)', borderRadius: 6, padding: '6px 8px',
                fontSize: 11, outline: 'none', width: '100%',
              }}
            />
          )}
          <button onClick={() => setSidebarOpen(!sidebarOpen)} style={{
            background: 'transparent', border: 'none', color: 'var(--text-muted)',
            cursor: 'pointer', fontSize: 16, padding: '4px',
          }}>
            {sidebarOpen ? '◀' : '▶'}
          </button>
        </div>
      </aside>

      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {tab === 'chat' && <ChatTab apiKey={apiKey} />}
        {tab === 'system' && <SystemTab />}
        {tab === 'observability' && <ObservabilityTab />}
        {tab === 'router' && <RouterTab />}
        {tab === 'models' && <ModelsTab />}
        {tab === 'federation' && <FederationTab apiKey={apiKey} />}
        {tab === 'memory' && <MemoryTab apiKey={apiKey} />}
        {tab === 'neurons' && <NeuronsTab apiKey={apiKey} />}
      </main>
    </div>
  )
}

/* ─── Chat ─────────────────────────────────────────── */

function ChatTab({ apiKey }: { apiKey: string }) {
  const [inputKey, setInputKey] = useState(0)
  const [messages, setMessages] = useState<{ role: string; content: string; meta?: any }[]>([
    { role: 'bot', content: 'Tríade Ω lista. Escribe un mensaje para comenzar.' },
  ])
  const [loading, setLoading] = useState(false)
  const [intent, setIntent] = useState('conversation')
  const [hypModel, setHypModel] = useState('')
  const [cenModel, setCenModel] = useState('')
  const [useOllama, setUseOllama] = useState(true)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, loading])

  async function approveRun(runId: string, idx: number) {
    try {
      const res = await api(`/api/safety/approve/${runId}`, {
        method: 'POST',
        headers: { ...(apiKey ? { 'X-TRIADE-API-Key': apiKey } : {}) },
      })
      setMessages(m => {
        const copy = [...m]
        copy[idx] = {
          role: 'bot',
          content: res.response || '(aprobado)',
          meta: { approved: true, safety: res.safety, models: res.models, run_id: runId },
        }
        return copy
      })
    } catch (e: any) {
      setMessages(m => [...m, { role: 'bot', content: `Error al aprobar: ${e.message}` }])
    }
  }

  async function rejectRun(runId: string, idx: number) {
    try {
      await api(`/api/safety/reject/${runId}`, { method: 'POST' })
      setMessages(m => {
        const copy = [...m]
        copy[idx] = { role: 'bot', content: '⛔ Run rechazado y descartado.', meta: { rejected: true } }
        return copy
      })
    } catch (e: any) {
      setMessages(m => [...m, { role: 'bot', content: `Error al rechazar: ${e.message}` }])
    }
  }

  function getText(): string {
    return inputRef.current?.value || ''
  }

  async function send() {
    const text = getText()
    if (!text.trim() || loading) return
    const userMsg = text
    setMessages(m => [...m, { role: 'user', content: userMsg }])
    setLoading(true)
    setInputKey(k => k + 1)
    const history = messages
      .filter(m => m.role !== 'bot' || m.content !== 'Tríade Ω lista. Escribe un mensaje para comenzar.')
      .filter(m => !m.meta?.pending && !m.meta?.rejected)
      .slice(-10)
      .map(m => ({ role: m.role, content: m.content }))
    const payload = {
      text: userMsg, source: 'react-ui', use_ollama: useOllama,
      hypothalamus_model: hypModel || null, central_model: cenModel || null,
      auto_select_models: !hypModel && !cenModel,
      conversation_history: history,
    }
    try {
      const res = await api('/api/run', {
        method: 'POST', body: JSON.stringify(payload),
        headers: { 'Content-Type': 'application/json', ...(apiKey ? { 'X-TRIADE-API-Key': apiKey } : {}) },
      })
      const safety = res.safety || {}
      setMessages(m => [...m, {
        role: 'bot',
        content: res.response || '(sin respuesta)',
        meta: {
          safety,
          models: res.models,
          run_id: res.run_id,
          neuron_proposal: res.neuron_proposal,
          neuron_candidate_gate: res.neuron_candidate_gate || res.memory_diff?.neuron_candidate_gate,
          response_coherence_gate: res.response_coherence_gate || res.memory_diff?.response_coherence_gate,
          post_run_learning: res.post_run_learning,
          background_candidates: res.background_neuron_candidates,
          experimental_activity: res.experimental_neuron_activity,
          autopromotions: res.memory_diff?.autopromotion_events,
          system_events: res.system_events?.filter((e: any) => e.severity !== 'info').slice(0, 5),
        },
      }])
    } catch (e: any) {
      if (e.status === 428) {
        const d = e.detail || {}
        setMessages(m => [...m, {
          role: 'bot',
          content: `⚠️ Safety requiere aprobación humana.\n\nRiesgo: ${d.risk_level}\nRazón: ${d.reason}\nID: ${d.run_id}`,
          meta: { pending: true, run_id: d.run_id, risk_level: d.risk_level, reason: d.reason, controls: d.required_controls },
        }])
      } else if (e.status === 403) {
        const d = e.detail || {}
        setMessages(m => [...m, {
          role: 'bot',
          content: `🚫 Acción bloqueada por Safety.\n\nRazón: ${d.reason || e.message}`,
          meta: { blocked: true },
        }])
      } else {
        setMessages(m => [...m, { role: 'bot', content: `Error: ${e.message}` }])
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700 }}>Chat</h2>
        <button onClick={() => setSettingsOpen(!settingsOpen)} style={{
          background: 'transparent', border: '1px solid var(--border)',
          color: 'var(--text-secondary)', borderRadius: 8, padding: '6px 12px',
          cursor: 'pointer', fontSize: 12,
        }}>
          {settingsOpen ? 'Ocultar opciones' : 'Opciones'}
        </button>
      </div>

      {settingsOpen && (
        <div style={{
          display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center',
          padding: 12, background: 'var(--bg-base)', borderRadius: 10,
          border: '1px solid var(--border)', marginBottom: 12, animation: 'fadeIn 150ms ease',
        }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 11, color: 'var(--text-muted)' }}>
            Intención
            <select value={intent} onChange={e => setIntent(e.target.value)}
              style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: 6, padding: '5px 8px', fontSize: 12, outline: 'none' }}>
              <option>conversation</option><option>analyze</option><option>memory</option><option>build_or_update</option>
            </select>
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 11, color: 'var(--text-muted)' }}>
            Hip.
            <input value={hypModel} onChange={e => setHypModel(e.target.value)} placeholder="auto"
              style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: 6, padding: '5px 8px', fontSize: 12, outline: 'none', width: 120 }} />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 11, color: 'var(--text-muted)' }}>
            Central
            <input value={cenModel} onChange={e => setCenModel(e.target.value)} placeholder="auto"
              style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: 6, padding: '5px 8px', fontSize: 12, outline: 'none', width: 120 }} />
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--text-secondary)', paddingTop: 14 }}>
            <input type="checkbox" checked={useOllama} onChange={e => setUseOllama(e.target.checked)} />
            Ollama
          </label>
        </div>
      )}

      <div style={{
        flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 12,
        padding: '12px 0',
      }}>
        {messages.map((m, i) => (
          <div key={i} style={{
            display: 'flex', gap: 10, alignItems: 'flex-start',
            animation: 'slideIn 200ms ease',
            flexDirection: m.role === 'user' ? 'row-reverse' : 'row',
          }}>
            <div style={{
              width: 32, height: 32, borderRadius: '50%', flexShrink: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 14, fontWeight: 700,
              background: m.role === 'user' ? 'linear-gradient(135deg, var(--accent), #6366f1)' : 'linear-gradient(135deg, #a855f7, #ec4899)',
              color: '#fff',
            }}>
              {m.role === 'user' ? 'U' : 'Ω'}
            </div>
            <div style={{
              maxWidth: '70%', padding: '10px 14px', borderRadius: 12,
              lineHeight: 1.5, fontSize: 14, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              background: m.meta?.pending ? 'var(--yellow-bg)' : m.meta?.blocked ? 'var(--red-bg)' : m.role === 'user' ? 'var(--accent-glow)' : 'var(--bg-surface)',
              border: m.meta?.pending ? '1px solid var(--yellow)' : m.meta?.blocked ? '1px solid var(--red)' : m.role === 'user' ? '1px solid rgba(59,130,246,0.2)' : '1px solid var(--border)',
              color: m.role === 'user' ? '#fff' : 'var(--text-primary)',
            }}>
              <div>{m.content}</div>
              {m.meta?.safety && m.meta?.safety.status && !m.meta?.pending && (
                <div style={{ marginTop: 6, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  <Badge status={m.meta.safety.status} />
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>riesgo: {m.meta.safety.risk_level}</span>
                </div>
              )}
              {m.meta?.models && (
                <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                  <span>{m.meta.models.hypothalamus?.name || '?'} → {m.meta.models.central?.name || '?'}</span>
                </div>
              )}
              {m.meta?.post_run_learning?.enabled && (
                <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 4, alignItems: 'center' }}>
                  <span>🧠 aprendizaje post-run</span>
                  <Badge status={m.meta.post_run_learning.status || 'candidate'} />
                </div>
              )}
              {m.meta?.neuron_proposal && (
                <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                  <span>🧬 neurona candidata: {m.meta.neuron_proposal.name}</span>
                </div>
              )}
              {!m.meta?.neuron_proposal && m.meta?.neuron_candidate_gate?.route === 'qualia_feedback' && (
                <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                  <span>💠 feedback positivo registrado; no se creó neurona.</span>
                </div>
              )}
              {!m.meta?.neuron_proposal && m.meta?.neuron_candidate_gate?.route === 'learning_candidate' && (
                <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                  <span>🧬 neurona no creada: pregunta factual simple; registrado como aprendizaje candidato.</span>
                </div>
              )}
              {!m.meta?.neuron_proposal && m.meta?.neuron_candidate_gate?.route === 'ignore' && (
                <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                  <span>🧬 neurona no creada; entrada sin misión operativa clara.</span>
                </div>
              )}
              {m.meta?.background_candidates?.length > 0 && (
                <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                  <span>🔄 {m.meta.background_candidates.length} candidato(s) en segundo plano</span>
                </div>
              )}
              {m.meta?.experimental_activity?.run_count > 0 && (
                <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                  <span>⚡ {m.meta.experimental_activity.run_count} neurona(s) experimental(es) ejecutadas</span>
                </div>
              )}
              {(m.meta?.autopromotions?.length || 0) > 0 && (
                <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {m.meta.autopromotions.map((ap: any, ai: number) => (
                    <div key={ai} style={{
                      fontSize: 11, padding: '4px 8px', borderRadius: 4,
                      background: 'var(--green-bg)', border: '1px solid var(--green)',
                      color: 'var(--green)',
                    }}>
                      ▲ {ap.message || `${ap.payload?.name}: ${ap.payload?.from} → ${ap.payload?.to}`}
                    </div>
                  ))}
                </div>
              )}
              {m.meta?.system_events?.length > 0 && (
                <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {m.meta.system_events.map((ev: any, ei: number) => (
                    <div key={ei} style={{
                      fontSize: 11, padding: '4px 8px', borderRadius: 4,
                      background: 'var(--bg-base)', border: '1px solid var(--border)',
                      color: ev.severity === 'error' ? 'var(--red)' : ev.severity === 'warning' ? 'var(--yellow)' : 'var(--text-muted)',
                    }}>
                      {ev.message || ev.type}
                    </div>
                  ))}
                </div>
              )}
              {m.meta?.approved && (
                <div style={{ marginTop: 6 }}><Badge status="approved" /></div>
              )}
            </div>
            {m.meta?.pending && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flexShrink: 0 }}>
                <button onClick={() => approveRun(m.meta!.run_id, i)} style={{
                  background: 'var(--green)', color: '#fff', border: 'none',
                  borderRadius: 6, padding: '6px 12px', cursor: 'pointer', fontWeight: 600, fontSize: 11,
                }}>✓ Aprobar</button>
                <button onClick={() => rejectRun(m.meta!.run_id, i)} style={{
                  background: 'transparent', color: 'var(--red)', border: '1px solid var(--red)',
                  borderRadius: 6, padding: '6px 12px', cursor: 'pointer', fontWeight: 600, fontSize: 11,
                }}>✕ Rechazar</button>
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '0 42px' }}>
            <div style={{
              display: 'flex', gap: 4, padding: '12px 16px', borderRadius: 12,
              background: 'var(--bg-surface)', border: '1px solid var(--border)',
            }}>
              {[0,1,2].map(i => (
                <div key={i} style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: 'var(--text-muted)',
                  animation: `typingDot 1.4s ${i * 0.2}s infinite`,
                }} />
              ))}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div style={{ display: 'flex', gap: 8, paddingTop: 8, borderTop: '1px solid var(--border)' }}>
        <textarea
          key={inputKey}
          ref={inputRef}
          onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send() }}
          placeholder="Escribe a Tríade…  Ctrl+Enter"
          style={{
            flex: 1, background: 'var(--bg-base)', border: '1px solid var(--border)',
            color: 'var(--text-primary)', borderRadius: 10, padding: '10px 14px',
            resize: 'none', minHeight: 48, maxHeight: 140, outline: 'none',
          }}
        />
        <button onClick={send} disabled={loading} style={{
          background: 'linear-gradient(135deg, var(--accent), #6366f1)',
          color: '#fff', border: 'none', borderRadius: 10, padding: '10px 22px',
          fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer', fontSize: 14,
          opacity: loading ? 0.6 : 1, alignSelf: 'flex-end',
        }}>
          {loading ? '...' : 'Enviar'}
        </button>
      </div>
    </div>
  )
}

/* ─── Observability ───────────────────────────────── */

function ObservabilityTab() {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')

  const fetch = useCallback(() => {
    api('/api/observability?limit=20')
      .then((payload) => { setData(payload); setError('') })
      .catch(e => setError(e.message))
  }, [])

  useEffect(() => { fetch(); const id = setInterval(fetch, 10000); return () => clearInterval(id) }, [fetch])

  if (error) return <PageError error={error} />
  if (!data) return <PageLoading />

  const workers = data.workers || {}
  const learning = data.learning || {}
  const neurons = data.neurons || {}
  const qualia = data.qualia || {}
  const federation = data.federation || {}
  const models = data.models || {}
  const errors = data.internal_errors || {}

  return (
    <Page title="Observabilidad" subtitle="Vista unificada de salud, aprendizaje, workers, neuronas y modelos">
      <Grid cols={2}>
        <Card title="Salud general" color={data.status === 'ok' ? '#22c55e' : '#eab308'}>
          <KVTable data={{ status: data.status, timestamp: data.timestamp, warnings: data.warnings, degraded_sources: data.degraded_sources }} />
        </Card>
        <Card title="Último run" color="#3b82f6">
          {data.last_run?.run_id ? <KVTable data={data.last_run} /> : <span style={{ color: 'var(--text-muted)' }}>No hay runs registrados todavía.</span>}
        </Card>
        <Card title="Workers" color={workers.active ? '#22c55e' : '#eab308'}>
          <KVTable data={{ active: workers.active, pending_tasks: workers.pending_tasks, task_counts: workers.task_counts, run_counts: workers.run_counts, last_error: workers.last_error }} />
          {!(workers.last_events || []).length && <p style={{ color: 'var(--text-muted)', marginTop: 8 }}>No hay workers activos.</p>}
        </Card>
        <Card title={`Errores (${errors.count || 0})`} color="#ef4444">
          {(errors.errors || []).length ? <ListRows items={errors.errors.slice(0, 8)} render={(e: any) => <><strong>{e.task_type || 'internal_error'}</strong><div style={{ color: 'var(--text-secondary)' }}>{e.message}</div></>} /> : <span style={{ color: 'var(--text-muted)' }}>No hay errores internos recientes.</span>}
        </Card>
        <Card title="Aprendizaje" color="#14b8a6">
          <KVTable data={{ candidates_by_status: learning.candidates_by_status, consolidated: learning.consolidated, rejected: learning.rejected }} />
          {!(learning.pending || []).length && <p style={{ color: 'var(--text-muted)', marginTop: 8 }}>No hay candidatos de aprendizaje pendientes.</p>}
        </Card>
        <Card title={`Neuronas (${neurons.summary?.total_neurons || 0})`} color="#ec4899">
          {(neurons.neurons || []).length ? <ListRows items={neurons.neurons.slice(0, 6)} render={(n: any) => <><div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><strong>{n.name}</strong><Badge status={n.status} /></div><div style={{ color: 'var(--text-secondary)' }}>{n.mission}</div><div style={{ color: 'var(--text-muted)', fontSize: 11 }}>{n.domain} · trust {n.trust_level}</div></>} /> : <span style={{ color: 'var(--text-muted)' }}>Esta neurona aún no tiene evidencia suficiente para identificarse plenamente.</span>}
        </Card>
        <Card title="Qualia" color="#a855f7">
          <KVTable data={{ latest_state: qualia.latest_state, signals: (qualia.recent_signals || []).length, experiences: (qualia.recent_experiences || []).length }} />
        </Card>
        <Card title="Federación" color="#eab308">
          <KVTable data={{ active_nodes: federation.active_count, revoked_nodes: federation.revoked_count, recent_exchanges: (federation.recent_exchanges || []).length }} />
        </Card>
        <Card title="Modelos" color={models.ollama?.ok ? '#22c55e' : '#eab308'}>
          <KVTable data={models} />
        </Card>
        <Card title="Bodega y memoria semántica" color="#3b82f6">
          <KVTable data={{ bodega: data.bodega?.counts, semantic_memory: data.semantic_memory }} />
        </Card>
      </Grid>
    </Page>
  )
}

/* ─── System ──────────────────────────────────────── */

function SystemTab() {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')

  const fetch = useCallback(() => {
    Promise.all([
      api('/api/health'), api('/api/system/pulse'), api('/api/system/life'), api('/api/system/qualia'),
    ]).then(([h, p, l, q]) => setData({ health: h, pulse: p, life: l, qualia: q }))
      .catch(e => setError(e.message))
  }, [])

  useEffect(() => { fetch(); const id = setInterval(fetch, 10000); return () => clearInterval(id) }, [fetch])

  if (error) return <PageError error={error} />
  if (!data) return <PageLoading />

  return (
    <Page title="Sistema" subtitle="Auto-refresh cada 10s">
      <Grid cols={2}>
        <Card title="Health" color="#3b82f6">
          <KVTable data={data.health} exclude={['doctor']} />
        </Card>
        <Card title="Pulse" color="#22c55e">
          <KVTable data={data.pulse} />
        </Card>
        <Card title="Life" color="#eab308">
          <KVTable data={data.life} />
        </Card>
        <Card title="Qualia" color="#a855f7">
          <KVTable data={data.qualia} />
        </Card>
      </Grid>
    </Page>
  )
}

/* ─── Router ──────────────────────────────────────── */

function RouterTab() {
  const [data, setData] = useState<any>(null)
  const [intent, setIntent] = useState('conversation')
  const [urgency, setUrgency] = useState('medium')
  const [loading, setLoading] = useState(false)

  async function consult() {
    setLoading(true)
    try { setData(await api(`/api/models/doctor?intent=${intent}&urgency=${urgency}`)) }
    catch (e: any) { setData({ error: e.message }) }
    finally { setLoading(false) }
  }
  useEffect(() => { consult() }, [])

  return (
    <Page title="Model Router" subtitle="Diagnóstico de selección de modelos">
      <div style={{ display: 'flex', gap: 8, alignItems: 'end', marginBottom: 16, flexWrap: 'wrap' }}>
        <label style={labelStyle}>Intención
          <select value={intent} onChange={e => setIntent(e.target.value)} style={selectStyle}>
            <option>conversation</option><option>analyze</option><option>memory</option><option>build_or_update</option>
          </select>
        </label>
        <label style={labelStyle}>Urgencia
          <select value={urgency} onChange={e => setUrgency(e.target.value)} style={selectStyle}>
            <option>low</option><option>medium</option><option>high</option>
          </select>
        </label>
        <button onClick={consult} disabled={loading} style={btnStyle}>
          {loading ? 'Consultando…' : 'Consultar'}
        </button>
      </div>

      {data && (
        <Grid cols={2}>
          <Card title="Hardware + Ollama" color="#14b8a6">
            <KVTable data={{ hardware: data.hardware, ollama_ok: data.ollama?.ok }} />
          </Card>
          <Card title="Decisiones" color="#3b82f6">
            {data.router?.decisions ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {Object.entries(data.router.decisions).map(([role, dec]: any) => (
                  <div key={role} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '8px 10px', background: 'var(--bg-base)', borderRadius: 8,
                    border: '1px solid var(--border)',
                  }}>
                    <span style={{ fontWeight: 600, fontSize: 12, textTransform: 'capitalize' }}>{role}</span>
                    <span style={{ fontSize: 12, color: 'var(--accent)' }}>{dec.selected_model || '—'}</span>
                    {dec.reason && <span style={{ fontSize: 11, color: 'var(--text-muted)', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{dec.reason}</span>}
                  </div>
                ))}
              </div>
            ) : (
              <KVTable data={data.router || {}} />
            )}
          </Card>
        </Grid>
      )}
    </Page>
  )
}

/* ─── Models ──────────────────────────────────────── */

function ModelsTab() {
  const [compat, setCompat] = useState<any>(null)
  const [queue, setQueue] = useState<any>(null)
  const [error, setError] = useState('')

  const fetch = useCallback(() => {
    Promise.all([
      api('/api/models/compatibility'), api('/api/models/install-queue?include_allowed=true'),
    ]).then(([c, q]) => { setCompat(c); setQueue(q) }).catch(e => setError(e.message))
  }, [])

  useEffect(() => { fetch(); const id = setInterval(fetch, 15000); return () => clearInterval(id) }, [fetch])

  if (error) return <PageError error={error} />
  if (!compat) return <PageLoading />

  return (
    <Page title="Modelos" subtitle="Compatibilidad y cola de instalación (auto-refresh 15s)">
      <Grid cols={2}>
        <Card title="Matriz de Compatibilidad" color="#a855f7">
          <KVTable data={compat.matrix || compat} />
        </Card>
        <Card title="Cola de Instalación" color="#ec4899">
          {queue?.queue?.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {(queue.queue as any[]).map((m, i) => (
                <div key={i} style={{
                  display: 'flex', justifyContent: 'space-between', gap: 8,
                  padding: '6px 10px', background: 'var(--bg-base)', borderRadius: 6,
                  border: '1px solid var(--border)', fontSize: 12,
                }}>
                  <span style={{ fontWeight: 600 }}>{m.model}</span>
                  <span style={{ color: 'var(--text-muted)' }}>prioridad {m.priority}</span>
                  <Badge status={m.status} />
                </div>
              ))}
            </div>
          ) : (
            <KVTable data={queue || {}} />
          )}
        </Card>
      </Grid>
    </Page>
  )
}

/* ─── Federation ──────────────────────────────────── */

function FederationTab({ apiKey }: { apiKey: string }) {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')

  const fetch = useCallback(() => {
    Promise.all([
      api('/api/federation/resource-lease'), api('/api/distributed-runtime/status'), api('/api/system/pulse'),
    ]).then(([lease, runtime, pulse]) => setData({ lease, runtime, pulse }))
      .catch(e => setError(e.message))
  }, [])

  useEffect(() => { fetch(); const id = setInterval(fetch, 15000); return () => clearInterval(id) }, [fetch])

  if (error) return <PageError error={error} />
  if (!data) return <PageLoading />

  return (
    <Page title="Federación" subtitle="Nodos, recursos y runtime distribuido (auto-refresh 15s)">
      <Grid cols={2}>
        <Card title="Resource Lease" color="#14b8a6">
          <KVTable data={data.lease} />
        </Card>
        <Card title="Runtime Distribuido" color="#3b82f6">
          <KVTable data={data.runtime} />
        </Card>
        <Card title="Nodos Federados" color="#22c55e">
          {data.pulse?.federation?.nodes?.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {(data.pulse.federation.nodes as any[]).map((n, i) => (
                <div key={i} style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '6px 10px', background: 'var(--bg-base)', borderRadius: 6,
                  border: '1px solid var(--border)', fontSize: 12,
                }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                    background: n.online ? 'var(--green)' : 'var(--red)' }} />
                  <span style={{ fontWeight: 600 }}>{n.node_id}</span>
                  <span style={{ color: 'var(--text-muted)', marginLeft: 'auto' }}>{n.trust_level}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{n.last_seen || ''}</span>
                </div>
              ))}
            </div>
          ) : (
            <KVTable data={data.pulse?.federation || {}} />
          )}
        </Card>
        <Card title="Transport Doctor" color="#eab308">
          <KVTable data={data.lease?.transport?.doctor || {}} />
        </Card>
      </Grid>
    </Page>
  )
}

/* ─── Memory ──────────────────────────────────────── */

function MemoryTab({ apiKey }: { apiKey: string }) {
  const [doctor, setDoctor] = useState<any>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<any>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api('/api/semantic/doctor').then(setDoctor).catch(e => setError(e.message))
  }, [])

  async function search() {
    if (!searchQuery.trim()) return
    try {
      setSearchResults(null)
      const res = await api('/api/semantic/search', {
        method: 'POST',
        body: JSON.stringify({ query: searchQuery, limit: 10, min_similarity: 0.5 }),
        headers: { 'Content-Type': 'application/json', ...(apiKey ? { 'X-TRIADE-API-Key': apiKey } : {}) },
      })
      setSearchResults(res)
    } catch (e: any) { setSearchResults({ error: e.message }) }
  }

  return (
    <Page title="Memoria Semántica" subtitle="Diagnóstico y búsqueda">
      <Grid cols={2}>
        <Card title="Doctor" color="#3b82f6">
          {doctor ? <KVTable data={doctor} /> : <p style={{ color: 'var(--text-muted)' }}>{error || 'Cargando…'}</p>}
        </Card>
        <Card title="Búsqueda" color="#a855f7">
          <div style={{ display: 'flex', gap: 6 }}>
            <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') search() }}
              placeholder="Buscar en memoria…"
              style={{ flex: 1, background: 'var(--bg-base)', border: '1px solid var(--border)',
                color: 'var(--text-primary)', borderRadius: 6, padding: '6px 10px', fontSize: 12, outline: 'none' }} />
            <button onClick={search} style={btnStyle}>Buscar</button>
          </div>
          {searchResults && (
            <div style={{ marginTop: 8 }}>
              {searchResults.error ? (
                <div style={{ color: 'var(--red)', fontSize: 12 }}>{searchResults.error}</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {(searchResults.results || searchResults).slice?.(0, 10).map((r: any, i: number) => (
                    <div key={i} style={{
                      padding: '8px 10px', background: 'var(--bg-base)', borderRadius: 6,
                      border: '1px solid var(--border)', fontSize: 12,
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span style={{ color: 'var(--accent)', fontWeight: 600 }}>{(r.similarity * 100).toFixed(0)}%</span>
                        <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{r.domain}</span>
                      </div>
                      <div style={{ color: 'var(--text-secondary)' }}>{r.content?.substring(0, 200)}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>
      </Grid>
    </Page>
  )
}

/* ─── Neurons ─────────────────────────────────────── */

function NeuronsTab({ apiKey }: { apiKey: string }) {
  const [candidates, setCandidates] = useState<any>(null)
  const [activity, setActivity] = useState<any>(null)
  const [missions, setMissions] = useState<any>(null)
  const [selectedMission, setSelectedMission] = useState<any>(null)
  const [pendingSafety, setPendingSafety] = useState<any[]>([])
  const [error, setError] = useState('')
  const [selectedNeuron, setSelectedNeuron] = useState<any>(null)

  const fetch = useCallback(() => {
    api('/api/system/neurons?limit=50').then(setCandidates).catch(e => setError(e.message))
    api('/api/system/activity').then(setActivity).catch(() => {})
    api('/api/neurons/missions?limit=20').then(setMissions).catch(() => {})
    api('/api/safety/pending').then(r => setPendingSafety(r.pending || [])).catch(() => {})
  }, [])

  useEffect(() => { fetch(); const id = setInterval(fetch, 8000); return () => clearInterval(id) }, [fetch])

  async function loadMissionDetail(missionId: number) {
    try {
      const res = await api(`/api/neuron_missions/${missionId}`)
      setSelectedMission(res)
    } catch (e: any) { setError(e.message) }
  }

  async function approveSafety(runId: string) {
    try {
      await api(`/api/safety/approve/${runId}`, { method: 'POST' })
      fetch()
    } catch (e: any) { setError(e.message) }
  }

  async function rejectSafety(runId: string) {
    try {
      await api(`/api/safety/reject/${runId}`, { method: 'POST' })
      fetch()
    } catch (e: any) { setError(e.message) }
  }

  async function loadNeuronDetail(name: string) {
    try {
      const res = await api(`/api/system/neurons/${encodeURIComponent(name)}?limit=20`)
      setSelectedNeuron(res)
    } catch (e: any) { setError(e.message) }
  }

  if (error) return <div style={{ padding: 20 }}>
    <PageError error={error} />
    <button onClick={() => setError('')} style={btnStyle}>Atrás</button>
  </div>

  if (selectedNeuron) {
    const n = selectedNeuron.neuron || {}
    const training = n.training || selectedNeuron.training || []
    const status = (n.status || '').toLowerCase()

    async function promoteTo(to: string) {
      try {
        await api(`/api/system/neurons/${encodeURIComponent(n.name)}/promote`, {
          method: 'POST', body: JSON.stringify({ status: to }),
          headers: { 'Content-Type': 'application/json', ...(apiKey ? { 'X-TRIADE-API-Key': apiKey } : {}) },
        })
        loadNeuronDetail(n.name)
      } catch (e: any) { setError(e.message) }
    }

    const p = selectedNeuron.progress || n.progress || {}

    return (
      <Page title={`Neurona: ${n.name}`} subtitle={`Dominio: ${n.domain}`}>
        <button onClick={() => setSelectedNeuron(null)} style={{ ...btnStyle, marginBottom: 12 }}>← Volver</button>
        <div style={{ marginBottom: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
          <Badge status={status} />
          {p.progress !== undefined && p.progress < 1 && (
            <div style={{ flex: 1, maxWidth: 300 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 2 }}>
                <span style={{ color: 'var(--text-muted)' }}>{p.target || p.phase}</span>
                <span style={{ color: 'var(--accent)', fontWeight: 600 }}>{(p.progress * 100).toFixed(0)}%</span>
              </div>
              <div style={{ background: 'var(--bg-base)', borderRadius: 8, height: 8, overflow: 'hidden' }}>
                <div style={{ width: `${(p.progress * 100).toFixed(0)}%`, height: '100%', background: 'var(--accent)', borderRadius: 8, transition: 'width 0.5s ease' }} />
              </div>
              {p.activation_progress !== undefined && (
                <div style={{ display: 'flex', gap: 12, marginTop: 4, fontSize: 10, color: 'var(--text-muted)' }}>
                  <span>Activaciones: {(p.activation_progress * 100).toFixed(0)}%</span>
                  <span>Diagnósticos: {(p.diagnosis_progress * 100).toFixed(0)}%</span>
                  <span>Test plans: {(p.test_plan_progress * 100).toFixed(0)}%</span>
                </div>
              )}
            </div>
          )}
          {p.progress !== undefined && p.progress >= 1 && (
            <span style={{ color: 'var(--green)', fontSize: 12, fontWeight: 600 }}>✓ {p.label}</span>
          )}
          {status === 'candidate_reviewable' && (
            <button onClick={() => promoteTo('experimental')} style={{
              background: 'var(--green)', color: '#fff', border: 'none',
              borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontWeight: 600, fontSize: 11,
            }}>▲ Promover a experimental</button>
          )}
          {status === 'experimental' && (
            <button onClick={() => promoteTo('stable')} style={{
              background: 'var(--accent)', color: '#fff', border: 'none',
              borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontWeight: 600, fontSize: 11,
            }}>★ Promover a stable</button>
          )}
          {(status === 'candidate_reviewable' || status === 'experimental') && (
            <button onClick={() => promoteTo('rejected')} style={{
              background: 'transparent', color: 'var(--red)', border: '1px solid var(--red)',
              borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontWeight: 600, fontSize: 11,
            }}>✕ Rechazar</button>
          )}
        </div>
        <Grid cols={2}>
          <Card title="Identidad" color="#a855f7">
            <KVTable data={{
              name: n.name, type: n.type, mission: n.mission, state: n.state, trust_level: n.trust_level,
              domain: n.domain, observing: n.observing, learning_state: n.learning_state,
              learned_or_attempting: n.learned_or_attempting, current_risk: n.current_risk,
              allowed_effects: n.allowed_effects, limits: n.limits, promotion_reason: n.promotion_reason,
              identity_message: n.identity_message, triade_relation: n.triade_relation, evidence_used: n.evidence_used,
            }} />
          </Card>
          <Card title={`Entrenamiento (${training.length})`} color="#3b82f6">
            {training.length ? training.map((t: any, i: number) => (
              <div key={i} style={{
                padding: '6px 8px', background: 'var(--bg-base)', borderRadius: 6,
                border: '1px solid var(--border)', fontSize: 12, marginBottom: 4,
              }}>
                <KVTable data={t} />
              </div>
            )) : <span style={{ color: 'var(--text-muted)' }}>Sin registros de entrenamiento</span>}
          </Card>
        </Grid>
      </Page>
    )
  }

  return (
    <Page title="Neuronas" subtitle="Candidatos y aprobaciones pendientes">
      {pendingSafety.length > 0 && (
        <Card title={`Safety Pendiente (${pendingSafety.length})`} color="#eab308">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {pendingSafety.map((p, i) => (
              <div key={i} style={{
                padding: '10px', background: 'var(--yellow-bg)', borderRadius: 8,
                border: '1px solid var(--yellow)', fontSize: 12,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <span style={{ fontWeight: 600 }}>{p.run_id?.slice(0, 20)}</span>
                  <Badge status={p.risk_level} />
                </div>
                <div style={{ color: 'var(--text-secondary)', marginBottom: 6 }}>{p.reason}</div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button onClick={() => approveSafety(p.run_id)} style={{
                    background: 'var(--green)', color: '#fff', border: 'none',
                    borderRadius: 6, padding: '5px 12px', cursor: 'pointer', fontWeight: 600, fontSize: 11,
                  }}>✓ Aprobar</button>
                  <button onClick={() => rejectSafety(p.run_id)} style={{
                    background: 'transparent', color: 'var(--red)', border: '1px solid var(--red)',
                    borderRadius: 6, padding: '5px 12px', cursor: 'pointer', fontWeight: 600, fontSize: 11,
                  }}>✕ Rechazar</button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
      {activity && (
        <Card title="Actividad de Fondo" color="#22c55e">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12 }}>
              <span>🔄 <strong>{activity.continuous_runner?.cycles || 0}</strong> ciclos</span>
              <span>⏱ <strong>{activity.uptime_seconds ? `${(activity.uptime_seconds / 60).toFixed(0)}m` : '—'}</strong></span>
              <span>🧬 <strong>{activity.neurons_total || 0}</strong> neuronas</span>
            </div>
            {activity.neurons_by_status && (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {Object.entries(activity.neurons_by_status).map(([s, c]) => (
                  <span key={s} style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    <Badge status={s} /> {c as number}
                  </span>
                ))}
              </div>
            )}
            {activity.promoted?.length > 0 && (
              <div style={{ fontSize: 11, color: 'var(--green)' }}>
                <strong>▲ Promovidas recientemente:</strong>
                {activity.promoted.map((p: any) => (
                  <span key={p.name} style={{ marginLeft: 8 }}>{p.name} → {p.status}</span>
                ))}
              </div>
            )}
          </div>
        </Card>
      )}
      {selectedMission && selectedMission.mission && (
        <Card title={`Misión: ${selectedMission.mission.title}`} color="#8b5cf6">
          <button onClick={() => setSelectedMission(null)} style={{ ...btnStyle, marginBottom: 8 }}>← Volver</button>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
            <div><b>Estado:</b> <Badge status={selectedMission.mission.status} /></div>
            <div><b>Dominio:</b> {selectedMission.mission.domain}</div>
            <div><b>Misión:</b> {selectedMission.mission.mission}</div>
            <div><b>Permitido:</b> {selectedMission.mission.allowed_sources?.join(', ')}</div>
            <div><b>Acciones:</b> {selectedMission.mission.allowed_actions?.join(', ')}</div>
            <div><b>Schedule:</b> {selectedMission.mission.schedule_hint}</div>
            {selectedMission.latest_score && (
              <div style={{ marginTop: 4, padding: '6px 8px', background: 'var(--bg-surface)', borderRadius: 6 }}>
                <b>Score actual:</b> {(selectedMission.latest_score.value * 100).toFixed(1)}%
                <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>
                  tipo: {selectedMission.latest_score.score_type}
                </span>
              </div>
            )}
          </div>
        </Card>
      )}
      {!selectedMission && missions && missions.missions?.length > 0 && (
        <Card title={`Misiones Neuronales (${missions.count})`} color="#8b5cf6">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {missions.missions.map((m: any) => (
              <div key={m.id} onClick={() => loadMissionDetail(m.id)} style={{
                padding: '8px 10px', background: 'var(--bg-base)', borderRadius: 6,
                border: '1px solid var(--border)', fontSize: 12, cursor: 'pointer',
                transition: 'border-color var(--transition)',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600 }}>{m.title}</span>
                  <Badge status={m.status} />
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 2 }}>
                  {m.mission?.slice(0, 80)}{m.mission?.length > 80 ? '...' : ''}
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 4, fontSize: 10, color: 'var(--text-muted)' }}>
                  <span>📂 {m.domain}</span>
                  <span>🔄 {m.schedule_hint}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
      <Card title={`Candidatos (${candidates?.neurons?.length || 0})`} color="#ec4899">
        {candidates?.neurons?.length ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {(candidates.neurons as any[]).map((n, i) => {
              const p = n.progress || {}
              return (
              <div key={i} onClick={() => loadNeuronDetail(n.name)} style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 10px', background: 'var(--bg-base)', borderRadius: 6,
                border: '1px solid var(--border)', fontSize: 12, cursor: 'pointer',
                transition: 'border-color var(--transition)',
              }}>
                <span style={{ fontWeight: 600, flex: 1 }}>{n.name}</span>
                <span style={{ color: 'var(--text-muted)', fontSize: 11, flex: 2 }}>{n.mission || n.identity_message}</span>
                <Badge status={n.status || n.state || n.activation} />
                {p.progress !== undefined && p.progress > 0 && p.progress < 1 && (
                  <div style={{ width: 60 }}>
                    <div style={{ background: 'var(--bg-surface)', borderRadius: 6, height: 6, overflow: 'hidden' }}>
                      <div style={{ width: `${(p.progress * 100).toFixed(0)}%`, height: '100%', background: 'var(--accent)', borderRadius: 6, transition: 'width 0.5s ease' }} />
                    </div>
                  </div>
                )}
                {p.progress !== undefined && p.progress >= 1 && (
                  <span style={{ color: 'var(--green)', fontSize: 11 }}>✓</span>
                )}
                <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{n.domain}</span>
              </div>
            )})}
          </div>
        ) : (
          <KVTable data={candidates || {}} />
        )}
      </Card>
    </Page>
  )
}

/* ─── Shared Components ───────────────────────────── */

function Page({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: 16, height: '100%', overflow: 'auto' }}>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 20, fontWeight: 700 }}>{title}</h2>
        {subtitle && <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 2 }}>{subtitle}</p>}
      </div>
      {children}
    </div>
  )
}

function PageLoading() {
  return (
    <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
      <div style={{ fontSize: 32, marginBottom: 8 }}>⏳</div>
      Cargando…
    </div>
  )
}

function PageError({ error }: { error: string }) {
  return (
    <div style={{ padding: 40, textAlign: 'center' }}>
      <div style={{ fontSize: 32, marginBottom: 8 }}>⚠️</div>
      <pre style={{ color: 'var(--red)', fontSize: 12 }}>{error}</pre>
    </div>
  )
}

function Card({ title, color, children }: { title: string; color?: string; children: React.ReactNode }) {
  return (
    <div style={{
      background: 'var(--bg-surface)', borderRadius: 12, border: '1px solid var(--border)',
      overflow: 'hidden', animation: 'fadeIn 200ms ease',
    }}>
      <div style={{
        padding: '10px 14px', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        {color && <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />}
        <span style={{ fontWeight: 600, fontSize: 13, color: color || 'var(--text-primary)' }}>{title}</span>
      </div>
      <div style={{ padding: 12, fontSize: 13, lineHeight: 1.6 }}>
        {children}
      </div>
    </div>
  )
}

function Grid({ cols, children }: { cols: number; children: React.ReactNode }) {
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: 12,
    }}>
      {children}
    </div>
  )
}

function ListRows({ items, render }: { items: any[]; render: (item: any, index: number) => React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {items.map((item, i) => (
        <div key={item.id || item.candidate_id || i} style={{
          padding: '8px 10px',
          background: 'var(--bg-base)',
          borderRadius: 6,
          border: '1px solid var(--border)',
          fontSize: 12,
        }}>
          {render(item, i)}
        </div>
      ))}
    </div>
  )
}

function Badge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    ok: 'var(--green)', active: 'var(--green)', online: 'var(--green)', approved: 'var(--green)',
    experimental: 'var(--yellow)', candidate: 'var(--accent)', error: 'var(--red)',
    blocked: 'var(--red)', stale: 'var(--yellow)', low: 'var(--green)',
    medium: 'var(--yellow)', high: 'var(--red)', critical: 'var(--red)',
  }
  const bgMap: Record<string, string> = {
    ok: 'var(--green-bg)', active: 'var(--green-bg)', online: 'var(--green-bg)', approved: 'var(--green-bg)',
    experimental: 'var(--yellow-bg)', candidate: 'var(--accent-glow)', error: 'var(--red-bg)',
    blocked: 'var(--red-bg)', stale: 'var(--yellow-bg)', low: 'var(--green-bg)',
    medium: 'var(--yellow-bg)', high: 'var(--red-bg)', critical: 'var(--red-bg)',
  }
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 8px', borderRadius: 12, fontSize: 11, fontWeight: 600,
      background: bgMap[status] || 'var(--bg-base)',
      color: colorMap[status] || 'var(--text-secondary)',
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: colorMap[status] || 'var(--text-muted)' }} />
      {status}
    </span>
  )
}

function KVTable({ data, exclude }: { data: any; exclude?: string[] }) {
  if (!data || typeof data !== 'object') return <span style={{ color: 'var(--text-muted)' }}>{String(data ?? '—')}</span>
  const entries = Object.entries(data).filter(([k]) => !exclude?.includes(k))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {entries.map(([k, v]) => (
        <div key={k} style={{
          display: 'flex', justifyContent: 'space-between', gap: 8,
          padding: '3px 0', borderBottom: '1px solid rgba(255,255,255,0.04)',
        }}>
          <span style={{ color: 'var(--text-muted)', fontSize: 12, textTransform: 'capitalize', flexShrink: 0 }}>
            {k.replace(/_/g, ' ')}
          </span>
          <span style={{
            fontSize: 12, textAlign: 'right', maxWidth: '60%', overflow: 'hidden',
            textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            color: typeof v === 'boolean' ? (v ? 'var(--green)' : 'var(--red)') : 'var(--text-primary)',
          }}>
            {typeof v === 'object' && v !== null ? JSON.stringify(v).slice(0, 80) : String(v ?? '—')}
          </span>
        </div>
      ))}
    </div>
  )
}

/* ─── Inline styles ───────────────────────────────── */

const labelStyle: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 2, fontSize: 11, color: 'var(--text-muted)',
}
const selectStyle: React.CSSProperties = {
  background: 'var(--bg-surface)', border: '1px solid var(--border)',
  color: 'var(--text-primary)', borderRadius: 6, padding: '5px 8px',
  fontSize: 12, outline: 'none',
}
const btnStyle: React.CSSProperties = {
  background: 'var(--accent)', color: '#fff', border: 'none',
  borderRadius: 6, padding: '7px 14px', cursor: 'pointer', fontWeight: 600,
  fontSize: 12, height: 32,
}
