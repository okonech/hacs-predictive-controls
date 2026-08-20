---
name: spec-writer
description: "Research, write, critique, and harden a Predictive Controls implementation specification grounded in the repository, retained incidents, and SPECIFICATION.md. Use when asked to make, create, draft, design, rewrite, or harden a spec, technical proposal, model change, implementation plan, architecture specification, performance specification, or migration specification. Produces an evidence-based draft, then performs exactly three adversarial critique-and-rewrite passes before delivering the final spec."
argument-hint: "Describe the specification to create and any required output path."
user-invocable: true
disable-model-invocation: false
---

# Spec Writer

Create an implementation-ready specification whose claims, constraints, and acceptance gates are traceable to the current repository, retained production evidence, and `SPECIFICATION.md`. The final artifact is the result of one research/draft pass followed by exactly three adversarial critique-and-hardening passes.

## 1. Establish Scope

1. Identify the requested outcome, affected model layers, intended audience, output path, and whether the spec is a proposal, migration, repair, or replacement.
2. Ask questions only when an unresolved product or authority decision would materially change the design. Resolve discoverable technical facts from the repository without asking the user.
3. Locate applicable repository instructions, `SPECIFICATION.md`, architecture contracts, tests, production paths, schemas, metrics, retained incidents, and historical evidence.
4. Treat `SPECIFICATION.md` as the sole model authority. If the new design conflicts with it, name the conflict and require explicit agreement before amending authority or production behavior.
5. For incident-derived model work, load `.github/skills/predictive-controls-regression-review/SKILL.md` and preserve exact public regressions.

## 2. Research Before Drafting

Start from the code that directly owns the behavior. Trace enough of its callers, persistence boundaries, timer/event ordering, tests, diagnostics, and operational path to explain the current behavior end to end.

Research must:

- distinguish verified facts from estimates, hypotheses, and recommendations;
- cite repository-relative files and symbols for important current-state claims;
- inspect existing tests and executable commands before defining validation;
- inspect repository history only when present behavior or intent is ambiguous;
- record missing measurements as baseline work, not invented numbers;
- identify compatibility, false-positive, false-negative, restart, rollback, bounded-state, callback-latency, and resource implications; and
- compare model alternatives against count zero/one/two, same-zone multiplicity, missed edges, backtracking, stuck assertions, false clears, unavailable inputs, out-of-order events, and restart.

Use a read-only exploration subagent for broad or independent fact-finding. Verify critical findings directly before relying on them.

## 3. Write The Initial Spec

Match established repository conventions. Unless clearly inapplicable, include:

1. title, status, affected model layers, and related `REQ-*` authority;
2. objective and public/operational outcome;
3. verified current state and problem statement;
4. scope and explicit non-goals;
5. invariants and compatibility requirements;
6. proposed state machine, data flow, contracts, event ordering, and failure behavior;
7. alternatives considered and rejection rationale;
8. phased implementation with dependencies and bounded changes;
9. observability, benchmark, test, migration, rollout, and rollback plans;
10. phase exit criteria and final acceptance criteria;
11. implementation surfaces and expected files/modules; and
12. a tracking table with every phase initially `Not started`, completed evidence empty, and one concrete next executable step per phase.

Requirements must be falsifiable. Prefer exact boundaries, state transitions, identities, limits, and executable gates over vague claims. Do not present unmeasured improvements as facts. Define baseline, comparison method, fixture identity, sample count, environment, and regression budget.

## 4. Adversarial Hardening Loop

Perform exactly three complete passes after the initial draft. In each pass, reread the entire current spec and inspect relevant code again where a criticism depends on implementation detail. A read-only review subagent may challenge the draft, but the primary agent owns verification and rewrite.

For each pass:

1. **Critique:** Try to disprove the design. Find unsupported claims, incorrect code assumptions, missing failure modes, hidden tradeoffs, authority conflicts, ambiguous contracts, unsafe sequencing, non-idempotent behavior, unbounded work, weak tests, and acceptance gates that could pass while behavior remains wrong.
2. **Ground:** Verify every material criticism against code, tests, schemas, metrics, retained incidents, or `SPECIFICATION.md`. Reject objections without a plausible failure or requirement.
3. **Harden:** Rewrite the spec itself. Correct false claims, close omissions, sharpen contracts, split unsafe phases, add negative/failure tests, and replace vague gates with executable evidence.
4. **Reconcile:** Reread the revised spec for contradictions, stale references, duplicated requirements, phase-order errors, and criteria no longer aligned with the design.

Use a different emphasis for each pass:

- **Pass 1, factual and architectural:** current-state accuracy, ownership boundaries, authority, data flow, evidence independence, and root-cause fit.
- **Pass 2, failure and operations:** event ordering, timer boundaries, crashes, restore, idempotency, rollback, state bounds, diagnostics, deployment order, and compatibility.
- **Pass 3, implementation and proof:** phase dependencies, state/schema precision, testability, benchmark validity, acceptance loopholes, adversarial cases, and whether another engineer could implement without additional guidance.

Do not count a pass unless it includes a full-spec reread, grounded critique, an actual rewrite where warranted, and reconciliation. If a pass finds no defensible change, record that internally and still complete the remaining passes.

## 5. Final Quality Gate

Before delivery:

- verify all three hardening passes completed;
- verify file links, symbols, commands, phase ordering, and frontmatter;
- ensure status and tracking do not claim unexecuted implementation as complete;
- ensure every material invariant has positive and negative checks;
- ensure count behavior never assigns identity, forces exactly N zones, or lets unrelated remote events directly erase strong local evidence;
- ensure persistence and rollback preserve authoritative user data;
- include focused `pytest --no-cov`, Ruff, mypy, full coverage, frontend, and applicable benchmark gates; and
- run the cheapest available Markdown, repository, or diff validation.

The final output is the hardened spec file. Do not include intermediate drafts or critique transcripts unless requested. Briefly summarize final scope, major hardening decisions, and validation performed.
