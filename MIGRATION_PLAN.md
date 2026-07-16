# Predictive Controls Specification Migration Plan

**Status:** Target implementation complete; release validation pending
**Target:** The normative model under `docs/spec/`
**Current release line:** `0.2.0`, storage schema 6
**Migration posture:** Exactness and public safety before compatibility or speed

## Implementation Progress

This ledger tracks implementation against the phases below. A phase is marked
complete only when its production deliverables are present; repository-wide
validation remains a separate final gate.

- [x] **Phase 0 - Freeze public behavior and incident inputs.** Retained public
   scenario families and exact-timestamp incident inputs are established.
- [x] **Phase 1 - Investigate exact N=5 feasibility.** Compact count-vector
   state, complete operators, and exact oracle parity were demonstrated. N=5
   product support was later abandoned; the supported maximum is N=2.
- [x] **Phase 2 - Add replacement engine port and differential harness.** The
   neutral engine protocol, legacy adapter, target engine, oracle, and
   differential runner exist.
- [x] **Phase 3 - Implement physical-node observation episodes.** Event-indexed
   node episodes, duration emissions, stable clear, aliases, and neutral
   unavailable handling are implemented.
- [x] **Phase 4 - Implement fixed-lag anonymous movement association.** Exact
   unresolved factors, endpoint injectivity, interval constraints, replay,
   watermark finalization, and overload diagnostics are implemented.
- [x] **Phase 5 - Implement authoritative count kernels.** Exchangeable exact
   count transitions support every authoritative count from zero through two.
- [x] **Phase 6 - Replace policy gates with posterior events.** Exact
   ArrivalSupported and finalized ReleaseSafe drive the target policy latch;
   finalized support drives prediction and route learning.
- [x] **Phase 7 - Introduce target persistence and deterministic restore.** Store
   schema 6 persists the complete exact state and bounded target policy audit;
   exact restore is atomic, and schema 5 migrates conservatively through neutral
   target bootstrap without invented assignments or synthetic policy edges.
- [x] **Phase 8 - Cut over the tracker facade.** Exact inference now owns
   occupancy, policy, prediction, learned routes, and configured action
   evaluation. Target entities, optional arrival/probability surfaces, bounded
   audit, status, and compatibility projections all consume exact diagnostics.
- [x] **Phase 9 - Enable counts 3 through 5 end to end.** Config flow,
   WebSocket, panel, runtime controls, exact inference, status diagnostics, and
   the optional authoritative-count sensor consistently support only zero
   through five and retain the last valid count while an input is invalid.
- [x] **Phase 10 - Remove the legacy production core and release the target
   contract.** Authoritative runtime paths load only exact inference; schema-5
   parsing and the release-0.1.20 replay comparator remain isolated for their
   documented windows. Release documentation is updated, and an independent
   implementation-conformance review found no target-contract blocker. Broad
   quality, final benchmark, and external rollout evidence remain separate gates.

This document tells an implementation agent how to migrate the current
Predictive Controls engine to the normative specification. It is an execution
plan, not a second source of product requirements. If this document conflicts
with `docs/spec/`, the specification wins and this plan must be corrected before
implementation continues.

## Required Reading and Workflow

Before changing behavior, read:

1. `docs/spec/README.md`;
2. `docs/spec/goals-and-principles.md`;
3. `docs/spec/change-governance.md`;
4. the technical specification that owns the current task;
5. `.github/skills/predictive-controls-regression-review/SKILL.md`; and
6. `async-todo.md` for the retained incident facts.

Every incident-derived behavior change follows the nine gates in the regression
review skill. In particular, add and prove the exact-timestamp public regression
before diagnosing or editing the production behavior that caused it. Use fresh,
context-isolated reviewers where the skill requires them.

Do not change Home Assistant automations to compensate for an inference defect.
Release `0.1.20` exposed the legacy consumer contract:

1. `activation_plausible -> on` authorizes normal activation;
2. `keep_on -> off` authorizes normal release; and
3. `prelight_plausible -> on` optionally authorizes prediction-based prelighting.

Release `0.2.0` implements the target default contract defined by `ENT-001`
through `ENT-010`:

1. `active -> on` turns normal outputs on;
2. `active -> off` turns normal outputs off; and
3. optional `prelight -> on` authorizes low-impact predictive lighting.

`arrival` is an optional disabled-by-default event for advanced fresh-episode
consumers. The migration dual-projects the legacy entities for at least one full
released version; their eventual removal is a separately reviewed breaking
change.

