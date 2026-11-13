# Objetivos de confiabilidad de producción

Estado: `proposed`, no `runtime verified`.

Estos objetivos convierten los gates técnicos en un contrato operacional. No se
presentan como SLO cumplidos hasta tener 72 horas, capacidad medida y operación
fuera del Cloudspace.

## SLO provisional

- Disponibilidad mensual del endpoint `/health/live`: **>= 99%**.
- Efectos duplicados, tareas perdidas, falsos `completed`, corrupción SQLite,
  resultados tardíos aceptados y pérdida de artifacts: **0**.
- Rollback de capacidades reversibles verificadas: **100%**.
- Restore drill cifrado: al menos uno exitoso cada siete días.

Para 99% mensual, el presupuesto teórico de indisponibilidad es 7 h 18 min en
un mes de 30.4375 días. Este cálculo no concede permiso para consumirlo; alertas
deben dispararse al 25%, 50%, 75% y 100%.

## RTO y RPO provisionales

- RTO propuesto: **15 minutos** desde detección hasta health e integridad
  restaurados. Estado: `unverified`; chaos debe registrar recovery time.
- RPO propuesto: **24 horas** para SQLite bajo backup diario. Estado:
  `unverified`; el intervalo configurado no sustituye una prueba de pérdida y
  restore.
- RPO de identity manifest y artifacts referenciados: **0 referencias perdidas**
  dentro de cada backup verificado.

## Alertas externas pendientes

- disponibilidad y latencia;
- corrupción o lock SQLite persistente;
- backlog/leases expiradas y falsos cierres;
- fallo o retraso del backup/drill;
- crecimiento de snapshots, artifacts y disco;
- reinicios de worker/API/watchdog;
- Ollama sin modelo razonador o GPU degradada;
- consumo de 25/50/75/100% del presupuesto de error.

La implementación local expone datos para estas señales, pero no existe todavía
un receptor externo persistente. Hasta configurarlo y probar entrega, el estado
de alertas es `pending_external`.

## Gate de adopción

Promover estos valores de `proposed` a `approved` exige:

1. 24 h y 72 h completas sobre el mismo SHA;
2. benchmark de capacidad con usuarios/tareas concurrentes y límites de RAM,
   VRAM, disco y latencia;
3. restore drill y recovery time medidos;
4. dominio/TLS/ingress persistentes;
5. propietario nominal y canal externo de alertas.
