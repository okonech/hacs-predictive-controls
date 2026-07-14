# Movement and Prediction

## Sequential Movement

Sequential graph-valid observations with compatible order, incoming context,
and edge timing are the primary high-confidence movement path. Movement evidence
retains origin, source, target, nodes, evidence IDs, probability, and disposition
before occupancy successors merge.

- **MOVE-001:** Release and learning MUST use path-specific coherent probability,
  not an aggregate of unrelated zone marginals. Learning retains the complete
  route origin. Release MAY aggregate mutually exclusive route alternatives
  that agree on the same immediate graph-valid source-to-target segment, but it
  MUST NOT combine different source segments or graph-invalid dispositions.
- **MOVE-002:** Graph departure MAY invalidate sustained origin evidence only
  after the configured coherent movement gate passes.
- **MOVE-003:** When two occupants share an origin, one departure leaves one
  occupant there and MUST NOT clear ownership.
- **MOVE-004:** Another occupant's event MUST NOT advance or release the context
  under review.
- **MOVE-005:** A fresh local observation backed by a coherent incoming path is
  presumptively valid movement. Policy SHOULD accept the destination activation
  unless contradictory count, local, timing, or path evidence makes that
  assignment materially less plausible.

An active sustained observation can establish that the occupant remained
localized through the present. Transition timing consumes that explicit
observation-validity interval; it does not rewrite the previous motion event.

## Anonymous Track Diagnostics

The panel MAY project the most probable current joint configuration as anonymous
track slots. For the $k$th displayed occupant in zone $z$, confidence is the
exact count-marginal tail $P(N_z \ge k)$. Unlocated positions are omitted from
the localized track list and remain visible through the configured-versus-
localized count.

- **MOVE-009:** A displayed track is a current anonymous posterior projection,
  not a persistent person identity. Its ordering MUST be deterministic, preserve
  same-zone multiplicity, expose asserted source entities when present, and
  MUST NOT feed occupancy, movement, prediction, or policy.

## Missed-Event Relocation

The model cannot assume every physical edge fires. Non-adjacent relocation
remains a low-prior explanation, but policy promotion requires:

1. independent positive destination evidence or an equivalently strong signal;
2. low retained origin support;
3. high destination support;
4. decisive relocation odds over retaining the origin;
5. exact accounting of all configured occupants;
6. an explicit `missed_movement` evidence trail.

- **MOVE-006:** One isolated or repeatedly flapping remote entity cannot confirm
  relocation.
- **MOVE-007:** Ambiguous relocation retains origin ownership and rejects or
  quarantines destination activation.
- **MOVE-008:** An asserted sensor MUST NOT hard-delete non-adjacent relocation
  hypotheses. Competing evidence is resolved by the posterior and strict policy.

## Next-Zone Prediction

Prediction answers what may happen next, not where an occupant is now. It is a
posterior predictive projection over supported directional contexts:

$$
P(Z_{next}=j \mid E_{\le t}) =
\sum_k P(k \mid E_{\le t})P(j \mid k,G,M)
$$

where $k$ is directional context, $G$ is the physical graph, and $M$ is shared
transition learning.

- **PRED-001:** Only graph-valid forward neighbors are candidates.
- **PRED-002:** The incoming zone is excluded unless reversal evidence exists.
- **PRED-003:** Exactly one forward candidate creates a deterministic lease in
  the same inference cycle; learned history is not required for an unambiguous
  graph continuation.
- **PRED-004:** Multiple forward candidates are ranked only by configured or
  learned probabilities normalized over those candidates.
- **PRED-005:** Contextless occupancy mass does not predict.
- **PRED-006:** Simultaneous supported contexts retain independent leases that
  expire and cancel independently.
- **PRED-007:** `prelight_plausible` is a bounded lease projection. It never feeds
  occupancy, movement, activation, or keep-on.
- **PRED-008:** Learning requires high-probability path-specific graph movement.
  It MUST NOT learn from prediction, contextless mass, missed movement, or
  arbitrary temporal pairing of interleaved occupants.
- **PRED-009:** Shared transition statistics are allowed. Person-specific
  prediction requires an independent identity source and is out of scope.

## Learned Route History

The predictor SHOULD learn more than one-step edge popularity. It retains
bounded, anonymous route context so repeated sequences such as
`office -> stairs -> dining_room -> kitchen` and their observed return routes
can influence later predictions.

- **PRED-010:** Learning MUST support variable-order graph-valid route prefixes,
  not only first-order source-to-destination counts.
- **PRED-011:** A route prefix is associated with a compatible directional
  context, never a persistent person identity. Ambiguous or interleaved paths do
  not update a precise route.
- **PRED-012:** At a branch, the predictor uses the longest sufficiently
  supported matching route prefix, then backs off deterministically to shorter
  prefixes and finally shared first-order counts.
- **PRED-013:** Learned route probability provides a small, bounded transition
  prior boost among graph-valid candidates. With fresh compatible observations,
  it MAY increase relative path and movement confidence. It MUST NOT alter a
  sensor likelihood, create a graph-invalid candidate, override strong
  contradictory live evidence, release `keep_on`, or independently set
  `activation_plausible`.
- **PRED-014:** The route model MAY create `prelight_plausible` before raw
  destination motion when posterior path support and learned continuation
  probability pass their gates.
- **PRED-015:** Forward and return sequences are learned from observed movement
  independently. A common outbound route does not imply its reverse without
  evidence.
- **PRED-016:** Route statistics MUST be bounded, persisted, deterministic, and
  capable of aging or discounting so obsolete routines do not dominate forever.
- **PRED-017:** A single traversal cannot make a route authoritative. Promotion
  requires configurable minimum support, and diagnostics expose the matched
  prefix, support, backoff level, and resulting probability.