## End State

The migration is complete only when production implements all of the following:

- exact anonymous count-vector occupancy for authoritative $0 \le N \le 5$;
- $N=2$ as the primary calibration, replay, and optimization profile;
- event-indexed physical-node observation emissions with separate burst,
  stable-clear, and hardware hold/refractory semantics;
- exact bounded fixed-lag anonymous movement/data association;
- interval-censored graph traversal with one external endpoint per crossing;
- event-time candidate deadlines and a maximum-lateness watermark;
- exchangeable authoritative count-transition kernels;
- `ArrivalSupported` and `ReleaseSafe` probabilities computed from augmented
  joint mass;
- deterministic policy latches with no policy-to-posterior feedback;
- atomic restart of posterior, unresolved factors, episodes, endpoint tokens,
  deadlines/watermark, support probabilities, count sequence, and latches;
- the `active`/`prelight` default entity contract, bounded optional diagnostics,
  and simple automation consumption;
- no probability pruning or silent approximate mode; and
- measured compliance with the approved $N=2$ workload gates.

## Current Implementation Baseline

The current engine is an exact/top-K-style filter for only zero through two
occupants. Important ownership boundaries are:

| Area                                  | Current owner                                                                             | Migration implication                                                                                       |
| ------------------------------------- | ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Runtime callback and Store scheduling | `runtime.py`                                                                              | Keep stable until the replacement core can run behind the tracker facade.                                   |
| Public inference facade               | `confidence.py`, `occupancy_tracker.py`                                                   | Introduce the replacement engine at this boundary; do not rewrite entities first.                           |
| Occupancy state objects               | `occupancy_state.py`                                                                      | Current tuple/object hypotheses are not the target $N=5$ representation.                                    |
| Observation replacement factors       | `observation_model.py`                                                                    | Replace with event-indexed physical-node episode emissions.                                                 |
| Posterior and directional contexts    | `joint_filter.py`                                                                         | Replace capped contexts and removable factors with compact occupancy arrays and an unresolved factor graph. |
| Transition construction               | `transition_model.py`, `joint_filter.py`                                                  | Replace per-position/cartesian expansion with complete precomputed one-occupant move operators.             |
| Activation and release                | `automation_policy.py`                                                                    | Replace legacy gate conjunctions and pending departures with posterior-event probabilities.                 |
| Prediction and route learning         | `prediction.py`, `route_model.py`, `markov.py`                                            | Preserve downstream-only behavior; consume only finalized graph-valid assignments.                          |
| Persistence                           | `occupancy_persistence.py`, `storage.py`, `const.py`                                      | Introduce a new atomic schema; schema 5 cannot represent the target graph.                                  |
| Public diagnostics                    | `status.py`, `diagnostics.py`, `websocket.py`, panel                                      | Add new diagnostics without breaking existing public entity IDs.                                            |
| Occupant count validation             | `config_flow.py`, `websocket.py`, `joint_filter.py`, `occupancy_tracker.py`, `runtime.py` | Enforce the approved product maximum of two occupants at every public boundary.                             |
| Performance                           | `benchmarks/occupancy_performance.py`                                                     | Gate N=2 across factor-graph, persistence, overload, and adversarial trace metrics.                         |

The primary integration seam is `OccupancyTracker`. Runtime observations already
flow through `observe`, count changes through `reconcile_expected_occupants`,
startup through `bootstrap_joint_state`, and persistence through
`occupancy_store_data` and `restore_joint_state`. Preserve those externally used
methods while replacing their internals.

## Non-Negotiable Migration Rules

1. **Do not mutate the legacy engine into the target model in one pass.** Build
   the replacement core alongside it, prove it, then cut over the tracker facade.
2. **Do not widen configuration to five early.** Counts 3 through 5 remain
   rejected publicly until exactness, persistence, and performance gates pass.
3. **Do not use legacy outputs as the new model's oracle.** Legacy behavior is a
   comparison signal only. The normative specification and brute-force exact
   oracle decide correctness.
4. **Do not preserve legacy gate conjunctions behind new names.**
   `ArrivalSupported` and `ReleaseSafe` must be probabilities of declared joint
   events, not wrappers around independently maximized thresholds.
5. **Do not subtract historical evidence from a later occupancy state.** A
   clear is a new false-negative-aware emission. Recompute only retained
   historical factors inside the fixed-lag graph.
