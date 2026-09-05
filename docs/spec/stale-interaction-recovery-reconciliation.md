# Stale Interaction Recovery And Same-Zone Availability Reconciliation

**Status:** Implemented incident repair for
`INC-2026-08-23-stale-interaction-recovery`

**Affected layers:** Home Assistant event normalization, physical episodes, zone
belief, policy, persistence validation, diagnostics, and retained public tests

**Related authority:** `REQ-GOAL-001`, `REQ-GOAL-003`, `REQ-GOAL-004`,
`REQ-GOAL-008`, `REQ-MAP-004`, `REQ-EVID-002`, `REQ-EVID-005`,
`REQ-EVID-006`, `REQ-EVID-011`, `REQ-BELIEF-001`, `REQ-POLICY-002`,
`REQ-POLICY-003`, `REQ-PUBLIC-002`, `REQ-STATE-002`, `REQ-STATE-003`,
`REQ-STATE-006`, `REQ-STATE-008`, `REQ-PERF-001`, and `REQ-GOV-001` through
`REQ-GOV-006`

## 1. Objective

Prevent retained Home Assistant event-entity timestamps from being interpreted
as fresh physical interaction presses when those entities recover availability.
Prevent an unavailable interaction-only node from deleting the current asserted
context of another trustworthy same-zone stay episode.

The public outcome is exact:

1. Stale interaction recovery emits no `active`, arrival, or refresh edge and
   contributes no belief, traversal, count, prediction, support, or learning
   authority.
2. A clear Shaila Office and Upstairs Bathroom remain inactive during the
   retained deployment callback burst.
3. Alex Office remains active while its mapped mmWave episode remains asserted;
   the unknown interaction alias remains node-local health state and cannot
   start or continue public release dwell for the distinct asserted stay
   episode.

## 2. Verified Current State

The immutable evidence record is
`tests/fixtures/zone_model/INC-2026-08-23-stale-interaction-recovery.md`.
The retained public regression is
`tests/incidents/test_inc_2026_08_23_1909z_stale_interaction_recovery_does_not_change_occupancy.py::test_inc_2026_08_23_1909z_stale_interaction_recovery_does_not_change_occupancy`.
It fails against unchanged behavior because Shaila Office falsely becomes
active.

The controlling path is:

1. `PredictiveControlsRuntime._async_state_changed` passes the Home Assistant
   `state_changed` event time and `new_state.state` to `observe_entity`.
2. `event_from_entity` converts every non-health state of a mapped interaction
   event entity to `pressed`, without validating the timestamp encoded in the
   event entity state.
3. `PhysicalEpisodeTracker.observe` starts a fresh interaction episode for each
   accepted alias callback.
4. `ZoneBeliefFilter.apply_interaction` sets the zone to the finite log-odds
   ceiling, and local-interaction authorization acquires or refreshes policy.
5. A later `unknown` alias reaches `ZoneModelEngine._observe`, which calls
   `ZoneBeliefFilter.apply_unavailable` for the entire zone. That clears
   `asserted_episode_id` even when a distinct same-zone mmWave episode remains
   asserted.
6. Ordinary elapsed decay and release dwell then release Alex Office despite the
   continuing physical assertion.

The behavior exposes two specification gaps. `REQ-EVID-006` names Home Assistant
`time_fired` as the occurrence frontier but does not distinguish the semantic
last-event timestamp carried by EventEntity state. `REQ-MAP-004` makes health
node-local for traversal but does not explicitly define zone-filter aggregation
when another physical node in the same zone remains asserted.

## 3. Authority Amendments

The sole model authority must be amended before production behavior changes.

### 3.1 Interaction occurrence frontier

Amend the input contract, `REQ-EVID-006`, and `REQ-EVID-011` so that a mapped
Home Assistant EventEntity has three relevant times:

- its parseable, timezone-aware ISO state value is the physical interaction
  occurrence frontier; and
