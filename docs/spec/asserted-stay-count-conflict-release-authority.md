# Asserted-Stay Count-Conflict Release Authority

**Status:** Implemented and validated repair for
`INC-2026-08-23-master-bathroom-asserted-release`

**Affected layers:** physical episodes, zone belief, count conflict, policy,
persistence, diagnostics, and retained public regressions

**Related authority:** `REQ-GOAL-002`, `REQ-EVID-003` through `REQ-EVID-005`,
`REQ-COUNT-001`, `REQ-COUNT-003`, `REQ-COUNT-009`, `REQ-POLICY-002`,
`REQ-POLICY-003`, `REQ-STATE-003`, `REQ-PERF-001`, and `REQ-GOV-001` through
`REQ-GOV-006`

## 1. Objective

Prevent a positive-count contradiction from releasing a publicly active stay
zone while the same physical stay episode is still asserted. Preserve count
conflict as bounded diagnostic and movement-authority health state. Preserve
ordinary probability-driven release after stable clear or unknown/unavailable
input, and preserve immediate categorical clearing when authoritative count
becomes zero.

The public outcome is exact: `active` remains on and emits no `released` edge
while the count-conflicted stay episode has not stably cleared and has not become
unknown/unavailable. Light or actuator state is not evidence and is outside this
repair.

## 2. Verified Current State

The retained evidence record is
`tests/fixtures/zone_model/INC-2026-08-23-master-bathroom-asserted-release.md`.
The controlling production path is:

1. `CountConflictTracker.evaluate` selects at least `N` independent outside
   supports and crosses the target profile release-dwell deadline.
2. `ZoneModelEngine._apply_count_conflicts` calls
   `PhysicalEpisodeTracker.apply_count_conflict` and
   `ZoneBeliefFilter.apply_health_degraded`.
3. Episode degradation closes traversal authority and changes the filter to
   `degraded_asserted`, removing the current assertion floor.
4. `ZoneModelEngine._release_due_policies` and `ZonePolicy.evaluate` use only
   belief threshold and dwell. Neither receives current zone-wide episode state
   at a timer frontier.
5. The filter therefore falls below `0.30`; policy completes the shared
   `stay_presence` 120-second dwell and emits `released` while raw mmWave is on.

The exact regression fails against unchanged behavior at the public assertion
`target_policy.active`.

## 3. Authority Conflict And Amendment

Current `REQ-EVID-005`, `REQ-COUNT-003`, `REQ-COUNT-009`, and
`REQ-POLICY-003` permit persistent outside supports to remove the asserted-stay
floor and begin normal release. That contract cannot produce the requested
outcome. This repair therefore amends the sole authority before production code
changes.

The revised authority separates two decisions:

- **Inference and movement health:** count conflict may mark an asserted stay
  episode health-degraded, close its traversal authority, remove its belief
  floor, and retain bounded diagnostics.
- **Public release eligibility:** the same count conflict is not local absence.
   While that episode remains physically asserted or is inside stable-clear
   confirmation, it vetoes creation or continuation of policy release dwell.
   Stable clear or unknown/unavailable state removes the veto. Count zero
   bypasses it categorically.

This is a deliberate false-off versus stale-on choice. Given no local clear,
unavailable observation, or outward movement, the system cannot distinguish a
person held by a correct sensor from a stuck sensor. It must not use remote
count consistency to choose absence and turn off an occupied room.

## 4. Scope And Non-Goals

### In scope

- all shared `stay_pir` and `stay_presence` nodes;
- active policy phases backed by ordinary evidence acquisition;
- count-conflicted episodes that are still raw asserted or inside stable-clear
   confirmation, including restored v4 state;
- release-pending cancellation, deterministic timer behavior, diagnostics, and
  focused persistence tests; and
- exact incident, inverse, and repository acceptance gates.

### Non-goals

- no room, entity, person, household member, or incident-time branching;
- no change to support creation, transfer, coalescence, count-conflict selection,
  conflict dwell, belief decay calibration, thresholds, or policy dwell;
- no use of light/output state, policy state, prediction, callback count, or
  same-state callbacks as occupancy evidence;
- no synthetic refresh or reacquisition edge;
- no new public entity; and
- no automation-side workaround.

## 5. Invariants

1. Count zero still clears every active output immediately.
2. A stable clear remains calibrated weak absence. Once stable clear is emitted,
   the count-conflict assertion veto no longer applies and ordinary threshold
   plus full release dwell starts or continues from that evaluation.
