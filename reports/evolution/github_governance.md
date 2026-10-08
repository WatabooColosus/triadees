# Main protection

Authenticated protection read returned HTTP 403 on 2026-10-07. Protection was not changed. This response cannot establish the current protection settings.

An operator with permission may apply protection against force push/deletion without required checks while Actions is externally blocked:

```powershell
gh api --method PUT repos/WatabooColosus/triadees/branches/main/protection --input reports/evolution/main_protection_proposal.json
```

When runners resume, configure required checks from their actual job names. The proposal deliberately does not block delivery on unavailable billing-limited runners.
