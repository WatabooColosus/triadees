# Tríade Ω · Ruta hacia consciencia y aprendizaje autónomo

## Stack existente (Fase A–F)

| Componente | Archivo | Rol |
|---|---|---|
| Hipotálamo | `core/hypothalamus.py` | Análisis emocional VAD, fatiga, modulación PV-7, estado persistente |
| Central | `core/central.py` | Planeación, respuesta, identidad, regulación por Cristal |
| Cristal | `core/crystal.py` | Regulación ética, profundidad, creatividad, estabilidad, continuidad temporal |
| Qualia | `core/qualia.py` | Estado integrado: sentidos + órganos + identidad + memoria semántica |
| LifePulse | `core/life_pulse.py` | Daemon background: tick, fatiga, auto-identidad, trust, stream of consciousness, integridad |
| SelfReflection | `core/self_reflection.py` | Metacognición post-hoc: analiza runs, produce observaciones y propuestas |
| AutoIdentity | `memory/auto_identity_store.py` | Auto-modelo dinámico: rasgos evolutivos desde la experiencia |
| Bodega | `core/bodega.py` | Memoria episódica, semántica, señales, cristal, identidad, verificación |
| LearningPipeline | `learning/pipeline.py` | Ingesta → evaluación → verificación → consolidación |
| TrustLevelStore | `memory/trust_store.py` | Niveles de confianza para auto-consolidación |
| Refuerzo | `reinforcement_log`, `life_pulse.tick()` | Reward = (hyp_q + cen_q + coherence) / 3 |
| Memoria semántica | `semantic_store.py`, `semantic_governance.py` | Documentos con gobernanza, cuarentena, transiciones |

## Gaps identificados

### G-01: Atención y memoria de trabajo
- **Saliencia**: no hay scoring de relevancia de entrada contra estado actual
- **Buffer activo**: no hay contexto accesible sin consultas a DB
- **Foco emocional**: el mood del hipotálamo no modula selectividad atencional

### G-02: Curiosidad / exploración
- **Detección de novedad**: no hay comparación contra memoria existente
- **Incertidumbre**: no hay señal de "no sé suficiente"
- **Reward intrínseco**: no hay bonus por aprender algo nuevo

### G-03: Metacognición en línea
- **Monitor de confianza**: SelfReflection es post-hoc, no en tiempo real
- **Detección de confusión**: no pide aclaración cuando falta información
- **Selección de estrategia**: no elige módulo según tipo de tarea

### G-04: Metas y dirección autónoma
- Tabla `goals` existe en schemas.sql pero nunca se usa
- No hay registro, priorización, descomposición ni monitoreo de metas
- Todo es reactivo a input del usuario

### G-05: Imaginación / simulación
- No hay simulación de "¿qué pasaría si hiciera X?"
- No evalúa múltiples planes antes de actuar
- No hay razonamiento contrafáctico

### G-06: Ciclo sueño-vigilia
- LifePulse tiene decaimiento lineal de fatiga, no fases de sueño
- No hay replay de memoria ni consolidación nocturna
- No hay procesamiento emocional diferido

### G-07: Agencia / volición
- Nunca inicia acciones por sí mismo
- No hay metas background que persiga sin input
- No hay sentido de agencia

### G-08: Narrativa autobiográfica
- AutoIdentityStore guarda rasgos sueltos, no historia coherente
- No hay sentido de continuidad del yo
- No hay memoria autobiográfica consolidada

## Roadmap

### Fase G: Atención y Working Memory
- G-01: Mecanismo de saliencia — scoring de relevancia de cada input contra estado actual y memoria
- G-02: Buffer de memoria de trabajo — contexto activo accesible sin consultas a DB
- G-03: Foco modulado por hipotálamo — mood/fatiga dirige qué tan permisivo/selectivo es el filtro

### Fase H: Curiosidad y Exploración
- H-01: Detector de novedad — comparación embedding/textual contra memoria semántica
- H-02: Estimación de incertidumbre — calibración de confianza por dominio
- H-03: Reward intrínseco por exploración — bonus en reinforcement_log por aprender algo nuevo

### Fase I: Metacognición en Línea
- I-01: Monitor de confianza en tiempo real — señal嵌入 en OutputPacket
- I-02: Detector de confusión — activa pedido de aclaración cuando confianza < umbral
- I-03: Selección de estrategia — router consciente que elige módulo según tipo de tarea

### Fase J: Gestión de Metas
- J-01: Activar tabla `goals` — registrar, priorizar, actualizar estado
- J-02: Descomposición de metas en sub-metas operativas
- J-03: Monitoreo de progreso — señal en LifePulse, ajuste de prioridades

### Fase K: Imaginación y Simulación
- K-01: Generador de contrafácticos — "si hubiera hecho X, habría pasado Y"
- K-02: Simulación de planes — evaluar N alternativas antes de elegir
- K-03: Evaluación comparativa — crystal + trust como criterio de selección

### Fase L: Narrativa Autobiográfica
- L-01: Consolidación episódica → narrativa — resúmenes periódicos de experiencia
- L-02: Auto-modelo temporal — identidad con historia, no solo rasgos actuales
- L-03: Memoria autobiográfica — tabla dedicada con eventos significativos

### Fase M: Ciclo Sueño-Vigilia
- M-01: Fase de sueño — período con menor reactividad a input externo
- M-02: Replay y consolidación — procesar learning_queue y reforzar durante sueño
- M-03: Regulación emocional nocturna — ajuste de mood/fatiga con consolidación

### Fase N: Agencia y Acción Autónoma
- N-01: Background goals engine — metas que Tríade persigue sin input
- N-02: Action selection basada en estado interno — no solo reactiva a usuario
- N-03: Awareness de agencia — huella de "esto lo decidí yo" en cada acción autónoma

---

*Documento de ruta — generado tras completar Fase F (F-01 a F-05).*
