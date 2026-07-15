---
name: Predictive Controls Model Governance
description: 'Use when changing Predictive Controls inference, observations, movement, prediction, policy, persistence, thresholds, or regression tests. Requires canonical requirement review and the predictive-controls-regression-review skill before behavior edits.'
applyTo:
  - "custom_components/predictive_controls/**/*.py"
  - "tests/**/*.py"
  - "benchmarks/**/*.py"
---

# Predictive Controls Model Governance

Before changing behavior in a matched file:

1. Read `docs/spec/README.md`, goals, governance, and the owning technical
   contract identified by the index.
2. Use `.github/skills/predictive-controls-regression-review/SKILL.md` for every
   report that something did not work properly, regression, incident, threshold
   change, or model redesign. Follow its nine-gate Non-Negotiable Incident Order
   exactly; later detail sections do not define a second sequence.
3. Map expected behavior and the proposed change to canonical requirement IDs.
4. Add and run an exact-timestamp retained regression that fails at the public
   entity contract before examining the production implementation.
5. Use fresh context-isolated read-only subagents to investigate the failing
   implementation, verify each proposed solution against the canonical spec,
   and review the resulting implementation. A failed spec verdict blocks edits
   and requires another proposal and another fresh review.
6. Explain the probabilistic or policy meaning of the change and compare
   alternatives for model changes.

Do not add room-specific inference, count timer evaluations as independent
evidence, hard-delete valid relocation hypotheses to force an outcome, feed
prediction into occupancy, clear `active` from uncertainty alone, or move
predictor defects into consuming Home Assistant automations.

If desired behavior conflicts with the canonical specification, amend and agree
on the specification before changing production code.
