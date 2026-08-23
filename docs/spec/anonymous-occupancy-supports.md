# Anonymous Occupancy Supports

**Status:** Implemented design record; independently reviewed
**Affected layers:** traversal provenance, anonymous support, count conflict, persistence, diagnostics  
**Authority:** [SPECIFICATION.md](../../SPECIFICATION.md), especially `REQ-GOAL-009`, `REQ-TRAV-001` through `REQ-TRAV-013`, `REQ-COUNT-001` through `REQ-COUNT-011`, `REQ-POLICY-003`, `REQ-STATE-001` through `REQ-STATE-010`, and `REQ-GOV-001` through `REQ-GOV-006`
**Incident:** `INC-2026-08-20-stale-gym-assertion`

## Objective

Allow authoritative positive household count to diagnose a stale asserted stay sensor when all occupants are already accounted for by independent, graph-confirmed evidence, even after one occupant has stopped moving and ordinary traversal tokens have expired.

For the retained incident, the intended public behavior is:

1. Shaila Office remains active from a confirmed arrival plus continuing trustworthy local evidence and no plausible departure.
2. A second anonymous support remains continuous through the confirmed Foyer/Dining/Kitchen route and its continuation through the stairs into Alex Office.
3. With authoritative count two, those two independent supports start a count contradiction against the unsupported continuously asserted Gym sensor.
4. After Gym's normal stay-profile conflict dwell, Gym is health-degraded; count does not switch Gym off directly. Normal degraded-belief decay remains authoritative. In the retained fixture Gym was never publicly acquired, so its belief falls below the off threshold without a fabricated `released` edge. For an already-active equivalent, the later `INC-2026-08-23` authority repair in `asserted-stay-count-conflict-release-authority.md` vetoes public release while the same stay episode remains count-degraded or inside stable-clear confirmation.

## Verified Implementation State

The implementation intentionally separates occupancy belief, traversal, anonymous count support, count conflict, and policy:

- [`ZoneBeliefFilter`](../../custom_components/predictive_controls/zone_model/filter.py) retains graph-local room belief after stable clear and accelerates decay only when bounded outward context exists.
- [`TraversalFrontier`](../../custom_components/predictive_controls/zone_model/traversal.py) issues anonymous, finite tokens. Unsupported stay episodes may bootstrap only within profile timing; expired tokens cannot authorize unrelated arrivals.
- [`AnonymousSupportTracker`](../../custom_components/predictive_controls/zone_model/supports.py) retains at most `PRODUCT_MAX_OCCUPANTS` count-only lineages and bounded token bindings without feeding support state back into traversal, belief, prediction, learning, or policy acquisition.
- [`CountConflictTracker`](../../custom_components/predictive_controls/zone_model/count.py) consumes sorted independent supports. A stale asserted stay target is degraded only after at least `N` outside supports persist through its release dwell.
- [`ZoneModelEngine._apply_count_conflicts`](../../custom_components/predictive_controls/zone_model/engine.py) applies count conflict as sensor-health degradation. Count does not write zone belief or public `active` directly.
- [`serialize_target_state`](../../custom_components/predictive_controls/zone_model/persistence.py) persists strict `zone-belief-v4` state atomically with a map/calibration fingerprint; conservative v3 import invents no support.

The retained production evidence establishes:

- Shaila Office was graph-authorized at `2026-08-20T17:00:41.725395Z`, refreshed locally, and had no observed compatible outward sequence before the Gym conflict window.
- Gym asserted at `17:06:39.497066Z`; its unsupported bootstrap expired before later Dining/Foyer activity.
- A distinct route became confirmed by Kitchen at `17:09:13.675459Z` and continued through Bottom Staircase, Top Staircase, and Alex Office at `17:09:59.684850Z`.
- The committed count model forgot Shaila as count support after traversal expiry, so no count conflict was recorded against Gym.

The exact public regression is [`test_inc_2026_08_20_stale_gym_assertion_releases_normally`](../../tests/test_zone_model_public_contract.py). Its factual inputs are immutable after reproduction under `REQ-GOV-005`; implementation-specific support assertions may be added only as separate focused tests.

The rejected stationary-anchor prototype remains historical design evidence only. Its structured fields have no persistence or diagnostic compatibility status; one-release ID-array aliases are the only retained public compatibility surface.

## Problem Statement

Traversal context answers whether two fresh events may be one movement. It is correctly short-lived. Zone belief answers whether a zone remains occupied. It deliberately carries no anonymous movement lineage. Count conflict therefore has no evidence type for a graph-confirmed occupant who settled in a stay zone and remained locally credible after traversal expiry.

Extending traversal windows would conflate occupancy duration with movement continuity and let old room events authorize unrelated later movement. Directly subtracting probability from Gym based on remote activity would bypass the established health-conflict and release policy, double-count correlated evidence, and make unrelated events write local belief. The missing capability is bounded anonymous count support that can be settled without becoming person identity or traversal authority.

## Scope

This implemented design adds an internal anonymous occupancy-support state machine used only by count-conflict evaluation and diagnostics.

It includes:

- creation from confirmed traversal provenance;
- exactly one current state and at most one settled endpoint per support;
- source-set propagation along accepted authorization provenance;
- conservative coalescing at ambiguous same-zone endpoints;
- count-conflict integration and continuous dwell identity;
- schema-versioned persistence and exact restore validation;
- retained incident, inverse, boundary, restart, and performance evidence.

## Non-Goals

