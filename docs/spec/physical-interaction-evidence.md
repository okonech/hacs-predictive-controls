# Physical Human-Interaction Evidence

**Status:** Implemented and repository-validated; operational rollout observation deferred  
**Affected layers:** map/schema, runtime normalization, physical episodes, zone belief, traversal, anonymous support, count, policy, persistence, diagnostics, deployment configuration  
**Authority:** [SPECIFICATION.md](../../SPECIFICATION.md), especially `REQ-GOAL-001` through `REQ-GOAL-009`, `REQ-MAP-001` through `REQ-MAP-005`, `REQ-EVID-001` through `REQ-EVID-011`, `REQ-BELIEF-001` through `REQ-BELIEF-010`, `REQ-TRAV-001`, `REQ-TRAV-002`, `REQ-TRAV-006`, `REQ-COUNT-001`, `REQ-COUNT-005`, `REQ-COUNT-007`, `REQ-COUNT-008`, `REQ-POLICY-001`, `REQ-POLICY-002`, `REQ-POLICY-005`, `REQ-STATE-001` through `REQ-STATE-010`, `REQ-PERF-001` through `REQ-PERF-004`, and `REQ-GOV-001` through `REQ-GOV-006`  
**Incident:** `INC-2026-08-22-master-bathroom-physical-press`

## Objective

Treat a mapped local physical key press as conclusive but finite evidence that a
human is in that key's zone. A fresh press must acquire that zone in the same
model update when authoritative count is positive, then follow ordinary stable
clear, graph-conditioned decay, threshold, and release-dwell behavior.

For the retained incident, Predictive Controls and its simple Home Assistant
consumer had turned the master-bathroom light off. At
`2026-08-22T07:28:36.046Z`, 4.082 seconds later, the physical switch emitted
`event.master_bathroom_master_bathroom_light_motion_scene_002`. The required
public behavior is an immediate `binary_sensor` active `off -> on` edge for the
master-bathroom zone. The light's state is neither an input nor corroboration.

## Verified Current State

The repository already separates the relevant layers:

- [`event_from_entity`](../../custom_components/predictive_controls/events.py)
  normalizes mapped Home Assistant entity updates before the target engine.
- [`PhysicalEpisodes`](../../custom_components/predictive_controls/zone_model/episodes.py)
  owns per-node episode identity, duplicate/stale handling, stable clear, and
  health state.
- [`ZoneBeliefFilter`](../../custom_components/predictive_controls/zone_model/filter.py)
  owns finite log-odds belief and context-specific elapsed decay.
- [`TraversalFrontier`](../../custom_components/predictive_controls/zone_model/traversal.py)
  owns bounded anonymous authorization and token provenance.
- [`AnonymousSupportTracker`](../../custom_components/predictive_controls/zone_model/supports.py)
  projects accepted confirmed-equivalent provenance into count-only support.
- [`ZoneModelEngine`](../../custom_components/predictive_controls/zone_model/engine.py)
  orders episode, belief, traversal, support, count, and policy work.
- [`ZonePolicy`](../../custom_components/predictive_controls/zone_model/policy.py)
  owns public acquisition, hysteresis, refresh, release dwell, and audit.
- [`serialize_target_state`](../../custom_components/predictive_controls/zone_model/persistence.py)
  persists strict `zone-belief-v4` state under a map/calibration fingerprint.

Before this proposal, the committed normalizer accepted only `on`, `off`,
`unknown`, and `unavailable`; Home Assistant event-entity timestamp states were
dropped during live handling and neutralized at startup. The target sensor state
type did not admit a pulse. Therefore the physical event could not reach belief
or policy even though it distinguished a local key press from remote output
changes.

The provisional patch adds interaction aliases, a `pressed` pulse, immediate
local authorization, a finite belief ceiling, normal clear/decay, persistence,
tests, and two master-bathroom deployment nodes. This document does not treat
those choices as correct merely because they exist.

The upper-level floor plan verifies that the master bathroom is an ensuite
reached through the walk-in closet. The deployment map's reciprocal adjacency
between each bathroom interaction node and `master_bedroom_closet` reflects that
physical route. Both interaction nodes inherit the sticky `master_bathroom`
zone behavior and resolve to the shared `stay_presence` profile.

### Evidence Provenance

