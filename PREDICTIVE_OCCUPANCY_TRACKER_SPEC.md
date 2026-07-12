# Predictive Occupancy Tracker Behavioral Specification

**Created:** 2026-07-12
**Status:** Implementation candidate; external rollout validation pending
**Scope:** Occupancy inference, movement tracking, prediction, and Home Assistant entity contracts

**Remediation companion:** See
[`PREDICTIVE_OCCUPANCY_TRACKER_REMEDIATION_SPEC.md`](PREDICTIVE_OCCUPANCY_TRACKER_REMEDIATION_SPEC.md).
Its bounded-inference design, performance budgets, and rollout gates supersede
this document's implementation plan where they conflict. The behavioral
requirements and public entity contract in this document remain normative.

The current-state assessment below records the pre-remediation baseline at this
document's creation. It is retained for design traceability, not as a statement
about the 0.1.18 implementation candidate. The candidate is not considered a
completed production cutover until the remediation companion's seven-day
external rollout gate is recorded and reviewed.

## Executive Decision

Predictive Controls is an inference layer. Its primary product is a small set of
stable Home Assistant entities; automations should not reproduce occupancy,
path, confidence, timeout, or recovery logic.

The canonical room automation contract is:

1. `binary_sensor.<zone>_activation_plausible` changing to `on` authorizes a
   normal turn-on.
2. `binary_sensor.<zone>_keep_on` changing to `off` authorizes a normal turn-off.
3. `binary_sensor.<zone>_prelight_plausible` changing to `on` optionally
   authorizes a low-impact prelight.

Confidence, raw sensor state, paths, track assignments, timers, and reasons are
diagnostics. A normal room automation must not need them.

The tracker must prefer a stale light over a false-off. A local sensor clear is
negative sensor evidence, not proof that a person left. A zone stops owning an
occupant only when the tracker observes a graph-valid departure, confidently
reassigns that occupant elsewhere, receives an authoritative zero-occupant
state, or is explicitly reset.

## Scope Baseline

- **Discovery method:** Review of all 26 Python modules under
  `custom_components/predictive_controls`, all 19 Python test modules, and the
  repository README, with focused tracing through runtime events, graph
  inference, confidence scoring, track selection, prediction, persistence, and
  automation-facing entities.
- **In scope:** Per-zone entity semantics, anonymous occupant tracks, graph
  traversal, missed-movement recovery, multi-occupant data association,
  deterministic and learned prediction, startup/restart behavior, diagnostics,
  and scenario-level acceptance tests.
- **Out of scope:** Person identity, cameras, biometric recognition, direct
  control of a specific light entity, room-specific automation policy, and
  replacement of Home Assistant's automation engine.

## Goals

- Keep consuming automations to the three simple per-zone entities.
- React to valid movement during the same event cycle.
- Predict forced graph continuations before destination sensors fire.
- Reject non-adjacent and uncorroborated false positives.
- Never clear an occupied zone from a local sensor clear or timer alone.
- Recover from missed movement by globally reconciling strong evidence with the
  configured occupant count.
- Track two simultaneous occupants and two simultaneous path hypotheses.
- Preserve understandable, replayable reasons for every automation-facing
  state transition.

## Non-Goals

- Persistently identifying which household member owns a track.
- Learning person-specific routines without an identity source.
- Guaranteeing the physical identity of an anonymous track across crossings.
- Turning ordinary automations into consumers of confidence thresholds or
  internal track IDs.
- Treating prediction as proof of occupancy.

## Current-State Assessment

The current implementation has strong foundations, but it only partially
matches the target behavior.

| Area                           | Assessment                            | Current behavior and gap                                                                                                                                                                                                                                                           |
| ------------------------------ | ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Simple entities                | Mostly aligned                        | `activation_plausible`, `keep_on`, and `prelight_plausible` exist. The README also recommends raw-motion triggers plus an activation guard, which creates a second public pattern. The target contract should use `activation_plausible` itself as the turn-on event.              |
| Confidence model               | Useful diagnostic, over-authoritative | Confidence encodes evidence quality well, but `keep_on` is derived directly from the `possible` threshold. Passive decay can therefore turn `keep_on` off without evidence that an occupant left.                                                                                  |
| Sensor-clear handling          | Not aligned                           | Sustained-room clears now decay gradually, but they still eventually clear a zone by time alone. The target rule requires a departure or confident relocation.                                                                                                                     |
| Graph constraints              | Mostly aligned                        | Zone adjacency, trail corridors, transition timing, and non-adjacent caps exist. Occupancy adjacency is symmetrized while Markov adjacency remains directional, so one map field currently has two semantics.                                                                      |
| Deterministic prediction       | Partial                               | A node with one configured outgoing edge predicts that edge immediately. The predictor does not use the incoming edge or per-track path context, so it cannot reliably identify a sole forward continuation when the previous area is also adjacent.                               |
| Learned prediction             | Partial                               | The first-order Markov model learns shared node transitions. It does not condition on the current track's previous node, and interleaved users can create ambiguous event pairing on shared graph segments.                                                                        |
| Simultaneous predictions       | Not aligned                           | Prediction hints are global and replaced by the latest `on` event. Two occupants cannot retain two independent predicted paths or prelight leases.                                                                                                                                 |
| False-positive rejection       | Partial                               | A non-adjacent event is capped when the configured occupant count is saturated by active tracks. Retained but currently inactive occupants do not saturate that check. Repeated hits from the same false sensor can also become their own prior occupancy evidence.                |
| Occupant count                 | Partial                               | The tracker selects the strongest zone candidates and supports one join slot per zone. These are ranked zone snapshots, not durable occupant hypotheses with path continuity.                                                                                                      |
| Track stability                | Not aligned                           | `track_1`, `track_2`, and so on are reassigned by score order on every event. Their IDs can swap without movement. The target model avoids false identity by canonicalizing exchangeable joint configurations while retaining directional context only where evidence supports it. |
| Missed movement                | Partial                               | Competition can sharply decay stale zones when stronger tracks fill the configured count. There is no joint posterior update proving that the configured occupants are better accounted for by the new evidence.                                                                   |
| Same-room occupants            | Partial                               | A join slot can represent a second occupant in one zone and can be consumed by a departure. The target model represents same-room counts directly in joint configurations.                                                                                                         |
| `expected_occupants` semantics | Ambiguous                             | Positive values limit track selection, while `0` disables competition. An entity value such as `not_home` also resolves to `0`, so "nobody home" and "unbounded tracking" are conflated.                                                                                           |
| Restart behavior               | Not aligned                           | Markov counts persist, but track ownership, confidence, recent paths, and held occupancy do not. Startup replays current entity states as new events and can synthesize misleading activation/path evidence.                                                                       |
| Observability                  | Strong base                           | Status and diagnostics expose confidence, recent events, tracks, departures, predictions, and reasons. They do not yet explain competing configurations, observation likelihoods, posterior mass transfer, policy latch decisions, or why an activation was rejected.              |
| Tests                          | Strong base, internal focus           | Scenario coverage is broad, but several assertions target internal confidence/status rather than the public entity transitions that automations consume.                                                                                                                           |
| Documentation                  | Needs synchronization                 | The README's sustained half-life and recommended automation pattern can drift from code. Behavioral constants and entity semantics need contract tests or generated documentation.                                                                                                 |