- Identifying people or assigning named occupants to rooms.
- Solving an exact whole-home assignment or forcing exactly `N` active zones.
- Using support to authorize traversal, acquisition, prediction, or learning.
- Replacing graph-local zone belief or public hysteresis.
- Treating a current `active` bit, high belief alone, or an isolated sensor assertion as support.
- Extending profile traversal/bootstrap windows for this incident.
- Tuning room-specific thresholds or special-casing Gym, Shaila Office, Alex Office, or any entity ID.

## Applied Authority Changes

The implementation was preceded by these amendments to `SPECIFICATION.md`:

- Extend `REQ-COUNT-003` from strong tracked fronts to independent anonymous occupancy supports.
- Refine `REQ-COUNT-008` to define support lineage, coalescing, one settled endpoint, and topology-preserving identity.
- Refine `REQ-COUNT-009` so persistent outside occupancy supports may trigger the existing health-degradation path.
- Add `REQ-COUNT-011` for the support state machine and cancellation rules.
- Amend `REQ-TRAV-002`, `REQ-TRAV-006`, and `REQ-TRAV-008` to expose which accepted source-token set authorized a target without granting the count layer authority to alter traversal.
- Amend `REQ-STATE-001`, `REQ-STATE-003`, `REQ-STATE-005`, `REQ-STATE-008`, and `REQ-STATE-009` for the new schema, source-token mappings, and restore behavior.
- Amend diagnostics requirements for support transitions and conflict provenance.

This design record is not itself authority.

## Invariants

1. **Anonymous:** A support ID is opaque model provenance, never a person, device tracker, household member, or durable named owner.
2. **Count-only:** Supports affect only count-conflict eligibility, health diagnostics, and explanations. They never authorize an arrival or write belief/public state directly.
3. **Evidence-derived:** A support begins only when traversal accepts a stay-target token with confirmed strength: three distinct sequential adjacent physical-node episodes or a reviewed boundary/missed-edge equivalent already accepted by traversal. The support layer cannot manufacture equivalent strength.
4. **No high-belief shortcut:** `active`, belief at/above threshold, local assertion, prediction, or timer passage cannot create support without confirmed provenance.
5. **One state and endpoint:** Each `support_id` has exactly one of `moving` or `settled` and exactly one current leading or settled node/zone. Kitchen and Alex Office cannot simultaneously be endpoints of one support. A bounded recent path is an exclusion footprint, not a claim of occupancy at every path node.
6. **No double count:** Current strong-front evidence is represented by its derived support, never counted alongside it. Connected/overlapping fronts remain coalesced.
7. **Source-set propagation:** A support advances only through an accepted traversal authorization containing a source token currently mapped to that support. If the accepted source set maps to several supports, those supports coalesce before advancing; the model does not select a person-like winner. Mere graph connectivity outside an accepted authorization, a remote reassertion, or a shared corridor cannot advance support.
8. **Conservative same-zone multiplicity:** Distinct supports that settle in the same zone coalesce deterministically. This version never infers same-zone multiplicity from sensor events, simultaneous or serial; `REQ-COUNT-005` remains true because one support is not one occupant assignment.
9. **Bounded:** Support cardinality is at most `PRODUCT_MAX_OCCUPANTS`. Token-to-support mappings are a subset of the traversal frontier's bounded active/retained token IDs. No episode or transition history grows with runtime.
10. **Ambiguity loses multiplicity:** Front merge, source-set merge, same-zone settlement, or an over-capacity creation attempt coalesces deterministically or declines the new support. Ambiguity may cause a false negative; it must not create an extra independent support.
11. **Soft count:** Count may health-degrade a contradictory asserted target only after `N` independent outside supports persist through the target release dwell. Count never directly releases it, and the later asserted-stay authority repair prevents that conflict from making the same raw-current stay episode publicly release-eligible.
12. **Fresh target wins immediately:** A new independent target episode or compatible target authorization cancels an unmatured conflict and restores existing conflict-recovery semantics.
13. **Zero count clears:** `N=0` atomically removes supports, mappings, fronts, conflicts, traversal, belief occupancy, and public active state under existing zero-count behavior.
14. **Deterministic:** Equal-timestamp ordering, support selection, coalescing, transfer, expiry, and conflict IDs are deterministic and restart-equivalent.
15. **No prototype compatibility obligation:** Uncommitted prototype state and field names have no compatibility status.
16. **Atomic transition:** A support update validates and builds complete next support/mapping/conflict state before replacing current state. No exception may expose a partially coalesced source set, duplicate endpoint, or dangling token mapping.
17. **Confirmed lineage retained through weak absence:** Settled support requires a graph-confirmed arrival and belief at/above the on threshold. It survives clear debounce and completed stable clear only without compatible outward context. A trustworthy same-endpoint reassertion rebinds the existing support but cannot create or clone one. Outward clear, unavailable/health/cadence state, or belief below threshold removes support.

## Alternatives

### A. Extend Stay Traversal Or Bootstrap Windows

Rejected. Gym's room evidence should remain credible for a long stay, but its original edge must not authorize Dining movement many minutes later. Extending movement windows couples unrelated concepts and increases cross-occupant misassociation.

### B. Direct Probabilistic Count Penalty

Rejected for the first implementation. Applying remote count pressure directly to Gym belief would require a calibrated likelihood model for dependence among count, fronts, local sensors, and missed exits. It would also bypass the established `REQ-COUNT-009` health-degradation path. Such a model may be evaluated later from shadow data, but this incident does not calibrate it.

### C. Zone-Level Boolean Anchor

