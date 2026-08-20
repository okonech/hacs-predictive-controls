---
name: work-todo-queue
description: "Process plain-language Predictive Controls work from async-todo.md in order. Use when asked to work the next todo, run the async queue, complete the next N items, process queued tasks, resume queued work, or reorient on unfinished tasks. Owns status, requirements, validation, and completion bookkeeping."
argument-hint: "Specify a batch such as next 3, all queued, or a heading. Defaults to the next eligible item."
user-invocable: true
disable-model-invocation: false
---

# Work Todo Queue

Use this skill to execute one or more plain-language items from repository-root `async-todo.md` and leave durable progress after each item.

## Invocation

- `reorient`, `status`, or `what is next`: read-only review; do not change status or start work.
- `next` or no argument: process one eligible item.
- `next N`: process at most N eligible items.
- `all queued`: process every eligible item present at start.
- A heading or list of headings: process those items in supplied order.

Resume `in progress` before `queued`; preserve file order; skip `blocked` and `completed` unless explicitly retried or reopened.

## Queue Contract

An item starts at a level-two heading and ends at the next level-two heading. Normalize active work to:

```markdown
## [ ] Title
> Status: in progress
```

Valid transitions are `queued -> in progress -> completed|blocked`; blocked/completed reopen only explicitly. Record ISO UTC start/completion/block timestamps, concise outcome, and executable verification under `### Work record`. Preserve the user's original prose.

## Per-Item Workflow

1. Read the complete queue and select the requested batch.
2. Re-read the selected item and applicable instructions/skills.
3. Mark only the current item `in progress`.
4. Anchor on owning code, nearby tests, `SPECIFICATION.md`, and retained evidence.
5. For incidents, invoke `predictive-controls-regression-review`; for specifications, invoke `spec-writer`; for written phased implementation, invoke `spec-implementation-tracking`.
6. Implement the smallest generic architecture-aligned solution.
7. Run a focused `pytest --no-cov` check immediately after the first edit, then touched-file Ruff.
8. Before completion, run the repository-required broad gates appropriate to the change.
9. Persist completed or blocked status before starting another item.

Do not silently broaden an item, discard unrelated changes, commit, branch, or push unless requested. Never mark work complete merely because code was written.