## Target Domain Model

### Exchangeable Position State

One anonymous occupant position inside a joint hypothesis. A position records a
zone or the special `unlocated` state, plus optional incoming-edge context while
movement is active. Position states are exchangeable: swapping two anonymous
occupants does not create a different physical state.

### Joint Occupancy Configuration

A canonical sorted tuple of position states whose length equals the configured
occupant count. For two occupants, `{alex_office, kitchen}` and
`{kitchen, alex_office}` are one configuration, while `{living_room,
living_room}` represents two occupants together. Every configuration conserves
the exact occupant count.

For `Z` position states and two occupants, the base state count is
`Z * (Z + 1) / 2`. With 16 zones this is 136 configurations, small enough for
exact deterministic filtering. Directional transition context increases the
count but remains tractable for the two-occupant target.

### Posterior Distribution

A normalized probability distribution over joint occupancy configurations. It
couples all zones: strong evidence in one place must compete with explanations
that already account for the configured occupants elsewhere. The production
target uses log probabilities and deterministic ordering to avoid underflow and
non-reproducible ties.

### Observation Evidence

The current state and provenance of one mapped sensor entity. Observation
likelihood depends on signal type, configured reliability, state, and age, not
on confidence previously created by that same entity. Repeated state changes
from one entity replace or age that entity's contribution instead of being
treated as independent corroboration.

### Movement Hypothesis

A graph-valid transition represented inside one or more joint configurations.
Incoming-edge context distinguishes forward movement from reversal without
claiming persistent person identity. If occupants merge or cross and identity
becomes unobservable, equivalent hypotheses are marginalized rather than
arbitrarily relabeled.

### Automation Policy Latch

A per-zone, stateful projection from posterior and evidence provenance to the
simple Home Assistant entities. Policy latches deliberately apply asymmetric
risk: ambiguous evidence may retain `keep_on`, but cannot manufacture a new
`activation_plausible` authorization.

### Prediction Lease

A time-bounded target derived from posterior movement hypotheses. Leases from
separate simultaneous paths coexist. The public zone `prelight_plausible`
entity is the logical OR of all valid leases for that zone.

### Diagnostic Confidence

The posterior marginal probability that at least one occupant is in a zone.
It is useful for diagnostics, ranking, and policy evidence, but crossing a
numeric threshold alone must not release a held `keep_on` latch.

## Automation-Facing Entity Contract

### `activation_plausible`

- Represents a short authorization event to perform a normal turn-on.
- Turns on when trusted evidence newly establishes or re-establishes occupancy
  in a zone strongly enough to pass the activation policy.
- Does not turn on for prediction alone.
- Does not turn on for a first isolated hit while the joint posterior already
  accounts for all occupants elsewhere.
- Repeated `off`/`on` reports from the same uncorroborated sensor must not create
  their own corroboration.
- May be implemented as a short pulse, but its duration is an internal contract
  and must be long enough for Home Assistant to publish a reliable state edge.

### `keep_on`

- Is latched on while the zone remains part of the last trusted occupancy
  explanation and no permitted clear cause has superseded it.
- Remains on when all local sensors clear and the occupant has not been
  confidently moved elsewhere.
- Remains on while movement evidence is ambiguous.
- Turns off only when the posterior and evidence provenance support a valid
  departure, confidently account for the final possible occupant elsewhere,
  apply an authoritative occupant-count change, or process an explicit reset.
- Must not turn off from elapsed time, confidence decay, a single local clear,
  integration reload, or Home Assistant restart alone.

### `prelight_plausible`

- Is on while any valid prediction lease targets the zone above the configured
  policy threshold.
- Does not assign occupancy and cannot by itself make `activation_plausible` or
  `keep_on` true.
- Supports simultaneous leases from independent movement hypotheses.
- Expires independently per movement hypothesis and target.

### Aggregate and Diagnostic Entities

- `home_keep_on` is on while any zone's keep-on policy latch is on.
- Aggregate zone-list sensors remain projections of the three public contracts.
- Diagnostics expose top configurations, zone marginals, posterior entropy,
  observation likelihoods and provenance, path evidence, prediction leases,
  policy reasons, and rejected alternatives.
- Diagnostic confidence remains available but is not required by ordinary
  automations.

## Occupancy and Clearing Rules

1. A local `on` event is positive evidence; a local `off` event only ends that
   sensor's active evidence.
2. A sensor clear weakens observation support but does not release the zone's
  keep-on latch.
3. A graph-valid departure transfers posterior mass only when event ordering,
  incoming-edge context, and edge timing are compatible.
4. A transition event may support more than one joint configuration, but one
  sensor event must not silently move two occupants unless the evidence
  explicitly represents two occupants.
5. A strong non-adjacent candidate may repair missed movement only when the
  joint posterior produces a uniquely stronger whole-house explanation with a
  configured safety margin and positive destination evidence.
6. If relocation is ambiguous, the origin remains owned and the destination is
   quarantined or represented as uncertainty; the tracker must not create an
   extra occupant beyond the configured count.
7. A false-positive candidate cannot become trusted solely because its own
  previous hit raised the posterior for that candidate.
8. If a configuration places two occupants in one zone, one departure leaves
  one occupant there. `keep_on` remains on until the final occupant leaves.
9. A transition zone may temporarily contain posterior occupancy mass while its
  lighting policy remains independently defined by its zone entities.
10. Posterior diffusion may reduce diagnostic certainty and rank alternatives,
   but it cannot independently release a held keep-on latch.

## Graph and Prediction Rules

### Graph Semantics

- Physical adjacency and allowed movement direction must have unambiguous map
  semantics.
- If physical adjacency is represented as undirected, map validation must reject
  accidental one-way declarations or normalize them consistently for all
  consumers.
- If directed travel is supported, direction must be explicit and separate from
  undirected physical adjacency.
- Transition timing may differ by direction and must be evaluated against each
  compatible movement hypothesis.

### Deterministic Pathing

- Prediction first uses incoming-edge path context, not learned popularity.
- At a transition node, the immediately previous node is excluded from forward
  candidates unless reversal evidence exists.
