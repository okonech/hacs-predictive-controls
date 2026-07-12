# Changelog

## 0.1.17 release candidate

### Changed

- Replaced ranked occupant tracks with exact anonymous zero-, one-, and two-occupant inference over a fixed configuration space.
- Added bounded directional contexts, sparse event-conditioned movement, path-specific evidence, deterministic replay ordering, and zero supported-count probability pruning.
- Made `activation_plausible`, `keep_on`, and optional `prelight_plausible` the canonical automation contract.
- Made `keep_on` conservative across local clears, elapsed time, restart, unsupported dynamic counts, and ambiguous movement.
- Added schema-3 persistence for posterior, contexts, policy, pending departures, evidence, leases, and transition counts, including schema-2 migration and safe map reconciliation.
- Added explicit unsupported-count diagnostics. Static counts above two are rejected; dynamic counts above two suspend inference while retaining established `keep_on` latches.
- Added a 100 ms hard runtime ceiling. An over-budget update completes atomically but suppresses activation and predictive actions.
- Added whole-package branch coverage, scenario-dominant coverage, strict typing, repository lint, frontend tests, portable benchmark fixtures, and CI quality gates.

### Verified evidence

- 364 Python tests pass with 100.00% whole-package branch coverage.
- 141 timestamped scenarios pass with 90% aggregate branch coverage across the replacement filter, policy, prediction, persistence, and runtime modules.
- Strict mypy passes all 64 Python source and test files.
- Ruff passes repository-wide; 24 frontend tests pass.
- The checked-in 16-zone, 17-node, 23-entity reference benchmark passes all PERF-001 through PERF-007 gates over 10,000 events. Core maximum is 15.389 ms; runtime maximum is 17.953 ms; zero occupancy probability is pruned.

### Rollout status

This is a release candidate, not a completed production cutover. The required seven-day Home Assistant shadow/soak evidence has not been collected. Follow `SHADOW_VALIDATION.md`; do not mark the behavioral specification implemented or remove the rollout blocker until that evidence passes review.
