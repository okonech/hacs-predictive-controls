# Predictive Controls Specification

**Status:** Normative
**Authority:** This file is the sole source of product and model requirements.
**Supported occupants:** 0 through 2, with 2 as the primary operating profile.

Code, tests, plans, changelogs, issues, and user documentation describe or
implement this specification but do not override it. If another repository file
conflicts with this file, this file wins and the other file must be corrected.

## 1. Mission

Predictive Controls converts imperfect, asynchronous sensor observations into
responsive, conservative, and explainable per-zone automation decisions. It is
optimized for lighting and similar environmental controls, not for reconstructing
exact person identities or proving a globally unique movement history.

The model must answer three separate questions:

1. **Zone belief:** How likely is each zone to benefit from remaining active?
2. **Traversal context:** Which fresh local observations are physically plausible
   given recent or current activity on the adjacency graph?
3. **Policy:** Does the filtered zone belief justify changing the public `active`
   state under asymmetric false-on and false-off costs?

Prediction is optional and downstream-only. It may prelight an adjacent zone, but
it must never change zone belief, traversal context, normal `active`, or learning
inputs.

## 2. Design Principles

- **REQ-GOAL-001, local control:** A zone decision should depend primarily on
  evidence in that zone and its graph neighborhood. Unrelated unresolved activity
  elsewhere must not make a local result unavailable.
- **REQ-GOAL-002, probability-driven policy:** The same declared zone belief must
  inform both activation and release. Historical ownership must not override a
  sufficiently low filtered belief indefinitely.
- **REQ-GOAL-003, asymmetric safety:** False offs in occupied stay zones cost more
  than delayed offs, while unsupported turn-ons remain undesirable. Policy must
  express that asymmetry through calibrated hysteresis and dwell rules.
- **REQ-GOAL-004, sensor realism:** Aliases, flaps, hardware hold time, stable
  clear, and prolonged assertions are correlated sensor behavior, not streams of
  independent evidence.
- **REQ-GOAL-005, graph plausibility:** Normal movement follows configured
  adjacency. Missed edges and source-free reacquisition remain possible without
  inventing a person identity or an exact route.
- **REQ-GOAL-006, multi-occupant tolerance:** Simultaneous activity fronts must be
  supported for authoritative counts 0, 1, and 2, including two occupants in one
  zone or on independent paths.
- **REQ-GOAL-007, bounded state:** Every influence, lease, hold, and diagnostic
  retention period is finite. No sensor episode or policy state may create
  permanent ownership.
- **REQ-GOAL-008, deterministic replay:** Equal ordered inputs, map, profiles,
  count controls, and restored state must produce equal outputs and explanations.
- **REQ-GOAL-009, generic behavior:** Production logic uses node roles, sensor
  profiles, reliability, adjacency, and shared calibration. It must not special
  case a room, entity, person, or incident.
- **REQ-GOAL-010, incident learning:** Every definitively diagnosed production
  incident becomes a retained public-contract regression with its observed event
  times and material state.

## 3. Non-Goals

- Persistent or inferred person identity.
- A globally unique anonymous movement assignment.
- Exact count-vector enumeration or injective proof that every occupant is
  supported outside a zone before that zone may release.
- Treating a light state, prediction, policy output, timer callback, or repeated
  unchanged sensor state as occupancy evidence.
- Guaranteeing a correct location when all relevant sensors miss an occupant.
- Hiding a failed or stuck sensor indefinitely through an infinite software hold.
- Room-specific thresholds or Home Assistant automations that reproduce model
  logic.

## 4. Inputs and Map Contract

The model consumes:

- ordered physical sensor state events with event timestamps;
- a map of zones, physical nodes, entity aliases, node roles, sensor profiles,
  adjacency, and graph timing;
- an authoritative occupant count in the supported range; and
- deterministic timer frontiers used only to advance declared decay, clear,
  health, lease, and policy dwell state.

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
  close their future traversal authority until recovery. They are not clear or
  absence evidence.