- If exactly one graph-valid forward candidate remains, the tracker creates an
  immediate prediction lease for that target without waiting for Markov history.
- A deterministic prediction is cancelled when reversal evidence appears, a
  different branch is reached, the lease expires, or stronger evidence
  invalidates its source hypothesis.

### Learned Branch Prediction

- Learned probabilities rank two or more valid forward branches; they do not
  create graph-invalid destinations.
- Transition learning updates source-to-destination counts only from posterior
  path mass that consistently associates both endpoints.
- Interleaved events from two occupants must not be learned as one person's
  transition.
- Shared learned transition statistics are acceptable; simultaneous path
  hypotheses and leases must remain independent.
- The latest event on one path must not erase another path's active prediction
  lease.

## Occupant-Count Semantics

- The configured value is the exact number of occupants believed to be inside,
  not merely a scoring limit.
- Every joint configuration contains exactly that many exchangeable positions,
  which may be located or `unlocated`.
- `expected_occupants = 0` means nobody is expected inside: all ownership and
  keep-on states are cleared through an explicit, diagnosable count-change
  transition.
- If unconstrained tracking remains supported, it uses a distinct `null`,
  `unbounded`, or disabled setting rather than overloading zero.
- Increasing the count adds an `unlocated` position to every valid starting
  configuration and does not synthesize room activation.
- Decreasing the count marginalizes the least-supported occupant position while
  preserving policy latches still supported by retained occupancy.

## Functional Requirements

### Public Contract

- **REQ-001:** The system MUST expose per-zone `activation_plausible`, `keep_on`,
  and `prelight_plausible` binary entities.
- **REQ-002:** A normal room automation MUST be implementable using only an
  `activation_plausible -> on` trigger and a `keep_on -> off` trigger, with an
  optional `prelight_plausible -> on` trigger.
- **REQ-003:** Public entity state changes MUST be derived atomically from the
  same inference update so consumers do not observe contradictory intermediate
  states.
- **REQ-004:** `activation_plausible` MUST reassert when a zone reacquires trusted
  occupancy after its prior `keep_on` became false incorrectly or provisionally.
- **REQ-005:** Prediction alone MUST NOT set `activation_plausible` or `keep_on`.
- **REQ-006:** Diagnostic confidence thresholds MUST NOT be required in ordinary
  automations.

### Occupancy Retention and Clearing

- **REQ-007:** A local sensor changing to `off` MUST NOT by itself change
  `keep_on` from on to off.
- **REQ-008:** Elapsed time or posterior diffusion MUST NOT by itself change
  `keep_on` from on to off for a previously trusted occupied zone.
- **REQ-009:** The system MUST turn `keep_on` off after graph-valid movement
  evidence transfers the final supported occupant out of the zone.
- **REQ-010:** The system MUST support relocation after missed movement when
  strong evidence elsewhere uniquely accounts for the configured occupants.
- **REQ-011:** The system MUST retain the origin zone when missed-movement
  relocation is ambiguous.
- **REQ-012:** One occupant leaving a zone containing two occupants MUST NOT turn
  that zone's `keep_on` off.
- **REQ-013:** Every joint configuration MUST contain exactly the configured
  number of occupants.
- **REQ-014:** Multiple sensors or signal types in one zone MUST NOT be counted
  as multiple occupants.
- **REQ-015:** Every ownership release MUST record one of these causes: observed
  path departure, confident relocation, occupant-count reduction, explicit
  reset, or authoritative away state.

### False-Positive Control and Recovery

- **REQ-016:** When all occupants are accounted for, an isolated non-adjacent hit
  MUST NOT produce `activation_plausible`.
- **REQ-017:** Retained but sensor-inactive occupancy hypotheses MUST count as
  accounted for during false-positive suppression.
- **REQ-018:** Repeated hits from one uncorroborated entity MUST NOT manufacture
  corroboration solely from confidence created by that same entity.
- **REQ-019:** Candidate promotion MUST require a valid path, posterior mass in
  `unlocated`, independent local corroboration, or configured
  strong-relocation evidence.
- **REQ-020:** Recovery after a short sensor flap MUST preserve `keep_on` without
  requiring a new activation pulse.
- **REQ-021:** Recovery after a genuine provisional false-off MUST emit a new
  `activation_plausible` edge once trusted occupancy is reacquired.

### Graph Movement and Prediction

- **REQ-022:** Movement assignments MUST follow configured graph edges unless the
  strong-relocation rule explicitly records missed movement.
- **REQ-023:** A transition with exactly one forward candidate after excluding
  its incoming node MUST create a prediction lease in the same event cycle.
- **REQ-024:** A branching transition MUST use learned or configured branch
  probabilities only among graph-valid forward candidates.
- **REQ-025:** Prediction state MUST be maintained independently for every
  simultaneous movement hypothesis.
- **REQ-026:** Two valid simultaneous paths MUST be able to expose two different
  `prelight_plausible` zones at the same time.
- **REQ-027:** Events MUST contribute to a consistent posterior path before they
  are used for transition learning.
- **REQ-028:** Interleaved events on shared graph segments MUST NOT create a
  learned transition unless one posterior path consistently contains both
  endpoints.
- **REQ-029:** Physical adjacency, traversal direction, and transition-time map
  semantics MUST be validated and documented consistently.

### Multi-Occupant Tracking

- **REQ-030:** With `expected_occupants = 2`, every posterior configuration MUST
  conserve two anonymous occupants through independent simultaneous movement.
- **REQ-031:** Permutations of anonymous occupants MUST be canonicalized into one
  configuration rather than duplicated or treated as identity swaps.
- **REQ-032:** The system MUST support two occupants in different zones, two in
  the same zone, joining, splitting, crossing, and one located plus one
  `unlocated` occupant.
- **REQ-033:** An event on one compatible path MUST NOT overwrite another active
  path or prediction lease.
- **REQ-034:** When two assignments are equally plausible, the system MUST
  preserve uncertainty rather than fabricate a precise identity or path.
- **REQ-035:** Exact occupant-count changes MUST reconcile the posterior and
  public entities deterministically.

### Restart, Timing, and Observability

- **REQ-036:** Restart or integration reload MUST NOT produce synthetic
  `activation_plausible` edges from bootstrap state enumeration.
- **REQ-037:** Restart or reload MUST NOT turn `keep_on` off solely because
  in-memory state was lost.
- **REQ-038:** The minimum state needed to preserve ownership and path safety MUST
  be restored or reconstructed before automation-facing entities become
  authoritative.
- **REQ-039:** Expired prediction and activation leases MUST not be restored as
  active after downtime.