Rejected. A boolean per zone cannot preserve support continuity while an occupant moves, cannot prevent one lineage from settling in two zones, and cannot explain which front/anchor combination sustained a conflict dwell.

### D. Anonymous Occupancy Support State Machine

Selected. It preserves movement provenance without person identity, keeps traversal authorization finite, reuses established count-conflict degradation, and can represent a settled endpoint after traversal tokens expire.

## State Model

### `AnonymousOccupancySupport`

The normative logical state is:

```text
support_id: opaque stable ID derived from first confirmed stay-token identity
state: moving | settled
created_at: UTC event time
updated_at: UTC event time
current_episode_id: current leading/settled physical episode
current_node_id: configured physical node
current_zone: configured zone
path_node_ids: bounded confirmed path used for the latest transition
provenance_kind: adjacent | boundary | missed_edge
valid_until: UTC event time when state=moving; absent when state=settled
last_transition: created | advanced | settled | coalesced
```

The tracker also owns a bounded `token_id -> support_id` mapping for active and retained traversal tokens. It is not occupant identity: it records only which anonymous connected support an accepted token can advance. Implementation may use equivalent normalized records, but snapshot diagnostics and restore validation must expose equivalent information.

The concrete immutable binding record is:

```text
token_id: active/retained traversal token ID
support_id: existing anonymous support ID
```

Supports are sorted by `support_id`; bindings are sorted by `token_id`. `support_id` is exactly `support:<first_confirmed_token_id>`. `created_at` is that token's `accepted_at`. `updated_at` is the latest accepted transition time and satisfies `created_at <= updated_at <= snapshot.updated_at`. Endpoint node/zone/episode and path equal the accepted target token that most recently advanced the support. `path_node_ids` contains one to three graph-compatible configured physical nodes and ends at `current_node_id`. A moving support has `valid_until` equal to that target token's traversal deadline; a settled support has `valid_until=None` and a stay-role endpoint in `asserted` or `clearing` status.

Only these confirmed-strength inputs create support:

- `track_confidence="confirmed"`, `provenance_kind="adjacent"`, exactly three distinct graph-adjacent path nodes; or
- an authorization already marked `equivalent_confirmed_strength=True`, with the boundary/missed-edge path and provenance validation required by traversal authority.

Provisional, adjacent-pair, same-zone, prediction, and ordinary boundary authorization cannot create support. They may propagate an existing support only when their accepted `source_tokens` contain a mapped token.

### Identity

- A confirmed stay-target token with no mapped source support receives a deterministic `support_id` derived from its token ID.
- When an accepted authorization has exactly one mapped source support, the target token inherits that support ID.
- When an accepted authorization has several mapped source supports, they coalesce under the lexicographically least support ID; all surviving token mappings are rewritten atomically.
- A token maps to at most one support. Unmapped linked tokens may be attached to the resulting support only when they are listed in the same accepted authorization; graph proximity alone is insufficient.
- A split never clones support. A branch without the canonical mapped source remains unsupported until it independently satisfies new-support creation.
- Merge, coalescence, provenance loss, or ambiguity changes the selected support-ID set and cancels dependent conflict dwell.
- IDs are sorted and compared deterministically; they do not encode a person.

### States And Transitions

| Current        | Input                                                                            | Guard                                                                                | Next                                                                                                                 | Count effect                 |
| -------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| absent         | accepted confirmed stay-target token                                             | target is trustworthy, belief at/above on threshold, no mapped source                | `settled` at target                                                                                                  | one new support if below cap |
| moving/settled | accepted authorized target                                                       | at least one source token maps to support; coalesce all mapped source supports first | target becomes sole endpoint; `settled` for eligible stay target, otherwise `moving` until target traversal deadline | same/coalesced support       |
| moving         | validity deadline                                                                | no compatible continuation/settlement before deadline                                | absent                                                                                                               | support removed              |
| settled        | clear enters debounce                                                            | source episode is `clearing`, belief remains at/above on threshold                   | `settled` until clear deadline                                                                                       | same support                 |
| settled        | correlated reassertion before clear deadline                                     | source episode returns to `asserted` without cadence/health warning                  | `settled` unchanged                                                                                                  | same support                 |
| settled        | stable clear                                                                     | belief remains at/above on threshold and no compatible outward context               | `settled` at the same endpoint                                                                                       | same support                 |
| settled        | trustworthy same-endpoint reassertion after weak clear                           | existing support remains at that endpoint                                            | `settled` rebound to the new episode                                                                                 | same support; never creation |
| settled        | outward clear, unavailable, health/cadence warning, or belief below on threshold | any                                                                                  | absent                                                                                                               | support removed              |
| settled        | second support settles in same zone                                              | any                                                                                  | coalesce under least support ID at that endpoint                                                                     | one support for zone         |
| any            | count becomes zero                                                               | accepted authoritative update                                                        | absent                                                                                                               | all supports removed         |

A stable clear remains weak absence for zone belief and public policy. A graph-confirmed settled support may outlive that weak absence only while the same endpoint retains belief at/above the on threshold and no compatible outward context exists. This preserves confirmed arrival lineage without treating high belief as support creation. A continuously asserted stay sensor remains local evidence under existing authority; support does not add trust or prevent that episode from being health-degraded when `N` other independent supports contradict it.

### Ownership And Method Contracts

`AnonymousSupportTracker` in `zone_model/supports.py` owns support records, token bindings, coalescence, retention, transition diagnostics, and count-support projection. `TraversalFrontier` remains the sole owner of authorization and tokens. `CountConflictTracker` owns only target conflict dwell/degradation state and consumes immutable count-support projections.

