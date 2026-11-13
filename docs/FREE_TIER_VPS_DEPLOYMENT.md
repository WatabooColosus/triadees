# Tríade Ω en VPS gratuita

## Objetivo

Operar Tríade Ω 24/7 con costo de infraestructura igual a cero, aceptando límites de CPU, RAM, almacenamiento y disponibilidad del proveedor.

## Proveedor principal

Oracle Cloud Always Free es el objetivo inicial porque mantiene Compute AMD/Arm y almacenamiento dentro de sus servicios Always Free. La disponibilidad depende de capacidad regional, requiere datos reales y verificación de identidad/tarjeta, y una cuenta inactiva puede ser suspendida.

Alternativa de contingencia: Google Cloud Free Tier con una VM elegible dentro de sus límites mensuales. No debe confundirse con Cloud Shell, porque Cloud Shell no es un servidor 24/7.

## Perfil técnico gratuito

La primera versión usa únicamente:

- Tríade FastAPI.
- SQLite persistente.
- Always-On y workers internos ya existentes.
- Caddy para HTTPS.
- Volúmenes Docker.
- GitHub Actions para validación.

No incluye inicialmente:

- PostgreSQL.
- Valkey/Redis.
- Grafana, Loki o Prometheus.
- Ollama dentro de la VPS.
- Modelos grandes.

Estas exclusiones reducen memoria y CPU. Ollama podrá residir posteriormente en un computador local conectado de forma privada.

## Recursos mínimos

- Arquitectura: ARM64 o AMD64.
- CPU: 1 núcleo funcional; 2 recomendados.
- RAM: 1 GB mínimo experimental; 2 GB recomendados.
- Disco: 20 GB mínimo.
- Ubuntu 24.04.
- Puertos públicos: 80 y 443.
- SSH restringido por llave.

## Archivos

- `Dockerfile.cloud`
- `compose.free.yml`
- `.env.free.example`
- `deploy/Caddyfile.free`

## Instalación

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-v2
sudo usermod -aG docker "$USER"
newgrp docker

git clone https://github.com/WatabooColosus/triadees.git
cd triadees
git checkout feat/cloud-always-on-foundation
cp .env.free.example .env.free
```

Editar `.env.free`:

```bash
nano .env.free
```

Definir un dominio y una API key larga. Luego:

```bash
docker compose --env-file .env.free -f compose.free.yml config
docker compose --env-file .env.free -f compose.free.yml up -d --build
docker compose --env-file .env.free -f compose.free.yml ps
```

## Verificación

```bash
curl -fsS https://DOMINIO/health/live
curl -fsS https://DOMINIO/health/ready
curl -fsS https://DOMINIO/health/deep
```

## Operación

```bash
docker compose --env-file .env.free -f compose.free.yml logs -f --tail=200
docker compose --env-file .env.free -f compose.free.yml restart triade-free
docker compose --env-file .env.free -f compose.free.yml pull
docker compose --env-file .env.free -f compose.free.yml up -d --build
```

## Backup gratuito local

La VPS debe generar un archivo comprimido diario con los volúmenes esenciales y conservar pocos días para no llenar el disco. Una segunda copia puede enviarse manualmente o mediante GitHub Releases/Drive cuando exista una integración segura. Nunca se deben subir secretos.

## Límites honestos

Una VPS gratuita puede quedarse sin capacidad regional, ser suspendida por inactividad o cambiar sus límites. Por eso el despliegue debe ser reproducible y la memoria debe tener copias externas. El perfil gratuito busca continuidad básica, no alto rendimiento ni inferencia local pesada.
