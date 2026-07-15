# Movement and Prediction

## Sequential Movement

Sequential graph-valid observations with compatible order, latent predecessor
assignment, and edge timing are the primary high-confidence movement path.
Movement assignment retains origin, source, target, nodes, endpoint IDs,
probability, and disposition inside the augmented Bayesian state before it is
marginalized into the forward occupancy message. Physical-node observation
episodes have semi-Markov bounded validity, and graph assignments may remain
unresolved across a finite causal interval before finalization.

- **MOVE-001:** Release and learning MUST use probability summed from the
  augmented joint mass satisfying the required path or support event, not an
  aggregate of unrelated zone marginals or independently selected maxima.
  Learning retains the complete route origin. Mutually exclusive alternatives
  may aggregate only when they satisfy the same policy event; graph-invalid
  dispositions never qualify as graph support.
- **MOVE-002:** Graph departure MAY invalidate superseded historical origin
  evidence only after the configured coherent movement gate passes. It MUST NOT
  invalidate current valid sustained room-positive evidence to force automatic
  final-occupant release.
- **MOVE-003:** When two occupants share an origin, one departure leaves one
  occupant there and MUST NOT clear ownership.
- **MOVE-004:** Another occupant's event MUST NOT advance or release the context
  under review.
- **MOVE-005:** A fresh local observation backed by a coherent incoming path is
  presumptively valid movement. Policy SHOULD accept the destination activation
  unless contradictory count, local, timing, or path evidence makes that
  assignment materially less plausible.
- **MOVE-015:** A fresh target-positive observation MAY create a
  `censored_graph_path` candidate from source $S$ through asserted
  transient gate $G$ to target $T$ when $S$, $G$, and $T$ are distinct, both
  physical graph edges exist, and $G$ cannot emit another positive edge because
  its observation episode remains open. Source, gate, and target episode
  intervals MUST have compatible order and fit the sum of configured edge
  timings, using the shared per-edge default when timing is absent. The open gate
  is structural route-availability evidence, not another observation
  likelihood.

  One fresh target event moves at most one anonymous occupant. The same open gate
  interval MAY support more than one crossing, up to the authoritative occupant
  count, only when each crossing has a distinct compatible target event and a
  feasible source-count assignment. Consumption is idempotent per
  `(source episode, gate episode, target event)` assignment; the same target
  event MUST NOT move two occupants. Ambiguous assignments remain alternatives
  and MUST NOT create person identity.

  Source-count feasibility is evaluated per predecessor configuration, not from
  a zone marginal threshold. Assigning $k$ crossings from one source requires at
  least $k$ occupants in that source in the predecessor configuration, consumes
  $k$ distinct target events, and creates successors that decrement and
  increment the corresponding anonymous zone counts exactly once per event.
  Therefore two occupants in one source plus one gate interval and one target
  event supports at most one crossing; two compatible target events may support
  two crossings. When different sources compete for one target event, they are
  mutually exclusive alternatives rather than simultaneous movements.

  Policy MAY use a finalized interval-censored assignment as admissible arrival
  or outside-support evidence under the same posterior event as ordinary graph
  movement. Unresolved assignments MUST NOT release ownership. Prediction,
  prelighting, transition learning, and route learning remain limited to
  directly observed `graph_valid` movement.
  Invalidated, stale, disconnected, out-of-order, or graph-incompatible evidence
  MUST NOT qualify.

## Bounded Causal Association

The filter retains the exact unresolved factor graph of anonymous predecessor
and endpoint-assignment variables while observations can still be causally
connected. This is bounded fixed-lag data association over an event-indexed
state model, not a dense time-sliced history and not persistent labeled
tracking.

Each candidate $C$ stores a semantic deadline:

$$
D(C)=\sup\{t:\text{an endpoint at event time }t\text{ can satisfy every episode
validity and graph-timing constraint of }C\}.
$$