The required logical APIs are:

```text
advance(at, episodes, beliefs, active_tokens, retained_tokens) -> SupportTransition
apply(at, effect, authorization, issued_target_token,
      episodes, beliefs, active_tokens, retained_tokens) -> SupportTransition
clear(at, reason="count_zero") -> SupportTransition
restore(supports, bindings, at) -> None
count_supports() -> tuple[CountSupport, ...]
```

`SupportTransition` contains complete next supports/bindings plus bounded latest-transition diagnostics; the tracker swaps them only after validation. `CountSupport` contains `support_id`, endpoint node/zone, and the one-to-three-node exclusion path. The engine captures the token returned by `TraversalFrontier.issue()` and passes it with the same accepted authorization; the tracker never looks up or modifies traversal internals. For non-positive effects and timer advancement, `authorization` and `issued_target_token` are absent.

`advance()` removes bindings whose token is absent from both active and retained frontier, expires moving support at `valid_until`, removes settled support at completed stable clear/unavailable/health/cadence/belief failure, coalesces duplicate settled zones, and returns all dependent selected-support invalidations in the same transition. `apply()` first advances to `at`, then derives mapped source IDs from the complete accepted source-token set, coalesces them, maps the issued target token, moves the sole endpoint, and settles only when the target satisfies the stay guard. A confirmed stay target with no mapped sources creates a support only when below cap.

To preserve `REQ-COUNT-008`, the tracker builds connected components only among current confirmed token paths. It indexes each path's at most three nodes and their configured neighbors, unions overlapping/adjacent path components, and coalesces every mapped support within one component. It never coalesces two settled supports merely because their zones are adjacent after their tokens expire; only same-zone settlement still coalesces them. This avoids an all-pairs token scan. All iteration, union roots, and tie-breaking use sorted IDs.

### Processing And Commit Ordering

The support tracker follows the engine's existing publication boundary instead of introducing a new one. For each input at event time `t`:

1. validate monotonic event and processing time;
2. advance episode, belief, traversal, moving-support, prediction, and policy frontiers with deadlines `< t` or `<= t` according to existing `REQ-STATE-009` half-open rules;
3. if an existing count-conflict deadline is `<= t`, evaluate only that stored dwell against the pre-input support frontier; cross it when its selected supports remain valid, otherwise cancel it, before any external input at `t` can extend or replace the old frontier;
4. apply the local episode and graph-local belief effect, compute traversal authorization, and issue/sync the target token;
5. evaluate the supported local policy edge and invoke its publication callback before unrelated whole-house support/count work, preserving the existing callback-order contract;
6. regardless of publication callback success, atomically update support state from the accepted effect, complete returned source-token set, and issued target token, then derive count supports and update/cancel/cross conflict dwell;
7. commit the event-time engine state and deferred audit, then report any captured publication exception to the caller;
8. expose one internally consistent snapshot for delayed persistence and diagnostics.

At one timestamp, moving-support expiry and stable clear are advanced before support/count evaluation and cannot be revived by an input at their deadline. A due count-conflict uses the selected support-ID set valid at that frontier; selected-support loss or coalescence at the same frontier cancels the dwell. This timer-first rule applies to positive, clear, unavailable, and count input alike. If a fresh compatible target positive arrives exactly at a matured conflict deadline, the old episode is diagnosed first and the accepted positive then follows ordinary same-event recovery/acquisition semantics; count still emits no direct public release. When no stored conflict is due, the supported local callback continues to precede ordinary whole-house count recomputation.

Source-support coalescence, token-map rewrite, endpoint movement, settlement, support expiry, and dependent conflict resets are computed in temporary immutable collections and swapped as one transition. Validation failure leaves prior support state untouched and aborts the engine operation under existing validation-failure semantics. A publication callback failure is different: the engine operation and support transition remain committed, matching [`test_publication_callback_failure_reports_after_atomic_engine_commit`](../../tests/test_zone_model_engine.py); the exception is reported only after commit.

## Count-Support Derivation

At each frontier, derive a sorted tuple of independent supports:

- one entry per valid `AnonymousOccupancySupport`, sorted by `support_id`;
- no separate entry for the front/token evidence from which that support was derived;
- one current endpoint node/zone used as the support's occupancy location;
- a bounded latest path used only as an exclusion footprint, so a target on the just-consumed path is not treated as independently outside itself;
- deterministic coalescence for mapped source sets, connected/overlapping current fronts, and same-zone settled endpoints;
- exclusion from a target's outside set when the target node/zone is the endpoint or lies in that latest bounded path.

For target `x` and count `N > 0`, start or continue conflict only when at least `N` sorted independent supports outside `x` exist continuously. A new conflict stores the first `N` sorted support IDs. While all selected IDs remain valid and outside, additional unselected supports or changes to them do not restart dwell. Topology-preserving transfer also preserves dwell. Loss, coalescence, split, or invalidation of a selected ID, target-compatible evidence, or count change resets an unmatured dwell; replacement supports start a new full dwell. A degraded conflict retains its selected IDs as historical recovery provenance.

If a selected support ceases to qualify after degradation, the conflict is
removed at that event-time frontier. A matching continuously asserted stay
episode returns from `degraded` to `asserted`, its belief context returns from
`degraded_asserted` to `asserted`, and a bounded `stuck_conflict_cleared` audit
row retains the original selected support IDs. Recovery adds no positive
likelihood, traversal token, acquisition authority, prediction, or public edge.

