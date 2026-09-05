---
name: Predictive Controls Model Governance
description: "Use when investigating or changing Predictive Controls observations, zone belief, traversal, count, policy, prediction, persistence, profiles, thresholds, benchmarks, or regression tests. This includes every report that a motion-, presence-, occupancy-, or room-sensor-driven light failed to turn on, stay on, turn off, or recover, even when the final controlling layer is automation or external hardware."
applyTo:
  - "custom_components/predictive_controls/**/*.py"
  - "tests/**/*.py"
  - "benchmarks/**/*.py"
---

# Predictive Controls Model Governance

`SPECIFICATION.md` is the sole design authority.

Motion-, presence-, occupancy-, and room-sensor-driven lighting reports are
Predictive Controls incidents from the outset. Keep their working specification,
diagnosis, and one separate retained regression per reported symptom in this
repository. Home Assistant live evidence still comes only from approved
read-only scripts in the sibling Homelab repository. If the completed review
assigns the controlling layer to `AUTOMATION` or `EXTERNAL`, keep the incident
record here and make only the resulting configuration or operational change in
the owning repository.

Before changing behavior in a matched file:

1. Read `SPECIFICATION.md` and map the change to its `REQ-*` IDs.
2. Use `.github/skills/predictive-controls-regression-review/SKILL.md` for a
   reported production failure or incident.
3. For an incident, do not edit production behavior until the mandatory workflow
   has established real evidence and a falsifiable root cause, created a temporary
   `docs/spec/` working specification, completed exactly three
   adversarial hardening passes, and proved the exact regression fails for the
   diagnosed reason.
   Every reported issue gets exactly one separately named, self-contained file
   at `tests/incidents/test_inc_YYYY_MM_DD_HHMMz_<symptom>.py`, where `HHMMz` is
   the first material event's UTC minute. That file contains the matching primary
   `test_inc_YYYY_MM_DD_HHMMz_<symptom>` replay of its material production
   sequence; do not place the incident replay in a shared test module. If the
   event minute is unknown, use the report-receipt UTC minute and record that
   provenance. An older or same-day similar incident file never substitutes for
   the new report. Existing incident files and primary tests must be renamed to
   this convention when their retained evidence provides the event minute.
   If unchanged code does not reproduce the reported failure, stop before
   implementation and improve evidence or diagnostics.
4. Implement from the hardened specification using
   `.github/skills/spec-implementation-tracking/SKILL.md`; keep its phase status,
   validated evidence, and next executable step current.
5. Use an independent read-only subagent before implementing a public-contract,
   persistence, shared-calibration, or otherwise high-blast-radius change, or
   whenever root cause remains unclear.
6. After the first production edit, immediately rerun the exact regression. Then
   run the nearest inverse/boundary tests and touched-file lint before broadening.
7. After the final Predictive Controls code change, run the complete Python suite
   with `.venv/bin/pytest -q` and all frontend tests with
   `npm run test:frontend`; focused tests never replace either full-suite run.
   Before handoff, also run repository mypy, frontend build when applicable,
   benchmark, and diff gates, including one explicit run of the entire retained
   `test_inc_` scenario corpus. Update the governing requirements plus Section 19
   in `SPECIFICATION.md`, retain every report's exact incident file as the
   permanent artifact, and delete the completed working spec.

For every Predictive Controls code change, the full Python and frontend test
suites are blocking validation gates. Run `.venv/bin/pytest -q` and
`npm run test:frontend` after the final code change. For every coded incident
solution, the full retained incident corpus is an additional blocking gate. Run
`.venv/bin/pytest --no-cov -q tests -k 'test_inc_'` after the final code change
and before the full-suite handoff. Focused tests, selected incident tests, the
incident corpus, the full Python suite, and frontend tests are distinct required
runs and do not replace one another. Do not report the solution complete when a
command was skipped or any test failed.

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
