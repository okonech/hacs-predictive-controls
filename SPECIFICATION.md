# Predictive Controls Specification

**Status:** Normative
**Authority:** This file is the sole source of product and model requirements.
**Supported occupants:** 0 through 2, with 2 as the primary operating profile.

Code, tests, changelogs, issues, and user documentation describe or
implement this specification but do not override it. If another repository file
conflicts with this file, this file wins and the other file must be corrected.

## 1. Mission

Predictive Controls converts imperfect, asynchronous sensor observations into
responsive, conservative, and explainable per-zone automation decisions. It is
optimized for lighting and similar environmental controls, not for reconstructing
exact person identities or proving a globally unique movement history.

The model must answer four separate questions while publishing one normal
per-zone control entity:

1. **Zone belief:** How likely is each zone to benefit from remaining active?
2. **Traversal context:** Which fresh local observations are physically plausible
   given recent or current activity on the adjacency graph?
3. **Acquisition:** Is the evidence sufficient to change an inactive zone's
   public `active` state without exposing ordinary local sensor false positives?
4. **Retention:** Does the filtered zone belief justify keeping an already-active
   zone on under asymmetric false-on and false-off costs?

The model may retain internal `inactive`, `pending`, `predicted`, and `active`
policy phases, but ordinary automations consume only
`binary_sensor.<zone>_active`. Compatible adjacency and a mature high-confidence
prediction are zero-wait acquisition paths. Unsupported local evidence may enter
a bounded track-bootstrap phase that remains publicly `off` until a compatible
second observation establishes a graph-local track.

Track confidence is intentionally graduated. Two distinct sequential adjacent
physical nodes establish a `provisional` track: sufficient for immediate local
activation at its leading edge, but insufficient for whole-home count conflict,
sensor-health contradiction, route learning, or prediction. A third distinct
sequential adjacent node promotes the track to `confirmed` for those broader
uses.

Prediction is policy authorization, not occupancy evidence. A mature
high-confidence graph-adjacent prediction may activate the same public `active`
entity early, but it must never change zone belief, create traversal context, or
learn from its own outcome.

## 2. Design Principles

- **REQ-GOAL-001, local control:** A zone decision should depend primarily on
  evidence in that zone and its graph neighborhood. Unrelated weak or unresolved
  activity elsewhere must not make a local result unavailable. A bounded count
  conflict from distinct strong tracked fronts may reject disconnected local
  evidence and eventually degrade a contradicted stuck assertion, but it may not
  delay graph-authorized or mature prediction-authorized acquisition.
- **REQ-GOAL-002, probability-driven policy:** The same declared zone belief must
  inform both activation and release. Historical ownership must not override a
  sufficiently low filtered belief indefinitely.
- **REQ-GOAL-003, asymmetric safety:** For an inactive zone, preventing an
  unsupported false turn-on costs more than bounded waiting for graph support.
  For an already-active stay zone, preventing a false off costs more than a
  delayed off. Acquisition authorization and release hysteresis must express
  these different costs without moving inference into automations.
- **REQ-GOAL-004, sensor realism:** Aliases, flaps, hardware hold time, stable
  clear, and prolonged assertions are correlated sensor behavior, not streams of
  independent evidence.
- **REQ-GOAL-005, graph plausibility:** Normal movement follows configured
  adjacency. A fresh track may bootstrap from any sequential pair of distinct
  adjacent sensor episodes; it does not require continuity with an older track.
  Bounded missed-edge reacquisition remains possible without inventing a person
  identity or an exact route. A lone local positive edge is not by itself
  permission to turn on an inactive zone.
- **REQ-GOAL-006, multi-occupant tolerance:** Simultaneous activity fronts must be
  supported for authoritative counts 0, 1, and 2, including two occupants in one
  zone or on independent paths.
- **REQ-GOAL-007, bounded state:** Every probability, traversal influence,
  lease, hold, and diagnostic retention is bounded. Current asserted stay
  evidence may persist only while its physical sensor remains asserted; it
  cannot create permanent identity or neighboring authority.
- **REQ-GOAL-008, deterministic replay:** Equal ordered inputs, map, profiles,
  count controls, and restored state must produce equal outputs and explanations.
- **REQ-GOAL-009, generic behavior:** Production logic uses node roles, sensor
  profiles, reliability, adjacency, and shared calibration. It must not special
  case a room, entity, person, or incident.
- **REQ-GOAL-010, incident learning:** Every definitively diagnosed production
  incident becomes a retained public-contract regression with its observed event
  times and material state.
- **REQ-GOAL-011, fast supported activation:** Compatible adjacent evidence and
  mature high-confidence prediction take the zero-wait policy path. They must not
  enter track-bootstrap retention or perform blocking work.
- **REQ-GOAL-012, one control authority:** All normal turn-on and turn-off
  complexity remains inside the model and is projected through one per-zone
  `active` binary entity. Automations must not combine separate on-authorization
  and off-retention entities.

## 3. Non-Goals

- Persistent or inferred person identity.
- A globally unique anonymous movement assignment.
- Exact count-vector enumeration or injective proof that every occupant is
  supported outside a zone before that zone may release.
- Treating a light state, prediction, policy output, timer callback, or repeated
  unchanged sensor state as occupancy evidence. A timer may resolve or expire an
  already-recorded pending candidate, and prediction may authorize policy, but
  neither is a new physical observation.
- Guaranteeing a correct location when all relevant sensors miss an occupant.
- Treating assertion duration alone as proof that an asserted stay sensor failed
  or that its room became empty.
- Room-specific thresholds or Home Assistant automations that reproduce model
  logic.
- A second public binary entity that automations must combine with `active` to
  obtain normal turn-on behavior.
- A universal wall-clock guarantee covering device transport, Home Assistant
  scheduling, or actuator latency. The integration is responsible for bounded
  decision time and same-update entity publication after it receives evidence.

## 4. Inputs and Map Contract

The model consumes:

- physical sensor state events with occurrence timestamps and a separate
  processing/receipt frontier;
- a map of zones, physical nodes, entity aliases, node roles, sensor profiles,
  reliability, adjacency, and graph timing;
- an authoritative occupant count in the supported range; and
- deterministic timer frontiers used only to advance declared decay, clear,
  health, track-bootstrap expiry, lease, and policy dwell state.

