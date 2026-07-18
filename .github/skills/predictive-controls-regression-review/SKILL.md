---
name: predictive-controls-regression-review
description: "Use for every Predictive Controls failure, incident, false activation, false release, stale active state, missed activation, wrong probability, traversal defect, sensor-profile change, threshold change, model redesign, or incident-derived fix. Requires an exact public regression, independent investigation, specification review, and implementation review."
argument-hint: "Describe the incident, wrong public behavior, or proposed model/profile change"
---

# Predictive Controls Regression Review

## Required Sources

Read `SPECIFICATION.md`. It is the only product and model authority. During an
active migration, also read the global rules and current phase in
`MIGRATION_PLAN.md`; the plan cannot override the specification.

## Non-Negotiable Incident Order

For every report that something did not work properly, execute these gates in
order. A general redesign without one observed incident starts at Gate 4, but
must still create prospective target tests before production implementation.

1. **Capture the failure as a public test.** Use retained production event times,
   material order, physical map, sensor states/settings, count, pre/post zone
   belief, traversal context, policy state, and expected public edge. Never invent
   missing timestamps. During pre-cutover migration, target-only expectations may
   call the shadow/test target engine while legacy public assertions stay intact.
2. **Prove the regression.** Run only the new test against unchanged controlling
   behavior. It must fail on `active`, `prelight`, or `refresh`, or on target zone
   belief when that is the reported contract. If it passes or fails for another
   reason, repair the reproduction. Freeze factual inputs and public expectations.
3. **Investigate independently.** Launch a fresh stateless read-only subagent with
   verified facts and file locations, but no preferred cause or fix. Require a
   code-grounded root cause and relevant `REQ-*` IDs. The parent independently
   checks the controlling path and reconciles disagreements with evidence.
4. **Propose before editing.** State the falsifiable mechanism, owning layer,
   smallest generic solution, alternatives rejected, calibration impact, and
   expected public effect. A redesign compares at least two approaches.
5. **Verify the proposal independently.** Launch a new context-isolated read-only
   subagent with facts, failing test, proposal, `SPECIFICATION.md`, and the current
   migration phase when applicable. Require explicit `PASS` or `FAIL`, requirement
   matrix, conflicts, two-occupant analysis, sensor-fault/restart analysis,
   calibration risks, and missing adversarial tests.
6. **Iterate until conformant.** `FAIL` blocks implementation. Redesign and submit
   to another fresh reviewer. If the desired behavior conflicts with the
   specification, obtain explicit user agreement and amend `SPECIFICATION.md`
   before another review.
7. **Implement only the verified proposal.** Make the smallest generic change at
   the controlling layer and immediately run the exact focused regression.
   Material design deviation returns to Gate 4.
8. **Review implementation independently.** Launch a different fresh read-only
   reviewer with the approved proposal, actual diff, regression, specification,
   and phase constraints. Require `PASS` or `FAIL` before broad validation.
9. **Validate adversarially and completely.** Add applicable inverse, boundary,
   disconnected, flap/alias, stuck, unavailable, missed-edge, two-occupant,
   same-zone, out-of-order, restart, timer-cadence, and performance cases. Run all
   repository quality gates from `MIGRATION_PLAN.md`.

## Evidence Record

Before diagnosis, record:

1. affected public entity/event and exact wrong or missing edge;
2. expected and actual public behavior;
3. material event timestamps and processing order;
4. physical-node, zone, role, profile, hardware reset/clear setting, and graph
   adjacency;
5. authoritative count and availability;
6. pre/post zone belief, active state, threshold, dwell, health state, and policy
   reason;
7. current/recent adjacent episodes and traversal tokens;
8. automation branch only to determine whether the consumer received the edge;
9. provenance of each fact: retained live data, repository configuration, or
   assumption; and
10. the cheapest trace value or test that would disprove the leading hypothesis.

Use `INC-YYYY-MM-DD-short-symptom` when a durable incident identity is useful.
Live Home Assistant diagnosis is read-only through approved deployment scripts.

## Controlling Layers

Choose the lowest layer that computes the wrong result:

