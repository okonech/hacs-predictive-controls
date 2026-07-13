# Goals and Principles

## Mission

Predictive Controls turns imperfect, asynchronous home sensor observations into
conservative, explainable occupancy, movement, prediction, and automation
decisions. Ordinary Home Assistant automations consume stable policy entities
instead of reproducing model logic.

## Base Assumptions

- **ASSUME-001:** Mapped sensors are generally accurate and observations usually
  arrive promptly. False positives occur occasionally; delayed or missed events
  are possible but uncommon. The model SHOULD trust a normal observation while
  retaining enough uncertainty to reject isolated contradictions.
- **ASSUME-002:** The configured occupant count is authoritative. Supported
  inference covers exactly zero, one, or two occupants.
- **ASSUME-003:** Occupants are anonymous and exchangeable. The model does not
  invent identity when paths cross or merge.
- **ASSUME-004:** Physical adjacency constrains normal movement, but a missing
  edge observation must remain recoverable at low prior.
- **ASSUME-005:** No event means no observed movement. Wall time alone does not
  diffuse occupants through the graph.
- **ASSUME-006:** A local sensor clear means its positive evidence ended; it does
  not prove departure.
- **ASSUME-007:** A continuously asserted sustained sensor is correlated
  duration evidence, not a stream of independent samples.
- **ASSUME-008:** In an ordinary occupied room, a false turn-off is more
  disruptive than a delayed turn-off. Ambiguity retains trusted ownership.
- **ASSUME-009:** New activation remains strict despite the false-off bias. It
  requires fresh local evidence and a plausible whole-house explanation. A
  coherent incoming path is normally sufficient support unless stronger
  evidence contradicts that arrival.
- **ASSUME-010:** Likelihoods, priors, timing windows, and policy thresholds are
  coupled calibration values, not universal truths.
- **ASSUME-011:** Repeated graph-valid route sequences reveal useful household
  routines. Learning is shared and anonymous: it describes common paths, not
  which person follows them.

## Product Goals

- **GOAL-001, false-off safety:** Ambiguous evidence MUST retain the last trusted
  `keep_on` state.
- **GOAL-002, strict activation:** New turn-ons MUST require fresh local evidence
  plus a supported path, unlocated mass, recovery state, or strict relocation.
  A fresh graph-backed arrival SHOULD activate by default unless specific
  contradictory evidence makes the assignment implausible.
- **GOAL-003, coherent inference:** Every probability change MUST correspond to
  an explicit observation, transition prior, duration likelihood, count change,
  or restore operation.
- **GOAL-004, topology-first movement:** Sequential graph-valid observations are
  the primary high-confidence movement evidence.
- **GOAL-005, missed-event recovery:** Strong evidence MAY repair a missed trail,
  but one remote hit MUST NOT teleport an accounted-for occupant.
- **GOAL-006, sustained evidence:** A continuously asserted sustained sensor
  SHOULD gain bounded local support until clear or supported departure.
- **GOAL-007, multi-occupant correctness:** Exact anonymous zero-, one-, and
  two-occupant explanations MUST be preserved.
- **GOAL-008, useful route learning:** Next-zone prediction MUST learn common
  multi-step paths and return routes over time while remaining separate from
  occupancy evidence and normal activation authorization.
- **GOAL-009, explainability:** Every public edge MUST have retained evidence,
  named gates, and a machine-readable reason.
- **GOAL-010, determinism and performance:** Equal inputs MUST produce equal
  results with zero supported-state pruning. A valid raw detection SHOULD
  produce its in-memory public activation decision within 50 ms and MUST do so
  within 100 ms under the supported workload.
- **GOAL-011, generic behavior:** Production logic MUST use roles, signal types,
  occupancy behavior, graph structure, and shared calibration. It MUST NOT
  special-case a room, entity, person, or incident.
- **GOAL-012, incident learning:** Every definitively diagnosed incident MUST
  become a permanent public-contract regression.

## Non-Goals

- Identifying a person without an independent identity source.
- Preserving anonymous identity through an unobservable crossing or merge.
- Treating a light's state as occupancy evidence.
- Directly controlling a particular room or light.
- Treating prediction as proof of occupancy.
- Guaranteeing immediate turn-off after an unobserved departure.
- Solving sensor hardware faults with room-specific inference rules.
- Exposing internal thresholds to ordinary automations.

## Layer Ownership

1. **Map:** zones, nodes, adjacency, timing, roles, occupancy behavior, and
   physical entity identity.
2. **Observation:** per-entity state likelihood and correlated episode state.
3. **Occupancy:** exact anonymous joint posterior.
4. **Movement:** bounded directional context and path-specific evidence.
5. **Prediction:** graph-valid next-zone leases.
6. **Policy:** activation and release authorization.
7. **Entities:** stable Home Assistant projections and diagnostics.

A defect is fixed in the lowest layer that computes the wrong result. Prediction
MUST NOT feed occupancy; policy MUST NOT alter probability; automations MUST NOT
reimplement lower-layer logic.