Each entity alias maps to exactly one physical node. A physical node maps to one
zone and declares one role:

- `stay`: evidence that one or more occupants may remain in a room;
- `transition`: evidence that a boundary or circulation area is being traversed;
- `entry`: evidence at a household boundary, usable for count-aware reacquisition;
  or
- `hybrid`: explicitly calibrated stay and transition behavior when the hardware
  cannot be represented by one primary role.

- **REQ-MAP-001:** Adjacency is declared between physical nodes or zones and must
  reflect traversable geography, not naming similarity.
- **REQ-MAP-002:** Node roles and profiles are shared behavioral categories.
  Zone-specific copies with different constants are prohibited unless a distinct
  physical sensor capability requires a separately named reusable profile.
- **REQ-MAP-003:** A map change invalidates incompatible restored filter state
  atomically and bootstraps without synthetic movement or public edges.
- **REQ-MAP-004:** Unknown and unavailable entities are neutral observations and
  close their future traversal authority until recovery. They atomically
  invalidate pending candidates and traversal tokens sourced from that physical
  node, so later activity cannot recreate authority from stale health state.
  They are not clear or absence evidence.
- **REQ-MAP-005:** Every physical node declares a finite reliability in `(0, 1]`.
  Reliability must temper local likelihood and health/conflict evaluation; it
  may not be retained only for display or prediction smoothing.

## 5. Physical Sensor Episodes

Raw alias edges are collapsed into one deterministic episode per physical node.
Every sensor profile declares independently:

1. `burst_correlation_window`: rapid clear/reassert edges that remain one flap
   episode;
2. `stable_clear_window`: how long clear must remain unchanged before the
   positive assertion is historical;
3. `hardware_hold_interval`: the period in which hardware may be unable to emit
   another positive edge;
4. `assertion_trust_horizon`: how long a continuous transition or boundary
   assertion retains full evidential weight before sensor-health degradation
   begins, and the upper bound on assertion-derived traversal authority;
5. `post_clear_residual`: the role-specific occupancy residual after stable
   clear; and
6. `traversal_context_window`: how long the node may authorize a graph-neighbor
   arrival;
7. `track_bootstrap_window`: how long an unsupported episode may pair with a
   later distinct adjacent episode before the candidate is rejected.

- **REQ-EVID-001:** A physical positive edge starts at most one episode and
  contributes one local likelihood update. It creates at most one traversal
  token only when that episode receives traversal or acquisition authorization.
  A token does not by itself imply public activation; a rejected pending episode
  creates no token.
- **REQ-EVID-002:** Same-state callbacks, alias edges while the physical node is
  already asserted, timer reevaluation, and flap edges in one episode contribute
  no independent evidence and create no extra traversal tokens.
- **REQ-EVID-003:** A stable clear contributes one calibrated weak absence update.
  It starts residual decay but does not prove departure.
- **REQ-EVID-004:** A current assertion is a bounded correlated observation.
  Duration influence may saturate but may not grow without limit.
- **REQ-EVID-005:** When a transition or boundary assertion exceeds its trust
  horizon, its likelihood influence decays toward a finite profile floor and a
  sensor-health warning is emitted. A stay assertion remains strong, bounded
  local evidence while the device is currently asserted unless the persistent
  external contradiction in `REQ-COUNT-009` health-degrades it; elapsed wall time
  alone must not convert it into absence. No continuous assertion may authorize
  unlimited neighboring arrivals.
- **REQ-EVID-006:** Out-of-order or duplicate inputs are ignored and diagnosed.
  They do not advance filter time, decay, traversal, policy, prediction, or
  learning. Home Assistant `time_fired` is the occurrence frontier used for this
  ordering; callback receipt time is retained separately as `processing_at` for
  audit and latency diagnostics. Live and replay normalization both preserve
  `unknown` and `unavailable` rather than dropping them.
- **REQ-EVID-007:** Each distinct target episode may consume a compatible open
  transition context once. One still-asserted hallway may therefore authorize
  different fresh room episodes without pretending that the hallway emitted
  repeated movement observations.
- **REQ-EVID-008:** One fresh unsupported positive may create at most one bounded
  pending acquisition candidate. Waiting, timer evaluation, repeated callbacks,
  and the unchanged assertion do not add evidence. A later distinct adjacent
  episode may atomically use the candidate as provisional traversal context and
  authorize only the new leading target; independent same-zone, boundary,
  missed-edge, or mature prediction context may immediately promote the pending
  target itself. Count and reliability are context, not independent corroborating
  observations. A deadline only rejects; it never turns a lone episode on.
- **REQ-EVID-009:** Current or unexpired transition context is direction-neutral
  unless the map explicitly declares a directional boundary. A hallway episode
  that remains asserted may authorize distinct departures, returns, and
  neighboring targets, including `hall -> room A -> hall -> room B`, without
  requiring the hallway hardware to clear between crossings.
- **REQ-EVID-010:** Repeated positive callbacks from one physical node can never
  corroborate that node or bootstrap a track, even across multiple episodes.
  Clear/reassert cycles faster than the declared hardware can reliably re-arm are
  one correlated episode, add no likelihood or traversal authority, and emit a
  sensor-health cadence warning. Later support from a distinct adjacent physical
  node remains valid and is not delayed by the warning.

## 6. Per-Zone Belief Model

Each zone has a binary latent state $O_z\in\{0,1\}$ and a filtered belief

$$
q_z(t)=P(O_z(t)=1\mid E_{\le t},G,N),
$$

where $E$ is accepted episode evidence, $G$ is the configured graph, and $N$ is
the authoritative occupant count. This is a control-oriented probability that
the zone should be treated as occupied; it is not a claim about person identity.

Implementations may use a two-state hidden Markov filter, equivalent log-odds
filter, or another reviewed formulation that preserves the following semantics:

1. fresh local positive evidence raises $q_z$ strongly;
2. stable clear applies weak absence evidence and begins role-specific decay;
3. a stay-zone assertion has longer occupancy persistence than a transition
   assertion;
4. a later fresh adjacent episode may raise arrival belief in its target and
   accelerate decay in a cleared plausible source;
5. absence of a plausible outward episode preserves a stay zone more strongly
   than a transition zone;
6. independent simultaneous fronts remain possible up to the supported count;
7. reliability tempers the strength of a local observation without changing its
   episode identity; and
