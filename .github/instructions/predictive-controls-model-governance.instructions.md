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
   reported error, regression, incident, threshold change, or model redesign.
3. Map expected behavior and the proposed change to canonical requirement IDs.
4. Add a retained regression that fails at the public entity contract before
   editing production behavior.
5. Explain the probabilistic or policy meaning of the change and compare
   alternatives for model changes.

Do not add room-specific inference, count timer evaluations as independent
evidence, hard-delete valid relocation hypotheses to force an outcome, feed
prediction into occupancy, release `keep_on` from uncertainty alone, or move
predictor defects into consuming Home Assistant automations.

If desired behavior conflicts with the canonical specification, amend and agree
on the specification before changing production code.