The candidate is created only when this feasible set is nonempty. Every profile
and route bound is finite, so $D(C)$ is finite and computable by interval
constraint propagation when the candidate is created or compatibly extended.
Unrelated activity cannot extend it.

The deployment declares one finite maximum accepted delivery lateness
$L_{late}$. Trusted receive time $r$ and normalized source event timestamps MUST
share the same validated UTC clock domain. At receive time $r$, the monotone
event-time watermark is $W(r)=r-L_{late}$. An input at or before the finalized
watermark is stale and is ignored diagnostically. An input newer than the
watermark may be inserted into the retained graph and causes deterministic
forward-message recomputation. A candidate finalizes exactly when $W(r)>D(C)$.
A wall-clock callback may advance the watermark and evaluate finalization, but
contributes no observation or movement evidence.

- **MOVE-016:** A causal assignment remains revisable only before its stored
  semantic deadline and while it is newer than the finalized watermark. Event
  count, unrelated sensor traffic, inactivity, and room-specific timers MUST NOT
  shorten or extend that interval.
- **MOVE-017:** Accepted in-lag evidence MAY reweight unresolved anonymous
  assignments and confirm or reject a prior interpretation. Activation MAY use
  the forward decision immediately and is never retracted. Release waits for
  every assignment and support variable on which it depends to finalize, so a
  later smoothing update cannot retract an emitted release edge.
- **MOVE-018:** Competing graph-valid source assignments into one target event
  preserve ownership for every affected origin until the bounded association is
  resolved. A stronger path MUST NOT release a different origin while a
  graph-valid alternative backed by current local evidence can explain the same
  target event.
- **MOVE-019:** Finalization marginalizes expired assignment variables into the
  forward occupancy message and MUST preserve occupancy probability exactly. It
  MUST NOT release ownership or convert ambiguous mass into a precise track. A
  finite finalized support certificate may remain only while its joint
  probability and evidence validity remain available for policy or learning.
- **MOVE-020:** The supported workload MUST declare numeric maximum accepted
  event rate $R_{max}$, instantaneous burst $B_{max}$, active physical-node
  episodes, maximum semantic route duration $D_{max}$, and $L_{late}$. The number
  of accepted endpoints whose assignments can coexist is bounded by
  $E_{max}=B_{max}+\lceil R_{max}(D_{max}+L_{late})\rceil$ after episode grouping;
  diagnostics and benchmarks MUST report the tighter observed graph and joint-
  assignment-state maxima. If input exceeds the envelope, processing MAY queue
  and exceed the latency target, but inference MUST retain exact occupancy mass,
  preserve existing `active`, and withhold release and learning until the exact
  association update completes. Overload MUST be explicit in diagnostics.

An active sustained observation can support localization through its explicit
validity interval. Transition timing conditions on that interval; it does not
rewrite a previous event or create a synthetic endpoint.

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
- **PRED-005:** Occupancy mass without a qualifying finalized directional
  assignment does not predict.
- **PRED-006:** Simultaneous supported contexts retain independent leases that
  expire and cancel independently.
- **PRED-007:** `prelight` is a bounded lease projection. The lease itself never
  feeds occupancy, movement, `active`, policy, or route learning. Later
  finalized graph-valid observed movement remains eligible for learning whether
  or not `prelight` was on.
- **PRED-008:** Learning requires high-probability finalized path-specific graph
  assignment. It MUST NOT learn from prediction, contextless mass, missed
  movement, or arbitrary temporal pairing of interleaved occupants.
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
- **PRED-013:** Finalized route statistics MAY parameterize a small, bounded
  prior adjustment among graph-valid assignment alternatives. That shared
  transition parameter is upstream model state, not feedback from a prediction
  lease. It requires fresh compatible observations and MUST NOT alter a sensor
  likelihood, create a graph-invalid candidate, override strong contradictory
  evidence, clear `active`, or independently set `active`.
- **PRED-014:** The route model MAY create `prelight` before raw
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