8. every continuous-time transition approaches a finite baseline.

Graph authorization supplies a distinct arrival-state transition after the
reliability-tempered local observation. For a trustworthy fresh physical target
episode authorized by same-zone independent evidence, adjacency, adjacent-pair
bootstrap, boundary evidence, or the bounded missed-edge rule, the current
shared calibration is

$$
q_z \leftarrow 0.75(1-q_z)+0.80q_z=0.75+0.05q_z.
$$

Equivalently, the shared supported-arrival transition matrix uses
$P(O'_z=1\mid O_z=0)=0.75$ and $P(O'_z=1\mid O_z=1)=0.80$.

This is a conditional occupancy-state transition supported by the source and
target episode relationship, not a second copy of the target sensor likelihood.
It guarantees that every supported physical acquisition begins in `[0.75, 0.80]`,
above the shared 0.70 on threshold even when the target's configured reliability
is low, without letting one arrival make retention arbitrarily sticky. It is
never applied to a lone pending episode, prediction, timer, repeat callback,
alias, or flap. The value is shared calibration and changes only with the
coupled replay and boundary review required by `REQ-POLICY-006`.

One acceptable continuous decay between observations is

$$
q_z(t+\Delta)=\pi_z + (q_z(t)-\pi_z)e^{-\Delta/\tau_z(c)},
$$

where $\pi_z$ is the profile baseline and $\tau_z(c)$ is selected from declared
context $c$. Context is a deterministic state machine; node role selects the
shared parameter family and is not itself a competing state:

1. an accepted positive selects `asserted` for its episode;
2. expiry of a transition or boundary assertion's trust horizon selects
   `degraded_asserted` while the same hardware assertion remains positive; stay
   assertions retain `asserted` locally while their traversal authority still
   expires;
3. stable clear selects `cleared_with_outward` when at least one compatible
  outward context for that source episode remains unexpired, otherwise
  `cleared_without_outward`;
4. a compatible adjacent target accepted while the source is clear selects
  `cleared_with_outward`; if accepted while the source remains asserted, it is
  retained and selects that context only if the same source episode later
  stable-clears before the outward context expires;
5. multiple compatible outward contexts compose by logical OR as one boolean
  context through the latest valid expiry and never require selecting one
  destination;
6. expiry of every compatible outward context reverts a still-cleared source to
  `cleared_without_outward`;
7. a new positive episode discards outward contexts associated with the prior
  source episode and selects `asserted`; and
8. unavailable selects `unavailable` until a later accepted state establishes a
  new episode or clear state. An accepted clear ends the unavailable context as
  a zero-delta transition to `cleared_without_outward`; only a stable clear
  contributes calibrated absence evidence.

`stay`, `transition`, `entry`, and `hybrid` profiles provide different baselines
and time constants for these states. In particular, transition profiles decay
faster than stay profiles. Constants are shared profile calibration, never
room-specific inactivity timers.

- **REQ-BELIEF-001:** Local evidence is never deleted by one unrelated remote
  event. Remote evidence may affect a zone only through a declared adjacent
  traversal relationship or the bounded count regularizer.
- **REQ-BELIEF-002:** A fresh target episode with compatible traversal context
  applies the shared arrival-state transition to the target after its
  reliability-tempered local likelihood. It does not require selecting a unique
  source occupant. Every physical acquisition authorization in Section 7 uses
  this transition; prediction never does.
- **REQ-BELIEF-003:** A cleared source followed by a fresh adjacent target episode
  applies a departure-conditioned decay profile to the source. An asserted or
  uncleared stay source receives weaker departure influence.
- **REQ-BELIEF-004:** A current transition assertion is primarily traversal
  context. It must not imply indefinite occupancy of the transition zone, even
  when hardware remains on during several crossings.
- **REQ-BELIEF-005:** A current stay assertion retains stronger local occupancy
  meaning. Its duration influence saturates at a finite profile value, and its
  traversal authority expires independently of that local meaning.
- **REQ-BELIEF-006:** Wall time advances declared state survival and decay. It
  does not synthesize sensor edges, graph traversal, independent evidence, or
  route-learning observations.
- **REQ-BELIEF-007:** All updates are numerically stable, normalized, finite, and
  deterministic. Probability values are clamped only for numerical protection,
  not to force policy outcomes.
- **REQ-BELIEF-008:** Acquisition authorization is separate from evidence
  acceptance. An unsupported local episode may raise belief while its pending
  candidate remains publicly inactive or is rejected. Prediction authorization
  may change `active` but never changes $q_z$.
- **REQ-BELIEF-009:** Node reliability $r$ tempers each configured local
  likelihood ratio in log space, so
  $\log LR_{effective}=r\log LR_{profile}$. The same tempered observation drives
  belief and health/conflict evaluation; code must not discard reliability
  between input normalization and zone-model evaluation.

## 7. Traversal Frontier, Acquisition, and Reacquisition

The model retains a bounded set of anonymous traversal tokens, not person
tracks. A token identifies a physical episode, zone, role, accepted event time,
and expiry. It says that a graph edge was recently observable; it does not claim
which occupant crossed it.

A fresh local target episode is immediately graph-authorized when any of these
holds:

1. the target has a current or recent compatible token from a different
  physical-node episode in the same zone; the target episode cannot authorize
  itself;
2. an adjacent node has a current valid transition assertion or unexpired token;
3. an entry node and count transition provide boundary reacquisition;
4. a reviewed missed-edge path of bounded graph length and time connects an
  unexpired frontier to the target.

Immediate authorization is evaluated synchronously in the same model update as
the target edge and never enters confirmation dwell. A separately created mature
high-confidence prediction authorization may also activate its graph-adjacent
target without a target-local episode under Section 12.

When no immediate authorization exists, a trustworthy local target episode may
create or replace the one pending track-bootstrap candidate for its zone.
Pending is an internal policy phase;
while the zone was inactive, its public `active` state remains `off`. A later
distinct episode on an adjacent node within the earlier candidate's
`track_bootstrap_window` establishes a new anonymous `provisional` graph-local
track. The model immediately authorizes the new leading episode and turns on its
zone when normal belief policy permits. The earlier candidate becomes bounded
provisional traversal context but its previously inactive zone is not
retroactively turned on solely because the pair completed. The model creates one
token per traversal-authorized episode in deterministic event-time order. Neither
episode needs continuity with a track that existed before the pair.

