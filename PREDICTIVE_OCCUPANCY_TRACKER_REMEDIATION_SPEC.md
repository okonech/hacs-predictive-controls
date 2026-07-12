# Predictive Occupancy Tracker Performance and Correctness Remediation

**Created:** 2026-07-12
**Status:** Implementation candidate complete; seven-day external rollout validation pending
**Depends on:** `PREDICTIVE_OCCUPANCY_TRACKER_SPEC.md`
**Scope:** Inference performance, graph semantics, policy correctness,
persistence, runtime integration, diagnostics, and validation

## Executive Decision

The public three-entity contract in the behavioral specification remains
unchanged. The current Cartesian joint filter does not.

Replace the current posterior over timestamped occupant positions with:

1. an exact, fixed-size posterior over anonymous per-zone occupant counts;
2. bounded directional context stored outside the canonical occupancy key;
3. sparse transitions into the zone observed by the current event;
4. path-specific movement evidence consumed by policy and learning; and
5. one atomic bootstrap update instead of replaying every current Home
   Assistant state as a movement event.

For the current 16-zone map plus `unlocated`, an exact two-occupant posterior
contains only:

$$
\binom{16 + 2}{2} = 153
$$

canonical count configurations. This fixed state space is the production
boundary. Directional context may become uncertain or be compacted, but
occupancy probability must not be dropped for the supported one- and
two-occupant configurations.

Performance is a correctness requirement. A model that blocks Home Assistant's
event loop or silently drops material posterior mass is not an acceptable
approximation, even if its public outputs look correct in short unit tests.
Accuracy and deterministic consistency take precedence within the accepted
latency envelope. An optimization MUST NOT approximate the occupancy posterior,
drop path evidence, weaken conservative policy gates, or change replay results
to meet a preferred percentile. Updates below 30 ms are the operating target;
100 ms is the hard per-update ceiling.

## Motivation and Measured Baseline

The audit found the following behavior on 2026-07-12:

| Case                                    | Result                                         |
| --------------------------------------- | ---------------------------------------------- |
| Repository map                          | 16 zones, 17 nodes, 23 mapped entities         |
| Two-occupant all-`off` bootstrap        | 14.177 seconds in the synchronous tracker path |
| Slowest bootstrap entity update         | 1.017 seconds                                  |
| Final retained hypotheses               | 4096, the hard cap                             |
| Largest single-update dropped mass      | 0.0017008                                      |
| Existing normal-event dropped-mass gate | 0.0001                                         |
| Whole Python package branch coverage    | 90%                                            |
| `runtime.py` branch coverage            | 52%                                            |

The current state key includes `entered_at`, so physically equivalent occupancy
configurations reached through different event times do not merge. Every event
then takes a Cartesian product of per-position stay, movement, unlocated, and
missed-movement options before applying the hard limit. The limit controls
retained output size, not work performed or mass lost.

The remediation must make runtime cost depend on the fixed occupancy state
space and local graph degree, not on event history length or timestamp variety.

## Goals

- Keep all public entity names and meanings from the behavioral specification.
- Complete ordinary sensor updates fast enough for Home Assistant's event loop.
- Make two-occupant inference exact at the occupancy-configuration level.
- Drop zero occupancy probability mass for supported counts.
- Preserve only bounded, evidence-backed directional context.
- Prevent one event from advancing or releasing multiple unrelated paths.
- Make restart behavior equivalent to uninterrupted processing where persisted
  evidence is compatible.
- Make map changes safe when an entity is removed, renamed, or rebound.
- Learn a concrete node edge only when the evidence identifies that edge.
- Prove behavior through the complete scenario matrix and real runtime adapters.
- Remove the legacy inference implementation after the replacement passes its
  shadow and performance gates.

## Non-Goals

- Supporting more than two occupants in this release.
- Persistent person identity.
- Background diffusion without an observation.
- Learning person-specific movement patterns.
- Tuning policy thresholds through the UI before replay evidence exists.
- Preserving incompatible numerical posterior weights across a map change.

## Hard Performance Requirements

The performance fixture is the repository's 16-zone predictive map with two
occupants. Timing is measured on one ordinary x86-64 core under supported
CPython versions, with coverage and debug logging disabled. Deterministic work
bounds are mandatory on every platform; wall-clock budgets are release gates on
the reference runner.

