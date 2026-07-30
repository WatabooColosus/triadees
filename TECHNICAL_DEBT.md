# Deuda técnica vigente · Tríade Ω

Corte: 2026-07-30. SHA documental base: `56b476d`. Esta lista es canónica;
los reportes anteriores son históricos cuando la contradicen.

## P0

- Ejecutar sin compresión las ventanas de 24 h y 72 h. La única ejecución
  observada fue una sonda real de 10 segundos; `long_run_verified=false`.
- Ejecutar el chaos completo en una ventana autorizada. Faltan reinicio de
  Ollama, presión de disco, reinicio por watchdog, GPU no disponible y memoria
  baja. La sub-suite aislada sí cubrió diez fallos sin pérdidas ni falsos cierres.
- Resolver 271 incidencias Ruff (247 catches amplios y 24 silenciosos) y 224
  errores mypy en 68 archivos, sin excepciones de reglas. Hasta entonces CI no
  está verde.
- Ejecutar GitHub Actions sobre el SHA candidato y obtener todos los jobs
  requeridos en verde. No hubo push por instrucción expresa.

## P1

- Ejecutar A/B multi-modelo real contra baseline de un solo modelo y adoptar
  routing solo si mejora calidad o recursos. El routing está implementado, pero
  su ventaja no está demostrada.
- Completar aprobación nominal y tráfico de serving LoRA canary controlado. El
  PEFT canary, hashes, regresión y rollback están implementados y probados; no se
  activó producción automáticamente.
- Mantener la ventana productiva de compatibilidad legacy y retirar tablas solo
  tras confirmar cero duplicados y cero pérdidas durante operación prolongada.
- Validar federación sostenida entre hosts diferentes. La evidencia vigente usa
  dos procesos reales con transporte TCP, firma Ed25519, reproducción y
  revocación, pero en un solo host.
- Operar simulacros periódicos de backup con la clave de producción configurada
  fuera de Git y registrar retención/espacio durante una ventana prolongada.

## P2

- Sustituir rate limiting local por un backend distribuido antes de escalar a
  múltiples réplicas y completar pruebas externas de abuso/egress.
- Continuar separando fronteras de DB, contratos, runtime, workers, seguridad,
  federación y learning para hacer tratable la deuda mypy.
- Añadir un motor visual independiente si existe una necesidad demostrada;
  `gemma3:4b` aporta comprensión visual, no generación de imágenes.
- Tríade OS continúa siendo un plano de control sobre Linux, no un kernel ni un
  sistema operativo anfitrión independiente.

## Cerrado con evidencia local

- Ejecución gobernada con lease, fencing, postcondición, artifact, receipt y
  rollback; estados blocked/skipped/dry-run no aparentan efecto.
- Identidad continua con manifest, hashes, detección de alteración, modo seguro,
  restore, API y CLI read-only.
- Traza causal triádica y benchmark ablativo determinista.
- Memoria longitudinal gobernada con aislamiento, contradicción y restore; el
  corpus inicial alcanzó los umbrales documentados.
- Estado longitudinal de modulación relacional PV-7, aislado y reversible.
- Metacognición calibrada, research gobernado, ciclo de aprendizaje con
  corrección, transferencia, persistencia y rollback.
- Utility Ledger, certificación neuronal, autenticación/RBAC/sesiones, backup
  cifrado y federación TCP de dos procesos.

## Regla de cierre

Una deuda solo se cierra con código, pruebas, evidencia runtime, documentación y
ruta de recuperación. Actividad, persistencia o etiquetas no sustituyen efecto,
recuperación útil ni aprendizaje validado.