- the enclosing `state_changed.time_fired`, or the direct observation time,
   bounds the encoded occurrence and establishes callback ordering; and
- runtime callback receipt remains `processing_at` for latency and audit.

`unknown` and `unavailable` remain health observations at their callback event
time. A non-health interaction state that is not a parseable aware timestamp is
invalid and ignored. A parsed timestamp later than its callback time is also
invalid. A parsed interaction timestamp before the model frontier is stale under
existing event ordering and cannot start an episode. Equality remains subject
to existing physical-node duplicate and idempotency rules; it is not globally
rejected because a distinct node may have a valid event at the same frontier.
No tolerance or incident-derived timing constant is introduced. This exception
is specific to the EventEntity contract; ordinary state entities continue to
use Home Assistant `time_fired` as their occurrence frontier.

### 3.2 Same-zone availability aggregation

Amend `REQ-MAP-004`, `REQ-BELIEF-001`, and the belief context state machine:

- unavailability always invalidates the affected physical node's pending
  candidate, traversal token, count support, and health-derived authority;
- before selecting zone context `unavailable`, the engine checks current
  physical episodes in that zone;
- if an episode in that zone is currently known-on, `asserted`, not
   health-degraded, and has a valid episode identity, that episode remains the
   zone's asserted context. It may be the same multi-alias state episode when
   another alias remains on, or an episode from a distinct physical node;
- deterministic selection uses the latest event frontier, then node ID, when
  more than one trustworthy asserted episode exists;
- context reselection is a zero-likelihood correction. It adds no positive,
  arrival, traversal, support, count, prediction, learning, activation, or
  refresh authority; and
- if no trustworthy asserted same-zone episode exists, existing unavailable
  context and ordinary release behavior remain unchanged.

This amendment does not make an asserted level sufficient to acquire an
inactive zone. It only preserves already-acquired public retention and the
bounded local evidence of an episode that was independently accepted.

## 4. Scope And Non-Goals

### In scope

- mapped interaction-only Home Assistant EventEntity normalization;
- live callbacks, startup snapshot, restore, out-of-order delivery, and
  unavailable recovery;
- all zones with one or more physical nodes, including mixed interaction and
  ordinary state nodes;
- deterministic zone-context reselection with bounded diagnostics;
- exact incident, inverse, persistence, and runtime adapter tests; and
- generated public behavior through the existing per-zone `active` entity.

### Non-goals

- no room, entity, scene number, person, household member, or incident-time
  branch;
- no threshold, likelihood, decay, dwell, cadence, profile, count, traversal,
  prediction, or benchmark calibration change;
- no repeated evidence from assertion duration, callback count, aliases, or
  timer reevaluation;
- no acquisition from a startup level or stale EventEntity state;
- no inference from lights, actuators, or policy outputs;
- no automation workaround or new public entity; and
- no rewrite of Home Assistant event entities or device integrations.

## 5. Invariants

1. A genuine live physical interaction whose aware timestamp is newer than the
   model frontier remains a conclusive finite-ceiling observation and retains
   existing immediate local acquisition behavior.
2. A retained timestamp replay is stale even when its availability callback is
   new. Callback recency cannot rewrite physical occurrence time.
3. Startup snapshots continue to neutralize retained EventEntity values and
   emit no synthetic movement or public edge.
4. `unknown` and `unavailable` remain neutral rather than clear or absence
   evidence.
5. Node unavailability always removes that node's traversal and support
   authority, even when another same-zone assertion preserves zone belief.
6. Context reselection never reapplies local positive likelihood and never
   renews the selected episode's traversal validity.
7. Stable clear of the reselected episode still contributes exactly one
   calibrated weak absence update and restores ordinary release behavior.
8. Count zero remains categorical and releases active outputs immediately.
9. A health-degraded or count-conflicted episode is not eligible as a
   trustworthy availability fallback. Cadence correlation or warning alone
   does not remove a currently asserted stay episode's bounded local retention
   authority under `REQ-EVID-012`.
