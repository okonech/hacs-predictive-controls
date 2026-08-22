# Temporal Support-Transfer Authority

**Status:** Implemented and independently reviewed  
**Incident:** `INC-2026-08-22-prearrival-support-transfer`  
**Affected layers:** anonymous supports, count conflict, policy, diagnostics,
persistence validation, public regression coverage  
**Required authority amendments:** `REQ-COUNT-008`, `REQ-COUNT-011`,
`REQ-STATE-010`  
**Related authority:** `REQ-COUNT-009`, `REQ-PERF-001`, `REQ-GOV-006`

## Objective

Prevent an anonymous occupancy support from moving away from its current
endpoint through a traversal token that was accepted before the support reached
that endpoint. Preserve legitimate anonymous movement, count-zero behavior,
same-zone multiplicity, bounded state, restart equivalence, and ordinary policy
hysteresis without introducing person identity or room-specific logic.

The public outcome for the retained incident is that `alex_office` remains
active while its trustworthy stay episode remains continuously asserted. A
later `shaila_office` episode may still acquire from the shared transition
token, but that pre-arrival token cannot move the support that settled at
`alex_office` after the token was accepted.

## Verified Current State

The production trace retained on 2026-08-22 establishes:

| Time (UTC)        | Observation or decision                                  | Material result                                                         |
| ----------------- | -------------------------------------------------------- | ----------------------------------------------------------------------- |
| `17:45:15.291907` | Master-bedroom entrance asserted                         | Adjacent authorization                                                  |
| `17:45:16.259573` | Top-of-stairs transition asserted                        | Confirmed traversal token                                               |
| `17:45:22.409954` | Alex office asserted                                     | Acquired at `0.7812030651163774`; support settled at Alex office        |
| `17:45:24.033458` | Shaila office asserted                                   | Reused the still-current top-of-stairs token                            |
| `17:47:28.212891` | Two supports remained outside Alex through release dwell | Alex episode health-degraded by `stuck_count_conflict`                  |
| `17:54:58.884915` | Degraded Alex belief crossed release policy              | Public Alex `active` released at belief `0.21652857849375204`           |
| `17:59:02.740671` | New top-of-stairs episode                                | Conflict cleared without synthetic positive evidence                    |
| `18:01:09.849514` | Guest-origin and closet supports remained outside Alex   | Count conflict degraded the same asserted Alex episode again            |
| `18:05:19.904316` | Closet support fell below support threshold              | Conflict cleared; Alex remained inactive without a fresh target episode |

Home Assistant history shows the Alex mmWave episode remained continuously
asserted from `17:45:22.409954`. The retained conflict selected two anonymous
support IDs; one had originated from the Alex target episode and had moved away,
while the other had originated from the kitchen route and was settled at the
continuously asserted guest-bedroom endpoint.

The implementation currently selects transfer sources in
`AnonymousSupportTracker.apply()` from every authorization source token that has
a retained `SupportTokenBinding`. It does not compare the token's `accepted_at`
with the mapped support's `updated_at`. Target processing then binds both source
tokens and the issued target token to the transferred support. A source token
accepted before the support's latest endpoint can therefore retain transfer
authority after that support advances.

## Problem Statement

A token-to-support binding records lineage, but the current implementation also
treats it as timeless transfer authority. That is causally invalid. If a token
was accepted at $t_1$ and a support reached its current endpoint at $t_2>t_1$,
the token cannot prove departure from that endpoint. Reusing it at $t_3>t_2$
can move the support to another target without any post-arrival source evidence.

This is distinct from traversal authorization. One open transition episode may
authorize multiple fresh targets because the model must not require hardware to
clear between occupants. The defect is allowing the same pre-arrival token to
move count-only lineage that did not yet occupy its current endpoint when the
token occurred.

## Scope

### In Scope

- Add one temporal binding-authority predicate wherever a token binding selects
   support state for transfer, source-set merge, or connected-current-component
   coalescence.
- Require an authorization source token to occur before the target on the
   accepted target path before it may select support for transfer or source-set
   merge; linked lineage outside that path remains authorization context only.
- Preserve the exact incident as a public regression with production event
  times, count `2`, continuous Alex assertion, and expected `active` retention.