## Incident Timeline Under This Design

1. Shaila Office's confirmed stay arrival creates support `S1`; continuing local evidence keeps `S1` settled after traversal expiry.
2. The accepted Foyer/Dining/Kitchen sequence issues a confirmed Kitchen stay token and creates independent support `S2` by `17:09:13.675459Z`.
3. With count two, `S1` and `S2` are outside Gym and begin Gym's conflict dwell.
4. Subsequent accepted authorizations propagate `S2` through mapped source tokens to Bottom, Top, and the confirmed Alex Office stay token. Alex becomes the sole endpoint without changing `S2`.
5. Later Kitchen activity cannot move or duplicate `S2` unless its accepted authorization contains a token mapped to `S2`. It cannot leave `S2` settled in both Kitchen and Alex.
6. At the Gym dwell deadline, two independent supports still exist; Gym is health-degraded. If either support had disappeared, coalesced, or become ambiguous before the deadline, degradation would be canceled.

## Persistence And Compatibility

### Schema

Introduce `zone-belief-v4`. A behavior-changing persisted state machine must not silently share the `zone-belief-v3` schema identifier.

The v4 snapshot includes bounded supports and token-to-support mappings needed to preserve moving/settled state and deadlines. Serialization remains deterministic through structured encoding: supports by `support_id`, mappings by `token_id`, and conflicts by target node. Mapping entries exist only for tokens present in the same active/retained traversal snapshot; a settled support may validly have no token mapping after traversal retention expires.

Within the existing root payload, `snapshot.anonymous_supports` is a list of the support records above and `snapshot.support_token_bindings` is a list of binding records. `snapshot.count_conflicts[*].support_ids` replaces persisted `strong_front_ids`, and policy audit uses `count_conflict_support_ids` instead of `count_conflict_front_ids`. No support data is duplicated at the root. Missing fields are not valid v4 defaults.

### Import

- v4 is fully decoded and cross-validated before a candidate engine is returned. Every support node/zone/episode must exist; timestamps cannot be in the future; paths must be graph-compatible; provenance must be confirmed-equivalent; IDs/mappings must be unique; every mapping must reference a token in the same active/retained traversal snapshot; support count must be within cap; state/deadline combinations must be valid; and current episode status, belief, and health must permit settled support. Invalid state rejects the whole candidate.
- A moving restored support must have `snapshot.updated_at < valid_until`, a mapped current target token, and an endpoint matching that token. A settled restored support has no `valid_until`; its endpoint episode and belief must validate even when all source tokens have expired.
- A v3 importer restores otherwise compatible episode, filter, traversal, count, policy, prediction, and bounded audit state but creates no supports from historical `active`, belief, or expired traversal. It drops every unmatured legacy strong-front conflict because continuity cannot be proven in the new support-ID domain. It may retain an already-degraded matching target episode and its legacy selected IDs only as historical recovery provenance. New supports arise only from future accepted confirmed stay tokens.
- Older incompatible schemas retain existing cold-bootstrap behavior.
- Restore constructs at `snapshot.updated_at`, validates prediction/support cross-component references, then advances moving-support expiry and count-conflict dwell exactly once to `restore_at`. At an exact deadline, uninterrupted and restored execution use the same support set and produce byte-equivalent deterministic state apart from explicitly non-persisted runtime metrics.

### Rollback

Before the first v4 write, startup copies an accepted v3 payload verbatim to a distinct `zone_belief_v3_rollback` store if that store is absent. It never overwrites that backup during the rollout window. Only after backup success may normal delayed storage replace the primary payload with v4.

Rollback to code that cannot read v4 restores the saved v3 payload to the primary inference store before starting the old integration. If no valid backup exists, remove only the incompatible primary inference payload and cold-bootstrap from current sensor/count snapshots without synthetic movement or public acquisition edges. Map/options, Home Assistant entities, entity registry, and learned/user configuration are never deleted. Rollback may lose post-upgrade inference history; it must not claim continuity it cannot prove.

Runtime storage remains delayed best-effort: accepted events schedule a save after the existing one-second debounce and shutdown performs an awaited save. A process or host crash inside that window may lose the latest support transition just as it may lose other inference state. Restore must remain conservative and must not reconstruct the missing transition from current `active` or belief alone.

## Diagnostics And Observability

Expose bounded diagnostics for:

- support ID, state, endpoint, source/leading episode, bounded path, provenance, created/updated time, and moving deadline;
- current token mappings and coalesced source IDs for the last transition;
- latest transition on each current support plus one tracker-level latest transition for a removed/expired support;
- removal reason: count zero, belief below threshold, unavailable, health warning, cadence warning, ambiguous split/merge, moving expiry;
- selected count-support IDs and endpoint zones on each conflict start, reset, crossing, degradation, and recovery;
- counters for support creation, transfer, coalescence, expiry, restore rejection, conflict start/cancel/degrade.

Diagnostics must remain bounded by configured nodes, `PRODUCT_MAX_OCCUPANTS`, the traversal token limit, one tracker-level transition record, and fixed-size saturating counters. Support transitions do not create a new history log. Count-conflict/recovery rows use the existing per-zone policy audit bounds of 12 hours, 2,048 entries, 2 MiB encoded, and 4 KiB per row. No per-event unbounded history is introduced.

