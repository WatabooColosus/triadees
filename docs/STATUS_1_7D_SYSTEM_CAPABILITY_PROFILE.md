# Triade Omega - System Capability Profile 1.7D

## Fase

TRIADE_SYSTEM_CAPABILITY_PROFILE_1.7D

## Objetivo

Ampliar el perfil de hardware/software para que Triade pueda evidenciar si una maquina Windows o Linux puede correr correctamente los modelos y servicios locales.

## Archivos

- triade/models/hardware_profile.py
- tests/test_hardware_profile.py

## Datos detectados

- Sistema operativo
- Version del sistema
- Arquitectura
- Maquina
- Procesador
- CPU threads
- CPU cores aproximados
- RAM total
- RAM disponible
- Disco total
- Disco libre
- Python version
- Node version
- npm version
- Ollama version
- GPU basica
- VRAM cuando se puede detectar
- Driver NVIDIA cuando nvidia-smi existe
- CUDA disponible cuando nvidia-smi responde
- Tier: low, medium, high
- Capability notes

## Fuentes usadas

Linux:

- /proc/meminfo
- /proc/cpuinfo
- lspci si existe
- nvidia-smi si existe

Windows:

- platform
- ctypes para RAM
- wmic si existe para GPU

General:

- shutil.disk_usage
- os.cpu_count
- node -v
- npm -v
- ollama --version

## Validacion local

Ejecutar:

- git pull
- source .venv/bin/activate
- pytest
- sudo systemctl restart triade-chat-ui
- curl http://127.0.0.1:8010/api/health

En /api/health deben verse hardware, ollama y doctor.

## Siguiente fase sugerida

TRIADE_MODEL_COMPATIBILITY_MATRIX_1.7E

Objetivo: generar matriz de compatibilidad por modelo con estados:

- recommended
- allowed
- risky
- blocked

segun RAM, VRAM, CPU, tier y disponibilidad de Ollama.
