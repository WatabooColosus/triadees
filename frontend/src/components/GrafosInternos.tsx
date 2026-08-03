/* Grafos internos como módulo del front de Tríade.
 *
 * No interpreta nada por su cuenta: el backend ya resolvió el estado de cada
 * nodo y su color desde el código real y la base en solo lectura. Aquí sólo se
 * pinta, se navega y se abre el interior. Si un dato no llega, se muestra
 * vacío; nunca se rellena.
 */
import { useState, useEffect, useCallback, useRef } from 'react'

const GRAPHS = [
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
type DebtEntry = { count: number; sample: string[]; evidence: string }
type Debt = {
  status: string; reason?: string; summary?: string
  debt_items_total?: number; graphs_age_seconds?: number
  items: Record<string, DebtEntry>
}

export function GrafosInternos() {
  const [view, setView] = useState<string>('debt')
  const [graph, setGraph] = useState<Graph | null>(null)
  const [debt, setDebt] = useState<Debt | null>(null)
  const [legend, setLegend] = useState<any[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<any>(null)
  const [status, setStatus] = useState('cargando…')
  const [error, setError] = useState('')
  const [actions, setActions] = useState<LiveEvent[]>([])
  const [hot, setHot] = useState<Set<string>>(new Set())
  const [pan, setPan] = useState({ x: 0, y: 0, k: 1 })
  const drag = useRef<{ x: number; y: number } | null>(null)

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
    try {
      const res = await fetch(`/api/internal-graphs/graph/${name}`)
      if (!res.ok) throw new Error(`${res.status}`)
      setGraph(await res.json())
    } catch (e: any) { setError(e.message || 'no se pudo leer el grafo') }
  }, [])

  useEffect(() => { loadGraph(view) }, [view, loadGraph])

  async function openNode(nodeId: string) {
    setSelected(nodeId)
    try {
      const res = await fetch(
        `/api/internal-graphs/node/${view}?node_id=${encodeURIComponent(nodeId)}`)
      setDetail(res.ok ? await res.json() : null)
    } catch { setDetail(null) }
  }

  const shown = graph ? graph.nodes.slice(0, NODE_CAP) : []
  const visible = new Set(shown.map(n => n.node_id))
  const edges = graph ? graph.edges.filter(e => visible.has(e.source) && visible.has(e.target)) : []
  const positions = layout(shown)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, height: '100%' }}>
      <div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
          <TabBtn active={view === 'debt'} onClick={() => setView('debt')} label="⚠ Dónde se rompe" />
          {GRAPHS.map(g => (
            <TabBtn key={g.key} active={view === g.key} onClick={() => setView(g.key)} label={g.label} />
          ))}
        </div>
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
            : (
              <svg
                style={{ width: '100%', height: '100%', cursor: drag.current ? 'grabbing' : 'grab' }}
                onMouseDown={e => { drag.current = { x: e.clientX - pan.x, y: e.clientY - pan.y } }}
                onMouseUp={() => { drag.current = null }}
                onMouseLeave={() => { drag.current = null }}
                onMouseMove={e => {
                  if (!drag.current) return
                  setPan(p => ({ ...p, x: e.clientX - drag.current!.x, y: e.clientY - drag.current!.y }))
                }}
                onWheel={e => setPan(p => ({ ...p, k: Math.min(6, Math.max(0.2, p.k * (e.deltaY < 0 ? 1.12 : 0.89))) }))}
              >
                <g transform={`translate(${pan.x},${pan.y}) scale(${pan.k})`}>
                  {edges.map((e, i) => {
                    const a = positions.get(e.source), b = positions.get(e.target)
                    if (!a || !b) return null
                    const hot = selected === e.source || selected === e.target
                    return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                      stroke={hot ? '#58a6ff' : '#484f58'} strokeWidth={hot ? 2 : 0.6} />
                  })}
                  {shown.map(n => {
                    const p = positions.get(n.node_id)
                    if (!p) return null
                    return (
                      <circle key={n.node_id} cx={p.x} cy={p.y}
                        r={hot.has(n.node_id) ? 12 : selected === n.node_id ? 9 : 6}
                        fill={n.color}
                        stroke={hot.has(n.node_id) || selected === n.node_id ? '#fff' : '#0d1117'}
                        strokeWidth={hot.has(n.node_id) ? 2.5 : 1.5}
                        style={{ cursor: 'pointer' }}
                        onClick={ev => { ev.stopPropagation(); openNode(n.node_id) }}>
                        <title>{`${n.label} · ${n.state}`}</title>
                      </circle>
                    )
                  })}
                </g>
              </svg>
            )}
        </div>

        <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, overflowY: 'auto', background: 'var(--bg-surface)' }}>
          {view === 'debt'
            ? <DebtPanel debt={debt} />
            : <NodePanel graph={graph} detail={detail} shownCount={shown.length} />}
        </div>
      </div>

      <AccionesEnVivo actions={actions} />
    </div>
  )
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
  return (
    <div style={{ fontSize: 12 }}>
      <h3 style={{ fontSize: 13, margin: '0 0 8px' }}>
        {debt.debt_items_total} elementos de deuda
      </h3>
      <p style={{ color: 'var(--text-muted)', fontSize: 11 }}>
        grafos de hace {Math.round((debt.graphs_age_seconds || 0) / 60)} min
      </p>
      {entries.map(([name, e]) => (
        <div key={name} style={{ padding: '7px 0', borderBottom: '1px solid var(--border)' }}>
          <b>{name.replace(/_/g, ' ')}</b> — {e.count}
          <div style={{ color: 'var(--text-muted)', fontSize: 10, margin: '3px 0' }}>{e.evidence}</div>
          {e.sample.map(s => (
            <div key={s} style={{ fontSize: 10, color: 'var(--text-secondary)', wordBreak: 'break-all' }}>{s}</div>
          ))}
        </div>
      ))}
    </div>
  )
}

function DebtChart({ debt }: { debt: Debt | null }) {
  if (!debt || debt.status !== 'measured') return null
  const entries = Object.entries(debt.items).sort((a, b) => b[1].count - a[1].count)
  const max = Math.max(...entries.map(([, e]) => e.count), 1)
  return (
    <svg style={{ width: '100%', height: '100%' }}>
      {entries.map(([name, e], i) => (
        <g key={name} transform={`translate(24,${28 + i * 46})`}>
          {/* La longitud es el recuento, no una estimación. */}
          <rect width={`${Math.max((e.count / max) * 70, 0.5)}%`} height={26} rx={4}
            fill={e.count ? '#b03030' : '#1b7f4b'} />
          <text x={8} y={18} fill="#fff" fontSize={12}>
            {e.count}  {name.replace(/_/g, ' ')}
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
function layout(nodes: Node[]) {
  const groups: Record<string, Node[]> = {}
  nodes.forEach(n => { (groups[n.state] = groups[n.state] || []).push(n) })
  const positions = new Map<string, { x: number; y: number }>()
  Object.keys(groups).sort().forEach((state, si) => {
    const list = groups[state]
    const radius = 80 + si * 110
    list.forEach((n, i) => {
      const angle = (i / list.length) * Math.PI * 2 + si * 0.4
      positions.set(n.node_id, {
        x: 460 + Math.cos(angle) * radius,
        y: 300 + Math.sin(angle) * radius,
      })
    })
  })
  return positions
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
