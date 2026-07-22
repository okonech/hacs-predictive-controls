# Predictive Controls v3 Migration Plan

**Status:** Implementation complete (Phases 0-6); deployment rollout pending
**Design authority:** `SPECIFICATION.md`
**Primary objective:** Prevent isolated and same-node flapping detections from
turning on lights while preserving same-update, single-digit-millisecond
activation for graph-supported detections and mature predictions.

## 1. Scope and Expected Size

This is a medium-large inference-core migration, not a complete integration
rewrite. Home Assistant event subscription, dispatch, and the existing per-zone
`binary_sensor.<zone>_active` entity are reusable. The current acquisition,
prediction, count-conflict, and persisted-state semantics are not.

Expected change surface:

| Area | Expected impact |
| --- | --- |
| Core model | Major changes in `types.py`, `profiles.py`, `episodes.py`, `filter.py`, `traversal.py`, `engine.py`, `policy.py`, `prediction.py`, `count.py`, and `persistence.py` |
| Integration adapters | Moderate changes in `occupancy_tracker.py`, `runtime.py`, `binary_sensor.py`, `automation_summary.py`, `status.py`, configuration, and entity-registry cleanup |
| Tests | Replace source-free and downstream-only prediction expectations; add track-confidence, incident, restart, count-conflict, and fast-path coverage across roughly 12-18 test modules |
| User-facing migration | Retire prelight entities/actions, migrate prediction options, and cold-start incompatible inference state safely |

Planning estimate: 5-7 coherent implementation changes, roughly 2,000-3,000
lines of production and test churn, followed by a shadow-observation period. A
reasonable engineering estimate is 5-8 focused development days plus 3-7 days
of live shadow evidence. This estimate is directional, not a delivery promise.

## 2. Target Event Pipeline

One sensor event must run through this ordered pipeline before Home Assistant
publication:

1. Normalize the physical-node event and retain its configured reliability.
2. Collapse aliases, duplicates, and hardware-impossible flap cadence into one
   physical episode.
3. Apply the reliability-tempered local belief likelihood exactly once.
4. Evaluate acquisition from existing confirmed context, pending adjacent
   candidates, same-zone independent evidence, boundary evidence, or the bounded
   missed-edge rule.
5. Create or advance track confidence:
   - one node: pending and publicly off;
   - two distinct sequential adjacent nodes: provisional, with only the new
     leading zone eligible to turn on;
   - three distinct sequential adjacent nodes: confirmed.
6. Evaluate mature prediction from confirmed track context only.
7. Project all evidence and prediction decisions through the one zone `active`
   policy state.
8. Publish changed `active` entities in the same runtime update.
9. Perform diagnostics materialization, persistence scheduling, route learning,
   and optional effects after the publication decision has been scheduled.

The hot path must not wait for persistence, audit serialization, route-statistic
updates, or a confirmation timer.

## 3. Delivery Rules

- Preserve one public `active` entity throughout the final implementation.
- Do not add room-specific exceptions or occupant identities.
- Capture each behavioral change as a public-contract regression before changing
  the implementation. Prove that the unchanged implementation fails the new
  regression, but do not merge a commit with a failing suite.
- Keep every merged change deterministic and fully green at 100% branch coverage.
- Develop the new behavior behind an internal test/shadow switch only as needed;
  do not expose two competing automation entities.
- Remove the temporary switch once v3 is the sole production path.

## 3.1 Requirement Map

| Phase | Governing requirements |
| --- | --- |
| 0 | `REQ-GOAL-010`, `REQ-GOV-002`, `REQ-GOV-003`, `REQ-GOV-004`, `REQ-GOV-005`, `REQ-PUBLIC-001` |
| 1 | `REQ-MAP-003`, `REQ-MAP-005`, `REQ-BELIEF-009`, `REQ-PROFILE-008`, `REQ-STATE-001`, `REQ-STATE-002` |
| 2 | `REQ-EVID-001`, `REQ-EVID-002`, `REQ-EVID-008`, `REQ-EVID-009`, `REQ-EVID-010`, `REQ-BELIEF-002`, `REQ-TRAV-001` through `REQ-TRAV-012`, `REQ-POLICY-001`, `REQ-POLICY-008`, `REQ-POLICY-009`, `REQ-PERF-001`, `REQ-PERF-006` |
| 3 | `REQ-PRED-001` through `REQ-PRED-006`, `REQ-POLICY-010`, `REQ-PUBLIC-003`, `REQ-PUBLIC-005` |
| 4 | `REQ-GOAL-006`, `REQ-COUNT-001` through `REQ-COUNT-010`, `REQ-POLICY-003`, `REQ-POLICY-011` |
| 5 | `REQ-MAP-003`, `REQ-STATE-001` through `REQ-STATE-009`, `REQ-PUBLIC-001` through `REQ-PUBLIC-005` |
| 6 | `REQ-DIAG-001` through `REQ-DIAG-005`, `REQ-PERF-001` through `REQ-PERF-007`, `REQ-GOAL-008` |