| ID       | Requirement                                                                                                                                                                                                                         |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PERF-001 | A core observation update MUST have maximum <= 100 ms over a 10,000-event deterministic replay. It SHOULD keep p50, p95, and p99 <= 30 ms; misses are reported but do not override correct deterministic behavior.                  |
| PERF-002 | The complete runtime callback, excluding Home Assistant's downstream entity writes, MUST have maximum <= 100 ms. It SHOULD keep p95 and p99 <= 30 ms. A callback above 100 ms completes its state update but suppresses activation. |
| PERF-003 | A 23-entity cold or restored bootstrap MUST complete its inference work in <= 100 ms, with complete integration setup adding no more than 250 ms. The hard bootstrap ceiling is 500 ms.                                             |
| PERF-004 | The supported posterior MUST contain exactly the precomputed occupancy configurations: at most 17 for one occupant and 153 for two occupants on the reference map.                                                                  |
| PERF-005 | Directional variants MUST be bounded to four variants per occupancy configuration and 612 variants globally on the reference map.                                                                                                   |
| PERF-006 | One event MUST expand no more than `configuration_count * (source_zone_count + 1)` occupancy candidates. No per-occupant Cartesian product is permitted.                                                                            |
| PERF-007 | Supported one- and two-occupant updates MUST drop zero occupancy probability mass. Directional context compaction MUST preserve its parent occupancy mass.                                                                          |
| PERF-008 | Event handling MUST perform no file, network, executor, or Store I/O before publishing the in-memory decision. Persistence remains delayed and asynchronous.                                                                        |
| PERF-009 | A configured or entity-provided occupant count above two MUST NOT enter the exact filter. It MUST produce an explicit unsupported-count diagnostic and a safe public state.                                                         |
| PERF-010 | Every performance run MUST publish event count, candidate expansions, configuration count, context count, p50/p95/p99/max latency, bootstrap latency, and peak memory.                                                              |

### Safe Behavior for Unsupported Counts

- Static configuration validation rejects values above two.
- If a dynamic count entity changes above two, retain existing `keep_on`
  latches, clear activation and prediction leases, stop occupancy transitions,
  and publish `count_status: unsupported`.
- Count zero remains authoritative and clears all three public contracts.
- Returning to one or two performs an atomic cold bootstrap from current states.
- A future release may raise the limit only after adding a new benchmark and
  explicit state-space budget.

## Replacement State Model

### Canonical Occupancy Configuration

Use a stable sorted zone index containing every configured zone plus
`unlocated`. A canonical occupancy configuration is a tuple of non-negative
counts in that index order.

```python
@dataclass(frozen=True, slots=True)
class OccupancyConfiguration:
    counts: tuple[int, ...]
```

Invariants:

- `len(counts) == zone_count + 1`;
- `sum(counts) == expected_occupants`;
- configuration identity contains no timestamps, event IDs, sensor IDs, path
  IDs, or person IDs;
- every valid configuration is generated once at filter construction;
- each configuration has a stable integer index used by dense probability
  arrays and serialization.

For `Z` configured zones and `N` occupants, the exact configuration count is:

$$
\binom{Z + N}{N}
$$

### Occupancy Posterior

Store one log probability per precomputed configuration in deterministic index
order. Precompute source and successor indexes for every `(configuration,
source_zone, target_zone)` move that transfers exactly one occupant.

```python
@dataclass(frozen=True, slots=True)
class OccupancyPosterior:
    log_probabilities: tuple[float, ...]
    updated_at: datetime
```

The posterior remains normalized within `1e-12`. Since the supported state
space is fixed and small, there is no occupancy pruning path and no hard-limit
branch for counts one or two.

### Directional Context Sidecar

Direction and event time are evidence metadata, not occupancy identity. Keep a
bounded context distribution attached to an occupancy configuration:

```python
@dataclass(frozen=True, slots=True)
class DirectionalContext:
    origin_zone: str
    previous_node_id: str | None
    current_node_id: str
    started_at: datetime
    last_event_at: datetime
    evidence_ids: tuple[str, ...]
    log_probability: float
```

Rules:

- Keep at most four directional variants per occupancy configuration.
- Sort by probability and then a total deterministic key.
- Merge excess context probability into one contextless variant for the same
  occupancy configuration.
- Context compaction may remove prediction precision but MUST NOT alter zone
  marginals or count marginals.