Runtime status adds `anonymous_supports`, `support_token_bindings`, `count_conflicts[*].support_ids`, and audit `count_conflict_support_ids`. For one compatibility release, the two legacy ID arrays `strong_front_ids` and `count_conflict_front_ids` remain exact aliases of their support-ID replacements. The old structured `strong_fronts` status list has no truthful one-endpoint equivalent and is removed as an explicit diagnostic contract change. New persistence uses only v4 names; the v3 importer alone decodes all legacy names. Tests require each retained ID alias to be byte-equivalent to its replacement so the two surfaces cannot diverge.

## Failure Behavior

- Invalid support snapshot: reject target state atomically, expose bounded restore reason/status, and use the existing cold-bootstrap path only when no accepted compatibility importer applies.
- Missing source token during an attempted transfer: do not transfer; retain or expire current support according to existing state and deadline.
- An accepted authorization containing tokens mapped to multiple supports: coalesce all mapped supports under the least ID before advancing. The authorization has already established a connected anonymous provenance set; the support layer never chooses one mapped support as a person-like winner.
- More than `PRODUCT_MAX_OCCUPANTS` independent creation candidates: retain existing supports and decline the new candidate deterministically; never evict an established support to make the count fit.
- Unsupported isolated target assertion: no support, regardless of belief.
- Out-of-order event older than model frontier: existing stale-input handling applies and support state does not change.
- Validation/transition exception: do not replace support state or publish a partial snapshot.
- Publication callback exception: finish and retain the atomic engine/support commit, discard only work already defined as post-publication learning, and report the exception after commit.
- Count unavailable/invalid: retain last valid count and support state; do not synthesize conflict.
- Positive count change: preserve valid supports, cancel unmatured conflicts under existing count-change semantics, and do not create/remove supports merely to equal the new count.
- Count zero: clear the support tracker, token mappings, traversal frontier, conflicts, prediction state, belief occupancy, and public active state in the same accepted count operation before exposing its snapshot.

## Implementation Plan

### Phase 0: Evidence And Baseline

- Preserve exact incident timestamps and public expectation in the retained regression.
- Split the dirty prototype test: the frozen public incident test retains every production event/time and asserts Shaila/Alex remain active at the incident frontier, Gym receives the public problem/health diagnostic, count emits no policy edge at degradation, and Gym belief later falls below the off threshold through degraded-belief decay. The retained Gym policy was never acquired and therefore emits no fabricated release edge. Place support IDs/endpoints/bindings in focused mechanism tests.
- Demonstrate the public regression fails against committed controlling behavior for Gym health/release, not setup.
- Prove committed `HEAD` lacks the prototype support type/behavior, and record the failing public assertion against committed production files while preserving the dirty test as the immutable input source.
- Record the environment (`python --version`, Node version, commit, CPU/platform), full gate baseline, and unmodified 100-event benchmark JSON under a temporary evidence path.

**Exit:** Exact public regression fails for the expected old Gym behavior and no setup/internal assertion; immutable inputs are frozen; baseline commands, environment, and benchmark JSON are recorded.

### Phase 1: Authority And Contracts

- Amend `SPECIFICATION.md` with approved support invariants, state transitions, count semantics, schema v4, diagnostics, and governance mapping.
- Add immutable support types with complete validation.
- Extend traversal authorization contracts only enough to preserve the accepted source-token set and issued target token consumed by the support tracker.
- Add transition-table unit tests before orchestration changes.

**Exit:** Authority is internally consistent; every record invariant above has a positive and mutation-negative type test; state-transition tests prove one endpoint, moving deadline, stable-clear removal, merge atomicity, sorted IDs, and cap behavior with no production integration.

### Phase 2: Support State Machine

- Implement a dedicated bounded support tracker separate from `TraversalFrontier` and `ZoneBeliefFilter`.
- Consume accepted traversal authorizations, issued target tokens, final episode effects, and current beliefs.
- Enforce one state/endpoint per support, source-set propagation, merge-before-advance, same-zone coalescing, deterministic IDs, cardinality cap, and deadlines.
- Do not expose supports to traversal or policy authorization APIs.

**Exit:** Positive, inverse, ambiguity, deadline, equal-timestamp, same-zone, and count-zero tracker tests pass.

### Phase 3: Count Conflict Integration

- Replace strong-front-only conflict inputs with derived independent support inputs.
- Preserve existing target eligibility, compatible-update cancellation, release dwell, health degradation, and recovery.
- Rename `CountConflictState.strong_front_ids` to `support_ids` and `PolicyDecision.count_conflict_front_ids` to `count_conflict_support_ids`, with the v3 decoder and one-release runtime status aliases defined above.

**Exit:** Exact incident passes; existing two-front conflict behavior remains; unrelated remote events and one-support cases cannot degrade a target.

### Phase 4: Persistence And Diagnostics

- Add schema v4 serialization, strict restore, v3 import, restore advancement, diagnostics, and bounded counters.
- Add uninterrupted-versus-restart equivalence at every transition/deadline.
- Add pre-v4-write v3 backup, rollback restore, delayed-save crash-window, and cold-bootstrap behavior.

**Exit:** Persistence mutation matrix and diagnostic bounds pass; v3 import invents no support.

### Phase 5: Adversarial And Performance Validation

- Run retained incident corpus, count zero/one/two matrix, same-zone multiplicity, connected/overlapping paths, backtracking, missed edges, stuck assertion, false clear, unavailable, cadence degradation, count change, stale/out-of-order input, and restart tests.
- Run full Python coverage, Ruff, mypy, frontend, benchmark, and diff/reference gates.
- Compare benchmark with Phase 0 under the same environment and fixture.

