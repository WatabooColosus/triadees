# Backups cifrados y restore drills

El runtime agenda `encrypted_backup` cada 24 horas. Después de crear y verificar
un backup nuevo, el worker intenta un restore drill; el ledger aplica un cooldown
de siete días, por lo que las ejecuciones intermedias quedan `blocked` de forma
esperada.

Configure la clave fuera del repositorio:

```bash
install -d -m 700 /ruta/segura
python - <<'PY' > /ruta/segura/triade_backup.key
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
chmod 600 /ruta/segura/triade_backup.key
export TRIADE_BACKUP_KEY_FILE=/ruta/segura/triade_backup.key
python scripts/runtime_backup.py
```

No copie la clave a Git ni a artifacts. El comando falla si el archivo permite
lectura o escritura a grupo u otros usuarios.

La verificación obligatoria incluye integridad SQLite, anchor de identidad,
conteo de memoria semántica, estados de tareas y existencia de referencias de
artifacts. El restore drill escribe en `artifacts/restore-drills`; nunca reemplaza
la base productiva. Un restore productivo requiere `human_approved=True` y crea
antes otro backup cifrado.

Para revisar el historial:

```bash
sqlite3 triade/memory/triade.db \
  "SELECT drill_id,status,integrity_check,created_at FROM backup_restore_drills ORDER BY created_at DESC;"
```

Los snapshots antiguos de watchdog se conservan comprimidos en
`artifacts/recovery/quarantine`. Cada `.db.gz` tiene un manifiesto `.db.gz.json`
con hashes de archivo y contenido. `RuntimeRecovery.restore_archived_snapshot`
verifica ambos hashes e integridad SQLite antes de escribir el destino.

## Una copia se comprueba antes de escribirla

`create()` ejecuta `PRAGMA integrity_check` sobre el snapshot **antes** de
comprimirlo y cifrarlo, y **se niega a escribir** si el origen está dañado
(`status: failed`, `reason: source_database_malformed`). El resultado queda
anotado en el manifiesto como `source_integrity`, para que saberlo no cueste
descifrar 60 MB.

Por qué existe: el 2026-08-08 la base de producción se corrompió entre dos
copias. La siguiente se creó a partir de ella y se archivó como si estuviera
bien, y era **la más reciente** — la que cualquiera habría elegido para
restaurar. Nadie lo supo hasta que hizo falta restaurar de verdad. Si el fallo
hubiera tardado unas horas más en notarse, las nueve copias buenas habrían
rotado hasta desaparecer.

Un backup que archiva corrupción es peor que no tenerlo: aparenta protección y
además **desplaza** a las copias que sí servían.

Negarse a escribir es deliberado. La alternativa —guardarla marcada como
sospechosa— deja la decisión para el peor momento posible, que es cuando hay que
restaurar con prisa. Al no escribirse, la copia buena anterior sigue siendo la
más reciente, y `backup_protection_gaps` empieza a avisar por antigüedad: la
falta se ve por dos vías en vez de por ninguna.

`backup_protection_gaps` mide ahora cuatro cosas, no tres: sin clave, clave con
permisos abiertos, copia caducada, copia sin huella de clave — y **copia cuyo
manifiesto no acredita que su origen estuviera íntegro**.