- Add direct support tests for stale, fresh, equal-time, and mixed source-token
  sets.
- Prove restore uses the same eligibility rule without schema migration.
- Expose a bounded lifecycle counter for stale transfer bindings ignored during
  accepted target processing.
- Amend the sole authority and maintained conformance snapshot.

### Non-Goals

- Do not disable count conflict or change count-conflict dwell, belief decay,
  thresholds, release dwell, reliability, or profiles.
- Do not require a stay sensor to clear before legitimate support movement.
- Do not infer identity, choose a unique occupant, force exactly $N$ active
  zones, or privilege a named room/person/entity.
- Do not treat policy state, prediction, timers, aliases, callback count, or
  light/switch output state as evidence.
- Do not change traversal authorization for fresh target acquisition.
- Do not deploy or reload Home Assistant as part of repository acceptance.

## Invariants

1. **Transfer frontier:** A bound source token may select its mapped support for
   transfer only when `token.accepted_at >= support.updated_at` at the start of
   the target application.
2. **Equality is current:** Exact equality is eligible. A source token issued in
   the same ordered update that establishes the support frontier remains usable
   when it also participates in the selected target path.
3. **Stale means ignored, not destructive:** An ineligible binding remains
   bounded retained lineage but contributes no source support ID, source-set or
   connected-component coalescence, transfer, or target rebinding for that
   application. If its mapped support independently loses a valid coalescence,
   ordinary referential-integrity remapping to the winning support is allowed.
4. **Fresh subset only:** A mixed source-token set resolves support IDs from only
   temporally eligible, on-path bindings. Stale or linked off-path bindings
   cannot pull another support into source-set merge.
5. **No synthetic support:** If no eligible mapped source remains, ordinary
   confirmed-strength creation may occur only when the support limit and existing
   creation contract allow it. Otherwise support state is unchanged.
6. **Authorization separation:** Ignoring stale transfer authority does not
   revoke target traversal authorization, belief, or policy acquisition.
7. **Monotonic time:** `AnonymousOccupancySupport.updated_at` is the support's
   causal mutation frontier and never moves backward. Creation, endpoint
   transfer, same-endpoint episode rebind, source-set/component/same-zone
   coalescence, and settlement may advance it. Event time controls the guard;
   processing time does not.
8. **No cloning:** Filtering a source set cannot clone, split, or increase the
   number of current supports except through the existing bounded creation path.
9. **Count behavior:** Count zero still clears all supports categorically. Counts
   one and two use only the resulting current support endpoints and retain all
   existing same-zone coalescence rules.
10. **Conflict behavior:** Count conflict itself remains unchanged. Preventing a
    causally invalid transfer keeps the support at the asserted target, so that
    support excludes the target from outside-support contradiction.
11. **Restart equivalence:** Restored tokens, bindings, and supports apply the
   same event-time guard. Restore neither rewrites bindings nor invents transfer.
   Support state, bindings, conflicts, audit decisions, policy, and public edges
   match uninterrupted execution; process-local lifecycle counter totals may
   reset, but the next event's counter delta is identical.
12. **Bounded observability:** Each ignored token binding increments one
    saturating lifecycle counter during the accepted target application. Timer
    advancement and repeated diagnostics do not increment it.
13. **Atomicity:** A support transition or validation failure before
   `AnonymousSupportTracker._commit()` changes neither support state nor the
   ignored-binding counter. `_commit()` and the counter delta complete before
   control returns to engine count/policy evaluation. Existing engine semantics
   then commit the accepted in-memory snapshot before publication callbacks;
   callback failure does not roll it back.
14. **Conservative open-transition ambiguity:** One continuously open transition
   may authorize several fresh targets, but a token accepted before one target's
   support frontier cannot prove that support subsequently departed. A genuine
   rapid backtrack with no newer source edge may therefore leave count support
   at the earlier target until fresh evidence resolves the ambiguity; target
   belief and acquisition remain independent.

## Proposed Contract

Define one internal binding-authority operation over a token, candidate support
mapping, and candidate binding mapping. It returns one of `unbound`,
`eligible(support_id)`, or `stale(support_id)`:

1. Look up `bindings[token.token_id]`.
2. Look up the mapped support in the candidate support mapping.
3. Return `eligible` only when the support exists and
   `token.accepted_at >= support.updated_at`; exact equality is eligible.
4. Return `stale` when both records exist but the token is earlier.
5. Treat an absent/pruned binding as `unbound`; strict candidate validation still
   rejects impossible persisted references before this operation.

`AnonymousSupportTracker.apply()` then:

1. Defines the path-source nodes as `authorization.path_node_ids[:-1]` and
   deduplicates/sorts support IDs only from `eligible` authorization source
   tokens whose `node_id` occurs in that prefix.
2. Counts distinct `stale` authorization source tokens once for diagnostics.
3. Runs existing source-set coalescence and transfer using only eligible support
   IDs.
4. Allows ordinary confirmed-strength creation when there is no eligible mapped
   source and the existing support-limit/settlement contract permits it.
5. Binds the issued target token and unbound/eligible source tokens to the
   resulting support. A stale source binding remains on its existing support and
   is not rebound merely because target creation or transfer succeeded.

`_coalesce_current_components()` uses the same predicate when turning active
token bindings into support IDs. Stale bindings are excluded silently there;
timer advancement does not increment the application counter. Same-zone
coalescence uses current support endpoints rather than token bindings and remains
unchanged.

When an eligible source set, active component, or same-zone endpoint rule
independently coalesces supports, existing `_coalesce()` behavior remaps every
binding from a removed support ID to the winning ID. That referential-integrity
remap does not grant the stale token authority and is required because a binding
may not reference an absent support.

The predicate is evaluated against support state after deterministic advancement
at the operation time and before any binding-derived coalescence. It uses event
time stored in existing v4 records. A coalescence at time $t$ advances the
winner's `updated_at` to at least $t$, so only tokens accepted at or after $t$
retain later binding authority. The implementation must not mutate, delete, or
overwrite a binding merely because it is stale for one operation.

### Implementation Shape

Add one private helper in `AnonymousSupportTracker` with the equivalent contract:

```python
def _binding_authority(
      token: TraversalToken,
      supports: Mapping[str, AnonymousOccupancySupport],
      bindings: Mapping[str, str],
) -> tuple[str | None, bool]:
      """Return (eligible support ID, stale existing binding)."""
```

- `(None, False)` means unbound or pruned.
- `(support_id, False)` means eligible.
- `(None, True)` means a current binding exists but predates the mapped
   support's causal mutation frontier.

Use this helper in both source selection and active-component support selection.
Source selection first excludes linked off-path tokens, then additionally retains
the set of stale on-path source token IDs so the post-operation binding loop
skips both ineligible classes and the commit receives the distinct stale count.
Extend `_commit()` with a default-zero ignored-stale delta and increment
`support_stale_binding_ignored` inside `_commit()` after transition construction
succeeds. No public model type, persisted dataclass, or schema field changes.

## Event Ordering

For an external target event at $t$:

1. Advance belief, episodes, traversal, supports, count conflict, prediction, and
   policy frontiers due before or at $t$ using existing timer-first ordering.
2. Apply the target episode and traversal authorization.
3. Advance support validity and remove invalid endpoints.
4. Rebind a same-endpoint settled support for a fresh local generation when
   applicable.
5. Resolve authorization source bindings with the temporal authority predicate.
6. Coalesce the eligible source set, transfer/create support, and bind only the
   target plus unbound/eligible source tokens.
7. Re-evaluate count conflict and policy atomically.
8. Publish changed public edges after the in-memory snapshot commits.

An exact-deadline target cannot revive a support removed during timer-first
advancement. A stale retained token cannot move a restored or uninterrupted
support after its `updated_at` frontier.

## Persistence And Compatibility

No schema or Store version change is required. `zone-belief-v4` already persists
`TraversalToken.accepted_at`, `AnonymousOccupancySupport.updated_at`, support
bindings, count conflicts, and the model frontier. Strict restore validation
remains authoritative.