## 3.2 Reviewed Alternatives

The selected design is **A, graph-supported acquisition with bounded track
bootstrap**. A lone episode raises local belief but remains off; two sequential
adjacent nodes authorize only the leading edge; three distinct sequential nodes
confirm broader provenance. A fixed shared arrival-state transition matrix with
`P(occupied' | empty)=0.75` and `P(occupied' | occupied)=0.80` is applied only to
supported physical acquisition, after the target likelihood, so every profile
and reliability in `(0, 1]` crosses the 0.70 on threshold in the same update.

Alternative **B, positive-count source-free acquisition**, preserves immediate
single-sensor response but makes isolated false positives indistinguishable from
real isolated arrivals. Count cannot repair this without imposing an exact
whole-home assignment, and the reported closet edges demonstrate the cost.

Alternative **C, separate authorization and retention entities**, can move the
same gating into automation but violates the one-authority goal, complicates
restart and edge ordering, and does not improve the inference evidence.

Across count zero, one, and two, same-zone multiplicity, missed edges,
backtracking, stuck and flapping sensors, unavailable and out-of-order input,
restart, and latency, A contains unsupported false-ons while preserving the
zero-wait path wherever compatible physical or mature prediction evidence
exists. Its deliberate cost is that a legitimate isolated leaf detection waits
for later support.

## 4. Phase 0 — Freeze the Baseline and Add Failing Reproductions

### Work

1. Capture the two reported master-closet activations at the retained
   minute-precision event times, authoritative count, Alex-office and
   guest-bedroom context, sensor states, beliefs, and traversal facts. Mark raw
   values that were not retained as unavailable rather than inventing them.
2. Add an immutable fixture asserting that isolated closet activity never
   produces `active: off -> on`.
3. Add focused contract scenarios for:
   - one isolated positive remaining off;
   - same-node and aliased flapping remaining off;
   - first node followed by an adjacent second node activating only the leading
     zone;
   - a third distinct adjacent node confirming the track;
   - `A -> B -> A` remaining provisional;
   - a confirmed path remaining valid through held-hallway branching;
   - two confirmed fronts eventually health-degrading a contradicted stuck stay
     sensor when authoritative count is two.
4. Record the current baseline benchmark and retained-suite result.

### Files

- `tests/fixtures/zone_model/`
- `tests/test_zone_model_public_contract.py`
- `tests/test_acceptance_scenarios.py`
- `tests/test_remediation_scenarios.py`
- `tests/zone_model_requirement_matrix.md`
- `benchmarks/occupancy_performance.py`

### Exit gate

The unchanged implementation has been shown to fail the incident and every
intentionally changed expectation for the expected reason. Preserved inverse
and characterization cases are recorded as passing controls, and the evidence
is recorded for the implementation phases.

## 5. Phase 1 — Introduce v3 Types, Profiles, and Reliability Semantics

### Work

1. Add `track_bootstrap_window` while retaining
   `single_node_reacquisition` as a deprecated v2 compatibility field until the
   atomic Phase 2 cutover.
2. Add bounded immutable types for:
   - pending acquisition candidates;
   - provisional and confirmed track provenance;
   - track path references containing at most the bounded evidence needed to
     prove three distinct sequential nodes;
   - policy phase and activation provenance;
   - prediction activation leases;
   - strong-front and count-conflict state.
3. Add track confidence to traversal tokens and policy/audit decisions.
4. Separate sensor `reliability` from prediction route-prior weighting:
   - make `reliability` canonical and validate it in `(0, 1]`;
   - accept legacy `initial_reliability` and `initial_weight` values in `(0, 1]`
     as deprecated aliases for one migration release;
   - use a separate `route_prior_weight` only if prediction smoothing still
     requires one;
   - reject values above one rather than treating them as reliability.
5. Add reliability-aware filter operations and diagnostics without routing live
   v2 behavior through them until Phase 2. Scale positive and clear likelihood
   ratios in log space at the atomic v3 cutover.