| Claim                                                                                                                                      | Provenance                                                                            | Status                                                                          |
| ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| Predictive Controls and its consumer turned the bathroom light off, then scene 002 fired 4.082 seconds later at `2026-08-22T07:28:36.046Z` | Retained live Home Assistant incident evidence                                        | Factual incident input; immutable after regression reproduction                 |
| Scene event means local physical interaction while output state may be remote                                                              | Home Assistant entity semantics and device mapping retained during incident diagnosis | Approved product interpretation for this design                                 |
| Filter, episode, traversal, support, count, policy, and persistence ownership                                                              | Current repository code linked above                                                  | Verified current architecture                                                   |
| Bathroom-to-closet adjacency                                                                                                               | Upper-level labeled floor plan and deployment map                                     | Verified physical/deployment fact                                               |
| Both deployment nodes resolve to `stay_presence`                                                                                           | Zone metadata plus executable `profile_assignment_for_node()` result                  | Verified repository behavior                                                    |
| `LOG_ODDS_LIMIT = 30.0`, unit reliability, and local confirmed-equivalent support are the desired contracts                                | User decision plus this proposal                                                      | Normative only after authority amendment                                        |
| Production release times after varied human behavior                                                                                       | Not measured by this incident                                                         | Must not be claimed; shared profile behavior and tests define only model timing |

## Problem Statement

Motion and presence sensors can miss a stationary person. A physical local key
press is direct human interaction, but the actuator's resulting state is not:
voice, UI, automation, and remote commands can change a light or fan without a
person in the room. The model needs an input category that preserves this
distinction and still releases after the person leaves.

A belief-only pulse is insufficient. Outward evidence and restart equivalence
require an episode and bounded token lineage. A permanently asserted synthetic
sensor is also wrong because an event entity has no enduring physical state and
would prevent ordinary release.

## Scope

This design includes:

- mapped `event.*` physical scene/key event entities;
- live pulse normalization and startup neutralization;
- interaction-only physical nodes and one episode per distinct occurrence;
- finite maximum local belief and immediate local acquisition;
- one bounded traversal token and count-support lineage;
- ordinary stable clear, outward-conditioned decay, threshold, and dwell;
- strict persistence, restore advancement, audit, and diagnostics;
- master-bathroom fan and light physical-control deployment mappings; and
- exact incident, inverse, restart, and bounded-state tests.

## Non-Goals

- Reading `light.*`, `switch.*`, fan, relay, output, automation, voice, UI, or
  service-call state as occupancy evidence.
- Inferring which person pressed a key or how many people are in the zone.
- Holding occupancy indefinitely after a press.
- Adding room-, entity-, device-model-, scene-number-, or incident-specific
  behavior to the Python model.
- Changing shared on/off thresholds, release dwell, or decay constants from one
  incident.
- Moving inference or timeout logic into Home Assistant automation YAML.
- Treating a timer callback, retained startup timestamp, duplicate callback, or
  repeated alias as a new press.
- Deploying or reloading the integration or Home Assistant configuration as part
  of repository acceptance.

## Proposed Authority Changes

The implementation requires the following amendments to `SPECIFICATION.md`:

1. Extend the input contract and `REQ-EVID-011` with mapped event pulses,
  interaction-only nodes, occurrence identity, and startup neutrality.
2. Extend `REQ-BELIEF-010` and `REQ-POLICY-001` with the finite ceiling,
  generation-idempotency, explicit local authorization, normal clear/decay,
  and no actuator-state inference.
3. Extend `REQ-TRAV-002` and `REQ-COUNT-008` so one fresh trustworthy
  `local_interaction` token is confirmed-equivalent for one count-only support,
  without granting support belief, traversal, prediction, or policy authority.
4. Clarify `REQ-COUNT-001`, `REQ-COUNT-005`, and `REQ-COUNT-007`: count zero
  suppresses interaction acquisition, while positive count neither delays it
  nor forces same-zone multiplicity or exact placement.
5. Extend `REQ-STATE-001`, `REQ-STATE-003`, `REQ-STATE-005`, `REQ-STATE-008`, and
  `REQ-STATE-010` with interaction enum validation, no likelihood replay,
  compatible-v4 restore, atomic rejection, and older-reader cold bootstrap.
6. Reconcile `REQ-MAP-005`, `REQ-BELIEF-009`, and `REQ-PROFILE-008`: a
  conclusive interaction node must declare reliability exactly `1.0`; a source
  that cannot make that claim must use an ordinary reliability-tempered sensor
  contract instead.
7. Extend `REQ-PERF-001` so local interaction uses the same zero-wait decision
  and publication-scheduling budget as other immediate authorizations.
8. Update Section 16 acceptance and Section 19 conformance in the same change
  under `REQ-GOV-006`.

