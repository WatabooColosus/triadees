# Aprendizaje prospectivo desde el panel continuo

El diagnóstico real de Colab del 26 de octubre de 2026 encontró siete lecciones
preparadas sin aplicaciones ni baseline. El único candidato verificado pertenecía
a `worker_failure`: el enrutador lo rechazaba por `no_compatible_neuron` y su
admisión conservaba `training_blocked: independent_transfer_evaluator_unavailable`.
El contenido era un objetivo de evitar un timeout, no una regla de transferencia
con un oráculo independiente. No se convierte ese objetivo en conocimiento aplicado.

El aprendizaje verificado forma parte del ciclo continuo interno. Al montar o
reutilizar el runtime verificado, Tríade lo inicia automáticamente y mantiene un
monitor de progreso idempotente; no hace falta ejecutar otra celda ni pulsar un
botón de inicio. El panel conserva una acción de consulta:

- **Ver circuito de aprendizaje** consulta modelos, lecciones, material, misiones,
  presupuestos y bloqueos de admisión sin modificar SQLite.

El arranque automático prepara el embedding que falte y ejecuta evaluaciones
experimentales acotadas, con las cuotas y los filtros nativos. Si un modelo,
presupuesto, evidencia o verificador no está disponible, el ciclo registra el
bloqueo y continúa con el resto de Tríade; no fuerza una aplicación insegura.

La solicitud explícita permite examinar ahora una neurona experimental aunque su
revisión ordinaria esté programada para después. No cambia esa fecha manualmente,
el estado de la neurona, los contratos, las cuarentenas ni las puertas de promoción.

El ciclo congela material autorizado antes de las primeras cinco pruebas reales.
Luego crea una nueva lección mediante el currículo oficial, conservando únicamente
el baseline de esa evaluación. Cinco pruebas posteriores pueden utilizar el material
mediante el recuperador experimental nativo, separado de memoria estable. No se
introducen respuestas de referencia en los prompts. Cada prueba exige respuestas
reales de Ollama, participación registrada de la neurona y un verificador seguro.
El recorder sólo asocia los runs de la nueva sesión. La resolución oficial puede
ser neutral, regresión o evidencia insuficiente; una diferencia antes/después no
se anuncia como mejora causal. Las sesiones antiguas sin baseline quedan intactas.

Las suites disponibles miden conceptos visuales por texto, razonamiento Python
por texto y comandos Android por texto. No acreditan procesamiento de imágenes,
ejecución de código, uso de dispositivos ni funcionamiento completo del sistema.
La inferencia se detiene ante un bloqueo no transitorio. Los presupuestos y los
trabajos activos se respetan; no se desactiva el modo protegido del backend.

Los checkpoints de progreso se guardan en el ámbito de memoria de Drive y se
contrastan con los runs presentes en SQLite al continuar. El guardián de copias
cifradas conserva su funcionamiento; una resolución solicita una copia verificada.
La instalación del paquete puede reutilizar API, Ollama y memoria sin reiniciarlos.

La interfaz reconstruye sus widgets al abrirse desde otro frontend, preservando
el contexto verificado y la preferencia del actualizador. Esto evita reutilizar
controles que Colab mostraba como `HTML(value=...)` en otra sesión del navegador.
