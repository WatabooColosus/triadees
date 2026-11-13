# Operación local diaria · Tríade Ω

## Estado rápido

```bash
sudo systemctl status triade-api
curl http://127.0.0.1:8000/health
```

---

## Logs

Últimos eventos:

```bash
journalctl -u triade-api -n 80 --no-pager
```

En vivo:

```bash
journalctl -u triade-api -f
```

---

## Reinicio seguro

```bash
sudo systemctl restart triade-api
sudo systemctl status triade-api
curl http://127.0.0.1:8000/health
```

---

## Actualización desde GitHub

Antes de actualizar:

```bash
cd ~/triadees
mkdir -p backups
sqlite3 triade/memory/triade.db ".backup 'backups/triade-before-git-pull.db'"
```

Actualizar:

```bash
cd ~/triadees
source .venv/bin/activate
git pull
pip install -r requirements.txt
pytest
sudo systemctl restart triade-api
```

Validar:

```bash
curl http://127.0.0.1:8000/health
```

---

## Ver memoria reciente

```bash
sqlite3 triade/memory/triade.db "SELECT id, run_id, title, created_at FROM episodic_memory ORDER BY id DESC LIMIT 10;"
```

---

## Ver eventos de modelo

```bash
sqlite3 triade/memory/triade.db "SELECT role, provider, model_name, ok, quality_score, created_at FROM model_events ORDER BY id DESC LIMIT 10;"
```

---

## Si el puerto 8000 está ocupado

```bash
sudo ss -tulnp | grep :8000
```

Si hay una ejecución manual, detenerla antes de iniciar systemd.

Regla:

```text
No ejecutar al mismo tiempo `python triade_digimon.py api` y `triade-api.service` en el puerto 8000.
```

---

## Apagar servicio

```bash
sudo systemctl stop triade-api
```

---

## Encender servicio

```bash
sudo systemctl start triade-api
```

---

## Seguridad

- No publicar API key.
- No subir `.env`.
- No abrir puerto 8000 a internet sin protección adicional.
- Para red local, usar firewall y clave.