- Existing v4 snapshots restore without rewriting support or binding records.
- A restored stale binding remains retained but is ignored by future transfer.
- Uninterrupted and restored execution must produce identical supports,
   bindings, conflicts, audit decisions, policy, and public edges at the next
   event. Tracker counter totals are process-local today; compare per-event deltas
   rather than accumulated totals across restart.
- Existing v3 import remains conservative because it invents no support.
- Crash before the next successful Store save retains the existing bounded
   false-negative behavior: Home Assistant may lose the accepted event, but
   restart must not replay retained state timestamps or synthesize a transfer.
- Rollback requires no data migration; older code may resume its former transfer
   behavior from the same v4 snapshot. Operational rollback is therefore a known
   behavioral rollback, not a data rollback, and must be followed by renewed
   observation for false count-conflict releases.

## Diagnostics

Add saturating lifecycle counter `support_stale_binding_ignored` to the existing
support tracker counters. The generic engine/occupancy status projection already
exports tracker counters under `lifecycle_counters`; no explicit production
status serializer branch or persisted field is required. Increment immediately
after a successful support commit by the number of distinct authorization source
tokens whose binding and support exist but whose `accepted_at` is earlier than
that support's `updated_at` during one accepted positive/interaction application.

The counter is diagnostic only. It resets with existing tracker counters on
restore, is not persisted evidence, does not alter policy, and must remain zero
for timer-only advancement, duplicate/stale/rejected events, connected-component
filtering outside accepted target application, bindings whose support was already
removed, and eligible equal-time bindings.

## Alternatives Rejected

1. **Disable count-conflict degradation.** This would restore indefinite stuck
   stay assertions and contradict `REQ-COUNT-009`.
2. **Require local clear before every transfer.** Hardware hold and missed clear
   edges would prevent legitimate movement and contradict bounded missed-edge and
   open-transition behavior.
3. **Delete stale bindings eagerly.** Deletion adds state mutation and restore
   complexity without being required for boundedness or correctness.
4. **Prefer active or highest-belief zones.** That feeds policy/belief back into
   anonymous lineage and approximates forbidden identity assignment.
5. **Use physical switch interaction to repair the route.** A press can reacquire
   locally but cannot correct a causally invalid support transfer when no press
   occurs.
6. **Increase decay or conflict dwell.** Incident-specific calibration would
   delay rather than prevent the invalid transfer.
7. **Let one continuously open transition prove immediate arrival and later
   departure.** The event predates the arrival frontier and cannot order the two
   occupants or prove backtracking. Reusing it for target authorization remains
   allowed; moving count lineage is conservatively withheld until newer source
   evidence exists.

## Implementation Phases

### Phase 0: Authority And Exact Baseline

- Amend `REQ-COUNT-008` and `REQ-COUNT-011` with temporal binding eligibility,
  and `REQ-STATE-010` with restart evaluation of retained stale bindings.
- Update Section 19 only after implementation evidence exists.
- Add an exact-timestamp public regression using generic node names, count `2`,
   the retained independent-support prelude, and the production causal order:
   shared transition at `17:45:16.259573`, retained target at
   `17:45:22.409954`, second target at `17:45:24.033458`, conflict dwell at
   `17:47:28.212891`, and historical release frontier
   `17:54:58.884915`.
- Assert the intermediate defect, not only the final release: after the retained
   target, its support endpoint is that target and its `updated_at` is later than
   the shared token; after the second target on old code, that same support has
   moved away and the stale-binding counter does not yet exist.
- Prove the unchanged implementation releases the continuously asserted target.

**Exit:** The exact public regression fails on the old behavior because target
`active` becomes false, while the retained inputs and expected public behavior
are fixed.

### Phase 1: Temporal Transfer Guard

- Centralize temporal binding authority and apply it to transfer source IDs and
   connected-current-component coalescence.
- Add the stale-binding lifecycle counter.
- Preserve stale bindings against target rebinding while allowing required
   remapping when independently authorized coalescence removes a support ID.
- Add direct stale/fresh/equality/mixed-set tests.

**Exit:** The exact public regression and direct support tests pass with
`--no-cov`; touched Python files pass Ruff.

### Phase 2: Restart And Adversarial Matrix

