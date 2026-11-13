# Federación entre Nodos · Tríade Ω

## Propósito

Este documento define el contrato y las reglas de la federación. El repositorio
implementa registro, permisos, transporte firmado, logs, Edge y contexto federado;
la operación sostenida con nodos remotos reales continúa experimental. En el corte
2026-07-23 no había nodos remotos activos.

La federación no significa sumar RAM/GPU como una sola máquina ni acceso total entre
sistemas. Significa intercambio limitado, autenticado, trazable y verificable de
evidencia, patrones, trabajos o especificaciones.

---

## 1. Principios

1. Permiso explícito.
2. Acceso mínimo necesario.
3. Trazabilidad completa.
4. Revocación posible.
5. Ningún acceso horizontal total.
6. Aprendizaje recibido siempre pasa por Safety.
7. Todo conocimiento externo entra como candidato, no como verdad estable.

---

## 2. Qué es un Nodo

Un nodo puede ser:

- Una instalación local de Tríade.
- Un servidor autorizado.
- Una instancia en otro equipo del usuario.
- Un flujo n8n autorizado.
- Un servicio API controlado.
- Un repositorio o agente con permisos definidos.

Cada nodo debe tener identidad, permisos y nivel de confianza.

---

## 3. FederatedNode

Estructura mínima:

```json
{
  "node_id": "string",
  "name": "string",
  "owner": "string",
  "endpoint": "string",
  "public_key": "string",
  "trust_level": "low|medium|high",
  "permissions": [],
  "status": "active|paused|revoked|archived",
  "created_at": "string",
  "updated_at": "string"
}
```

---

## 4. Permisos

Permisos posibles:

```text
send_knowledge
receive_knowledge
send_patterns
receive_patterns
send_neuron_specs
receive_neuron_specs
request_verification
request_sandbox_test
```

Permisos prohibidos por defecto:

```text
read_full_memory
write_stable_memory
modify_identity_core
execute_system_commands
access_private_files
access_credentials
```

---

## 5. Tipos de Intercambio Permitidos

### Conocimiento consolidado
Resumen o dato previamente verificado. El receptor vuelve a gobernarlo y no lo
acepta automáticamente como verdad.

### Patrón operativo
Método, plantilla, estrategia o flujo reutilizable.

### NeuronSpec
Especificación de una neurona candidata o estable.

### VerificationReport
Reporte de validación o prueba.

### LearningCandidate
Candidato enviado por otro nodo para revisión local.

---

## 6. FederatedExchangePacket

```json
{
  "exchange_id": "string",
  "source_node_id": "string",
  "target_node_id": "string",
  "exchange_type": "knowledge|pattern|neuron_spec|verification|learning_candidate",
  "payload": {},
  "permissions_used": [],
  "risk_level": "low|medium|high|critical",
  "safety_status": "approved|approved_with_warning|sandbox_only|requires_human_approval|blocked",
  "created_at": "string"
}
```

---

## 7. Flujo de Recepción

```text
paquete recibido
→ autenticación
→ validación de permisos
→ Safety
→ registro en federated_exchange_log
→ entrada a learning_queue
→ sandbox
→ verificación
→ decisión de Central
```

Regla: nada recibido por federación se consolida automáticamente.

Si no hay nodos online, Edge produce contexto local de recuperación y conserva la
ausencia de federación como evidencia; no simula nodos remotos.

---

## 8. Flujo de Envío

```text
solicitud de envío
→ selección de contenido autorizado
→ Safety
→ anonimización si aplica
→ creación de FederatedExchangePacket
→ firma / autenticación
→ envío
→ registro de salida
```

---

## 9. Niveles de Confianza

### low
Nodo nuevo o poco probado. Todo entra a sandbox.

### medium
Nodo conocido. Puede compartir candidatos y patrones, pero requiere verificación.

### high
Nodo altamente confiable. Puede acelerar evaluación, pero no saltar Safety.

---

## 10. Registro de Intercambio

Cada intercambio debe registrar:

- Nodo origen.
- Nodo destino.
- Tipo de paquete.
- Permisos usados.
- Fecha.
- Resultado Safety.
- Resultado Verificación.
- Decisión final.
- Hash o referencia del payload cuando aplique.

---

## 11. Revocación

Un nodo puede ser revocado si:

- Viola permisos.
- Envía contenido malicioso.
- Intenta modificar identidad.
- Solicita memoria privada.
- Pierde confianza.
- El usuario decide desconectarlo.

Estado final: `revoked`.

---

## 12. Relación con n8n

n8n puede actuar como orquestador, no como inteligencia central.

Puede:

- Recibir webhooks.
- Enviar eventos a Tríade.
- Activar flujos autorizados.
- Registrar outputs.
- Pedir aprobación humana.

No debe:

- Saltar Safety.
- Escribir memoria estable directamente.
- Modificar identidad núcleo.
- Compartir información sin permisos.

---

## 13. Regla de Privacidad

La memoria personal, estratégica o privada nunca se comparte por defecto.

Debe existir autorización específica por:

- Tipo de dato.
- Nodo destino.
- Propósito.
- Tiempo.
- Nivel de detalle.

---

## Estado

Documento inicial de federación creado para preparar una red privada de nodos Tríade con permisos, trazabilidad y aprendizaje controlado.
