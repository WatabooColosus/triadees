# Tríade Ω · Colab R7 — Centro de Control

R7 es un notebook independiente del R5 original, almacenado en la carpeta **Colab Notebooks** del Drive del propietario; el archivo no se publica en GitHub porque contiene la fuente R5 autocontenida y detalles específicos de la cuenta. El controlador general, `tools/triade_colab_r7_control.py`, sí está versionado aquí.

## Arranque

1. Abrir el notebook `TRIADE_OMEGA_COLAB_R7_CENTRO_CONTINUIDAD.ipynb` en Drive.
2. Ejecutar **solo la primera celda de código** para montar el panel.
3. Pulsar **Iniciar / recuperar**. R7 instala R5 fijado en `8fdd397b...`, conecta la copia V2 y comprueba identidad. **Antes de iniciar la API**, examina copias R5/R7 verificadas en Drive, elige una no regresiva y detiene el arranque si no puede acreditar la versión más reciente.
4. Comprueba Ollama, API 8010, guardian y la versión elegida. El frontal React requiere el login habitual.

## Actualizaciones

- Versión base R5: `8fdd397b...` (reproducible).
- R6.3.1-rc: `ada140cf...`, **candidata**, requiere aprobación `ACTUALIZAR R6.3.1`; usa los instaladores secuenciales R6.2/R6.3/R6.3.1, no mueve `HEAD`, no cambia identidad ni sobrescribe snapshot fuente.
- El panel muestra la versión realmente en ejecución y consulta `main`, pero **nunca instala automáticamente un `main` móvil**.
- Guarda `version_preferida.json` en `MyDrive/Triade/operacion_colab_r7`, de modo que una nueva sesión puede rehidratar la misma selección.

## Memoria y continuidad

- Revisa el índice canónico V2 intacto y los guardianes R5 y R7; valida SHA256, integridad SQLite, propietario, recuentos, linaje y fecha.
- Guardián R7 crea imágenes WAL-consistentes con índices verificados en `operacion_colab_r7/snapshots`, intenta un nuevo respaldo cada 600 s, siempre que Drive tenga espacio. No elimina automáticamente historiales del usuario. No se ejecuta junto al guardián R5 conocido.
- Marca de agua `ultimo_estado_observado.json`: último recuento visto, **no es un respaldo**. Si el respaldo recuperable resulta anterior, el arranque falla cerrado. Existe recuperación manual explícita de una copia anterior con `ACEPTO COPIA ANTERIOR`.
- Si Colab apaga el runtime, ninguna CPU/GPU/workers sigue funcionando. Para reanudar, es necesario abrir el notebook y ejecutar la primera celda. No se promete continuidad de los últimos eventos anteriores a la próxima copia.

## Evidencia y precauciones

Cinco tests locales del motor de restauración superados. Sin prueba end-to-end en una sesión Colab recién reconstruida. No fusionar al núcleo estable ni afirmar aprendizaje funcional sin pruebas de integración y registro de runs auténticos.

No registrar claves Fernet, sesiones de usuario ni credenciales en commits o logs.