- **REQ-040:** Every public state transition MUST expose a machine-readable reason
  and supporting evidence in diagnostics.
- **REQ-041:** Quarantined candidates MUST expose why they were rejected or what
  additional evidence would promote them.
- **REQ-042:** Replay output MUST include public entity states after every event,
  not only internal confidence and track snapshots.
- **REQ-043:** Runtime event handling for one sensor update MUST complete without
  waiting for the periodic confidence refresh.

## Concrete Implementation Design

### New Internal Modules

| Module                     | Responsibility                                                                                                                               | Must not own                                                    |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `occupancy_state.py`       | Immutable position/configuration keys, canonicalization, posterior containers, marginals, log-sum-exp helpers, and inference update records. | Sensor calibration, Home Assistant state, or automation policy. |
| `observation_model.py`     | Convert one changed `OccupancyEvent` into per-zone-count log likelihoods; track entity provenance and reject duplicate same-state evidence.  | Graph transitions or policy latches.                            |
| `transition_model.py`      | Enumerate stay, adjacent movement, same-room, `unlocated`, and low-prior missed-movement successors from the graph and elapsed time.         | Sensor likelihoods or public entities.                          |
| `joint_filter.py`          | Predict, score, canonicalize, merge, normalize, deterministically prune, and derive marginals and movement mass.                             | Home Assistant entity projection.                               |
| `automation_policy.py`     | Maintain per-zone activation leases and keep-on latches from filter updates and explicit count/reset commands.                               | Posterior mutation or transition learning.                      |
| `prediction.py`            | Build, retain, cancel, and aggregate direction-aware prediction leases from posterior path mass and shared Markov statistics.                | Occupancy evidence.                                             |
| `occupancy_persistence.py` | Versioned serialization, map compatibility checks, lease expiry, and restore reconciliation for posterior and policy state.                  | Inference decisions.                                            |

### Existing Module Responsibilities

| Module                                                        | Implementation action                                                                                                                                                                                                                   |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `occupancy_tracker.py`                                        | Become the compatibility facade over `JointOccupancyFilter`, `AutomationPolicy`, and `PredictionManager`. Retain `observe()`, `states`, `recent_events`, and diagnostics during migration. Remove ranked-track ownership after cutover. |
| `occupancy_scoring.py`                                        | Retain legacy scoring only for shadow comparison and diagnostic compatibility. Move new likelihood math to `observation_model.py`. Delete ownership decisions from this module after cutover.                                           |
| `automation_summary.py`                                       | Read policy output and posterior marginals. It must not derive `keep_on` from status thresholds. Preserve `ZoneAutomationState` and `AutomationSummary` fields.                                                                         |
| `markov.py`                                                   | Preserve shared transition counts and serialization. Accept only weighted, posterior-consistent movement updates from the new filter.                                                                                                   |
| `engine.py`                                                   | Orchestrate prediction and actions from filter output. Stop pairing raw global events as if they belonged to one user.                                                                                                                  |
| `runtime.py`                                                  | Preserve event subscriptions and dispatcher behavior; restore inference state before bootstrap; run shadow comparison; persist after accepted updates.                                                                                  |
| `confidence.py`                                               | Preserve the current facade while delegating to the tracker. Zone confidence becomes the posterior occupied marginal.                                                                                                                   |
| `status.py`, `diagnostics.py`                                 | Add posterior, provenance, policy, pruning, and shadow-diff payloads while keeping existing keys during one compatibility release.                                                                                                      |
| `binary_sensor.py`, `sensor.py`, `actions.py`, `websocket.py` | Preserve external contracts; adapt only to consume the new summary/diagnostic structures.                                                                                                                                               |

No entity unique ID, entity name, automation trigger, YAML map field, action
schema, or websocket command changes as part of the inference cutover.

### Core Data Structures

The implementation should use frozen dataclasses and tuples for hypothesis keys.
Names below are normative; field spelling may change only if all semantics and
tests remain equivalent.

```python
@dataclass(frozen=True)
class PositionState:
    zone: str | None                 # None means unlocated
    incoming_zone: str | None        # directional context, never identity
    entered_at: datetime | None

@dataclass(frozen=True)
class HypothesisKey:
    positions: tuple[PositionState, ...]  # canonical sort order

@dataclass(frozen=True)
class WeightedHypothesis:
    key: HypothesisKey
    log_probability: float

@dataclass(frozen=True)
class Posterior:
    hypotheses: tuple[WeightedHypothesis, ...]
    updated_at: datetime
    pruned_probability: float

@dataclass(frozen=True)
class ObservationProvenance:
    event_id: str
    evidence_episode_id: str
    entity_id: str
    node_id: str
    zone: str
    state: str
    signal_type: str
    reliability: float
    log_likelihood_by_count: tuple[float, ...]
    disposition: str

@dataclass(frozen=True)
class FilterUpdate:
    previous: Posterior
    current: Posterior
    occupied_marginals: Mapping[str, float]
    count_marginals: Mapping[str, tuple[float, ...]]
    movement_mass: Mapping[tuple[str, str], float]
    provenance: ObservationProvenance

@dataclass(frozen=True)
class ZonePolicyState:
    keep_on: bool
    activation_expires_at: datetime | None
    last_trusted_at: datetime | None
    reason: str
    evidence_ids: tuple[str, ...]

@dataclass(frozen=True)
class PredictionLease:
    path_key: tuple[str, str | None, str]
    target_zone: str
    probability: float
    expires_at: datetime
    reason: str
```

Canonicalization uses an explicit `position_sort_key()` returning only mutually
comparable values: `(zone is None, zone or "", incoming_zone or "",
entered_at.isoformat() if entered_at else "")`. Do not rely on dataclass ordering
or compare naive and timezone-aware datetimes. `hypothesis_sort_key()` is the
tuple of position sort keys. Duplicate canonical keys are merged with
log-sum-exp. Two equal positions are retained, so a same-room pair remains
distinguishable from one occupant without assigning identities.

### Observation Model

The first implementation uses explicit calibrated profiles rather than treating
the existing confidence number as a probability. Each profile defines
`P(on | count > 0)`, `P(on | count = 0)`, `P(off | count > 0)`, and
`P(off | count = 0)`. Configured reliability interpolates each base probability
toward the uninformative value `0.5`:

`calibrated = 0.5 + reliability * (base - 0.5)`.

Starter profiles must be constants with unit tests:

| Profile                | `on, occupied` | `on, empty` | `off, occupied` | `off, empty` |
| ---------------------- | -------------: | ----------: | --------------: | -----------: |
| Sustained/still-target |           0.97 |        0.02 |            0.30 |         0.95 |
| Ordinary room motion   |           0.90 |        0.04 |            0.45 |         0.90 |
| Transition motion      |           0.85 |        0.05 |            0.55 |         0.85 |

