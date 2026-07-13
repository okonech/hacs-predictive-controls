# Predictive Controls Specification

**Status:** Normative
**Scope:** Product goals, probabilistic model, movement and prediction,
automation policy, observability, and change governance

This directory is the sole design authority for Predictive Controls. Code,
tests, and user documentation must comply with these rules and do not override
them.

## Reading Map

Load only the sections needed for the task:

| Question                                          | Required document                                                             |
| ------------------------------------------------- | ----------------------------------------------------------------------------- |
| What is the project trying to achieve?            | [Goals and principles](goals-and-principles.md)                               |
| How should occupancy and sensor evidence behave?  | [Occupancy and evidence](occupancy-and-evidence.md)                           |
| How should tracks and next-zone predictions work? | [Movement and prediction](movement-and-prediction.md)                         |
| When may automations turn on or off?              | [Automation policy and observability](automation-policy-and-observability.md) |
| How are regressions and model changes reviewed?   | [Change governance](change-governance.md)                                     |

For any behavioral change, read this index, goals and principles, change
governance, and only the technical section that owns the behavior.

## Core Contract

Predictive Controls answers four separate questions:

1. **Occupancy:** Which anonymous joint occupant locations best explain the
   observations?
2. **Movement:** Which graph-valid path, if any, explains a new observation?
3. **Prediction:** Given supported movement, which adjacent zone is likely next?
4. **Policy:** Is there enough evidence to authorize a turn-on or turn-off?

These products have one-way dependencies:

```text
map + observations -> occupancy + movement -> prediction
                                       \----> automation policy -> entities
```

- Prediction is not occupancy evidence.
- Policy does not rewrite the posterior.
- A room automation does not compensate for an inference defect.

The normal Home Assistant contract is:

1. `activation_plausible -> on` authorizes a normal turn-on.
2. `keep_on -> off` authorizes a normal turn-off.
3. `prelight_plausible -> on` optionally authorizes low-impact prelighting.

## Conflict Rule

If desired behavior conflicts with this specification, amend and agree on the
relevant specification file before changing production behavior. Never encode a
new design silently inside an incident fix.