## 5. Physical Sensor Episodes

Raw alias edges are collapsed into one deterministic episode per physical node.
Every sensor profile declares independently:

1. `burst_correlation_window`: rapid clear/reassert edges that remain one flap
   episode;
2. `stable_clear_window`: how long clear must remain unchanged before the
   positive assertion is historical;
3. `hardware_hold_interval`: the period in which hardware may be unable to emit
   another positive edge;
4. `assertion_trust_horizon`: how long a continuous assertion retains full
   evidential weight before sensor-health degradation begins;
5. `post_clear_residual`: the role-specific occupancy residual after stable
   clear; and
6. `traversal_context_window`: how long the node may authorize a graph-neighbor
   arrival.

- **REQ-EVID-001:** A physical positive edge starts at most one episode and
  contributes one local likelihood update and one traversal token.
- **REQ-EVID-002:** Same-state callbacks, alias edges while the physical node is
  already asserted, timer reevaluation, and flap edges in one episode contribute
  no independent evidence and create no extra traversal tokens.
- **REQ-EVID-003:** A stable clear contributes one calibrated weak absence update.
  It starts residual decay but does not prove departure.
- **REQ-EVID-004:** A current assertion is a bounded correlated observation.
  Duration influence may saturate but may not grow without limit.
- **REQ-EVID-005:** When an assertion exceeds its trust horizon, its likelihood
  influence decays toward a finite profile floor and a sensor-health warning is
  emitted. A stuck node may retain some local protection but cannot keep `active`
  on forever or authorize unlimited neighboring arrivals.
- **REQ-EVID-006:** Out-of-order or duplicate inputs are ignored and diagnosed.
  They do not advance filter time, decay, traversal, policy, prediction, or
  learning.
- **REQ-EVID-007:** Each distinct target episode may consume a compatible open
  transition context once. One still-asserted hallway may therefore authorize
  different fresh room episodes without pretending that the hallway emitted
  repeated movement observations.

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
   and
7. every continuous-time transition approaches a finite baseline.

One acceptable continuous decay between observations is

$$
q_z(t+\Delta)=\pi_z + (q_z(t)-\pi_z)e^{-\Delta/\tau_z(c)},
$$

where $\pi_z$ is the profile baseline and $\tau_z(c)$ is selected from declared
context $c$. Context is a deterministic state machine; node role selects the
shared parameter family and is not itself a competing state:

1. an accepted positive selects `asserted` for its episode;
2. expiry of that assertion's trust horizon selects `degraded_asserted` while
  the same hardware assertion remains positive;
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
  new episode or clear state.

`stay`, `transition`, `entry`, and `hybrid` profiles provide different baselines
and time constants for these states. In particular, transition profiles decay
faster than stay profiles. Constants are shared profile calibration, never
room-specific inactivity timers.

- **REQ-BELIEF-001:** Local evidence is never deleted by one unrelated remote
  event. Remote evidence may affect a zone only through a declared adjacent
  traversal relationship or the bounded count regularizer.
- **REQ-BELIEF-002:** A fresh target episode with compatible adjacent traversal
  context applies an arrival transition to the target. It does not require
  selecting a unique source occupant.
- **REQ-BELIEF-003:** A cleared source followed by a fresh adjacent target episode
  applies a departure-conditioned decay profile to the source. An asserted or
  uncleared stay source receives weaker departure influence.
- **REQ-BELIEF-004:** A current transition assertion is primarily traversal
  context. It must not imply indefinite occupancy of the transition zone, even
  when hardware remains on during several crossings.
- **REQ-BELIEF-005:** A current stay assertion retains stronger local occupancy
  meaning, subject to bounded trust and health degradation.
- **REQ-BELIEF-006:** Wall time advances declared state survival and decay. It
  does not synthesize sensor edges, graph traversal, independent evidence, or
  route-learning observations.
- **REQ-BELIEF-007:** All updates are numerically stable, normalized, finite, and
  deterministic. Probability values are clamped only for numerical protection,
  not to force policy outcomes.