6. **Do not attach probability-bearing provenance after occupancy mass merges.**
   Assignment and support variables belong in the augmented probabilistic state.
7. **Do not introduce person identity.** Assignment IDs identify episodes and
   endpoints, never household members or persistent anonymous tracks.
8. **Do not prune occupancy configurations.** Overload may delay processing and
   suppress release/learning, but it cannot discard occupancy probability.
9. **Do not let prediction feed occupancy, movement, activation, or release.**
10. **Do not migrate invalid schema-5 inference into invented target state.** If
    exact behavioral conversion cannot be proved, retain safe policy ownership,
    rebuild inference from a neutral snapshot without synthetic movement, and
    report the migration explicitly.

## Target Internal Architecture

Create a replacement package under
`custom_components/predictive_controls/inference/`. Keep modules narrow enough
that the exact oracle and optimized engine can share model definitions without
sharing implementation mistakes.

Recommended module ownership:

| Module                          | Responsibility                                                                                                  |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `inference/types.py`            | Immutable event, episode, assignment, deadline, support-certificate, and result types.                          |
| `inference/state_space.py`      | Canonical count-vector enumeration, rank/unrank, zone/count marginals, and compact numeric posterior storage.   |
| `inference/operators.py`        | Complete stay and one-occupant source-target transition indexes for every configuration and configured pair.    |
| `inference/count_transition.py` | Exact exchangeable $K^+$ and $K^-$ kernels.                                                                     |
| `inference/episodes.py`         | Physical-node episode state machine and event/duration emission likelihoods.                                    |
| `inference/association.py`      | Unresolved factor graph, endpoint consumption, interval feasibility, deadlines, watermark, and marginalization. |
| `inference/support.py`          | Exact `ArrivalSupported` and `ReleaseSafe` event construction and probability summation.                        |
| `inference/engine.py`           | Ordered orchestration and immutable update snapshots.                                                           |
| `inference/persistence.py`      | Target-schema payload types and strict atomic validation.                                                       |
| `tests/oracle/`                 | Deliberately simple brute-force reference implementation; never imported by production.                         |

Use standard-library numeric containers first (`array`, lists, tuples, compact
integer indexes). Do not add NumPy unless the prototype demonstrates a material
need and Home Assistant packaging/runtime cost is reviewed explicitly.

The production-facing engine result must provide, at minimum:

- exact occupancy and count marginals;
- complete normalization/pruning diagnostics;
- current physical-node episode state;
- unresolved and finalized assignment summaries;
- watermark, candidate deadlines, accepted/rejected event disposition;
- `ArrivalSupported` probability for the current target;
- finalized `ReleaseSafe` probability for every held zone;
- current-positive and competing-assignment veto state;
- finalized graph-valid assignments eligible for prediction/learning;
- operation, graph-size, overload, and latency counters; and
- immutable evidence IDs sufficient for policy audit.

Policy consumes this result but cannot mutate it.

## Migration Phases

Each phase is a stop/go gate. Commit-sized implementation batches should stay
inside one phase and retain passing checks from all completed phases.

### Phase 0: Freeze Public Behavior and Incident Inputs

**Goal:** Establish immutable safety anchors before replacement work.

Tasks:

1. Add the exact-timestamp upstairs-bathroom legacy public regression from
   `async-todo.md`. Prove it fails against unchanged production for the recorded
   reason, then freeze its events, timestamps, topology, gates, and expected
   `keep_on -> off` edge. Record the target expectation as the corresponding
   `active -> off` edge without changing the factual legacy reproduction.
2. Retain the Alex-office competing-source regression and verify its current
   expected public timeline.
3. Record baseline public timelines for every existing scenario family using
   `tests/occupancy_test_utils.py`.
4. Save baseline $N=2$ benchmark results and the current schema-5 restore corpus.
5. Categorize existing tests as:
   - invariant and expected to remain unchanged;
   - legacy implementation detail to replace; or
   - behavior that conflicts with the new normative specification.

Gate:

- Both incident regressions exist at the public contract.
- The bathroom test fails for the recorded causal-loss defect before a behavior
  fix; the office test remains protected.
- No incident input has been weakened to fit a proposed implementation.

### Phase 1: Prove Exact $N=5$ Feasibility Before Production Edits

**Goal:** Determine whether the exact support and 100 ms contract can coexist.

Tasks:

1. Implement count-vector enumeration and deterministic rank/unrank for
   $N=0\ldots5$ on arbitrary small maps and the 16-zone reference map.
2. Implement compact posterior arrays and precomputed complete one-occupant move
   operators. One target event has stay plus at most one move from each occupied
   source per predecessor; never enumerate a cartesian product of occupant moves.
3. Implement a brute-force exact oracle for small maps and randomized traces.
4. Prove optimized/oracle parity for posterior values, marginals, normalization,
   source multiplicity, endpoint uniqueness, missed movement, and count changes.
5. Prototype the unresolved assignment representation, deadline propagation, and
   exact marginalization. The prototype need not expose production entities.
6. Declare numeric `MOVE-020` parameters: $R_{max}$, $B_{max}$, active episode
   maximum, $D_{max}$, and $L_{late}$.
7. Run prototype traces at $N=2$ and $N=5$, including all 20,349 reference-map
   configurations at $N=5$.
8. Measure p50/p95/p99/max update latency, operations, peak memory, unresolved
   graph/joint-state size, bootstrap, serialization, restore, and overload.

Gate:

- Oracle parity passes within the normative `1e-12` normalization tolerance.
- No occupancy probability is pruned.
- $N=2$ and $N=5$ meet the 50 ms preferred and 100 ms hard callback contracts
  inside the declared workload envelope.
- Numeric memory, graph, persistence, and startup ceilings are reviewed and
  recorded.

If this gate fails after profiling and a compact operator implementation, stop.
Present evidence and amend either the supported count or latency contract. Do not
continue with pruning, top-K inference, or an undocumented approximate mode.

### Phase 2: Add a Replacement Engine Port and Differential Harness

**Goal:** Make the new core replaceable without destabilizing Home Assistant.

Tasks:

1. Define an internal engine protocol used by `OccupancyTracker` for bootstrap,
   observation, count reconciliation, finalization, diagnostics, serialize, and
   restore operations.
2. Adapt the current `JointOccupancyFilter` stack to that protocol without
   changing behavior.
3. Adapt the prototype core to the same protocol.
4. Add a test-only differential runner that feeds identical maps, snapshots,
   count controls, events, and timer callbacks to both engines.
5. Compare public timelines, occupancy/count marginals, accepted event
   disposition, normalization, and restart behavior. Classify differences by
   normative requirement; do not force parity where legacy behavior violates the
   new spec.
6. Keep `runtime.py`, entities, `automation_summary.py`, and prediction actions
   on the legacy engine during this phase.

Gate:

- Existing tests pass through the legacy protocol adapter.
- The replacement engine runs complete replay traces without affecting public
  state.
- Every differential mismatch has a requirement ID and expected disposition.

### Phase 3: Implement Physical-Node Observation Episodes

**Goal:** Replace removable current-state factors with coherent sequential
emissions.

Tasks:

1. Add shared profile values for `burst_correlation_window`,
   `stable_clear_window`, and `refractory_or_hold_interval`; do not alias one to
   another implicitly.
2. Group aliases by physical node and maintain one episode process per node.
3. Integrate accepted edge emissions exactly once. Duplicate state callbacks and
   unchanged timer evaluation have zero evidence effect.
4. Apply asserted-duration survival likelihood incrementally and with a finite
   ceiling.
5. Treat clear as a new calibrated weak absence emission. Never divide the old
   positive likelihood out of the current hidden state.
6. Finalize stable clear by event-time deadline. Timer callbacks may advance the
   frontier and re-evaluate policy later, but add no evidence.
7. Treat `unknown`/`unavailable` as neutral: close future endpoint validity, add
   no clear evidence, and do not release ownership.

Gate:

- Oracle parity covers on/off/on bursts, aliases, sustained duration, duplicate
  callbacks, long quiet false negatives, unavailable, and restart.
- Posterior results are independent of duplicate/timer evaluation frequency.
- Existing public false-positive/flapping and false-negative scenarios pass.

### Phase 4: Implement Fixed-Lag Anonymous Movement Association

**Goal:** Replace directional-context caps and pending path fragments with exact
bounded association.

Tasks:

1. Add latent assignment alternatives for stay, graph-adjacent movement,
   `unlocated -> target`, and low-prior missed movement.
2. Keep mutually exclusive competing sources as joint assignment mass.
3. Enforce one external endpoint per crossing globally. Distinct endpoint events
   may support multiple crossings only when predecessor multiplicity permits.