- Add uninterrupted/restore equivalence around a stale transfer attempt.
- Cover count zero, counts one/two, same-zone coalescence, moving expiry,
  same-endpoint rebind, support-limit saturation, unavailable endpoint,
  out-of-order input, and callback failure.
- Verify no stale binding participates in source-set merge or active-component
   coalescence, including after `updated_at` advances through coalescence.

**Exit:** Focused support, count, persistence, and public-contract suites pass
with `--no-cov`; touched files pass Ruff and mypy.

### Phase 3: Acceptance And Conformance

- Update Section 19 and this tracker from validated evidence.
- Run full Python coverage, Ruff, strict mypy, frontend tests/build, applicable
  100-event benchmark, and diff/reference checks.
- Perform an independent read-only conformance review because the public model
  authority changes.

**Exit:** All repository gates and independent conformance review pass with no
unresolved contract divergence.

## Test Matrix

| Case                                                    | Required result                                                                                                 |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Exact production order                                  | Continuously asserted target remains active past the historical release time                                    |
| Token accepted before support update                    | Binding ignored; endpoint, `updated_at`, and transfer count unchanged                                           |
| Token accepted exactly at support update                | Transfer remains eligible                                                                                       |
| Token accepted after support update                     | Ordinary transfer remains eligible                                                                              |
| Mixed stale/fresh tokens for one support                | Support selected once from fresh token only                                                                     |
| Mixed stale/fresh tokens for several supports           | Only fresh supports coalesce and transfer                                                                       |
| Fresh linked token outside selected target path         | It remains lineage and cannot select, merge, transfer, or target-rebind support                                 |
| All sources stale, support capacity full                | No transfer or creation                                                                                         |
| All sources stale, confirmed target, capacity available | Existing bounded creation contract decides independently                                                        |
| Stale-bound source plus independent target creation     | Old binding stays on its current support; only target and unbound/eligible source tokens bind to new support    |
| Stale binding on independently coalesced loser          | Binding remaps to winner for referential integrity but cannot select the loser or target                        |
| Same-endpoint reassertion                               | Support rebinds to new episode; older bound tokens become stale                                                 |
| Stale active binding in connected component             | It cannot select or coalesce its mapped support                                                                 |
| Moving support expiry at target timestamp               | Timer-first removal wins; no revival                                                                            |
| Count zero                                              | Supports and bindings clear categorically                                                                       |
| Restore before stale attempt                            | Same support/binding/conflict/audit/policy/public result and same next-event counter delta as uninterrupted run |
| Coalescence advances support frontier                   | Tokens older than the coalescence event become stale for later binding-derived operations                       |
| Target authorization                                    | Target may acquire even when no support transfers                                                               |
| Duplicate/out-of-order target                           | No transfer and no ignored-binding counter increment                                                            |
| Validation failure                                      | No support or counter commit                                                                                    |
| Callback failure                                        | Complete accepted in-memory result, counter, and policy commit before publication error surfaces                |

The direct unit matrix belongs in `test_zone_model_supports.py`; the exact
incident and authorization-separation assertions belong in
`test_zone_model_public_contract.py`; uninterrupted/restore equivalence belongs
in `test_zone_model_persistence.py`; count-conflict inverse coverage belongs in
`test_zone_model_count.py`; and generic lifecycle projection belongs in
`test_status.py`. Existing helpers should be extended locally rather than adding
a production test hook.

## Performance And Resource Bounds

Source-token and active-token counts are already bounded. The shared predicate
adds one support lookup and one datetime comparison per bound token in existing
source-selection and active-component loops, retaining their current asymptotic
work and all support/token bounds. No new scan, history growth, or persisted
record is introduced.

Run `python benchmarks/occupancy_performance.py --events 100` against the
reference map. It must pass its current bounded-support, binding, token,
persistence, callback, fast-path, and timer hard gates. Compare output against
the pre-change tracked artifact under the same environment; investigate any
affected fast-path p99 or max regression above 20%. Replace
`PERFORMANCE_RESULTS.json` only with a complete passing run intentionally chosen
as the new tracked artifact, not with partial or failed output.

## Acceptance Criteria

