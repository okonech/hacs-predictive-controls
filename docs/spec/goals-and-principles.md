# Goals and Principles

## Mission

Predictive Controls turns imperfect, asynchronous home sensor observations into
conservative, explainable occupancy, movement, prediction, and automation
decisions. Ordinary Home Assistant automations consume stable policy entities
instead of reproducing model logic.

## Base Assumptions

- **ASSUME-001:** Mapped sensors are generally accurate, but isolated false
  positives and correlated bursts of rapid state flapping are the primary
  observation faults the model MUST resist. Brief or prolonged false negatives
  while a person is still are plausible. Observations usually arrive promptly,
  but delayed or missed edges remain possible.
- **ASSUME-002:** The configured occupant count is authoritative. Supported
  inference covers every integer count from zero through two occupants. Two
  occupants are the primary, maximum, and overwhelmingly common operating
  profile. Count updates are ordered control inputs; they provide count, not
  identity or room.
- **ASSUME-003:** Occupants are anonymous and exchangeable. The model does not
  invent identity when paths cross or merge.
- **ASSUME-004:** Physical adjacency constrains normal movement, but a missing
  edge observation must remain recoverable at low prior.
- **ASSUME-005:** No event means no observed movement. Wall time alone does not
  diffuse occupants through the graph. An asserted transition-gate interval MAY
  establish that a graph route remained physically observable, but it is not a
  repeated movement observation. Wall time MAY only advance deterministic
  episode and assignment finalization frontiers and re-evaluate evidence already
  integrated.
- **ASSUME-006:** A local sensor clear ends its positive evidence and contributes
  only its calibrated false-negative-aware absence likelihood. It does not prove
  departure.
- **ASSUME-007:** A continuously asserted sustained sensor is correlated
  duration evidence, not a stream of independent samples.
- **ASSUME-008:** In an ordinary occupied room, a false turn-off is more
  disruptive than a delayed turn-off. Ambiguity retains trusted ownership, but
  historical ownership MUST NOT remain indefinitely after later evidence
  accounts for all configured occupants outside the room.
- **ASSUME-009:** New activation remains strict despite the false-off bias. It
  requires fresh local evidence and a plausible whole-house explanation. A
  coherent incoming path is normally sufficient support unless stronger
  evidence contradicts that arrival.
- **ASSUME-010:** Likelihoods, priors, timing windows, and policy thresholds are
  coupled calibration values, not universal truths.
- **ASSUME-011:** Repeated graph-valid route sequences reveal useful household
  routines. Learning is shared and anonymous: it describes common paths, not
  which person follows them.
- **ASSUME-012:** Supported deployments map the meaningful occupied zones and
  provide an authoritative current occupant count in the supported range. Exact
  count conservation and later observations in mapped zones are the primary
  recovery mechanisms for missed detections.
- **ASSUME-013:** A sustained room-occupancy sensor that remains continuously
  asserted after the room is vacant is an operator-visible hardware fault. The
  automatic model is not required to override that assertion; reset,
  authoritative away/count state, or device repair resolves it.

## Product Goals

- **GOAL-001, false-off safety:** Ambiguous evidence MUST retain the last trusted
  `active` state.
- **GOAL-002, strict activation:** New turn-ons MUST require fresh local evidence
  plus a supported path, unlocated mass, recovery state, or strict relocation.
  A fresh graph-backed arrival SHOULD activate by default unless specific
  contradictory evidence makes the assignment implausible.
- **GOAL-003, coherent inference:** Every probability change MUST correspond to
  an explicit event/interval emission, transition assignment, authoritative
  count kernel, or restore operation in one event-indexed probabilistic model.
- **GOAL-004, topology-first movement:** Sequential graph-valid observations are
  the primary high-confidence movement evidence.
- **GOAL-005, missed-event recovery:** Strong evidence MAY repair a missed trail,
  but one remote hit MUST NOT teleport an accounted-for occupant.
