# DEPRECATED — no instalar estos units

Esta carpeta es legado. Las unidades apuntan a `WorkingDirectory=/home/santiago/triadees`
y `User=santiago` — una máquina distinta al entorno real de producción actual.

`triade-model-router.service` ya se documenta a sí mismo como
"DEPRECATED — merged into single_port_app:8010". `triade.service` y
`triade-chat-ui.service` usan el mismo `ExecStart` que
`deploy/systemd/triade-api.service`: instalarlas juntas colisiona en el
puerto 8010.

**Fuente de verdad real: [`deploy/systemd/`](../deploy/systemd/).** Esa
carpeta refleja byte a byte lo que hoy está instalado y verificado en
`/etc/systemd/system/` en el servidor de producción local (ver
`docs/audits/systemd_service_matrix.md` y `TECHNICAL_DEBT.md`).

Hallazgo 2026-07-30: un worker autónomo del propio sistema (commit
`aa001f3`, "Triade Evolution Worker") siguió escribiendo en esta carpeta
legado después de que `deploy/systemd/` ya era la fuente de verdad. Este
archivo existe para que ningún proceso, humano o autónomo, instale nada de
aquí por error.
