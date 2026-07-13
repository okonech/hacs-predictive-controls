# Change Governance

Every reported regression and every proposed change to inference, movement,
prediction, policy, thresholds, map semantics, or persistence uses the
repository skill at
`.github/skills/predictive-controls-regression-review/SKILL.md`.

## Requirements

- **GOV-001:** State observed public behavior, expected public behavior, and
  governing requirement IDs before proposing a fix.
- **GOV-002:** Separate verified evidence from assumptions and identify the
  controlling layer.
- **GOV-003:** Preserve a diagnosed incident with the smallest permanent test
  containing material event order, timings, states, probabilities, and gates.
- **GOV-004:** The regression MUST assert `activation_plausible`, `keep_on`, or
  `prelight_plausible`; internal assertions are supplementary.
- **GOV-005:** Confirm the regression fails for the diagnosed reason before the
  production edit. If it cannot reproduce, improve diagnostics instead of
  guessing.
- **GOV-006:** State whether a change modifies observation likelihood, duration
  likelihood, transition prior, posterior, context, prediction, policy, or
  persistence. Do not hide a change in the wrong layer.
- **GOV-007:** For model changes, compare at least two approaches for
  probabilistic coherence, temporal correlation, multi-occupant behavior,
  missed events, sensor faults, persistence, calibration, and runtime.
- **GOV-008:** Reject room-specific conditions or constants, event count as
  independent evidence, prediction feedback, policy-to-posterior feedback,
  timer-only release, and automation workarounds for predictor defects.
- **GOV-009:** Calibration changes require a generic replay corpus, incident
  regressions, boundary tests, and documented before/after public effects.
- **GOV-010:** Run the focused regression immediately after the first production
  edit, then related suites and every repository quality gate.
- **GOV-011:** Amend and agree on the specification first when desired behavior
  conflicts with it.

## Required Scenario Families

The retained suite covers:

1. sustained confidence rises monotonically, saturates, and is independent of
   timer or event frequency;
2. disconnected or non-adjacent flapping cannot release a held sustained room
   or manufacture corroboration;
3. coherent adjacent departure can invalidate a stuck asserted episode and
   release the final occupant;
4. strong independent evidence can repair missed movement while one remote hit
   cannot;
5. local clear, silence, low marginal, and periodic evaluation alone produce no
   `keep_on -> off` edge;
6. two sustained occupants are supported independently and same-room evidence
   applies once rather than once per occupant;
7. interleaved paths cannot advance, predict, learn, or release each other;
8. independent prediction leases coexist and cancel independently;
9. out-of-order events cannot advance duration, context, prediction, learning,
   or policy;
10. restart round-trips duration and invalidation without synthetic edges or
    duplicate evidence;
11. long-running assertion can support adjacent departure through an explicit
    observation-validity interval without rewriting a prior path event.
12. a normal graph-backed arrival authorizes activation within the preferred
  50 ms and hard 100 ms callback budgets unless explicit contradictory
  evidence is present;
13. repeated multi-step outbound and return routes improve only compatible
  graph-valid branch predictions, back off when support is sparse, and never
  independently activate or release occupancy.

## Calibration

Observation likelihoods, transition priors, duration parameters, thresholds,
freshness windows, timing windows, and lease durations are coupled calibration.
Changing one value requires reviewing every gate that consumes the resulting
posterior or movement evidence and replaying the generic scenario corpus.

## Completion Criteria

- The expected behavior follows from named requirements.
- Evidence and assumptions are separated.
- The incident fails at the public contract before the fix.
- The fix is generic and belongs to the controlling layer.
- Inverse, multi-occupant, sensor-fault, missed-event, ordering, and restart
  cases are covered where relevant.
- Full Python tests with 100% branch coverage, Ruff, mypy, frontend tests, and
  benchmark gates pass.
- Documentation, diagnostics, persistence, and changelog are updated when their
  contracts change.
