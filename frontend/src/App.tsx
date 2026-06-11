import { useState, useEffect } from 'react'

const BASE = ''

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

export default function App() {
  const [tab, setTab] = useState<Tab>('chat')
  const [health, setHealth] = useState<any>(null)
  const [apiKey, setApiKey] = useState('')

  useEffect(() => {
    api('/api/health')
      .then(setHealth)
      .catch(() => {})
  }, [])

  const tabs: { key: Tab; label: string }[] = [
    { key: 'chat', label: 'Chat' },
    { key: 'system', label: 'Sistema' },
    { key: 'router', label: 'Router' },
    { key: 'models', label: 'Modelos' },
    { key: 'federation', label: 'Fed' },
    { key: 'memory', label: 'Memoria' },
    { key: 'neurons', label: 'Neuronas' },
  ]

  return (
    <div style={styles.app}>
      <header style={styles.header}>
        <div style={styles.brand}>Tríade Ω</div>
        <div style={styles.statusBar}>
          {health ? (
            <span style={{ color: health.status === 'ok' ? '#9bffb1' : '#ff6b6b' }}>
              {health.mode} · runs: {health.doctor?.counts?.runs ?? '?'}
            </span>
          ) : (
            <span style={{ color: '#9aa7bd' }}>Cargando...</span>
          )}
          <input
            style={styles.apiKeyInput}
            type="password"
            placeholder="API Key"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
      </header>

      <nav style={styles.nav}>
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              ...styles.tab,
              ...(tab === t.key ? styles.tabActive : {}),
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main style={styles.main}>
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

  async function send() {
    if (!text.trim() || loading) return
    const userMsg = text
    setMessages((m) => [...m, { role: 'user', content: userMsg }])
    setLoading(true)
    // Build conversation history from non-greeting messages
    const history = messages
      .filter((m) => m.role !== 'bot' || m.content !== 'Tríade Ω lista. Escribe un mensaje para comenzar.')
      .slice(-10)
      .map((m) => ({ role: m.role, content: m.content }))
    const payload = {
      text: userMsg,
      source: 'react-ui',
      use_ollama: useOllama,
      hypothalamus_model: hypModel || null,
      central_model: cenModel || null,
      auto_select_models: !hypModel && !cenModel,
      conversation_history: history,
    }
    try {
      const res = await api('/api/run', {
        method: 'POST',
        body: JSON.stringify(payload),
        headers: {
          'Content-Type': 'application/json',
          ...(apiKey ? { 'X-TRIADE-API-Key': apiKey } : {}),
        },
      })
      setMessages((m) => [
        ...m,
        {
          role: 'bot',
          content: res.response || '(sin respuesta)',
        },
      ])
    } catch (e: any) {
      setMessages((m) => [...m, { role: 'bot', content: `Error: ${e.message}` }])
    } finally {
      setLoading(false)
      setText('')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', gap: 8, padding: '8px 0', flexWrap: 'wrap', alignItems: 'center' }}>
        <label style={styles.label}>Intención
          <select value={intent} onChange={(e) => setIntent(e.target.value)} style={styles.select}>
            <option>conversation</option><option>analyze</option><option>memory</option><option>build_or_update</option>
          </select>
        </label>
        <label style={styles.label}>Hipotálamo
          <input value={hypModel} onChange={(e) => setHypModel(e.target.value)} style={styles.inputS} placeholder="auto" />
        </label>
        <label style={styles.label}>Central
          <input value={cenModel} onChange={(e) => setCenModel(e.target.value)} style={styles.inputS} placeholder="auto" />
        </label>
        <label style={{ ...styles.label, flexDirection: 'row', gap: 4 }}>
          <input type="checkbox" checked={useOllama} onChange={(e) => setUseOllama(e.target.checked)} />
          Ollama
        </label>
      </div>
      <div style={styles.chatBox}>
        {messages.map((m, i) => (
          <div key={i} style={{ ...styles.msg, alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start', background: m.role === 'user' ? '#1f6feb' : '#171f2e' }}>
            {m.content}
          </div>
        ))}
        {loading && <div style={styles.msg}>...</div>}
      </div>
      <div style={{ display: 'flex', gap: 8, padding: '10px 0' }}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send() }}
          style={styles.textarea}
          placeholder="Escribe a Tríade... Ctrl+Enter"
        />
        <button onClick={send} disabled={loading} style={styles.sendBtn}>Enviar</button>
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
      api('/api/health'),
      api('/api/system/pulse'),
      api('/api/system/life'),
      api('/api/system/qualia'),
    ])
      .then(([h, p, l, q]) => setData({ health: h, pulse: p, life: l, qualia: q }))
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <pre style={styles.pre}>Error: {error}</pre>
  if (!data) return <p>Cargando...</p>

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, height: '100%', overflow: 'auto' }}>
      <Section title="Health">
        <pre style={styles.pre}>{JSON.stringify(data.health, null, 2)}</pre>
      </Section>
      <Section title="Pulse">
        <pre style={styles.pre}>{JSON.stringify(data.pulse, null, 2)}</pre>
      </Section>
      <Section title="Life">
        <pre style={styles.pre}>{JSON.stringify(data.life, null, 2)}</pre>
      </Section>
      <Section title="Qualia">
        <pre style={styles.pre}>{JSON.stringify(data.qualia, null, 2)}</pre>
      </Section>
    </div>
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
    try {
      setData(await api(`/api/models/doctor?intent=${intent}&urgency=${urgency}`))
    } catch (e: any) {
      setData({ error: e.message })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { consult() }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'end' }}>
        <label style={styles.label}>Intención
          <select value={intent} onChange={(e) => setIntent(e.target.value)} style={styles.select}>
            <option>conversation</option><option>analyze</option><option>memory</option><option>build_or_update</option>
          </select>
        </label>
        <label style={styles.label}>Urgencia
          <select value={urgency} onChange={(e) => setUrgency(e.target.value)} style={styles.select}>
            <option>low</option><option>medium</option><option>high</option>
          </select>
        </label>
        <button onClick={consult} disabled={loading} style={styles.btn}>Consultar</button>
      </div>
      {data && (
        <>
          <Section title="Hardware + Ollama">
            <pre style={styles.pre}>{JSON.stringify({ hardware: data.hardware, ollama: data.ollama?.ok }, null, 2)}</pre>
          </Section>
          <Section title="Decisiones">
            {data.router?.decisions ? (
              <table style={styles.table}>
                <thead><tr><th>Rol</th><th>Modelo</th><th>Motivo</th></tr></thead>
                <tbody>
                  {Object.entries(data.router.decisions).map(([role, dec]: any) => (
                    <tr key={role}>
                      <td style={{ fontWeight: 700 }}>{role}</td>
                      <td>{dec.selected_model || '—'}</td>
                      <td style={{ fontSize: 12, color: '#9aa7bd' }}>{dec.reason || ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <pre style={styles.pre}>{JSON.stringify(data.router, null, 2)}</pre>
            )}
          </Section>
        </>
      )}
    </div>
  )
}

/* ─── Models ──────────────────────────────────────── */

function ModelsTab() {
  const [compat, setCompat] = useState<any>(null)
  const [queue, setQueue] = useState<any>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([
      api('/api/models/compatibility'),
      api('/api/models/install-queue?include_allowed=true'),
    ])
      .then(([c, q]) => { setCompat(c); setQueue(q) })
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <pre style={styles.pre}>Error: {error}</pre>
  if (!compat) return <p>Cargando...</p>

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, height: '100%', overflow: 'auto' }}>
      <Section title="Compatibilidad">
        <pre style={styles.pre}>{JSON.stringify(compat.matrix || compat, null, 2)}</pre>
      </Section>
      <Section title="Cola de Instalación">
        {queue?.queue ? (
          <table style={styles.table}>
            <thead><tr><th>Modelo</th><th>Prioridad</th><th>Estado</th></tr></thead>
            <tbody>
              {queue.queue.map((m: any, i: number) => (
                <tr key={i}><td>{m.model}</td><td>{m.priority}</td><td>{m.status}</td></tr>
              ))}
            </tbody>
          </table>
        ) : (
          <pre style={styles.pre}>{JSON.stringify(queue, null, 2)}</pre>
        )}
      </Section>
    </div>
  )
}