| Layer | Controlling question |
| --- | --- |
| `MAP_PROFILE` | Are physical aliases, role, profile, adjacency, hardware timing, or graph timing wrong? |
| `EPISODE` | Did one physical node create the wrong edge, clear, flap group, trust state, or health state? |
| `ZONE_BELIEF` | Did local likelihood or elapsed context decay produce the wrong filtered probability? |
| `TRAVERSAL` | Did current/recent adjacency, leading edge, missed edge, token expiry, or reacquisition authorize incorrectly? |
| `COUNT` | Did count 0, positive-count eligibility, boundary context, or invalid count behave incorrectly? |
| `POLICY` | Did correct belief/context produce the wrong hysteresis, dwell, refresh, or edge? |
| `PREDICTION` | Did a downstream lease or learning update violate separation or graph bounds? |
| `PERSISTENCE` | Did bootstrap, restore, map compatibility, schema migration, or elapsed advancement change the result? |
| `PUBLICATION` | Was the correct result projected with the wrong entity/event edge or cadence? |
| `AUTOMATION` | Did a simple consumer ignore or mishandle a correct public edge? |
| `EXTERNAL` | Did hardware, Home Assistant delivery, timestamping, or unavailable data cause the symptom? |

## Requirement Matrix

Every proposal records:

| Item | Required content |
| --- | --- |
| Public contract | Wrong or missing `active`, `prelight`, `refresh`, or target belief behavior |
| Governing requirements | Relevant `REQ-GOAL`, model-layer, public, state, performance, and governance IDs |
| Current discrepancy | Exact behavior that conflicts with or exposes an ambiguity in those requirements |
| Migration disposition | Preserve, replace, or retire existing behavior/test, with named replacement |
| Expected effect | Public timeline and diagnostic change after the proposal |

If no requirement decides expected behavior, it is a design gap. Amend the sole
specification after explicit agreement; do not infer a requirement from current
code or tests.

## Model Review Criteria

For a model, profile, traversal, policy, or threshold proposal, compare at least
two approaches against:

1. probabilistic or decision-theoretic meaning;
2. correlated evidence and double-counting risk;
3. counts zero, one, and two, including independent fronts and same-zone
   multiplicity;
4. ordinary graph movement, an open transition sensor, backtracking, and missed
   edges;
5. isolated false positives, false clears, flaps, aliases, stuck assertions,
   unavailable state, and hardware reset behavior;
6. out-of-order input and restart during every relevant frontier;
7. calibration coupling and whether constants are shared profiles;
8. determinism, bounded state, callback latency, persistence, and diagnostics;
9. false activation, false release, missed activation, stale-active duration,
   chatter, and refresh behavior; and
10. compatibility and rollback within the current migration phase.

## Mandatory Rejection Checks

Reject or redesign a proposal if it:

- hard-codes a room, node, entity, person, household member, or incident time;
- treats callback count, aliases, one open assertion, or timer reevaluation as
  independent evidence;
- uses prediction, light/output state, or policy state as zone-belief evidence;
- creates persistent person identity or requires a globally unique assignment;
- forces positive-count beliefs to exactly N active zones or erases strong local
  evidence to satisfy count;
- lets an unrelated remote event directly invalidate local evidence;
- uses elapsed time without a stored profile/context transition and idempotent
  timestamp advancement;
- allows a stuck transition node to authorize neighboring arrivals forever;
- introduces thresholds or decay constants from one room/incident without corpus
  calibration and boundary tests;
- moves a model defect into Home Assistant automation YAML;
- changes a frozen public incident test to accommodate implementation; or
- removes a legacy internal test without its named target replacement and
  requirement mapping.

Probability-driven release is valid when it follows the declared zone filter,
shared lower threshold, bounded sensor trust, and release-confirmation dwell.
Low raw sensor confidence or a timer alone is not an equivalent release model.

## Validation Expectations

After the focused regression passes:

- test inverse activation/release direction;
- test exact threshold boundaries and dwell cancellation;
- test timer-cadence invariance;
- test disconnected and missed-edge paths;
- test hallway -> room A -> still-open hallway -> room B;
- test two occupants on independent paths and sharing one room;
- test aliases, flaps, stuck transition/stay sensors, and unavailable recovery;
- test out-of-order rejection and restart at active frontiers;
- test count 0 and positive-count no-room-invention;
- prove prediction cannot change normal `active`;
- verify compact diagnostics explain every public edge; and
- run the full Python, coverage, Ruff, mypy, frontend, 100-event benchmark, and
  diff/reference gates.

Preserve each reviewer's verdict and requirement findings in the phase report.