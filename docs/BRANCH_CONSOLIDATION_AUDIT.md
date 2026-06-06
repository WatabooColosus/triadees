# Auditoria de ramas de Triade

Fecha local de auditoria: 2026-06-05

## Diagnostico corto

El repositorio no tiene una sola linea principal efectiva. `main` es la rama oficial remota, pero el trabajo vivo del nucleo, UI, pulso y salida conversacional esta repartido en ramas `fix/` y `codex/`.

La rama que hoy representa el trabajo mas reciente sobre la base actual es:

- `fix/output-gate-after-codex`

La rama que debe quedar como unica principal del proyecto es:

- `main`

## Estado observado

Ramas locales:

- `main`: apunta a `0337489 Prepare Phase E relay hardening`.
- `fix/output-gate-after-codex`: apunta a `04497be Use active UI with neuron candidate controls`.
- `fix/output-gate-on-codex`: apunta a `1f1bcb5 feat: mejora nucleo Triade y analisis conversacional`.
- `codex/auditoria-evolutiva-triade`: apunta al mismo commit local que `fix/output-gate-on-codex`.
- `fix/central-user-facing-response`: apunta a `856b6fd Show system events in single port UI`.

Ramas remotas:

- `origin/main`: apunta a `0337489 Prepare Phase E relay hardening`.
- `origin/fix/output-gate-after-codex`: apunta a `04497be Use active UI with neuron candidate controls`.
- `origin/fix/output-gate-on-codex`: apunta a `1f1bcb5 feat: mejora nucleo Triade y analisis conversacional`.
- `origin/fix/central-user-facing-response`: apunta a `856b6fd Show system events in single port UI`.
- `origin/codex/auditoria-evolutiva-triade`: apunta a `0337489`, pero la rama local del mismo nombre apunta a `1f1bcb5`.
- `origin/1.9F-semantic-memory-fix`: rama historica de memoria semantica.

## Incoherencias detectadas

1. `main` no contiene el trabajo mas reciente.
   - `fix/output-gate-after-codex` esta 16 commits por delante de `main`.
   - Por eso el sistema real puede sentirse distinto segun desde que rama se ejecute.

2. Hay ramas duplicadas para el mismo avance.
   - `fix/output-gate-on-codex` y `codex/auditoria-evolutiva-triade` apuntan localmente al mismo commit `1f1bcb5`.
   - Remotamente, `origin/codex/auditoria-evolutiva-triade` no coincide con su rama local.

3. `fix/central-user-facing-response` esta desalineada.
   - Tiene 5 commits propios, pero le faltan 39 commits que ya existen en `main`.
   - Si se usa como base directa, aparenta borrar workflows, federacion, docs, tests y archivos importantes.
   - Debe tratarse como rama vieja para rescatar ideas, no como base de integracion.

4. La historia de `fix/output-gate-after-codex` tiene commits que conviene limpiar antes de convertirlos en historia principal.
   - Incluye `efffccf ABORT placeholder should not be used`.
   - Incluye mensajes duplicados como `Connect background neuron candidates to system events`.
   - Esto no necesariamente rompe el codigo, pero ensucia la narrativa tecnica del proyecto.

5. La rama remota `origin/1.9F-semantic-memory-fix` parece historica.
   - La memoria semantica ya evoluciono despues de ese punto.
   - Debe mantenerse solo si sirve como referencia de recuperacion.

## Linea principal recomendada

La estrategia correcta es dejar `main` como unica rama principal.

Ruta recomendada:

1. Validar que `fix/output-gate-after-codex` corre tests y doctor.
2. Integrar el contenido de `fix/output-gate-after-codex` en `main`.
3. Hacer esa integracion como squash o merge limpio, para no llevar a `main` commits de reparacion accidental como `ABORT placeholder`.
4. Revisar si algo unico de `fix/central-user-facing-response` no esta ya incluido.
5. Si falta algo valioso, aplicarlo por cherry-pick selectivo o port manual.
6. Empujar `main`.
7. Eliminar ramas redundantes locales y remotas cuando `main` ya contenga lo necesario.

## Ramas a conservar temporalmente

- `main`: rama principal unica.
- `fix/output-gate-after-codex`: conservar hasta que su contenido este en `main` y verificado.

## Ramas candidatas a eliminar despues de integrar

- `fix/output-gate-on-codex`
- `codex/auditoria-evolutiva-triade`
- `fix/central-user-facing-response`
- `origin/fix/output-gate-after-codex`
- `origin/fix/output-gate-on-codex`
- `origin/codex/auditoria-evolutiva-triade`
- `origin/fix/central-user-facing-response`
- `origin/1.9F-semantic-memory-fix`, solo si ya no se necesita como referencia historica.

## Comandos sugeridos para consolidar

Estos comandos son intencionalmente no destructivos hasta el punto de borrado. Los borrados deben ejecutarse solo despues de confirmar que `main` ya contiene el trabajo correcto.

```bash
git switch main
git pull --ff-only origin main
git merge --squash fix/output-gate-after-codex
python -m pytest -q
python triade_digimon.py doctor
git commit -m "Consolidar nucleo vivo de Triade en main"
git push origin main
```

Despues de verificar `main`:

```bash
git branch -d fix/output-gate-after-codex
git branch -d fix/output-gate-on-codex
git branch -d codex/auditoria-evolutiva-triade
git branch -d fix/central-user-facing-response
git push origin --delete fix/output-gate-after-codex
git push origin --delete fix/output-gate-on-codex
git push origin --delete codex/auditoria-evolutiva-triade
git push origin --delete fix/central-user-facing-response
git remote prune origin
```

## Criterio de aceptacion

El repositorio queda sano cuando:

- `origin/HEAD` apunta a `origin/main`.
- `main` contiene el nucleo vivo, pulso, memoria semantica continua, UI activa y pruebas.
- `python -m pytest -q` pasa en `main`.
- `python triade_digimon.py doctor` pasa en `main`.
- No quedan ramas remotas activas que compitan como fuente de verdad.
- Las ramas de trabajo nuevas nacen de `main` y vuelven a `main` por PR o merge controlado.

