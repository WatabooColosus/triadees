# Tríade Ω · Release Colab R6.3.1 · continuidad verificable

Estado: candidata **NO estable**, sujeta a GitHub Actions y comprobación tras reinicio de Colab.

## Componentes recibidos
- R6: misiones seguras faltantes 11,12,14,15,16; 13 sigue protegida como candidata.
- R6.2: evidencias de runs reales vinculadas a misiones, planificación ampliada, rotación educativa con métricas.
- R6.3: pruebas funcionales prospectivas y guardas de atribución; no se retrocalifica el historial.
- R6.3.1: cuarentena semántica segura tratada como advertencia benigna **solo** si coincide su texto, sin errores y safety_score >= 0.6.
- Continuidad: `tools/triade_colab_continuity_r631.py`, que restaura el **código** desde hashes Git después de que R5 restaure la Bodega.

## Datos reales medidos al final de la anterior sesión Colab
- 16 neuronas; al menos 6 activaciones; 15 aplicaciones educativas; Bodega quick_check=ok, API=200.
- 5 pruebas funcionales fueron rechazadas inicialmente por verificación warning con seguridad 0.9; su acreditación posterior requiere la prueba real original y no está confirmada.
- Los datos de Drive son la autoridad para memoria; GitHub no contiene ni debe contener SQLite, claves Fernet ni credenciales.

## Reanudación segura de Colab
1. Arrancar el notebook R5 de Drive, restaurando desde Drive con `restore_proof.json` y `r5_continuity.json`.
2. Comprobar que la Bodega nueva tenga al menos 6 activaciones y 15 aplicaciones; si tiene menos, investigar snapshot antes de habilitar módulos nuevos.
3. En la **última celda** ejecutar el cargador reproducible pinned de Git `tools/triade_colab_continuity_r631.py` (sin repetir instalaciones manuales).
4. Verificar API HTTP 200, quick_check OK, ownership de PID; verificar trabajadores con lecturas separadas, no con solo conteos acumulados.
5. Guardar el notebook con la última celda en Drive. Colab seguirá perdiendo procesos/RAM/GPU tras desconexión: no hay continuidad de ejecución sin VM activa.

La fusión a `main` no modifica automáticamente notebooks ya guardados en Drive ni despliega código a una VM apagada.