This design record is subordinate to those numbered requirements.

## Invariants

1. **Physical-only source:** Interaction aliases use the `event` domain and a
   signal type equal to `interaction` or beginning `interaction_`.
2. **Isolated node:** A physical node contains only interaction aliases or only
   state aliases. Mixing them is invalid because a pulse cannot overwrite a
   motion/presence episode.
3. **Trusted classification:** Every interaction-only node has reliability
   exactly `1.0`. Lower reliability is rejected at map validation rather than
   silently ignored by the finite-ceiling update.
4. **One occurrence, one episode:** Each distinct event occurrence starts one
   new generation. Equal-time duplicate and older input add no evidence.
5. **Startup neutral:** A retained event-entity timestamp observed during
   bootstrap becomes `unknown`; it never becomes `pressed`, starts no episode,
   and emits no public edge.
6. **Finite maximum:** One accepted pulse sets zone log odds to
   `LOG_ODDS_LIMIT = 30.0`, not literal probability one. The generation ID, not
   bounded diagnostic history, makes the update idempotent.
7. **Immediate acquisition:** With authoritative count greater than zero, the
   fresh trustworthy interaction episode receives one explicit
   `local_interaction` authorization and is evaluated for acquisition in the
   same update. It requires no prior movement token or pending dwell.
8. **Count zero authoritative:** With count zero, the episode may be retained for
   health/order diagnostics, but belief remains at the empty baseline, no token
   or support survives, and public `active` remains off.
9. **Ordinary release:** The interaction episode starts in `clearing` at its
   occurrence time. At the shared profile's stable-clear deadline it applies one
   normal weak clear. Compatible outward evidence chooses
   `cleared_with_outward`; otherwise `cleared_without_outward` applies. Both
   converge to a finite baseline and eventually satisfy ordinary release dwell.
10. **Bounded lineage:** One interaction episode creates at most one traversal
    token and one confirmed-equivalent count support. Neither is person identity.
11. **Count-only support:** Interaction-derived support may participate in
    ordinary count-conflict eligibility, but cannot write belief, authorize
    traversal/policy/prediction, clone on a split, or force exactly `N` zones.
12. **Same-zone ambiguity:** Multiple physical switches or occupants in one zone
    may produce separate episodes, but settled support coalesces by zone and
    never claims same-zone occupant multiplicity.
13. **Newest generation wins:** Stable clear from an older interaction node or
    generation cannot clear a newer same-zone generation's belief.
14. **Health neutrality:** `unknown` and `unavailable` are not presses or clear
    evidence. After live operation begins, either health state on any interaction
    alias immediately marks that interaction node unavailable and invalidates its
    token, pending context, and support without fabricating departure. There is
    no all-alias health quorum. Startup neutralization remains a bootstrap-only
    path and creates no authority to invalidate.
15. **Deterministic ordering:** At one timestamp, due stable-clear/token/policy
    frontiers advance before the external pulse. The new pulse then creates its
    generation and may reacquire/refresh once.
16. **Restart equivalence:** Restore never reapplies interaction likelihood.
    Uninterrupted and restored execution have identical episode, belief, token,
    support, policy, and release frontiers.
17. **Bounded diagnostics:** Pulse handling adds no unbounded history. Existing
    episode, token, support, audit, and contribution limits remain authoritative.
18. **Simple consumer:** Home Assistant automations continue to consume only the
    public `active` edge; they do not inspect the physical event directly.

## Alternatives

### A. Infer From Light Or Fan Output

Rejected. Outputs can change remotely and would create false occupancy from
automation, voice, UI, restore, or service calls. It also creates feedback from
the controlled actuator into the controller.

### B. Treat Event Entity State As A Held Binary Sensor

Rejected. Home Assistant event entity state is an occurrence timestamp, not a
physical assertion. Holding it would prevent clear and make restart replay an
old press.

### C. Apply Belief Only Without Episode Or Token

Rejected. It cannot preserve idempotent occurrence identity, outward movement,
count-support provenance, stable clear, or restart equivalence.

### D. Set Literal Probability One Or Hold Indefinitely

Rejected. Infinite log odds cannot decay under finite elapsed transitions and
would violate numerical stability and eventual release.

### E. Reuse Motion/Presence Node Aliases

Rejected. A pulse lifecycle would overwrite a held state episode and make alias
deduplication order-dependent.

### F. Finite Interaction Episode With Local Authorization

Selected. It establishes a strong local fact while preserving existing graph,
count, decay, persistence, and public-policy boundaries.

