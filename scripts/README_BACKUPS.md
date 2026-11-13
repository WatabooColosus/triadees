# Backups locales de SQLite · Tríade Ω

## Objetivo

Proteger la memoria local de Tríade antes de ejecutar el sistema como servicio 24/7.

Base por defecto:

```text
triade/memory/triade.db
```

Carpeta recomendada:

```text
backups/
```

---

## Crear backup manual

Desde la raíz del repo:

```bash
mkdir -p backups
sqlite3 triade/memory/triade.db ".backup 'backups/triade-backup.db'"
```

Con fecha:

```bash
mkdir -p backups
sqlite3 triade/memory/triade.db ".backup 'backups/triade-$(date +%Y%m%d-%H%M%S).db'"
```

---

## Verificar backup

```bash
sqlite3 backups/triade-backup.db ".tables"
```

---

## Restaurar backup

1. Detener servicio si está activo:

```bash
sudo systemctl stop triade-api
```

2. Copiar backup sobre la base actual:

```bash
cp backups/triade-backup.db triade/memory/triade.db
```

3. Levantar servicio:

```bash
sudo systemctl start triade-api
```

---

## Recomendación

Antes de actualizar código con `git pull` en producción local:

```bash
sqlite3 triade/memory/triade.db ".backup 'backups/triade-before-update.db'"
git pull
pytest
```
