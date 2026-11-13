# Compatibilidad de contratos públicos

## Objetivo

Tríade Ω distingue entre estado interno detallado y contrato público estable. Los subsistemas pueden evolucionar hacia estados más expresivos sin romper clientes, paneles o pruebas que consumen valores históricos.

## Principio

Cada adaptación debe conservar dos vistas:

- **pública:** valor compatible y estable;
- **interna:** valor detallado que refleja el estado real.

La compatibilidad nunca debe ocultar errores, fingir disponibilidad ni convertir degradación en éxito.

## Ollama Blood

Cuando el estado interno es:

```text
degraded_no_ollama
```

la API pública puede exponer:

```text
degraded
```

junto con:

```json
{
  "internal_status": "degraded_no_ollama"
}
```

Esto permite que clientes antiguos continúen operando mientras los clientes nuevos reciben la causa exacta.

## Heartbeat y gobernador

Cuando el gobernador reduce una configuración `full_local_guarded` a `light_background`, la representación interna debe conservar ese valor.

Para clientes que aún reconocen `balanced_background`, la salida compatible puede incluir:

```json
{
  "heartbeat_truth": "Autonomía full_local_guarded configurada · degradada a balanced_background por gobernador",
  "internal_heartbeat_truth": "Autonomía full_local_guarded configurada · degradada a light_background por gobernador"
}
```

## Reglas

1. Nunca eliminar el valor interno.
2. Nunca mapear un fallo a `ok`.
3. Toda adaptación debe tener prueba dedicada.
4. Los campos compatibles deben marcarse como legado en documentación.
5. Los clientes nuevos deben preferir `internal_status` e `internal_heartbeat_truth`.
6. Las futuras retiradas requieren versión de API y periodo de transición.

## Evolución recomendada

La siguiente versión mayor debería exponer contratos versionados:

- `/api/v1/...`: compatibilidad histórica;
- `/api/v2/...`: estados internos canónicos.

Hasta entonces, la capa dual evita rupturas y mantiene trazabilidad.