- A contextless variant cannot authorize path release, prediction, or learning.
- Timestamps remain in context values and never participate in occupancy-key
  equality.

This is a Rao-Blackwellized design: occupancy remains exact while short-lived
directional detail is bounded and allowed to become unknown.

## Sparse Event Update

Only evidence in the currently observed zone can justify moving probability
into that zone. Do not diffuse every occupant to every neighbor on every event.

### Event Classes

| Event                       | Occupancy transition                                           |
| --------------------------- | -------------------------------------------------------------- |
| Duplicate same-entity state | None; return unchanged posterior with duplicate provenance     |
| Unsupported/unknown state   | None; return unchanged posterior with ignored provenance       |
| Sensor `off`                | Observation replacement only; no movement successor generation |
| Sensor `on`                 | Stay plus one-occupant movement into the observed zone         |
| Bootstrap snapshot          | Batch observation reconciliation; no movement successors       |
| Prediction evaluation       | None                                                           |
| Count change                | Deterministic configuration projection                         |

### Positive Observation Algorithm

For an `on` event in target zone `T`:

1. Add a stay contribution for every prior configuration.
2. For every graph-valid source zone containing at least one occupant, add the
   precomputed successor that moves exactly one occupant from the source to
   `T`.
3. Add `unlocated -> T` with its configured prior.
4. Add low-prior `source -> T` missed-movement contributions for non-adjacent
   sources containing an occupant.
5. Score all contributions with transition timing and the current entity's
   replacement observation likelihood.
6. Merge contributions directly into the fixed successor array with
   log-sum-exp.
7. Normalize once and derive marginals and path-specific movement evidence.

The implementation shape is:

```python
next_weights = impossible_vector(configuration_count)
for prior_index, prior_weight in enumerate(posterior.log_probabilities):
    add_stay(next_weights, prior_index, prior_weight, event)
    for source in candidate_sources[prior_index][event.zone]:
        successor_index = move_index[prior_index, source, event.zone]
        add_move(next_weights, successor_index, prior_weight, source, event)
apply_entity_likelihood_delta(next_weights, event)
posterior = normalize(next_weights)
```

This algorithm is `O(C * Z)` in the worst case and normally `O(C * degree(T))`,
where `C` is at most 153 for the supported map and count.

### No Ambient Diffusion

Elapsed time can weaken diagnostics and path context, but it does not move an
occupant without an observation. A later non-adjacent observation remains
recoverable through the explicit missed-movement contribution. This removes
unbounded state growth and avoids inventing motion from unrelated events.

## Graph and Timing Semantics

The map schema has one unambiguous interpretation:

- `adjacent` describes undirected physical adjacency.
- Every physical adjacency declaration MUST be reciprocal. Validation rejects
  one-way declarations and names both nodes in the error.
- The map editor writes and removes both directions atomically.
- Directed prediction and learning are represented by path context and directed
  Markov counts, not by asymmetric physical adjacency.
- `transition_seconds[source][target]`, when present, is a directed timing
  override and is valid only for physically adjacent nodes.
- Missing directed timing uses one documented default. It MUST NOT silently
  borrow the reverse direction's override.

Transition scoring uses elapsed event time only when a compatible directional
context exists. An edge outside its allowed timing envelope remains possible at
a low missed-timing prior and records that reason. It cannot contribute to the
normal graph-release threshold.

Required validation errors include:

- undefined adjacency target;
- non-reciprocal physical edge;
- timing override for a non-adjacent node;
- negative or non-finite timing;
- duplicate entity binding;
- one entity bound to incompatible nodes or signal types.

## Path-Specific Movement Evidence

The filter emits movement contributions before merging occupancy successors:

```python
@dataclass(frozen=True, slots=True)
class MovementEvidence:
    path_key: tuple[str, str | None, str]
    origin_zone: str
    source_zone: str
    target_zone: str
    coherent_probability: float
    source_node_id: str | None
    target_node_id: str
    evidence_ids: tuple[str, ...]
    disposition: str
```

Requirements:

- Movement probability is conditioned and updated inside the filter, where
  predecessor context is still available.
- Policy MUST NOT combine sequential edge marginals with a probabilistic OR.
- One event may move at most one anonymous occupant per predecessor context.
- One movement contribution may extend only the path context from which it was
  derived. It cannot advance every pending origin sharing a corridor.
- A graph departure release uses coherent path probability from one origin,
  not a zone-level aggregate that has lost its predecessor.