## Input And Map Contract

`NodeConfig.from_mapping()` recognizes `interaction` and `interaction_*` signal
types. If any entity on a node is an interaction signal, all entities on that
node must be interaction signals, every entity ID must begin `event.`, and
resolved reliability must equal `1.0`.

Interaction-only stay nodes use the normal capability/zone profile assignment.
They do not introduce an interaction-specific decay profile. The deployment
nodes inherit `master_bathroom` sticky behavior and therefore use
`stay_presence`. Adjacency must remain reciprocal and reflect the closet-to-
bathroom doorway verified by the floor plan.

At runtime:

- a live mapped interaction state other than `unknown`/`unavailable` normalizes
  to `pressed` at the callback's occurrence time;
- startup/bootstrap normalization converts the retained state to `unknown`;
- health states remain `unknown`/`unavailable`; and
- unmapped or non-interaction event entities do not become pulses.

## State Machine And Ordering

```text
startup timestamp -> unknown -> baseline/unavailable (no pulse)
live occurrence    -> pressed -> clearing interaction episode
duplicate/stale    -> ignored and diagnosed
clearing deadline  -> clear + one stable-clear effect
clear + outward    -> cleared_with_outward decay
clear alone        -> cleared_without_outward decay
belief <= off gate through dwell -> inactive
```

For an accepted live pulse at event time `t`:

1. Advance all due frontiers through `t`, including an older stable clear.
2. Create a new interaction episode generation with `started_at=t`,
   `clear_started_at=t`, and the shared profile's finite deadlines.
3. Set the zone belief to `LOG_ODDS_LIMIT` once for that generation.
4. Create one explicit authorized `local_interaction` authorization.
5. Issue one bounded token with one-node path and confirmed-equivalent strength.
6. Evaluate public policy and schedule the supported local edge before unrelated
   whole-house support/count materialization.
7. Commit the accepted in-memory episode, belief, token, support, count, policy,
  and audit transition even if the publication callback fails, under the
  existing accepted-observation transaction contract.
8. On normal completion, schedule persistence through the existing one-second
  delayed atomic save path. A callback exception may prevent that scheduling;
  the in-memory transition remains committed and the next successful update or
  normal shutdown saves it.

If a same-zone newer generation already owns the filter when an older stable
clear arrives, the older clear is ignored. At the exact newer pulse time, due
older frontiers run first and the new pulse then becomes authoritative.

## Belief, Traversal, Count, And Policy Contracts

The finite ceiling is

$$
q_z = \frac{1}{1 + e^{-30}},
$$

which is strictly below one and can decay. The interaction update does not also
apply ordinary positive likelihood or the supported-arrival matrix.

`local_interaction` authorization is an explicit traversal result even though it
requires no source token. This keeps acquisition audit and persistence aligned
with every other evidence-acquired active state. Its issued token has the target
node as its one-node path, bounded profile validity, no person identity, and
confirmed-equivalent strength solely for anonymous count support.

For count `N=1` or `N=2`, the pulse acquires locally without count-conflict
delay. Count support remains one per settled zone after coalescence. For `N=0`,
the empty-house path dominates and clears belief, tokens, support, predictions,
and public active state.

While inactive, one pulse may emit exactly one `acquired` edge. While already
active, a distinct pulse may emit at most one `refreshed` event under the normal
episode deduplication rule. Duplicate/stale/startup/restore input emits neither.
Release uses the existing profile off threshold and confirmation dwell without
an interaction-specific floor.

## Persistence, Compatibility, And Rollback

The implementation keeps `zone-belief-v4` because interaction state adds only
enum values to existing bounded record shapes; it adds no required persisted
field or alternate record layout. This is acceptable only if strict generic
decoders and cross-record validators reject every unknown or inconsistent enum
atomically. The map/profile fingerprint covers the new physical nodes and
profile mapping.

- Pre-interaction v4 snapshots with compatible maps restore normally.
- Interaction episodes, contributions, token provenance, support bindings,
  active reason, and audit fields use existing generic record decoders plus
  immutable-type and engine cross-validation; no permissive string fallback is
  allowed.
- Restore advances existing deadlines once and never calls the observation
  update for historical interaction evidence.
- Malformed interaction provenance rejects the candidate atomically and cold
  bootstraps from current count/sensor snapshots without a public edge.
- Downgrading to a reader that does not recognize interaction enum values may
  reject inference state and cold bootstrap. It must not modify the map, entity
  registry, learned route data, or user configuration.
