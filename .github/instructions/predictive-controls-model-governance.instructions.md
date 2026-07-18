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
3. For an incident, add and prove the exact-timestamp public regression before
   diagnosing or editing production behavior.
4. Use an independent read-only subagent only when root cause is unclear or the
   proposal changes `SPECIFICATION.md` or a public contract.
5. After a coherent edit batch, run the smallest focused test with `--no-cov`
   and lint the changed files. Before handoff, run the complete applicable
   pytest/coverage, repository mypy, frontend, benchmark, and diff gates.

Do not add room/entity/person-specific model logic, count timer callbacks as
independent evidence, let prediction or policy feed zone belief, normalize
positive-count belief into forced room assignments, or move model defects into
Home Assistant automations.

Elapsed time may advance declared bounded filter decay, episode health, token
expiry, prediction leases, and policy dwell exactly once from stored timestamps.
It must not synthesize sensor observations or traversal edges.

If desired behavior conflicts with `SPECIFICATION.md`, stop production work and
obtain explicit agreement to amend that file first.
