# Auditoría integral de Tríade Ω — 2026-07-23

## Dictamen ejecutivo

Tríade Ω es hoy un **prototipo integrado avanzado de agente local gobernado**. Ya une conversación, memoria, regulación, modelos locales, aprendizaje candidato, pulsos, observabilidad, acceso web explícito y un plano de control llamado Tríade OS. No es todavía un sistema operativo de propósito general, una AGI, una conciencia ni un modelo fundacional entrenado desde cero.

Puede evolucionar sobre la base actual. La prioridad no debe ser producir más actividad, sino aumentar la cantidad de evidencia útil por ciclo, reducir duplicados y comprobar que cada promoción mejora resultados medibles.

### Evidencia de esta auditoría

- Suite: **999 pruebas aprobadas**, una advertencia de deprecación externa y cero fallos.
- Frontend: build de producción aprobado.
- Compilación Python: aprobada.
- Alineación medida: **0.96 / strong**; Central, Bodega, Cristal y Runner en 1.0; Hipotálamo en 0.8.
- Auto-test seguro: aprobado sin errores; deuda técnica medida en 77/100.
- Recursos observados: 8 CPU, 25.99 GiB RAM y Ollama con los seis modelos requeridos.
- Web pública y endpoints de diagnóstico: respondiendo HTTP 200.
- Estado global expuesto como `degraded`: hay ciclos persistidos recientes y workers activos, pero el observador HTTP no ve vivo el hilo de background dentro de su proceso. Es una incoherencia de supervisión que debe resolverse antes de producción.

## Mapa operativo

| Componente | Función efectiva | Estado |
|---|---|---|
| Central | Planifica, estructura teoría y produce la respuesta; coordina el ciclo. | Operativa |
| Neurona Creadora | Propone neuronas, nodos, relaciones y candidatos cuando detecta una misión nueva. | Operativa con gates |
| Neurona Formativa | Asigna misión, nutrición, evaluación y condiciones de promoción. | Operativa con gates |
| Hipotálamo emocional | Interpreta intención, tono, urgencia, riesgo y vector emocional PV-7. | Operativo; falta estado longitudinal propio por sesión |
| Bodega | SQLite, episodios, señales, memoria semántica, aprendizaje y contexto global. | Operativa |
| Qualia / Alma | Capa simbólica y relacional que resume estado interno y continuidad. No demuestra experiencia subjetiva. | Conectada y observable |
| Cristal | Regula forma, coherencia, estabilidad temporal, creatividad y ética de la salida. | Operativo |
| Runner | Ejecuta el ciclo cognitivo, persiste artefactos, integridad, eventos y aprendizaje posterior. | Operativo |
| Pulso Vivo | Ejecuta salud, nutrición, evaluación, consolidación y tareas programadas. | Operativo |
| Tríade OS | Plano de control cognitivo y de servicios dentro de Linux; no reemplaza el SO anfitrión. | Operativo |
| Model Router / Ollama Blood | Selecciona modelos locales y registra proveedor, calidad y fallback. | Operativo |
| `triade-omega` | Modelo local derivado de Qwen2.5 mediante Modelfile e identidad innata. No es un modelo nuevo entrenado desde cero. | Operativo |
| Adquisición de modelos | Descarga secuencial desde catálogo permitido, con presupuesto de disco y sin ejecutar código remoto. | Operativa, todavía no descubre catálogos abiertos por sí sola |
| Web guardada | Busca únicamente por solicitud explícita, bloquea destinos privados y devuelve fuentes. | Operativa |
| Edge local | Produce contexto local determinista cuando no hay nodos conectados y registra la recuperación. | Operativo |
| Edge federado | Agrega evidencia de nodos dentro del contexto global de Bodega sin tratarla automáticamente como verdad. | Estructura operativa; sin nodos remotos activos |
| Refutación | Contrasta afirmaciones con evidencia persistida y marca soportado, refutado o inconcluso. | Operativa |
| Seguridad pública | Permite chat/run/doctor sin API key y bloquea escrituras administrativas públicas. | Adecuada para demostración guardada, no para producción multiusuario |
| UI / Núcleo de control | Muestra órganos, modelos, aprendizaje, internet y estado del runtime. | Operativa |

## Lo que está bien