- Ambiguous movement remains multiple bounded contexts or becomes contextless.
  It never fabricates a precise path.

## Automation Policy Remediation

### Explicit Release and Recovery State

Extend policy state with structured release metadata:

```python
class ReleaseCause(StrEnum):
    GRAPH_DEPARTURE = "graph_departure"
    CONFIRMED_RELOCATION = "confirmed_relocation"
    COUNT_REDUCTION = "count_reduction"
    AUTHORITATIVE_AWAY = "authoritative_away"
    EXPLICIT_RESET = "explicit_reset"
    PROVISIONAL_FALSE_OFF = "provisional_false_off"

@dataclass(frozen=True, slots=True)
class ZonePolicyState:
    keep_on: bool
    activation_expires_at: datetime | None
    last_trusted_at: datetime | None
    last_release_cause: ReleaseCause | None
    recovery_eligible: bool
    reason_code: str
    evidence_ids: tuple[str, ...]
```

Only `PROVISIONAL_FALSE_OFF` is recovery eligible. A zone released by confirmed
movement, relocation, count reduction, away state, or reset must reacquire
occupancy through the normal path, unlocated-mass, independent-corroboration,
or strong-relocation gates. `last_trusted_at` alone never authorizes recovery.

### Corroboration

Remove the lifetime `_positive_entities` set. Independent corroboration is
derived from current observation evidence:

- distinct entity binding signatures;
- positive latest state;
- compatible evidence episodes;
- signal-specific freshness or an actively asserted sustained-presence state;
- no duplicate contribution from one physical entity with multiple aliases.

Corroboration evidence clears or is revalidated on map change, occupant-count
change, and policy release. Diagnostics list the exact accepted entity IDs and
the evidence that is missing when promotion is rejected.

### Release

Graph release still requires both low origin occupancy and at least the
configured coherent path probability. The path evidence carries its own
origin, so same-room partial departures and shared corridors cannot release the
wrong latch. Count reduction and reset remain direct authoritative releases.

Every policy evaluation returns a structured decision, including rejected
decisions:

```python
@dataclass(frozen=True, slots=True)
class PolicyDecision:
    zone: str
    action: str
    accepted: bool
    reason_code: str
    gate_values: Mapping[str, float | bool | str]
    evidence_ids: tuple[str, ...]
```

## Prediction and Learning Remediation

- Prediction leases are created only from compatible directional contexts.
- A single forward candidate excluding the incoming node creates its lease in
  the same update cycle.
- Contextless probability contributes no prediction.
- Leases remain keyed independently per path and target.
- Reversal cancels only the matching path lease.
- Learning requires a known source node, known target node, valid directed
  edge, and coherent path probability at or above the learning threshold.
- If more than one source node is compatible, do not choose the first sorted
  node. Record `ambiguous_source_node` and learn nothing.
- Transition counts are updated after the in-memory public decision and saved
  asynchronously.

## Persistence and Map Changes

### Schema 3 Payload

Persist atomically:

- schema version and exact map fingerprint;
- zone index and expected occupant count;
- fixed occupancy posterior probabilities;
- bounded directional contexts;
- policy states including release cause and recovery eligibility;
- active coherent departure/path leases;
- prediction leases;
- observation evidence with binding signatures;
- valid directed transition counts;
- last update sequence and timestamp.

An entity binding signature contains entity ID, node ID, zone, signal type,
role, occupancy behavior, reliability profile version, and relevant graph
version.

### Exact-Fingerprint Restore

Restore all validated state, expire leases by wall time, then perform one batch
bootstrap reconciliation. A matching entity with the same current state adds
zero likelihood. A changed state replaces the stored likelihood once. Removed
or newly added entities are handled in the batch before one normalization.

### Changed-Fingerprint Restore

Do not reuse numerical posterior or entity likelihood state after an
inference-relevant map change. Selective subtraction is unsafe because those
factors have already influenced the posterior.

Instead:

1. restore `keep_on` latches only for unchanged zone IDs;
2. restore valid transition counts only for unchanged directed node edges;
3. discard occupancy weights, observation factors, directional contexts,
   pending departures, and prediction leases;
4. create a cold fixed-state prior;
5. apply the current Home Assistant snapshot as one bootstrap batch;
6. suppress activation and prediction pulses;
7. publish `restore_status: map_changed_rebuilt` with changed binding and edge
   details.