- A crash before delayed save restores the last complete snapshot; the lost
  pulse is not inferred from the retained Home Assistant event timestamp. This
  deliberately chooses a bounded false negative after a crash over replaying a
  possibly old physical action.

### Operational Frontiers

- **Before stable clear:** A saved `clearing` episode restores with its original
  clear deadline. Restore before the deadline preserves it; restore at or after
  the deadline applies stable clear exactly once.
- **At stable clear:** Timer-first ordering applies the old stable clear before
  a new pulse at the same timestamp. The new generation then sets the finite
  ceiling and remains authoritative.
- **Before release dwell:** Restored belief and pending release retain their
  original event-time frontier. Restart cannot extend the dwell.
- **At release dwell:** Restore or uninterrupted advancement emits the same
  ordered release result without replaying the pulse.
- **After a newer same-zone pulse:** An older node or generation may complete its
  clear, but cannot change the filter unless its episode ID is still the zone's
  current generation.
- **Live health loss:** `unknown` or `unavailable` on any interaction alias
  invalidates that node's active/retained authority and count support before a
  later episode may use it. A later physical pulse starts a fresh generation; it
  does not revive the invalidated token.
- **Out-of-order delivery:** An event occurrence older than the engine frontier
  returns `stale` and changes no deadline, contribution, token, support, policy,
  prediction, learning, audit edge, or persistence payload.
- **Publication failure:** The accepted in-memory model transition and deferred
  audit commit before the callback error is reported. No prediction learning is
  committed from the failed publication. Durability follows the next successful
  scheduled or final save; an intervening crash follows the previous bullet's
  false-negative rule.

## Diagnostics And Failure Behavior

Accepted pulses expose bounded episode kind `interaction`, belief contribution
`local_interaction`, traversal reason/provenance `local_interaction`, policy
reason `local_interaction`, and ordinary support provenance. Diagnostics must
retain event and processing time separately and never label the actuator state
as evidence.

Invalid mixed-domain nodes, non-event interaction aliases, or non-unit
interaction reliability block map construction. Invalid persisted enum or
cross-record provenance rejects restore atomically. Publication failure reports
the callback error after committing the accepted in-memory model transition;
validation failure commits nothing. A live health state on one interaction alias
invalidates node authority without waiting for sibling scene aliases.

## Implementation Plan

### Phase 0: Evidence And Baseline

- Preserve exact incident time, event entity, prior public-off state, and
  expected public acquisition in the retained regression.
- Demonstrate committed pre-change behavior does not produce the public edge for
  the mapped event timestamp.
- Record current full Python, Ruff, mypy, frontend, benchmark, and map-validation
  baselines.

**Exit:** The exact regression fails for the missing public edge on committed
behavior, factual inputs are frozen, and baseline commands are recorded.

### Phase 1: Authority And Map Contracts

- Amend `SPECIFICATION.md` with the approved pulse, reliability, support,
  count-zero, persistence, and conformance contracts.
- Add map/type positive and mutation-negative tests before orchestration work.
- Reject mixed nodes, actuator domains, and non-unit interaction reliability.

**Exit:** Authority is internally consistent and map/type boundaries pass.

### Phase 2: Episode, Belief, Traversal, And Policy

- Normalize live/startup states and add interaction-only episode generations.
- Apply the finite ceiling idempotently by current generation.
- Add immediate authorization, bounded token/support provenance, and ordinary
  policy acquisition/refresh/release behavior.
- Preserve timer-first ordering and newer-generation ownership.

**Exit:** Focused positive, inverse, same-zone, count, deadline, and callback
tests pass with `--no-cov`; touched Python files pass Ruff.

### Phase 3: Persistence And Diagnostics

- Extend strict v4 enum validation and cross-record restore checks.
- Prove uninterrupted/restore equivalence before, at, and after clear/release
  frontiers.
- Prove crash-before-save and older-reader cold-bootstrap behavior.

**Exit:** Interaction persistence mutation and restart matrices pass atomically.

### Phase 4: Deployment Mapping And Runtime

- Add separate fan and light physical-control nodes using verified `event.*`
  scene entities and reciprocal closet adjacency.
- Prove startup retained timestamps remain neutral and a later live occurrence
  acquires.
- Validate YAML and `PredictiveMap` semantics; do not change automation YAML.

**Exit:** The final deployment map parses, resolves both nodes to
`stay_presence`, and contains no actuator entity as interaction evidence.

### Phase 5: Adversarial And Performance Validation

