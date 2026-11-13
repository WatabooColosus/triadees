# Migración UI React — Tríade Ω

> La UI oficial de Tríade Ω es React SPA en `frontend/`.
> FastAPI single-port sirve la SPA y la API.
> Las rutas HTML legacy quedan como compatibilidad o redirect.
> Toda nueva visualización debe implementarse en React.
> Los endpoints deben devolver JSON limpio.
> No crear nuevas pantallas HTML embebidas.

---

## Cabina React viva

La SPA incluye una **Cabina Viva** (tab 🖥) que refresca automáticamente cada 5 segundos.

- React consulta `GET /api/ui/react-dashboard` en un loop con `useLiveDashboard`.
- El polling se pausa cuando la pestaña no está visible (`document.visibilityState`).
- Los datos incluyen: Pulse, Ollama Blood, Git status, procesos internos, Bodega, Memory Trace, Learning Journal, Deuda Técnica y eventos recientes.
- Si una petición falla, se conserva el último dato válido.
- Botón "Refrescar ahora" para recarga manual.

La UI es **read-only para estado del sistema**. Git status se muestra con comandos whitelist (shell=False, timeout 3s). Acciones peligrosas requieren API key y confirmación explícita.

---

## Estructura React actual

```
frontend/
├── index.html              # HTML dev entrypoint (Vite)
├── dist/                   # Build output
│   ├── index.html
│   └── assets/
│       ├── index-*.js
│       └── index-*.css
├── src/
│   ├── App.tsx             # SPA completa (~1594 líneas)
│   ├── index.css           # Estilos globales
│   └── vite-env.d.ts       # Tipos Vite
├── package.json
├── vite.config.ts
└── tsconfig.json
```

Tabs: Chat, Sistema, Observabilidad, Router, Modelos, Federación, Memoria, Neuronas.

---

## Cómo correr build

```bash
npm --prefix frontend run build
```

Esto genera `frontend/dist/` con los assets estáticos que sirve FastAPI.

---

## Cómo servir

```bash
python triade_digimon.py api --host 127.0.0.1 --port 8010
```

Abrir en navegador:
- `http://127.0.0.1:8010/`
- `http://127.0.0.1:8010/observabilidad`

La SPA se sirve desde `GET /` cuando `frontend/dist/index.html` existe.
Si el build no existe, FastAPI sirve un fallback HTML legacy (`CLEAN_UI_HTML`).

---

## Cómo agregar nueva tarjeta React

1. Crear componente en `frontend/src/components/` (ej. `PulseCard.tsx`).
2. Importar y usar en el tab correspondiente de `App.tsx`.
3. Consumir endpoint API correspondiente con la función `api()`.

```typescript
// Ejemplo de componente
function PulseCard({ data }: { data: any }) {
  return (
    <Card title="Pulso Vivo" color="#22c55e">
      <KVTable data={{
        runtime_enabled: data.runtime_enabled,
        mode: data.mode,
        cycles: data.cycles_last_hour,
      }} />
    </Card>
  )
}
```

```typescript
// En el fetch del tab:
const pulse = await api('/api/runtime/heartbeat')
```

---

## Cómo consumir endpoints API

Usar la función `api()` de `App.tsx`:

```typescript
const data = await api('/api/runtime/heartbeat')
const blood = await api('/api/models/ollama/blood')
const dashboard = await api('/api/ui/react-dashboard')
```

La función `api()` maneja automáticamente:
- Prefijo de URL (vacío para single-port).
- Parseo JSON.
- Manejo de errores HTTP.

---

## Reglas de migración

1. **No crear nuevas pantallas HTML embebidas.** Usar siempre React.
2. **Endpoints JSON primero.** Si una vista necesita datos, crear endpoint API limpio.
3. **No duplicar lógica de negocio en el frontend.** Cada tarjeta React debe solo mostrar datos del API.
4. **Componentes pequeños.** Si `App.tsx` supera 2000 líneas, extraer a `components/`.
5. **SPA history fallback.** FastAPI sirve `/` para todas las rutas SPA; React maneja el routing interno.
6. **API read-only por defecto.** Endpoints de dashboard no deben modificar estado ni ejecutar workers.

---

## Endpoints principales para la SPA

| Endpoint | Propósito | Tab |
|---|---|---|
| `GET /api/health` | Salud general | Sistema |
| `GET /api/runtime/heartbeat` | Pulso vivo, continuidad, errores | Observabilidad |
| `GET /api/runtime/learning-journal` | Candidatos, ciclos, consolidaciones 24h | Observabilidad |
| `GET /api/runtime/neuron-nutrition` | Nutrición neuronal | Observabilidad |
| `GET /api/models/ollama/blood` | Sangre cognitiva Ollama | Sistema |
| `GET /api/bodega/global-context` | Contexto global de memoria | Memoria |
| `GET /api/observability` | Observabilidad completa | Sistema/Observabilidad |
| `GET /api/neurons/stable-audit` | Auditoría de neuronas estables | Neuronas |
| `GET /api/system/neurons` | Listado de neuronas | Neuronas |
| `GET /api/neurons/missions/relevant` | Misiones relevantes | Neuronas |
| `GET /api/safety/pending` | Aprobaciones humanas pendientes | Neuronas |
| `GET /api/system/technical-debt` | Auditoría de deuda técnica | Sistema |
| `GET /api/ui/react-dashboard` | Dashboard agregado read-only | Sistema |
