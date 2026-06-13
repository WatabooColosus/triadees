import { useState } from 'react'
import { useLiveDashboard, api as liveApi } from './useLiveDashboard'
import {
  Grid, Card, Badge, btn,
  PulseCard, OllamaBloodCard, ResourcesCard, WorkModeCard,
  RepoChangesCard, ProcessStatusCard, AutonomyBudgetCard,
  TrashCard, DelegatedActionsCard, BodegaCard, MemoryTraceCard,
  LearningJournalCard, TechnicalDebtCard, WorkersCard,
  SafeShellCard, EventsFeed,
} from './Cards'

export function CabinaViva() {
  const { data, loading, error, lastUpdated, refresh } = useLiveDashboard()
  const [busy, setBusy] = useState<string | null>(null)
  const [actionMsg, setActionMsg] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [shellResult, setShellResult] = useState<{ key: string; stdout: string } | null>(null)

  async function act(label: string, fn: () => Promise<any>) {
    if (busy) return
    setBusy(label)
    setActionError(null)
    setActionMsg(null)
    try {
      const res = await fn()
      setActionMsg(res?.message || `${label} completado`)
      refresh()
    } catch (e: any) {
      setActionError(e.message || `Error en ${label}`)
    } finally {
      setBusy(null)
    }
  }

  function runCycle() {
    act('Ejecutar ciclo', () =>
      liveApi('/api/runtime/once', { method: 'POST', body: JSON.stringify({ mode: 'observe_only' }) }))
  }

  function startMode(mode: string) {
    if (mode === 'execute_missions') {
      if (!window.confirm('¿Activar execute_missions? Se crearán candidatos y se ejecutarán misiones. No se consolida stable.')) return
    }
    if (mode === 'full_local') {
      if (!window.confirm('⚠️ full_local ejecuta aprendizaje, evaluación y consolidación estable. ¿Continuar?')) return
    }
    act(`Encender ${mode}`, () =>
      liveApi('/api/runtime/start', {
        method: 'POST',
        body: JSON.stringify({ mode, interval_seconds: mode === 'observe_only' ? 30 : 60 }),
      }))
  }

  function stopRuntime() {
    act('Apagar', () => liveApi('/api/runtime/stop', { method: 'POST' }))
  }

  if (loading && !data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
        Cargando cabina viva…
      </div>
    )
  }

  if (!data && !loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <div style={{ color: '#ef4444', fontSize: 16, marginBottom: 12 }}>No se pudieron cargar datos</div>
        {error && (
          <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 16 }}>
            Error: {error}
          </div>
        )}
        <button onClick={refresh} style={btn}>Reintentar</button>
      </div>
    )
  }

  const dash = data!
  const blockErrors = dash.errors || []
  const hb = dash.heartbeat || {}
  const governor = dash.governor || {}

  async function runShell(key: string) {
    if (busy) return
    setBusy(`Shell: ${key}`)
    setShellResult(null)
    try {
      const res = await liveApi('/api/system/safe-shell/run', {
        method: 'POST',
        body: JSON.stringify({ command_key: key }),
      })
      setShellResult({ key, stdout: res.stdout || res.stderr || '(sin salida)' })
    } catch (e: any) {
      setActionError(e.message || `Error en ${key}`)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div style={{ height: '100%', overflow: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {lastUpdated ? `Última actualización: ${lastUpdated}` : ''}
          </span>
          <Badge status={dash.status || 'unknown'} />
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            /api/ui/react-dashboard · refresh {Math.round((dash.refresh_hint_seconds || 5) / 5)}s
          </span>
        </div>
        <button onClick={refresh} style={btn} disabled={!!busy}>Refrescar</button>
      </div>

      {busy && (
        <div style={{ padding: '8px 12px', marginBottom: 12, borderRadius: 6, background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.3)', fontSize: 12, color: '#93c5fd' }}>
          {busy}…
        </div>
      )}

      {actionMsg && (
        <div style={{ padding: '8px 12px', marginBottom: 12, borderRadius: 6, background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)', fontSize: 12, color: '#bbf7d0' }}>
          {actionMsg}
        </div>
      )}

      {actionError && (
        <div style={{ padding: '8px 12px', marginBottom: 12, borderRadius: 6, background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', fontSize: 12, color: '#fca5a5' }}>
          {actionError}
        </div>
      )}

      {error && (
        <div style={{
          padding: '8px 12px', marginBottom: 12, borderRadius: 6,
          background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
          fontSize: 12, color: '#fca5a5',
        }}>
          Error de conexión: {error} (mostrando datos anteriores)
        </div>
      )}

      {blockErrors.length > 0 && (
        <div style={{
          padding: '8px 12px', marginBottom: 12, borderRadius: 6,
          background: 'rgba(234,179,8,0.1)', border: '1px solid rgba(234,179,8,0.3)',
          fontSize: 11, color: '#fde047',
        }}>
          <strong>Bloques con error:</strong>
          {blockErrors.map((b: any, i: number) => (
            <div key={i} style={{ marginTop: 2 }}>· {b.block}: {b.error}</div>
          ))}
        </div>
      )}

      <Grid cols={2}>
        <PulseCard data={dash.heartbeat} onCycle={runCycle} onStart={startMode} onStop={stopRuntime} />
        <OllamaBloodCard data={dash.ollama_blood} />
        <ResourcesCard data={governor} />
        <WorkModeCard data={governor} />
        <RepoChangesCard data={dash.git_status} />
        <ProcessStatusCard data={dash.heartbeat} />
        <AutonomyBudgetCard data={dash.autonomy_delegation} />
        <TrashCard data={dash.autonomy_delegation} onRestore={(manifestPath) => act('Restaurar', () =>
          liveApi('/api/trash/restore', {
            method: 'POST',
            body: JSON.stringify({ manifest_path: manifestPath }),
          })
        )} />
        <DelegatedActionsCard onPlan={async (intent, path, level) => {
          const res = await liveApi('/api/delegated/plan', {
            method: 'POST',
            body: JSON.stringify({ intent, paths: [path], autonomy_level: level }),
          })
          return res
        }} />
        <BodegaCard data={dash.bodega_summary} />
        <MemoryTraceCard data={dash.observability} />
        <LearningJournalCard data={dash.learning_journal} />
        <TechnicalDebtCard data={dash.technical_debt} />
        <WorkersCard data={dash.workers} />
        <SafeShellCard onRunShell={runShell} />
      </Grid>
      {shellResult && (
        <div style={{ marginTop: 12 }}>
          <Card title={`Shell: ${shellResult.key}`} color="#f59e0b">
            <pre style={{ fontSize: 10, color: 'var(--text-primary)', whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 200, overflow: 'auto', margin: 0 }}>{shellResult.stdout}</pre>
          </Card>
        </div>
      )}
      <EventsFeed events={dash.runtime_events} />
    </div>
  )
}