- **GOAL-006, sustained evidence:** A continuously asserted sustained sensor
  SHOULD gain bounded local support and protect final ownership until clear,
  authoritative count or away state, or explicit reset.
- **GOAL-007, multi-occupant correctness:** For every supported authoritative
  count $0 \le N \le 2$, all exact anonymous joint explanations, same-zone
  multiplicities, and count-conserving movements MUST be preserved without
  count-specific behavior or weaker guarantees at other supported counts.
- **GOAL-008, useful route learning:** Next-zone prediction MUST learn common
  multi-step paths and return routes over time while remaining separate from
  occupancy evidence and normal activation authorization.
- **GOAL-009, explainability:** Every public edge MUST have retained evidence,
  posterior event probability, named gates, and a machine-readable reason.
- **GOAL-010, determinism and performance:** Equal inputs MUST produce equal
  results with zero supported-state pruning. A valid raw detection SHOULD
  produce its in-memory public `active` acquisition decision within 50 ms and
  MUST do so
  within 100 ms under the supported workload, including the maximum supported
  occupant count on the reference topology.
- **GOAL-011, generic behavior:** Production logic MUST use roles, signal types,
  occupancy behavior, graph structure, and shared calibration. It MUST NOT
  special-case a room, entity, person, or incident.
- **GOAL-012, incident learning:** Every definitively diagnosed incident MUST
  become a permanent public-contract regression.
- **GOAL-013, eventual evidence-backed release:** When no valid local positive
  evidence remains and finalized augmented posterior mass places zero occupants
  in a held room while injectively supporting every configured occupant outside
  it, policy MUST eventually clear `active`. Elapsed time, local clear, low
  marginal, unavailable state, unlocated mass, or prediction alone remains
  insufficient.
- **GOAL-014, correlated-fault resistance:** Rapid toggles or aliases from one
  physical node MUST remain one correlated observation episode. They MUST NOT
  manufacture independent corroboration, multiple occupant movements, repeated
  activation authority, or route-learning support.
- **GOAL-015, bounded causal movement:** Movement attribution MAY remain
  unresolved across causally linked updates within finite sensor-validity and
  graph-timing bounds. Later evidence MAY resolve that attribution without
  inventing persistent person identity or revising finalized public history.
- **GOAL-016, probabilistic integrity:** Occupancy, movement assignment, support
  provenance, and policy-event probabilities MUST be marginals or events of one
  declared joint model. The implementation MUST NOT remove historical evidence
  from a later hidden state, combine unrelated marginal maxima, or attach
  probability-bearing provenance after posterior mass has merged.

## Non-Goals

- Identifying a person without an independent identity source.
- Preserving anonymous identity through an unobservable crossing or merge.
- Treating a light's state as occupancy evidence.
- Directly controlling a particular room or light.
- Treating prediction as proof of occupancy.
- Guaranteeing immediate turn-off after an unobserved departure.
- Automatically recovering from a sustained room sensor that remains stuck on;
  such a fault requires reset, authoritative state, or repair.
- Recovering the number of people who crossed from one undifferentiated sensor
  edge without distinct endpoint evidence.
- Preserving person identity through anonymous crossings, merges, or restarts.
- Solving sensor hardware faults with room-specific inference rules.
- Exposing internal thresholds to ordinary automations.

## Layer Ownership

1. **Map:** zones, nodes, adjacency, timing, roles, occupancy behavior, and
   physical entity identity.
2. **Observation:** per-entity state likelihood and correlated episode state.
3. **Occupancy:** exact anonymous count-configuration posterior.
4. **Movement:** bounded latent assignment graph and shared transition learning.
5. **Prediction:** graph-valid next-zone leases.
6. **Policy:** deterministic activation and ownership decisions over posterior
  events.
7. **Entities:** stable Home Assistant projections and diagnostics.

A defect is fixed in the lowest layer that computes the wrong result. Prediction
MUST NOT feed occupancy; policy MUST NOT alter probability; automations MUST NOT
reimplement lower-layer logic.