4. Implement open-gate interval-censored routes from source, asserted gate, and
   target episode intervals without treating gate duration as repeated evidence.
5. Compute finite $D(C)$ by interval constraint propagation.
6. Implement validated UTC event timestamps, receive-time watermark
   $W(r)=r-L_{late}$, stale rejection, and in-lag deterministic recomputation.
7. Finalize only when the watermark passes the candidate deadline. Marginalize
   exact occupancy mass into the forward message and retain only bounded,
   lossless support certificates.
8. On overload, retain exact occupancy, preserve current `active`, and suppress
   release and learning until association processing is complete.

Gate:

- The bathroom departure remains unresolved while its local positive is current
  and retains the earlier causal mass across later linked updates.
- The office competing-source case cannot release the asserted office.
- Multi-crossing, same-room multiplicity, stale/out-of-order, expiration,
  compaction, and overload tests satisfy `MODEL-011` through `MODEL-016` and
  `MOVE-015` through `MOVE-020`.
- Finalization changes no occupancy probability beyond numerical tolerance.

### Phase 5: Implement Authoritative Count Kernels

**Goal:** Support exact count changes without identity or room heuristics.

Tasks:

1. Implement $K^+$ using independent boundary evidence when available and
   otherwise an `unlocated` arrival prior.
2. Implement $K^-$ by anonymous multiplicity-weighted removal, conditioned by
   independent boundary-exit evidence when available.
3. Apply multi-step changes as deterministic sequences of one-person kernels.
4. Deduplicate and order count controls. Persist their accepted sequence.
5. Make $N=0$ the unique empty state and the only count value that directly
   releases every held zone.
6. Ensure a nonzero count decrease never chooses the least-supported room,
   clears a latch directly, or invents which occupant left.

Gate:

- Oracle parity covers $0\to1$, $1\to2$, $2\to1$, $1\to0$, all intermediate
  counts through 5, multi-step changes, same-zone multiplicity, boundary
  evidence, and unlocated fallback.
- Normalization, exchangeability, and public policy behavior satisfy
  `MODEL-017` through `MODEL-021`.

### Phase 6: Replace Policy Gates with Posterior Events

**Goal:** Make public decisions direct consequences of the augmented posterior.

Tasks:

1. Compute $a_z=P(\operatorname{ArrivalSupported}(z)\mid O_{1:k})$ from joint
   assignment mass for each fresh target.
2. Compute finalized
   $r_z=P(\operatorname{ReleaseSafe}(z)\mid O_{1:k})$ for held zones using
   injective support matching.
3. Ensure `ReleaseSafe` excludes unlocated, contextless, prediction-only, stale,
   duplicated, flap-derived, coarsened, overloaded-incomplete, and unresolved
   competing support.
4. Keep current sustained local positive as a hard automatic-release veto until
   stable-clear finalization. Continuously stuck-on remains an explicit
   operator-reset/$N=0$/away/repair case.
5. Replace `PendingDeparture` and the legacy graph/relocation/count-exclusion
   gate conjunctions. Do not leave hidden fallback release paths.
6. Retain one deterministic `active` latch outside physical inference. Its on
   edge consumes the accepted acquisition decision and its off edge consumes the
   finalized release decision. Policy reads probabilities and evidence IDs but
   never changes them.
7. Record $a_z$, $r_z$, matching/support IDs, local veto, competing mass,
   threshold, watermark, and accepted/rejected reason in the audit.
8. Let prediction and route learning consume only finalized direct graph-valid
   assignments. Keep interval-censored and missed movement out of learning as
   required by the spec.

Gate:

- The exact bathroom test now passes: release occurs only after stable clear and
  finalized qualifying support.
- The exact office test remains held under competing-source ambiguity.
- Every scenario in governance families 2 through 11 passes at the public
  contract.
- There is one activation-risk threshold over $a_z$ and one release-risk
  threshold over $r_z$; no independent legacy probability conjunction can emit
  a public edge.

### Phase 7: Introduce Target Persistence and Deterministic Restore

**Goal:** Make restart equivalent to uninterrupted execution.

Tasks:

1. Add a new storage schema version only after the complete target payload is
   defined. Do not increment `STORAGE_VERSION` repeatedly during partial work.
2. Serialize compact configuration metadata and posterior values without
   repeating zone strings per configuration.
