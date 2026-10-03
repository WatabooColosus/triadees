# Tríade Ω · Stack OSS 8GB-first

## Regla de integración

Tríade no absorbe repositorios completos como dependencias estructurales. Cada
proyecto externo entra detrás de un contrato reemplazable y conserva su licencia.
El núcleo Tríade sigue siendo Central + Hipotálamo + Bodega + gobierno.

El objetivo es un portátil de aproximadamente 8 GB de RAM y GPU pequeña o
ausente. "8GB-first" es un perfil que debe certificarse con mediciones reales;
no significa que todo modelo vaya a caber ni que exista rendimiento idéntico en
cada equipo.

## Proyectos seleccionados

| Proyecto | Licencia observada | Papel en Tríade | Decisión |
|---|---|---|---|
| ggml-org/llama.cpp | MIT | inferencia GGUF CPU/GPU híbrida y API local | integrado como proveedor alternativo |
| Ollama | MIT | servidor de modelos existente | se conserva; compite A/B con llama.cpp |
| asg017/sqlite-vec | MIT / Apache-2.0 | KNN vectorial dentro de SQLite | siguiente integración, detrás de feature flag |
| ggml-org/whisper.cpp | MIT | STT local cuantizado | órgano opcional bajo demanda |
| k2-fsa/sherpa-onnx | Apache-2.0 | VAD/STT/TTS/keyword spotting | opcional; no residente |
| qdrant/fastembed | Apache-2.0 | embeddings ONNX ligeros | candidato de fallback, no default |
| asg017/sqlite-lembed | licencia no localizada en la raíz auditada | embeddings GGUF dentro de SQLite | no se copia ni integra hasta aclarar licencia |

También se evaluaron servidores/frameworks más amplios. No se adoptan como base
si duplican orquestación, memoria o gobierno que Tríade ya posee.

## Arquitectura 8GB-first

```text
                    TRÍADE Ω
        ┌──────────────┼──────────────┐
        │              │              │
     Central      Hipotálamo       Bodega
        │              │              │
        └────── contrato de motor ─────┘
                       │
             ┌─────────┴─────────┐
             │                   │
          Ollama             llama.cpp
             │                   │
             └── 1 modelo activo ┘

Bodega SQLite
  ├─ tablas y FTS/keyword: siempre disponibles
  ├─ sqlite-vec: acelerador opcional
  └─ embeddings: sólo al ingerir/buscar cuando aporten valor

Voz
  ├─ whisper.cpp: STT on-demand
  └─ sherpa-onnx: capacidades de voz avanzadas on-demand
```

## Restricciones del perfil

1. Un solo modelo generativo residente.
2. Una sola inferencia paralela.
3. Contexto inicial de 4096 tokens.
4. Modelo pequeño para continuidad; modelo mayor sólo si Resource Governor lo permite.
5. No cargar PyTorch/Transformers en el núcleo de 8 GB.
6. Redis es opcional y sólo se usa en despliegues distribuidos.
7. PEFT/LoRA es laboratorio, no metabolismo continuo.
8. Embeddings persistidos en disco; no mantener el encoder residente.
9. Voz se carga por evento y se libera después.
10. Heartbeat, scheduler, seguridad y memoria no usan GPU.

## Dependencias

`requirements-low-resource.txt` instala el núcleo sin:

- PyTorch / Transformers vía sentence-transformers;
- PEFT;
- Accelerate;
- Redis.

`pyproject.toml` separa esos componentes en extras:
`semantic-heavy`, `training`, `distributed`, `server-full` y `full-local`.

## Motores

El proveedor puede elegirse sin reescribir Central/Hipotálamo:

```bash
TRIADE_MODEL_PROVIDER=ollama
# o
TRIADE_MODEL_PROVIDER=llama.cpp
TRIADE_MODEL_BASE_URL=http://127.0.0.1:8080
```

La promoción de un proveedor debe depender de medición A/B, no de preferencia.

## Certificación

```bash
python scripts/benchmark_low_resource_stack.py --provider ollama --model qwen2.5:1.5b
python scripts/benchmark_low_resource_stack.py --provider llama.cpp --model <modelo-expuesto>
```

Comparar al menos:

- RSS del proceso Tríade;
- RAM libre antes/después;
- VRAM libre antes/después;
- latencia;
- tokens/s cuando el backend la reporte;
- calidad de respuestas sobre el mismo corpus;
- liberación efectiva del modelo;
- estabilidad del heartbeat mientras el modelo está descargado.

No se promueve un motor/modelo como default hasta que pase estas pruebas en el
hardware objetivo.

## Siguiente etapa: sqlite-vec

La memoria actual persiste vectores en JSON y la búsqueda puede recorrerlos en
Python. El siguiente paso es mantener esa tabla como fuente auditable y añadir
un índice `vec0` opcional. Si la extensión no está instalada, Tríade conserva
el camino actual sin perder memoria ni disponibilidad.

Esto evita hacer de sqlite-vec una dependencia dura mientras sigue en pre-v1.