An `unknown` or `unavailable` state is neutral. A duplicate event with the same
entity state is neutral. Within one correlation episode, a later edge from the
same entity replaces that entity's prior active likelihood contribution: the
filter applies `new_log_likelihood - previous_log_likelihood`, not a second full
likelihood. A quiet interval longer than the profile's correlation window starts
a new episode, but policy still cannot treat two episodes from one entity as
independent corroboration. Independent entities compose in log space. Every
replacement and episode ID remains visible in provenance.

The profile values are safe initial calibration values, not user-facing knobs.
Changing them requires replaying the acceptance corpus and documenting the
public timeline differences.

### Transition Model

For each position in each prior configuration, enumerate:

1. staying in the current zone;
2. moving to each graph-valid adjacent zone;
3. remaining or becoming `unlocated` when the authoritative count is positive;
4. moving from `unlocated` to a locally observed zone;
5. a low-prior non-adjacent move used only for missed-movement recovery.

Take the Cartesian product for all positions, canonicalize each result, and
merge duplicates. Transition weights use configured directional transition
seconds, dwell statistics, and shared Markov counts. The missed-movement prior
must be lower than every graph-valid movement prior and cannot by itself satisfy
the activation policy.

The transition enumerator emits predecessor movement tags before equivalent
successors are merged. `joint_filter.py` aggregates those tags into posterior
movement mass so policy and learning can distinguish `office -> hallway` from a
coincident hallway observation.

### Filter Update Order

Every event is processed synchronously in this order:

```python
def observe(event: OccupancyEvent) -> FilterUpdate:
    provenance = observation_model.prepare_delta(event)
    if provenance.disposition == "duplicate":
        return unchanged_update(provenance)

    predicted = transition_model.propagate(posterior, event.event_at)
    scored = score_by_likelihood_delta(predicted, provenance)
    merged = merge_canonical_hypotheses(scored)
    normalized = normalize_log_probabilities(merged)
    posterior = deterministic_prune(normalized)
    update = derive_marginals_and_movement_mass(posterior, provenance)

    policy.apply(update)
    predictions.apply(update)
    transition_learning.apply(update)
    return update
```

The normalizer must reject NaN and positive infinity, handle all-impossible
observations by retaining the prior with a diagnostic error, and guarantee
probability sum `1.0 +/- 1e-12`. Sorting is always by descending probability and
then canonical key; dictionary order is never a tie-breaker.

Use exact enumeration while the posterior has at most 512 configurations. Above
that target, retain configurations until cumulative retained probability is at
least `0.999999`, up to a hard maximum of 4096. Record dropped mass. Shadow mode
must fail its validation gate if any normal event drops more than `0.0001` mass.

### Automation Policy

Policy is intentionally asymmetric and stateful:

- A positive local event may emit `activation_plausible` only when the occupied
  marginal reaches `0.60`, increases by at least `0.20`, and is supported by a
  graph path, independent corroboration, recovery of a previously trusted zone,
  or prior mass in `unlocated`.
- A prediction never satisfies an activation condition.
- An activation sets `keep_on`; a clear event does not unset it.
- A graph-valid release requires both zone occupied marginal at or below `0.20`
  and at least `0.85` posterior movement mass carrying the final supported
  occupant out of the zone.
- A non-adjacent relocation release requires zone occupied marginal at or below
  `0.10`, destination occupied marginal at or above `0.80`, and posterior odds
  of at least `10:1` for relocation over retaining the origin.
- An authoritative count of zero and an explicit reset release all latches.
- Thresholds are named internal constants. They are changed only with replay
  evidence and public-contract tests, not exposed as initial UI tuning knobs.

`AutomationPolicy` receives immutable `FilterUpdate` values and returns immutable
zone policy snapshots. It must never modify the posterior to justify its own
prior output.

### Prediction and Learning

For posterior paths with sufficient mass:

1. exclude the incoming zone from forward candidates;
2. if one candidate remains, create a lease immediately;
3. if multiple remain, rank only those candidates with shared Markov counts;
4. retain leases from other simultaneous path keys;
5. cancel a lease on reversal, incompatible destination evidence, expiry, count
   reduction, reset, or map incompatibility.

Only posterior-consistent movement mass at or above `0.80` may update Markov
counts. Its weight is the movement mass. Prediction probabilities never feed
back into observation likelihoods or occupancy posterior scores.

### Persistence and Bootstrap

Extend the existing Home Assistant `Store` payload rather than introducing a
second persistence mechanism. Increment the storage schema and persist:

- map fingerprint and authoritative occupant count;
- normalized top posterior configurations;
- per-zone policy latches and evidence IDs;
- unexpired activation and prediction leases;
- observation entity states needed to suppress bootstrap duplicates;
- existing shared transition counts.

On startup, load and validate stored data before registering current entity
states as observations. Expire leases using elapsed wall time. If the map
fingerprint changed, discard invalid positions and redistribute their mass to
`unlocated`; do not guess renamed zones. Current Home Assistant states reconcile
as bootstrap observations with activation suppressed. Persisted data that fails
schema or numerical validation is rejected atomically and surfaced in
diagnostics.

## Development Plan

Each phase ends with an executable gate. The legacy tracker remains available
until the shadow comparison phase passes; there is no half-converted public
entity mode.

### Phase 0: Freeze the Public Contract

| Task    | Files                               | Work and exit test                                                                                                                        | Requirements                |
| ------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- |
| `T-001` | `tests/occupancy_test_utils.py`     | Add a trace runner that records all three public zone entities after every event. Prove it can express the current Alex Office incident.  | REQ-001-006, REQ-042        |
| `T-002` | `tests/test_occupancy_scenarios.py` | Convert the short-clear regression and representative entry/exit tests to exact public timelines before changing inference.               | REQ-007-012                 |
| `T-003` | `tests/fixtures/occupancy_traces/`  | Store the 2026-07-12 office flap as timestamped input and expected output, with entity IDs anonymized only if the repository requires it. | REQ-007, REQ-042            |
| `T-004` | Full suite                          | Record the current `164 passed` baseline. No inference behavior changes in this phase.                                                    | All regression requirements |

**Gate:** existing suite passes and the incident fixture fails if `keep_on`
contains any false interval.

### Phase 1: Build the Pure Joint Model

