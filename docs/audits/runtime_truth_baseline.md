# Runtime truth baseline

## Scope

- Base commit: `4c18120525b039b4b6c66703a07b829b01d8e3f0`
- Reference commit: `9516b47ca42d4faf6c2192e4548ad1b8cfffdf06`
- Branch: `codex/runtime-truth-stabilization`
- Date: 2026-07-29 UTC
- OS: Linux 6.8.0-1064-gcp x86_64
- Python: 3.12.11
- Node: 22.14.0
- npm: 10.9.2

## Results

| Check | Result | Evidence | Duration |
|---|---:|---|---:|
| `python -m compileall triade` | pass | exit 0 | <1 s |
| `ruff check .` | fail | 825 diagnostics; 405 marked auto-fixable | <1 s cached |
| `pytest -q` | pass | 1156 collected, 1156 passed, one dependency deprecation warning | 329 s |
| `mypy triade` | fail | 225 errors in 69 files | 1 s cached |
| `npm ci` | pass | 71 packages installed, audit during install clean | 2 s |
| `npm run build` | pass | Vite 6.4.3, 31 modules transformed | 1 s |
| `npm audit` | pass | 0 vulnerabilities | <1 s |

The first timing attempt used `/usr/bin/time`, which is not installed in the
runtime image and returned exit 127 before executing any check. All checks in
the table were subsequently executed directly. Durations below one second are
reported as such because the available shell timer has one-second resolution.

## Baseline interpretation

This baseline is not green: Ruff and mypy fail. The runtime behavior suite and
frontend build pass, but those results do not waive static-analysis failures.
No check was disabled, filtered, or converted into a warning.

The existing runtime also has two task representations (`worker_tasks` and
`autonomous_tasks`). Commit `4c18120` added v2 leasing to productive execution,
but non-success handler states can still be closed through `complete()`. Phase 1
must replace that ambiguity with a canonical execution-result contract and
explicit terminal transitions.
