# WORKLOG nivel 8

## Fase A ? baseline
- HECHO: inspeccionados Git, `origin/main`, workflows, ?rbol del repositorio y SQLite.
- EVIDENCIA: `reports/level8/baseline.json`, `reports/level8/baseline.md`; SHA `46728d2a3dbb8e5221ee160dbad3ce3ab4c148e8`; SQLite integrity `ok`, 107 tablas.
- FALTA: ejecutar diagn?stico individual de CI y demostrar cadena aprendizaje?uso?medici?n en runtime normal.
- RIESGO: los artefactos runtime no son reproducibles por s? solos; no se versionan.
- SIGUIENTE PASO: Fase B, clasificar fallos CI sin ocultarlos.

## Fase B ? CI, primer bloqueo
- HECHO: corregido el contrato obsoleto de metacognici?n: `SUBSYSTEM_STATUS=active`, coherente con la invocaci?n productiva en `triade/workers/worker_loop.py`.
- EVIDENCIA: `python -m pytest -q tests/test_activation_contracts.py` pasa.
- FALTA: revisar el resto de la suite y clasificar cualquier fallo adicional; no hay `gh` instalado para consultar runs remotos.
- RIESGO: los fallos hist?ricos de workflows remotos no pueden atribuirse sin sus logs.
- SIGUIENTE PASO: cerrar baseline CI local y auditar gates ampliados.

## Fase B ? estado
- HECHO: contratos de metacognici?n y tablas activas corregidos; prueba focalizada verde.
- EVIDENCIA: `reports/level8/ci_truth.json`, `reports/level8/ci_truth.md`; auditor?a ampliada en `reports/level8/autonomy_gates.json`.
- FALTA: aislar fallos restantes de la suite completa y ejecutar las fases D-K.
- RIESGO: no se puede afirmar CI remoto verde sin logs de GitHub.
- SIGUIENTE PASO: reparar la cadena learning?use?measurement sin insertar filas manuales.

## Fase B ? reparaciones posteriores
- HECHO: documentaci?n de autonom?a delegada, ejecuci?n dry-run serializada, cierre de staging tolerante a cuarentena y precedencia de `TRIADE_BACKUP_KEY_FILE`.
- EVIDENCIA: pruebas focalizadas verdes: autonom?a delegada, background service, backup gap, activation contracts.
- FALTA: suite completa y deuda de backups en Windows/ACL; el runner local reporta fallos de entorno por configuraci?n global de clave y chmod no fiable.
- RIESGO: no declarar CI verde hasta separar esos fallos de infraestructura Windows de regresiones de c?digo.
- SIGUIENTE PASO: aislar la configuraci?n de backup por ra?z/proceso y continuar con la suite.