A provisional track has only one-hop forward authority. A third distinct
physical-node episode that is adjacent to the provisional leading edge and
arrives within graph timing is authorized immediately and promotes the frontier
to `confirmed`. Backtracking between the same two nodes, aliases, repeat
callbacks, and flaps do not satisfy the third-node requirement. Once confirmed,
fresh compatible adjacent episodes inherit confirmed provenance while the
frontier remains valid.

Compatible same-zone independent, boundary, bounded missed-edge, or mature
prediction support may also promote a pending candidate immediately. At its
deadline, an unsupported candidate expires as rejected regardless of count,
reliability, assertion duration, or belief. Its local evidence remains in zone
belief and may participate in health diagnosis, but it does not turn on an
inactive zone and creates no traversal token. Waiting and the deadline are not
independent corroboration.

Pending cardinality and replacement are deterministic. A zone retains at most
one candidate. A repeat, alias, or same physical-node episode is ignored. A
fresh trustworthy episode from a distinct physical node in the same zone
corroborates and authorizes that zone immediately; it does not by itself count
as an adjacent-node step for track confirmation. Otherwise a newer unsupported
episode replaces the older zone candidate after the older candidate has first
been considered as compatible support in event-time and node-ID order. A
candidate used as the first half of an adjacent pair is removed atomically.

- **REQ-TRAV-001:** Tokens expire by event time and shared graph/profile timing.
  Expired tokens cannot authorize activation or learning.
- **REQ-TRAV-002:** Tokens are anonymous and independently consumable by distinct
  target episodes. Each token carries `provisional` or `confirmed` track
  provenance and never becomes persistent occupant identity.
- **REQ-TRAV-003:** The sequence hallway to room A to still-open hallway to room B
  must permit both fresh room episodes. Room A begins faster decay only after its
  local evidence clears and the room B episode supplies plausible outward
  context.
- **REQ-TRAV-004:** A transition assertion that never clears has bounded
  neighboring authority. After its trust horizon it requires a new independent
  endpoint or corroborating node and emits a health warning.
- **REQ-TRAV-005:** Disconnected or graph-incompatible activity cannot authorize
  an immediate normal arrival. It may only join a later adjacent track-bootstrap
  pair or use a bounded missed-edge, boundary, same-zone independent, or mature
  prediction path.
- **REQ-TRAV-006:** Adjacent, same-zone independent, boundary, and bounded
  missed-edge authorizations are zero-wait paths. Their decision is made before
  any whole-house diagnostic materialization or pending-candidate work.
- **REQ-TRAV-007:** Pending track-bootstrap candidates are bounded by event time,
  profile, reliability, episode identity, and fixed retention. They neither
  consume nor manufacture traversal tokens until a compatible pair or another
  traversal authorization is accepted. An earlier candidate used to establish a
  provisional pair may create traversal context without retroactive activation.
  Source health degradation or unavailability removes the candidate before any
  later pair can consume it.
- **REQ-TRAV-008:** A mature prediction authorization is derived only from fresh
  accepted graph traversal and cannot make an untracked episode appear
  graph-authorized or teach the route model from its own outcome.
- **REQ-TRAV-009:** Two compatible pending episodes on distinct adjacent physical
  nodes establish a provisional track atomically; neither must first create a
  token for the other. Only the new leading target receives acquisition authority
  from the pair. One node, aliases of one node, repeat callbacks, and a
  clear/reassert flap inside one episode cannot bootstrap a track.
- **REQ-TRAV-010:** Provisional tracks may authorize their one next distinct
  adjacent leading episode with zero wait, thereby becoming confirmed, but they
  cannot count as strong tracked fronts, health-degrade other sensors, create
  predictions, or contribute route-learning observations. These restrictions do
  not delay local leading-edge activation.
- **REQ-TRAV-011:** Shared arrival calibration ensures that a trustworthy fresh
  leading target episode plus adjacent-token or adjacent-pair authorization
  satisfies normal on policy in that same update. Track-confidence bookkeeping
  cannot defer the public edge.
- **REQ-TRAV-012:** At most one pending candidate exists per zone. Same-zone
  independent corroboration may authorize the zone but cannot substitute for
  any of the three distinct sequential adjacent physical nodes required for
  confirmed provenance.

## 8. Authoritative Count

Count is context, not identity and not a requirement to solve an exact whole-home
assignment.

For conflict and sensor-health evaluation, a strong tracked front is a bounded
graph-connected group outside the target anchored by an authorized traversal
frontier with `confirmed` provenance. It contains at least three distinct
sequential physical-node episodes with adjacency between each pair, or a reviewed
boundary/missed-edge equivalent with the same evidential strength, plus current
or recent trustworthy stay evidence and belief at or above the profile's on
threshold. `active`, a lone pending episode, and a two-node provisional track are
not strong tracked fronts. Connected or overlapping fronts are coalesced so one
movement corridor is not counted as several occupants.

- **REQ-COUNT-001:** $N=0$ sets every $q_z$ to the empty baseline, clears every
  `active` output, invalidates traversal tokens and prediction leases, and emits
  one explained edge per changed public entity.
- **REQ-COUNT-002:** A change to positive $N$ must not invent a room, movement,
  activation, or person identity. Boundary evidence may shape reacquisition.
- **REQ-COUNT-003:** For $N>0$, count is a bounded soft regularizer over independent
  tracked fronts. It may reduce mutually incompatible weak beliefs and flag a
  disconnected pending candidate as count-conflicted when at least $N$ strong
  tracked fronts already exist. The candidate remains publicly off but retained
  until normal expiry so later graph support can still promote it. Count may not
  force exactly $N$ active zones and may contribute to release only through the
  persistent stuck-sensor conflict in `REQ-COUNT-009`.
- **REQ-COUNT-004:** Evidence for up to $N$ independent outside clusters may
  accelerate decay of a cleared origin. It is not injective proof of absence and
  is unnecessary when local filtered belief already satisfies release policy.
- **REQ-COUNT-005:** Same-zone multiplicity is always possible. Two occupants do
  not require two active zones, and one occupant may leave one of several recently
  active zones ambiguous.
- **REQ-COUNT-006:** Stale, duplicate, invalid, or unavailable count controls are
  ignored and diagnosed without changing the last valid count.
