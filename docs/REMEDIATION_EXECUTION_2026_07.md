# Plan ejecutado de estabilización integral · 2026-07

## Objetivo

Convertir la auditoría integral de Tríade Ω en correcciones verificables sin
debilitar Safety, `identity_core`, gobernanza semántica ni trazabilidad.

## Trabajo ejecutado

1. **Git y línea base.** Git for Windows 2.55 quedó instalado. La copia local
   fue conectada a `https://github.com/WatabooColosus/triadees.git` y el trabajo
   quedó aislado en `codex/full-remediation-2026-07` sobre `origin/main`.
2. **Integridad neuronal.** `NeuronActivityStore` crea un run padre auditable
   para actividad producida por pulso/workers. Se conserva la foreign key y se
   añadió una regresión que exige `PRAGMA foreign_key_check = []`.
3. **Verdad del runtime.** El hilo background local es la fuente canónica de
   `runtime_enabled`; living report y heartbeat consumen la misma verdad. Se
   eliminó el endpoint temporal `/api/debug/singleton`.
4. **Suite determinista.** Se incorporó `pytest-xdist` al perfil dev. La suite
   completa pasa con `python -m pytest -n 4 --dist loadfile -q`; el modo
   secuencial continúa disponible para depuración.
5. **Workers.** Los locks ahora validan que su PID siga vivo en Windows/POSIX.
   Un lock obsoleto se recupera y sus runs se cierran como `interrupted`. En la
   base local se reconciliaron dos runs obsoletos.
6. **Aprendizaje.** Se restauró el gate de evidencia comparativa: ningún item
   pasa a `validated_in_runs` ni a stable sin decisión `improved`. Diez filas
   históricas sin esa evidencia fueron devueltas a `verified` con nota
   `integrity_reconciliation`; no se inventó evidencia.
7. **Exposición segura.** El CLI rechaza bind no-loopback de la API si no existe
   `TRIADE_API_KEY`. Localhost sigue funcionando sin clave; el relay público
   conserva su aplicación y tokens separados.
8. **Recall semántico.** Se verificaron ranking coseno, filtros, dimensiones,
   fallo degradado y gobernanza candidate/stable. Los tests de integración
   confirman que solo memoria stable llega a Central.
9. **Federación.** Se añadió una prueba DB-backed con dos nodos autorizados,
   envío, recepción, log y entrada como candidate, demostrando que el intercambio
   no consolida memoria automáticamente.
10. **Documentación y compatibilidad.** Proyecto y FastAPI declaran `2.2.0`;
    se documentó Autonomía Delegada; las rutas Windows usan separación
    normalizada; Git se descubre incluso si el proceso nació antes de instalarlo;
    SQLite cierra conexiones de misiones explícitamente y el update de fatiga es
    portable.

## Reparación de datos locales

- 2 worker runs obsoletos: `running` → `interrupted`.
- 10 aprendizajes sin medición: `validated_in_runs` → `verified`.
- 27 runs históricos padres creados para `model_events` huérfanos.
- Resultado final de `PRAGMA foreign_key_check`: cero violaciones.

## Evidencia de aceptación

- Suite completa: 100% aprobada en cuatro workers de pytest.
- Frontend: `npm.cmd run build` aprobado con Vite.
- Batería focal de runtime/autonomía/Git/SQLite/API: 64 aprobadas.
- Batería de recall/federación/gobernador: 41 aprobadas.
- Ollama: razonamiento, código, embeddings y modelo ligero disponibles.

## Operación recomendada

```powershell
python -m pytest -n 4 --dist loadfile -q
cd frontend
npm.cmd run build
```

Para exposición fuera de localhost, definir una clave fuerte antes de iniciar:

```powershell
$env:TRIADE_API_KEY = "<secreto-administrado-fuera-del-repo>"
python triade_digimon.py api --host 0.0.0.0 --port 8010
```

No guardar la clave en Git.