This may lose path precision, but it cannot classify a rebound entity as a
duplicate in its old zone and cannot produce a false keep-on clear.

### Schema 2 Migration

Schema 2 posterior values are not compatible with the replacement state model.
Migrate policy latches for valid zones and valid Markov counts only. Rebuild all
other inference state through the atomic bootstrap path. Publish
`restore_status: migrated_policy_only`.

## Atomic Bootstrap

Runtime startup MUST NOT call the ordinary movement update once per entity.

Bootstrap procedure:

1. Load and validate persisted state.
2. Read all mapped current states into an immutable snapshot.
3. Resolve the authoritative occupant count once.
4. Select restored posterior or a precomputed cold-start prior.
5. Compute every entity likelihood delta against that same prior snapshot.
6. Sum deltas per fixed occupancy configuration.
7. Normalize once.
8. Reconcile policy without activation or prediction pulses.
9. Publish one dispatcher update after platforms are ready.
10. Schedule one delayed save if reconciliation changed persisted state.

The cold-start prior covers every valid occupancy configuration, with a
documented higher prior for `unlocated`. This allows current positive sensors to
reconstruct likely occupancy without simulating a sequence of movements. Batch
results are independent of entity iteration order.

## Runtime Integration

- Build the bootstrap snapshot in `async_setup_entry` before the runtime becomes
  authoritative.
- Keep the pure filter and policy update synchronous because they meet the hard
  latency budget.
- Emit one dispatcher notification after each complete atomic update.
- Never expose intermediate posterior, policy, or prediction state.
- Coalesce delayed Store saves; `async_stop` performs one awaited final save.
- Track event-loop latency separately from inference latency.
- If the hard update ceiling is exceeded, finish the current update, suppress
  activation for that update, record `performance_budget_exceeded`, and compact
  directional context before the next event. Never silently skip a clear or
  authoritative count command.

## Diagnostics and Replay

Diagnostics MUST include:

- top occupancy configurations and probabilities;
- zone occupied and count marginals;
- posterior entropy;
- occupancy configuration and directional-context counts;
- candidate expansions and context compactions for the last update;
- last, rolling p50/p95/p99, and maximum inference latency;
- bootstrap inference and total setup latency;
- observation likelihood and binding signature;
- accepted and rejected movement alternatives;
- every policy decision and failed gate;
- coherent path and prediction leases;
- restore and map-reconciliation details;
- transition-learning acceptance or rejection reason;
- unsupported-count and performance-degraded status.

Replay output includes all three public booleans for every zone after every
event, policy reasons/evidence, posterior invariants, performance counters, and
learning changes. It must serialize deterministically for byte comparison.

## Validation Strategy

### Coverage Contract

- Whole-package Python branch coverage is 100%. The coverage target is the
  package, not an allowlist of selected modules.
- Runtime, setup, entities, config flow, diagnostics, and WebSocket adapters are
  included.
- Every branch exclusion requires an inline rationale and review.
- At least 80% of branches in the replacement filter, policy, prediction,
  persistence, and runtime modules are exercised through timestamped acceptance
  scenarios. Focused unit tests cover numerical primitives, parser errors, and
  otherwise unreachable failure injection.
- Frontend tests remain independently required.

### Scenario Contract

Implement S-01 through S-28 from the behavioral specification as named,
timestamped fixtures. Each fixture records:

- map and authoritative count;
- initial stored state, if any;
- input entity states and event timestamps;
- expected public timeline after every event;
- expected policy reasons and evidence IDs;
- posterior count and normalization invariants;
- expected prediction and learning changes;
- maximum candidate and latency budgets where relevant.

S-24 runs every fixture twice and under 100 seeded permutations of equal-time
events. Public timelines, posterior ordering, reasons, and serialized replay
output must be byte-identical wherever the fixture declares events unordered.

Add these audit regressions explicitly:

- `R-01 Actual-map two-occupant bootstrap performance`;
- `R-02 Release followed by unsupported local hit`;
- `R-03 Restart midway through a two-edge departure`;
- `R-04 Entity ID rebound from one valid zone to another`;
- `R-05 Two source nodes ambiguous for one learned edge`;
- `R-06 Two origins sharing one corridor edge`;
- `R-07 Non-reciprocal graph declaration rejection`;
- `R-08 Directed transition timing acceptance and rejection`;
- `R-09 Unsupported dynamic occupant count`;
- `R-10 Context compaction preserves occupancy mass`.