- **REQ-COUNT-007:** Count conflict never delays an adjacent-token,
  adjacent-pair bootstrap, same-zone independent, boundary, bounded missed-edge,
  or mature prediction authorization. Those paths explain movement or establish a
  graph-supported front rather than inventing an isolated additional front.
- **REQ-COUNT-008:** Strong-front construction is anonymous, deterministic,
  reliability-aware, and bounded by configured zones. It must not enumerate
  occupant assignments, infer identities, or use lingering `active` state as a
  substitute for current/recent evidence. A continuously connected front keeps a
  stable internal identity as confirmed token membership grows or is replaced;
  that topology-preserving evolution does not restart an existing conflict
  dwell. Loss, split, or merge that removes the required disjoint outside fronts
  still cancels the dwell.
- **REQ-COUNT-009:** When at least $N>0$ disjoint strong tracked fronts outside an
  asserted target persist continuously for that target profile's release dwell,
  and the target receives no new independent episode or compatible traversal
  context, the count contradiction health-degrades that target episode. Its
  assertion no longer floors belief, its traversal authority remains closed, and
  normal probability-driven decay and release proceed. Count does not switch the
  zone off directly. Stable clear followed by a fresh trustworthy positive, or a
  compatible new traversal episode, clears the conflict and restores normal
  evaluation immediately.
- **REQ-COUNT-010:** A stuck-off or missed intermediate sensor cannot permanently
  break acquisition elsewhere. An existing frontier may cross only the reviewed
  bounded missed-edge path, while any later pair of adjacent distinct episodes
  may bootstrap a new track without identity or continuity with the old frontier.

## 9. Automation Policy

`active` is one public projection of filtered zone belief plus bounded
acquisition authorization, not durable ownership. Pending remains publicly off;
predicted and evidence-acquired phases are publicly on. For shared thresholds
$0<\theta_{off}<\theta_{on}<1$:

$$
active_z(t^+) =
\begin{cases}
1 & q_z\ge\theta_{on}\ \text{and evidence acquisition is authorized},\\
1 & \text{a mature prediction authorization is current},\\
0 & q_z\le\theta_{off}\ \text{and release dwell is satisfied},\\
active_z(t^-) & \text{otherwise}.
\end{cases}
$$

An unconfirmed prediction-authorized phase is an exception to ordinary release
dwell: its short nonrenewing activation lease expires to `off` unless trustworthy
target evidence converts it to evidence-acquired `active`. This provenance is
internal and does not create another public control entity.

Thresholds represent an explicit cost and calibration policy. For false-off cost
$C_{FO}$ and false-on cost $C_{FP}$, the unconstrained release decision boundary
is $C_{FP}/(C_{FO}+C_{FP})$; hysteresis and dwell stabilize that decision rather
than replacing it with a separate proof system.

- **REQ-POLICY-001:** Evidence acquisition requires a fresh trustworthy local
  episode, or its still-valid pending candidate, plus one traversal or
  reacquisition authorization from Section 7. Prediction acquisition instead
  requires the mature authorization in Section 12. Existing `active`, waiting,
  and timer callbacks are not acquisition evidence.
- **REQ-POLICY-002:** Release occurs when filtered belief is at or below
  $\theta_{off}$ for the profile's release-confirmation dwell. It does not require
  globally finalized movement, support certificates, or accounting for every
  occupant elsewhere.
- **REQ-POLICY-003:** Current trustworthy stay evidence may floor $q_z$ or extend
  release confirmation according to profile calibration. While a stay sensor
  remains asserted, assertion age alone cannot release the zone. Stable clear,
  unavailable state, count zero, or the persistent tracked-front conflict in
  `REQ-COUNT-009` may remove that floor and begin release under the declared
  filter and dwell.
- **REQ-POLICY-004:** Transition zones use shorter occupancy persistence and
  release dwell than stay zones. Their assertions may remain useful as bounded
  traversal context after transition-zone occupancy belief has decayed.
- **REQ-POLICY-005:** A trustworthy fresh positive evaluated while the zone was
  already active emits at most one `refresh` event for its distinct physical-node
  episode ID. The episode that creates an `active` off-to-on edge does not also
  emit refresh. Duplicate callbacks, aliases, flaps in that episode, replay,
  timer advancement, clear, count control, restore, and prediction cannot emit a
  second refresh. Recently published refresh episode IDs remain deduplicated
  across restart until their bounded episode/audit retention expires. Consumers
  may use refresh to reassert an output that was manually turned off without
  requiring a false `active` edge.
- **REQ-POLICY-006:** Thresholds, dwell intervals, belief decay, likelihoods, and
  health horizons are coupled calibration. Changes require replay, adversarial
  tests, and shadow evidence rather than one-incident tuning.
- **REQ-POLICY-007:** Policy never mutates sensor episodes or retroactively changes
  $q_z$. It only projects the current model result.
- **REQ-POLICY-008:** One zone has at most one pending candidate and one public
  `active` value. Support directed at that pending zone promotes it immediately.
  When its episode instead serves as the first half of an adjacent pair, it
  becomes provisional traversal context without retroactive public activation.
  Expiry rejects it once; no path emits duplicate activation edges.
- **REQ-POLICY-009:** A pending candidate created while inactive remains publicly
  `off`. Its local evidence may participate in belief and later retention only
  after another authorization changes `active` to `on`.
- **REQ-POLICY-010:** Prediction-authorized `active` converts atomically to normal
  evidence-acquired `active` when compatible trustworthy target evidence arrives.
  Conversion emits no second `off -> on` edge or `refreshed` event, and prediction
  outcome is not learning evidence.
- **REQ-POLICY-011:** Ordinary evidence-acquired release semantics remain
  probability-driven. A count-backed stuck-sensor diagnosis changes sensor health
  and allows ordinary decay; it does not directly release the zone. Only an
  unconfirmed prediction lease has the shorter mandatory expiry described above.

Current shared policy calibration is:

| Profile           | On threshold | Off threshold | Release dwell |
| ----------------- | ------------ | ------------- | ------------- |
| `transition_fast` | 0.70         | 0.30          | 15 seconds    |
| `stay_pir`        | 0.70         | 0.30          | 60 seconds    |
| `stay_presence`   | 0.70         | 0.30          | 120 seconds   |
| `entry_boundary`  | 0.70         | 0.30          | 15 seconds    |

