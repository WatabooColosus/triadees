/* Grafos internos como módulo del front de Tríade.
 *
 * No interpreta nada por su cuenta: el backend ya resolvió el estado de cada
 * nodo y su color desde el código real y la base en solo lectura. Aquí sólo se
 * pinta, se navega y se abre el interior. Si un dato no llega, se muestra
 * vacío; nunca se rellena.
 */
import { useState, useEffect, useCallback, useRef } from 'react'

const GRAPHS = [
  { key: 'system', label: 'SYSTEM' },
  { key: 'organs', label: 'Órganos' },
  { key: 'vital_chain', label: 'Cadena vital' },
  { key: 'workers', label: 'Workers y tareas' },
  { key: 'tables', label: 'Tablas SQLite' },
  { key: 'entrypoints', label: 'Entrypoints' },
  { key: 'imports', label: 'Módulos e imports' },
  { key: 'calls', label: 'Llamadas' },
  { key: 'neural', label: 'Runtime neural' },
  { key: 'physical', label: 'Atlas físico' },
]

/* Por encima de esto el navegador deja de responder. El recorte se declara. */
const NODE_CAP = 900

type Node = {
  node_id: string; kind: string; label: string; state: string
  color: string; metadata: Record<string, any>
}
type Edge = { source: string; target: string; relation: string; evidence: string }
type Graph = { nodes: Node[]; edges: Edge[]; states: Record<string, number>; source?: string }
type LiveEvent = {
  source: string; row_id: number; at: string | null; graph: string
  node_id: string | null; action: string; status: string; evidence: string
}
type DebtEntry = {
  count: number; sample: string[]; evidence: string
  classified?: Record<string, { classification?: string; reason?: string }>
  contract_broken?: Record<string, any>
}
type Refresh = {
  running: boolean; stale: boolean; stale_after_seconds: number
  age_seconds: number | null; last_build_seconds: number | null
  builds: number; last_error: string | null; trigger?: string
  exit_code?: number | null; command?: string; stderr_summary?: string | null
  last_valid_artifact?: string | null; last_valid_age_seconds?: number | null
}
type Debt = {
  status: string; reason?: string; summary?: string
  debt_items_total?: number; debt_real_total?: number
  by_classification?: Record<string, number>; graphs_age_seconds?: number
  items: Record<string, DebtEntry>; refresh?: Refresh
}
type Health = {
  state: string; raw_state: string; reasons: string[]; checked_at: string
  source: string; components: Record<string, { state: string; evidence: string; last_progress?: string }>
}

