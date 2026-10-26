# Centro continuo de Colab

El mismo botón **Instalar / encender / actualizar** sirve en una VM vacía y en
una sesión existente. Instala las dependencias ausentes, recupera únicamente la
continuidad de Drive acreditada e inicia el runtime. El cuaderno no ofrece un
botón por versión histórica ni exige instalar R5 manualmente antes de actualizar.

El cuaderno de ciclo único llama al instalador desde la ejecución principal de
la celda. La autorización de Drive continúa directamente hacia la instalación,
sin requerir ejecutar de nuevo la celda ni pulsar otro botón. El panel aparece
antes de consultar la red; muestra cinco etapas reales y tiempo transcurrido.
La comprobación de catálogo/CI se hace una vez por instalación, después de montar
Drive. El vigilante espera su primer intervalo y no compite con el arranque.
Los componentes locales se reutilizan solo si su SHA coincide. Una reejecución
con servicios ya verificados reutiliza la sesión sin consultas de GitHub; el
botón de actualización y el vigilante mantienen la búsqueda de futuras versiones.
La reanudación comprueba API, Ollama, código, propietario y recuentos locales
frente a la verificación previa; no vuelve a calcular hashes de imágenes grandes
de Drive. La instalación y la recuperación mantienen la validación completa.

La primera publicación usa internamente los instaladores de compatibilidad ya
auditados de R5/R6.3.1. Esto no convierte esa candidata en estable ni prueba un
reinicio en el Drive del propietario. Los próximos paquetes pueden sustituir el
instalador completo y sus componentes; el cliente no contiene nombres de
versiones del runtime.

## Canal y ejecución

- Catálogo permanente: `releases/colab-channel.json` en la rama `colab-releases`
  del repositorio `WatabooColosus/triadees`.
- El panel consulta ese catálogo cada 600 segundos mientras el kernel siga vivo.
  Reabrir el panel reutiliza el mismo cliente y su hilo de vigilancia.
- Comprobar actualizaciones no monta Drive ni inicia servicios. El botón de
  instalación monta Drive antes de consultar el último recibo persistente.
- Cada publicación declara commit Git inmutable, secuencia creciente, versión,
  protocolo y SHA-256 de todos sus componentes. Se validan todos los componentes
  antes de importar uno. El catálogo no puede señalar otro repositorio o rutas
  arbitrarias fuera de `tools/*.py`.
- Runtime Truth CI, Python Tests y Tríade Tests deben estar completadas y en verde
  para el commit exacto. Una ejecución más reciente fallida o pendiente bloquea
  la versión aunque exista un resultado antiguo correcto.
- Por defecto, las versiones se aplican con el único botón. La casilla opcional
  permite aplicar futuras publicaciones **estables** con `auto_update_safe=true`;
  las candidatas siguen requiriendo pulsar el botón. No instala por primera vez
  ni pide OAuth desde un hilo de fondo. Un intento automático fallido no se
  repite continuamente sobre esa misma publicación.

## Publicar las próximas versiones

El publicador mantiene el catálogo; el usuario conserva el mismo cuaderno.
Para cada versión:

1. Preparar un paquete completo compatible con protocolo 1. El módulo instalador
   declara `install(context)`, `verify(context)` y `recover(context, error)`.
   `context` proporciona `r5`, rutas locales de los componentes ya verificados,
   el manifiesto y un callback `progress`. El adaptador de la primera publicación
   es `tools/triade_colab_release.py`; no obliga a repetir esa implementación.
2. `install` debe aceptar tanto una VM vacía como un reintento y devolver
   `{"status":"ready"}` únicamente después de su arranque. `verify` debe observar
   el runtime real y devolver `True` solo para el código y la memoria previstos.
   `recover` debe conservar memoria y diagnósticos; una recuperación fallida no
   se presenta como rollback certificado.
3. Publicar el código, esperar la CI y actualizar el catálogo con una secuencia
   superior, el commit exacto y los hashes de sus archivos. El catálogo debe usar
   `schema=triade.colab.release.v1`, `repository=WatabooColosus/triadees`,
   `protocol=1`, `channel=candidate|stable`, `auto_update_safe` booleano y `files`
   con al menos `installer={path,sha256}`. El cliente admite otros componentes
   declarados por nombre, sin modificar el cuaderno.
4. Publicar como estable y habilitar aplicación automática solo cuando exista
   aceptación operativa del paquete. El primer catálogo es candidato y no
   habilita esa modalidad.

El recibo se escribe en `MyDrive/Triade/operacion_colab_continua/installed.json`
solo después de instalación y verificación. Una sesión nueva lee ese recibo
antes de permitir versiones anteriores. Esto guarda la versión, no reemplaza
los respaldos de Bodega. El índice V2, las identidades y las copias originales
de Drive siguen protegidos por el instalador correspondiente.

El controlador obtiene sus mínimos de la restauración acreditada del propietario
y del último punto operativo registrado en Drive. No exige un número fijo de
actividades o aplicaciones educativas tomado de otra ejecución. Busca también
las imágenes documentadas de la misma rama V2 aunque falte el puntero de revisión;
verifica SHA, SQLite, propietario, origen, linaje y recuentos antes de elegirlas.
Nunca elige una imagen que reduzca las tablas protegidas o actividades activadas.
Un conflicto real mantiene el arranque detenido y **Estado real** sigue disponible
después de una instalación incompleta, sin exigir instalar otra vez para verlo.

