# FEDERATION_FLOW · Tríade Ω

## Propósito

La federación de Tríade Ω permite que múltiples nodos autorizados cooperen de forma controlada, verificable y auditable.

El objetivo no es compartir memoria completa ni ejecutar comandos arbitrarios, sino intercambiar capacidades, conocimiento y trabajo encapsulado bajo reglas de seguridad.

---

# Componentes actuales

## Federation Core

Ubicación:

```text
triade/federation/
```

Responsabilidades:

* Registro de nodos
* Gestión de permisos
* Gestión de confianza (trust)
* Control de intercambio federado
* Registro de auditoría
* Actualización de capacidades
* Gestión de estados

---

## Signed Transport

Ubicación:

```text
triade/federation/contracts.py
```

Características:

* HMAC SHA256
* Nonce
* Timestamp
* Verificación temporal
* Envelope firmado
* Validación de sandbox

Objetivo:

Garantizar integridad del transporte federado.

---

## Node Registry

Ubicación:

```text
triade/federation/federation.py
```

Responsabilidades:

* Registrar nodos
* Revocar nodos
* Pausar nodos
* Reactivar nodos
* Actualizar capacidades
* Consultar nodos disponibles

Estados:

```text
active
paused
revoked
archived
stale
```

---

## Node Live Registry

Ubicación:

```text
triade/federation/node_live_registry.py
```

Responsabilidades:

* Heartbeat
* TTL
* Detección de nodos inactivos
* Barrido automático

Objetivo:

Evitar que recursos desconectados sean considerados disponibles.

---

## Public Relay

Ubicación:

```text
apps/public_relay_app.py
```

Responsabilidades:

* Registro remoto
* Heartbeat remoto
* Cola de trabajos
* Auditoría de trabajos
* Distribución de APK Android
* Gestión de nodos navegador

---

## Pairing Portal

Ubicación:

```text
apps/federation_pairing_app.py
```

Responsabilidades:

* Emparejamiento
* Entrega de permisos iniciales
* Registro controlado
* Publicación de capacidades

---

## Mobile Node Agent

Ubicación:

```text
apps/mobile_node_agent.py
```

Responsabilidades:

* Nodo Android/Termux
* Ejecución controlada
* Scheduler cooperativo local
* Reporte de capacidades
* Gestión de trabajos

---

## Android Native Node

Ubicación:

```text
android/triade-node/
```

Responsabilidades:

* Nodo móvil nativo
* Relay Client
* Runtime local
* Comunicación con Relay

---

# Flujo actual

```text
Nodo
 ↓
Pairing
 ↓
Federation Registry
 ↓
Node Live Registry
 ↓
Public Relay
 ↓
Job Queue
 ↓
Execution
 ↓
Audit
 ↓
Learning Pipeline
```

---

# Permisos

Permitidos:

```text
send_knowledge
receive_knowledge
send_patterns
receive_patterns
send_neuron_specs
receive_neuron_specs
request_verification
request_sandbox_test
publish_capabilities
request_compute
```

Prohibidos:

```text
read_full_memory
write_stable_memory
modify_identity_core
execute_system_commands
access_private_files
access_credentials
```

---

# Trust Levels

```text
low
medium
high
```

---

# Deuda Técnica Actual

## Scheduler Federado

Pendiente:

* Selección automática de nodos
* Ranking de recursos
* Asignación inteligente de trabajos
* Balanceo de carga

---

## Observabilidad Federada

Pendiente:

* Vista global de nodos
* Heartbeats
* Capacidades
* Consumo de recursos
* Latencia

---

# Próxima Fase

Crear:

```text
triade/federation/scheduler.py
```

Objetivo:

Seleccionar automáticamente el mejor nodo para cada trabajo según:

* CPU
* RAM
* VRAM
* Trust
* Tier
* Disponibilidad
* Latencia

y convertir la federación en una red cooperativa real.
   
