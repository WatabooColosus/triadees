# Reglas operativas de Tríade

Estas reglas se aplican a todo el repositorio y a cualquier sesión de Codex que opere el runtime desplegado.

## Diagnóstico y evidencia

- Antes de modificar archivos o servicios, inspecciona `git status`, la rama y `HEAD`, y compara la rama con `origin/main` usando referencias actualizadas.
- Diagnostica fallos con evidencia directa y correlacionada: endpoints vivos, configuración efectiva, código ejecutado, procesos, estado de servicios y logs del sistema.
- Distingue configuración declarada, configuración efectiva y estado observado. No presentes documentación, artefactos antiguos o filas históricas como prueba de actividad actual.
- Para migraciones o contratos ausentes, reconstruye el contenido desde el historial Git, referencias de código, esquema real y pruebas. No inventes estructuras ni evidencia.
- Conserva en la entrega los comandos, valores y marcas de tiempo necesarios para sustentar cada afirmación relevante.

## Protección de datos y alcance

- Trata la base de datos y los artefactos operativos como datos reales. No insertes, actualices ni borres filas para hacer pasar verificaciones de salud.
- No borres, reinicialices, reemplaces ni restaures bases de datos, colas, locks, runs o evidencias sin autorización explícita del usuario.
- Aplica la reparación mínima que resuelva la causa demostrada. Preserva cambios ajenos ya presentes en el árbol de trabajo.
- No incluyas secretos, credenciales, tokens ni valores temporales del servidor en código, documentación, commits o respuestas.
- No modifiques archivos fuera del repositorio, unidades systemd ni configuración del host sin autorización explícita solicitada en el momento de la acción.

## Validación y operación

- Ejecuta primero las pruebas directamente relacionadas con el cambio y luego la suite necesaria en proporción al riesgo. Informa fallos preexistentes por separado.
- Tras cambios de runtime, verifica los endpoints de liveness, salud profunda, Always-On, workers y heartbeat, además del proveedor de modelos local cuando corresponda.
- Para afirmar actividad real, demuestra progreso entre dos observaciones: ciclos o timestamps nuevos, workers vivos, runner continuo y metabolismo activo. No generes tráfico, tareas o actividad artificial para fabricar esa evidencia.
- Revisa los logs posteriores al cambio y confirma que el error reparado no reaparece.
- Reinicia únicamente los servicios que necesiten recargar el cambio y solicita autorización inmediatamente antes de cualquier reinicio o acción con `sudo`.

## Control de versiones

- No hagas `push`, `merge`, rebase, reset destructivo ni elimines ramas sin autorización explícita del usuario.
- No hagas commit salvo que el usuario lo solicite. Antes de entregar, muestra el estado y el diff exactos de los cambios realizados.