3. Persist unresolved factors, episode IDs/state, endpoint consumption,
   deadlines, watermark, finalized support certificates, $a_z$/$r_z$ inputs,
   count sequence, policy latches/audit, prediction leases, and route statistics.
4. Validate schema, map fingerprint, count, array dimensions, indexes, UTC
   datetimes, finite values, normalization, assignment references, and bounds as
   one atomic operation.
5. Restore before snapshot bootstrap. Purge only assignments already behind the
   restored finalization frontier; marginalize them without emitting public
   edges or making old endpoints reusable.
6. Define schema-5 migration conservatively:
    - preserve valid ownership for projection as target `active` and compatibility
       `keep_on`, plus bounded route statistics where safe;
   - do not convert directional contexts or replacement factors into invented
     target assignments;
   - initialize target inference from the complete current snapshot with no
     synthetic movement, activation, release, prediction, or learning; and
   - expose a clear migration status.
7. Reject malformed or incompatible target state atomically and bootstrap safely.

Gate:

- Restart at every episode/assignment/count/policy phase produces the same next
  posterior, public timeline, diagnostics ordering, and learning output as
  uninterrupted execution.
- Corrupt and incompatible payloads fail as a unit.
- Persistence size, serialization, restore, and startup remain within approved
  prototype ceilings.

### Phase 8: Cut Over the Tracker Facade

**Goal:** Make the replacement engine authoritative without changing public
entity semantics.

Tasks:

1. Switch `OccupancyTracker` internals to the replacement engine while preserving
   runtime-facing methods and immutable update behavior.
2. Project existing `ZoneState`, anonymous tracks, summaries, binary sensors,
   status payloads, diagnostics, and WebSocket responses from the new result.
3. Add target `active`, `prelight`, `home_active`, and
   `predictive_controls_problem` entities, the optional disabled arrival event,
   and optional disabled probability sensors exactly as `ENT-001` through
   `ENT-009` specify.
4. Remove legacy behavior calls from the authoritative path, but retain the old
   engine briefly as a test/replay comparator until release validation passes.
5. Dual-project compatibility entities for at least one full released version:
   `keep_on` aliases `active`, `activation_plausible` retains the accepted-arrival
   lease, `prelight_plausible` aliases `prelight`, and `home_keep_on` aliases
   `home_active`. Preserve existing registry rows; disable legacy entities by
   default only for new installs.
6. Migrate repository-owned Home Assistant automations and public regression
   assertions to `active`/`prelight`. Keep factual legacy assertions where they
   prove pre-cutover behavior and add the target edge beside them.
7. Run a recorded shadow corpus comparing old/new public timelines. Every
   intentional difference must map to a normative requirement and retained test.

Gate:

- No Home Assistant adapter or automation needs lower-layer inference logic.
- Entity registry, summary, status, panel, WebSocket, runtime, and action tests
   pass with target projections and compatibility aliases.
- No target decision depends on legacy filter or policy state.
- Manual controlled-device state never feeds `active`, and restart/reload emits
   neither a synthetic `active` edge nor an arrival event.

### Phase 9: Enable Counts 3 Through 5 End to End

**Goal:** Expose the already-proven count range through every supported surface.

Tasks:

1. Raise validation from 2 to 5 in `config_flow.py`, `websocket.py`, runtime count
   synchronization, tracker configuration, and panel inputs.
2. Remove unsupported-count fallback behavior that maps counts above two to a
   public zero state.
3. Preserve validation for negative, fractional, unavailable, stale, duplicate,
   and above-five count values.
4. Update status/diagnostics to show requested, accepted, stale/rejected, and
   current authoritative count controls.
5. Add frontend and Home Assistant adapter tests for every count 0 through 5.

Gate:

- Counts 0 through 5 work through static config and the authoritative entity.
- No interface claims support above 5.
- $N=2$ benchmark and incident behavior do not regress.

### Phase 10: Remove Legacy Core and Release the Target Contract

**Goal:** Finish with one production model and no semantic fallback.

Tasks:

1. Delete legacy filter/context/pending-departure code only after no production
   import or restore path uses it.
2. Retain schema-5 migration readers for the documented compatibility window;
   do not retain schema-5 inference semantics.
3. Update `README.md`, `CHANGELOG.md`, `SHADOW_VALIDATION.md`, package description,
   diagnostics documentation, and performance results to describe the actual
   released model and count range.
4. Update or remove legacy tests only when a normative requirement and target
   replacement test justify the change.