6. Define the v3 fingerprint inputs now, but retain the legacy fingerprint for
   v2 and schema-6 decoding until Phase 5.

### Files

- `custom_components/predictive_controls/model.py`
- `custom_components/predictive_controls/events.py`
- `custom_components/predictive_controls/zone_model/types.py`
- `custom_components/predictive_controls/zone_model/profiles.py`
- `custom_components/predictive_controls/zone_model/filter.py`
- `custom_components/predictive_controls/occupancy_tracker.py`
- corresponding model, profile, event, filter, and validation tests

### Exit gate

The additive types and filter operations pass focused tests, legacy behavior and
fingerprints remain unchanged, and the Phase 2 cutover has one explicit switch
point. Phase 1 and Phase 2 may land in one atomic change; no intermediate build
may reference a removed field or partially apply reliability.

## 6. Phase 2 — Replace Source-Free Acquisition with Track Bootstrap

This is the largest and highest-risk phase.

### Work

1. Stop issuing traversal tokens before acquisition/traversal authorization.
2. Remove `source_free_corroborated` and every direct acquisition based only on
   positive count, high belief, elapsed time, or `single_node_reacquisition`.
3. Store exactly one pending candidate per zone, bounded by the profile's
   track-bootstrap window. Same-node/alias repeats are ignored. A distinct
   same-zone node corroborates acquisition without counting as an adjacent path
   step; otherwise the newer unsupported candidate replaces the older one only
   after the old candidate is considered for support in deterministic order.
4. Implement atomic adjacent-pair bootstrap:
   - the earlier pending episode becomes provisional traversal context;
   - the new leading episode is authorized and may turn on immediately;
   - the earlier inactive zone is not back-activated;
   - both evidence references are retained deterministically.
5. Apply the shared `q <- 0.75 + 0.05q` arrival-state transition to every
   trustworthy physically authorized target after its reliability-tempered
   local likelihood. Never apply it to pending, prediction, timer, alias, or
   flap input. Test every profile at reliability `1.0`, representative deployed
   reliability, and a near-zero positive boundary.
6. Carry a bounded path summary on provisional tokens. A third distinct adjacent
   node promotes the frontier to confirmed; aliases, callbacks, flaps, and
   `A -> B -> A` do not.
7. Once confirmed, let new graph-adjacent leading episodes inherit confirmed
   provenance while the source token remains valid.
8. Preserve independently consumable held-transition context so one hallway can
   support reversals and multiple destinations without synthesizing edges.
9. Preserve the bounded two-hop missed-edge rule, but make its authorization and
   confidence provenance explicit.
10. Treat clear/reassert events faster than the declared hardware re-arm interval
   as correlated health anomalies with no additional likelihood, candidate, or
   token.
11. Expire pending candidates and provisional/confirmed tokens deterministically
    through the normal timer frontier and restart state.

### Suggested internal design

Keep this logic in `traversal.py` unless the file becomes difficult to review. If
separation is needed, introduce one internal `AcquisitionFrontier` that owns
pending candidates and track provenance while `TraversalFrontier` owns only
authorized tokens. Do not split the public entity or require automation-side
coordination.

### Files

- `custom_components/predictive_controls/zone_model/traversal.py`
- `custom_components/predictive_controls/zone_model/episodes.py`
- `custom_components/predictive_controls/zone_model/filter.py`
- `custom_components/predictive_controls/zone_model/engine.py`
- `custom_components/predictive_controls/zone_model/types.py`
- `tests/test_zone_model_traversal.py`
- `tests/test_zone_model_episodes.py`
- `tests/test_zone_model_engine.py`
- public-contract and fixture tests from Phase 0

### Exit gate

- Isolated and same-node flapping events never activate.
- The second distinct adjacent event activates its leading zone in the same model
  update.
- The first inactive candidate is not back-activated.
- Only the third distinct adjacent node confirms the track.
- Branching, reversal, two occupants, missed edges, expiry, and restart are
  deterministic and bounded.

## 7. Phase 3 — Make Prediction an Internal `active` Authorization

### Work

1. Move prediction ownership into the atomic engine transaction, or add an
   engine-level acquisition coordinator. The current post-engine manager cannot
   safely update policy before publication.
2. Evaluate prediction after confirmed traversal authorization and before runtime
   dispatch.