## 7. Traversal Frontier and Reacquisition

The model retains a bounded set of anonymous traversal tokens, not person
tracks. A token identifies a physical episode, zone, role, accepted event time,
and expiry. It says that a graph edge was recently observable; it does not claim
which occupant crossed it.

A fresh local target episode is graph-authorized when any of these holds:

1. the target has a current or recent compatible token from a different
  physical-node episode in the same zone; the target episode cannot authorize
  itself;
2. an adjacent node has a current valid transition assertion or unexpired token;
3. an entry node and count transition provide boundary reacquisition;
4. no compatible frontier exists, the authoritative count is positive, and the
   target passes the stricter source-free reacquisition gate; or
5. a reviewed missed-edge path of bounded graph length and time connects an
   unexpired frontier to the target.

Source-free reacquisition requires a trustworthy fresh local episode and either
independent physical-node corroboration or a profile whose measured false-positive
rate permits single-node reacquisition. It may raise target belief, but it must
be explained distinctly from an adjacent arrival.

- **REQ-TRAV-001:** Tokens expire by event time and shared graph/profile timing.
  Expired tokens cannot authorize activation or learning.
- **REQ-TRAV-002:** Tokens are anonymous and independently consumable by distinct
  target episodes. They never become persistent occupant identity.
- **REQ-TRAV-003:** The sequence hallway to room A to still-open hallway to room B
  must permit both fresh room episodes. Room A begins faster decay only after its
  local evidence clears and the room B episode supplies plausible outward
  context.
- **REQ-TRAV-004:** A transition assertion that never clears has bounded
  neighboring authority. After its trust horizon it requires a new independent
  endpoint or corroborating node and emits a health warning.
- **REQ-TRAV-005:** Disconnected or graph-incompatible activity cannot authorize
  a normal arrival. It may only use the stricter source-free or bounded missed-edge
  reacquisition path.

## 8. Authoritative Count

Count is context, not identity and not a requirement to solve an exact whole-home
assignment.

- **REQ-COUNT-001:** $N=0$ sets every $q_z$ to the empty baseline, clears every
  `active` output, invalidates traversal tokens and prediction leases, and emits
  one explained edge per changed public entity.
- **REQ-COUNT-002:** A change to positive $N$ must not invent a room, movement,
  activation, or person identity. Boundary evidence may shape reacquisition.
- **REQ-COUNT-003:** For $N>0$, count is a bounded soft regularizer over independent
  evidence clusters. It may reduce mutually incompatible weak beliefs but may not
  erase strong local evidence or force exactly $N$ active zones.
- **REQ-COUNT-004:** Evidence for up to $N$ independent outside clusters may
  accelerate decay of a cleared origin. It is not injective proof of absence and
  is unnecessary when local filtered belief already satisfies release policy.
- **REQ-COUNT-005:** Same-zone multiplicity is always possible. Two occupants do
  not require two active zones, and one occupant may leave one of several recently
  active zones ambiguous.
- **REQ-COUNT-006:** Stale, duplicate, invalid, or unavailable count controls are
  ignored and diagnosed without changing the last valid count.

## 9. Automation Policy

`active` is the hysteretic projection of filtered zone belief, not durable
ownership. For shared thresholds $0<\theta_{off}<\theta_{on}<1$:

$$
active_z(t^+) =
\begin{cases}
1 & q_z\ge\theta_{on}\ \text{and acquisition is authorized},\\
0 & q_z\le\theta_{off}\ \text{and release dwell is satisfied},\\
active_z(t^-) & \text{otherwise}.
\end{cases}
$$

Thresholds represent an explicit cost and calibration policy. For false-off cost
$C_{FO}$ and false-on cost $C_{FP}$, the unconstrained release decision boundary
is $C_{FP}/(C_{FO}+C_{FP})$; hysteresis and dwell stabilize that decision rather
than replacing it with a separate proof system.