| Task    | Files                                                     | Work and exit test                                                                                                                      | Requirements             |
| ------- | --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| `T-101` | `occupancy_state.py`, `tests/test_occupancy_state.py`     | Implement canonical keys, exact count conservation, log normalization, marginals, deterministic ordering, and serialization primitives. | REQ-013, REQ-030-032     |
| `T-102` | `observation_model.py`, `tests/test_observation_model.py` | Implement profiles, reliability interpolation, provenance, unavailable handling, and same-entity duplicate suppression.                 | REQ-014-019              |
| `T-103` | `transition_model.py`, `tests/test_transition_model.py`   | Enumerate graph-valid, same-room, unlocated, and low-prior missed-movement successors with directional context.                         | REQ-009-011, REQ-020-021 |
| `T-104` | `joint_filter.py`, `tests/test_joint_filter.py`           | Implement predict-score-merge-normalize-prune and movement-mass derivation.                                                             | REQ-010-019, REQ-030-034 |
| `T-105` | `prediction.py`, `tests/test_prediction.py`               | Implement forced continuation, branch ranking, simultaneous leases, reversal cancellation, and strict non-evidence behavior.            | REQ-003, REQ-022-026     |
| `T-106` | `automation_policy.py`, `tests/test_automation_policy.py` | Implement activation authorization, keep-on latching, graph release, relocation margin, recovery, reset, and count-zero rules.          | REQ-001-012, REQ-034-035 |

**Gate:** pure tests pass without importing Home Assistant. Seeded permutation
tests produce byte-for-byte equal posterior and policy snapshots.

### Phase 2: Integrate in Shadow Mode

| Task    | Files                                         | Work and exit test                                                                                                                             | Requirements         |
| ------- | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| `T-201` | `occupancy_tracker.py`, `confidence.py`       | Feed every event to legacy and joint trackers. Continue publishing legacy entities; expose joint posterior and proposed policy in diagnostics. | REQ-036, REQ-040-043 |
| `T-202` | `runtime.py`, `engine.py`                     | Keep event handling synchronous; route proposed movement mass to prediction and transition learning without changing public outputs.           | REQ-022-029, REQ-043 |
| `T-203` | `status.py`, `diagnostics.py`, `websocket.py` | Add top configurations, marginals, evidence provenance, prune mass, policy reasons, and legacy-versus-joint entity diffs.                      | REQ-036, REQ-040-042 |
| `T-204` | Replay and scenario tests                     | Replay all existing scenarios through both trackers and classify every diff as intentional, legacy defect, or joint-model defect.              | REQ-007-042          |

**Gate:** no unexplained public-output diffs, no normalization/invariant errors,
no event with pruned mass above `0.0001`, and the full suite remains green.

### Phase 3: Cut Over Public Policy and Prediction

| Task    | Files                                  | Work and exit test                                                                                                                                          | Requirements         |
| ------- | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| `T-301` | `automation_summary.py`                | Source confidence from posterior marginals and all three public booleans from `AutomationPolicy`/`PredictionManager`. Preserve dataclass and entity fields. | REQ-001-006, REQ-036 |
| `T-302` | `engine.py`, `markov.py`, `actions.py` | Replace global event pairing with posterior-consistent movement learning and multi-lease action evaluation.                                                 | REQ-022-029, REQ-033 |
| `T-303` | `binary_sensor.py`, `sensor.py`        | Verify no entity IDs, unique IDs, names, availability, or attributes regress. No intended production logic belongs here.                                    | REQ-001-006, REQ-036 |
| `T-304` | Core scenario tests                    | Rewrite legacy confidence/track assertions as exact public timelines and posterior invariants.                                                              | REQ-007-035          |

**Gate:** all acceptance scenarios below pass using the joint policy as the sole
public source; canonical two-trigger room automations remain unchanged.

### Phase 4: Persistence and Dynamic Count

| Task    | Files                                                 | Work and exit test                                                                                                 | Requirements         |
| ------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | -------------------- |
| `T-401` | `occupancy_persistence.py`, `const.py`, `__init__.py` | Add versioned serializer, map fingerprint, migration/rejection behavior, and existing-Store integration.           | REQ-037-039          |
| `T-402` | `runtime.py`                                          | Restore before bootstrap, suppress synthetic activation, expire leases, and schedule saves after accepted updates. | REQ-037-039, REQ-043 |
| `T-403` | `joint_filter.py`, `automation_policy.py`             | Reconcile occupant count increase, decrease, zero, and unavailable entity state.                                   | REQ-013, REQ-034-035 |
| `T-404` | Restart/count tests                                   | Test valid restore, stale leases, corrupt schema, changed map, and every count transition.                         | REQ-034-039          |

**Gate:** restart and count tests produce no synthetic activation or false
keep-on clear edges; corrupt storage cannot prevent integration startup.

### Phase 5: Remove Legacy Ownership

| Task    | Files                                                 | Work and exit test                                                                                                                                                               | Requirements             |
| ------- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| `T-501` | `occupancy_tracker.py`, `occupancy_scoring.py`        | Delete ranked-track, join-slot, conflict-decay, and confidence-threshold ownership paths after one compatibility release. Retain only diagnostic adapters still used externally. | REQ-007-019, REQ-030-035 |
| `T-502` | `status.py`, `diagnostics.py`, frontend payload tests | Remove deprecated diagnostics only after consumers no longer require them. Document payload migration.                                                                           | REQ-036, REQ-040-042     |
| `T-503` | README and examples                                   | Publish the three-entity contract, algorithm limits, restore behavior, and calibration workflow.                                                                                 | REQ-001-006, REQ-037-043 |

**Gate:** no production code computes ownership from confidence thresholds, all
tests pass, mypy is clean, and Ruff is clean when installed.

## Existing Test Reuse

The current 164-test suite is the migration safety net. Do not discard it as a
unit; preserve fixtures and intent even where internal assertions must change.