3. Require all prediction activation conditions:
   - confirmed source track;
   - graph-adjacent target;
   - probability at least `0.85`;
   - at least five accepted confirmed-track observations for that route;
   - positive authoritative count;
   - no target health contradiction.
4. Replace the current 30-second downstream lease with the 10-second
   nonrenewing activation lease.
5. Extend `ZonePolicyState` to represent `inactive`, `pending`, `predicted`, and
   evidence-acquired active provenance while retaining one boolean `active`
   projection.
6. Confirm a predicted activation atomically when trustworthy target evidence
   arrives. Emit no second activation or refresh edge.
7. Expire an unconfirmed prediction directly to off after 10 seconds. Prediction
   must not alter belief or ordinary release dwell.
8. Learn routes only from confirmed physical traversal. Do not learn from
   provisional paths, predictions, confirmations, expiries, source-free legacy
   state, or health-degraded nodes.
9. Ensure normalized probability `1.0` from sparse data cannot bypass the
   five-observation maturity requirement.
10. Remove the configurable activation threshold. The fixed model threshold is
    0.85; legacy option values are ignored for activation and retained only in
    migration diagnostics for one release.

### Files

- `custom_components/predictive_controls/zone_model/prediction.py`
- `custom_components/predictive_controls/zone_model/policy.py`
- `custom_components/predictive_controls/zone_model/engine.py`
- `custom_components/predictive_controls/zone_model/types.py`
- `custom_components/predictive_controls/occupancy_tracker.py`
- `custom_components/predictive_controls/runtime.py`
- prediction, policy, engine, runtime, restart, and public-contract tests

### Exit gate

Mature prediction changes the existing zone `active` state before the runtime
dispatcher fires; confirmation produces no duplicate edge; unconfirmed expiry is
bounded; prediction never changes belief or teaches itself.

## 8. Phase 4 — Add Confirmed-Front Count Conflict and Stuck-Sensor Recovery

### Work

1. Build anonymous strong fronts only from confirmed three-node tracks, or a
   reviewed boundary/two-hop missed-edge lineage carrying equivalent confirmed
   strength, plus current/recent trustworthy stay evidence and belief above the
   on threshold.
2. Coalesce connected or overlapping token lineages so one corridor cannot count
   as several occupants.
3. Never use active state alone, pending candidates, or provisional tracks as a
   strong front.
4. Track a per-target continuous conflict frontier when at least `N > 0` disjoint
   strong fronts persist outside an asserted target.
5. Cancel the conflict immediately on compatible target traversal, a new
   independent target episode, loss of a strong front, or count change.
6. After one target release dwell of continuous conflict, health-degrade the
   contradicted asserted stay episode, close its traversal authority, and remove
   its belief floor.
7. Let existing probability decay and release dwell turn the zone off; count
   never writes `active = false` directly.
8. Recover after trustworthy stable clear and a fresh episode, including a
   physical sensor reset.
9. Cover count zero, one, and two; same-zone multiplicity; unavailable and
   out-of-order input; false clears; front loss and dwell reset; provisional
   conflicts; boundary/missed-edge equivalents; and target recovery as named
   inverse tests.

### Files

- `custom_components/predictive_controls/zone_model/count.py`
- `custom_components/predictive_controls/zone_model/episodes.py`
- `custom_components/predictive_controls/zone_model/filter.py`
- `custom_components/predictive_controls/zone_model/engine.py`
- `custom_components/predictive_controls/zone_model/policy.py`
- `custom_components/predictive_controls/zone_model/types.py`
- count, episode-health, release, multi-occupant, and restart tests

### Exit gate

Two confirmed fronts at count two eventually override one contradicted stuck
assertion without enforcing an exact occupant assignment, while a temporary or
provisional conflict cannot cause release.

## 9. Phase 5 — Persist v3 Atomically and Migrate Public Surfaces

### Persisted state

1. Change the target schema to `zone-belief-v3`.
2. Persist pending candidates, token confidence/path provenance, policy phase,
   prediction activation deadline, strong-front conflict frontier, and all
   existing deterministic episode/filter/release state.
3. Validate the complete snapshot atomically before installing any component.
4. Restore and advance every deadline exactly once; restart cannot increase track
   confidence or extend a lease/window.
5. Use half-open windows. At equal timestamps, advance all deadlines `<= t`
   before processing the external input at `t`. Add just-before, exact-deadline,
   just-after, uninterrupted, and restart variants for pending, tokens, trust,
   stable clear, prediction, count conflict, and release dwell.

### v2 import strategy