### Deterministic Complexity Tests

Wall-clock tests are supplemented by deterministic operation limits:

- exact expected configuration count;
- no occupancy pruning call for counts one or two;
- candidate expansion ceiling per event;
- context variants per configuration and globally;
- one normalization per event;
- one dispatcher notification per event;
- one batch normalization and dispatcher notification per bootstrap.

These tests catch algorithmic regressions without relying only on noisy timing.

## Documentation Contract

- The README uses `activation_plausible -> on` as the canonical turn-on trigger
  and `keep_on -> off` as the canonical turn-off trigger.
- Raw motion may be documented only as a diagnostic or an explicitly advanced
  alternative with ordering caveats; it is not the recommended contract.
- Publish the supported occupant limit and safe unsupported-count behavior.
- Publish map direction and timing semantics.
- Publish bootstrap and map-change behavior.
- Publish the reference performance results for each release.
- Mark the original behavioral specification as implemented only after every
  acceptance and rollout gate passes.

## Implementation Plan

### Phase 0: Freeze and Reproduce

| Task   | Deliverable                                                                                               | Gate                                                                   |
| ------ | --------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| R-T001 | Commit the audit regressions as failing tests and fixtures.                                               | Every reproduced defect fails for the documented reason.               |
| R-T002 | Add deterministic operation counters and the actual-map benchmark harness.                                | Baseline numbers are stored as artifacts, not asserted as acceptable.  |
| R-T003 | Change coverage configuration to measure the whole package.                                               | The current truthful baseline is visible without a 100% threshold yet. |
| R-T004 | Add a release flag that prevents the current Cartesian joint filter from controlling production entities. | Existing stable behavior remains available during replacement.         |

### Phase 1: Fixed Occupancy Core

| Task   | Deliverable                                                                                           | Gate                                                     |
| ------ | ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| R-T101 | Implement zone indexing, configuration generation, dense log posterior, and precomputed move indexes. | Exact 17/153 counts and numerical primitive tests pass.  |
| R-T102 | Implement sparse positive updates and observation-only clear updates.                                 | No Cartesian product and zero occupancy mass loss.       |
| R-T103 | Add bounded directional context with mass-preserving compaction.                                      | R-10 and crossing/join/split scenarios pass.             |
| R-T104 | Implement reciprocal graph validation and directed timing lookup.                                     | R-07 and R-08 pass.                                      |
| R-T105 | Benchmark pure core against PERF-001 and PERF-004 through PERF-007.                                   | All core performance gates pass before integration work. |

### Phase 2: Path, Policy, and Learning

| Task   | Deliverable                                                              | Gate                                                        |
| ------ | ------------------------------------------------------------------------ | ----------------------------------------------------------- |
| R-T201 | Emit coherent path-specific movement evidence from predecessor contexts. | Shared corridors cannot advance two origins from one event. |
| R-T202 | Replace generic recovery with release-cause-aware policy.                | R-02 and all retention/recovery scenarios pass.             |
| R-T203 | Replace lifetime positive sets with current evidence corroboration.      | Repeated and stale-source false-positive scenarios pass.    |
| R-T204 | Drive predictions and learning only from compatible path contexts.       | R-05 and S-12 through S-15, S-27 pass.                      |

### Phase 3: Persistence and Runtime

| Task   | Deliverable                                                  | Gate                                                      |
| ------ | ------------------------------------------------------------ | --------------------------------------------------------- |
| R-T301 | Implement schema 3 and policy-only schema 2 migration.       | Exact restore, corrupt restore, and migration tests pass. |
| R-T302 | Persist coherent path state and structured policy state.     | R-03 matches uninterrupted public behavior.               |
| R-T303 | Implement changed-map cold rebuild and binding signatures.   | R-04 and S-21 pass.                                       |
| R-T304 | Implement atomic batch bootstrap and one-update publication. | PERF-003 and restart scenarios pass.                      |
| R-T305 | Add runtime latency and operation diagnostics.               | Runtime benchmark meets PERF-002 and PERF-010.            |

### Phase 4: Acceptance Cutover

