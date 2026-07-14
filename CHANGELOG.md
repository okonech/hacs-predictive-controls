# Changelog

## 0.1.20 release candidate

### Added

- Added a Reliability panel tab that ranks repeated policy-rejected motion
	captures and repeated short low-confidence pulses from the retained audit,
	including exact coverage, policy reasons, and peak occupied confidence.
- Restored Occupancy-tab tracks as deterministic anonymous projections of the
	exact posterior, including same-zone multiplicity and asserted source entities
	without claiming persistent person identity.

### Fixed

- Added a one-use `censored_graph_path` movement candidate for a quick return
	through a still-on transient gate whose PIR cannot emit a second positive
	edge. Eligibility follows configured graph timings, preserves the actual
	occupant source and intermediate gate provenance, survives compatible restart,
	and supports activation without changing thresholds or affecting release,
	prediction, or learning. The retained two-occupant regression uses the exact
	2026-07-14 production timestamps and verifies entrance, closet, and bathroom
	activation.
- Released `keep_on` for a supported intermediate-zone departure when anonymous
	route histories disagree about the older route origin but overwhelmingly agree
	on the immediate graph-valid segment. Release now audits both absolute segment
	mass and destination-normalized segment share while retaining low-origin,
	material-decrease, and occupied-destination gates. The retained regression uses
	the exact 2026-07-13 production event timestamps and policy probabilities.
- Preserved sustained origin evidence when graph-valid movement carries one of
	two occupants away but the exact posterior still supports another occupant in
	the origin. Interleaved activity can no longer erase a continuously asserted
	room episode unless final-occupant departure is also supported. When another
	occupant can explain an adjacent arrival, movement out of the asserted origin
	now pays the alias-safe calibrated observation likelihood instead of treating
	both source assignments as equally plausible.
- Collapsed correlated aliases from one physical map node into one effective
	observation and duration factor. Additional asserted aliases no longer
	multiply same-room occupancy or manufacture movement, and schema 3 posterior
	state rebuilds once from the current Home Assistant snapshot under schema 4.
- Stopped treating normalized coherent movement mass as an absolute activation
	gate. Fresh graph-valid arrivals now activate when the source prior and the
	existing `0.60` occupied-marginal and `0.20` increase gates pass, avoiding
	missed arrivals when valid joint alternatives dilute one path below `0.40`.
- Retained complete observation context with each policy audit event using
	lossless compressed JSON. Audit history is now FIFO-bounded to 12 hours, 8,192
	decisions, and 12 MiB of compressed context, with actual usage and coverage in
	integration diagnostics.
- Scheduled coalesced Store persistence for every processed observation,
	including duplicate, stale, and rejected events needed to explain no-action
	decisions.
- Canonicalized persisted audit probabilities to prevent floating-point
	roundoff such as `1.0000000000000002` from invalidating restart state produced
	by the integration itself.
- Added bounded, restart-safe sustained-duration evidence and explicit assertion
	validity intervals without rewriting movement timestamps. Sustained local
	evidence now survives unrelated activity while low-prior missed relocation
	remains possible.
- Removed timer and low-confidence release ownership. `keep_on` now releases
	only for supported departure or relocation, authoritative count or away state,
	or explicit reset. Recovery from legacy persisted provisional releases remains
	supported.
- Added bounded variable-order anonymous route learning with deterministic
	backoff, aging, persistence, and diagnostics. Route history only influences
	graph-valid prediction leases.
- Made callback latency degradation diagnostic-only; exceeding the hard budget
	no longer suppresses an otherwise valid activation.
- Required corroboration from distinct physical nodes before non-adjacent
	relocation can activate a destination or release sustained origin ownership.
	Correlated aliases from one flapping device no longer manufacture independent
	evidence, while genuinely independent destination sensors can still override a
	stale or stuck origin assertion.
- Kept each occupancy card's last-node attribution scoped to events from that
	zone instead of copying the latest whole-house observation onto every zone.

### Rollout status

This candidate replaces 0.1.19. The seven-day Home Assistant shadow/soak gate
remains uncollected and must restart on the exact 0.1.20 code revision.

## 0.1.19 release candidate

### Fixed

- Extended the Home Assistant `Store` migration hook to accept both version-1 and version-2 persistence wrappers. Version 1 was present in a deployed installation and still prevented config-entry setup in 0.1.18.

### Rollout status

This hotfix replaces the setup-broken 0.1.18 candidate. The seven-day Home Assistant shadow/soak gate remains uncollected and must restart on the exact 0.1.19 code revision.

## 0.1.18 release candidate

### Fixed

- Added the required Home Assistant `Store` migration hook so existing version-2 persistence wrappers load into schema 3 instead of aborting config-entry setup with `NotImplementedError`.
- Preserved legacy transition and policy data for the existing semantic migration and validation path.

### Rollout status

This hotfix replaces the setup-broken 0.1.17 candidate. The seven-day Home Assistant shadow/soak gate remains uncollected and must restart on the exact 0.1.18 code revision.

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