/* ─── Federation ──────────────────────────────────── */

function FederationTab({ apiKey }: { apiKey: string }) {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([
      api('/api/federation/resource-lease'),
      api('/api/distributed-runtime/status'),
      api('/api/system/pulse'),
    ])
      .then(([lease, runtime, pulse]) => setData({ lease, runtime, pulse }))
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <pre style={styles.pre}>Error: {error}</pre>
  if (!data) return <p>Cargando...</p>

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, height: '100%', overflow: 'auto' }}>
      <Section title="Resource Lease">
        <pre style={styles.pre}>{JSON.stringify(data.lease, null, 2)}</pre>
      </Section>
      <Section title="Runtime Distribuido">
        <pre style={styles.pre}>{JSON.stringify(data.runtime, null, 2)}</pre>
      </Section>
      <Section title="Nodos Federados (Pulse)">
        {data.pulse?.federation?.nodes ? (
          <table style={styles.table}>
            <thead><tr><th>Nodo</th><th>Online</th><th>Trust</th><th>Last Seen</th></tr></thead>
            <tbody>
              {data.pulse.federation.nodes.map((n: any, i: number) => (
                <tr key={i}>
                  <td style={{ fontWeight: 700 }}>{n.node_id}</td>
                  <td>{n.online ? '✅' : '❌'}</td>
                  <td>{n.trust_level}</td>
                  <td style={{ fontSize: 11 }}>{n.last_seen}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <pre style={styles.pre}>{JSON.stringify(data.pulse?.federation, null, 2)}</pre>
        )}
      </Section>
      <Section title="Transport Doctor">
        {data.lease?.transport?.doctor && (
          <pre style={styles.pre}>{JSON.stringify(data.lease.transport.doctor, null, 2)}</pre>
        )}
      </Section>
    </div>
  )
}

/* ─── Memory ──────────────────────────────────────── */

function MemoryTab({ apiKey }: { apiKey: string }) {
  const [doctor, setDoctor] = useState<any>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<any>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api('/api/semantic/doctor')
      .then(setDoctor)
      .catch((e) => setError(e.message))
  }, [])

  async function search() {
    if (!searchQuery.trim()) return
    try {
      setSearchResults(null)
      const res = await api('/api/semantic/search', {
        method: 'POST',
        body: JSON.stringify({ query: searchQuery, limit: 10, min_similarity: 0.5 }),
        headers: {
          'Content-Type': 'application/json',
          ...(apiKey ? { 'X-TRIADE-API-Key': apiKey } : {}),
        },
      })
      setSearchResults(res)
    } catch (e: any) {
      setSearchResults({ error: e.message })
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, height: '100%', overflow: 'auto' }}>
      <Section title="Doctor Memoria Semántica">
        {doctor ? (
          <pre style={styles.pre}>{JSON.stringify(doctor, null, 2)}</pre>
        ) : (
          <p>{error || 'Cargando...'}</p>
        )}
      </Section>
      <Section title="Búsqueda Semántica">
        <div style={{ display: 'flex', gap: 8 }}>
          <input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') search() }}
            style={{ ...styles.inputS, flex: 1 }} placeholder="Buscar en memoria..." />
          <button onClick={search} style={styles.btn}>Buscar</button>
        </div>
        {searchResults && (
          <div style={{ marginTop: 8 }}>
            {searchResults.error ? (
              <pre style={styles.pre}>{searchResults.error}</pre>
            ) : (
              <table style={styles.table}>
                <thead><tr><th>Score</th><th>Contenido</th><th>Dominio</th></tr></thead>
                <tbody>
                  {(searchResults.results || searchResults).slice?.(0, 10).map((r: any, i: number) => (
                    <tr key={i}>
                      <td>{(r.similarity * 100).toFixed(0)}%</td>
                      <td style={{ fontSize: 12, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {r.content?.substring(0, 120)}
                      </td>
                      <td style={{ fontSize: 11 }}>{r.domain}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </Section>
    </div>
  )
}

/* ─── Neurons ─────────────────────────────────────── */

function NeuronsTab({ apiKey }: { apiKey: string }) {
  const [candidates, setCandidates] = useState<any>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api('/api/system/neurons?limit=50')
      .then(setCandidates)
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <pre style={styles.pre}>Error: {error}</pre>

  return (
    <div style={{ height: '100%', overflow: 'auto' }}>
      <Section title="Neuronas / Candidatos">
        {candidates ? (
          <pre style={styles.pre}>{JSON.stringify(candidates, null, 2)}</pre>
        ) : (
          <p>Cargando...</p>
        )}
      </Section>
    </div>
  )
}

/* ─── Helpers ─────────────────────────────────────── */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={styles.section}>
      <div style={styles.sectionTitle}>{title}</div>
      {children}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  app: {
    background: '#090b10',
    color: '#edf2ff',
    fontFamily: 'Inter, system-ui, sans-serif',
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'column',
    padding: 12,
    gap: 8,
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '8px 12px',
    background: '#121722',
    borderRadius: 12,
    border: '1px solid #263246',
  },
  brand: { fontSize: 22, fontWeight: 800, letterSpacing: '-0.5px' },
  statusBar: { display: 'flex', gap: 12, alignItems: 'center', fontSize: 13 },
  apiKeyInput: {
    background: '#171f2e',
    border: '1px solid #263246',
    color: '#edf2ff',
    borderRadius: 8,
    padding: '6px 10px',
    fontSize: 12,
    width: 120,
    outline: 'none',
  },
  nav: { display: 'flex', gap: 4, padding: '4px 0' },
  tab: {
    background: 'transparent',
    color: '#9aa7bd',
    border: 'none',
    padding: '8px 16px',
    borderRadius: 8,
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 600,
  },
  tabActive: { background: '#1f6feb', color: '#fff' },
  main: {
    flex: 1,
    background: '#121722',
    borderRadius: 12,
    border: '1px solid #263246',
    padding: 16,
    overflow: 'auto',
    minHeight: 0,
  },
  chatBox: {
    flex: 1,
    overflow: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
    padding: '8px 0',
  },
  msg: {
    maxWidth: '80%',
    padding: '12px 14px',
    borderRadius: 16,
    lineHeight: 1.45,
    whiteSpace: 'pre-wrap',
    fontSize: 14,
  },
  textarea: {
    flex: 1,
    background: '#171f2e',
    border: '1px solid #263246',
    color: '#edf2ff',
    borderRadius: 10,
    padding: 10,
    resize: 'none',
    minHeight: 48,
    outline: 'none',
    fontFamily: 'inherit',
  },
  sendBtn: {
    background: 'linear-gradient(135deg,#73c7ff,#9bffb1)',
    color: '#061018',
    border: 'none',
    borderRadius: 10,
    padding: '10px 24px',
    fontWeight: 700,
    cursor: 'pointer',
  },
  label: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    fontSize: 11,
    color: '#9aa7bd',
  },
  select: { background: '#171f2e', border: '1px solid #263246', color: '#edf2ff', borderRadius: 8, padding: '6px 8px', fontSize: 12, outline: 'none' },
  inputS: { background: '#171f2e', border: '1px solid #263246', color: '#edf2ff', borderRadius: 8, padding: '6px 8px', fontSize: 12, outline: 'none', width: 140 },
  btn: { background: '#1f6feb', color: '#fff', border: 'none', borderRadius: 8, padding: '8px 16px', cursor: 'pointer', fontWeight: 600, fontSize: 13 },
  section: { background: '#0d121c', border: '1px solid #263246', borderRadius: 10, padding: 12 },
  sectionTitle: { fontSize: 13, fontWeight: 700, color: '#8fd3ff', marginBottom: 8, textTransform: 'uppercase' as const, letterSpacing: '0.5px' },
  pre: { fontSize: 11, color: '#cbd6ea', whiteSpace: 'pre-wrap', wordBreak: 'break-all' as const, margin: 0, lineHeight: 1.4 },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 12 },
}
