ALPHA ENGINE V13 - PHASE 5B FIX2
ENV IDENTITY + SEC PREFLIGHT

Purpose
- Reuse the user's existing .env instead of hard-coding a generic SEC identity.
- Read MMM_SEC_USER_AGENT first; ALPHA_ENGINE_SEC_USER_AGENT remains an alias.
- Search root/.env, root/secrets/.env, parent/.env, and the sibling
  ALPHA_ENGINE_V12_RETURN_FIRST_STARTER/.env + secrets/.env.
- Never print, copy, commit, or persist the actual User-Agent/email or API keys.
- Run ONE SEC identity preflight before scanning the universe. A rejected identity
  aborts immediately with SEC_IDENTITY_PREFLIGHT_FAILED.
- Retain FIX1 gzip/deflate decoding and cache-integrity checks.
- No model, feature, policy, score, cost, or threshold changes.

Run
  .\\RUN_V13_PHASE5B_LIVE_SHADOW.ps1
