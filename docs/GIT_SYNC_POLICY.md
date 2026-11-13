# Política de sincronización Git · Tríade Ω

Repositorio local:

```text
C:\triadees
```

Repositorio remoto:

```text
origin = https://github.com/WatabooColosus/triadees.git
```

Reglas operativas:

1. Mantener el repo local comunicado con `origin`.
2. Antes de cambios importantes, revisar:

```bash
git status --short --branch
git fetch origin
```

3. No trabajar directo sobre `main` para cambios de Codex; usar ramas `codex/...`.
4. Antes de integrar, verificar pruebas y revisar diff.
5. No versionar estado local, tokens, bases SQLite, runs ni archivos de agente local.

Estado confirmado:

```text
origin/main conectado
rama de trabajo actual: codex/auditoria-evolutiva-triade
```