1. The exact incident regression fails before and passes after the generic fix.
2. No source token older than a support's current frontier can select, coalesce,
   transfer, or target-rebind that support through binding-derived behavior;
   referential-integrity remap after independently authorized coalescence remains
   valid.
3. No linked source token outside the accepted target path can select, merge,
   transfer, or target-rebind support.
4. Fresh and equal-time on-path source transfers retain existing behavior.
5. Target acquisition remains independent from support transfer.
6. Count zero/one/two, same-zone multiplicity, conservative open-transition
   backtracking ambiguity, missed edges, stale assertions, false clears,
   unavailable input, out-of-order delivery, and restart have explicit passing
   coverage.
7. Persistence schema and Store version remain unchanged and strict restore is
   atomic.
8. Lifecycle diagnostics expose ignored stale bindings without becoming model
   evidence.
9. Full repository validation and independent conformance review pass.

## Implementation Surfaces

- `SPECIFICATION.md`
- `custom_components/predictive_controls/zone_model/supports.py`
- `tests/test_zone_model_public_contract.py`
- `tests/test_zone_model_supports.py`
- `tests/test_zone_model_count.py`
- `tests/test_zone_model_persistence.py`
- `tests/test_status.py`
- `PERFORMANCE_RESULTS.json` only when benchmark regeneration changes it

## Implementation Tracking

| Phase                             | Status   | Completed evidence                                                                                                                                                                                                                                                                                                                    | Next executable step                                              |
| --------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| 0. Authority and exact baseline   | Complete | Authority amended; `test_inc_2026_08_22_prearrival_token_cannot_release_asserted_target` proven red on unchanged code: stale support moved to the second target and public retained target released                                                                                                                                   | Preserve the frozen regression while implementing Phase 1         |
| 1. Temporal transfer guard        | Complete | Frozen incident green; 24 focused public/support tests pass; temporal and path authority, guarded rebinding, component filtering, counter bounds, and touched-file Ruff validated                                                                                                                                                     | Preserve Phase 1 behavior while adding restart/adversarial proofs |
| 2. Restart and adversarial matrix | Complete | 203 focused support/count/persistence/public/status/engine tests pass; uninterrupted/restore equality, counter delta, mixed authority, expiry, coalescence remap, validation and callback atomicity, count inverse, generic status projection, Ruff, and strict touched-file mypy validated                                           | Preserve Phase 2 behavior through complete repository gates       |
| 3. Acceptance and conformance     | Complete | Section 19 reconciled; 595 Python tests pass at 100% statement/branch coverage; repository Ruff and strict mypy pass; 29 frontend tests and build pass; 100-event benchmark passes all hard gates without an affected p99/max regression over 20%; diff check and independent read-only conformance review pass with no valid finding | None                                                              |

## Hardening Record

- Initial evidence-based draft complete.
- Adversarial hardening pass 1 complete: corrected restore authority and callback
   semantics; extended temporal authority to component coalescence; preserved
   stale bindings during independent creation; documented open-transition
   ambiguity.
- Adversarial hardening pass 2 complete: defined `updated_at` as the causal
   mutation frontier; corrected process-local counter restart semantics; bounded
   commit atomicity; specified crash, rollback, expiry, and generic status
   projection behavior.
- Adversarial hardening pass 3 complete: distinguished forbidden target
   rebinding from required coalescence remapping; fixed the helper and commit
   shape; assigned each proof to a concrete test layer; pinned exact red-test
   checkpoints and an executable benchmark gate.
- Phase 1 implementation discovery: timestamp-only filtering was falsified by
   the frozen regression because traversal authorization also carries fresh linked
   lineage outside the selected target path. Authority and implementation scope
   were corrected before further production edits.
- Phase 2 compatibility discovery: corrected transfer authority leaves fewer
   valid supports in the retained 2026-08-20 gym trace, so its former internal
   count-conflict degradation is no longer authorized. The incident's public
   contract remains unchanged: the isolated gym assertion never activates or
   emits a public edge.
- Phase 3 independent review verified the temporal and selected-path predicates,
   stale-lineage preservation, coalescence remapping, restart/callback atomicity,
   diagnostics, persistence compatibility, and both retained incident contracts.