#!/usr/bin/env bash
# Devuelve a los ficheros del repo el modo que git tiene indexado.
#
# Por qué existe: el reinicio del Studio deja *todo* el árbol en 0744. Como
# `core.fileMode` está en false, git no ve el cambio y `git status` sale limpio,
# así que el desajuste es invisible hasta que rompe algo. Rompe dos cosas:
#
#   1. `ruff check .` pasa de 0 a 715 errores EXE002 («ejecutable sin shebang»)
#      porque 1128 ficheros que git tiene como 100644 aparecen como ejecutables.
#      La validación local deja de parecerse a la de CI, donde los modos son los
#      del índice y no hay ningún EXE002.
#   2. La clave de backup queda legible por el grupo y `EncryptedBackup` se niega
#      a cifrar (`backup_key_file_permissions_must_be_0600`). El 2026-08-08 eso
#      dejó al organismo trece horas sin copia, con cada `encrypted_backup` en
#      dead_letter y nada que lo dijera.
#
# La fuente de verdad es el índice de git, no una lista a mano: lo que git dice
# 100755 vuelve a 755 y lo que dice 100644 vuelve a 644. Así no hay que
# mantener sincronizado un inventario de scripts que se queda viejo solo.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

changed=0
while IFS= read -r -d '' entry; do
    mode="${entry%% *}"
    path="${entry#* }"
    path="${path#*$'\t'}"
    [ -f "$path" ] || continue
    case "$mode" in
        100755) want=755 ;;
        100644) want=644 ;;
        *) continue ;;
    esac
    have="$(stat -c '%a' "$path" 2>/dev/null || echo '')"
    if [ "$have" != "$want" ]; then
        chmod "$want" "$path"
        changed=$((changed + 1))
    fi
done < <(git ls-files -sz)

echo "modos restaurados desde el índice de git: $changed fichero(s)"

# La clave de backup no está en git (y no debe estarlo), así que su modo no sale
# del índice: se cierra aquí, que es el mismo momento del arranque.
key_file="${TRIADE_BACKUP_KEY_FILE:-}"
if [ -z "$key_file" ] && [ -f "$ROOT/.env" ]; then
    key_file="$(grep -E '^TRIADE_BACKUP_KEY_FILE=' "$ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"'' || true)"
fi
if [ -n "$key_file" ] && [ -f "$key_file" ]; then
    have="$(stat -c '%a' "$key_file" 2>/dev/null || echo '')"
    if [ "$have" != "600" ]; then
        chmod 600 "$key_file"
        echo "clave de backup: $have -> 600"
    else
        echo "clave de backup: ya en 600"
    fi
else
    echo "clave de backup: no configurada o ausente (se omite)"
fi

# Tercera víctima del mismo 0744, y la que menos se ve venir: la clave con la
# que se firman los commits. ssh se niega a usar una clave privada accesible por
# otros ("UNPROTECTED PRIVATE KEY FILE"), git no puede firmar y `git commit`
# falla con «failed to write commit object». No está en el índice —vive dentro
# de .git—, así que tampoco sale del bucle de arriba.
signing_key="$(git config --get user.signingkey 2>/dev/null || true)"
if [ -n "$signing_key" ] && [ -f "$ROOT/$signing_key" ]; then
    signing_key="$ROOT/$signing_key"
fi
if [ -n "$signing_key" ] && [ -f "$signing_key" ]; then
    have="$(stat -c '%a' "$signing_key" 2>/dev/null || echo '')"
    if [ "$have" != "600" ]; then
        chmod 600 "$signing_key"
        echo "clave de firma: $have -> 600"
    else
        echo "clave de firma: ya en 600"
    fi
else
    echo "clave de firma: no configurada (se omite)"
fi
