#!/usr/bin/env bash
set -euo pipefail

# Tríade Ω · Post-Reboot Verification Script
# Verifica; no arranca nada por su cuenta.
#
# Antes sí arrancaba: los pasos 2 y 4 hacían `nohup ollama serve` y
# `nohup uvicorn` si no encontraban el servicio arriba, pese a que la cabecera
# decía "safe, non-destructive". Eso lo convertía en un tercer lanzador, y uno
# especialmente dañino porque on_start.sh lo llamaba en segundo plano justo
# después de pedirle a systemd que arrancara lo mismo: los dos corrían a la vez
# por el puerto. El 2026-08-10, reproduciendo un arranque en frío, el nohup de
# este guion ganó la carrera y dejó al proceso del 8010 fuera de todo cgroup de
# servicio mientras triade-api.service se reiniciaba por detrás. Es el mismo
# accidente que el 2026-07-30 con Ollama y sus 150+ reinicios.
#
# Ahora, si algo no está arriba, se le pide a systemd —que es quien supervisa—
# y nunca se lanza un proceso suelto.

SHA=$(cd /teamspace/studios/this_studio/triadees && git rev-parse HEAD 2>/dev/null || echo "unknown")
HOST=$(hostname)
DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "===================================================="
echo " Tríade Ω · Post-Reboot Verification"
echo " Host: $HOST"
echo " Time: $DATE"
echo " SHA:  ${SHA:0:12}"
echo "===================================================="

REPO_DIR="/teamspace/studios/this_studio/triadees"
OLLAMA_BIN="/teamspace/studios/this_studio/.ollama/runtime/bin/ollama"
LOG_DIR="$REPO_DIR/logs"
PORT=8010

mkdir -p "$LOG_DIR"

# Step 1: Verify repository
echo ""
echo "[1/10] Repository check..."
cd "$REPO_DIR"
if git rev-parse HEAD >/dev/null 2>&1; then
    echo "  ✓ Repository at $REPO_DIR"
    echo "  ✓ Branch: $(git branch --show-current)"
    echo "  ✓ SHA: $(git rev-parse HEAD)"
else
    echo "  ✗ Repository not found"
fi

# Step 2: Start Ollama if not running
echo ""
echo "[2/10] Ollama..."
if curl -sf --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "  ✓ Ollama already running"
else
    echo "  Ollama caído; se lo pido a systemd (no se lanza suelto)"
    sudo systemctl start triade-ollama.service 2>/dev/null || echo "  ✗ systemd no pudo arrancar triade-ollama.service"
    for i in $(seq 1 60); do
        if curl -sf --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
            echo "  ✓ Ollama started"
            break
        fi
        sleep 1
    done
    if ! curl -sf --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        echo "  ✗ Ollama failed to start"
    fi
fi

# Step 3: Verify models
echo ""
echo "[3/10] Models..."
if curl -sf --max-time 5 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    MODELS=$(curl -sf http://127.0.0.1:11434/api/tags | python3 -c "import sys,json; ms=json.load(sys.stdin).get('models',[]); [print(f'    {m[\"name\"]}') for m in ms]" 2>/dev/null)
    echo "  ✓ Models available:"
    echo "$MODELS"
else
    echo "  ✗ Cannot list models"
fi

# Step 4: Start API if not running
echo ""
echo "[4/10] API..."
if curl -sf --max-time 3 "http://127.0.0.1:$PORT/health/live" >/dev/null 2>&1; then
    echo "  ✓ API already running on port $PORT"
else
    echo "  API caída; se la pido a systemd (no se lanza suelta)"
    cd "$REPO_DIR"
    sudo systemctl start triade-api.service 2>/dev/null || echo "  ✗ systemd no pudo arrancar triade-api.service"
    for i in $(seq 1 60); do
        if curl -sf --max-time 2 "http://127.0.0.1:$PORT/health/live" >/dev/null 2>&1; then
            echo "  ✓ API started"
            break
        fi
        sleep 1
    done
    if ! curl -sf --max-time 2 "http://127.0.0.1:$PORT/health/live" >/dev/null 2>&1; then
        echo "  ✗ API failed to start"
    fi
fi

# Step 5: Database integrity
echo ""
echo "[5/10] Database..."
DB="$REPO_DIR/triade/memory/triade.db"
if [ -f "$DB" ]; then
    DB_SIZE=$(stat --printf="%s" "$DB" 2>/dev/null | numfmt --to=iec 2>/dev/null || echo "unknown")
    python3 -c "import sqlite3; c=sqlite3.connect('$DB').cursor(); c.execute('PRAGMA integrity_check'); r=c.fetchone()[0]; print('  ✓ Integrity:', r); c.execute('SELECT COUNT(*) FROM identity_core'); print('  ✓ Identity core rows:', c.fetchone()[0])" 2>&1
else
    echo "  ✗ Database not found at $DB"
fi

# Step 6: Check systemd services (if available)
echo ""
echo "[6/10] Systemd services..."
if command -v systemctl >/dev/null 2>&1; then
    for svc in triade-ollama.service triade-api.service; do
        if systemctl is-enabled "$svc" >/dev/null 2>&1; then
            STATUS=$(systemctl is-active "$svc" 2>/dev/null)
            echo "  $svc: $STATUS"
        else
            echo "  $svc: not installed"
        fi
    done
else
    echo "  systemctl not available"
fi

# Step 7: Warning if load average is high
echo ""
echo "[7/10] System load..."
LOAD=$(cat /proc/loadavg 2>/dev/null | awk '{print $1","$2","$3}')
CPU=$(nproc 2>/dev/null || echo 8)
LOAD1=$(echo "$LOAD" | cut -d, -f1 | cut -d. -f1)
if [ "${LOAD1:-0}" -gt "$((CPU * 2))" ]; then
    echo "  ⚠ Load average high: $LOAD (CPUs: $CPU) — Resource Governor may degrade mode"
else
    echo "  ✓ Load average: $LOAD (CPUs: $CPU)"
fi

# Step 8: Verify public URL
echo ""
echo "[8/10] Public URL..."
echo "  URL: https://lightning.ai/agenciadigitalwataboo-org/deploy-model-project/studios/triade/web-ui?port=$PORT"

# Step 9: Test inference (quick)
echo ""
echo "[9/10] Quick inference test..."
timeout 20 curl -sf http://127.0.0.1:11434/api/generate \
    -d '{"model":"qwen2.5:3b-instruct","prompt":"Hi","stream":false}' \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('  ✓ Response:', d.get('response','')[:50])" 2>/dev/null || echo "  ⚠ Inference skipped (model loading may take >20s)"

# Step 10: Summary
echo ""
echo "[10/10] Health summary..."
python3 "$REPO_DIR/scripts/triade_doctor_full.py" --json 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
status=d.get('overall_status','UNKNOWN')
print(f'  Overall status: {status}')
deg=d.get('degraded_components',[])
if deg:
    print(f'  Degraded: {len(deg)} — {\", \".join(deg[:5])}')
print(f'  SHA: {d.get(\"sha\",\"unknown\")}')
" 2>/dev/null || echo "  Could not run doctor"

echo ""
echo "===================================================="
echo " Post-reboot verification complete."
echo "===================================================="