## 10. Sensor Profiles and Hardware Settings

The supported profiles and current asserted-state calibration are:

| Profile           | Hardware clear/reset recommendation                                                         | Asserted local baseline | Track-bootstrap window | Software interpretation                                                                                              |
| ----------------- | ------------------------------------------------------------------------------------------- | ----------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `transition_fast` | Use the shortest reliable device setting, initially 5-15 seconds where hardware supports it | 0.15                    | 45 seconds             | Short zone persistence; may be the first or second observation that bootstraps a new adjacent track                  |
| `stay_pir`        | Start near 30 seconds; increase only if measured false clears are excessive                 | 0.90                    | 90 seconds             | Strong local retention evidence; a lone unsupported episode remains publicly off and creates no traversal authority |
| `stay_presence`   | Use the device's shortest stable presence/absence reporting                                 | 0.95                    | 120 seconds            | Strong current presence evidence; acquisition still requires graph, pair, boundary, missed-edge, or prediction      |
| `entry_boundary`  | Use a short reliable reset consistent with the physical crossing                            | 0.10                    | 30 seconds             | Boundary reacquisition and count context, not long-lived room occupancy                                              |

The hardware recommendations are deployment starting points. The asserted local
baselines and track-bootstrap windows are normative current shared calibration.
Device settings must be recorded with the map profile because software timing
must reflect actual hardware behavior.

- **REQ-PROFILE-001:** Transition hardware should clear faster than stay-room
  hardware when reliable. This improves endpoint observability but correctness
  must not depend on the hallway producing a second edge before another room
  fires.
- **REQ-PROFILE-002:** A long asserted hallway supports the open traversal context
  described in `REQ-EVID-007`; it is not repeatedly counted and does not prevent
  another room from becoming a new leading edge.
- **REQ-PROFILE-003:** A stay room that fires and remains occupied retains belief
  through its longer local profile even after a fast transition sensor clears.
- **REQ-PROFILE-004:** Hardware changes are calibrated changes. Validate them with
  retained traces and shadow metrics before broad deployment.
- **REQ-PROFILE-005:** A stay-role node backed only by `motion` or `pir` uses
  `stay_pir`, even when the zone occupancy behavior is sticky. Sticky metadata
  cannot upgrade motion-only hardware to true presence.
- **REQ-PROFILE-006:** `stay_presence` requires true presence/mmWave capability
  or reviewed sticky non-motion hardware, including anchor sensors. No profile
  receives source-free turn-on authority merely because authoritative count is
  positive, local belief is high, or a timer expires.
- **REQ-PROFILE-007:** A profile's track-bootstrap window applies only when no fast
  authorization exists. Compatible graph, adjacent-pair bootstrap, or mature
  prediction authorization bypasses it completely, including when a candidate
  was already pending.
- **REQ-PROFILE-008:** Reliability tempers positive likelihood and sensor-health
  conflict evaluation. Reliability alone never authorizes an inactive zone.
- **REQ-PROFILE-009:** Track-bootstrap retention never delays or vetoes compatible
  same-zone independent, adjacency, boundary, missed-edge, or mature prediction
  authorization. Its expiry only removes the candidate's ability to pair later.

## 11. Public Contract

Ordinary Home Assistant automations consume model outputs and do not recreate
inference logic. Each zone has one control authority regardless of whether its
activation was authorized by observed evidence or a mature prediction.

- Per-zone `binary_sensor.<zone>_active`:
  - `off -> on` authorizes normal activation;
  - `on -> off` authorizes normal release.
- Optional `event.<zone>_arrival` emits event type `acquired` for the distinct
  episode that changes `active` from off to on and event type `refreshed` for the
  deduplicated episode defined by `REQ-POLICY-005` while `active` is already on.
  It carries zone, physical-node episode ID, accepted event time, belief,
  authorization reason, and policy reason. It is disabled by default.
- `home_active` is true when any zone is active and is an aggregate only.

- **REQ-PUBLIC-001:** Public edges are emitted once, in deterministic event-time
  order, with reason, belief, threshold, profile, evidence references, and
  evidence-acquired or prediction-authorized provenance.
- **REQ-PUBLIC-002:** Bootstrap and compatible restore do not emit synthetic
  activation, release, refresh, arrival, prediction, or learning events.
- **REQ-PUBLIC-003:** Normal control automations consume only `active`. They may
  optionally consume `event.<zone>_arrival` for effects or diagnostics, but must
  not inspect internal phase, thresholds, reasons, timers, or graph state to
  decide whether the zone should be on.
- **REQ-PUBLIC-004:** Exact-assignment, ownership, support-certificate, and other
  retired projections are not part of the public contract and must not be
  reintroduced as occupancy authority.
- **REQ-PUBLIC-005:** `pending` is internal and publicly `off`; `predicted` and
  evidence-acquired phases both project through the same `active` entity. There
  is no separate prelight, authorized-on, or active-off control entity.

## 12. Prediction and Learning

Prediction is optional policy authorization. It consumes learned accepted
traversal sequences and may activate the same public `active` entity early for
one graph-adjacent target. It is not occupancy evidence and never modifies
$q_z$, the traversal frontier, count, sensor health, or a learning observation.

A prediction is mature enough to authorize activation only when all of the
following hold:

1. it was created by a fresh accepted traversal episode on a confirmed track;
2. its target is directly graph-adjacent to the accepted source;
3. the target probability is at least 0.85 and has at least five accepted learned
   transitions in the current compatible model;
4. authoritative count is positive; and
5. no current target health condition or accepted contradictory target evidence
   blocks activation.

The current prediction activation lease is 10 seconds. It is short,
nonrenewing, and bound to its source episode. Lower-confidence predictions remain
diagnostic only. Compatible target evidence atomically converts the predicted
phase to evidence-acquired `active`; otherwise the lease expires to `off`
without ordinary release dwell.

Lease identity includes the confirmed source episode as well as the graph route,
so a newer traversal generation cannot overwrite another still-valid source
lease on the same route. Probability is the raw full-route probability: all
learned competing adjacent edges remain in its denominator even when a
backtracking candidate is ineligible for activation. A confirmed observed
departure from the prediction source cancels older outgoing leases and their
unconfirmed predicted public phases before the new route observation is learned.
Source health degradation or unavailability has the same cancellation effect.

