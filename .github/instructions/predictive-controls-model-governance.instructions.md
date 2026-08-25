---
name: Predictive Controls Model Governance
description: "Use when changing Predictive Controls observations, zone belief, traversal, count, policy, prediction, persistence, profiles, thresholds, benchmarks, or regression tests."
applyTo:
  - "custom_components/predictive_controls/**/*.py"
  - "tests/**/*.py"
  - "benchmarks/**/*.py"
---

# Predictive Controls Model Governance

`SPECIFICATION.md` is the sole design authority.

Before changing behavior in a matched file:

1. Read `SPECIFICATION.md` and map the change to its `REQ-*` IDs.
2. Use `.github/skills/predictive-controls-regression-review/SKILL.md` for a
   reported production failure or incident.
3. For an incident, do not edit production behavior until the mandatory workflow
   has established real evidence and a falsifiable root cause, created a temporary
   `docs/spec/` working specification, completed exactly three
   adversarial hardening passes, and proved the exact regression fails for the
   diagnosed reason.
4. Implement from the hardened specification using
   `.github/skills/spec-implementation-tracking/SKILL.md`; keep its phase status,
   validated evidence, and next executable step current.
5. Use an independent read-only subagent before implementing a public-contract,
   persistence, shared-calibration, or otherwise high-blast-radius change, or
   whenever root cause remains unclear.
6. After the first production edit, immediately rerun the exact regression. Then
   run the nearest inverse/boundary tests and touched-file lint before broadening.
7. Before handoff, run the complete applicable pytest/coverage, repository mypy,
   frontend, benchmark, and diff gates; update the governing requirements plus
   Section 19 in `SPECIFICATION.md`, retain the exact regression test as the
   permanent incident artifact, and delete the completed working spec.

Do not add room/entity/person-specific model logic, count timer callbacks as
independent evidence, let prediction or policy feed zone belief, normalize
positive-count belief into forced room assignments, or move model defects into
Home Assistant automations.

Elapsed time may advance declared bounded filter decay, episode health, token
expiry, prediction leases, and policy dwell exactly once from stored timestamps.
It must not synthesize sensor observations or traversal edges.

If desired behavior conflicts with `SPECIFICATION.md`, stop production work and
obtain explicit agreement to amend that file before implementation. Perform the
final authority reconciliation again after validation.