export function GrafosInternos() {
  const [view, setView] = useState<string>('debt')
  const [graph, setGraph] = useState<Graph | null>(null)
  const [debt, setDebt] = useState<Debt | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [legend, setLegend] = useState<any[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<any>(null)
  const [status, setStatus] = useState('cargando…')
  const [error, setError] = useState('')
  const [actions, setActions] = useState<LiveEvent[]>([])
  const [hot, setHot] = useState<Set<string>>(new Set())
  const [pan, setPan] = useState({ x: 0, y: 0, k: 1 })
  const [camera, setCamera] = useState({ rx: -0.22, ry: 0.48 })
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<any[]>([])
  const [timelineFilter, setTimelineFilter] = useState('')
  const drag = useRef<{ x: number; y: number; rx: number; ry: number } | null>(null)

  /* Pulso vivo: acciones ocurridas y señales de SQLite, nunca la estructura.
   * Las acciones llegan por cursor, así que ninguna se pierde entre pulsos. */
  useEffect(() => {
    const source = new EventSource('/api/internal-graphs/stream')
    source.addEventListener('pulse', (ev: any) => {
      const p = JSON.parse(ev.data)
      setLegend(p.legend || [])
      const load = (p.resources?.load_average || [0])[0]
      setStatus(`vivo ${new Date(p.generated_at * 1000).toLocaleTimeString()} · ` +
        `${p.database?.tables ?? '—'} tablas · integridad ${p.database?.integrity ?? '—'} · ` +
        `carga ${Number(load).toFixed(2)}`)
      setGraph((prev) => prev ? applySignals(prev, p.signals, view) : prev)
      const incoming: LiveEvent[] = p.events || []
      if (incoming.length) {
        setActions(prev => [...incoming].reverse().concat(prev).slice(0, 200))
        /* Un nodo que acaba de actuar se marca; el destello dura un pulso. */
        setHot(new Set(incoming.map(e => e.node_id).filter(Boolean) as string[]))
        window.setTimeout(() => setHot(new Set()), 1600)
      }
    })
    source.onerror = () => setStatus('stream desconectado · reintentando')
    return () => source.close()
  }, [view])

  const loadGraph = useCallback(async (name: string) => {
    setSelected(null); setDetail(null); setError('')
    if (name === 'debt') {
      setGraph(null)
      try {
        const res = await fetch('/api/internal-graphs/debt')
        setDebt(await res.json())
      } catch (e: any) { setError(e.message || 'no se pudo leer la deuda') }
      return
    }
    if (name === 'health') {
      setGraph(null)
      try {
        const res = await fetch('/api/internal-graphs/health')
        if (!res.ok) throw new Error(`${res.status}`)
        setHealth(await res.json())
      } catch (e: any) { setError(e.message || 'no se pudo medir salud') }
      return
    }
    if (name === 'timeline') {
      setGraph(null)
      const value = timelineFilter.trim()
      const key = value.startsWith('task-') ? 'task_id' : 'run_id'
      const params = value ? `?${key}=${encodeURIComponent(value)}` : ''
      try {
        const res = await fetch(`/api/internal-graphs/timeline${params}`)
        if (!res.ok) throw new Error(`${res.status}`)
        const payload = await res.json()
        setActions(payload.events || [])
      } catch (e: any) { setError(e.message || 'no se pudo leer timeline') }
      return
    }
    try {
      const res = await fetch(`/api/internal-graphs/graph/${name}`)
      if (!res.ok) throw new Error(`${res.status}`)
      setGraph(await res.json())
    } catch (e: any) { setError(e.message || 'no se pudo leer el grafo') }
  }, [timelineFilter])

  useEffect(() => { loadGraph(view) }, [view, loadGraph])

  /* Mientras se reconstruyen los grafos se vuelve a preguntar. Sin esto la
   * regeneración termina y el panel sigue enseñando la cifra vieja hasta que
   * alguien cambia de pestaña: la acción se completaría sin verse. */
  useEffect(() => {
    if (view !== 'debt' || !debt?.refresh?.running) return
    const timer = window.setTimeout(() => loadGraph('debt'), 5000)
    return () => window.clearTimeout(timer)
  }, [view, debt, loadGraph])

  async function openNode(nodeId: string) {
    setSelected(nodeId)
    try {
      const res = await fetch(
        `/api/internal-graphs/node/${view}?node_id=${encodeURIComponent(nodeId)}`)
      setDetail(res.ok ? await res.json() : null)
    } catch { setDetail(null) }
  }

  async function search() {
    if (!query.trim()) { setResults([]); return }
    try {
      const res = await fetch(`/api/internal-graphs/search?q=${encodeURIComponent(query)}`)
      if (!res.ok) throw new Error(`${res.status}`)
      setResults((await res.json()).results || [])
    } catch (e: any) { setError(e.message || 'búsqueda fallida') }
  }

  function focusResult(result: any) {
    setView(result.graph)
    setSelected(result.node_id)
    setResults([])
    window.setTimeout(() => openNode(result.node_id), 0)
  }

  const shown = graph ? graph.nodes.slice(0, NODE_CAP) : []
  const visible = new Set(shown.map(n => n.node_id))
  const edges = graph ? graph.edges.filter(e => visible.has(e.source) && visible.has(e.target)) : []
  const positions = projectLayout(layout3d(shown), camera)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, height: '100%' }}>
      <div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
          <TabBtn active={view === 'debt'} onClick={() => setView('debt')} label="⚠ Dónde se rompe" />
          <TabBtn active={view === 'health'} onClick={() => setView('health')} label="SYSTEM HEALTH" />
          <TabBtn active={view === 'timeline'} onClick={() => setView('timeline')} label="Timeline" />
          {GRAPHS.map(g => (
            <TabBtn key={g.key} active={view === g.key} onClick={() => setView(g.key)} label={g.label} />
          ))}
        </div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 6, position: 'relative' }}>
          <input value={query} onChange={e => setQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') search() }}
            placeholder="Buscar worker, tabla, módulo, neurona, goal, task, run…"
            style={{ flex: 1, background: 'var(--bg-base)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 8px' }} />
          <button onClick={search}>Buscar</button>
          <button onClick={() => { setPan({ x: 0, y: 0, k: 1 }); setCamera({ rx: -0.22, ry: 0.48 }) }}>Reset cámara</button>
          {results.length > 0 && <div style={{ position: 'absolute', top: 34, left: 0, right: 180, zIndex: 5, background: 'var(--bg-surface)', border: '1px solid var(--border)', maxHeight: 220, overflowY: 'auto' }}>
            {results.map(r => <button key={`${r.graph}:${r.node_id}`} onClick={() => focusResult(r)} style={{ display: 'block', width: '100%', textAlign: 'left', padding: 7, background: 'transparent', color: 'var(--text-primary)', border: 0, borderBottom: '1px solid var(--border)' }}>
              {r.label} · {r.graph} · {r.state}
            </button>)}
          </div>}
        </div>
        {view === 'timeline' && <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
          <input value={timelineFilter} onChange={e => setTimelineFilter(e.target.value)} placeholder="run_id o task_id"
            style={{ flex: 1, background: 'var(--bg-base)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 6, padding: '5px 8px' }} />
          <button onClick={() => loadGraph('timeline')}>Filtrar evidencia</button>
        </div>}
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{error || status}</div>
        {legend.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 6 }}>
            {legend.map((l: any) => (
              <span key={l.state} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color: 'var(--text-muted)' }}>
                <i style={{ width: 9, height: 9, borderRadius: '50%', background: l.color, display: 'inline-block' }} />
                {l.state} — {l.meaning}
              </span>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 10, flex: 1, minHeight: 420 }}>
        <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg-surface)' }}>
          {view === 'debt'
            ? <DebtChart debt={debt} />
            : view === 'health'
              ? <HealthGrid health={health} />
              : view === 'timeline'
                ? <AccionesEnVivo actions={actions} />
            : (
              <svg
                style={{ width: '100%', height: '100%', cursor: drag.current ? 'grabbing' : 'grab' }}
                onMouseDown={e => { drag.current = { x: e.clientX, y: e.clientY, ...camera } }}
                onMouseUp={() => { drag.current = null }}
                onMouseLeave={() => { drag.current = null }}
                onMouseMove={e => {
                  if (!drag.current) return
                  if (e.shiftKey) {
                    setPan(p => ({ ...p, x: p.x + e.movementX, y: p.y + e.movementY }))
                  } else {
                    setCamera({
                      ry: drag.current.ry + (e.clientX - drag.current.x) * 0.008,
                      rx: Math.max(-1.45, Math.min(1.45,
                        drag.current.rx + (e.clientY - drag.current.y) * 0.008)),
                    })
                  }
                }}
                onWheel={e => setPan(p => ({ ...p, k: Math.min(6, Math.max(0.2, p.k * (e.deltaY < 0 ? 1.12 : 0.89))) }))}
              >
                <g transform={`translate(${pan.x},${pan.y}) scale(${pan.k})`}>
                  {edges.map((e, i) => {
                    const a = positions.get(e.source), b = positions.get(e.target)
                    if (!a || !b) return null
                    const hot = selected === e.source || selected === e.target
                    return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                      stroke={hot ? '#58a6ff' : '#484f58'}
                      strokeOpacity={Math.max(0.25, (a.depth + b.depth) / 2)}
                      strokeWidth={hot ? 2 : 0.6} />
                  })}
                  {shown.map(n => {
                    const p = positions.get(n.node_id)
                    if (!p) return null
                    const radius = (hot.has(n.node_id) ? 12 : selected === n.node_id ? 9 : 6) * p.depth
                    return <g key={n.node_id} style={{ cursor: 'pointer' }}
                      onClick={ev => { ev.stopPropagation(); openNode(n.node_id) }}
                      onDoubleClick={() => {
                        const next = String(n.metadata?.progressive_view || '')
                        if (next && next !== view) setView(next)
                      }}>
                      <circle cx={p.x} cy={p.y} r={radius}
                        fill={n.color} fillOpacity={Math.max(0.45, p.depth)}
                        stroke={hot.has(n.node_id) || selected === n.node_id ? '#fff' : '#0d1117'}
                        strokeWidth={hot.has(n.node_id) ? 2.5 : 1.5}>
                        <title>{`${n.label} · ${n.state} · doble clic para entrar`}</title>
                      </circle>
                      {view === 'system' && <text x={p.x + radius + 4} y={p.y + 4}
                        fill="var(--text-secondary)" fontSize={10}>{n.label}</text>}
                    </g>
                  })}
                </g>
              </svg>
            )}
          {!['debt', 'health', 'timeline'].includes(view) && <div style={{ position: 'absolute', margin: 8, fontSize: 10, color: 'var(--text-muted)', pointerEvents: 'none' }}>
            arrastra: girar · shift+arrastra: mover · rueda: zoom · doble clic: entrar
          </div>}
        </div>

        <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, overflowY: 'auto', background: 'var(--bg-surface)' }}>
          {view === 'debt'
            ? <DebtPanel debt={debt} />
            : view === 'health'
              ? <HealthEvidence health={health} />
              : view === 'timeline'
                ? <p style={{ color: 'var(--text-muted)', fontSize: 11 }}>Cada entrada referencia una fila persistida. El filtro no sintetiza correlaciones ausentes.</p>
            : <NodePanel graph={graph} detail={detail} shownCount={shown.length} />}
        </div>
      </div>

      {!['timeline'].includes(view) && <AccionesEnVivo actions={actions} />}
    </div>
  )
}