3. Unknown or unavailable is neutral rather than clear, but either state removes
   the claim that a stay sensor is currently asserted. Both use the existing
   unavailable-context belief decay, after which ordinary release dwell remains
   authoritative.
4. Elapsed wall time, assertion trust-horizon expiry, timer reevaluation, and
   remote support changes do not by themselves remove the veto while raw stay
   state remains asserted.
5. A newly diagnosed count conflict cancels any existing release-pending
   timestamp for that active zone. Dwell cannot accumulate behind the veto.
6. Support loss restores the same asserted episode and belief immediately under
   existing `REQ-COUNT-009` recovery behavior; it emits no synthetic positive,
   acquisition, refresh, or traversal edge.
7. Count-conflict health degradation continues to close traversal authority and
   remains visible in episode, conflict, policy-audit, status, and lifecycle
   diagnostics.
8. Transition and entry profiles are unchanged. Interaction pulses remain finite
   evidence and have no indefinitely asserted raw state.
9. Same-zone multiplicity remains possible; count never forces exactly `N`
   active zones.
10. State and callback work remain deterministic and bounded by configured
    physical nodes and zones.
11. A count-degraded episode that goes raw off and reasserts inside its
   stable-clear window remains the same degraded episode. It cancels clear
   confirmation, remains held, retains closed traversal authority, contributes
   no new likelihood, and cannot create a structurally invalid asserted state
   with retained degradation fields.

## 6. Policy Contract

For zone `z` at frontier `t`, define `asserted_count_conflict_hold(z, t)` as true
iff at least one physical episode in `z`:

- uses a shared profile whose role is `stay`;
- is the current episode for its physical node;
- has `degradation_reason == "count_conflict"` and `health_warning == true`;
- remains in episode status `degraded` or `clearing`; and
- has not reached stable-clear status `clear` or neutral-availability status
   `unavailable` after degradation.

The engine derives this value from bounded current episode state. It is not
persisted separately. One helper derives a `frozenset[str]` of held zones once
per model frontier in $O(P)$ time and $O(Z)$ bounded space, where $P$ is physical
nodes and $Z$ is zones. Release paths use set membership; they must not rescan all
episodes separately for every zone.

For ordinary active policy:

1. If `asserted_count_conflict_hold` is true, policy remains active, sets
   `pending_release_since = None`, emits no public event, and records reason
   `asserted_stay_hold` when a normal policy evaluation row is retained.
2. Otherwise existing belief threshold, interpolated crossing time, and profile
   release dwell apply unchanged.
3. `apply_count_zero` remains higher priority and releases immediately.
4. Prediction lease expiry remains governed by prediction provenance and is not
   converted into an evidence-acquired asserted-stay hold.

The hold must be checked in both policy paths:

- before `_release_due_policies` can publish a due timer release; and
- in `_evaluate_policies`, so any pending dwell is canceled and ordinary event
  evaluations cannot start it while the hold exists.

## 7. Event Ordering

At each accepted external or timer frontier:

1. advance episode, belief, traversal, support, conflict, and prediction state
   under existing ordering;
2. apply any newly crossed count conflict, including episode health degradation,
   belief context transition, and traversal synchronization;
3. derive zone holds from the resulting current episode states;
4. prevent due release for held zones;
5. evaluate policy with the same hold, canceling pending dwell if needed; and
6. persist and publish under existing edge-gated runtime behavior.

Stable clear is authoritative only when the episode tracker emits its existing
stable-clear effect. A raw off edge moves the count-degraded episode to
`clearing` while preserving its health metadata, so the profile clear window
does not start release dwell. If the sensor reasserts during that window, the
same episode returns to `degraded`, not ordinary `asserted`; its hold continues
without accumulated release time and traversal authority remains closed.

Unknown or unavailable state moves the episode to `unavailable` and removes the
hold in the same atomic observation that applies the unavailable belief context.
Count zero remains an earlier categorical reset.

On external observations, `_release_due_policies` runs before the new raw event
is applied. It must therefore derive the hold from the pre-event current episode
state. A raw off arriving exactly when release would otherwise be due remains
blocked, then enters `clearing`; stable clear at the later episode deadline is
the first frontier eligible to start ordinary release dwell. On timer advance,
count conflict is applied before normal policy evaluation, so the same derived
hold cancels pending dwell at the diagnosis frontier.

