---
name: predictive-controls-regression-review
description: 'Use for every Predictive Controls regression, reported error, false activation, false shutoff, wrong keep_on state, missed activation, incorrect prediction, occupancy probability defect, movement-track defect, policy threshold change, inference redesign, or incident-derived fix. Reviews evidence and proposed changes against the canonical docs/spec contracts before production edits, requires a generic retained public-contract regression, and rejects room-specific or probabilistically incoherent workarounds.'
argument-hint: 'Describe the incident, regression, wrong prediction, or proposed model/policy change'
---

# Predictive Controls Regression Review

## Purpose

Use this workflow to determine what failed, which project rule controls the
behavior, and whether a proposed fix improves the general model rather than only
the reported room or trace.

This skill governs diagnosis and change design. It does not assume the current
implementation or an existing test is correct.

## Required Source

Before analysis or edits, read `docs/spec/README.md`,
`docs/spec/goals-and-principles.md`, and `docs/spec/change-governance.md`.
Then load only the owning technical contract:

- observation, occupancy, duration, restart, or persistence:
  `docs/spec/occupancy-and-evidence.md`;
- tracks, relocation, prediction, or learning:
  `docs/spec/movement-and-prediction.md`;
- activation, keep-on, release, public entities, or diagnostics:
  `docs/spec/automation-policy-and-observability.md`.

If the requested behavior conflicts with the canonical specification, stop the
production change and present the conflict. Amend the specification first only
after the user agrees to the new design.

## When to Use

- A light turned on, failed to turn on, turned off, or failed to turn off at the
  wrong time because of Predictive Controls output.
- `activation_plausible`, `keep_on`, or `prelight_plausible` exposed an
  unexpected state or edge.
- Occupancy posterior, movement evidence, directional context, prediction,
  learning, persistence, or diagnostics appear wrong.
- A sensor flap, stuck sensor, missing motion event, interleaved occupant path,
  restart, or map change causes a regression.
- Any proposal changes a likelihood, prior, timing rule, threshold, release
  cause, evidence lifetime, prediction lease, or exact-state invariant.
- A change is motivated by one named room or one production incident.

## Guardrails

- Do not make a production edit before completing Stages 1 through 4.
- Do not accept current code, tests, README text, or historical specs as proof
  that behavior is intended.
- Keep live Home Assistant access read-only. Use only approved deployment access
  scripts when they are available; never call services, fire events, reload the
  integration, or mutate live state during diagnosis.
- Never solve an inference or policy defect in Home Assistant automation YAML.
- Never add a room name, entity ID, or incident-specific timeout to production
  inference or policy code.
- Never treat prediction as occupancy evidence.
- Never treat periodic reevaluation of one sensor state as independent evidence.
- Never release `keep_on` from uncertainty, elapsed time, local clear, or low
  marginal alone.

## Stage 1: Establish the Incident

Record facts before drawing a causal conclusion:

1. Identify the affected public entity and exact wrong edge or missing edge.
2. Record expected and actual public behavior.
3. Capture only material event order, event time, entity state, mapped node and
   zone, occupant count, pre/post marginals, movement alternatives, policy gates,
   latch state, prediction leases, and automation trace branch.
4. State which facts came from retained live state/history/trace/audit, which
   came from repository configuration, and which remain assumptions.
5. If physical adjacency matters, verify the map against the available physical
   layout rather than inferring geography from names.

Use this incident identity format when a durable report is useful:
`INC-YYYY-MM-DD-short-symptom`.

Do not collect broad logs after the controlling event and policy decision are
known. Prefer the smallest evidence set that can falsify the leading causal
hypothesis.

## Stage 2: Classify the Controlling Layer

Choose one primary category and any contributing categories:

| Category | Controlling question |
| --- | --- |
| `OBSERVATION` | Did one physical entity contribute the wrong likelihood, duration, freshness, or corroboration? |
| `OCCUPANCY_MODEL` | Did the exact posterior update, count conservation, normalization, or evidence competition fail? |
| `MOVEMENT` | Did graph topology, timing, directional context, or missed-movement attribution fail? |
| `PREDICTION` | Did a forward candidate, branch probability, lease, cancellation, or learning update fail? |
| `POLICY` | Did correct inference produce the wrong activation, latch, release, or recovery decision? |
| `PERSISTENCE` | Did restart, restore, migration, bootstrap, or map compatibility change the result? |
| `MAP` | Is a node, binding, role, occupancy behavior, adjacency, or timing declaration wrong? |
| `AUTOMATION` | Did a consumer violate the three-entity contract or execute the wrong branch? |
| `EXTERNAL` | Did Home Assistant delivery, hardware state, timestamping, or unavailable data cause the symptom? |

Step from wiring to the nearest code that directly computes the wrong result.
For example, an entity platform usually projects state; it rarely owns an
incorrect release decision.

## Stage 3: Build the Requirement Matrix

Create a compact matrix before proposing a fix:

| Item | Required content |
| --- | --- |
| Public contract | Wrong or missing `activation_plausible`, `keep_on`, or `prelight_plausible` edge |
| Governing goals | Relevant `GOAL-*` IDs |
| Model rules | Relevant `MODEL-*`, `EVID-*`, `MOVE-*`, or `PRED-*` IDs |
| Policy rules | Relevant `POL-*` IDs |
| Governance | Relevant `GOV-*` IDs |
| Current discrepancy | Exact behavior that violates or exposes ambiguity in those rules |

If no requirement clearly decides the expected behavior, this is a design gap,
not yet an implementation bug. Compare alternatives and amend the specification
before editing production code.

