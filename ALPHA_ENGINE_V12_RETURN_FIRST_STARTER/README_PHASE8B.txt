ALPHA ENGINE V12 - PHASE 8B
PRE-OOS EXECUTION PARITY LOCK

WHY THIS EXISTS
Phase 8 correctly froze the model/policy and audited optimizer/MILP lineage, but its NAV replay used the event-driven membership target without applying the audited MILP weights. Phase 8B fixes implementation parity BEFORE final OOS is opened.

NO PARAMETER RESELECTION
- same 9 H20 features
- same frozen feature weights and expected-return calibration
- same Top-15
- same entry floor / uncertainty / minimum extra edge / max replacements
- same 20/40 bps costs

EXECUTION CONTRACT
1. frozen net-edge decides membership changes
2. only when membership changes, expected-return LCB determines theoretical weights
3. continuous cap is applied
4. MILP discretizes those SAME approved 15 names
5. execution occurs next session
6. MILP may not introduce or remove names beyond the net-edge membership decision

2025+ remains unopened.
