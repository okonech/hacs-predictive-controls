# Occupancy and Evidence

## Exact Anonymous State

For occupant count $N \in \{0,1,2\}$ and configured zones plus `unlocated`, the
latent state is an exchangeable joint occupancy configuration. Its identity
contains only zone multiplicity, never person IDs, timestamps, event IDs, path
IDs, sensors, confidence, or policy state.

The complete state-space size is:

$$
|\mathcal{X}| = \binom{Z + N}{N}
$$

An implementation may use a count vector or canonical repeated positions.

- **MODEL-001:** Every configuration MUST contain exactly $N$ positions.
- **MODEL-002:** Anonymous permutations MUST collapse to one configuration.
- **MODEL-003:** Two occupants MAY occupy the same zone.
- **MODEL-004:** Every valid configuration MUST remain represented for supported
  counts; no occupancy probability may be pruned.
- **MODEL-005:** The posterior MUST normalize within `1e-12` after every update.

## Event-Driven Update

For a positive observation in target zone $T$, each predecessor contributes:

1. a stay explanation;
2. one-occupant moves from occupied graph-adjacent sources into $T$;
3. `unlocated -> T` when unlocated mass exists;
4. low-prior non-adjacent moves into $T$ for missed-event recovery.

A single sensor event may move at most one anonymous occupant per predecessor
context. A local `off` event replaces observation evidence and creates no
movement successors.

- **MODEL-006:** Graph-valid movement MUST have higher prior than missed
  non-adjacent movement.
- **MODEL-007:** Non-adjacent movement MUST remain possible at low prior. Active
  local evidence competes through likelihood; it does not delete hypotheses.
- **MODEL-008:** An unrelated event may support another occupant or `unlocated`
  without moving the occupant best supported in a sustained room.
- **MODEL-009:** Timing and ordering affect only compatible directional contexts
  and remain visible in diagnostics.
- **MODEL-010:** Out-of-order or ignored events MUST NOT advance posterior time,
  duration, context, policy, prediction, or learning.

## Directional Context

Direction and event time are evidence metadata attached to occupancy mass, not
occupancy identity. Each configuration retains at most four directional
variants. Excess variants merge into contextless mass for the same configuration.

- **MODEL-011:** Context compaction MUST preserve parent configuration mass.
- **MODEL-012:** Contextless mass cannot authorize graph release, prediction, or
  transition learning.
- **MODEL-013:** A movement contribution advances only its compatible context.
- **MODEL-014:** Ambiguity remains bounded alternatives or contextless mass; the
  system MUST NOT fabricate a precise anonymous track.

## Per-Entity Observation Factors

Each physical entity owns one current likelihood factor. A state edge replaces
the previous factor:

$$
\Delta \log L_e = \log L_e(\text{new}) - \log L_e(\text{old})
$$

- **EVID-001:** A duplicate same-state event has zero posterior effect.
- **EVID-002:** Repeated episodes from one entity MUST NOT count as independent
  corroboration.
- **EVID-003:** Aliases for one physical entity contribute at most one factor.
- **EVID-004:** Independent factors MAY compose only when their physical binding
  signatures and evidence episodes are independent.
- **EVID-005:** `unknown` and `unavailable` are neutral unless an explicit fault
  model says otherwise.

## Sustained Duration Evidence

A sustained sensor remaining asserted is one correlated duration observation.
For asserted duration $t$, use a calibrated bounded log-likelihood-ratio
contribution $B_e(t)$. Re-evaluation applies only the replacement delta:

$$
\Delta B_e = B_e(t_{new}) - B_e(t_{applied})
$$

The required shape is monotone, bounded, and saturating while the episode is
valid. One acceptable calibration family is:

$$
B_e(t) = B_{max,e}\left(1-e^{-t/\tau_e}\right)
$$

The family is part of the model; $B_{max,e}$ and $\tau_e$ are shared profile
calibration values that require replay evidence and stuck-sensor analysis.

- **EVID-006:** Duration evidence applies only to explicitly sustained evidence
  profiles.
- **EVID-007:** Re-evaluating at the same time is idempotent.
- **EVID-008:** Event frequency MUST NOT change total duration contribution.
- **EVID-009:** Duration influence MUST have a finite ceiling.
- **EVID-010:** Clearing or replacing the assertion MUST remove its applied
  duration factor.
- **EVID-011:** Confirmed path-specific departure or relocation MAY invalidate an
  old asserted episode even if a faulty sensor remains on.
- **EVID-012:** One remote event MUST NOT invalidate local asserted evidence.
- **EVID-013:** Duration state MUST survive restart without duplicate application.
- **EVID-014:** Long assertions SHOULD produce sensor-health diagnostics; health
  warnings do not move occupancy or release policy.
- **EVID-015:** Duration evaluation MUST NOT rewrite path nodes, motion-event
  timestamps, evidence IDs, dispositions, update sequence, prediction, or
  learning. A valid assertion MAY localize its source through the present using
  an explicit observation-validity interval, not a fabricated path event.

Naive periodic reapplication is rejected because it counts correlated samples
as independent. A hard anchor is rejected because it gives a stuck sensor
unlimited authority and prevents evidence-based departure.

## Persistence and Bootstrap

Persistence retains enough state to reproduce the same next decision: map
fingerprint, exact count, complete posterior, bounded contexts, policy latches,
valid leases, per-entity factor and episode state, applied duration contribution,
departure invalidation, transition counts, and update sequence.

- **STATE-001:** Restore MUST validate schema, count, map compatibility,
  datetimes, finite values, normalization, and context mass atomically.
- **STATE-002:** Invalid state MUST fail as a unit with an explicit diagnostic.
- **STATE-003:** Bootstrap reconciles one complete snapshot without synthetic
  movement, activation, prediction, or learning.
- **STATE-004:** Identical replay input MUST produce deterministic public
  timelines and diagnostic ordering.