La presencia de archivos WAL/SHM locales no se interpreta por sí sola como un
fallo. Antes de recuperar una revisión más completa, se guarda la memoria local
con la API de backup de SQLite, incluidos los datos confirmados del WAL. La
restauración usa esa misma API transaccional sobre la Bodega existente, sin
borrar archivos laterales ni reemplazar su inode. Un escritor que mantiene la
base ocupada, un cambio de recuentos durante la preparación o un listener API
activo (aunque su salud no responda 200) mantienen el bloqueo. Las copias
originales de Drive no se modifican.

## Validación

`tests/test_colab_continuous.py` comprueba VM vacía, instalación de dependencias,
checksum de Node, publicación posterior, reanudación, veto a downgrade tras
perder el kernel, veto a CI fallida, todos los hashes antes de ejecutar, fallo de
verificación sin avance del recibo y vigilancia automática con consentimiento.
Estos son contratos con fixtures temporales; no acreditan actividad ni memoria
real de Colab. La aceptación con Drive real sigue siendo una comprobación aparte.

## Actualización del auditor desde el panel existente

R7.6-auditor-panel incorpora un quinto componente verificado, `auditor`. El
cliente R7.5 ya admite ese componente sin cambiar la celda ni el cuaderno.
Después de publicar el catálogo con CI verde, se usa **Comprobar nuevas
versiones** y **Instalar / encender / actualizar**. Si API, Ollama, Bodega,
propietario, continuidad y R6.3.1 están acreditados, el adaptador adjunta el
auditor al panel existente sin instalar dependencias, restaurar memoria,
iniciar guardianes ni reiniciar la API. El recibo solo avanza tras verificar.

El auditor usa recuentos de filas sobre conexiones SQLite de solo lectura,
inspecciona el esquema y evita la conversión de `"id"` a un literal cuando la
columna real es `cycle_id`. Muestra eventos nuevos, estados de ambas colas,
configuración efectiva permitida del PID registrado y detalles del panel de
deuda mediante GET locales. Los endpoints que exigen autenticación se declaran
no observados, sin desactivar el login. Los GET pueden generar telemetría del
backend o refresco de sus artefactos; se realizan después de medir los deltas.
Los contenidos de tareas y payloads no se vuelcan. Ni eventos nuevos ni tareas
pendientes por sí solos acreditan aprendizaje, ejecución completa o bloqueo.

## Protección cifrada en Colab (R7.7)

El repositorio conserva una referencia histórica a una clave de Windows en
`config/backup_key_location.json`. Una VM de Colab no tiene ese volumen. El
componente `protection`, entregado por el mismo canal, valida primero propietario
y proceso API registrado, recupera una clave única de las ubicaciones declaradas
o del ámbito persistente de esa fuente V2 y la copia a un fichero local 0600.
Con claves distintas, archivos inválidos o identidad persistente en conflicto se
detiene y preserva las referencias; no elige una arbitrariamente.

Si no existe clave utilizable y tampoco hay copias cifradas previas en el ámbito
Colab ni en el directorio local de respaldos, crea protección **nueva** en
`MyDrive/Triade/operacion_colab_continua/proteccion_cifrada/<fuente-V2>/`.
La clave anterior no se reemplaza ni se presenta como recuperada. Una clave
perdida con copias cifradas locales o persistentes exige recuperar la original;
no se genera otra sobre ese corpus. La referencia anterior se archiva de forma
privada antes de actualizar el puntero canónico, que MissionPlanner relee en cada
ciclo. No se reinicia la API ni se modifica la autonomía.

La clave persistente queda en la cuenta privada de Drive, junto al ámbito de
copias: el cifrado protege los archivos separados de la clave; no sustituye el
control de acceso de esa cuenta. La clave no se imprime, no aparece en argumentos
de comandos y no se publica en Git. Cada nueva sesión recupera la misma clave.

Se crea una copia genuina mediante SQLite online backup, se comprueba su
integridad, se cifra y se verifica descifrándola en un directorio temporal. Se
verifican también los bytes persistidos en Drive. No se restaura la Bodega ni se
insertan filas para certificar actividad. Se usan las operaciones de copia y
verificación de EncryptedBackup sin ejecutar sus migraciones de inicialización.
Una vigilancia del kernel, única y serializada, copia después respaldos cifrados
reales del backend cada 600 s (máximo dos copias automáticas nuevas al día), sin
borrar las anteriores. Un fallo de cuota o de verificación conserva los archivos
y no certifica el avance. La vigilancia termina con la sesión de Colab.

**Estado real** y **Auditar actividad** muestran `backup_protection`, con la
verificación de descifrado/Drive y el estado de resolución que declara el backend
en su `/api/health` público. La escritura del puntero no acredita por sí sola que
el planificador ya lo haya adoptado; se declara pendiente del siguiente ciclo.
La recuperación de cifrados antiguos permanece `not_certified`.

El auditor `schema-aware-2` conserva deltas de filas y añade avance de cursor de
eventos (el log retiene 5000 filas), detalles limitados a la ventana y metadatos
de lease/reintento de tareas. Lee además las brechas de respaldo, servicios y
cadena vital con inspectores oficiales locales: su origen se distingue de la
API autenticada. Los 403 siguen visibles; no se desactiva el login ni se fabrican
sesiones. El modo `observe_only` y las restricciones de aprendizaje permanecen.