10. Equal ordered inputs, restored state, and map produce equal selection,
    belief, policy, audit, and persistence output.
11. Contribution, audit, episode, token, support, and policy retention remain
    bounded by existing limits.
12. The event callback remains non-blocking and performs only parsing, bounded
    same-zone selection, and existing model updates.

## 6. Proposed Design

### 6.1 Event normalization

Add a private parser in `events.py` for mapped interaction state values. It
accepts ISO-8601 values with `Z` or an explicit UTC offset and returns a UTC
instant. Naive, malformed, non-finite, and callback-future values are rejected.
Parsing catches `TypeError`, `ValueError`, and timestamp-range failures inside
the adapter; none may escape the non-blocking Home Assistant callback.

The exact adapter is
`_interaction_event_at(state: str, callback_at: datetime) -> datetime | None`.
It replaces terminal `Z` with `+00:00`, parses with `datetime.fromisoformat`,
requires an aware value, normalizes any explicit offset to UTC, rejects
`parsed_at > callback_at`, and returns `None` on rejection. For a valid live
interaction, `event_from_entity` returns `state="pressed"` and
`event_at=parsed_at`. Startup still passes `allow_unsupported_state=True` and
normalizes every non-health interaction state to `unknown` without parsing it
as a pulse.

`event_from_entity` behavior becomes:

| Binding and raw state                                         | Normalized state  | Event frontier         |
| ------------------------------------------------------------- | ----------------- | ---------------------- |
| interaction, aware ISO timestamp                              | `pressed`         | parsed state timestamp |
| interaction, `unknown`/`unavailable`                          | unchanged         | callback event time    |
| interaction, malformed non-health value during live operation | ignored           | none                   |
| interaction, non-health startup snapshot                      | `unknown`         | snapshot frontier      |
| ordinary state binding                                        | existing behavior | callback event time    |

Runtime continues to pass callback receipt as `processing_at`; its
`state_changed.time_fired` value is the upper bound used to reject a
callback-future interaction timestamp. Existing engine stale ordering rejects
recovered retained timestamps before episode mutation.

### 6.2 Availability reconciliation

Add one engine helper, owned by `ZoneModelEngine` because only the engine can
see physical episodes and zone membership, that handles zone-filter response
after an accepted `unknown` or `unavailable` episode update. It reads the
bounded episode snapshot, selects eligible same-zone asserted candidates, and
either:

- invokes a new zero-delta filter context-reselection method with the selected
  episode ID; or
- invokes existing `apply_unavailable` when no candidate exists.

The helper is used by both cold bootstrap snapshot processing and live observe.
Episode, frontier, pending-candidate, token, support, and count invalidation
remain on their existing node-local paths.

For live health input, execution order is fixed: advance pending model deadlines
to the callback frontier; apply physical-node health mutation and its node-local
invalidation; select from the resulting episode snapshot; apply exactly one
zone-context operation; then evaluate policy once. For bootstrap, timestamp
states are already normalized to neutral `unknown`; the helper's purpose is to
prevent those neutral nodes from replacing a concurrently asserted raw state,
not to suppress a bootstrap interaction acquisition that cannot occur.

Compatible restore receives a separate zero-evidence reconciliation after
elapsed advancement. It intersects current raw `on` state nodes with already
restored matching episodes. Only a restored episode that is still `asserted`,
known-on, healthy, and current-on in the startup snapshot may be selected. This
operation does not feed raw `on` through `PhysicalEpisodeTracker.observe`, does
not create a generation or likelihood, does not restore traversal or support,
and does not acquire or refresh policy. A restored inactive policy remains
inactive. A raw level with no matching restored asserted episode is ignored for
compatible restore under `REQ-STATE-003` and `REQ-STATE-006`.

