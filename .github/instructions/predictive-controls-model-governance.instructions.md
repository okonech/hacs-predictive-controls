---
name: Predictive Controls Model Governance
description: "Use when changing Predictive Controls observations, zone belief, traversal, count, policy, prediction, persistence, profiles, thresholds, benchmarks, or regression tests."
applyTo:
  - "custom_components/predictive_controls/**/*.py"
  - "tests/**/*.py"
  - "benchmarks/**/*.py"
---

# Predictive Controls Model Governance

`SPECIFICATION.md` is the sole design authority. `MIGRATION_PLAN.md` sequences
implementation but cannot add or reinterpret requirements.

Before changing behavior in a matched file:

1. Read `SPECIFICATION.md` and map the change to its `REQ-*` IDs.
2. During migration, read only the active phase in `MIGRATION_PLAN.md` plus its
   global execution and validation rules.
3. Use `.github/skills/predictive-controls-regression-review/SKILL.md` for a
   reported production failure or incident. Routine implementation of an
   already-approved migration phase follows the quick loop in `MIGRATION_PLAN.md`.
4. For an incident, add and prove the exact-timestamp public regression before
   diagnosing or editing production behavior.
5. Use an independent read-only subagent only when root cause is unclear, the
   proposal changes `SPECIFICATION.md` or a public contract, or final migration
   conformance is being reviewed. Do not require proposal and implementation
   reviewers for each planned phase.
6. After a coherent edit batch, run the smallest focused test with `--no-cov`
   and lint the changed files. Defer full pytest/coverage, repository mypy,
   frontend, benchmarks, diff checks, broad adversarial expansion, and final
   conformance review until all migration implementation phases are complete.

Do not add room/entity/person-specific model logic, count timer callbacks as
independent evidence, let prediction or policy feed zone belief, normalize
positive-count belief into forced room assignments, or move model defects into
Home Assistant automations.

Elapsed time may advance declared bounded filter decay, episode health, token
expiry, prediction leases, and policy dwell exactly once from stored timestamps.
It must not synthesize sensor observations or traversal edges.

If desired behavior conflicts with `SPECIFICATION.md`, stop production work and
obtain explicit agreement to amend that file first.