5. Retain the legacy entity projections for the `ENT-010` compatibility release.
   Their removal is not part of legacy inference-core deletion. Propose removal
   later as a separately reviewed breaking change after migration evidence.
6. Perform independent post-implementation conformance review before broad
   release validation.

Gate:

- No references remain to top-K pruning, removable current-state factors,
  capped directional contexts, pending-departure gate conjunctions, or 0-to-2
  support as production behavior.
- The target default surface has no third per-zone binary sensor; legacy entities
   remain compatibility projections only for the documented release window.
- All completion criteria below pass.

## Testing Strategy

Use four complementary levels. None substitutes for another.

### Exact mathematical tests

- count-vector rank/unrank and complete configuration enumeration;
- operator/oracle equality on randomized small maps;
- count conservation and exchangeability;
- posterior and augmented-mass normalization within `1e-12`;
- exact marginalization invariance;
- endpoint injectivity and source multiplicity;
- `ArrivalSupported` and `ReleaseSafe` sums against brute force; and
- deterministic ordering independent of dictionary/hash order.

### Retained public scenarios

- exact bathroom delayed-confirmation incident;
- exact office competing-source incident;
- all 12 scenario families in `docs/spec/change-governance.md`;
- inverse, disconnected, missed, stale, flap, unavailable, quiet, stuck-on,
  same-room, multi-crossing, restart, and overload cases; and
- public `active` and `prelight` timelines, optional arrival-event idempotence,
  and compatibility `activation_plausible`, `keep_on`, and
  `prelight_plausible` projections during the documented window.

### Persistence and adapter tests

- target-schema round trip and corruption rejection;
- schema-5 conservative migration;
- restart at every unresolved/finalized boundary;
- config flow, WebSocket, runtime count entity, status, diagnostics, panel, entity
  registry, summary, binary sensor, and sensor projection; and
- no synthetic public edge during bootstrap, migration, reload, or restore.

### Performance tests

Run the 16-zone/17-node/23-entity reference map at the maximum supported count
$N=2$.
Include the deterministic 10,000-update one-millisecond replay plus correlated
burst, maximum-lag, out-of-order, all-episodes-active, and overload traces.
Report every metric required by governance scenario 12.

## Required Validation Commands

After focused tests for each edited slice, run all repository gates before a
phase is declared complete:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
npm run test:frontend
.venv/bin/python benchmarks/occupancy_performance.py \
  --events 100 \
  --output /tmp/predictive-controls-performance.json
```

The benchmark command accepts occupant count, trace profile, and target output.
Final release validation must run the complete 10,000-update $N=2$ profile, not
only the 100-event CI smoke command.

The Python test command enforces whole-package 100% branch coverage. Do not lower
coverage, remove retained regressions, or relax exactness/performance gates to
complete a phase.

## Cutover and Rollback

Before target-schema data is written, rollback means selecting the legacy engine
behind the tracker facade and re-running its unchanged tests. After target-schema
data is written, code rollback must not ask old code to parse target state.
Instead:

1. stop before loading incompatible state;
2. preserve the target Store payload for diagnosis;
3. restore the last known schema-5 backup only when it is known compatible with
   the rolled-back release; and
4. otherwise cold-bootstrap the legacy engine from the current snapshot while
   conservatively retaining external automation safety.

Do not implement automatic bidirectional state conversion. Target state contains
probabilistic association that schema 5 cannot represent, and converting it back
would fabricate or discard semantics.

## Definition of Done

The migration is complete when all of these are true:

- The canonical specification has no known implementation discrepancy.
- Both retained production incidents pass at the public contract.
- All optimized operators match the exact oracle.
- Every occupancy configuration for supported $N=0\ldots2$ remains represented with zero
  pruned probability.
- Observation episodes, count kernels, fixed-lag assignments, policy-event
  probabilities, prediction separation, and deterministic restore satisfy their
  named requirements.
- The $N=2$ primary and maximum profile passes approved latency, memory, graph,
  persistence, startup, and overload gates.
- All Python tests pass with 100% branch coverage; Ruff, mypy, and frontend tests
  pass.
- The final independent conformance review returns `PASS`.
- Target `active`/`prelight` automation semantics pass, and legacy entity IDs
   remain usable throughout the documented compatibility release.
- Documentation and changelog describe implemented behavior rather than the old
  engine or an unshipped target.

Until every item above is complete, describe the target model as implementation
pending and keep `async-todo.md` current with the next executable gate.