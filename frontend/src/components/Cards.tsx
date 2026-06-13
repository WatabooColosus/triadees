export function Card({ title, color, children }: { title: string; color?: string; children: React.ReactNode }) {
  return (
    <div style={{
      background: 'var(--bg-surface)',
      borderRadius: 10,
      border: '1px solid var(--border)',
      overflow: 'hidden',
    }}>
      {title && (
        <div style={{
          padding: '10px 14px', fontWeight: 700, fontSize: 12, letterSpacing: '0.3px',
          borderBottom: '1px solid var(--border)',
          background: color ? `rgba(${parseInt(color.slice(1,3),16)},${parseInt(color.slice(3,5),16)},${parseInt(color.slice(5,7),16)},0.08)` : undefined,
          color: color || 'var(--text-primary)',
          display: 'flex', alignItems: 'center', gap: 8,
        }}>{title}</div>
      )}
      <div style={{ padding: '12px 14px' }}>{children}</div>
    </div>
  )
}

export function Grid({ cols, children }: { cols: number; children: React.ReactNode }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: 12 }}>
      {children}
    </div>
  )
}

export function Badge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    ok: '#22c55e', active: '#22c55e', enabled: '#22c55e', approved: '#22c55e', healthy: '#22c55e',
    degraded: '#eab308', warning: '#eab308', medium: '#eab308',
    error: '#ef4444', failed: '#ef4444', blocked: '#ef4444', high: '#ef4444', critical: '#ef4444',
    unavailable: '#6b7280', inactive: '#6b7280', unknown: '#6b7280', paused: '#6b7280', rejected: '#6b7280',
  }
  const bg = colorMap[status?.toLowerCase()] || '#8b5cf6'
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 10, fontSize: 10,
      fontWeight: 600, background: bg, color: '#fff', lineHeight: '18px',
    }}>{status}</span>
  )
}

export function KVTable({ data, exclude }: { data: any; exclude?: string[] }) {
  if (!data || typeof data !== 'object') return <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Sin datos</div>
  const keys = Object.keys(data).filter(k => !exclude?.includes(k) && data[k] !== undefined && data[k] !== null)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      {keys.map(k => (
        <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12 }}>
          <span style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{k}</span>
          <span style={{ color: 'var(--text-primary)', fontWeight: 500, textAlign: 'right', wordBreak: 'break-all' }}>
            {typeof data[k] === 'boolean' ? (data[k] ? 'sí' : 'no') : String(data[k] ?? '—')}
          </span>
        </div>
      ))}
    </div>
  )
}

/* ── Cards ───────────────────────────────── */

export function PulseCard({ data }: { data: any }) {
  if (!data) return null
  const score = data.runtime_continuity_score ?? 0
  const scoreColor = score >= 0.7 ? '#22c55e' : score >= 0.4 ? '#eab308' : '#ef4444'
  return (
    <Card title="Pulso Vivo" color={data.runtime_enabled ? '#22c55e' : '#f59e0b'}>
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 28, fontWeight: 700, color: scoreColor }}>{(score * 100).toFixed(0)}%</div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>continuidad</div>
      </div>
      <KVTable data={{
        runtime: data.runtime_enabled ? 'activo' : 'inactivo',
        modo: data.mode,
        ciclos_hora: data.cycles_last_hour,
        ciclos_24h: data.cycles_last_24h,
        misiones_hora: data.missions_executed_last_hour,
        workers: data.workers_active,
        background: data.background_thread_alive ? 'vivo' : 'inactivo',
        ultima_accion: data.latest_action,
        ultimo_error: data.latest_error,
      }} />
    </Card>
  )
}

