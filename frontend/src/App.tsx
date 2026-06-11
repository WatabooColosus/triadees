import { useState, useEffect, useRef } from 'react'
import './index.css'

const BASE = ''
const COLORS = ['#3b82f6', '#22c55e', '#eab308', '#ef4444', '#a855f7', '#ec4899', '#14b8a6']

async function api(path: string, opts?: RequestInit) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json()
}

type Tab = 'chat' | 'system' | 'router' | 'models' | 'federation' | 'memory' | 'neurons'

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'chat', label: 'Chat', icon: '💬' },
  { key: 'system', label: 'Sistema', icon: '⚙' },
  { key: 'router', label: 'Router', icon: '🔀' },
  { key: 'models', label: 'Modelos', icon: '🧠' },
  { key: 'federation', label: 'Federación', icon: '🌐' },
  { key: 'memory', label: 'Memoria', icon: '📦' },
  { key: 'neurons', label: 'Neuronas', icon: '🧬' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('chat')
  const [health, setHealth] = useState<any>(null)
  const [apiKey, setApiKey] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(true)

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
              fontSize: 13, textAlign: 'left',
              transition: 'all var(--transition)',
            }}>
              <span style={{ fontSize: 16, width: 24, textAlign: 'center', flexShrink: 0 }}>{t.icon}</span>
              {sidebarOpen && <span>{t.label}</span>}
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
  const [text, setText] = useState('')
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([
    { role: 'bot', content: 'Tríade Ω lista. Escribe un mensaje para comenzar.' },
  ])
  const [loading, setLoading] = useState(false)
  const [intent, setIntent] = useState('conversation')
  const [hypModel, setHypModel] = useState('qwen2.5:3b-instruct')
  const [cenModel, setCenModel] = useState('qwen2.5:3b-instruct')
  const [useOllama, setUseOllama] = useState(true)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, loading])

  async function send() {
    if (!text.trim() || loading) return
    const userMsg = text
    setMessages(m => [...m, { role: 'user', content: userMsg }])
    setLoading(true)
    const history = messages
      .filter(m => m.role !== 'bot' || m.content !== 'Tríade Ω lista. Escribe un mensaje para comenzar.')
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
      setMessages(m => [...m, { role: 'bot', content: res.response || '(sin respuesta)' }])
    } catch (e: any) {
      setMessages(m => [...m, { role: 'bot', content: `Error: ${e.message}` }])
    } finally {
      setLoading(false)
      setText('')
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
              background: m.role === 'user' ? 'var(--accent-glow)' : 'var(--bg-surface)',
              border: m.role === 'user' ? '1px solid rgba(59,130,246,0.2)' : '1px solid var(--border)',
              color: m.role === 'user' ? '#fff' : 'var(--text-primary)',
            }}>
              {m.content}
            </div>
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
          value={text} onChange={e => setText(e.target.value)}
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

/* ─── System ──────────────────────────────────────── */

function SystemTab() {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    Promise.all([
      api('/api/health'), api('/api/system/pulse'), api('/api/system/life'), api('/api/system/qualia'),
    ]).then(([h, p, l, q]) => setData({ health: h, pulse: p, life: l, qualia: q }))
      .catch(e => setError(e.message))
  }, [])

  if (error) return <PageError error={error} />
  if (!data) return <PageLoading />

  return (
    <Page title="Sistema">
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
  useEffect(() => {
    Promise.all([
      api('/api/models/compatibility'), api('/api/models/install-queue?include_allowed=true'),
    ]).then(([c, q]) => { setCompat(c); setQueue(q) }).catch(e => setError(e.message))
  }, [])

  if (error) return <PageError error={error} />
  if (!compat) return <PageLoading />

  return (
    <Page title="Modelos" subtitle="Compatibilidad y cola de instalación">
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
  useEffect(() => {
    Promise.all([
      api('/api/federation/resource-lease'), api('/api/distributed-runtime/status'), api('/api/system/pulse'),
    ]).then(([lease, runtime, pulse]) => setData({ lease, runtime, pulse }))
      .catch(e => setError(e.message))
  }, [])

  if (error) return <PageError error={error} />
  if (!data) return <PageLoading />

  return (
    <Page title="Federación" subtitle="Nodos, recursos y runtime distribuido">
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
  const [error, setError] = useState('')
  useEffect(() => {
    api('/api/system/neurons?limit=50').then(setCandidates).catch(e => setError(e.message))
  }, [])

  if (error) return <PageError error={error} />
  return (
    <Page title="Neuronas" subtitle="Candidatos registrados">
      <Card title={`Candidatos (${candidates?.neurons?.length || 0})`} color="#ec4899">
        {candidates?.neurons?.length ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {(candidates.neurons as any[]).map((n, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 10px', background: 'var(--bg-base)', borderRadius: 6,
                border: '1px solid var(--border)', fontSize: 12,
              }}>
                <span style={{ fontWeight: 600, flex: 1 }}>{n.name}</span>
                <Badge status={n.status} />
                <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{n.domain}</span>
              </div>
            ))}
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

function Badge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    ok: 'var(--green)', active: 'var(--green)', online: 'var(--green)',
    experimental: 'var(--yellow)', candidate: 'var(--accent)', error: 'var(--red)',
    blocked: 'var(--red)', stale: 'var(--yellow)',
  }
  const bgMap: Record<string, string> = {
    ok: 'var(--green-bg)', active: 'var(--green-bg)', online: 'var(--green-bg)',
    experimental: 'var(--yellow-bg)', candidate: 'var(--accent-glow)', error: 'var(--red-bg)',
    blocked: 'var(--red-bg)', stale: 'var(--yellow-bg)',
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

/* ─── Inline styles for select/input reuse ────────── */

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