| Existing test module          | Disposition                         | Concrete use during overhaul                                                                                                                                                          |
| ----------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_model.py`               | Keep                                | Map parsing and validation remain authoritative.                                                                                                                                      |
| `test_entity_catalog.py`      | Keep                                | Entity discovery and signal metadata feed the observation model unchanged.                                                                                                            |
| `test_entity_platforms.py`    | Keep                                | Locks the three public entity families and platform setup.                                                                                                                            |
| `test_entity_registry.py`     | Keep                                | Locks entity cleanup and unique IDs.                                                                                                                                                  |
| `test_events.py`              | Keep                                | `OccupancyEvent` remains the filter input boundary.                                                                                                                                   |
| `test_occupancy_graph.py`     | Keep and extend                     | Keep all adjacency/corridor tests; add incoming-edge and directional successor cases.                                                                                                 |
| `test_occupancy_dwell.py`     | Keep                                | Dwell learning becomes a transition prior, not an ownership timeout.                                                                                                                  |
| `test_occupancy_settings.py`  | Keep and extend                     | Keep parsing; add unavailable, increase, decrease, and zero reconciliation cases.                                                                                                     |
| `test_panel.py`               | Keep                                | No inference behavior belongs in panel registration.                                                                                                                                  |
| `test_yaml_config.py`         | Keep                                | No map/action schema change is planned.                                                                                                                                               |
| `test_markov.py`              | Keep and extend                     | Preserve count/probability/restore tests; add weighted posterior-consistent updates.                                                                                                  |
| `test_engine.py`              | Adapt                               | Retain action/cooldown fixtures; replace global event-pair assumptions with movement-mass and simultaneous-lease assertions.                                                          |
| `test_actions.py`             | Adapt                               | Keep parsing and cooldown tests; pass aggregated lease probabilities from the new predictor.                                                                                          |
| `test_occupancy_replay.py`    | Adapt                               | Preserve replay input helpers; add the three public states after every step and deterministic repeat comparisons.                                                                     |
| `test_status.py`              | Adapt                               | Preserve existing payload keys through compatibility; add posterior/provenance/policy fields.                                                                                         |
| `test_websocket.py`           | Adapt                               | Preserve commands and round trips; extend expected diagnostic payloads only.                                                                                                          |
| `test_automation_summary.py`  | Rewrite assertions                  | Keep summary builders and dataclass coverage; replace confidence-threshold expectations with policy-latch and marginal expectations.                                                  |
| `test_confidence.py`          | Split and rewrite                   | Keep pure legacy scoring tests until Phase 5. Move ownership expectations to filter/policy tests; confidence no longer authorizes release.                                            |
| `test_occupancy_scenarios.py` | Rewrite assertions, reuse scenarios | Preserve maps, event builders, timings, false-positive cases, join/split cases, and the office regression. Assert public timelines and posterior invariants instead of ranked tracks. |

Add `tests/occupancy_test_utils.py` with `run_trace()`, `PublicSnapshot`,
`assert_zone_timeline()`, `assert_normalized()`, and `assert_count_conserved()`.
This avoids duplicating a second pseudo-runtime in every new test module.

## Required Acceptance Matrix

Each behavioral test records a public snapshot after every event. `A`, `K`, and
`P` below mean `activation_plausible`, `keep_on`, and `prelight_plausible`.

| ID                               | Event sequence                                                                                       | Required public result                                                                                                  | Required internal invariant                                                                                     | Requirements                  |
| -------------------------------- | ---------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| `S-01 Short clear`               | Office trusted; office `off`; two seconds; office `on`.                                              | Office `K` is always on; the final positive may pulse `A`; no false off edge or separate turn-off authorization exists. | Clear changes likelihood but does not satisfy a release gate.                                                   | REQ-004, REQ-007-008          |
| `S-02 Long clear only`           | Trusted room clears and no other events occur for hours.                                             | Room `K` remains on.                                                                                                    | Posterior may diffuse; policy reason remains retained ambiguity.                                                | REQ-007-008                   |
| `S-03 Observed departure`        | Office -> hallway -> destination within edge windows.                                                | Office `K` turns off only after final departure mass is confirmed; destination pulses `A`.                              | Count conserved; movement mass is attributed to graph-valid edges.                                              | REQ-009, REQ-020-021          |
| `S-04 Weak missed movement`      | Office trusted; one non-adjacent sensor fires once.                                                  | Office `K` remains on; candidate has no `A`.                                                                            | Retaining-origin hypotheses win; candidate is quarantined.                                                      | REQ-011, REQ-016-019          |
| `S-05 Strong missed movement`    | Office trusted; two independent destination sensors corroborate non-adjacent occupancy.              | Destination pulses `A`; office `K` clears only after relocation odds and marginals pass both gates.                     | Low-prior missed path is explicit and diagnostic.                                                               | REQ-010-011, REQ-019          |
| `S-06 Repeated false positive`   | All occupants accounted for; one unrelated entity fires repeatedly.                                  | False zone never pulses `A` or sets `K`.                                                                                | Duplicate/same-source evidence does not compound.                                                               | REQ-014-018                   |
| `S-07 Independent corroboration` | Two different signal sources in a candidate zone fire.                                               | Candidate may pulse `A` only if path/unlocated/relocation conditions also pass.                                         | Provenance contains both entity IDs exactly once.                                                               | REQ-015, REQ-019              |
| `S-08 Two interleaved paths`     | A moves office -> hall -> kitchen while B moves bedroom -> landing -> bath, with interleaved events. | Both destinations pulse `A`; origins clear independently; two `P` zones may coexist.                                    | Every configuration contains two occupants; no event erases the other path.                                     | REQ-025, REQ-030, REQ-033     |
| `S-09 Same-room join`            | One occupant trusted in kitchen; second graph-valid path arrives in kitchen.                         | Kitchen remains `K`; arrival may pulse `A`; no extra zone turns on.                                                     | Posterior mass moves to configurations containing kitchen twice.                                                | REQ-012-013, REQ-032          |
| `S-10 Same-room split`           | Two occupants supported in kitchen; one leaves along a valid path.                                   | Kitchen `K` remains on; destination pulses `A`.                                                                         | High posterior mass retains one kitchen position.                                                               | REQ-012, REQ-032              |
| `S-11 Crossing ambiguity`        | Two occupants swap adjacent zones through overlapping transition events.                             | No unrelated `A` or `K` edge; valid predictions remain bounded to paths.                                                | Permuted identities merge to one canonical physical explanation.                                                | REQ-031-033                   |
| `S-12 Forced continuation`       | Path enters a transition zone with one forward candidate.                                            | Target `P` turns on in the same inference cycle while target `A` and `K` remain unchanged.                              | No Markov history is required; prediction is not occupancy evidence.                                            | REQ-003, REQ-005, REQ-022-023 |
| `S-13 Branch prediction`         | Path enters a branch with two forward candidates and learned counts.                                 | Qualifying targets expose `P`; another concurrent path's lease remains.                                                 | Incoming zone excluded; ranking uses only forward candidates.                                                   | REQ-024-026                   |
| `S-14 Reversal`                  | A predicted path returns to its incoming zone.                                                       | Forward `P` lease cancels immediately; reversal alone does not synthesize `A`.                                          | Lease cancellation reason is `reversal`.                                                                        | REQ-026, REQ-040              |
| `S-15 Prediction isolation`      | Create path-one lease, then update unrelated path two.                                               | Both valid `P` outputs remain until their own cancellation/expiry.                                                      | Lease keys differ and are retained independently.                                                               | REQ-025-026, REQ-033          |
| `S-16 Count increase`            | Count changes one -> two while one room is trusted.                                                  | Existing room remains `K`; no new room pulses `A`.                                                                      | Every posterior key gains one `unlocated` position.                                                             | REQ-013, REQ-034-035          |
| `S-17 Count decrease`            | Count changes two -> one with unequal evidence.                                                      | Better-supported room stays `K`; removed occupancy does not create activation.                                          | Marginalization and tie-breaking are deterministic.                                                             | REQ-034-035                   |
| `S-18 Count zero`                | Authoritative count changes to zero.                                                                 | All `K`, `A`, and `P` outputs clear.                                                                                    | Posterior becomes the zero-occupant configuration.                                                              | REQ-034-035                   |
| `S-19 Restart clear sensors`     | Persist trusted room, stop, age time, restart with local sensor clear.                               | Room `K` is continuous; no bootstrap `A`; expired leases remain off.                                                    | Restore precedes bootstrap and provenance marks restored state.                                                 | REQ-037-039                   |
| `S-20 Corrupt restore`           | Storage has invalid schema, NaN, or wrong occupant count.                                            | Integration starts unavailable-to-clear without synthetic activation.                                                   | Stored inference is rejected atomically with a diagnostic reason.                                               | REQ-037-040                   |
| `S-21 Map change`                | Persisted hypothesis references a removed zone.                                                      | No removed-zone entity output and no guessed replacement activation.                                                    | Invalid position mass moves to `unlocated`; leases cancel.                                                      | REQ-038-040                   |
| `S-22 Out-of-order events`       | Destination timestamp precedes delayed transition delivery.                                          | Policy uses event time and either reconciles explicitly or quarantines; never silently invents a path.                  | Ordering disposition is deterministic and diagnostic.                                                           | REQ-010-011, REQ-040-042      |
| `S-23 Recovery pulse`            | A legacy/provisional false-off exists; trusted local evidence returns.                               | Zone pulses `A` again and sets `K`.                                                                                     | Recovery reason references prior trusted state and new evidence.                                                | REQ-002, REQ-040              |
| `S-24 Deterministic replay`      | Run every fixture twice and under 100 seeded equal-time event permutations.                          | Public timelines are byte-for-byte equal where timestamps impose no order.                                              | Posterior order, prune mass, and reasons are identical.                                                         | REQ-031, REQ-040-043          |
| `S-25 Activation lease expiry`   | A valid local arrival pulses `A`; advance past the activation lease without departure.               | `A` returns off while `K` remains on; a later independent arrival can create a new on edge.                             | Activation lease and occupancy policy latch have separate lifetimes.                                            | REQ-001-002, REQ-004          |
| `S-26 Prediction-only trace`     | Restore or inject a valid prediction lease without any local observation.                            | Target `P` may be on; target `A` and `K` remain off and aggregate occupied zones do not change.                         | Posterior is byte-for-byte unchanged by prediction evaluation.                                                  | REQ-003, REQ-005-006          |
| `S-27 Interleaved learning`      | Two users traverse different graph edges with alternating event delivery.                            | Public outputs follow both paths; no unrelated prelight appears from a cross-user pairing.                              | Markov counts update only for posterior-consistent edges at sufficient movement mass and never from prediction. | REQ-027-029                   |
| `S-28 Entity compatibility`      | Build entities and summaries before and after policy cutover from the same map.                      | Per-zone and aggregate IDs, names, availability, and boolean meanings are unchanged.                                    | New diagnostics are additive during compatibility; no public entity is renamed or removed.                      | REQ-006, REQ-036              |

### Numerical and Property Tests

The following are separate pure tests because scenario success can hide
probability defects:

- canonical permutations merge and same-room multiplicity is retained;
- normalized probabilities sum to `1.0 +/- 1e-12` after every update;
- no posterior, likelihood, marginal, or persisted value is NaN or infinite;
- exact occupant count holds for every hypothesis after every event;
- equivalent successor paths merge with log-sum-exp rather than `max`;
- deterministic pruning keeps the same keys and reports exact dropped mass;
- increasing the cap never changes retained high-probability ordering;
- one entity's duplicate state event has zero posterior effect;
- two independent entities compose once each;
- a prediction-only update has zero posterior effect;
- interleaved paths update Markov counts only for posterior-consistent edges;
- serialization round trips within `1e-12` and rejects invalid probabilities.

## Success Criteria

- **SC-001:** Sensor-clear-only traces contain zero `keep_on` on-to-off edges.
- **SC-002:** Confirmed graph departures clear the origin within the same
  inference cycle that release criteria pass.
- **SC-003:** Forced-forward predictions set `prelight_plausible` in the source
  event cycle and before destination evidence.
- **SC-004:** All two-occupant hypotheses conserve exactly two positions through
  at least 100 seeded interleavings, including join, split, and crossing traces.
- **SC-005:** Isolated and repeated single-source non-adjacent false positives
  produce zero activation authorizations while occupants are accounted for.
- **SC-006:** The posterior normalizes within `1e-12`; normal scenario pruning
  drops no more than `0.0001` probability mass.
- **SC-007:** Restart traces produce zero synthetic activation edges, zero false
  keep-on clear edges, and no restoration of expired leases.
- **SC-008:** Every public transition includes a machine-readable policy reason
  and at least one evidence or authoritative-command reference.
- **SC-009:** Replay of identical input produces byte-for-byte identical public
  timelines, canonical posterior ordering, and diagnostic reasons.
- **SC-010:** The full pre-overhaul test suite remains passing or has an explicit
  assertion migration preserving the original behavioral intent.
- **SC-011:** The canonical two-trigger room automation requires no raw motion,
  confidence threshold, timeout, adjacency, or recovery template.

## Assumptions and Decisions

- The configured occupant count is authoritative. Count `0` means nobody is
  inside; it must no longer mean unlimited tracking.
- Missing movement events are possible, so non-adjacent relocation has a low
  prior but is not impossible.
- False-offs are more disruptive than delayed turn-offs; ambiguity retains the
  last trusted keep-on latch.
- Anonymous occupants are exchangeable. Directional path continuity is retained
  only while evidence distinguishes it; permanent person identity is not
  inferred.
- Shared environmental transition learning remains useful. Person-specific
  learning requires a separate identity source and is out of scope.
- The initial production target is exact inference for one or two occupants;
  deterministic retained-mass pruning bounds larger configurations.
- Manual light overrides are outside the tracker. Recovery activation is tied to
  reacquiring occupancy, not observing physical light state.
- The new filter ships behind shadow diagnostics before it controls entities.

## Readiness

This document is the development handoff. Implementation starts with Phase 0,
then proceeds in task order unless a phase gate exposes a model defect. The
public three-entity contract is frozen; the replaceable surface is the internal
inference core and its policy projection.
