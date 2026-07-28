# Recuperación y persistencia de Ollama en Studio · 2026-07-28

## Objetivo

Restaurar el motor Ollama, verificar los modelos cognitivos de Tríade y evitar
que la instalación desaparezca con una reconstrucción del entorno de Studio.

## Causa encontrada

El binario `ollama` no existía en el sistema y no había blobs o manifiestos de
modelos. Solo sobrevivían archivos mínimos de configuración. La instalación
anterior no estaba declarada en el repositorio ni conectada al hook de arranque,
y dependía de una capa reemplazable de la instancia.

## Recuperación

- Ollama 0.32.5 instalado en `.ollama/runtime` del volumen persistente de Studio.
- Modelos almacenados en `.ollama/models`, no en el filesystem efímero.
- Catálogo declarado en `config/studio-models.txt`.
- Arranque y reconciliación automática desde `.lightning_studio/on_start.sh`.
- Reinstalación automática del runtime fijado a versión 0.32.5 si falta.
- Restauración automática de cualquier modelo declarado que falte.
- Límites de un modelo cargado y una inferencia paralela para 15 GiB de RAM.

## Modelos verificados

- `qwen2.5:3b-instruct`: razonamiento general.
- `qwen3:1.7b`: respuesta rápida.
- `qwen2.5-coder:3b`: código.
- `nomic-embed-text:latest`: embeddings de 768 dimensiones.
- `qwen3:4b`: profundidad moderada.

Todos fueron descargados con verificación de digest de Ollama y ejecutaron una
inferencia o embedding real. El diagnóstico de Tríade reportó `full_local`, sin
funciones degradadas y con todos los modelos requeridos presentes.

## Documentos fundacionales

Se mantienen localizados `triade_formulas_v0_1.pdf` y `Base.docx`. Esta fase no
altera identidad, órganos ni contratos cognitivos; restaura una dependencia ya
declarada en la política técnica vigente.

## Rollback

Retirar el hook de Ollama, detener el proceso y revertir los scripts/configuración.
Los modelos persistentes pueden conservarse para evitar otra descarga; eliminarlos
es una operación separada y no forma parte del rollback automático.