function HealthGrid({ health }: { health: Health | null }) {
  if (!health) return <p style={{ padding: 12, color: 'var(--text-muted)' }}>Midiendo…</p>
  return <div style={{ padding: 14, display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 10 }}>
    {Object.entries(health.components).map(([name, item]) => <div key={name} style={{ border: '1px solid var(--border)', borderRadius: 7, padding: 10 }}>
      <b>{name}</b><div style={{ color: healthColor(item.state), marginTop: 5 }}>{item.state}</div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 5 }}>{item.last_progress || 'sin timestamp disponible'}</div>
    </div>)}
  </div>
}

function HealthEvidence({ health }: { health: Health | null }) {
  if (!health) return null
  return <div style={{ fontSize: 11 }}><h3>{health.state}</h3><p>{health.reasons.join(' · ') || 'sin degradaciones'}</p>
    {Object.entries(health.components).map(([name, item]) => <div key={name} style={{ borderTop: '1px solid var(--border)', padding: '7px 0' }}><b>{name}</b><br /><code>{item.evidence}</code></div>)}
    <p style={{ color: 'var(--text-muted)' }}>fuente: {health.source}</p></div>
}

function healthColor(state: string) {
  if (state === 'healthy') return '#1b7f4b'
  if (state === 'recovering') return '#c58b1b'
  if (state === 'failed' || state === 'stalled') return '#b03030'
  return '#8b949e'
}

