# V13 Pre-holdout Freeze

This repository was created only after the pre-2025 research process was closed.

The canonical freeze identifier is read from `artifacts/freeze/v13_phase3aa_freeze_manifest.json` and is verified by the bootstrap script before the first commit. The script also recalculates the SHA-256 digest of every file listed in that manifest and aborts on any mismatch.

The purpose of this checkpoint is methodological: the 2025+ code-blinded holdout must be evaluated against exactly the model, configuration, and portfolio mechanics that existed before the holdout was opened.

No post-holdout result should be used to rewrite this tag. Any later development belongs in subsequent commits/tags and must preserve this checkpoint.