The activation maturity threshold is fixed at 0.85 in the inference contract.
Legacy configurable prediction thresholds are ignored for activation during
migration and removed from the public configuration surface; probability and
support remain diagnostic. A future configurable value requires a new reviewed
specification change.

- **REQ-PRED-001:** Prediction may authorize the normal public `active` output
  only through the mature path above. It never changes belief, traversal
  evidence, count, health, or acquisition classification.
- **REQ-PRED-002:** A prediction lease expires, cancels on contradictory evidence,
  and never renews itself without a new accepted source traversal episode. One
  source episode may authorize at most one activation edge for a target. Distinct
  source episodes on the same route retain distinct leases.
- **REQ-PRED-003:** Learning is anonymous, shared, bounded, restart-safe, and
  accepts only confirmed-track transitions. It excludes provisional tracks,
  flaps, health-degraded or unavailable nodes, rejected untracked episodes,
  pending outcomes, predicted activations, and prediction confirmation or expiry.
- **REQ-PRED-004:** Removing prediction disables early predicted activation but
  does not change sensor-evidence belief, graph or track-bootstrap acquisition,
  release, count, or health semantics.
- **REQ-PRED-005:** A probability of 1.0 inferred from fewer than five accepted
  transitions is immature and cannot authorize activation. Model maturity is
  evaluated from the full retained route distribution before candidate filtering
  can make a sparse or non-backtracking target appear certain.
- **REQ-PRED-006:** Prediction evaluation and publication use the same zero-wait
  fast path as direct adjacency. Audit, persistence, and route-statistic updates
  cannot block that path.

## 13. Persistence and Restart

Persist only state needed to reproduce the next decision:

- map/profile fingerprint and authoritative count sequence;
- per-node episode identity, accepted state, timestamps, applied influence, and
  sensor-health state;
- per-zone filter state, last update time, public active state, acquisition phase
  and provenance, pending acquisition candidate, prediction confirmation
  deadline, and pending release dwell;
- unexpired traversal tokens with provisional/confirmed provenance and prediction
  leases;
- bounded route statistics, update sequence, and audit metadata.

- **REQ-STATE-001:** Restore validates schema, map fingerprint, count, timestamps,
  finite probabilities, episode identity, token expiry, and policy state atomically.
  Evidence-acquired active state remains bound to its acquisition episode, time,
  reason, bounded path, and source episodes. A prediction lease remains bound to
  the exact confirmed source token; its support must equal the retained target
  route count and its probability must equal the raw full-route probability from
  all retained competing counts and priors. The fingerprint covers every
  behavior-affecting map input plus sensor, belief, and policy calibrations.
- **REQ-STATE-002:** Invalid or incompatible state fails as a unit and bootstraps
  from current sensor/count snapshots without movement or public edges.
- **REQ-STATE-003:** Restore advances decay and expiry exactly once to the restore
  frontier. It must not reapply historical observation likelihoods.
- **REQ-STATE-004:** The one-time exact-assignment schema-6 importer may preserve
  public `active` state only as a compatibility seed. It must not invent zone
  belief, traversal tokens, or support provenance. Migration is deferred until
  current sensor state is available, and a current valid authoritative count
  overrides the stored legacy count.
- **REQ-STATE-005:** The current persisted inference schema is
  `zone-belief-v3`. A `zone-belief-v2` importer may retain compatible filter,
  episode, traversal, and active state only when retained provenance verifies
  that the active edge was not authorized by the legacy source-free path;
  otherwise it must discard the active state. It reconstructs neither pending nor
  prediction provenance. Older
  `zone-belief-v1` state is incompatible and must cold bootstrap from current
  sensor/count snapshots.
- **REQ-STATE-006:** A currently asserted stay sensor observed during cold
  bootstrap seeds belief but cannot by itself turn on an inactive zone. It may
  restore evidence-acquired `active` only from validated compatible persistence,
  or acquire after current same-zone, adjacent-pair bootstrap, boundary,
  missed-edge, or mature prediction authorization. Bootstrap emits no synthetic
  public edge.
- **REQ-STATE-007:** Restored pending and predicted phases remain bound to their
  original event-time deadlines. Restart cannot extend a track-bootstrap window,
  renew a prediction lease, or turn an expired phase on.
- **REQ-STATE-008:** Restart preserves provisional/confirmed track provenance
  without increasing confidence or converting restored same-node callbacks into
  new episodes. Unexpired historical tokens from an older valid generation may
  coexist with the node's exact current-generation token; only the latter may be
  marked physically current.
- **REQ-STATE-009:** Every validity window is half-open: evidence is usable for
  `created_at <= event_at < expires_at`. At one timestamp, stored timer
  frontiers with deadline less than or equal to that timestamp are advanced
  before the external input. Thus evidence exactly at a pending, token, trust,
  prediction, stable-clear, conflict, or release deadline cannot extend the old
  frontier. Uninterrupted execution and restore at that timestamp emit the same
  ordered result.

## 14. Explainability and Diagnostics

Every accepted or rejected policy evaluation records a compact bounded row with:

- event and processing time;
- zone, physical node, episode, role, and profile;
- pre/post $q_z$ and active state;
- local, adjacent, reacquisition, reliability, count-front, prediction, decay,
  dwell, and health contributions;
- acquisition/release threshold and authorization result;
- traversal token creation, provisional/confirmed promotion, use, and expiry;
- pending and prediction phase creation, deadline, promotion, rejection, and
  expiry; and
- deterministic reason code.

Diagnostics expose current episodes, beliefs, active states, traversal frontier,
count input, sensor-health warnings, prediction leases, latency, ignored events,
strong tracked fronts, pending candidates, reliability calibration, and
bounded audit retention. They do not need to serialize a whole-house exact
assignment graph.

- **REQ-DIAG-001:** An operator can explain every public edge from one zone-local
  audit row plus referenced neighboring episodes.
- **REQ-DIAG-002:** Audit retention has fixed time, entry, and byte bounds with
  constant-time FIFO eviction.
- **REQ-DIAG-003:** A zone active longer than its profile expectation without
  current trustworthy evidence is directly observable as a diagnostic condition.
