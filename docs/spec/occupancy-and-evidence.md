# Occupancy and Evidence

## Exact Anonymous Occupancy State

At accepted event index $k$, the hidden occupancy state is a count vector
$X_k=(n_0,\ldots,n_Z)$ over configured zones plus `unlocated`, where
$\sum_z n_z=N_k$ and the authoritative count $N_k\in\{0,1,2,3,4,5\}$. The state
contains multiplicity only, never person IDs, timestamps, event IDs, path IDs,
sensors, confidence, or policy state. Later requirements use symbolic $N$;
behavior MUST NOT be implemented as separate count-specific models.

The complete state-space size is:

$$
|\mathcal{X}| = \binom{Z + N}{N}
$$

For the 16-zone reference topology, the maximum supported count requires
$\binom{21}{5}=20{,}349$ exact occupancy configurations. An implementation may
use a compact indexed numeric array, a count vector, canonical repeated
positions, or an equivalent exact representation. It MUST NOT prune supported
occupancy probability or silently approximate the posterior to meet the
performance budget.

- **MODEL-001:** Every configuration MUST contain exactly $N$ positions.
- **MODEL-002:** Anonymous permutations MUST collapse to one configuration.
- **MODEL-003:** Any multiplicity from zero through $N$ MAY occupy the same zone.
- **MODEL-004:** Every valid configuration MUST remain represented for supported
  counts; no occupancy probability may be pruned.
- **MODEL-005:** The posterior MUST normalize within `1e-12` after every update.

## Event-Driven Update

Each accepted observation updates an event-indexed Bayesian state model. For
observation $O_k$, latent anonymous movement assignment $A_k$, physical-node
episode state $H_{k-1}$, and graph $G$:

