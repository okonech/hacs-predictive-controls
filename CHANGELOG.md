# Changelog

## 0.2.4

### Changed

- Replace the standalone Zone Beliefs list on the Occupancy tab with belief,
  policy, profile, evidence, and anonymous traversal-frontier details embedded
  directly in the zone graph.
- Highlight possible next paths and recent directed traversal authorizations on
  graph edges without presenting anonymous evidence as persistent person tracks.

## 0.2.3

### Fixed

- Treat `review_required` as advisory once role, occupancy behavior, and signal
  type resolve a deterministic physical profile. This prevents reviewed legacy
  maps from failing integration startup.
- Bootstrap and validate the target model before registering runtime callbacks,
  so a setup error cannot leave orphaned event and timer subscriptions behind.
- Keep the panel usable when live status is unavailable, and report a clear
  integration setup error instead of rendering a config-entry ID.

## 0.2.2

### Fixed

- Register the Predictive Controls custom panel through Home Assistant's current
  `module_url` loader instead of the legacy `js_url` path. The new versioned
  bundle URL also invalidates stale or corrupted cached panel responses.
- Add a repeatable frontend build command and a real-browser smoke page that
  verifies a config-entry ULID cannot render as the panel body.

## 0.2.1

### Changed

- Replaced exact whole-home occupant assignment and support certificates with
  graph-local per-zone beliefs, finite physical episodes, anonymous traversal
  tokens, and probability-driven Schmitt policy hysteresis.
- Made the zone-belief engine the sole runtime, entity, WebSocket, diagnostics,
  automation-summary, and persistence authority. Store schema 7 retains a
  read-only schema-6 migration seed without executing legacy inference.
- Reworked the Activity and occupancy workspaces around target beliefs, policy
  edges, traversal authorization, prediction leases, and sensor-health warnings.
- Retained optional prediction as isolated 30-second graph-adjacent leases using
  bounded anonymous Markov counts. Prediction cancels on newer target evidence
  or count zero and never feeds occupancy or normal `active`.
- Replaced the performance artifact with the 100-event target benchmark and
  bounded token, audit, persistence, and callback-latency gates.

### Removed

- Removed the exact inference package, fixed-lag association, factor chain,
  global assignment/support state, legacy policy/route/dwell layers, shadow
  comparator, and their internal-only tests.
- Removed retired compatibility diagnostics/entities and unused historical panel
  bundles. Stable `active`, `prelight`, `home_active`, problem, and arrival event
  IDs remain on the public automation surface.

### Fixed

- Made decay, threshold crossing, release dwell, traversal expiry, stuck-sensor
  degradation, and restore advancement independent of timer callback cadence.
- Preserved atomic state on rejected restores, including malformed prediction
  state, and cancel prediction leases when newer physical target evidence
  contradicts or resolves them.
- Corrected schema-6 seeding, untouched-zone restore, traversal-token reuse,
  outward context, stale input, unavailable sensor, and manual-refresh behavior.

## 0.2.0 release candidate

### Changed

- Replaced production occupancy inference with the exact event-indexed anonymous
	count-vector model for every supported authoritative count from zero through
	two.
	Complete same-zone multiplicity is retained with zero probability pruning.
- Replaced removable current-state factors and capped directional contexts with
	physical-node episodes, incremental duration survival, and deterministic
	bounded fixed-lag movement/data association.
- Replaced legacy acquisition/release gate conjunctions with posterior-event
	`ArrivalSupported` and `ReleaseSafe` probabilities, asymmetric policy
	thresholds, durable `active`, and optional `prelight`.
- Made exact inference the sole production authority. The release-0.1.20 engine
	remains isolated as a replay comparator for retained tests and is not imported
	by runtime, tracker, status, entities, actions, or persistence dispatch.
- Upgraded Home Assistant Store persistence to version 6 with exact augmented
	state, deterministic unresolved-work restore, and bounded target policy audit.
	Schema-5 input has a one-way compatibility reader that preserves sanitized
	ownership and learned counts without translating legacy evidence into target
	posterior support.
- Extended static configuration, authoritative count entities, WebSocket
	settings, the panel, inference, diagnostics, and persistence to counts zero
	through two. Well-formed values above two enter the explicit unsupported-count
	state and are never approximated or coerced into a supported posterior.
- Made `active`, optional `prelight`, `home_active`, and the problem entity the
	default automation surface. Existing `activation_plausible`, `keep_on`,
	`prelight_plausible`, and `home_keep_on` IDs remain compatibility projections
	for the documented `ENT-010` release window.
- Changed production binary projections to publish only on native on/off edges,
	with a concise text explanation on each published state. Optional diagnostic
	entities now share one 30-second sampled runtime signal, while the
	authoritative occupant count remains immediate on value or availability edges.
- Kept exact inference and lightweight policy decisions event-complete while
	building full exact audit contexts lazily on durable latch edges and 30-second
	policy samples. Multi-row samples retain one context, every latch edge retains
	its context, and packing or out-of-order events cannot advance the sample
	frontier incorrectly.

### Added

- Added disabled-by-default per-zone occupancy, `ArrivalSupported`, and
	`ReleaseSafe` probability sensors plus the authoritative occupant-count sensor.
- Added disabled-by-default idempotent per-zone arrival events with immutable
	physical-node episode IDs and `acquired`/`refreshed` event types.
- Added target policy-audit persistence and diagnostics containing accepted and
	rejected decisions, threshold values, evidence IDs, and latch transitions.
- Added exact operator/oracle, count-transition, episode, fixed-lag,
	persistence/replay, policy, and supported-count regression coverage. Low-level
	state-space stress tests retain generalized coverage above the product limit.

### Fixed

- Preserved finite branch-local localization for a currently asserted sustained
	physical-node episode without extending that episode's movement endpoint to
	unrelated later events. Endpoint alternatives are now normalized as one
	categorical transition per predecessor, coherent graph-valid movement retains
	full multiplicity, and only the low-prior `missed_movement` branch is prevented
	from spending the final occupant supported by a sustained source. A single
	non-adjacent endpoint or correlated same-node flap still cannot authorize
	activation.
- Raised the shared sustained-duration evidence ceiling from `ln(4)` to `ln(24)`
	after the generic zero-, one-, and two-occupant replay corpus passed. In the
	frozen production incident, Guest Bedroom occupancy increased from `0.82405`
	to `0.96274`, Bedroom Entrance `ReleaseSafe` reached `0.95720`, and the
	unrelated held entrance released while the asserted bedroom remained occupied.

### Performance

- The checked-in 16-zone, 17-node, 23-entity benchmark covers 10,000 deterministic
	updates at the maximum supported count of two occupants (153 configurations),
	with exact normalization, zero pruning, deterministic restart, and measured
	startup, persistence, operator storage, and memory limits.
- Coalesced commuting zone-likelihood factors within each endpoint-delimited
	segment by summing their log-potentials and retaining the latest contributing
	event time. This preserves the sequential exact posterior and endpoint
	prefixes while bounding factor storage by unresolved endpoints and zones rather
	than raw event volume.

### Rollout status

Production migration implementation is complete. Independent conformance, all
repository quality gates, the final release benchmark, and the seven-day Home
Assistant target-contract observation remain release blockers until recorded.

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

This is a release candidate, not a completed production cutover. Its required seven-day Home Assistant shadow/soak evidence was never collected. The checklist was later retired when `SPECIFICATION.md` replaced that model; current rollout gates are in `MIGRATION_PLAN.md`.
