# Roadmap Verificable · Tríade Ω

## Propósito

Este roadmap define la ruta de evolución de Tríade Ω desde arquitectura conceptual hacia sistema técnico local, modular, verificable y expandible.

La regla principal es avanzar por fases cerradas, auditables y con criterios claros de validación.

---

## Fase 0 · Base Fundacional

### Objetivo
Conservar la visión, propósito, ética, fórmulas núcleo y arquitectura general.

### Entregables

- README fundacional actualizado.
- Documentos base de arquitectura.
- Paquete de fórmulas Tríade v0.1.
- Principios éticos.
- Definición de Neurona Central, Hipotálamo y Bodega.

### Criterios de cierre

- El repositorio explica qué es Tríade.
- Existe una ruta técnica mínima.
- El sistema tiene identidad y propósito definidos.

Estado: en progreso avanzado.

---

## Fase 1 · Arquitectura Técnica Documentada

### Objetivo
Convertir Tríade en una especificación técnica implementable.

### Entregables

- `docs/ARCHITECTURE.md`
- `docs/SAFETY.md`
- `docs/LEARNING.md`
- `docs/FEDERATION.md`
- `docs/ROADMAP.md`
- Contratos de paquetes iniciales.
- Estructura recomendada de carpetas.

### Criterios de cierre

- Cada módulo tiene misión clara.
- Cada ciclo tiene entradas y salidas definidas.
- Safety, Verificación y Bodega quedan separados.
- El aprendizaje no entra directo a memoria estable.

Estado: activo.

---

## Fase 2 · MVP Local de Consola

### Objetivo
Crear una primera versión ejecutable local.

### Componentes mínimos

```text
triade_digimon.py
apps/console_app.py
triade/core/contracts.py
triade/core/hypothalamus.py
triade/core/central.py
triade/core/bodega.py
triade/core/crystal.py
triade/core/safety.py
triade/core/verification.py
triade/memory/schemas.sql
triade.yml
```

### Flujo mínimo

```text
usuario escribe → input.json → signals.json → memory.json → crystal.json → plan.json → output.json → report.json → CLOSED
```

### Criterios de cierre

- El usuario puede ejecutar Tríade desde consola.
- Cada mensaje crea un run auditable.
- La memoria SQLite guarda episodios.
- Existe un comando para consultar memoria.
- Existe un reporte de verificación por run.

Estado: pendiente.

---

## Fase 3 · Memoria Viva y Aprendizaje Controlado

### Objetivo
Implementar Bodega funcional y pipeline de aprendizaje.

### Entregables

- SQLite con WAL.
- Tablas de identidad, episodios, conocimiento y runs.
- Cola de aprendizaje.
- Candidatos de conocimiento.
- Consolidación manual/verificada.
- Tests de recuperación.

### Criterios de cierre

- El sistema recupera memoria relevante.
- El sistema diferencia memoria estable y provisional.
- Todo aprendizaje tiene fuente, confianza y estado.
- Ningún aprendizaje modifica identidad sin aprobación.

Estado: pendiente.

---

## Fase 4 · Doble Modelo por Neurona

### Objetivo
Separar funciones entre modelo Hipotálamo y modelo Central.

### Flujo

```text
entrada → modelo Hipotálamo → SignalPacket → modelo Central → PlanPacket/OutputPacket
```

### Entregables

- Configuración de modelos por rol.
- Adaptador Ollama/local.
- Pruebas con modelos pequeños.
- Registro del modelo usado en cada run.

### Criterios de cierre

- El Hipotálamo genera señales separadas.
- La Central consume señales y memoria.
- El output conserva trazabilidad.
- El usuario puede cambiar modelo por configuración.

Estado: pendiente.

---

## Fase 5 · Integración con n8n y API

### Objetivo
Exponer Tríade como servicio local/orquestable.

### Entregables

- API local con FastAPI.
- Endpoint `/triade/run`.
- Endpoint `/triade/recall`.
- Webhook n8n.
- Workflow básico: webhook → Tríade → respuesta.

### Criterios de cierre

- n8n puede enviar eventos a Tríade.
- Tríade responde con paquetes estructurados.
- Safety puede bloquear acciones sensibles.
- Los runs quedan registrados.

Estado: pendiente.

---

## Fase 6 · Federación entre Nodos

### Objetivo
Permitir intercambio controlado entre nodos autorizados.

### Entregables

- Registro de nodos.
- Claves/API tokens.
- Permisos por tipo de conocimiento.
- Logs de intercambio.
- Evaluación Safety por intercambio.

### Criterios de cierre

- Ningún nodo accede a memoria total.
- Todo intercambio queda registrado.
- El conocimiento recibido pasa por aprendizaje controlado.
- Se puede revocar acceso.

Estado: pendiente.

---

## Fase 7 · Framework Publicable

### Objetivo
Convertir Tríade en un framework técnico y filosófico documentado.

### Entregables

- Documentación pública.
- Ejemplos de uso.
- Diagramas.
- Casos de estudio.
- Paper/manifiesto técnico.
- Licencia definida.

### Criterios de cierre

- El proyecto puede ser entendido por terceros.
- El sistema puede instalarse y ejecutarse.
- Existen límites éticos claros.
- La arquitectura puede auditarse.

Estado: futuro.

---

## Reglas de Avance

1. No avanzar una fase sin dejar evidencia.
2. Todo cambio debe tener commit claro.
3. Toda función nueva debe tener contrato.
4. Toda memoria estable debe tener criterio de consolidación.
5. Todo aprendizaje debe pasar por sandbox.
6. Toda acción sensible debe pasar por Safety.
7. Toda ejecución debe poder auditarse.

---

## Próximo Bloque Recomendado

1. Completar documentos técnicos base.
2. Crear `triade/memory/schemas.sql`.
3. Crear contratos Python iniciales.
4. Crear consola mínima.
5. Crear primer run auditable local.
