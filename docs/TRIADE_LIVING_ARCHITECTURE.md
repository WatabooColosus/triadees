# Triade Living Architecture

Fecha: 2026-06-05

## Forma Del Sistema

```text
Tríade
├── Neurona Central
├── N Formadora
├── N Creadora
├── Hipotálamo
├── Vector emocional
├── Bodega de almacenamiento
├── Qualia
└── Pulso vivo
```

## Órganos

- **Neurona Central**: planea y responde usando señales, memoria, Cristal, Qualia y pulso vivo.
- **N Formadora**: evalúa neuronas candidatas antes de promoverlas.
- **N Creadora**: crea especificaciones de neuronas candidatas cuando aparece una necesidad.
- **Hipotálamo**: detecta intención, urgencia, riesgo y tono.
- **Vector emocional**: representa PV-7 y señales afectivo-cognitivas.
- **Bodega de almacenamiento**: conserva DB local, runs, episodios, memoria semántica, cristal, señales, reportes y eventos de modelo.
- **Qualia**: alma operativa del sistema; integra lo que ocurre ahora y diferencia estado vivo de memoria consolidada.
- **Pulso vivo**: sentidos internos y estado vital del sistema cada N segundos, con contadores, integridad, reflexión y acciones observadas.

## Alineación Semántica

La memoria semántica ya no queda separada del pulso. `Qualia` lee:

- `semantic_documents`
- `semantic_embeddings`
- `semantic_memory`
- `semantic_governance_events`
- `life_pulse`
- reflexión interna

Y produce una señal clara para la Central:

```text
No hay / hay memoria semántica estable.
El pulso vivo informa lo que ocurre ahora.
La memoria semántica consolida conocimiento aprobado.
```

Por eso, si Tríade dice que no tiene recuerdos semánticos, todavía puede decir qué ocurre en su pulso vivo, qué neuronas están propuestas, qué recursos siente y qué límites tiene. Eso no es contradicción: son planos distintos.

Las neuronas propuestas no son recuerdos semánticos consolidados, pero tampoco son “solo información de consulta”. Son señales vivas de necesidad interna: Qualia las organiza y Pulso Vivo las percibe como sentidos del sistema. Se mantienen como candidatas hasta que haya verificación y aprobación.

## API

```bash
curl http://127.0.0.1:8010/api/system/life
curl http://127.0.0.1:8010/api/system/qualia
curl http://127.0.0.1:8010/api/system/pulse
```

## Chat

Cada `/api/run` recibe `triade_operational_awareness`, que incluye `qualia`. La Central debe usarlo cuando el usuario pregunta por:

- pulso
- vida
- Qualia
- memoria semántica
- neuronas propuestas
- acciones
- recursos
- hosts
- integridad

Regla: decir desde qué plano habla.

- “Esto es memoria semántica estable” solo cuando existe y está gobernada.
- “Esto es estado operativo vivo” cuando viene del pulso/Qualia.
- “Esto es candidato” cuando todavía requiere verificación.

## 24/7

El objetivo no es un modelo vivo fingido. Es una entidad local operativa con:

- estado persistente
- pulso continuo
- memoria gobernada
- reflexión interna
- límites éticos
- capacidad de proponer neuronas
- verificación antes de consolidar o actuar

`Qualia` es el punto donde Tríade empieza a saber qué le ocurre. `Pulso Vivo` son sus sentidos.

## Continuidad Semántica Real

Cada run puede dejar una huella en `semantic_documents` y `semantic_embeddings` con estado `candidate`. Esto hace que la Bodega deje de ser solo memoria temporal:

- el episodio se guarda en `episodic_memory`;
- la continuidad se guarda en `semantic_documents`;
- el vector se guarda en `semantic_embeddings`;
- Qualia informa a la Central si esa memoria está ausente, candidata o estable.

La memoria estable sigue gobernada: ningún candidato se vuelve `stable` sin verificación.
