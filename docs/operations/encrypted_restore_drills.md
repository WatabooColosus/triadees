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

## El modo del fichero se cierra en cada arranque

`scripts/triade_runtime.sh up` llama a `EncryptedBackup.ensure_key_file_mode()`
antes de levantar la app, e imprime el resultado. Existe porque la exigencia de
`0600` es correcta pero frágil ante el entorno: el reinicio del Studio devuelve
`0744` a todos los ficheros, y con la clave abierta no se crea **ni** se restaura
nada. El 2026-08-08 eso dejó al organismo trece horas sin una sola copia, con
cada `encrypted_backup` cayendo en `dead_letter` por lease expirado.

El arranque cierra el modo y lo dice (`status: tightened` con el modo anterior);
no lo silencia. `backup_protection_gaps` sigue midiendo el permiso en vivo,
porque puede volver a abrirse con el runtime ya levantado.

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