**Exit:** All acceptance gates pass and no unresolved correctness finding remains.

### Executable Gates

Run from the repository root with the existing `.venv`:

```bash
.venv/bin/python -m pytest -q --no-cov tests/test_zone_model_supports.py tests/test_zone_model_count.py tests/test_zone_model_public_contract.py tests/test_zone_model_persistence.py
.venv/bin/python -m ruff check custom_components/predictive_controls tests benchmarks
.venv/bin/python -m mypy
.venv/bin/python -m pytest -q
npm run test:frontend
.venv/bin/python benchmarks/occupancy_performance.py --map benchmarks/reference-map.yaml --events 100 --output /tmp/predictive-controls-supports-benchmark.json
git diff --check
```

During Phases 1 through 4, use the smallest touched test file(s) with `--no-cov` plus Ruff on touched Python files before further edits. The final Python command must retain repository-configured 100% branch coverage. The benchmark process must exit zero and report `passed: true`; generated evidence remains outside the worktree.

### Phase 6: Rollout And Review

- Perform fresh independent conformance review against this spec and `SPECIFICATION.md`.
- Deploy with pre-upgrade inference-state backup.
- Observe support/conflict diagnostics through representative two-occupant movement and at least one normal long stay before accepting rollout.
- Roll back on false target degradation, support duplication, restore rejection loop, or performance gate breach.

**Exit:** Production observation confirms expected support transitions without false degradation; rollback remains available.

## Test Matrix

Required focused cases include:

- confirmed three-node arrival creates one settled support;
- provisional/two-node, isolated high belief, `active`, prediction-only, and timer-only states create none;
- support state cannot alter a traversal authorization result, acquisition phase, zone belief, prediction lease, or public active state when count-conflict output is held constant;
- support survives ordinary traversal-token expiry while settled and credible;
- clearing debounce retains support, correlated reassertion preserves it, and completed stable clear removes it without forcing zone belief or public active off;
- an accepted authorization with a mapped source token transfers support to moving and clears the old endpoint atomically;
- source sets mapped to two supports coalesce before advancing and cannot count twice;
- remote/connected corridor activity without a mapped source token cannot transfer support;
- compatible target arrival settles the same support ID at exactly one endpoint;
- later old-endpoint reassertion cannot duplicate or steal a support without explicit lineage;
- moving expiry removes support and cancels dependent conflict;
- token expiry removes its mapping; settled support remains valid with zero mappings;
- one current confirmed token component plus its settled support counts once;
- two independent fronts create two support IDs;
- incident-focused state test proves `S1` and `S2` use different first-confirmed token IDs, both are settled, each has one endpoint, `S2` ends only in Alex Office, and no raw front is counted in addition;
- connected/overlapping current confirmed token components coalesce, while adjacent token-expired settled zones do not;
- simultaneous and serial same-zone arrivals do not infer multiplicity;
- split traversal cannot clone one support onto two branches;
- over-capacity support creation is declined without evicting established support;
- count one/two never forces exact active-zone cardinality;
- count zero clears all support state;
- fresh compatible target evidence cancels conflict immediately;
- support loss one microsecond before conflict deadline prevents degradation;
- support present at deadline degrades exactly once;
- external clear at the same deadline follows existing timer-first semantics;
- compatible positive at the same deadline diagnoses the old conflict first, then applies ordinary recovery without a count-driven public release;
- count change cancels unmatured conflict;
- publication callback failure still commits the same support/count snapshot as successful callback execution;
- validation failure leaves support/mapping/conflict state byte-equivalent to its pre-operation snapshot;
- unavailable/health/cadence loss removes support;
- stale/out-of-order events cannot mutate support;
- restart before, at, and after moving/conflict deadlines matches uninterrupted execution;
- malformed, duplicate, future, graph-incompatible, and semantically inconsistent v4 supports fail atomically;
- malformed binding to absent token/support, moving support without target binding, settled support with deadline, and unsorted/over-cap support snapshots fail atomically;
- v3 import creates no support, drops unmatured legacy conflict dwell, and preserves only valid already-degraded recovery provenance;
- first v4 startup writes one immutable v3 rollback backup before replacing the primary payload;
- crash before delayed save restores the last complete snapshot without inferring the lost support transition;
- exact `INC-2026-08-20-stale-gym-assertion` degrades Gym while Shaila and Alex remain active;
- inverse incident with one outside support does not degrade Gym;
- inverse incident where Shaila has plausible outward movement cancels conflict;
- inverse incident where a settled source reaches stable clear before the dwell deadline cancels conflict while its zone belief may remain active;
- inverse incident where Gym receives fresh compatible evidence cancels conflict.

## Performance And Resource Gates

Use [`benchmarks/occupancy_performance.py`](../../benchmarks/occupancy_performance.py) and [`benchmarks/reference-map.yaml`](../../benchmarks/reference-map.yaml).