- La arquitectura teórica tiene correspondencia explícita en módulos ejecutables y endpoints observables.
- El procesamiento principal puede mantenerse local y usar GPU mediante Ollama.
- La identidad de Tríade queda separada de la procedencia real del modelo base; no se presenta el Modelfile como entrenamiento original.
- Cada run conserva entrada, señales, memoria, cristal, plan, seguridad, salida, diferencias, reporte, integridad y cierre.
- El aprendizaje usa estados candidato/experimental/stable, pruebas y gates; una conversación simple no debería convertirse directamente en una neurona estable.
- Internet, descarga de modelos y federación están acotados por allowlists, presupuesto, bloqueo SSRF, permisos y trazabilidad.
- Qualia está integrada como metáfora operativa medible sin afirmar conciencia humana.
- La API pública sin clave conserva una superficie limitada y bloquea administración peligrosa.

## Lo que está incompleto o mal

- El Hipotálamo detecta emoción por turno, pero no mantiene todavía un estado emocional longitudinal agregado y verificable por sesión.
- No hay nodos federados remotos activos; el Edge global es hoy contrato, almacenamiento y recuperación local.
- La asignación de modelos especializados existe, pero el Runner aún no orquesta N modelos dinámicamente para cada pensamiento o acción.
- `gemma3:4b` puede comprender entradas visuales compatibles, pero no sustituye un motor de generación de imágenes por difusión.
- La adquisición descarga un catálogo permitido; no evalúa autónomamente todos los modelos gratuitos de Internet, algo que además sería inseguro y costoso sin pruebas previas.
- Los pulsos y el aprendizaje pueden producir candidatos repetitivos si se mide actividad en vez de novedad o mejora.
- El despliegue público depende del ciclo de vida del Cloudspace; faltan dominio, TLS/ingress estable, autenticación por capacidades, copias y operación de producción.
- Tríade OS es un plano de control de la aplicación, no aislamiento de procesos, kernel, drivers ni gestor general del equipo.
- La primera auditoría estática contenía un falso negativo del Runner tras extraer la escritura de artefactos a un módulo; se corrigió para auditar la implementación real.

## Modelos locales observados

- `triade-omega:latest`: identidad y contrato innato de Tríade, derivado localmente.
- `qwen2.5:3b-instruct`: respaldo conversacional.
- `qwen3:4b`: razonamiento alternativo.
- `qwen2.5-coder:3b`: tareas de código y reparación.
- `gemma3:4b`: lenguaje y comprensión visual compatible.
- `nomic-embed-text`: embeddings para memoria semántica.

## ¿Conviene darle más pulsos?

No conviene acelerar todos los pulsos indiscriminadamente. El intervalo actual de 60 segundos ya es intenso para un sistema local. Más ciclos pueden aumentar temperatura, consumo, ruido de candidatos, contención de SQLite y falsos aprendizajes sin mejorar la calidad.

Se recomienda un planificador adaptativo:

1. Salud ligera cada 30–60 segundos.
2. Nutrición, refutación y evaluación cada 5–15 minutos.
3. Tests profundos cada 10–30 minutos o después de cambios reales.
4. Ráfagas activadas por eventos nuevos, no por tiempo vacío.
5. Retroceso automático ante inactividad, errores, temperatura, presión de RAM/GPU o falta de novedad.

Antes de aumentar frecuencia deben medirse: evidencia nueva por ciclo, candidatos duplicados, promociones que pasan evaluación, regresiones, latencia, errores y uso de CPU/RAM/GPU. Acelerar solo si la utilidad marginal sube y el error no empeora.

## Siguiente evolución recomendada

1. Añadir scheduler adaptativo con presupuesto térmico y de recursos.
2. Implementar en el Runner un despacho real por capacidad hacia múltiples modelos, con evaluación A/B y fallback.
3. Crear evaluaciones por neurona y exigir mejora estadística antes de `stable`.
4. Persistir el estado longitudinal del Hipotálamo por sesión.
5. Conectar nodos federados reales con firma, identidad, reputación, expiración y cuarentena.
6. Incorporar un generador de imágenes local separado si esa capacidad es requerida.
7. Preparar un dataset gobernado y un adaptador LoRA si se busca aprendizaje de pesos propio, conservando procedencia y reversibilidad.
8. Endurecer el despliegue público con autenticación por capacidades, cuotas, logs, backups y disponibilidad independiente del entorno de desarrollo.

## Criterio de avance

El próximo nivel no se alcanza creando más nombres de neuronas ni ejecutando más ciclos. Se alcanza cuando una capacidad nueva tiene misión, datos de evaluación, comparación con baseline, mejora demostrable, límites de recursos, reversión y evidencia observable en producción.
