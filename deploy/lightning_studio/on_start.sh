#!/bin/bash
# Tríade Ω · Arranque automático tras el reinicio del Lightning Studio.
#
# Este fichero es el ÚNICO punto de entrada del arranque, y existe aquí porque
# ~/.lightning_studio vive en /teamspace/studios/this_studio, que es lo único
# que persiste cuando el Studio se recrea. La raíz del contenedor es un overlay:
# /etc/systemd/system vuelve vacío en cada arranque.
#
# Ese detalle es la causa de que Tríade no sobreviviera a un reinicio. La versión
# anterior de este guion afirmaba en su cabecera que las units «ya arrancan solas
# por boot porque están enabled». No lo estaban: no existían. El 2026-08-10, con
# el Studio 19 minutos arriba, había cero units `triade*` instaladas y nada
# escuchando en el 8010, mientras studio-web.log seguía con la parada limpia de
# la sesión anterior.
#
# La cadena queda así, con un solo mecanismo de supervisión:
#
#   BOOT -> on_start.sh -> install_systemd_units.sh -> systemd -> triade-api
#
# systemd es el único que mantiene procesos vivos. Este guion no lanza nada con
# nohup: un proceso manual que gane la carrera por el puerto deja a la unit
# reiniciándose en bucle mientras sirve tráfico algo que nadie supervisa (pasó el
# 2026-07-30 con triade-ollama y 150+ reinicios).

set -uo pipefail

REPO_DIR="/teamspace/studios/this_studio/triadees"
LOG_DIR="$REPO_DIR/logs"
BOOT_LOG="$LOG_DIR/on_start.log"

mkdir -p "$LOG_DIR"

exec >>"$BOOT_LOG" 2>&1
echo "=== on_start $(date -Is) ==="

# 1. Units de systemd: instalar desde el repo, habilitar y arrancar. Idempotente.
#    Este paso va primero porque el hook de plataforma tiene una ventana acotada.
#    En el boot de 2026-08-11 murió durante la reparación de 849 modos y no llegó
#    a instalar una sola unit. El runtime debe recuperar dueño antes del trabajo
#    administrativo del checkout.
bash "$REPO_DIR/scripts/install_systemd_units.sh" || echo "AVISO: fallo instalando units"

for unit in triade-ollama.service triade-api.service triade-watchdog.service; do
    sudo systemctl start "$unit" || echo "AVISO: no arrancó $unit"
done
sudo systemctl start triade-backup.timer || true

# 2. Modos de fichero. El reinicio del Studio deja todo el árbol en 0744, y eso
#    rompe `ruff check` y los permisos de claves. Ya no bloquea el restablecimiento
#    de systemd ni de la URL; la unit carga `.env` antes de este paso.
bash "$REPO_DIR/scripts/restore_file_modes.sh" || echo "AVISO: no se pudieron restaurar los modos"

# 3. Esperar a Ollama sólo para sincronizar modelos. La API no espera por esto:
#    si Ollama tarda o falla, arranca igual y queda con el modelo degradado.
for _ in $(seq 1 60); do
    curl -sf --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
done

MODELS_FILE="$REPO_DIR/config/studio-models.txt"
if [ -f "$MODELS_FILE" ] && curl -sf --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    # Descarga de modelos: es sincronización de datos, no supervisión de
    # procesos, así que aquí sí es correcto lanzarlo en segundo plano.
    nohup "$REPO_DIR/scripts/ensure_studio_models.sh" "$MODELS_FILE" \
        >"$LOG_DIR/studio-model-sync.log" 2>&1 &
fi

# 4. Verificación del arranque (sólo lectura).
nohup bash "$REPO_DIR/scripts/post_reboot_verify.sh" \
    >"$LOG_DIR/post-reboot-verify.log" 2>&1 &

echo "=== on_start terminado $(date -Is) ==="
