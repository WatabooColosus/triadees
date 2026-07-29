# Perfil 32 RAM / 24 VRAM

El hardware observado es 31,34 GiB RAM y una NVIDIA L4 con 22,49 GiB (23.034 MiB) de VRAM reportada. Se reserva capacidad para sistema, interacción y picos de KV cache.

El perfil inicial de `triade.yml` limita inferencia pesada y embeddings a una unidad concurrente, reserva 10 GiB de RAM entre sistema e interacción, y 3 GiB de VRAM. Los límites térmicos son 78 °C soft y 85 °C hard. Son configuración declarativa en esta fase; el `GPUResourceManager` que los hará obligatorios corresponde al PR 5.
