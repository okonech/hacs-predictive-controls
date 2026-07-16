# Predictive Controls Specification

**Status:** Normative
**Scope:** Product goals, probabilistic model, movement and prediction,
automation policy, observability, and change governance

This directory is the sole design authority for Predictive Controls. Code,
tests, and user documentation must comply with these rules and do not override
them.

## Normative Model Summary

Predictive Controls is an exact event-indexed anonymous Bayesian state-space
model with semi-Markov physical-sensor episodes and bounded fixed-lag movement
association for authoritative count $N$, with $0 \le N \le 2$:

The primary and maximum operational profile is $N=2$. Calibration,
optimization, incident replay, and routine performance measurement emphasize
two occupants, while correctness remains mandatory for every supported count.

1. Physical-node edge sequences form correlated observation episodes. Their
   event and duration emissions are integrated once; flaps, aliases, duplicate
   callbacks, and timer evaluation never become independent votes.
2. The occupancy posterior contains every anonymous count configuration for the
   authoritative count. Movement assignment and support provenance are latent
   variables in the same probability measure, not labels attached after merge.
3. Graph movement is represented by bounded fixed-lag anonymous assignments.
   Asserted transition intervals may bridge missed edges, including distinct
   crossings by multiple occupants, without becoming repeated observations.
4. Acquisition thresholds the forward probability of a supported arrival and
   sets the durable `active` policy state. Release thresholds the finalized
   probability that the origin is empty and every occupant is distinctly
   supported elsewhere, then clears `active`.
5. Resolved departure, strict relocation, and count-accounted exclusion are
   support mechanisms for the same release event. Low marginal, local clear,
   elapsed time, unavailable state, unlocated mass, and prediction never suffice
   alone.
6. A currently valid sustained room-positive assertion blocks automatic release.
   A continuously stuck-on room sensor therefore requires reset, authoritative
   zero/away state, or repair.

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
2. **Movement:** Which bounded anonymous causal path or interval-censored graph
   traversal, if any, explains the observations?
3. **Prediction:** Given supported movement, which adjacent zone is likely next?
4. **Policy:** Under asymmetric false-on and false-off costs, is there enough
   causally or count-accounted evidence to authorize a turn-on or turn-off?

These products have one-way dependencies:

```text
map + count + sensor episodes -> occupancy + movement assignment -> prediction
                                                       \----> policy -> entities
```

- Prediction is not occupancy evidence.
- Policy does not rewrite the posterior.
- A room automation does not compensate for an inference defect.

The normal Home Assistant contract is:

1. `active -> on` turns normal outputs on.
2. `active -> off` turns normal outputs off.
3. `prelight -> on` optionally authorizes low-impact predictive lighting.

The optional disabled-by-default `arrival` event exposes distinct accepted
fresh episodes for advanced consumers. Ordinary automations do not need it.

## Conflict Rule

If desired behavior conflicts with this specification, amend and agree on the
relevant specification file before changing production behavior. Never encode a
new design silently inside an incident fix.