- Run the complete test matrix and repository gates.
- Add a `local_interaction` fast-path scenario to the real runtime/publication
  benchmark using a synthetic interaction node in an existing benchmark zone.
  Require 100/100 acquisitions, explicit `local_interaction` qualification,
  100/100 public writes, p99 at most 5 ms, and max below 10 ms.
- Compare the 100-event benchmark against the recorded pre-benchmark-extension
  baseline under the same host, Python, map, count, and trace profile. Apply the
  existing 20% review trigger and absolute budgets; do not claim improvement
  from unmatched runs.
- Verify bounded token/support/audit limits and regenerate tracked performance
  evidence only after the standalone benchmark passes.
- Perform fresh independent conformance review against this document and
  `SPECIFICATION.md`.

**Exit:** All repository acceptance criteria pass with no unresolved authority,
correctness, persistence, or performance finding.

### Executable Gates

Run from the Predictive Controls repository root:

```bash
.venv/bin/python -m pytest -q --no-cov tests/test_events.py tests/test_model.py tests/test_runtime.py tests/test_zone_model_episodes.py tests/test_zone_model_filter.py tests/test_zone_model_engine.py tests/test_zone_model_traversal.py tests/test_zone_model_persistence.py tests/test_zone_model_public_contract.py
.venv/bin/python -m ruff check custom_components/predictive_controls tests benchmarks
.venv/bin/python -m mypy
.venv/bin/python -m pytest -q
npm run test:frontend
npm run build:frontend
.venv/bin/python benchmarks/occupancy_performance.py --events 100 --output PERFORMANCE_RESULTS.json
git diff --check
```

Validate the deployment map from the homelab repository with
`home-assistant/scripts/validate-yaml.sh home-assistant/predictive-controls-map.yaml`
and construct `PredictiveMap` from the parsed file. Temporary baseline benchmark
evidence remains outside both worktrees; accepted current performance evidence
is the tracked `PERFORMANCE_RESULTS.json`.

## Test Matrix

Required positive and inverse cases:

- exact `2026-08-22T07:28:36.046Z` incident pulse acquires from public off;
- accepted belief is finite and exactly `LOG_ODDS_LIMIT`;
- compatible closet evidence selects outward decay and releases earlier;
- no outward evidence selects slower decay but eventually releases;
- count zero suppresses acquisition and clears token/support state;
- counts one and two both permit immediate local acquisition;
- two same-zone switches create distinct episodes but at most one settled
  same-zone support;
- an older switch's clear cannot withdraw a newer same-zone pulse;
- a pulse exactly at an older clear deadline follows timer-first ordering;
- equal-time duplicate, older event, repeated callback, and alias replay add no
  evidence/token/support/refresh;
- startup retained timestamp is neutral; the next live timestamp acquires;
- `unknown` and `unavailable` never normalize to `pressed`;
- live `unknown` or `unavailable` on one of several interaction aliases removes
  that node's token/support without waiting for all sibling aliases;
- `pressed` on a non-interaction alias is invalid;
- mixed interaction/state node, `light.*`/`switch.*` alias, and reliability below
  `1.0` fail map validation;
- remote/voice/UI output changes cannot enter the interaction path;
- current-generation idempotency survives contribution eviction and restore;
- immutable type validation rejects malformed interaction effects;
- malformed persisted interaction episode/contribution/token/support/policy/audit
  provenance rejects restore atomically;
- uninterrupted and restored clear/release outcomes are byte-equivalent;
- stale input after restore mutates nothing;
- publication callback failure commits the same accepted in-memory interaction
  snapshot and audit as successful publication but may defer persistence until
  the next successful/final save; pre-commit validation failure commits nothing;
- count conflict cannot delay a new interaction pulse, and interaction support
  cannot directly release or write another zone's belief;
- token/support/contribution/audit cardinality remains within existing bounds;
- standalone performance output contains a passing `local_interaction` fast path
  with 100 samples and the declared latency/publication/qualification gates;
  and
- no automation YAML changes are required.

### Requirement Proof Matrix

