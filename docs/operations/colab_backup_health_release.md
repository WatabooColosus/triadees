# Paquete de corrección Colab: respaldo y salud del scheduler

Este paquete de una sola publicación incorpora los módulos
`triade/memory/encrypted_backup.py` y `triade/runtime/service_health.py`
corregidos en el PR #189. El canal utiliza copias exactas en
`tools/colab_patch_sources/` para respetar las rutas de código permitidas por
el actualizador R7 existente.

- El instalador comprueba SHA-256 del paquete, permisos de rutas, identidad del
  checkout R5 y las reglas habituales de continuidad antes de parchear.
- Si los archivos ya son idénticos, reutiliza el servicio, sin reiniciarlo.
- En otro caso guarda el código anterior bajo
  `work/actualizaciones/runtime_path_patches/`, detiene solamente la API propia,
  escribe ambos módulos con reemplazo atómico y reinicia el backend.
- `verify` compara los bytes de los módulos realmente instalados con las copias
  del paquete antes de guardar el recibo de versión en Drive.
- En fallo de instalación de archivos intenta restaurar los originales; un
  rollback de archivos no certifica la continuidad educativa.
- No sustituye claves, no borra ni restaura Bodega, no fusiona conocimiento ni
  modifica el registro de aprendizaje.
- La alarma `backup_key_configuration_degraded` **se mantiene** hasta que exista
  una clave utilizable; `repeated_worker_errors` sigue detectando fallos
  reales de workers.

La publicación debe usar una secuencia superior a 42, un SHA de commit
inmutable, hashes por componente y los tres gates **push** exigidos por el
actualizador: Runtime Truth CI, Python Tests, Tríade Tests.

El propietario aplica desde su panel **ENCENDER / ACTUALIZAR TRÍADE**. Después
comprobar `/api/health`, `/api/runtime/heartbeat`, los eventos de workers y
la evidencia de copia cifrada verificable desde Colab. CI verde no acredita por
sí sola que esos bloqueos se hayan resuelto en el organismo vivo.
