# Tríade Ω · Agente móvil Termux

Este agente convierte un celular Android en nodo federado consentido. Expone
capacidades, configuración de uso y una cola mínima de jobs ligeros.

## Instalar en el celular

En Termux:

```bash
pkg update
pkg install python git
python -m pip install fastapi uvicorn pydantic
```

Copia el repositorio o al menos la carpeta `apps/` y `triade/` al celular.
Desde la raíz del repo en Termux:

```bash
export TRIADE_NODE_TOKEN="cambia-este-token"
python apps/mobile_node_agent.py --host 0.0.0.0 --port 8790 --node-id celular-santiago --usage 60
```

Para habilitar el panel web admin sobre una carpeta especifica:

```bash
termux-setup-storage
python apps/mobile_node_agent.py \
  --host 0.0.0.0 \
  --port 8790 \
  --node-id celular-santiago \
  --usage 60 \
  --admin-root /sdcard/Download
```

Sin `--admin-root`, el modo admin permanece desactivado por defecto. Si no defines `TRIADE_NODE_TOKEN`, el agente genera un token local aleatorio y lo guarda en `mobile_node_state.json`.

Luego abre en el navegador:

```text
http://IP_DEL_CELULAR:8790/admin
```

El panel permite:

- listar archivos dentro de `--admin-root`;
- leer archivos de texto dentro de `--admin-root`;
- ejecutar comandos permitidos por lista (`python_version`, `whoami`, `pwd`).

No ejecuta comandos arbitrarios. Para agregar comandos, edita
`mobile_node_state.json` y agrega entradas a `allowed_commands`.

## Probar desde la PC central

Reemplaza la IP por la del celular:

```powershell
$TOKEN="cambia-este-token"
Invoke-RestMethod http://IP_DEL_CELULAR:8790/health
Invoke-RestMethod http://IP_DEL_CELULAR:8790/capabilities -Headers @{Authorization="Bearer $TOKEN"}
```

## Registrar como nodo federado

```powershell
$TOKEN="cambia-este-token"
$CAPS = Invoke-RestMethod http://IP_DEL_CELULAR:8790/capabilities -Headers @{Authorization="Bearer $TOKEN"}
python triade_digimon.py federate register celular-termux `
  --name "Celular Termux" `
  --endpoint http://IP_DEL_CELULAR:8790 `
  --trust medium `
  --permission publish_capabilities `
  --permission request_compute `
  --capabilities ($CAPS | ConvertTo-Json -Depth 8)
```

## Jobs disponibles

```powershell
$BODY = @{task="benchmark"; seconds=5; payload=@{}} | ConvertTo-Json
Invoke-RestMethod http://IP_DEL_CELULAR:8790/jobs `
  -Method Post `
  -ContentType "application/json" `
  -Headers @{Authorization="Bearer $TOKEN"} `
  -Body $BODY
```

El porcentaje `--usage 60` es cooperativo: el agente trabaja en ventanas de
tiempo y duerme el resto. Android puede limitar más por batería, temperatura o
políticas del sistema.