## Stage 4: Review Model Quality

### 4.1 State one falsifiable causal hypothesis

Name the exact mechanism, such as:

- a stale asserted state was excluded from release safety;
- one entity episode was counted more than once;
- a remote observation moved the wrong anonymous occupant;
- path mass lost its origin before policy evaluated release;
- a policy threshold released a correctly ambiguous posterior;
- a prediction lease fed back into occupancy;
- restore reapplied an already integrated likelihood factor.

Also name the cheapest test or trace value that would disprove it.

### 4.2 Identify the mathematical layer

For each proposed change, explicitly state whether it changes:

- an observation likelihood;
- a correlated duration likelihood;
- a transition prior;
- state-space identity or normalization;
- directional context or movement evidence;
- posterior predictive branch probability;
- automation policy only;
- persistence or bootstrap semantics.

A change belongs in one layer. If it crosses layers, justify every dependency
and preserve one-way flow from inference to policy and outputs.

### 4.3 Compare alternatives

For an inference, movement, prediction, or policy redesign, compare at least two
plausible approaches. Evaluate each against:

1. Bayesian or probabilistic interpretation.
2. Correlated evidence and double-counting risk.
3. Zero-, one-, and two-occupant behavior.
4. Sequential graph movement and missed-event recovery.
5. Stuck, flapping, stale, unknown, and unavailable sensors.
6. Out-of-order events and restart.
7. Calibration requirements and parameter coupling.
8. Exact-state, context, latency, and determinism budgets.
9. Public activation, release, and prediction failure modes.

Do not select an approach merely because it passes the incident trace.

### 4.4 Mandatory rejection checks

Reject or redesign a proposal if it:

- hard-codes a room, node, entity, household member, or incident timestamp;
- adds a threshold with no generative-model or policy meaning;
- repeatedly multiplies one asserted sensor as independent evidence;
- rewrites a path event timestamp, evidence sequence, or movement disposition
  during timer-based duration evaluation;
- deletes a valid low-prior hypothesis to force a desired posterior;
- allows one unrelated remote event to invalidate local asserted evidence;
- uses a timer or low confidence alone to release `keep_on`;
- lets policy mutate occupancy probability;
- lets prediction affect occupancy, movement, activation, or keep-on;
- breaks exact count, normalization, zero pruning, or context mass preservation;
- handles a predictor defect in consuming automation YAML;
- changes calibration against only one room or one incident replay.

## Stage 5: Preserve the Regression

Before the production edit:

1. Add the smallest deterministic regression reproducing the observed shape.
2. Preserve exact values and timing boundaries when they control the failure.
3. Use a generic test map and generic zone names unless physical topology is the
   cause. A test may document the incident name while its behavior remains
   parameterized.
4. Assert the expected public edge or retained public state.
5. Add internal assertions for the governing invariant and diagnosed gate.
6. Run the test against the current behavior and confirm it fails for the stated
   reason.

If the regression passes before the proposed fix or fails for another reason,
do not edit production behavior. Correct the reproduction or improve retained
diagnostics.

## Stage 6: Implement the Smallest Generic Change

Make the smallest change at the controlling layer that satisfies the canonical
requirements and generic scenario corpus.

- Prefer an existing profile, role, signal type, graph abstraction, evidence
  episode, or immutable update contract over a new special case.
- Treat thresholds as coupled calibration. Review all gates that consume the
  changed posterior or movement evidence.
- Persist any new state needed to avoid restart discontinuity or double counting.
- Keep diagnostics sufficient to explain accepted and rejected decisions.
- Update the canonical specification first if the agreed design changed.

Immediately run the focused incident regression after the first production
edit. Repair that same slice before widening scope.

## Stage 7: Validate Adversarially

Run the focused incident test, then nearby tests for the controlling layer. A
model or policy change also requires tests for:

- the inverse error direction;
- a disconnected or non-adjacent false signal;
- a stuck or flapping source;
- a valid adjacent departure;
- strict missed-event relocation;
- two occupants and same-room multiplicity where relevant;
- out-of-order delivery;
- persistence round-trip and backward defaults for new state;
- threshold boundaries and idempotent timer evaluation.
- valid graph-backed activation callback latency at the preferred 50 ms and hard
  100 ms boundaries when the change touches the event path;
- variable-order route matching, sparse-support backoff, outbound/return
  independence, bounded learned influence, and interleaved-occupant rejection
  when the change touches prediction or learning.

Run all repository gates before completion:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
npm run test:frontend
.venv/bin/python benchmarks/occupancy_performance.py
```

The Python test command enforces whole-package 100% branch coverage. Do not
weaken coverage, exact-state, performance, or retained-regression gates to make a
change pass.

## Stage 8: Report the Decision

Use [the review template](./references/review-template.md). The final report must
state:

- what happened and what should have happened;
- verified root cause and controlling layer;
- requirement IDs;
- alternatives considered and why the selected model is stronger;
- retained regression and public assertion;
- generic production change;
- validation results and residual calibration risk;
- whether live Home Assistant was queried and confirmation that it was not
  mutated.

## Completion Gate

The review is complete only when all are true:

- Evidence and assumptions are separated.
- The expected behavior follows from named canonical requirements.
- The incident is reproduced at the public contract.
- The chosen fix is generic and lives in the controlling layer.
- Model alternatives and coupled failure modes were evaluated.
- Focused and full validation pass.
- Specification, user documentation, diagnostics, persistence, and changelog are
  updated where their contracts changed.