/* El registro de acciones es la prueba de que el grafo se mueve con el sistema
 * y no con un temporizador: cada línea es una fila real que se puede ir a ver. */
function AccionesEnVivo({ actions }: { actions: LiveEvent[] }) {
  return (
    <div style={{
      border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg-surface)',
      padding: 10, maxHeight: 190, overflowY: 'auto',
    }}>
      <h4 style={{ fontSize: 11, margin: '0 0 6px', color: 'var(--text-muted)' }}>
        ACCIONES EN VIVO {actions.length ? `· ${actions.length}` : ''}
      </h4>
      {!actions.length
        ? <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: 0 }}>
            Esperando a que el sistema actúe. Sólo se muestra lo que ocurre desde
            que abriste esta vista, nunca el historial.
          </p>
        : actions.map(a => (
          <div key={`${a.source}-${a.row_id}`} style={{
            display: 'flex', gap: 8, fontSize: 11, padding: '2px 0',
            borderBottom: '1px solid var(--border)',
          }}>
            <span style={{ color: 'var(--text-muted)', minWidth: 58 }}>
              {a.at ? a.at.slice(11, 19) : '—'}
            </span>
            <span style={{
              minWidth: 56,
              color: a.status === 'failed' ? '#b03030'
                : a.status === 'active' ? '#1b7f4b' : 'var(--text-muted)',
            }}>{a.status}</span>
            <span style={{ flex: 1 }}>{a.action}</span>
            <code style={{ color: 'var(--accent)', fontSize: 10 }}>{a.evidence}</code>
          </div>
        ))}
    </div>
  )
}

