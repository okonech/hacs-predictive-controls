---
name: spec-implementation-tracking
description: "Implement a Predictive Controls repository specification or written multi-phase plan while keeping phase status, validated evidence, and the next executable step current inside the document. Use when asked to implement this spec, execute a written plan, work through phases, resume spec implementation, or track implementation progress."
argument-hint: "Provide the specification or plan path to implement."
user-invocable: true
disable-model-invocation: false
---

# Specification Implementation Tracking

Use the working specification as the source of truth only while implementation
is active or blocked. It is not the permanent incident artifact.

## Start Or Resume

1. Read the specification's objective, invariants, phases, exit criteria, and current tracking section.
2. If no tracking section exists, add one near the top with one row per phase: status (`Not started`, `In progress`, `Blocked`, or `Complete`), completed evidence, and one concrete next executable step.
3. Reconcile the document with the repository before editing code. Never mark historical claims complete without current evidence.
4. Confirm required amendments to the sole authority, `SPECIFICATION.md`, have explicit agreement before production behavior changes.
5. Mark exactly one implementation phase `In progress` unless the spec explicitly permits parallel independent phases.
6. For an incident-derived spec, require a `Regression proof` phase before every
	production implementation phase. Do not begin production edits until its
	exact command, expected failure signature, observed pre-fix result, and
	evidence provenance are recorded and the failure matches the diagnosis.

## During Implementation

- Reference tracking after every context transition or interruption.
- Update the current row after each validated milestone.
- Record executable evidence and outcomes such as focused test names, retained
	incident replays, benchmark results, migrations, or quality-gate commands.
- Keep unfinished requirements visible. Update both phase requirements and tracking when scope changes.
- If blocked, record the concrete blocker and smallest unblocking step.
- Do not mark a phase complete until its exit criteria pass.
- For incident-derived changes, preserve exact public regression inputs and expectations.

## Phase Boundaries

1. Run the phase's focused tests and executable exit checks.
2. Update the phase row to `Complete` with concise evidence.
3. Mark the next phase `In progress` and name its first executable step.
4. Re-read the next phase, relevant `REQ-*` invariants, and applicable instructions before editing production code.

## Completion

- Run full Python coverage, repository Ruff, mypy, frontend tests, applicable benchmarks, and diff/reference checks.
- Reconcile every acceptance criterion with evidence or an explicit unresolved item.
- Set the document status to implemented only when all required phases and acceptance criteria are complete.
- Leave optional or deferred work labeled explicitly.
- Update the governing requirements and implementation-conformance results in
	`SPECIFICATION.md`, then verify the canonical specification contains the final
	implemented contract and evidence.
- For incident-derived work, retain the exact regression test as the permanent
	incident artifact.
- Delete the completed working specification after canonical reconciliation.
	Keep it only if work remains incomplete or blocked, or if it is the sole record
	of an unresolved requirement, failed gate, or rollback need.