The filter remains ignorant of nodes and candidate eligibility. Its new method
is
`reselect_asserted_context(episode_id: str, at: datetime) -> ZoneBeliefState`.
It requires a non-empty identity, calls its own idempotent `_advance_to(at)`,
and only applies the engine's selected identity. If context and both episode
identities already match, it is a no-op. Otherwise it changes `context`,
`generation_episode_id`, `asserted_episode_id`, `outward_context`, and
`health_warning` consistently. It records no belief contribution because no
observation or likelihood occurred. Existing zone context and episode
diagnostics expose the correction without extending the persisted enum. It does
not call any likelihood or traversal function.

The engine owns
`_select_asserted_context(zone: str, eligible_node_ids: frozenset[str] | None = None) -> EpisodeState | None`
and `_reconcile_zone_availability(zone: str, at: datetime, eligible_node_ids: frozenset[str] | None = None) -> None`.
Live and cold-bootstrap calls pass no node restriction after episode mutation.
Compatible restore passes exactly the physical node IDs whose current raw
snapshot contains at least one ordinary `on` alias. The selector returns the
eligible episode object so tests and callers retain one identity source.

### 6.3 Deterministic candidate selection

A candidate must satisfy all of:

- same `zone` as the unavailable update;
- non-null `episode_id` and `last_event_at`;
- `known_on` true;
- `status == "asserted"`;
- `health_warning` false; and
- profile and identity valid under existing snapshot validation.

Cadence warning does not disqualify a still-asserted stay episode. An
interaction-only node affected by any health alias is unavailable under
`REQ-MAP-004` and therefore fails the `status == "asserted"` predicate without a
separate node-name exception. Select Python `max` with the exact lexicographic
key `(last_event_at, node_id, episode_id)`: latest event wins, then the
lexicographically greatest node ID, then episode ID. This is deterministic and
bounded by configured physical nodes. It does not claim occupant identity or
choose among public zones.

### 6.4 Persistence and rollback

The target state remains byte-shape compatible `zone-belief-v4`: no field,
enum value, or schema-fingerprint input is added. Existing v4 payloads restore
unchanged, and a newly serialized reselected context remains decodable by the
prior v4 implementation. Round-trip and prior-version decode tests must include
a reselected asserted context. No authoritative map, count configuration, or
user data is modified.

Already-persisted false interaction likelihood cannot be retroactively
distinguished from a genuine physical press using only v4 filter state. The
repair therefore does not subtract or reset historical belief during restore.
Such belief follows existing bounded decay and release. Bootstrap reconciliation
must still restore a current trustworthy asserted context without adding
likelihood or a public edge. An inactive asserted zone remains subject to
existing acquisition authority and is not synthetically reacquired during
upgrade. Rollout verification must distinguish prevention of new stale replay
from bounded decay of pre-repair state.

The exact engine entry point is
`reconcile_restored_asserted_contexts(events: Sequence[SensorInput], at: datetime) -> ZoneModelSnapshot`.
It requires one shared startup frontier, derives current-on ordinary physical
node IDs from configured aliases, and calls the restricted selector once per
zone after restore advancement. It does nothing when authoritative count is
zero and emits no policy event. `OccupancyTracker.bootstrap_state` invokes it
only in the compatible restored-engine branch; cold bootstrap continues through
`bootstrap_sensor_snapshot`.

### 6.5 Diagnostics

Policy audit for ignored stale interactions records no confirming local evidence
or public edge. Existing stale disposition and event-loop processing latency
remain sufficient. A malformed or callback-future interaction value is rejected
before the target model, creates no model audit row, and does not increment
accepted-event counters. No new public diagnostic entity is required.

Episode diagnostics continue to show the unavailable interaction node
separately from the asserted same-zone stay node. Zone belief diagnostics expose
the selected asserted context and identity; no observation contribution is
fabricated for the correction.

## 7. Failure Behavior And Boundaries

- A valid interaction timestamp may equal its callback event time. At an
   already-observed model frontier, existing physical-node identity and
   idempotency rules decide duplicate versus a valid distinct-node event.
- An interaction timestamp newer than its callback event time is invalid and is
   rejected before model mutation.