- **REQ-DIAG-004:** Acquisition uses stable reason codes at minimum for
  `same_zone_authorized`, `adjacent_authorized`, `boundary_authorized`,
  `missed_edge_authorized`, `prediction_authorized`, `track_bootstrap_pending`,
  `provisional_track_acquired`, `track_confirmed`, `untracked_expired`,
  `correlated_flap_ignored`, `impossible_cadence`, `stuck_count_conflict`,
  `stuck_conflict_cleared`, and `prediction_unconfirmed`. A single local episode
  with only positive count is never labeled `source_free_corroborated`.
- **REQ-DIAG-005:** A count-conflict audit row identifies the conflicting strong
  tracked fronts and reliability result without claiming occupant identities.

## 15. Performance and Determinism

- **REQ-PERF-001:** An adjacent-token, adjacent-pair bootstrap, same-zone
  independent, boundary, bounded missed-edge, or mature prediction authorization
  produces its in-memory policy decision with p99 latency at or below 5 ms and
  hard latency below 10 ms on the 16-zone reference map at $N=2$. The integration
  schedules the corresponding
  `active` publication in the same Home Assistant event-loop update in which it
  receives the accepted evidence. No confirmation timer, blocking I/O,
  persistence, audit materialization, or learning update may precede that
  decision and schedule.
- **REQ-PERF-002:** Routine benchmark validation uses 100 events. Every benchmark
  entry point hard-rejects more than 1,000 requested events.
- **REQ-PERF-003:** Per-event work is bounded by configured nodes, local graph
  degree, active traversal tokens, and fixed audit limits; it must not enumerate
  whole-home occupant assignments.
- **REQ-PERF-004:** Same inputs produce byte-stable persisted model state and
  deterministic diagnostics apart from explicitly excluded runtime timing fields.
- **REQ-PERF-005:** Routine entity publication must use bounded current-state
  projections without materializing retained policy audit. Shared automation
  summaries are computed at most once per runtime update; full
  audit materialization is reserved for startup restoration, explicit
  diagnostics, persistence, and operator status requests.
- **REQ-PERF-006:** Unsupported candidates may remain pending for their profile's
  bounded track-bootstrap window. If fast authorization arrives while pending,
  promotion uses `REQ-PERF-001`; it does not wait for the deadline.
- **REQ-PERF-007:** The latency budget begins when the integration receives the
  accepted input event and ends when it schedules the entity state write. Sensor
  transport, Home Assistant's scheduler after that write, network delivery, and
  actuator switching are measured end-to-end diagnostics but are not claimed as
  model guarantees. The retained production-publication benchmark registers the
  complete binary-sensor entity set in production order and measures through the
  subscribers preceding the corresponding zone entity. Strict wall-time gates
  come from the standalone benchmark process, not coverage instrumentation.

## 16. Acceptance Requirements

The implementation is acceptable only when retained public-contract
scenarios and adversarial tests demonstrate:

1. an inactive target with fresh direct adjacency evidence activates in the same
   model update and meets `REQ-PERF-001`;
2. hallway to room A to still-open hallway to room B, including reversal, with
   both valid room activations and eventual room A release;
3. two occupants on independent paths and two occupants sharing one room without
   enforcing one active zone per occupant;
4. loss of every prior frontier followed by two sequential adjacent sensor
   episodes bootstrapping a provisional track, with the second leading zone
   activating immediately but the first inactive zone not back-activating;
5. an isolated closet detection while $N=2$ and two strong disconnected tracked
   fronts are current in Alex office and guest bedroom remains publicly `off`,
   eventually records `untracked_expired`, and produces no normal light
   activation;
6. isolated, disconnected, flapping, aliased, unavailable, and out-of-order
   sensor behavior, including degradation of stuck transition/boundary sensors
   and continued bounded local evidence from asserted stay sensors when no
   persistent count-backed tracked-front conflict exists;
7. an asserted stuck stay sensor is health-degraded only after $N$ disjoint strong
   tracked fronts persist elsewhere for the declared dwell, then releases through
   normal belief decay; clearing/resetting it restores normal evaluation;
8. a third distinct sequential adjacent physical node confirms a provisional
   track, while repeated traversal between only two nodes leaves it provisional;
9. isolated same-node or aliased flapping never creates a track or turns on an
   inactive zone, and physically impossible clear/reassert cadence remains one
   correlated episode with a health diagnostic;
10. no threshold chatter at exact boundaries;
11. restart during assertion, pending acquisition, provisional or confirmed
   traversal, predicted activation, stable clear, and release dwell without
   extending any lease;
12. count changes 0 to 2 without invented identity or room selection;
13. a mature graph-adjacent prediction activates the normal `active` entity in
   the same model update, converts without a second edge on target evidence, and
   expires within 10 seconds when unconfirmed;
14. sparse, provisional, untracked, self-confirming, and below-threshold
   predictions cannot activate or teach the model;
15. the fast paths meet `REQ-PERF-001` independently of diagnostics and retained
   audit size; and
16. all retained production incident regressions pass at the public contract.

## 17. Change Governance

- **REQ-GOV-001:** Amend this file and obtain explicit design agreement before a
  production change that conflicts with it.
- **REQ-GOV-002:** A reported behavioral failure first becomes the smallest exact
  public-contract regression using retained production timestamps and material
  state. The unchanged implementation must fail that regression for the stated
  reason before diagnosis proceeds.
- **REQ-GOV-003:** Model changes compare at least two alternatives across local
  calibration, two occupants, same-zone multiplicity, missed edges, stuck and
  flapping sensors, unavailable state, out-of-order delivery, restart,
  determinism, and performance.
- **REQ-GOV-004:** Fresh context-isolated reviewers independently investigate the
  failure, verify the proposal against this specification, and review the final
  implementation before broad validation.
- **REQ-GOV-005:** Public incident tests are immutable after reproduction except
  when independent evidence proves a factual input error. Tests may not be
  weakened, retimed, skipped, or moved to automation YAML to fit an
  implementation.

## 18. Superseded Architecture

This specification intentionally replaces exact anonymous count-vector
occupancy, mandatory fixed-lag global movement assignment, `ArrivalSupported`,
`ReleaseSafe`, support-certificate renewal, and durable ownership in the current
system. Those mechanisms have no authority over current behavior and must not be
restored. It also replaces separate prediction/prelight control entities and
automation-side authorization splits: prediction is internal provenance behind
the one `active` output. The schema-6 decoder permitted by `REQ-STATE-004` is a
bounded data importer only and cannot execute retired inference.
