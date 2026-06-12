# Living Neurons

## Estado real

Tríade ya ejecutaba neuronas experimentales dentro de un run mediante `run_experimental_neurons()` y guardaba evidencia con `NeuronActivityStore`. La capa Living Workers agrega continuidad operacional: las neuronas pueden observar el sistema periódicamente, registrar diagnósticos y producir evidencia sin esperar una conversación humana.

## Qué neuronas trabajan de fondo

- Neuronas `experimental` registradas en `neurons`, activadas por dominio/contexto mediante `experimental_neuron_runtime`.
- Neuronas candidatas formadas desde deuda del sistema mediante `background_neurons` + `neuron_formation_pipeline`.
- Autopromoter revisa candidatas y experimentales con reglas existentes, pero stable requiere readiness.
- Learning workers revisan `learning_queue` y pueden mover candidatos hasta `verified` o memoria semántica `experimental`.

## Límites

- Una neurona experimental no ejecuta acciones externas.
- No modifica repositorio ni memoria estable.
- No cambia identidad núcleo.
- No decide por la Central.
- Su salida es diagnóstico, test plan y evidencia.

## Ciclo vivo

```text
observe → extract candidate → evaluate → sandbox → verify → experimental memory/activity → measure → promote/reject
```

En esta implementación, la promoción a memoria estable queda fuera de la autonomía worker. Stable memory requiere evidencia, source_ref y aprobación explícita o política de trust aplicada fuera del worker.
