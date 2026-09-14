ALPHA ENGINE V13 - PHASE 4C FIX1

Purpose: archival publishing fix only.

The original Phase4C successfully built the observed-holdout evidence files, but git add refused them because artifacts/validation is ignored by the repository-wide .gitignore.

FIX1 changes only the Git staging command to force-add the exact six archival files. It does NOT alter holdout results, hashes, model, policy, seal, or any economic calculation.

Run: .\CHECKPOINT_V13_PHASE4_HOLDOUT.ps1

The script is idempotent/restart-safe: it rebuilds the same deterministic evidence manifest, stages the exact files, commits if needed, pushes main, and creates/pushes the existing Phase4C tag if absent.