- A malformed interaction state is ignored; `unknown` and `unavailable` are
  still processed as health states.
- If the only asserted same-zone node is the node becoming unavailable, no
  fallback exists and the zone becomes unavailable.
- If a same-zone candidate is count-conflict degraded, the zone becomes
  unavailable rather than silently restoring its floor.
- If multiple asserted nodes exist, deterministic selection changes no
  likelihood and later stable clear is accepted only for the selected
  generation.
- Out-of-order stale recovery cannot advance filter time, policy dwell, pending
  deadlines, prediction, or learning.
- Restart during any state uses the persisted frontier and the same snapshot
  reconciliation rules.
- Compatible restore never turns current raw state into a new episode. A
   restored assertion absent from the current-on snapshot is not eligible for
   context reselection.

## 8. Alternatives Rejected

1. **Compare callback and state timestamps with a tolerance.** Rejected because
   it adds an uncalibrated timing constant and can still classify delayed stale
   recovery as physical interaction.
2. **Suppress all interaction callbacks after startup for a fixed window.**
   Rejected because it can drop genuine presses and is deployment-time logic.
3. **Treat interaction recovery as `off`.** Rejected because event entities have
   no persistent asserted state and clear would fabricate absence.
4. **Ignore every unavailable interaction event.** Rejected because node-local
   traversal, support, and health invalidation must still occur.
5. **Reapply the selected mmWave positive.** Rejected because it would double
   count one physical episode and could fabricate refresh or traversal.
6. **Repair affected rooms in automation or clear persisted state manually.**
   Rejected because the defect is generic model input normalization and context
   aggregation.

## 9. Implementation Phases

### Phase 1: Retained incident

- Preserve exact production values, callback order, count, topology, beliefs,
  and public expectations.
- Prove the new runtime regression fails against unchanged behavior.

**Exit:** failure is on a reported public `active` outcome.

### Phase 2: Authority and event frontier

- Amend `SPECIFICATION.md` for EventEntity occurrence time and same-zone
  availability aggregation.
- Implement aware timestamp parsing and stale ordering.
- Replace the obsolete test that accepts an old timestamp at a new callback as
  a fresh press.

**Exit:** stale recovery creates no interaction episode or public edge; a fresh
interaction still acquires.

### Phase 3: Availability reconciliation

- Add zero-delta asserted-context reselection.
- Route bootstrap and live neutral availability through one engine helper.
- Preserve node-local invalidation and ordinary no-fallback unavailable behavior.

**Exit:** exact Alex retention passes without synthetic evidence; single-node
unavailable behavior remains unchanged.

### Phase 4: Persistence, inverses, and performance

- Add v4 context round-trip, prior-version decode, and restart coverage without
   changing the persisted enum or schema fingerprint.
- Cover stable clear, count conflict, cadence warning, multiple asserted nodes,
  malformed timestamp, future timestamp, duplicate timestamp, count zero, and
  cold bootstrap.
- Run the retained 100-event benchmark; no new path or calibration gate is
  required unless the existing callback ceiling regresses.

**Exit:** focused inverses, persistence, lint, type check, and benchmark pass.

### Phase 5: Repository validation and review

- Run full coverage, Ruff, mypy, frontend tests/build, benchmark, diff checks,
  and retained incident corpus.
- Obtain independent conformance review because this repair amends public model
  authority.

**Exit:** all repository gates pass and review finds no unresolved authority,
correctness, rollback, or acceptance gap.

## 10. Validation Commands

```bash
pytest --no-cov -q \
   tests/incidents/test_inc_2026_08_23_1909z_stale_interaction_recovery_does_not_change_occupancy.py::test_inc_2026_08_23_1909z_stale_interaction_recovery_does_not_change_occupancy
pytest --no-cov -q tests/test_events.py tests/test_runtime.py \
  tests/test_zone_model_engine.py tests/test_zone_model_filter.py \
  tests/test_zone_model_persistence.py
ruff check custom_components/predictive_controls/events.py \
  custom_components/predictive_controls/zone_model/engine.py \
  custom_components/predictive_controls/zone_model/filter.py \
  tests/test_events.py tests/test_runtime.py
mypy custom_components/predictive_controls
pytest -q
npm run test:frontend
npm run build:frontend
python benchmarks/occupancy_performance.py
node scripts/build_frontend.mjs --check
git diff --check
```