function TabBtn({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button onClick={onClick} style={{
      background: active ? 'var(--accent-glow)' : 'transparent',
      color: active ? 'var(--accent)' : 'var(--text-secondary)',
      border: '1px solid var(--border)', borderRadius: 6,
      padding: '4px 10px', fontSize: 12, cursor: 'pointer',
      fontWeight: active ? 600 : 400,
    }}>{label}</button>
  )
}

function DebtPanel({ debt }: { debt: Debt | null }) {
  if (!debt) return <p style={{ color: 'var(--text-muted)', fontSize: 12 }}>Midiendo…</p>
  if (debt.status !== 'measured') {
    return (
      <p style={{ color: 'var(--text-muted)', fontSize: 12 }}>
        No medible: {debt.reason}. Genera los grafos con
        <code> python scripts/build_internal_graphs.py</code>.
      </p>
    )
  }
  const entries = Object.entries(debt.items).sort((a, b) => b[1].count - a[1].count)
  const r = debt.refresh
  const observed = debt.debt_items_total ?? 0
  const real = debt.debt_real_total ?? observed
  const classified = Math.max(0, observed - real)
  return (
    <div style={{ fontSize: 12 }}>
      <h3 style={{ fontSize: 13, margin: '0 0 8px' }}>
        {real} elementos de deuda real · {observed} hallazgos observados
      </h3>
      <p style={{ color: 'var(--text-muted)', fontSize: 11, margin: '0 0 6px' }}>
        {classified} hallazgos tienen contrato verificado (bajo demanda, compuerta o vacío esperado) y no se cuentan como rotura.
      </p>
      <p style={{ color: 'var(--text-muted)', fontSize: 11 }}>
        grafos de hace {Math.round((debt.graphs_age_seconds || 0) / 60)} min
        {r?.running
          ? ' · reconstruyendo…'
          : r?.stale ? ' · caducados' : ' · al día'}
      </p>
      {r?.last_error && (
        <p style={{ color: 'var(--danger, #d66)', fontSize: 10, margin: '0 0 6px' }}>
          la última reconstrucción falló: {r.last_error}
        </p>
      )}
      {r?.last_error && <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>
        exit={r.exit_code ?? '—'} · {r.command || 'comando desconocido'} · último válido {r.last_valid_artifact || 'ninguno'}
        {r.last_valid_age_seconds != null ? ` (${Math.round(r.last_valid_age_seconds)} s)` : ''}
      </div>}
      {entries.map(([name, e]) => {
        const classifiedCount = Object.keys(e.classified || {}).length
        const realCount = Math.max(0, e.count - classifiedCount)
        return (
        <div key={name} style={{ padding: '7px 0', borderBottom: '1px solid var(--border)' }}>
          <b>{name.replace(/_/g, ' ')}</b> — {realCount} real / {e.count} observado(s)
          <div style={{ color: 'var(--text-muted)', fontSize: 10, margin: '3px 0' }}>{e.evidence}</div>
          {e.sample.map(s => {
            const classification = e.classified?.[s]?.classification
            return (
              <div key={s} style={{ fontSize: 10, color: 'var(--text-secondary)', wordBreak: 'break-all' }}>
                {s}{classification ? ` · ${classification}` : ' · REAL_BROKEN'}
              </div>
            )
          })}
        </div>
      )})}
    </div>
  )
}

