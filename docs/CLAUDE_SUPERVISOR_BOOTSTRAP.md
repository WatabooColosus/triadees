# Activación del supervisor externo Claude

## Opción A · Ejecutarlo ahora desde Claude Code

Cambiar a la rama del PR y abrir Claude Code:

```bash
git fetch origin
git switch feat/claude-external-supervisor
claude
```

Después escribir exactamente:

```text
Ejecuta el supervisor externo de Tríade. Lee CLAUDE.md y el agente triade-external-supervisor. Analiza el PR actual, genera los grafos reales, elige una sola brecha prioritaria y trabaja hasta dejar pruebas y evidencia. Prohibido simular y prohibido hacer merge.
```

Claude Code leerá `CLAUDE.md` como instrucciones del repositorio y podrá invocar el agente especializado ubicado en `.claude/agents/`.

## Opción B · Ejecución manual desde GitHub Actions

Antes se requiere configurar el secreto del repositorio:

```text
ANTHROPIC_API_KEY
```

Luego abrir **Actions → Claude · Supervisor externo de Tríade → Run workflow**, seleccionar la rama que contiene el workflow e indicar la misión.

## Opción C · Comentario en PR después del merge del workflow

Cuando `.github/workflows/claude-triade-supervisor.yml` esté en la rama principal y la aplicación de Claude tenga permisos, comentar en un PR:

```text
@claude supervisa triade
```

O:

```text
@claude ejecuta el supervisor externo
```

El workflow leerá el contexto del PR, las instrucciones del repositorio y ejecutará un ciclo de supervisión.

## Seguridad

- No usar `--dangerously-skip-permissions`.
- No permitir acceso de escritura a la base viva.
- No entregar secretos en prompts, commits o artefactos.
- Mantener aprobación humana para merge, despliegue y migraciones.
- Revisar consumo, límites de turnos y coste antes de habilitar recurrencia.