## 8. Persistence, Upgrade, And Rollback

No Store schema, inference schema, or serialized field changes are required.
Store version remains `7` and target schema remains `zone-belief-v4`.

An existing v4 snapshot may contain:

- a count-degraded asserted episode;
- a matching `CountConflictState` with `degraded_at`;
- degraded asserted belief; and
- active policy with or without `pending_release_since`.

Restore retains those facts. On first advancement, the derived hold prevents
release and clears restored pending dwell through ordinary policy evaluation.
No bootstrap edge is emitted. A snapshot already made inactive by the old bug is
not synthetically reacquired on restore; fresh valid local evidence or a physical
interaction remains required by `REQ-POLICY-001`.

Restore at or after a pending release deadline applies the hold before any
ordinary release transition, including `emit_events=False` advancement. A crash
before the pending-cancel state is saved may restore the old pending timestamp,
but the first deterministic advancement cancels it again; dwell never resumes
from that stale timestamp after stable clear or unknown/unavailable.

Rollback to the preceding release remains possible because serialized state is
unchanged. Rollback reintroduces the false-release behavior and is therefore an
operational fallback, not semantic preservation.

## 9. Diagnostics

Existing conflict and reliability diagnostics remain authoritative:

- `CountConflictState.degraded_at` still means the contradiction crossed dwell;
- episode status, `health_warning`, and `degradation_reason` remain
  count-degraded;
- the `stuck_count_conflict` audit row remains `health_degraded` with
  `reliability_result == "degraded"`;
- support-loss recovery remains `stuck_conflict_cleared` / `recovered`; and
- no new lifecycle counter is required.

Normal policy audit rows may use reason `asserted_stay_hold`; they carry no new
evidence kind and do not claim another sensor observation. Status/UI transport
requires no schema change because policy reasons are strings.

## 10. Alternatives

### Remove count-conflict degradation entirely

Rejected for this repair. It would also restore traversal authority and erase a
useful bounded stuck-sensor diagnostic. The incident only proves that remote
count contradiction lacks public release authority while local stay assertion
remains current.

### Treat conflict as diagnostic-only everywhere

Rejected because a plausibly stuck sensor should not continue authorizing
neighbor movement or count lineage. Preserving degradation for inference while
adding an explicit public release veto retains that separation.

### Release after stay assertion trust horizon

Rejected. A stay sensor can correctly remain asserted for an occupied room far
beyond its trust horizon. Elapsed time is not a clear, unavailable state, or
outward observation and cannot distinguish stuck hardware from presence.

### Require only an additional fixed timeout

Rejected. It delays rather than removes the unsupported absence decision,
introduces an uncalibrated constant, and still turns remote count consistency
into local absence.

### Fix the Home Assistant automation

Rejected. The automation correctly consumed the public off edge. The model owns
release authority and must be repaired at the controlling layer.

## 11. Implementation Surfaces

- `SPECIFICATION.md`: amend evidence, count, policy, acceptance, and Section 19
  conformance text.
- `zone_model/episodes.py`: preserve valid degraded status for raw-off/reassert
   flaps inside stable-clear confirmation.
- `zone_model/engine.py`: add a side-effect-free held-zone projection over the
   current episode tuple, pass one projection to `_release_due_policies`, and
   pass the same projection to `_evaluate_policies` at each frontier.
- `zone_model/policy.py`: add an explicit boolean `asserted_stay_hold` evaluation
   input. In the ordinary evidence-active phase, process it before the low-belief
   branch, cancel/prevent release dwell, and retain deterministic reason
   `asserted_stay_hold`. Do not apply it to predicted-phase lease expiry or
   `apply_count_zero`.
- `tests/test_zone_model_count.py`: preserve the exact public incident and count
  inverses.
- `tests/test_zone_model_policy.py`: unit boundaries for hold, dwell cancellation,
  stable clear, unavailable, and prediction separation.
- `tests/test_zone_model_persistence.py`: restored degraded assertion with pending
  dwell cannot release or extend old pending time.
- retained fixtures and requirement matrix: map the replacement behavior to the
  amended requirements.

## 12. Validation Matrix

Required focused cases:

1. exact August 23 public incident remains active and emits no release;
2. two outside supports still cross conflict dwell, health-degrade the episode,
   close traversal, and record existing diagnostics;
3. held conflict cancels a pre-existing pending release;
4. raw off before stable-clear deadline remains held;
5. raw off/reassert inside stable-clear confirmation remains one degraded held
   episode, does not reopen traversal, and serializes/restores validly;
