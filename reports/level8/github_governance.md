# GitHub governance blocker

Authenticated GET `/repos/WatabooColosus/triadees/branches/main/protection` returned HTTP 403 on 2026-10-07 UTC. This does not establish whether protection is absent. No governance changes were made.

Hosted runner jobs currently cannot start because GitHub reports failed payments or an insufficient spending limit. Resolve account Billing & plans, then rerun the workflows. Do not remove checks or mask failures.

After runner availability and green execution, an administrator can inspect and configure protection:

```powershell
gh api repos/WatabooColosus/triadees/branches/main/protection
gh api --method PUT repos/WatabooColosus/triadees/branches/main/protection --input reports/level8/main_protection_proposal.json
```

The proposal requires the Runtime Truth aggregator and Measurement Core job, prevents force pushes and branch deletion, and keeps ordinary administrator/local operation possible. Confirm check names against successful runs before applying; enforcement with unavailable runners will block merges. `gh` is not installed on this host; equivalent GitHub Settings → Branches configuration is possible for an administrator.