Current v2 tokens and route history are unsafe to retain because tokens were
issued before authorization and prediction learned from two-node traversal. The
safest importer is therefore conservative:

1. Validate the v2 payload using a dedicated legacy decoder and legacy map
   fingerprint.
2. Defer migration until current Home Assistant sensor snapshots are available.
3. Build fresh reliability-tempered v3 episode and belief state from those
   snapshots without synthetic movement or public events.
   A current asserted stay sensor seeds belief only and never active state.
4. Discard all v2 traversal tokens, token uses, pending state, prediction leases,
   and route counts.
5. Preserve a v2 active zone only when retained audit proves its latest unmatched
   acquisition used adjacent, same-zone independent, boundary, or bounded
   missed-edge authorization. Drop active state when provenance is absent or the
   reason is `source_free_corroborated`.
6. Do not emit a release edge for discarded compatibility state.
7. Keep one versioned backup of the v2 payload through the rollout window so a
   package rollback does not require v2 code to read v3 state.

This may temporarily leave an occupied zone off after upgrade when its old active
provenance cannot be proven. That is the intended conservative failure mode and
should be handled by performing the upgrade during a maintenance window and
walking a valid path afterward.

### Public/API cleanup

1. Keep `binary_sensor.<zone>_active` and `home_active` IDs stable.
2. Remove `ZonePrelightSensor` and its expected registry IDs after checking and
   migrating any local automations that still reference them.
3. Remove prelight booleans from `AutomationSummary`; retain prediction
   probability only as diagnostics.
4. Remove the configurable prediction activation threshold. Normal activation
   uses the fixed `0.85`; preserve an old stored value only as a one-release
   migration diagnostic and never as control input.
5. Remove prediction actions that can independently drive normal lights. Effects
   and diagnostics may consume optional arrival events, but automation does not
   recreate authorization.
6. Add active attributes for phase/provenance, track confidence, evidence IDs,
   and prediction expiry without requiring automations to inspect them.

### Files

- `custom_components/predictive_controls/zone_model/persistence.py`
- `custom_components/predictive_controls/occupancy_tracker.py`
- `custom_components/predictive_controls/storage.py`
- `custom_components/predictive_controls/binary_sensor.py`
- `custom_components/predictive_controls/automation_summary.py`
- `custom_components/predictive_controls/entity_registry.py`
- `custom_components/predictive_controls/config_flow.py`
- `custom_components/predictive_controls/actions.py`
- persistence, platform, registry, configuration, action, and runtime tests

### Exit gate

v3 round-trips byte-stably, malformed restore fails atomically, v2 migration
cannot restore unsafe authority, and only one public per-zone control entity can
turn normal lights on or off.

## 10. Phase 6 — Diagnostics, Performance, and Full Acceptance

### Diagnostics

Expose, with bounded retention:

- pending candidate and expiry;
- provisional/confirmed token provenance and bounded path references;
- reliability and effective likelihood contribution;
- strong-front membership and count-conflict start/cancel/degrade reason;
- predicted active source, probability, learned support, and deadline;
- stable reason codes required by the specification;
- model decision, dispatcher schedule, and sampled end-to-end latency.

Remove the misleading normal reason `source_free_corroborated`; retain it only in
the v2 migration decoder and historical displays.

### Performance

Add dedicated benchmark traces for:

1. existing confirmed token to adjacent target;
2. adjacent-pair provisional bootstrap;
3. provisional third-node confirmation;
4. same-zone independent evidence;
5. entry-boundary authorization;
6. bounded missed-edge authorization;
7. mature prediction activation; and
8. pending expiry and count-conflict timer work outside the fast path.

Required gates on the 16-zone, count-two reference map:

- accepted runtime input through dispatcher, current-state entity projection,
  and `ZoneActiveSensor.async_write_ha_state` p99 at or below 5 ms;
- every measured production publication path below 10 ms;
- entity state write scheduled in the same Home Assistant update;
- bounded token, candidate, conflict, prediction, and audit state;
- byte-stable persistence and deterministic replay.

### Full validation

Run and retain:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
.venv/bin/python -m pytest -q
npm run test:frontend
.venv/bin/python benchmarks/occupancy_performance.py \
  --events 100 \
  --output /tmp/predictive-controls-performance-v3.json
