ALPHA ENGINE BYMA 1.0.1
=====================

Purpose
-------
Executable Argentine-market version of the Alpha Engine.

It does NOT throw away V13. V13 remains the frozen "IDEAL" model and can later
be displayed on the website as the frictionless benchmark / live paper track.

ALPHA ENGINE BYMA reuses the validated V13 forecast surface but changes the
portfolio problem BEFORE allocation:

    V13 forecast -> current BYMA-accessible universe -> rebuild weights
    -> persistent portfolio -> integer BYMA execution -> capital capacity

This is deliberately NOT:
- V13 target weights with inaccessible names simply deleted.
- A Top-N.
- Manual stock picking.
- A post-hoc replacement of unavailable names.
- A guarantee of future return.

Run
---
1. Extract ALPHA_ENGINE_BYMA to:
   C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_BYMA

2. From that folder:
   .\RUN_ALPHA_ENGINE_BYMA_FULL.ps1

Outputs
-------
outputs\byma_summary.json
outputs\byma_continuous_comparison.csv
outputs\byma_integer_capacity.csv
outputs\byma_current_target.csv
outputs\byma_master.csv
outputs\byma_pre2025_nav_20bps.csv
outputs\byma_holdout_nav_20bps.csv

Final states
------------
PRODUCTION_CANDIDATE
CAPITAL_INSUFFICIENT
REJECT_ALPHA_PORTABILITY
REJECT_INTEGER_IMPLEMENTATION

Interpretation
--------------
PRE2025 is primary design evidence.
2025+ is secondary/post-hoc because V13 holdout has already been inspected.
A production candidate still deserves forward shadow monitoring, but this build
answers the important engineering question immediately: whether the validated
V13 signal transfers to a BYMA-native portfolio without deleting inaccessible
targets after allocation.


1.0.1 correction
----------------
The 1.0.0 release incorrectly used the legacy Comafi CEDEAR-SHARES page.
1.0.1 uses the current official Programas-CEDEARs master and fails closed unless
current ratios pass explicit certification checks before any portfolio simulation.
Do not use 1.0.0 results for integer sizing or the final portability verdict.