- **REQ-POLICY-001:** Acquisition requires a fresh trustworthy local episode and
  one traversal or reacquisition authorization from Section 7. Existing `active`
  state is not acquisition evidence.
- **REQ-POLICY-002:** Release occurs when filtered belief is at or below
  $\theta_{off}$ for the profile's release-confirmation dwell. It does not require
  globally finalized movement, support certificates, or accounting for every
  occupant elsewhere.
- **REQ-POLICY-003:** Current trustworthy stay evidence may floor $q_z$ or extend
  release confirmation according to profile calibration, but bounded sensor-health
  degradation guarantees eventual release when no fresh supporting evidence
  appears.
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

## 10. Sensor Profiles and Hardware Settings

The initial supported profiles are role-based:

| Profile | Hardware clear/reset recommendation | Software interpretation |
| --- | --- | --- |
| `transition_fast` | Use the shortest reliable device setting, initially 5-15 seconds where hardware supports it | Short zone persistence; assertion is bounded traversal context; rapid stable clear reveals path endpoints sooner |
| `stay_pir` | Start near 30 seconds; increase only if measured false clears are excessive | Strong fresh local evidence, weak clear evidence, long no-exit residual |
| `stay_presence` | Use the device's shortest stable presence/absence reporting | Strong current stay evidence with a finite assertion trust horizon |
| `entry_boundary` | Use a short reliable reset consistent with the physical crossing | Boundary reacquisition and count context, not long-lived room occupancy |

These are deployment starting points, not normative constants. Device settings
must be recorded with the map profile because software timing must reflect actual
hardware behavior.

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

## 11. Public Contract

Ordinary Home Assistant automations consume model outputs and do not recreate
inference logic.

- Per-zone `binary_sensor.<zone>_active`:
  - `off -> on` authorizes normal activation;
  - `on -> off` authorizes normal release.
- Optional per-zone `binary_sensor.<zone>_prelight` authorizes low-impact
  prediction only.
- Optional `event.<zone>_arrival` emits event type `acquired` for the distinct
  episode that changes `active` from off to on and event type `refreshed` for the
  deduplicated episode defined by `REQ-POLICY-005` while `active` is already on.
  It carries zone, physical-node episode ID, accepted event time, belief,
  authorization reason, and policy reason. It is disabled by default.
- `home_active` is true when any zone is active and is an aggregate only.

- **REQ-PUBLIC-001:** Public edges are emitted once, in deterministic event-time
  order, with reason, belief, threshold, profile, and evidence references.
- **REQ-PUBLIC-002:** Bootstrap and compatible restore do not emit synthetic
  activation, release, refresh, arrival, prediction, or learning events.
- **REQ-PUBLIC-003:** Automations may consume `active`, optional `prelight`, and
  optional `event.<zone>_arrival` acquired/refreshed events; they must not inspect
  internal thresholds or duplicate graph logic.
- **REQ-PUBLIC-004:** Legacy projections may exist only during a declared
  compatibility phase in the migration plan. They are not part of the target
  contract.

## 12. Prediction and Learning

Prediction is optional. It consumes accepted traversal sequences after they are
observed and may create a finite lease only for graph-adjacent candidates.

- **REQ-PRED-001:** Prediction and learning never feed zone belief, traversal
  authorization, normal `active`, count, or sensor health.
- **REQ-PRED-002:** A prediction lease expires, cancels on contradictory evidence,
  and never renews itself without new accepted traversal evidence.
- **REQ-PRED-003:** Learning is anonymous, shared, bounded, restart-safe, and
  excludes flaps, unavailable nodes, source-free reacquisition, and prediction
  outcomes.
- **REQ-PRED-004:** Prediction may be removed from the product without changing
  occupancy or normal automation semantics.

## 13. Persistence and Restart

Persist only state needed to reproduce the next decision:

- map/profile fingerprint and authoritative count sequence;
- per-node episode identity, accepted state, timestamps, applied influence, and
  sensor-health state;
- per-zone filter state, last update time, active hysteresis state, and pending
  release dwell;
