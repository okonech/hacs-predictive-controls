---
name: predictive-controls-regression-review
description: "Use for a reported Predictive Controls production incident, false activation, false release, stale active state, missed activation, wrong probability, traversal defect, or incident-derived fix. Uses an exact public regression and a quick focused fix loop; independent review is reserved for unclear causes, specification/public-contract changes, and final migration conformance."
argument-hint: "Describe the incident, wrong public behavior, or proposed model/profile change"
---

# Predictive Controls Regression Review

## Required Sources

Read `SPECIFICATION.md`. It is the only product and model authority. During an
active migration, also read the global rules and current phase in
`MIGRATION_PLAN.md`; the plan cannot override the specification.

## Incident Fix Loop

For every reported production failure, use this short loop. Routine work in an
already-approved migration phase follows `MIGRATION_PLAN.md`, not this incident
workflow.

1. **Capture the failure as a public test.** Use retained production event times,
   material order, physical map, sensor states/settings, count, pre/post zone
   belief, traversal context, policy state, and expected public edge. Never invent
   missing timestamps. During pre-cutover migration, target-only expectations may
   call the shadow/test target engine while legacy public assertions stay intact.
2. **Prove the regression.** Run only the new test against unchanged controlling
   behavior. It must fail on `active`, `prelight`, or `refresh`, or on target zone
   belief when that is the reported contract. If it passes or fails for another
   reason, repair the reproduction. Freeze factual inputs and public expectations.
3. **Locate the controlling layer.** Form one falsifiable local cause from the
   failing test and nearest owning code. Use one read-only subagent only if the
   cause remains unclear after local inspection.
4. **Implement the smallest generic fix.** State the governing `REQ-*` IDs and
   avoid room-, entity-, person-, or incident-specific logic. A conflict with
   `SPECIFICATION.md` requires user agreement before implementation.
5. **Validate quickly.** Run the exact regression with `--no-cov`, plus at most
   one nearest inverse or boundary test when it materially distinguishes the
   fix. Lint changed files. Stop there during an active migration.
6. **Escalate only when necessary.** Independent proposal review is required for
   a specification/public-contract change or unresolved calibration choice.
   Independent implementation review and exhaustive adversarial/repository gates
   occur once at final migration stabilization, not after each incident or phase.

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

## Escalation Requirement Matrix

Only a proposal escalated for a specification/public-contract change or
unresolved calibration choice records:

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

## Escalated Model Review Criteria

At final migration stabilization, or when an unresolved model/profile/threshold
choice is explicitly escalated, compare alternatives against:

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

During migration, preserve the exact regression and run only the nearest
discriminating inverse or boundary case. Record broader applicable cases for the
final stabilization pass rather than implementing or running all of them after
each fix. At final stabilization, run the complete retained incident corpus,
adversarial matrix, full Python coverage, Ruff, mypy, frontend, 100-event
benchmarks, diff/reference checks, and one independent conformance review.