# Despliegue Local en PC · Tríade Ω

## Veredicto

Con la PC disponible sí se puede correr Tríade Ω como sistema local real.

Equipo de referencia documentado:

```text
CPU: Intel Core i7-3770 / 8 hilos
GPU: NVIDIA GeForce GTX 1070
RAM: 16 GB
Disco: ~1.7 TB
Sistema recomendado: Ubuntu 24.04 LTS
```

Este equipo es suficiente para:

- Ejecutar Tríade Ω MVP con Python.
- Guardar memoria persistente en SQLite.
- Generar runs auditables.
- Ejecutar consola interactiva.
- Ejecutar modelos locales pequeños o medianos vía Ollama.
- Servir una API local con FastAPI.
- Integrarse con n8n en red local.

---

## 1. Capacidades Reales por Nivel

### Nivel 1 · Tríade MVP SQLite

Estado: viable inmediatamente.

Comandos:

```bash
git clone https://github.com/WatabooColosus/triadees.git
cd triadees
python3 triade_digimon.py run "Hola Tríade, registra este run local"
python3 triade_digimon.py chat
python3 triade_digimon.py recall memoria
```

Requisitos:

- Python 3.10+
- SQLite incluido en Python

---

### Nivel 2 · Tríade con entorno virtual y pruebas

Estado: recomendado.

```bash
cd ~/triadees
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install pytest
pytest
```

---

### Nivel 3 · Tríade con modelo local Ollama

Estado: viable con modelos ligeros/medianos.

Modelos recomendados para esta PC:

```text
qwen2.5:3b-instruct
llama3.2:3b
phi3:mini
mistral:7b-instruct-q4
llama3:8b-instruct-q4
```

Notas:

- 3B corre más cómodo.
- 7B/8B cuantizado puede correr, pero más lento.
- GTX 1070 ayuda, pero por VRAM y compatibilidad conviene probar primero modelos pequeños.

Comandos base:

```bash
ollama serve
ollama pull qwen2.5:3b-instruct
ollama run qwen2.5:3b-instruct
```

---

### Nivel 4 · Tríade API Local

Estado: siguiente fase técnica.

Objetivo:

```text
POST /triade/run
GET /triade/recall
GET /triade/health
```

Uso:

- Conectar n8n.
- Conectar dashboard web.
- Conectar otras máquinas autorizadas.
- Exponer Tríade dentro de la red local.

---

### Nivel 5 · Tríade 24/7 en la PC

Estado: viable si la PC permanece encendida.

Recomendado:

- systemd service para Tríade API.
- n8n como servicio aparte.
- backups de `triade.db`.
- firewall local.
- acceso externo solo con túnel seguro o VPN.

No recomendado inicialmente:

- Abrir puertos públicos sin autenticación.
- Exponer Tríade directamente a internet.
- Guardar secretos en archivos públicos.

---

## 2. Arquitectura Recomendada en la PC

```text
PC Ubuntu
├── triadees/                 # Código desde GitHub
│   ├── triade_digimon.py
│   ├── triade/
│   ├── docs/
│   ├── tests/
│   └── runs/
├── data/
│   └── triade_backups/       # Copias de seguridad
├── ollama/                   # Modelos locales
├── n8n/                      # Orquestación futura
└── services/
    └── triade-api.service    # Servicio futuro systemd
```

---

## 3. Instalación Recomendada

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip sqlite3 curl

git clone https://github.com/WatabooColosus/triadees.git ~/triadees
cd ~/triadees

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install pytest

python triade_digimon.py run "Primer run real en PC local"
python triade_digimon.py recall run
pytest
```

---

## 4. Diagnóstico Manual

```bash
cd ~/triadees
source .venv/bin/activate
python --version
python triade_digimon.py run "diagnóstico local"
ls -la runs/
sqlite3 triade/memory/triade.db ".tables"
sqlite3 triade/memory/triade.db "SELECT id, run_id, title, created_at FROM episodic_memory ORDER BY id DESC LIMIT 5;"
```

---

## 5. Límites del Equipo

La PC puede correr Tríade, pero hay que cuidar:

- RAM: 16 GB limita modelos grandes.
- CPU antigua: modelos 7B/8B pueden ser lentos.
- GPU GTX 1070: útil, pero no equivalente a GPUs modernas para IA.
- No conviene abrir servicios públicos sin seguridad.

---

## 6. Mejor Ruta de Evolución

### Paso A
Correr MVP SQLite local.

### Paso B
Agregar comando `doctor`.

### Paso C
Agregar adaptador Ollama.

### Paso D
Separar modelo Hipotálamo y modelo Central.

### Paso E
Crear API FastAPI.

### Paso F
Conectar n8n.

### Paso G
Crear servicio systemd 24/7.

---

## Estado

La PC disponible se considera apta para correr:

```text
Tríade Ω Local MVP + SQLite + Runs auditables + Ollama ligero
```

Estado recomendado:

```text
LOCAL_PC_READY_FOR_TRIADE_0.1
```
