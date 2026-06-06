# Core Scorecard

Fecha: 2026-06-05

Escala: 0-10, donde 10 significa claro, estable, verificable, modular y listo para evolucionar.

| Area | Score | Lectura |
| --- | ---: | --- |
| Central | 7 | Plan y respuesta claros, fallback seguro, pero prompts/calidad siguen dentro de clases generales. |
| Hipotalamo | 7 | Señales estructuradas y fallback por reglas; intención/riesgo todavía hardcodeados. |
| Bodega | 7 | Persistencia real y trazabilidad fuerte; demasiadas responsabilidades en un módulo. |
| Cristal | 8 | Fórmula, temporalidad e historial comparativo ya verificables; falta separar política/umbrales. |
| Memoria episodica | 7 | Guarda episodios por run y permite recall simple; resumen/tags son básicos. |
| Memoria semantica | 6 | Store, embeddings, búsqueda y gobernanza existen; DB real analizada no tiene contenido semántico. |
| Model router | 8 | Selección por rol/hardware y fallback documentado; falta latencia/calidad comparativa real. |
| CLI | 7 | Cubre run, chat, doctor, modelos, learning y análisis; archivo monolítico. |
| API | 7 | Endpoints útiles y compatibles; single-port mezcla dominios. |
| UI | 6 | Integra single-port; trazabilidad de fuente histórica necesita normalización. |
| Testing | 8 | Suite amplia y nuevas pruebas del analizador; faltan más pruebas end-to-end de fallback/model_events. |
| Observabilidad | 7 | Artefactos y DB por run completos; falta latencia y causa normalizada de fallback. |
| Mantenibilidad | 6 | Arquitectura funcional, pero runner, bodega, CLI y single-port deben dividirse. |

CORE_MATURITY_LEVEL = 7.0