| Contract                                                                  | Required executable proof                                                                                                                       |
| ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Exact public incident, finite ceiling, outward and missed-outward release | `test_inc_2026_08_22_0728z_physical_press_acquires_then_decays_normally`                                                                        |
| Count zero and positive count one/two                                     | `test_physical_press_does_not_bypass_authoritative_count_zero`; `test_interaction_count_two_acquires_without_conflict_delay`                    |
| Live/startup/health normalization                                         | `test_event_from_entity_normalizes_live_interaction_but_not_startup_state`; `test_runtime_start_does_not_replay_retained_interaction_timestamp` |
| Physical-only map, isolated aliases, unit reliability                     | `test_interaction_nodes_cannot_mix_state_entities_or_actuator_domains`; `test_interaction_nodes_require_unit_reliability`                       |
| Episode identity, duplicate/stale, per-alias health                       | `test_interaction_pulses_deduplicate_replay_but_accept_new_scene_edges`; `test_interaction_health_state_invalidates_single_alias_authority`     |
| Finite-ceiling generation idempotency after bounded-history loss          | `test_interaction_idempotency_uses_generation_after_restore`                                                                                    |
| Same-zone newest-generation ownership and exact deadline ordering         | `test_older_interaction_clear_does_not_withdraw_newer_same_zone_pulse`; `test_interaction_at_clear_deadline_applies_timer_then_new_generation`  |
| Explicit authorization, support coalescence, and count-only isolation     | `test_interaction_authorization_requires_a_fresh_clearing_pulse`; same-zone engine assertions; existing support noninterference suite           |
| Atomic callback behavior                                                  | `test_interaction_publication_failure_commits_atomic_snapshot`; `test_publication_callback_deferral_discards_on_engine_validation_failure`      |
| Strict restore and uninterrupted equivalence                              | `test_interaction_episode_round_trips_and_releases_on_the_same_frontier`; interaction mutation cases in `test_zone_model_persistence.py`        |
| Immediate-path performance                                                | `test_target_benchmark_reports_required_bounded_metrics` plus standalone `PERFORMANCE_RESULTS.json` `local_interaction` trace                   |
| Deployment syntax, semantics, profile, and actuator exclusion             | `validate-yaml.sh`, `PredictiveMap.from_mapping`, profile-resolution assertion, and production-diff actuator scan                               |

## Performance, Rollout, And Rollback

Use [`benchmarks/occupancy_performance.py`](../../benchmarks/occupancy_performance.py)
with the existing deterministic reference map and a synthetic interaction node
added only inside fast-path measurement. This change adds constant-time
normalization plus work bounded by existing episode, token, support, filter, and
audit limits. It must not add an unbounded event history or an all-pairs scan.
The local-interaction path is an immediate authorization under `REQ-PERF-001`:
p99 decision latency is at most 5 ms, hard decision latency is below 10 ms at
count two, and scheduling the public write occurs in the same Home Assistant
event-loop update without blocking I/O. The retained performance JSON must name
`local_interaction` alongside every existing fast path; a benchmark that does
not exercise the pulse cannot satisfy this requirement.

Repository acceptance does not deploy Home Assistant. After release, observe at
least one physical press, one outward transition, one missed-outward gradual
release, and one restart before accepting operational rollout. Roll back on
false acquisition from output state, replayed startup presses, failure to
release, duplicate supports, restore loops, or latency-budget breach. Rollback
may cold-bootstrap inference state but must preserve map and user configuration.

Deploy the integration code before or atomically with the map. New code with the
old map is inert. Old code with the new map must continue to parse the map but
ignore unsupported event timestamp states; it cannot treat them as ordinary
positive sensor state. A map fingerprint change may cold-bootstrap inference
without synthetic movement or public edges. No automation reload or inference
state conversion is required. On rollback, leaving the interaction nodes in the
map is safe only if the older version is verified to ignore their live timestamp
states; otherwise remove only those map nodes before starting the older version.

## Acceptance Criteria

1. The exact incident regression fails on committed old behavior and passes
   after the generic change with an immediate public acquisition edge.
2. Only mapped trusted `event.*` interaction aliases can create a pulse.
3. One pulse applies finite maximum belief exactly once by generation.
4. Positive count authorizes immediately; count zero remains categorically
   empty; count never forces exact placement or same-zone multiplicity.
5. Outward evidence accelerates release, while missed outward evidence still
   releases through ordinary decay and dwell.
6. Interaction support is bounded, anonymous, count-only, coalesced by settled
   zone, and unable to affect belief/traversal/policy directly.
7. Startup, duplicate, stale, per-alias unavailable, equal-deadline,
  callback-failure, crash-window, and restart cases satisfy the test matrix.
8. v4 restore is strict, atomic, idempotent, and uninterrupted-equivalent.
9. The master-bathroom deployment map uses separate physical-only nodes,
   verified scene entity IDs, reciprocal closet adjacency, and `stay_presence`.
10. No light/fan/switch output state or automation YAML participates in
    inference.
