# Cloud database truth

Measured against `compose.cloud.yml` on 2026-08-11. PostgreSQL and Valkey are
real readiness dependencies, but the existing organism has not been migrated
from SQLite. `TRIADE_DB_PATH=/app/memory/triade.db` is therefore explicit and
stored on the `triade_memory` volume; an empty accidental SQLite file elsewhere
must never satisfy cloud health.

| Subsystem | SQLite | PostgreSQL | Source of truth |
| --- | --- | --- | --- |
| runtime | read/write | readiness only | SQLite |
| metabolism | read/write | no | SQLite |
| workers | read/write | no | SQLite |
| learning | read/write | no | SQLite |
| memory | read/write | no | SQLite |
| goals | read/write | no | SQLite |
| federation | read/write | no | SQLite |
| health | deep runtime state | dependency reachability | SQLite plus declared dependency checks |

Cloud startup order is: PostgreSQL/Valkey healthy, writable SQLite volume,
durability pragmas, required metabolic migration, interrupted-cycle recovery,
runtime threads, then deep health. Moving a subsystem to PostgreSQL requires a
separate data migration and must change this matrix together with its tests.