6. stable clear removes the hold and requires a fresh full release dwell;
7. unknown/unavailable at and before the due-release frontier removes the hold
   and uses unavailable-context decay plus
   dwell;
8. count zero releases immediately despite a hold;
9. support loss restores asserted belief without a public edge;
10. one/provisional support cannot create a conflict;
11. same-zone supports coalesce and do not fabricate outside count;
12. transition/entry sensor degradation behavior is unchanged;
13. interaction acquisition and ordinary release remain unchanged;
14. out-of-order and duplicate input cannot remove the hold;
15. restart during conflict dwell preserves its deadline;
16. restart after degradation before, at, and after the old due-release frontier
   derives the hold, clears pending dwell, and emits no bootstrap edge;
17. callback failure before save may replay pending cancellation without release
   or duplicate public events; and
18. deterministic callback and 100-event benchmark bounds remain satisfied.

Existing test disposition:

- split `test_t05_t06_health_degradation_never_extends_pending_release` into an
   unchanged transition-health case and a count-conflicted stay case;
- replace the old final assertion in
   `test_two_settled_supports_degrade_stuck_assertion_only_after_full_dwell` that
   expected eventual release while asserted with indefinite active hold plus a
   stable-clear release boundary; and
- retain all support selection, dwell, degradation, traversal closure, recovery,
   and diagnostic assertions in those tests.

Focused editing gate:

```bash
.venv/bin/python -m pytest -q --no-cov \
  tests/test_zone_model_count.py \
  tests/test_zone_model_policy.py \
  tests/test_zone_model_persistence.py
.venv/bin/python -m ruff check \
  custom_components/predictive_controls/zone_model/engine.py \
  custom_components/predictive_controls/zone_model/policy.py \
  tests/test_zone_model_count.py \
  tests/test_zone_model_policy.py \
  tests/test_zone_model_persistence.py
```

Final gate:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
npm run test:frontend
npm run build:frontend
.venv/bin/python benchmarks/occupancy_performance.py --events 100 \
  --output /tmp/predictive-controls-performance.json
git diff --check
```

## 13. Acceptance Criteria

1. The exact incident test fails on unchanged code at public `active`, then
   passes without changing retained factual inputs or public expectation.
2. No count conflict can start or retain release dwell for an active zone while
   its same count-degraded stay episode remains physically asserted or is inside
   stable-clear confirmation.
3. Stable clear, unknown/unavailable, and count zero retain their specified
   distinct release behavior.
4. Count conflict still closes traversal authority and retains bounded existing
   diagnostics.
5. No persistence schema or public entity change occurs.
6. Held-zone projection performs one bounded episode scan per frontier and does
   not alter asymptotic callback work.
7. All focused, full, static, frontend, benchmark, and diff gates pass.
8. Independent final review finds no room-specific logic, evidence feedback,
   forced room assignment, hidden stale-state extension, or authority mismatch.

## 14. Tracking

| Phase                    | Status   | Completed evidence                                                                                                                                                                                                | Next executable step                                                     |
| ------------------------ | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| 1. Incident regression   | Complete | Exact test fails on public `active` against unchanged behavior; retained evidence record added.                                                                                                                   | Keep factual inputs and public expectation immutable.                    |
| 2. Authority amendment   | Complete | `REQ-GOAL-001`, `REQ-EVID-005`, `REQ-COUNT-003`, `REQ-COUNT-009`, `REQ-POLICY-002`, and `REQ-POLICY-003` separate count health from public release authority.                                                     | Keep the amended requirements authoritative over historical design text. |
| 3. Policy implementation | Complete | Engine derives one bounded held-zone projection; both release paths apply it; policy cancels pending dwell; degraded clear/reassert remains structurally valid.                                                   | Preserve count-zero and predicted-phase priority.                        |
| 4. Focused inverses      | Complete | Exact incident plus stable-clear, flap, unavailable, zero-count, pending-cancel, and restart boundaries pass in 162 focused tests.                                                                                | Retain the exact incident inputs and public edge assertion.              |
| 5. Final validation      | Complete | 603 Python tests pass at 100% branch coverage; Ruff, strict mypy, 29 frontend tests/build, bounded 100-event benchmark, and `git diff --check` pass; independent review found no defects or authority mismatches. | Preserve the incident and inverse corpus through release.                |