## 11. Acceptance Criteria

1. The exact retained regression fails on unchanged code and passes after the
   generic repair without changing factual inputs or public expectations.
2. All stale retained scene timestamps in the incident produce no interaction
   episode, belief contribution, authorization, support, policy acquisition, or
   refresh.
3. Shaila Office and Upstairs Bathroom remain inactive throughout the incident
   replay.
4. Alex Office remains active beyond the production false-release frontier while
   its original mmWave episode remains asserted.
5. The unknown Alex interaction alias is unavailable in episode diagnostics and
   owns no traversal or support authority.
6. A genuine fresh physical interaction still acquires immediately from public
   off and reaches the finite log-odds ceiling.
7. A single-node interaction zone still enters unavailable context and follows
   ordinary belief-plus-dwell release.
8. Stable clear of the reselected stay episode applies one weak absence update
   and later permits ordinary release when no other trustworthy asserted
   same-zone episode remains.
9. Count zero, count conflict, cadence correlation, restart, rollback, malformed,
   duplicate, future, and out-of-order boundaries retain their governing
   contracts.
10. No room-specific branch, synthetic positive, timer observation, threshold,
    profile constant, public entity, or automation complexity is added.
11. Bounded persistence, audit, and callback latency gates pass.
12. Independent review confirms conformance with the amended sole authority.
13. The exact regression proves Alex belief context, generation identity, and
   asserted identity all equal the original mmWave episode after the unknown
   interaction callback; no positive or interaction contribution is added by
   that correction.
14. The exact regression proves no stale Shaila or bathroom callback creates an
   interaction generation, authorization, acquisition, or refresh.
15. Candidate tie-breaking and restored episode order variations select the
   same episode and serialize the same v4 state.

## 12. Implementation Surfaces

- `SPECIFICATION.md`
- `custom_components/predictive_controls/events.py`
- `custom_components/predictive_controls/runtime.py`
- `custom_components/predictive_controls/zone_model/engine.py`
- `custom_components/predictive_controls/zone_model/filter.py`
- `tests/test_events.py`
- `tests/test_runtime.py`
- `tests/test_zone_model_engine.py`
- `tests/test_zone_model_filter.py`
- `tests/test_zone_model_persistence.py`
- `tests/fixtures/zone_model/INC-2026-08-23-stale-interaction-recovery.md`

## 13. Tracking

| Phase                           | Status   | Completed evidence                                                                                                                                                    | Next executable step                                                  |
| ------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| 1. Retained incident            | Complete | Exact live evidence retained; unchanged code fails the new runtime regression on Shaila Office public `active`.                                                       | Preserve factual inputs and public expectations unchanged.            |
| 2. Authority and event frontier | Complete | Sole authority amended; aware UTC, offset, malformed, naive, future, startup, and exact incident boundaries pass.                                                     | Keep EventEntity occurrence time distinct from callback receipt time. |
| 3. Availability reconciliation  | Complete | Live, cold-bootstrap, no-fallback, stable-clear, and deterministic multi-node tests pass without synthetic authority.                                                 | Preserve node-local invalidation and zero-likelihood selection.       |
| 4. Persistence and inverses     | Complete | Compatible restore, inactive-policy, current-on match, count-zero, current/pre-feature v4, and guard tests pass.                                                      | Keep the `zone-belief-v4` payload shape unchanged.                    |
| 5. Validation and review        | Complete | 656 Python tests pass at 100% branch coverage; Ruff, mypy, 30 frontend tests/build, generated panel, benchmark, diff checks, and independent conformance review pass. | Retain the incident and inverse regressions.                          |