| Task   | Deliverable                                                                   | Gate                                                                                      |
| ------ | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| R-T401 | Complete all S-01 through S-28 fixtures and public timelines.                 | All scenarios pass with deterministic output.                                             |
| R-T402 | Complete whole-package and scenario-dominant coverage.                        | 100% package branch and 80% core-through-scenario gates pass.                             |
| R-T403 | Run at least seven days of shadow comparison using the fast replacement core. | No false keep-on clears, no unsupported activations, no latency breach, and no mass loss. |
| R-T404 | Switch public entities to the replacement implementation.                     | One compatibility release completes without contract regressions.                         |

### Phase 5: Remove Legacy Ownership

| Task   | Deliverable                                                                                                          | Gate                                                          |
| ------ | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| R-T501 | Delete ranked tracks, join slots, conflict decay, old activation plausibilities, and confidence-owned release paths. | All acceptance, performance, and frontend tests remain green. |
| R-T502 | Remove compatibility diagnostics only after consumers migrate.                                                       | Payload migration is documented and tested.                   |
| R-T503 | Align README, package version, manifest version, and release notes.                                                  | Documentation and metadata checks pass.                       |

## Rollout Gates

The replacement cannot control public entities until all of the following are
true:

1. The actual-map cold and restored bootstrap benchmarks pass.
2. All one- and two-occupant updates drop zero occupancy mass.
3. S-01 through S-28 and R-01 through R-10 pass.
4. S-24 is deterministic across all required permutations.
5. Whole-package branch coverage is 100% and the scenario-dominant threshold is
   met.
6. No runtime callback exceeds the hard latency ceiling in the reference run.
7. Shadow diagnostics report no unexplained public-policy difference.
8. Persistence migration and map-rebinding tests pass.
9. The README contains only the canonical simple automation contract.
10. The legacy implementation has a dated removal task and owner.

Any breach blocks cutover. Raising a state, latency, or mass-loss limit requires
a benchmark artifact, replay evidence, and an explicit specification change.

## Alternatives Rejected

### Optimize the Current Cartesian Enumerator

Rejected because pruning after enumeration does not bound work, and timestamps
inside canonical keys prevent physically equivalent states from merging. Small
constant-factor improvements do not solve history-dependent growth.

### Lower the Existing Hard Limit

Rejected because it improves retained object count by discarding more
probability while leaving most predecessor expansion work intact.

### Particle Filtering

Rejected for the one- and two-occupant target because the exact count state
space is only 17 or 153 configurations. Sampling would add nondeterminism and
replay variance without a necessary scaling benefit.

### Independent Named or Ranked Tracks

Rejected because assignment swaps recreate false identity and interleaved-user
learning failures. Anonymous count configurations retain exact occupancy while
bounded context carries only evidence-supported direction.

### Move Inference to an Executor

Rejected as the primary fix. It would stop direct event-loop blocking but add
queueing, stale intermediate decisions, ordering complexity, and cancellation
races. The bounded core is small enough to run synchronously within budget.

## Success Criteria

- **RSC-001:** The repository-map two-occupant bootstrap completes within the
  PERF-003 budget and publishes one atomic update.
- **RSC-002:** Every supported event retains exactly 17 or 153 configured
  occupancy probabilities and drops zero occupancy mass.
- **RSC-003:** No supported runtime callback exceeds its hard latency budget.
- **RSC-004:** Confirmed releases cannot use the provisional recovery gate.
- **RSC-005:** Restart midway through a departure produces the same public
  release timeline as uninterrupted processing.
- **RSC-006:** Rebinding an entity cannot preserve or subtract evidence in its
  old zone.
- **RSC-007:** Ambiguous source nodes produce no learned concrete edge.
- **RSC-008:** One event cannot advance more than one unrelated path context.
- **RSC-009:** All 38 behavioral and remediation scenarios pass with exact
  public timelines and deterministic reasons.
- **RSC-010:** Whole-package branch coverage is 100%, and at least 80% of core
  branches are exercised through acceptance scenarios.
- **RSC-011:** The legacy ownership implementation is absent from the production
  event path.
- **RSC-012:** Ordinary Home Assistant automations require only the three public
  entities defined by the behavioral specification.

## Readiness Decision

The current Cartesian implementation is not a candidate for incremental tuning
into production readiness. Implementation begins at Phase 0 and replaces the
state representation before changing policy thresholds. Public cutover remains
blocked until the bounded core, batch bootstrap, restart equivalence, complete
scenario matrix, and hard runtime budgets all pass.