export function OllamaBloodCard({ data }: { data: any }) {
  if (!data) return null
  const active = data.cognitive_blood_active
  return (
    <Card title="Sangre Cognitiva" color={active ? '#22c55e' : '#ef4444'}>
      {!active && data.status === 'degraded_no_ollama' && (
        <div style={{ padding: '8px 10px', marginBottom: 8, borderRadius: 6, background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', fontSize: 12, color: '#fca5a5' }}>
          Tríade respira en fallback; no hay sangre cognitiva activa.
        </div>
      )}
      {active && (
        <div style={{ padding: '8px 10px', marginBottom: 8, borderRadius: 6, background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)', fontSize: 12, color: '#bbf7d0' }}>
          Sangre cognitiva activa.
        </div>
      )}
      <KVTable data={{
        estado: data.status,
        presion: data.blood_pressure_score,
        url: data.base_url,
        razonador: data.reasoning_model,
        embeddings: data.embedding_model,
        coder: data.coder_model,
        puede_razonar: data.can_reason,
        puede_embed: data.can_embed,
        puede_nutrir: data.can_nourish_neurons,
        puede_evaluar: data.can_evaluate_learning,
        puede_consolidar: data.can_consolidate_stable,
        componentes_degradados: data.degraded_components?.length,
        accion_recomendada: data.recommended_action,
      }} />
    </Card>
  )
}

export function RepoChangesCard({ data }: { data: any }) {
  if (!data) return null
  if (data.status === 'unavailable') {
    return (
      <Card title="Repo: Git status" color="#6b7280">
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Git no disponible: {data.error || 'no es un repositorio'}</div>
      </Card>
    )
  }
  const color = data.dirty ? '#eab308' : '#22c55e'
  return (
    <Card title={`Repo: ${data.branch} @ ${data.commit}`} color={color}>
      <KVTable data={{
        estado: data.dirty ? 'cambios locales' : 'limpio',
        archivos_modificados: data.changed_files_count,
      }} />
      {data.changed_files?.length > 0 && (
        <div style={{ marginTop: 6, maxHeight: 120, overflowY: 'auto', fontSize: 10, color: 'var(--text-muted)' }}>
          {data.changed_files.slice(0, 15).map((f: string, i: number) => (
            <div key={i} style={{ padding: '1px 0', fontFamily: 'monospace', whiteSpace: 'pre' }}>{f}</div>
          ))}
          {data.changed_files.length > 15 && <div style={{ padding: '2px 0' }}>... y {data.changed_files.length - 15} más</div>}
        </div>
      )}
      {data.recent_commits?.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 4 }}>Commits recientes</div>
          {data.recent_commits.map((c: any, i: number) => (
            <div key={i} style={{ fontSize: 10, color: 'var(--text-muted)', padding: '1px 0', fontFamily: 'monospace' }}>
              <span style={{ color: 'var(--accent)' }}>{c.hash}</span> {c.message?.slice(0, 60)}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

export function ProcessStatusCard({ data }: { data: any }) {
  if (!data) return null
  return (
    <Card title="Procesos Internos" color="#22c55e">
      <KVTable data={{
        runtime: data.runtime_enabled ? 'activo' : 'inactivo',
        modo: data.mode,
        ciclos_hora: data.cycles_last_hour,
        ciclos_24h: data.cycles_last_24h,
        workers: data.workers_active ? 'activos' : 'inactivos',
        misiones_hora: data.missions_executed_last_hour,
        background: data.background_thread_alive ? 'vivo' : 'inactivo',
        ultima_accion: data.latest_action,
        ultimo_error: data.latest_error,
      }} />
    </Card>
  )
}

export function BodegaCard({ data }: { data: any }) {
  if (!data) return null
  const confianza = data.memory_confidence ?? 'unknown'
  const color = confianza === 'high' ? '#22c55e' : confianza === 'medium' ? '#eab308' : '#6b7280'
  return (
    <Card title="Bodega Global" color={color}>
      <KVTable data={{
        confianza: confianza,
        motor_semantico: data.semantic_engine_status,
        modo_recall: data.semantic_recall_mode,
        aprendizaje: data.semantic_learning_allowed,
        contradicciones: data.contradictions_count,
        politica: data.recommended_context_policy,
      }} />
    </Card>
  )
}

export function MemoryTraceCard({ data }: { data: any }) {
  if (!data) return null
  const m = data.memory_trace_summary || {}
  return (
    <Card title="Memory Trace" color="#8b5cf6">
      <KVTable data={{
        confianza: m.memory_confidence,
        identity_matches: m.identity_matches_count,
        semantic_matches: m.semantic_matches_count,
        episodic_matches: m.episodic_matches_count,
        authorized: m.authorized_matches_count,
        quarantined: m.quarantined_matches_count,
        stable_needs_review: m.stable_needs_review,
      }} />
    </Card>
  )
}

export function LearningJournalCard({ data }: { data: any }) {
  if (!data) return null
  return (
    <Card title="Learning Journal" color="#22c55e">
      <KVTable data={{
        ciclos_24h: data.cycles_last_24h,
        misiones: data.missions_executed,
        evidencia: data.evidence_created,
        candidatos: data.candidates_created,
        evaluados: data.candidates_evaluated,
        verificados: data.candidates_verified,
        consolidados: data.candidates_consolidated,
        rechazados: data.candidates_rejected,
        neuronas_nutridas: data.neurons_nourished,
      }} />
      {data.latest_learning_candidate && (
        <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>
          Último candidato: {typeof data.latest_learning_candidate === 'string' ? data.latest_learning_candidate : JSON.stringify(data.latest_learning_candidate).slice(0, 80)}
        </div>
      )}
      {data.latest_rejection && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Último rechazo: {typeof data.latest_rejection === 'string' ? data.latest_rejection : JSON.stringify(data.latest_rejection).slice(0, 80)}
        </div>
      )}
    </Card>
  )
}

export function TechnicalDebtCard({ data }: { data: any }) {
  if (!data) return null
  const [expanded, setExpanded] = useState(false)
  const score = data.score ?? 0
  const color = score >= 70 ? '#22c55e' : score >= 40 ? '#eab308' : '#ef4444'
  return (
    <Card title={`Deuda Técnica · Score ${score}/100`} color={color}>
      <KVTable data={{
        deudas: data.debts_count,
        advertencias: data.warnings_count,
      }} />
      {data.debts?.length > 0 && !expanded && (
        <div style={{ marginTop: 6 }}>
          {data.debts.slice(0, 3).map((d: any, i: number) => (
            <div key={i} style={{ fontSize: 10, color: 'var(--text-muted)', padding: '2px 0' }}>
              <Badge status={d.severity} /> {d.item}
            </div>
          ))}
        </div>
      )}
      {expanded && data.debts?.length > 0 && (
        <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {data.debts.map((d: any, i: number) => (
            <div key={i} style={{ padding: '6px 8px', background: 'var(--bg-base)', borderRadius: 6, fontSize: 11 }}>
              <div style={{ fontWeight: 600 }}>{d.item} <Badge status={d.severity} /></div>
              <div style={{ color: 'var(--text-muted)', marginTop: 2 }}>{d.detail}</div>
            </div>
          ))}
        </div>
      )}
      <button onClick={() => setExpanded(!expanded)} style={{
        marginTop: 8, background: 'transparent', border: '1px solid var(--border)',
        color: 'var(--text-muted)', borderRadius: 6, padding: '4px 12px', fontSize: 11, cursor: 'pointer',
      }}>
        {expanded ? 'Colapsar' : 'Ver detalles'}
      </button>
    </Card>
  )
}

export function EventsFeed({ events }: { events: any[] }) {
  if (!events || events.length === 0) return null
  return (
    <Card title={`Eventos recientes (${events.length})`} color="#3b82f6">
      <div style={{ maxHeight: 200, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 3 }}>
        {events.map((e: any, i: number) => (
          <div key={i} style={{
            display: 'flex', gap: 6, fontSize: 10, padding: '4px 6px',
            background: 'var(--bg-base)', borderRadius: 4,
          }}>
            <span style={{ color: 'var(--text-muted)', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
              {e.created_at?.slice(11, 19) || e.timestamp?.slice(11, 19) || ''}
            </span>
            <Badge status={e.severity || e.status || 'info'} />
            <span style={{ color: 'var(--text-primary)' }}>{e.event_type || e.message || e.type || ''}</span>
          </div>
        ))}
      </div>
    </Card>
  )
}

/* ── Workers Card ─────────────────────────── */

export function WorkersCard({ data }: { data: any }) {
  if (!data) return null
  return (
    <Card title="Workers" color="#f59e0b">
      <KVTable data={{
        estado: data.status,
        tareas_activas: data.active_tasks,
        ultimo_run: data.last_run_ref,
      }} />
    </Card>
  )
}

/* ── Cabina Viva ──────────────────────────── */

import { useLiveDashboard } from './useLiveDashboard'

export function CabinaViva() {
  const { data, loading, error, lastUpdated, refresh } = useLiveDashboard()

  if (loading && !data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
        Cargando cabina viva…
      </div>
    )
  }

  const dash = data

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {lastUpdated ? `Última actualización: ${lastUpdated}` : ''}
          </span>
          <Badge status={dash?.status || 'unknown'} />
        </div>
        <button onClick={refresh} style={{
          background: 'var(--accent)', color: '#fff', border: 'none',
          borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontWeight: 600, fontSize: 11,
        }}>Refrescar ahora</button>
      </div>

      {error && (
        <div style={{
          padding: '8px 12px', marginBottom: 12, borderRadius: 6,
          background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
          fontSize: 12, color: '#fca5a5',
        }}>
          Error: {error} (manteniendo último dato válido)
        </div>
      )}

      <Grid cols={2}>
        <PulseCard data={dash?.heartbeat} />
        <OllamaBloodCard data={dash?.ollama_blood} />
        <RepoChangesCard data={dash?.git_status} />
        <ProcessStatusCard data={dash?.heartbeat} />
        <BodegaCard data={dash?.bodega_summary} />
        <MemoryTraceCard data={dash?.observability} />
        <LearningJournalCard data={dash?.learning_journal} />
        <TechnicalDebtCard data={dash?.technical_debt} />
        <WorkersCard data={dash?.workers} />
      </Grid>
      <EventsFeed events={dash?.runtime_events} />
    </div>
  )
}