$$
p_k(x,a) \propto
L_k(O_k \mid x,a,H_{k-1})
\sum_{x'} T_k(x,a \mid x',N_k,G)p_{k-1}(x')
$$

The occupancy posterior is the exact marginal
$p_k(x)=\sum_a p_k(x,a)$. Observation likelihood, transition probability, and
assignment probability therefore remain one coherent joint measure; movement
provenance is not attached heuristically after occupancy successors merge.

For a positive observation in target zone $T$, each predecessor contributes:

1. a stay explanation;
2. one-occupant moves from occupied graph-adjacent sources into $T$;
3. `unlocated -> T` when unlocated mass exists;
4. low-prior non-adjacent moves into $T$ for missed-event recovery.

A single external endpoint event may move at most one anonymous occupant per
predecessor configuration. Its transition operator therefore needs only stay
plus one-occupant source-to-target alternatives, not a Cartesian product of
independent per-occupant moves. A local `off` event contributes its calibrated
episode likelihood and creates no movement endpoint.

An optimized implementation MAY precompute move indexes, but they MUST cover
every occupancy configuration and every configured source-target pair in the
supported state space. Precomputation changes lookup cost, never transition
support or probability.

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

## Augmented Association and Support State

Direction, event time, episode identity, and endpoint consumption belong to the
bounded latent assignment state $A_k$, not occupancy identity. While an
assignment remains causally revisable, all mutually exclusive feasible source
and route alternatives retain their joint probability. There is no arbitrary
per-configuration top-$K$ context cap.

When an assignment passes its event-time finalization frontier, inference
marginalizes it into the forward occupancy message. Marginalization MUST
preserve occupancy probability exactly. A finite support certificate MAY remain
while policy or learning can still consume it, but its probability MUST be a
lossless marginal of the same assignment mass and its validity MUST be bounded.
Mass whose causal assignment has been marginalized without such a certificate
is contextless for policy purposes.

- **MODEL-011:** Assignment finalization, marginalization, and compaction MUST
  preserve the occupancy posterior and normalization exactly.
- **MODEL-012:** Contextless, `unlocated`, prediction-only, or coarsened support
  cannot authorize graph release, prediction, or transition learning.
- **MODEL-013:** A movement contribution advances only its compatible assignment
  alternatives and consumes each external endpoint at most once.
- **MODEL-014:** Ambiguity remains mutually exclusive assignment mass or
  contextless mass; the system MUST NOT fabricate a precise anonymous track.
- **MODEL-015:** Bounded anonymous predecessor and assignment links are latent
  evidence association, not persistent occupant identity.
- **MODEL-016:** Any policy probability conditioned on support provenance MUST
  be computed by summing the augmented joint mass satisfying that support event.
  It MUST NOT be reconstructed from independent marginal maxima or labels added
  after configurations merge.

## Physical-Node Observation Emissions

Each physical node owns a finite episode state $H_e$. An accepted edge or
duration interval contributes one conditional emission likelihood to the
event-indexed model:

$$
\Delta \log L_{e,k}=
\log P(O_{e,k}\mid X_k,A_k,H_{e,k-1})
$$

Past emissions remain integrated through the forward posterior. After occupancy
may have transitioned, inference MUST NOT divide an old observation likelihood
out of the current hidden state. An unfinalized episode factor MAY be recomputed
or replaced only over the same historical variables inside the retained factor
graph.

- **EVID-001:** A duplicate same-state event has zero posterior effect.
- **EVID-002:** Repeated edges inside one episode MUST NOT count as independent
  observations. A later distinct episode MAY provide new temporal evidence, but
  the same physical node never becomes an independent corroborating source for
  itself.
- **EVID-003:** Aliases for one physical entity contribute at most one factor.
  Raw alias states remain separately observable for episode and restart
  handling, but the physical node contributes one effective emission process.
  An alias edge while that node is already asserted cannot independently create
  movement.
- **EVID-004:** Independent factors MAY compose only when their physical binding
  signatures and evidence episodes are independent.
- **EVID-005:** `unknown` and `unavailable` are neutral unless an explicit fault
  model says otherwise. They close future endpoint validity but provide neither
  a clear observation nor release evidence.

## Correlated Observation Episodes

Raw state edges from one physical node are grouped into a correlated observation
episode using finite correlation, stable-clear, hold, and refractory semantics
declared by its shared sensor profile. Those bounds describe the sensor emission
process; they are not room-specific inactivity timers.

Every profile MUST declare three distinct finite parameters:

1. `burst_correlation_window`: the maximum separation at which rapid clear and
  reassertion edges remain one correlated flap episode;
2. `stable_clear_window`: how long a clear must remain unreasserted before the
  prior positive becomes historical; and
3. `refractory_or_hold_interval`: the interval in which asserted hardware may be
  physically unable to emit another positive endpoint.

The parameters MAY have equal calibrated values, but one MUST NOT silently serve
as the default for another. In particular, a long hardware refractory interval
does not turn all edges in that interval into one flap burst.

A positive edge starts an episode. Clear and reassertion edges inside the
profile's correlation interval update that same episode sequence. If clear
remains stable through the profile's finite stable-clear interval, the prior
positive becomes historical and the episode finalizes at its declared event-time
deadline. A later positive starts a new episode. A continuously asserted positive
remains current; automatic recovery from that stuck-on condition is explicitly
out of scope.

- **EVID-016:** One physical-node episode contributes one correlated emission
  process and one bounded duration-survival process. Repeated state edges,
  aliases, or timer evaluations within that episode MUST NOT create independent
  corroboration.
- **EVID-017:** One observation episode may seed at most one fresh local
  activation and one source or target endpoint for any particular causal
  assignment. Repeated flaps in the same episode MUST NOT move additional
  occupants, reopen finalized movement, or update route learning.
- **EVID-018:** Episode continuity, stable-clear deadline, and finalization MUST
  be deterministic functions of accepted event times and finite shared sensor
  profile parameters named above. The stable-clear deadline is exactly the most
  recent accepted clear event time plus `stable_clear_window`, unless a
  reassertion in the same episode supersedes it. Stable clear finalization or
  availability loss changes evidence validity only; it MUST NOT move occupancy
  or release `keep_on` by itself. A wall-clock callback MAY advance the
  finalization frontier and re-evaluate already satisfied policy gates without
  adding evidence.
- **EVID-019:** A clear observation contributes a calibrated weak absence
  likelihood that explicitly allows false negatives. Repeated clear evaluations
  from one unchanged episode are idempotent and MUST NOT accumulate absence
  evidence.

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
calibration values that require false-positive, false-negative, long-assertion,
and movement replay evidence.

- **EVID-006:** Duration evidence applies only to explicitly sustained evidence
  profiles.
- **EVID-007:** Re-evaluating at the same time is idempotent.
- **EVID-008:** Event frequency MUST NOT change total duration contribution.
- **EVID-009:** Duration influence MUST have a finite ceiling.
- **EVID-010:** Clearing ends future asserted-duration increments and contributes
  its calibrated clear emission. Historical duration evidence remains integrated
  in the posterior; it MUST NOT be subtracted from a later hidden state.
- **EVID-011:** Confirmed path-specific departure or relocation MAY outweigh a
  historical positive episode through the joint posterior, but automatic
  inference MUST NOT discard a current valid sustained room-positive assertion
  merely to force release. Authoritative zero count or away state and explicit
  reset remain permitted overrides. Automatic recovery from a continuously
  stuck-on room sensor is out of scope.

  A room-positive assertion is current while its physical node's effective state
  is positive or a subsequent clear remains before that episode's deterministic
  stable-clear deadline. If no reassertion occurs, the positive becomes
  historical exactly at that deadline even if its episode provenance remains in
  the fixed-lag graph. Crossing the deadline MAY remove a release veto and
  re-evaluate already supported policy gates, but the passage of time is not
  evidence and cannot satisfy a missing movement, posterior, support-accounting,
  or competition gate.
- **EVID-012:** One remote event MUST NOT invalidate local asserted evidence.
- **EVID-013:** Duration state MUST survive restart without duplicate application.
- **EVID-014:** Long assertions SHOULD produce sensor-health diagnostics; health
  warnings do not move occupancy or release policy.
- **EVID-015:** Duration evaluation MUST NOT rewrite path nodes, motion-event
  timestamps, evidence IDs, dispositions, update sequence, prediction, or
  learning. A valid assertion MAY localize its source through the present using
  an explicit observation-validity interval, not a fabricated path event.

Naive periodic reapplication is rejected because it counts correlated samples
as independent. An infinite posterior anchor is also rejected: a current
sustained assertion receives bounded likelihood support while its separate
automatic-release veto remains an explicit policy decision under `POL-017`.

## Authoritative Count Transitions

The count source provides an authoritative ordered control input $N_k$. A count
change is an explicit transition between occupancy state spaces, never an
identity observation and never an instruction to choose a room heuristically.

For a one-person increase, the transition adds one anonymous position according
to a normalized arrival prior $q_z^+$ derived from independent boundary evidence
when available and otherwise concentrated on `unlocated`:

$$
K^+(x+e_z\mid x)=q_z^+
$$

For a one-person decrease, each predecessor removes one anonymous position with
probability proportional to its multiplicity and any independent boundary-exit
evidence $w_z^-$:

$$
K^-(x-e_z\mid x)=
\frac{x_z w_z^-}{\sum_j x_j w_j^-}
$$

With no location-bearing exit evidence, all $w_z^-=1$, so each anonymous
position is exchangeable. Larger count changes apply these kernels repeatedly in
a deterministic order.

- **MODEL-017:** Count transitions MUST preserve normalization, exchangeability,
  and every configuration in the new authoritative count space.
- **MODEL-018:** A count increase MUST NOT synthesize movement, local activation,
  or person identity. Independent entry evidence MAY shape $q^+$ through the
  ordinary observation and transition model.
- **MODEL-019:** A nonzero count decrease MUST NOT select a room for release,
  invert marginals into identity, or remove the least-supported zone. Policy
  evaluates the resulting exact posterior and support event for each held zone.
- **MODEL-020:** $N=0$ produces the unique empty configuration. It is the only
  count value that categorically proves every zone empty.
- **MODEL-021:** Stale or duplicate count controls MUST be ignored and diagnosed;
  the same accepted count transition MUST NOT be applied twice.

## Persistence and Bootstrap

Persistence retains enough state to reproduce the same next decision: map
fingerprint, exact count, complete forward posterior, unresolved fixed-lag factor
graph, support-event marginals, episode and endpoint IDs, consumed assignments,
finalization deadlines and watermark, policy hysteresis and ownership state,
valid leases, per-node episode state and applied duration contribution, count
transition sequence, route statistics, and update sequence.

- **STATE-001:** Restore MUST validate schema, count, map compatibility,
  datetimes, finite values, normalization, and context mass atomically.
- **STATE-002:** Invalid state MUST fail as a unit with an explicit diagnostic.
- **STATE-003:** Bootstrap reconciles one complete snapshot without synthetic
  movement, activation, prediction, or learning.
- **STATE-004:** Identical replay input MUST produce deterministic public
  timelines and diagnostic ordering.
- **STATE-005:** Restore MUST purge only assignments already beyond their stored
  finalization frontier. Purging marginalizes their probability into the forward
  message, emits no public edge, and never makes an old endpoint reusable; a new
  crossing requires new episode and endpoint IDs.
