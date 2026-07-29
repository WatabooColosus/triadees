# Branch protection for runtime truth

Protect `main` in repository settings with these minimum rules:

- require a pull request; disallow direct pushes;
- require at least one reviewer who did not author the runtime change;
- require the `Runtime Truth CI / required-result` check;
- require branches to be up to date before merge;
- dismiss stale approvals after new commits;
- require conversation resolution;
- block force pushes and deletion;
- retain the uploaded test, coverage, mypy, secret-scan, and concurrency evidence.

The global mypy step is temporarily marked non-blocking because the recorded
baseline has 225 errors in 69 files. Its full output remains visible and is
uploaded; changed runtime modules are checked locally with mypy before each
commit. Ruff, format, tests, dependency audits, frontend build, operational
truth, rollback and concurrency are blocking and must not be bypassed.
