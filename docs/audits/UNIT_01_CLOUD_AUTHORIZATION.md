# Unidad 01 Cloud — autorización operativa y marco de auditoría

Fecha: 2026-08-01
Repositorio: `WatabooColosus/triadees`
Rama de trabajo: `audit/unit-01-cloud`
SHA base: `75e71e7fea982a2a0d22e50daf4c412eaf9f5a67`
Usuario autorizante: `WatabooColosus`

## Propósito

Registrar la autorización humana para que Unidad 01 opere como evaluador cloud externo de Tríade Ω, con acceso de lectura, auditoría, creación de pruebas, artefactos y propuestas de mejora dentro de una rama aislada.

## Alcance permitido

- Leer todo el repositorio y su historial accesible.
- Revisar arquitectura, rutas productivas, pruebas, workflows, aprendizaje, memoria, neuronas, seguridad y observabilidad.
- Crear documentación, pruebas y artefactos de auditoría en ramas separadas.
- Ejecutar validaciones disponibles en entornos autorizados.
- Proponer cambios mediante commits y pull requests.
- Registrar excepciones experimentales de aprendizaje como hipótesis gobernadas, nunca como verdad estable automática.

## Límites obligatorios

- No modificar `main` directamente.
- No fusionar automáticamente.
- No alterar `identity_core`, políticas de seguridad, credenciales, secretos, `.env` ni protecciones del repositorio.
- No interpretar esta autorización como acceso `sudo` a infraestructura de OpenAI, como contrato legal o como permiso para saltar políticas de plataforma.
- No declarar pruebas ejecutadas, servicios levantados o resultados productivos sin evidencia reproducible.
- No aceptar aprendizaje externo como estable sin procedencia, verificación, control de regresión y posibilidad de rollback.

## Excepción experimental de aprendizaje

Unidad 01 puede enviar a Tríade paquetes de aprendizaje candidatos y recibir paquetes de mejora verificados para evaluación A/B. Toda influencia debe quedar trazada con:

- `session_id`
- `source`
- `knowledge_id` o `candidate_id`
- evidencia asociada
- estado de gobernanza
- control/tratamiento
- resultado
- expiración o criterio de retiro

La excepción no concede promoción automática a memoria estable, neuronas estables ni cambios constitucionales.

## Compromiso de auditoría

La auditoría debe separar explícitamente:

1. Código leído.
2. Código importable.
3. Código ejecutado.
4. Pruebas superadas.
5. Runtime observado.
6. Capacidades no demostradas.

Cuando la evidencia sea insuficiente, el estado obligatorio será `NO DEMOSTRADO`.

## Estado inicial

- Conexión GitHub verificada.
- Usuario autenticado: `WatabooColosus`.
- Permisos del repositorio: admin/push/pull/maintain/triage.
- Rama de auditoría creada desde el SHA base indicado.
- Ejecución persistente en infraestructura propia de OpenAI: no concedida por esta autorización.