function DebtChart({ debt }: { debt: Debt | null }) {
  if (!debt || debt.status !== 'measured') return null
  const entries = Object.entries(debt.items).sort((a, b) => b[1].count - a[1].count)
  const realCount = (e: DebtEntry) => Math.max(0, e.count - Object.keys(e.classified || {}).length)
  const max = Math.max(...entries.map(([, e]) => realCount(e)), 1)
  return (
    <svg style={{ width: '100%', height: '100%' }}>
      {entries.map(([name, e], i) => (
        <g key={name} transform={`translate(24,${28 + i * 46})`}>
          {/* La longitud es el recuento, no una estimación. */}
          <rect width={`${Math.max((realCount(e) / max) * 70, 0.5)}%`} height={26} rx={4}
            fill={realCount(e) ? '#b03030' : '#1b7f4b'} />
          <text x={8} y={18} fill="#fff" fontSize={12}>
            {realCount(e)} real  {name.replace(/_/g, ' ')}
          </text>
        </g>
      ))}
    </svg>
  )
}

function NodePanel(
  { graph, detail, shownCount }: { graph: Graph | null; detail: any; shownCount: number }
) {
  if (!graph) return <p style={{ color: 'var(--text-muted)', fontSize: 12 }}>Cargando…</p>
  return (
    <div style={{ fontSize: 12 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 10 }}>
        {Object.entries(graph.states).sort((a, b) => b[1] - a[1]).map(([state, n]) => (
          <span key={state} style={{
            fontSize: 10, padding: '2px 7px', borderRadius: 999,
            border: '1px solid var(--border)', color: 'var(--text-secondary)',
          }}>{state}: {n}</span>
        ))}
      </div>
      {graph.nodes.length > shownCount && (
        <p style={{ fontSize: 10, color: 'var(--text-muted)' }}>
          mostrando {shownCount} de {graph.nodes.length} nodos · recorte declarado
        </p>
      )}
      {!detail
        ? <p style={{ color: 'var(--text-muted)' }}>Selecciona un nodo para ver su interior.</p>
        : (
          <>
            <h3 style={{ fontSize: 13, margin: '6px 0' }}>{detail.node.label}</h3>
            <p>
              <i style={{ width: 9, height: 9, borderRadius: '50%', background: detail.node.color, display: 'inline-block', marginRight: 5 }} />
              <b>{detail.node.state}</b> · {detail.degree.out} salientes / {detail.degree.in} entrantes
            </p>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                {Object.entries(detail.node.metadata || {}).map(([k, v]) => (
                  <tr key={k}>
                    <td style={{ color: 'var(--text-muted)', paddingRight: 8, verticalAlign: 'top' }}>{k}</td>
                    <td style={{ wordBreak: 'break-all' }}>{String(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h4 style={{ fontSize: 11, margin: '12px 0 4px', color: 'var(--text-muted)' }}>
              CONEXIONES Y EVIDENCIA
            </h4>
            {[...detail.outgoing.map((e: Edge) => ({ ...e, dir: '→' })),
              ...detail.incoming.map((e: Edge) => ({ ...e, dir: '←' }))]
              .slice(0, 50).map((e: any, i: number) => (
                <div key={i} style={{ padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: 10 }}>
                  {e.dir} <b>{e.relation}</b><br />
                  {e.dir === '→' ? e.target : e.source}<br />
                  <code style={{ color: 'var(--accent)' }}>{e.evidence}</code>
                </div>
              ))}
          </>
        )}
    </div>
  )
}

/* Disposición determinista: mismo grafo, misma imagen. Se agrupa por estado en
 * anillos, de modo que lo desconectado queda visualmente separado. */
function layout3d(nodes: Node[]) {
  const groups: Record<string, Node[]> = {}
  nodes.forEach(n => { (groups[n.state] = groups[n.state] || []).push(n) })
  const positions = new Map<string, { x: number; y: number; z: number }>()
  Object.keys(groups).sort().forEach((state, si) => {
    const list = groups[state]
    const radius = 80 + si * 110
    list.forEach((n, i) => {
      const angle = (i / list.length) * Math.PI * 2 + si * 0.4
      positions.set(n.node_id, {
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
        z: (si - (Object.keys(groups).length - 1) / 2) * 95 + Math.sin(angle * 2) * 35,
      })
    })
  })
  return positions
}

function projectLayout(
  source: Map<string, { x: number; y: number; z: number }>,
  camera: { rx: number; ry: number },
) {
  const projected = new Map<string, { x: number; y: number; depth: number }>()
  source.forEach((p, id) => {
    const x1 = p.x * Math.cos(camera.ry) + p.z * Math.sin(camera.ry)
    const z1 = -p.x * Math.sin(camera.ry) + p.z * Math.cos(camera.ry)
    const y2 = p.y * Math.cos(camera.rx) - z1 * Math.sin(camera.rx)
    const z2 = p.y * Math.sin(camera.rx) + z1 * Math.cos(camera.rx)
    const perspective = Math.max(0.45, Math.min(1.55, 700 / (700 - z2)))
    projected.set(id, { x: 460 + x1 * perspective, y: 300 + y2 * perspective, depth: perspective })
  })
  return projected
}

/* Las señales sólo tocan lo que cambia en caliente: filas y ejecuciones. */
function applySignals(graph: Graph, signals: any, view: string): Graph {
  if (!signals) return graph
  let touched = false
  const nodes = graph.nodes.map(node => {
    let live: any = null
    if (view === 'vital_chain' && node.node_id.startsWith('stage:')) {
      live = signals.stages?.[node.label]
    } else if (view === 'workers' && node.node_id.startsWith('task_type:')) {
      live = signals.task_types?.[node.label]
    } else if (view === 'tables' && node.node_id.startsWith('table:')) {
      const rows = signals.tables?.[node.label]
      if (rows !== undefined && node.metadata.rows !== rows) {
        touched = true
        return { ...node, metadata: { ...node.metadata, rows } }
      }
      return node
    }
    if (!live) return node
    const next = { ...node, metadata: { ...node.metadata } }
    if (live.rows !== undefined) next.metadata.rows = live.rows
    if (live.executions !== undefined) next.metadata.executions = live.executions
    if (live.state && live.state !== node.state) { next.state = live.state; touched = true }
    return next
  })
  if (!touched) return graph
  const states: Record<string, number> = {}
  nodes.forEach(n => { states[n.state] = (states[n.state] || 0) + 1 })
  return { ...graph, nodes, states }
}
