---
name: predictive-controls-regression-review
description: "Use for any reported Predictive Controls bug, incorrect behavior, production incident, false activation, false release, stale active state, missed activation, wrong probability, traversal defect, warning defect, or incident-derived fix. Requires live evidence as available, root-cause diagnosis, a temporary working spec hardened by exactly three adversarial passes, exact retained regression proof, tracked implementation, full validation, final SPECIFICATION.md reconciliation, and working-spec deletion."
argument-hint: "Describe the incident, wrong public behavior, or proposed model/profile change"
---

# Predictive Controls Regression Review

## Required Sources

Read `SPECIFICATION.md`. It is the only product and model authority.

## Mandatory Incident Workflow

For every reported production failure, complete these gates in order. Do not edit
production behavior before Gates 1-5 are complete.

1. **Establish authority and evidence.** Read `SPECIFICATION.md`, the owning code,
   nearby tests, and relevant retained incident regression tests and evidence.
   Fetch current runtime data when
   it can distinguish causes. Home Assistant access is read-only through approved
   scripts in the homelab repository. Record provenance and never invent missing
   timestamps or state.
2. **Diagnose the root cause.** Locate the lowest controlling layer. State one
   falsifiable diagnosis, its supporting evidence, contributing conditions, and
   the cheapest check that could disprove it. Do not confuse deployment drift or
   downstream automation behavior with a model cause.
3. **Create a temporary working implementation specification.** Write or update
   `docs/spec/<incident-or-change-name>.md`. Use
   `.github/skills/spec-writer/SKILL.md`. Include the evidence record, diagnosis,
   governing `REQ-*` IDs, objective, non-goals, invariants, exact event ordering,
   alternatives, compatibility, persistence, rollout/rollback, implementation
   phases, regression plan, acceptance gates, and a phase tracking table. The
   first executable phase is `Regression proof`; it precedes all implementation
   phases and records the exact test command, expected failure signature, actual
   pre-fix result, post-fix result, and evidence provenance.
4. **Harden the specification.** Complete exactly three full critique-and-rewrite
   passes required by the spec-writer skill: factual/architectural,
   failure/operations, and implementation/proof. Resolve grounded criticism in
   the artifact itself. A public-contract or calibration change receives an
   independent read-only review before implementation.
5. **Capture and prove the failure.** Add the smallest public regression using
   retained production event times, material order, physical map, sensor
   states/settings, count, belief, traversal, policy state, and expected public
   edge or diagnostic contract. Run it against unchanged controlling behavior;
   it must fail for the diagnosed reason. Freeze its factual inputs and public
   expectations after proof, and record the command and observed failure
   signature in the implementation spec before production edits.
6. **Implement the hardened specification.** Use
   `.github/skills/spec-implementation-tracking/SKILL.md`; keep exactly one phase
   in progress and update validated evidence and the next executable step. Make
   the smallest generic fix and avoid room-, entity-, person-, or
   incident-specific logic.
7. **Validate from narrow to broad.** Immediately rerun the exact regression
   after the first production edit, then the nearest inverse and boundary tests,
   touched-file lint, complete retained incident corpus, full coverage, Ruff,
   mypy, frontend, applicable benchmark, and diff/reference gates. Record each
   completed gate in the implementation spec.
8. **Reconcile authority and hand off.** Update the appropriate normative
   requirements and Section 19 implementation-conformance snapshot in
   `SPECIFICATION.md`, plus directly conflicting current-state documentation.
   After its acceptance gates pass, verify `SPECIFICATION.md` contains the final
   contract and validated result, then delete the completed working spec. The
   exact regression test is the permanent incident artifact. Record deployment
   or operational cleanup separately from code correctness.

If the hardened design conflicts with `SPECIFICATION.md`, obtain explicit user
agreement and amend the conflicting authority before Gate 6. Gate 8 still
performs final reconciliation against the implementation and validated evidence.

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

Use `INC-YYYY-MM-DD-short-symptom` for the temporary working spec when an
incident identity helps implementation tracking. Preserve that identity in the
retained regression test when useful.
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
| Test disposition | Preserve, replace, or retire existing behavior/test, with named replacement |
| Expected effect | Public timeline and diagnostic change after the proposal |

If no requirement decides expected behavior, it is a design gap. Amend the sole
specification after explicit agreement; do not infer a requirement from current
code or tests.

## Escalated Model Review Criteria

When an unresolved model/profile/threshold choice is explicitly escalated,
compare alternatives against:

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
10. persistence compatibility and rollback behavior.

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
- removes an internal test without its named replacement and
  requirement mapping.

Probability-driven release is valid when it follows the declared zone filter,
shared lower threshold, bounded sensor trust, and release-confirmation dwell.
Low raw sensor confidence or a timer alone is not an equivalent release model.

## Validation Expectations

Preserve the exact regression test and run the nearest discriminating inverse or
boundary cases while editing. Before handoff, run the complete retained incident
corpus, adversarial matrix, full Python coverage, Ruff, mypy, frontend,
applicable 100-event benchmarks, and diff/reference checks. The final report must
name the evidence provenance, diagnosed cause, working-spec deletion, retained
regression-test path, red/green result, validation results, canonical
specification update, and remaining deployment work.
