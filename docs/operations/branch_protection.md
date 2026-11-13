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

The global mypy step is blocking and runs under `set -o pipefail`; a failing
`mypy triade` cannot be hidden by `tee`. Ruff, format, tests, dependency audits,
frontend build, operational truth, rollback and concurrency are also blocking
and must not be bypassed.

Repository API check on 2026-07-30 returned `404 Branch not protected` for
`main`. The policy above is therefore documented but not active. Enable it only
after the final direct-push implementation sequence, then verify the protection
API and a pull-request gate. Until that external setting is applied, do not
describe branch protection as enforced.
