# Alpha Engine GitHub Live

This layer runs the already-sealed Alpha Engine V13 policy on a GitHub-hosted Windows runner.

## Schedule

07:30 `America/Argentina/Buenos_Aires`, Monday-Friday.

## Guarantees

- No model tuning.
- No real orders.
- V13 critical sealed files are hashed before and after every run.
- The workflow fails if any sealed critical file changes.
- The mobile page contains model/forward information only, not the personal portfolio ledger.
- Every successful run archives a timestamped decision JSON under `cloud/history/decisions/`.

## Secret required

Repository Actions secret:

`MMM_SEC_USER_AGENT`

Never commit its value to the repository.

## Mobile page

The workflow publishes `mobile_snapshot/` through GitHub Pages after a successful model run.