- Record Phase 0 100-event core p50/p95/p99/max, each fast-path p99/max, timer-work p95/max, token/audit/persistence maxima, output schema, map path/hash, Python/Node versions, commit, CPU/platform, and trace profile.
- Run Phase 5 on the same host, Python, event count, map, count `N=2`, and `deterministic` trace profile with coverage disabled and no competing repository test process.
- `REQ-PERF-001` fast paths remain p99 at or below 5 ms and hard latency below 10 ms. Core/timer preferred p95 remains at or below the benchmark's 50 ms gate and hard max at or below 100 ms. The benchmark must report all path/publication/completion and byte-stability gates true.
- A core p95 or p99 increase greater than 20% versus the recorded baseline is a mandatory review trigger, not an automatic failure when all authoritative absolute gates pass. Record the explanation and rerun once under the same conditions before acceptance.
- Benchmark output adds `support_max`, `support_limit`, `support_binding_max`, and `support_binding_limit`; gates require maxima within `PRODUCT_MAX_OCCUPANTS` and traversal token limit.
- Support update work is `O(nodes + tokens * local_degree + supports)` per event using the path-node/neighbor index, with three nodes per path, traversal tokens bounded by 64, and supports bounded by `PRODUCT_MAX_OCCUPANTS`; no all-pairs token or retained-audit scan is permitted.
- Persisted and diagnostic payload growth is measured. Repeated serialization must be byte-stable; each encoded support record is at most 4 KiB, each encoded binding at most 512 bytes, and the tables remain bounded by `PRODUCT_MAX_OCCUPANTS` supports and 64 bindings.

## Acceptance Criteria

1. The exact incident regression fails on committed old behavior and passes after the generic change.
2. Two independent outside supports continuously saturate count and health-degrade a contradictory asserted stay target only after its normal release dwell.
3. One support cannot be settled or counted in both Kitchen and Alex Office.
4. Support continuity across valid mapped-source movement does not restart conflict dwell; merge, split, or support-ID-set change does.
5. Remote activity without a mapped source token cannot move, duplicate, or erase settled support.
6. No identity, exact assignment, direct count-to-belief write, or direct count-to-public release is introduced.
7. All positive and inverse test-matrix cases pass.
8. v4 restore is atomic and restart-equivalent; v3 import invents no support.
9. Full Python suite reaches 100% branch coverage; repository Ruff and mypy pass.
10. Frontend tests and the applicable 100-event benchmark pass within stated budgets.
11. Fresh independent review finds no unresolved authority, correctness, persistence, or public-contract defect.
12. Production rollout records no false count-conflict degradation during the observation window.
13. Publication callback failure preserves the same committed support state as successful publication, while validation failure exposes no partial transition.
14. A verified v3 rollback payload exists before the first v4 primary-store write, and the documented downgrade drill restores or cold-bootstraps inference without modifying authoritative user configuration.
15. Public incident assertions contain no support/anchor implementation fields; focused tests independently prove creation provenance, one endpoint, mapping, coalescence, cap, and no-double-count invariants.
16. Runtime diagnostic compatibility aliases equal the new support fields, and v4 persistence contains no legacy front field names.

## Implementation Surfaces

Expected surfaces, subject to Phase 1 design review:

- `SPECIFICATION.md`
- `custom_components/predictive_controls/zone_model/types.py`
- new `custom_components/predictive_controls/zone_model/supports.py`
- `custom_components/predictive_controls/zone_model/traversal.py`
- `custom_components/predictive_controls/zone_model/count.py`
- `custom_components/predictive_controls/zone_model/engine.py`
- `custom_components/predictive_controls/zone_model/persistence.py`
- `custom_components/predictive_controls/zone_model/policy.py`
- `custom_components/predictive_controls/status.py` and WebSocket/panel consumers where count provenance is shown
- `custom_components/predictive_controls/__init__.py` and storage tests for pre-v4 rollback backup
- `benchmarks/occupancy_performance.py` for bounded support metrics
- focused count/support/persistence/type tests
- retained public incident regression
- benchmark only if new bounded-work assertions require it

`filter.py` should not change unless Phase 2 proves its existing public belief state cannot supply a required retention guard. Traversal authorization may gain only the structured source/target provenance required above; support state must not feed back into traversal decisions.

## Tracking

| Phase                                     | Status   | Completed evidence                                                                                                                                                                                                                                        | Next executable step                                     |
| ----------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| 0. Evidence and baseline                  | Complete | Exact public regression fails on committed `HEAD` at missing Gym health degradation; 510 tests/100% coverage, Ruff, mypy, 29 frontend tests, and 100-event benchmark pass at `9fe1510`. Baseline JSON: `/tmp/predictive-controls-supports-baseline.json`. | Add normative support contracts and type mutation tests. |
| 1. Authority and contracts                | Complete | `SPECIFICATION.md` defines anonymous supports, weak-clear retention, count-only authority, and `zone-belief-v4`.                                                                                                                                          | None.                                                    |
| 2. Support state machine                  | Complete | Bounded supports, bindings, transfer, coalescence, expiry, weak-clear retention, and same-endpoint rebind have focused tests.                                                                                                                             | None.                                                    |
| 3. Count conflict integration             | Complete | Count consumes immutable support projections; the exact Gym incident degrades health without a fabricated policy edge.                                                                                                                                    | None.                                                    |
| 4. Persistence and diagnostics            | Complete | Strict v4 restore, conservative v3 import, immutable pre-write rollback backup, aliases, and bounded lifecycle counters pass focused tests.                                                                                                               | None.                                                    |
| 5. Adversarial and performance validation | Complete | 553 Python tests pass at 100% branch coverage; Ruff, strict mypy, 29 frontend tests, frontend build, diff check, and all benchmark gates pass. Support/binding maxima are 2/2 and 10/64; core p95 is 1.548 ms.                                            | None.                                                    |
| 6. Rollout and review                     | Complete | Accepted v3 state is backed up immutably before runtime start or any v4 write; backup failure aborts setup. Independent conformance review found no authority violations or behavioral defects.                                                           | Observe support/conflict diagnostics during rollout.     |