- unexpired traversal tokens and prediction leases;
- bounded route statistics, update sequence, and audit metadata.

- **REQ-STATE-001:** Restore validates schema, map fingerprint, count, timestamps,
  finite probabilities, episode identity, token expiry, and policy state atomically.
- **REQ-STATE-002:** Invalid or incompatible state fails as a unit and bootstraps
  from current sensor/count snapshots without movement or public edges.
- **REQ-STATE-003:** Restore advances decay and expiry exactly once to the restore
  frontier. It must not reapply historical observation likelihoods.
- **REQ-STATE-004:** Migration from the exact-assignment schema preserves public
  `active` state only as a temporary compatibility seed with a finite expiry. It
  must not invent zone belief, traversal tokens, or support provenance.

## 14. Explainability and Diagnostics

Every accepted or rejected policy evaluation records a compact bounded row with:

- event and processing time;
- zone, physical node, episode, role, and profile;
- pre/post $q_z$ and active state;
- local, adjacent, reacquisition, count, decay, dwell, and health contributions;
- acquisition/release threshold and authorization result;
- traversal token creation, use, and expiry; and
- deterministic reason code.

Diagnostics expose current episodes, beliefs, active states, traversal frontier,
count input, sensor-health warnings, prediction leases, latency, ignored events,
and bounded audit retention. They do not need to serialize a whole-house exact
assignment graph.

- **REQ-DIAG-001:** An operator can explain every public edge from one zone-local
  audit row plus referenced neighboring episodes.
- **REQ-DIAG-002:** Audit retention has fixed time, entry, and byte bounds with
  constant-time FIFO eviction.
- **REQ-DIAG-003:** A zone active longer than its profile expectation without
  fresh trustworthy evidence is directly observable as a diagnostic condition.

## 15. Performance and Determinism

- **REQ-PERF-001:** A valid raw detection produces its in-memory policy decision
  within 50 ms preferred and 100 ms maximum on the 16-zone reference map at
  $N=2$.
- **REQ-PERF-002:** Routine benchmark validation uses 100 events. Every benchmark
  entry point hard-rejects more than 1,000 requested events.
- **REQ-PERF-003:** Per-event work is bounded by configured nodes, local graph
  degree, active traversal tokens, and fixed audit limits; it must not enumerate
  whole-home occupant assignments.
- **REQ-PERF-004:** Same inputs produce byte-stable persisted model state and
  deterministic diagnostics apart from explicitly excluded runtime timing fields.

## 16. Acceptance Requirements

The target implementation is acceptable only when retained public-contract
scenarios and adversarial tests demonstrate:

1. direct room entry and quiet stay without false release;
2. hallway to room A to still-open hallway to room B, with both valid room
   activations and eventual room A release;
3. two occupants on independent paths and two occupants sharing one room;
4. a missed transition edge followed by trustworthy source-free reacquisition;
5. isolated, disconnected, flapping, aliased, stuck-on, unavailable, and
   out-of-order sensor behavior;
6. probability-driven release without globally available assignment provenance;
7. no threshold chatter at exact boundaries;
8. restart during assertion, stable clear, traversal, and release dwell;
9. count changes 0 to 2 without invented identity or room selection;
10. optional prediction remaining behaviorally isolated; and
11. all retained production incident regressions passing at the public contract.

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
- **REQ-GOV-006:** Every implementation phase ends with focused tests, the full
  Python suite and branch coverage, Ruff, mypy, frontend tests, the 100-event
  benchmark, and repository diff/reference checks. A failing gate blocks the
  next phase.

## 18. Conflict Rule

This specification intentionally replaces exact anonymous count-vector
occupancy, mandatory fixed-lag global movement assignment, `ArrivalSupported`,
`ReleaseSafe`, support-certificate renewal, and durable ownership as target
requirements. Those mechanisms may remain temporarily as migration
implementation details, but they have no authority over the target behavior.

The migration plan may sequence work and define temporary compatibility. It may
not add, remove, or reinterpret a requirement in this file.