11. Full Python tests retain 100% branch coverage; Ruff, strict mypy, frontend
    tests/build, benchmark, YAML, semantic map, and diff gates pass.
12. Fresh independent review finds no unresolved authority, correctness,
    persistence, deployment, or public-contract defect.

## Implementation Surfaces

Expected repository surfaces:

- `SPECIFICATION.md`
- `custom_components/predictive_controls/events.py`
- `custom_components/predictive_controls/model.py`
- `custom_components/predictive_controls/zone_model/types.py`
- `custom_components/predictive_controls/zone_model/profiles.py`
- `custom_components/predictive_controls/zone_model/episodes.py`
- `custom_components/predictive_controls/zone_model/filter.py`
- `custom_components/predictive_controls/zone_model/traversal.py`
- `custom_components/predictive_controls/zone_model/supports.py`
- `custom_components/predictive_controls/zone_model/count.py`
- `custom_components/predictive_controls/zone_model/policy.py`
- `custom_components/predictive_controls/zone_model/engine.py`
- `custom_components/predictive_controls/zone_model/persistence.py` only if
  existing generic decoding cannot validate new provenance
- `benchmarks/occupancy_performance.py` and
  `tests/test_occupancy_performance_benchmark.py`
- `PERFORMANCE_RESULTS.json` after the standalone benchmark passes
- focused normalization, map, episode, belief, traversal, engine, policy,
  persistence, runtime, and public-contract tests
- `home-assistant/predictive-controls-map.yaml` in the homelab repository

No automation file is an implementation surface.

## Tracking

| Phase                                     | Status   | Completed evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | Next executable step                                                                                            |
| ----------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| 0. Evidence and baseline                  | Complete | Hardened specification completed after exactly three adversarial passes. Detached commit `4b3f871` probe at `2026-08-22T07:28:36.046Z`: `normalized=None`, `public_active=False`, and the required acquisition assertion failed. Current 100-event count-two baseline: p99 `2.142180 ms`, max `2.152290 ms`, eight existing fast paths.                                                                                                                                                                                                                                                                 | None.                                                                                                           |
| 1. Authority and map contracts            | Complete | `SPECIFICATION.md` reconciled across evidence, belief, traversal, count, policy, profile, state, performance, acceptance, and conformance. Interaction physical-domain/isolation/unit-reliability map tests pass: 39/39 in `tests/test_model.py`; touched-file Ruff passes.                                                                                                                                                                                                                                                                                                                             | None.                                                                                                           |
| 2. Episode, belief, traversal, and policy | Complete | Generation idempotency survives contribution eviction/restore; any live interaction-alias health state invalidates token/support authority without releasing; count-two, same-zone coalescence, exact-deadline timer ordering, callback failure, traversal, policy, and exact public regressions pass. Focused suite: 153 passed; touched-file Ruff passes.                                                                                                                                                                                                                                             | None.                                                                                                           |
| 3. Persistence and diagnostics            | Complete | Strict v4 restore rejects valid-enum fabrications across interaction episode, contribution, token, support, active-policy, and audit records. Uninterrupted and restored snapshots match before, at, and after stable clear and release. Full persistence/type slice: 148 passed; touched-file Ruff passes.                                                                                                                                                                                                                                                                                             | None.                                                                                                           |
| 4. Deployment mapping and runtime         | Complete | Live/startup normalization tests pass: retained timestamp is neutral and later live occurrence acquires. Homelab YAML parse/diff validation passes. Semantic parse yields 19 nodes; both separate interaction nodes resolve to `stay_presence`, use unit-reliability `event.*` aliases, and are reciprocally adjacent to the closet. Production diff has zero actuator-evidence additions and zero automation changes.                                                                                                                                                                                  | None.                                                                                                           |
| 5. Adversarial and performance validation | Complete | Python: 580 passed at 100% statement/branch coverage. Ruff and strict mypy pass. Frontend: 29 passed and production build succeeds. Standalone benchmark passes nine fast paths; `local_interaction` has 100/100 acquisition, qualification, and publication, p99 `2.147295 ms`, max `2.387612 ms`. Count-two core baseline comparison: p99 `+0.18%`, max `+13.17%`, below the 20% review trigger. Independent review found no behavioral or contract defect; its stale Section 19 finding was reconciled. Homelab YAML, semantic map/profile, actuator exclusion, and no-automation-change gates pass. | Observe post-deployment diagnostics separately; repository acceptance does not deploy or reload Home Assistant. |