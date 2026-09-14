ALPHA ENGINE V13 - PHASE 5A
SHADOW PRODUCTION PARITY CONTRACT

This is NOT new research and NOT a new backtest.
It validates that the sealed Phase4 bundle exactly reproduces the persisted holdout advisor,
then emits the stable model-only contract that future Sheets/web integrations will consume.

NO broker orders. NO retraining. NO retuning. NO Top-N. NO new cap. NO fixed holding period.

Run:
  .\RUN_V13_PHASE5_SHADOW_CONTRACT.ps1

Outputs:
  outputs/shadow/v13_shadow_contract_summary.json
  outputs/shadow/v13_shadow_contract_latest.csv
  outputs/shadow/v13_shadow_contract_latest.json

The contract intentionally does NOT issue BUY/HOLD/REDUCE/EXIT against a real portfolio yet.
Those actions require current holdings/cash from the operational layer (Google Sheets / API),
which will be connected only after this parity gate passes.