git diff --check
```

## 11. Rollout and Backout

The code migration and offline acceptance gates are complete. The live replay,
shadow-observation, maintenance-window activation, and later removal of the v2
rollback backup remain operator-run deployment steps because they require real
Home Assistant event traffic and elapsed observation time.

1. Run the complete retained corpus and at least seven days of recorded event
   replay before live shadowing.
2. Shadow v3 without a second public entity. Record only `would_activate`,
   `would_reject`, provisional/confirmed transitions, prediction outcomes, and
   decision latency.
3. Shadow live for at least 72 hours or until the normal path corpus includes the
   master suite, both offices, shared rooms, reversals, quiet stays, and two
   simultaneous confirmed fronts.
4. Go live only when:
   - both closet incidents remain off;
   - isolated and flapping episodes produce no activation;
   - supported leading edges and mature predictions satisfy the latency gate;
   - no provisional track affects count, health, prediction, or learning;
   - predicted false-ons remain within the declared 10-second lease;
   - all retained tests and performance gates pass.
5. Activate v3 during a maintenance window, preserve the v2 payload backup, and
   walk representative valid paths after startup.
6. Back out by reinstalling the prior integration version and restoring the
   preserved v2 payload. Do not attempt to make v2 interpret v3 state.
7. Remove the temporary shadow path and v2 backup after one stable release and
   the agreed observation period.

## 12. Principal Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Two-node false coincidence turns on one target | Contain provisional authority to the leading zone; prohibit global count, health, learning, and prediction use until three distinct nodes |
| Legitimate isolated leaf arrival remains off | Accept as the deliberate false-positive bias; rely on direct adjacency, bounded missed edge, mature prediction, or sensor reset/path recovery |
| Track branching accidentally becomes identity assignment | Store bounded anonymous episode lineage only; allow independent consumption and coalesce only for count diagnostics |
| Prediction creates a feedback loop | Require confirmed physical history and minimum support; never update belief or learning from prediction or confirmation |
| v2 restore reintroduces unsafe source-free authority | Discard v2 tokens/routes and preserve active only with retained non-source-free audit provenance |
| Count conflict falsely releases a valid stay | Require `N` confirmed disjoint fronts continuously for a full release dwell; count only health-degrades, ordinary belief/release still decides off |
| New hot-path work breaks latency | Decide and schedule publication before audit, persistence, learning, and whole-home diagnostics; benchmark each fast path independently |
| Prelight removal breaks an automation | Inventory entity-registry and automation references before rollout; migrate normal control to the stable `active` entity |

## 13. Definition of Done

The migration is complete when the implementation, tests, persisted schema,
diagnostics, and Home Assistant public surface all satisfy `SPECIFICATION.md`;
the master-closet incident and all retained regressions pass; no isolated or
same-node flapping event can turn on a light; two-node supported leading edges and
mature predictions publish in single-digit milliseconds; and production uses
only the one per-zone `active` entity for normal control.

## 14. Implementation Record

Completed on 2026-07-21:

| Phase | Completed result |
| --- | --- |
| 0 | Retained the minute-precision master-closet incident as an immutable public-contract regression and recorded the v2 failure mechanism. |
| 1 | Added bounded v3 types, canonical sensor reliability, distinct route priors, shared calibration, and inference-complete fingerprints. |
| 2 | Removed source-free acquisition; added one pending candidate per zone, adjacent-pair leading-edge activation, three-node confirmation, bounded missed-edge handling, and flap containment. |
| 3 | Moved mature prediction into the same `active` policy with a fixed 0.85/5-observation gate and nonrenewing 10-second lease. |
| 4 | Added coalesced confirmed strong fronts, count-conflict dwell, health degradation, ordinary release, and reset recovery without occupant identities. |
| 5 | Added atomic `zone-belief-v3` persistence, conservative v2 import and rollback backup, exact deadline ordering, and removal of normal prelight/action/threshold control surfaces. |
| 6 | Added bounded provenance/reliability/conflict diagnostics; seven independent, path-qualified 100-sample fast-path benchmarks measured from accepted runtime input through all 34 registered binary sensors, the 18-subscriber production update fanout, the corresponding `ZoneActiveSensor` projection/signature, and `async_write_ha_state`; and separate 100-sample pending-expiry and count-conflict deadline traces outside that fast path. The final offline gate is 504 Python tests at 100% statement/branch coverage, 29 frontend tests and a reproducible bundle, Ruff, strict mypy, and byte-stable persistence. On the reference host, production-publication p99 values were 0.818-2.445 ms and maxima were 0.879-2.565 ms; pending-expiry and count-conflict p95 values were 0.205 ms and 1.228 ms respectively. |
