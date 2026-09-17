# Predictive Controls Specification

**Status:** Normative
**Authority:** This file is the sole source of product and model requirements.
**Supported occupants:** 0 through 2, with 2 as the primary operating profile.
**Implementation status:** Repository version `0.2.6` implements the approved
selected-path, presence-gated departure, diagnostic-health, durable-learning and
strict modular panel contracts, including bounded overlapping selected branches.
**Current local validation passes (2026-09-17):**3351 Python tests,100% statement
and branch coverage; distinct83 incident,111 scenario and308 frontend cases pass.
Ruff, mypy, strict types, shipped build/freshness, independent review and standalone
100-event performance gates pass with unchanged100% coverage and5ms p99 limits.
[Section 19.0](#current-local-conformance) distinguishes current results from
historical green. No deployment, live restart or physical actuation is claimed.

### Approved selected-path cutover contract — 2026-09-12

The user approved implementing event-driven selected anonymous paths and the
following diagnostic thresholds. This amendment takes precedence over conflicting
age-bound traversal/endpoint-only and warning-coupled component clauses below.
These are current requirements; [Section 19.0](#current-local-conformance) records
their local validation. Frozen incident assertions remain retained.

- **REQ-PATH-001:** Maintain one deterministic compatible multiset of exactly N
  anonymous slots, U when unlocated, with same-zone overlap and no person identity.
  One physical positive advances at most one slot. Count0 clears all selection;
  count increase adds U; reduction removes U then weakest/oldest spatial evidence.
- **REQ-PATH-002:** Keep at most4 observed visits and4 connected route occurrences
  per track. The current-ON subset need not be connected. A->B->C survives B clear;
  clearing prior B removes B-only branch authority, not route history or endpointC.
  Endpoint OFF/time alone never evicts occupancy. New selected movement may replace
  old coverage; rejected branches and U do not retain every possible room.
- **REQ-PATH-003:** An ordinary live observed current generation may pair with a
  distinct adjacent ordinary/correlated target without token-age expiry. Bootstrap
  ON, aliases, duplicate events, timers and correlated origins do not seed a path.
  Persist consumed origin state; retired ON cannot become a new source. Provisional
  endpoints retain continuation authority independent of3/5minute timers. Optional
  device timing is context, not required authority or occupancy expiry.
- **REQ-PATH-004:** Selected coverage retains only already evidence-active zones;
  it never retroactively acquires a source. Displaced generations use outward
  decay/full dwell without fabricated OFF, likelihood or sensor-fault evidence,
  subject to the presence gate below. Raw held assertions cannot resurrect retired
  branches. Predictions remain
  downstream, create no selected path, and do not learn selected-only transitions.
- **REQ-PATH-005, user-approved presence gate (2026-09-12):** Loss of selected
  branch authority (subject to PATH007/008's supported-overlap exception) cannot
  start departure-induced local
  confidence decay while genuine noninteraction presence remains asserted in that
  zone. Physical `stay_presence` witnesses (not PIR/interaction/bootstrap-only
  levels) protect through their existing stable-clear confirmation. Departure decay
  and full release dwell begin only after protection ends; protected time never
  counts toward release. Unknown/unavailable withdraws that witness without fake
  OFF; another valid same-zone witness can still protect. Count0 remains immediate.
  Fresh real presence may restore local protection, not selected path authority or
  acquisition of an inactive output. The filter derives physical context without
  policy/output feedback; policy uses it only to retain evidence-acquired activity.
  This supersedes conflicting displaced-assertion decay/context/hold clauses in
  belief and policy requirements. Normal asserted calibration is not frozen.
  Persist one strict `physical_hold` Boolean per zone, validated against real live
  episode provenance and aggregate alias state. No extra tracks or timers. Current
  semantic fingerprint adds `presence_gated_departure_version:1`; old fingerprints
  reject, isolated historical readers remain separate. Local validation is recorded
  in [Section 19.0](#current-local-conformance), separately from deployment.
- **REQ-HEALTH-001:** Report a diagnostic warning after600 uninterrupted observed
  seconds ON without selected path support, starting at the later ON/support-loss
  frontier. Recover on OFF/support; unknown intervals cannot count as known ON.
- **REQ-HEALTH-002, user-approved recalibration (2026-09-16):** Warn at the tenth
  completed quick physical ON/OFF cycle in `(now-1200s,now]`, not at nine.
  Shared quick-cycle calibration remains ON<=60s;
  this is an implementation calibration, not a claimed device minimum. Count
  aggregate physical edges, not aliases/duplicates/timers; retain last10 qualifying
  completions. Recover when fewer than10 remain, expiring the left boundary before
  any same-time new input. No earlier low-count warning bypass. This supersedes
  the September12 six-cycle/hour calibration. The user approved updating synthetic
  threshold/expiry checks, not original incident inputs or lighting expectations.
  STATE011's fingerprint changes with calibration; old full inference rejects.
- **REQ-HEALTH-003:** These warnings do not evict selected occupancy, suppress
  accepted movement, or change hardware. Correlation suppression remains separate.
  This supersedes release-dwell/count-conflict health degradation in COUNT009 and
  age-only health warnings in EVID005/TRAV004 for the cutover engine.
- **REQ-PATH-STATE-001:** Selection, consumed live origins, timing frontiers and
  diagnostic health ledger restore strictly and atomically under a new fingerprint.
  Do not infer tracks from old supports or startup ON. Preserve historical readers,
  authoritative configuration, count0 and physical evidence independence.

### Approved unsupported-jump and release follow-up — 2026-09-13

This user-approved amendment supersedes ordinary missed-edge and TRAV021 gap
acquisition for the selected-path engine. Legacy component validators remain
qualification-only, not current engine authority. Connected selected movement,
held observed intermediate evidence, independent adjacent pairing, same-zone,
boundary and mature prediction behavior remain valid.

- **REQ-PATH-006:** Do not authorize an inactive target through an unobserved
  intermediate. After legitimate paths fail, fresh noninteraction target evidence
  two directed edges from an eligible selected endpoint/branch, but not directly
  adjacent or same-zone, records `unsupported_jump` rather than inferred movement.
  No source path/visit, target arrival, targetON, or prediction is manufactured.
  The ordinary target may later be the origin of an independent fresh adjacent
  pair; only the later leading zone acquires. Correlated targets cannot seed.
  Initial isolated origins without selected context, startup, duplicates, aliases,
  stale input, timers and count0 never create this occurrence. An actually
  confirming unexpired predicted policy suppresses this diagnostic; an unselected
  diagnostic lease does not. Missing connection is not proof of a sensor fault.
- **REQ-HEALTH-004:** Surface `unsupported_jump` as its own warning kind/reason,
  never flapping, suspected-stuck, or episode health degradation. Retain one latest
  occurrence per physical target/reason, active while aggregate knownON without
  selected coverage. OFF/noONunknown, bootstrap or accepted coverage clears it;
  count0 alone does not clear history. Event-only occurrences retain their observed
  timestamps across timers; clearing sets last/clear to the actual clear frontier.
  Use existing strict24h cleared-history projection; active warnings remain visible.
  Existing600s and quick-cycle diagnoses stay independent. Reliability/graph show
  all active kinds, the diagnostic sensor retains history, and Problem identifies
  unsupported spatial evidence separately from physical sensor health. No warning
  changes occupancy, acquisition eligibility, learning or hardware.
- **REQ-POLICY-014:** Evidence-active selected-displaced zones preserve their first
  eligible lower-threshold crossing before duplicate/invalid/unavailable callbacks,
  after selected-retention and physical-presence holds end. Full profile dwell is
  mandatory; ignored input cannot restart it. Coarse/fine/restored continuations
  agree at equal frontiers; stale input adds no advancement. No numeric timing
  constant or shared calibration change is introduced.
- **REQ-PERF-008:** Replace only the obsolete ordinary missed-edge acquisition
  sample with a separately named rejected-jump diagnostic workload. All requested
  samples must remain targetOFF, reject acquisition, produce the warning, and meet
  p99<=5ms/hard<10ms dispatch-to-completed-rejection timing. This workload's presence,
  sample completeness, correctness and latency gate top-level benchmark/CLI success.
  Valid acquisition paths retain original public-ON qualification and budgets.

New warning inference uses `unsupported_jump_diagnostics_version:1` in the semantic
fingerprint, retaining Store7/v4. Unknown/mismatched occurrence types, future times,
duplicates, active OFF/unknown or selected-covered warnings reject atomically.
Historical fingerprint recipes exclude this later key without changing archived
expected hashes. No proof is inferred from startup or old inference.

### Approved overlapping selected branches — 2026-09-16

**Implemented and locally validated:** the office-arrival scenario reproduced
the miss before the change and now passes; Section19.0 records complete green
validation and retained qualification boundaries. This amendment overrides immediate
suffix retirement only while bounded selected overlap remains supported.

- **REQ-PATH-007:** When movement continues from an earlier selected occurrence,
  preserve still-supported displaced positive/correlated occurrences as bounded
  overlap tips in the SAME anonymous slot. Keep last4 chronological visits and
  one connected main route of at most4 occurrences; at most3 `branch_routes`
  preserve actual observed prefixes (each at most4) to distinct active tips in
  those visits outside the main route. Prefix-only history confers no authority.
  No raw-ON union, extra slot, artificial edge, person identity or retroactive
  activation. An actual adjacent target detection remains required.
- **REQ-PATH-008:** Select against pre-input eligible sources before append/bound
  eviction. Preserve endpoint/resident/incoming priority and causal equal-time
  ordering; a saved tip continues via its witnessed prefix, never chronological
  visit adjacency. Stable clear, unavailable/current-generation mismatch, history
  eviction, slot replacement and count0 revoke saved authority irreversibly.
  Existing physical clear confirmation remains; only main endpoints retain OFF
  continuation. Capacity-trimmed main prefixes do not become tips. Revocation
  updates all copies; restoring/promoting a prefix never rearms retired ancestors.
  Correlated selected tips may continue but correlated unselected origins cannot
  seed. Saved interaction tips are excluded; existing main interaction rules stay.
- **REQ-PATH-STATE-002:** Require current `branch_routes`, exact consumed ledger,
  tip membership, canonical bounds, identical occurrence copies, legal directed
  geometry, unique recorded predecessor (multiple successors permitted), acyclic
  chronology including numeric same-node generations at equal times, and
  cross-slot ownership. A revoked endpoint cannot retain branch authority;
  prefix-only ancestors must be inactive in every copy. The exact current
  physical episode with `cadence_correlated=True` requires ledger origin
  `correlated` regardless of consumption. Do not require the converse: real
  count/startup/availability resets can clear that physical flag; historical
  generations do not inherit current physical provenance. Reject
  malformed state atomically before pruning; validate bounds before leaf decoding.
  Increment `selected_path_version` to2, retaining Store7/v4; old full inference
  rejects before decode, configuration and historical readers remain preserved.
- **REQ-DIAG-011:** Diagnostics expose `selected_path_version:2`. Coverage is
  main endpoint plus active main branches and saved tips. Movement separately
  applies endpoint eligibility; UI presence requires matching aggregate ON, not
  clearing. Display observed overlap prefixes separately within the same slot;
  prefix history never adds candidates. Current selection requires v2/valid
  branch and history fields; malformed/old selection is unavailable without
  hiding usable belief/policy data. Only absent selected_paths permits legacy
  fallback. Validate combined input/witness/generation chronology across all slots,
  including conflicting same-generation occurrences and decreasing times. Parse
  exposed canonical numeric generations with exact node prefixes and arbitrary
  integer precision; preserve the existing opaque-ID/suffix-independent client
  contract, without inventing a backend consumed ledger in the browser. Equal-time
  cross-node order follows observations, not lexical names. Projection must use
  the producer's actual map and reject impossible geometry. Semantic selection
  rejection must publish fresh independent belief/policy data; transport staleness
  remains distinct and recovery restores exact selected routes/edges.
  Deploy matching backend/bundle and reload browser; old cached JS may
  ignore new fields. Prediction uses only the actual continued main-route suffix,
  with existing independent grant, maturity, lease and no-selected-learning rules.

**Approved synthetic scenario disposition:** preserve all captured incident inputs
and public oracles. The user explicitly approved replacing conflicting synthetic
immediate-retirement assumptions, including neighbor rejection in
`test_runtime_presence_until_clear_then_release_without_branch_revival` and the
OFF95 expectations of `test_runtime_single_path_branch_releases_former_room` and
`test_runtime_hall_reassertion_does_not_delay_branch_release`, with measured overlap
behavior/full unchanged dwell. Preserve their original sensor timelines; give
truly revoked/evicted fixtures to corruption and lease/warning negatives. Preserve
the original guarantees with named replacements, never skip or weaken validation.
Final measured releases, preserved guarantees and retained qualification tests
are recorded in Section19.0; the completed working specifications are removed.

### Current engine and retained component scope (qualification boundaries)

PATH001–008, PATH-STATE001–002, HEALTH001–004, POLICY014, PRED008–009 and STATE013 govern the
selected-path engine wherever older component clauses differ. Selected slots are
not anonymous count supports; selected coverage is not a token lease; diagnostic
warnings are not physical episode faults. The detailed token, support, count-conflict,
cadence-warning and gap contracts remain genuine component/validator qualification
boundaries, including strict accepted specimens and their rejection inverses.
They are neither removed nor re-enabled as superseded live control gates.

The live engine still uses valid same-zone, boundary and independently authorized
token/support fallbacks after selection fails. Their finite authority remains
strictly bounded. That does not impose token TTLs on selected endpoints or ordinary
live origins, enable acquisition through an unobserved intermediate, or let count
conflict and warning state evict occupancy. REQ-TRAV-019/STATE012's abandoned
live-stay record plan is historical, not a missing current schema requirement.
Section 16 retains existing acceptance text with its already-approved scope and
amendments; this reconciliation creates no new oracle or authority.

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
4. **Retention:** Do current endpoint evidence and filtered zone belief justify
  keeping an already-active zone on under asymmetric false-on and false-off costs?

The model may retain internal `inactive`, `pending`, `predicted`, and `active`
policy phases, but ordinary automations consume only
`binary_sensor.<zone>_active`. Compatible adjacency and a mature high-confidence
prediction are zero-wait acquisition paths. Unsupported local evidence may enter
a bounded track-bootstrap phase that remains publicly `off` until a compatible
second observation establishes a graph-local track.

Track confidence is intentionally graduated. Two distinct sequential adjacent
physical nodes establish a `provisional` track, sufficient for immediate local
activation at its leading edge. A third distinct sequential adjacent node promotes
it to `confirmed`; selected confirmation permits mature prediction execution under
REQ-PRED-008, never selected-only learning or count-driven sensor degradation.

Prediction is policy authorization, not occupancy evidence. A mature
high-confidence graph-adjacent prediction may activate the same public `active`
entity early, but it must never change zone belief, create traversal context, or
learn from its own outcome.

Adjacency evidence is derived only from physical-sensor episodes and their bounded
selected or independently authorized traversal provenance. Public predictive
`active` entities and actuator states are outputs, never recursive evidence inputs.
A raw sensor's current `on` state is insufficient: an ordinary live origin must
match its observed generation and consumption ledger under REQ-PATH-003, not an
unproven startup level or the historical REQ-TRAV-019 record plan.

## 2. Design Principles

- **REQ-GOAL-001, local control:** A zone decision should depend primarily on
  evidence in that zone and its graph neighborhood. Unrelated weak or unresolved
  activity elsewhere must not make a local result unavailable. Selected movement
  may displace old coverage within N slots; disconnected evidence alone does not
  acquire. Diagnostic warnings neither degrade physical episodes nor veto valid
  selected movement. Presence protection and full release dwell remain independent.
- **REQ-GOAL-002, probability-driven policy:** The same declared zone belief must
  inform both activation and release. The selected-coverage retention exception
  in REQ-POLICY-013 prevents clear/time-only false release without changing belief;
  an eligible departure still releases through the lower threshold and dwell.
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
  Observed held intermediate evidence remains usable, but an unobserved two-edge
  jump is rejected under REQ-PATH-006, not filled with an inferred visit. A lone
  local positive edge is not by itself permission to turn on an inactive zone.
- **REQ-GOAL-006, multi-occupant tolerance:** Simultaneous activity fronts must be
  supported for authoritative counts 0, 1, and 2, including two occupants in one
  zone or on independent paths.
- **REQ-GOAL-007, bounded state:** Every probability, traversal influence,
  lease, hold record, and diagnostic retention is bounded. A settled-endpoint
  policy hold has bounded state, not a time-only expiry. Current asserted stay
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
- Proving a globally unique movement history. Selecting one deterministic
  compatible N-slot set is required, not a claim that no alternative occurred.
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
- mapped physical human-interaction event entities, such as local wall-switch
  scene presses, whose aware ISO state timestamp is the pulse occurrence
  frontier and which have no persistent asserted state;
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
  They are not clear or absence evidence. After live operation begins, either
  health state on any alias of an interaction-only node immediately invalidates
  that node's token, pending context, and count support without waiting for an
  all-alias health quorum. Before selecting zone context `unavailable`, the
  engine preserves an eligible same-zone episode that remains known-on,
  `asserted`, identity-valid, and free of health degradation. It may preserve
  the same multi-alias state episode when another alias remains on or a distinct
  physical-node episode. This zero-likelihood context correction creates no
  traversal, support, count, prediction, learning, activation, or refresh
  authority. If no eligible assertion remains, the zone selects `unavailable`.
  Startup neutralization creates no such authority.
- **REQ-MAP-005:** Every physical node declares a finite reliability in `(0, 1]`.
  Reliability must temper local likelihood and health/conflict evaluation; it
  may not be retained only for display or prediction smoothing. An interaction
  node using the conclusive finite-ceiling update in `REQ-BELIEF-010` must
  declare reliability exactly `1.0`; a source with uncertain reliability must
  use the ordinary reliability-tempered sensor contract instead.

## 5. Physical Sensor Episodes

Raw alias edges are collapsed into one deterministic episode per physical node.
Correlation, hardware hold, stable clear and likelihood calibration below remain
current. Legacy trust-horizon, impossible-cadence and sustained-cadence *warning*
effects are retained component contracts: the live engine disables those episode
diagnostics and uses HEALTH001–004 instead. Profile/token deadlines do not expire
selected occupancy or ordinary live-origin pairing. Actual unknown/unavailable
input still revokes the affected authority; diagnostics cannot fabricate it.

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
  later distinct adjacent episode before the candidate is rejected;
8. `cycle_correlation_window`: how long a completed stable-clear/reassert cycle
  remains linked to the same physical-node cadence run; and
9. `sustained_cadence_warning_window`: how long a linked run with at least one
  completed cycle may continue before a sustained-flapping warning starts.

- **REQ-EVID-001:** A physical positive edge starts at most one episode and
  contributes one local likelihood update. It creates at most one traversal
  token only when that episode receives traversal or acquisition authorization.
  A token does not by itself imply public activation; a rejected pending episode
  creates no token.
- **REQ-EVID-002:** Same-state callbacks, alias edges while the physical node is
  already asserted, timer reevaluation, and flap edges in one episode contribute
  no independent evidence and create no extra traversal tokens. A reliable
  correlated reassertion after the hardware hold interval may only reopen the
  adjacency usability of that episode's previously authorized token under
  `REQ-TRAV-013`; it does not add likelihood, change count, activate its own
  zone, or authorize without a later distinct target episode.
- **REQ-EVID-003:** A stable clear contributes one calibrated weak absence update.
  It starts residual decay but does not prove departure.
- **REQ-EVID-004:** A current assertion is a bounded correlated observation.
  Duration influence may saturate but may not grow without limit.
- **REQ-EVID-005:** When a transition or boundary assertion exceeds its trust
  horizon, its likelihood influence decays toward a finite profile floor and a
  sensor-health warning is emitted in the retained episode component contract.
  Current engine warning behavior is exclusively HEALTH001–004, without age-only
  episode degradation or a selected-path expiry. A stay assertion remains bounded
  local evidence for public retention while the device is currently asserted.
  In the legacy count-conflict qualification, `REQ-COUNT-009` may health-degrade
  its inference and traversal authority and remove its belief floor, but is not
  local absence and cannot start or continue public release dwell until stable
  clear or unknown/unavailable state. Elapsed wall time alone must not convert it
  into absence. No continuous assertion may authorize unlimited neighboring
  arrivals.
- **REQ-EVID-006:** Out-of-order or duplicate inputs are ignored and diagnosed.
  They do not advance filter time, decay, traversal, policy, prediction, or
  learning. Home Assistant `time_fired` is the occurrence frontier used for
  ordinary state entities. For a mapped Home Assistant EventEntity, a parseable
  timezone-aware ISO state value normalized to UTC is the physical interaction
  occurrence frontier; `state_changed.time_fired` bounds that value and callback
  receipt remains `processing_at`. A malformed, naive, or callback-future
  non-health value is ignored before model mutation. A parsed value before the
  model frontier is stale; equality remains subject to physical-node duplicate
  and idempotency rules. Live and replay normalization both preserve `unknown`
  and `unavailable` at their callback event time rather than dropping them.
- **REQ-EVID-007:** Each distinct target episode may consume a compatible open
  transition context once. One still-asserted hallway may therefore authorize
  different fresh room episodes without pretending that the hallway emitted
  repeated movement observations.
- **REQ-EVID-008:** One fresh unsupported positive may create at most one bounded
  pending acquisition candidate. Waiting, timer evaluation, repeated callbacks,
  and the unchanged assertion do not add evidence. A later distinct adjacent
  episode may atomically use the candidate as provisional traversal context and
  authorize only the new leading target; independent same-zone, boundary,
  mature prediction, or REQ-PATH-003 live-origin context may immediately
  authorize the target. Count and reliability are context, not independent
  corroborating observations. A deadline only rejects the candidate; it never
  turns a lone episode on or erases the separately consumable live provenance
  specified in REQ-PATH-003. Missed-edge acquisition is component-only under
  REQ-PATH-006.
- **REQ-EVID-009:** Current or unexpired transition context is direction-neutral
  unless the map explicitly declares a directional boundary. A hallway episode
  that remains asserted may authorize distinct departures, returns, and
  neighboring targets, including `hall -> room A -> hall -> room B`, without
  requiring the hallway hardware to clear between crossings.
- **REQ-EVID-010:** Repeated positive callbacks from one physical node can never
  corroborate that node or bootstrap a track, even across multiple episodes.
  Clear/reassert cycles faster than the declared hardware can reliably re-arm are
  one correlated episode and add no likelihood or traversal authority. Their
  immediate cadence warning is component-only; live warnings use HEALTH002.
  REQ-TRAV-020 may preserve only an already
  authorized original historical token; the flap supplies no new authority.
  For a profile without cross-generation cadence,
  stable clear closes that current warning at its exact frontier; a fresh
  independent episode that starts after the burst and hardware-hold windows but
  before stable clear closes it at the positive timestamp. Both retain bounded
  history. Later support from a distinct adjacent physical node remains valid
  and is not delayed by the warning. A correlated reassertion after hardware
  re-arm is not impossible cadence: it still adds no evidence, but may preserve
  bounded continuity of an already-authorized path under `REQ-TRAV-013`.
- **REQ-EVID-011:** A mapped local human-interaction event is a discrete physical
  pulse, never light, switch, fan, or other actuator output state. Each distinct
  live event-entity occurrence with a valid frontier under `REQ-EVID-006` starts
  one finite interaction episode directly in clearing, while malformed,
  duplicate, stale, or out-of-order occurrences add no evidence. Startup
  snapshots treat the retained event-entity timestamp as neutral and never
  replay it as a press. Interaction aliases occupy an interaction-only physical
  node so their pulse lifecycle cannot overwrite a motion or presence sensor
  episode. The episode then uses the shared stable-clear, outward-conditioned
  decay, fallback decay, threshold, and release-dwell lifecycle.
- **REQ-EVID-012:** A shared `stay_presence` profile links completed cycles across
  fresh episode generations using only aggregate physical-node `known_on`
  transitions. An alias callback that does not change that aggregate state,
  duplicate, stale input, interaction pulse, and nonzero count change cannot
  mutate cadence. The first positive after no open run is ordinary full evidence.
  After stable clear, a fresh aggregate positive strictly before the last
  transition plus `cycle_correlation_window` is a new generation but one
  `correlated_positive`; at the exact half-open deadline it is ordinary full
  evidence and starts a new run. Unknown/unavailable, authoritative count zero,
  and quiet expiry reset bounded cadence state without synthesizing evidence,
  traversal, support, policy, prediction, learning, or public edges. A sustained
  cadence warning requires at least one completed linked cycle and begins exactly
  at the run start plus `sustained_cadence_warning_window` only while the run is
  still open. One continuously asserted stay sensor is never flapping from age
  alone and retains the bounded local authority in `REQ-EVID-005`. The three-hour
  warning is a retained component qualification, not the current HEALTH002 trigger.
- **REQ-EVID-013:** An impossible-cadence warning still closes episode-level
  traversal validity in the retained component contract. The sole preservation
  exception is REQ-TRAV-020's original noncurrent token. Warning, aliases,
  repeats and timers add no source likelihood, activation, refresh, support,
  prediction or learning; warning clearance cannot resurrect deleted authority.

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

A fresh trustworthy human-interaction pulse is conclusive local evidence at the
model's finite numerical ceiling. It sets the zone log odds to
`LOG_ODDS_LIMIT`, never to literal probability one, and receives immediate local
acquisition authorization without requiring prior traversal. The pulse enters
the profile's normal stable-clear lifecycle immediately, retains one bounded
traversal token for outward-track evidence, and then uses the same profile decay,
threshold, and release dwell as other evidence. Compatible outward evidence
selects `cleared_with_outward` decay; absent outward evidence selects the slower
`cleared_without_outward` fallback. Belief still decays, but an interaction-created
settled endpoint protects evidence-active policy under REQ-POLICY-013 until
qualified departure/transfer or an explicitly scoped invalidation. Fallback decay
alone does not release that endpoint. Remote, voice, automation, or UI changes to a light or switch state
are not interaction evidence.

Graph authorization supplies a distinct arrival-state transition after the
reliability-tempered local observation. For a trustworthy fresh physical target
episode authorized by selected movement, same-zone independent evidence,
adjacency, adjacent-pair bootstrap or boundary evidence, the current
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
shared parameter family and is not itself a competing state. In the selected
engine, generation-bound `path_displaced_at` selects departure-conditioned decay
only after genuine `physical_hold` ends (PATH004/005). This effective decay context
does not fabricate OFF, an absence likelihood or a health fault. The following
ordinary episode/outward transitions remain applicable when not superseded by
that presence gate; trust-degradation transitions are component qualifications:

1. an accepted positive selects `asserted` for its episode;
2. expiry of a transition or boundary assertion's trust horizon selects
   `degraded_asserted` while the same hardware assertion remains positive; stay
   assertions retain `asserted` locally while their traversal authority still
   expires;
3. stable clear selects and commits `cleared_with_outward` when at least one
  compatible pending outward context for that source episode remains unexpired,
  otherwise `cleared_without_outward`;
4. a compatible adjacent target accepted while the source is already clear
  immediately commits `cleared_with_outward`; if accepted while the source
  remains asserted, it is pending and commits only if the same source episode
  later stable-clears before the pending context expires;
5. multiple compatible pending outward contexts compose by logical OR through
  the latest valid expiry and never require selecting one destination. On
  commitment, the filter consumes that pending authority into the boolean
  `cleared_with_outward` decay context with no remaining outward object or
  deadline;
6. pending outward authority that expires before stable clear is discarded
  without commitment. Committed `cleared_with_outward` decay does not revert at
  the former authority deadline; a confirmed return or new accepted positive
  supersedes it deterministically;
7. a new positive episode discards outward contexts associated with the prior
  source episode and selects `asserted`; an accepted correlated-continuity
  reassertion discards outward context for that same episode as a zero-likelihood
  context correction and adds no positive evidence; and
8. unavailable selects `unavailable` only when no eligible same-zone asserted
  episode remains under `REQ-MAP-004`. Otherwise the deterministic maximum
  `(last_event_at, node_id, episode_id)` selects `asserted` context with that
  identity and no likelihood contribution. An accepted clear ends unavailable
  context as a zero-delta transition to `cleared_without_outward`; only a stable
  clear contributes calibrated absence evidence.

`stay`, `transition`, `entry`, and `hybrid` profiles provide different baselines
and time constants for these states. In particular, transition profiles decay
faster than stay profiles. Constants are shared profile calibration, never
room-specific inactivity timers.

- **REQ-BELIEF-001:** Local evidence is never deleted by one unrelated remote
  event. Remote evidence may affect a zone only through a declared adjacent
  traversal relationship or the bounded count regularizer. Node-local health
  state likewise cannot delete a separate trustworthy same-zone assertion.
  Reselecting that already-accepted episode changes context only: it does not
  reapply likelihood, renew traversal, or create a public edge.
- **REQ-BELIEF-002:** A fresh target episode with compatible traversal context
  applies the shared arrival-state transition to the target after its
  reliability-tempered local likelihood. It does not require selecting a unique
  source occupant. Every physical acquisition authorization in Section 7 uses
  this transition; prediction never does.
- **REQ-BELIEF-003:** A cleared source followed by a fresh adjacent target episode
  applies a departure-conditioned decay profile to the source. An asserted or
  uncleared stay source receives weaker departure influence.
- **REQ-BELIEF-004:** A current transition assertion is primarily traversal
  context, not repeated movement evidence. Its local belief can decay while
  selected coverage independently retains an evidence-active output; clear or
  elapsed time alone cannot evict its selected endpoint.
- **REQ-BELIEF-005:** A current stay assertion retains stronger local occupancy
  meaning. Its duration influence saturates at a finite profile value. Ordinary
  token authority has finite expiry; selected endpoints/live origins use PATH003
  instead, and genuine presence protection uses PATH005.
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
- **REQ-BELIEF-010:** A trustworthy human-interaction pulse applies the finite
  numerical ceiling exactly once for its current episode generation. Generation
  identity, not bounded contribution or audit retention, makes the update
  idempotent across eviction and restore. The pulse does not also apply ordinary
  positive likelihood or the supported-arrival matrix. It does not stack with
  repeated callbacks, bypass categorical count zero, alter thresholds or dwell,
  or create a permanent occupancy floor. Ordinary clear and decay lower belief;
  public release additionally requires REQ-POLICY-013 eligibility when a settled
  endpoint remains.
- **REQ-BELIEF-011:** The ordinary first positive in a cadence run applies the
  configured positive likelihood under `REQ-BELIEF-009`. Each later
  `correlated_positive` applies the same configured reliability multiplied by
  $s=\ln(c_e/c_o)/\ln(p_o/p_e)$, derived from the shared stable-clear and positive
  likelihoods and validated in `(0, 1]`. Its preceding stable-clear update and
  this scaled positive have zero net sensor likelihood in log space within
  absolute tolerance `1e-12`; ordinary elapsed-time decay still advances. The
  effect retains unmodified physical reliability, creates a fresh generation,
  and records the actual scaled belief contribution. Static node reliability is
  not reduced to repair repeated completed cycles.

## 7. Traversal Frontier, Acquisition, and Reacquisition

### 7.1 Current selected authority

The engine maintains exactly N anonymous slots, including U, under PATH001–008.
One real positive selects at most one compatible continuation or ordinary-live
adjacent origin; source eligibility is evaluated on the deadline-reconciled
pre-input generation. Four observed visits and four connected route occurrences
bound each located slot, plus at most three witnessed prefixes of at most four
occurrences to active retained overlap tips outside the main route. These are
the same slot, not extra occupants; prefix-only ancestors have no authority.
Held earlier branches may continue a route; clearing an
intermediate withdraws its branch, not the observed connection or final endpoint.
Unknown/mismatched endpoints retain location but cannot authorize neighboring
movement until fresh eligible evidence. Raw levels and timers never rearm origins.
Selection authorizes only the new target and issues no legacy token or count
support; independently authorized ordinary fallback targets may be adopted without
inventing their token history. Correlated targets cannot independently admit a slot.

Ordinary missed-edge and REQ-TRAV-021 gap acquisition are disabled in the current
engine. Failure of legitimate paths may record `unsupported_jump`, never inferred
target acquisition; a later independent adjacent pair remains possible. Selected
provisional continuation and ordinary live-origin pairing do not depend on 3/5-minute
token ages. Finite token/pending fallbacks below remain bounded on their own terms.

### 7.2 Retained traversal component contracts

The following token/pending descriptions and REQ-TRAV clauses specify the genuine
traversal/support qualification boundary. Same-zone, adjacency, boundary, exact
endpoint and handoff fallbacks remain available where their actual predicates hold;
this is not a legacy engine mode. Token TTLs never govern selected retention or
live-origin pairing. Count-health gates, inferred missed-edge/gap acquisition and
the unimplemented REQ-TRAV-019 plan do not override Section 7.1. Strict codecs,
original mutation/lifetime inverses and historical provenance checks remain required.

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
  unexpired frontier to the target. Elapsed path time starts at token acceptance
  unless the current episode-state set contains an exact source-node and
  source-episode match in `clearing` or `clear`, with a clear event strictly
  later than token acceptance and no later than the target; that exact clear
  frontier is the bounded departure time. Missing, mismatched, asserted,
  degraded, unavailable, stale, or future source state preserves
  token-acceptance timing.

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

An authorized token whose ordinary traversal window expires may retain dormant
lineage only until its physical episode's original assertion trust horizon. A
reliable correlated reassertion of that same episode after the hardware hold
interval may reopen the same token for adjacency use. Reopening retains the
token ID, accepted time, path, confidence, and provenance; its new expiry is the
earlier of one traversal-context window after the reassertion and the original
assertion trust horizon. It is not a new positive, token, candidate, count
observation, or source-zone acquisition. Dormant lineage cannot authorize a
target until such a reassertion occurs.

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
  Their profile-bounded traversal context is finite and half-open under
  `REQ-STATE-009`, subject to any earlier assertion-trust bound. Expired tokens
  cannot directly authorize activation or learning. Dormant lineage retained
  solely for `REQ-TRAV-013` is not a usable token.
- **REQ-TRAV-002:** Tokens are anonymous and independently consumable by distinct
  target episodes. Each token carries `provisional` or `confirmed` track
  provenance, or explicit `local_interaction` provenance for a source-free local
  pulse, and never becomes persistent occupant identity. A `local_interaction`
  authorization issues exactly one bounded one-node token for the interaction's
  own node. Every accepted authorization exposes its complete accepted
  source-token set and issued target token to the count-only support layer
  without granting that layer authority to change traversal acceptance, except
  for the explicitly consumable settled-source selection in REQ-TRAV-018.
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
  any whole-house diagnostic materialization or pending-candidate work. The
  supported local policy edge is scheduled before unrelated support/count work;
  publication callback failure still commits the accepted model transition.
- **REQ-TRAV-007:** Pending track-bootstrap candidates are bounded by event time,
  profile, reliability, episode identity, and fixed retention. They neither
  consume nor manufacture traversal tokens until a compatible pair or another
  traversal authorization is accepted. An earlier candidate used to establish a
  provisional pair may create traversal context without retroactive activation.
  Source health degradation or unavailability removes the candidate before any
  later pair can consume it.
- **REQ-TRAV-008:** A mature prediction authorization is derived only from fresh
  accepted graph traversal and cannot make an untracked episode appear
  graph-authorized or teach the route model from its own outcome. Prediction
  authorization never creates or advances anonymous count support.
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
- **REQ-TRAV-013:** A correlated reassertion may reopen adjacency use of the same
  previously authorized episode token only when it occurs after the profile's
  hardware hold interval, before the episode's original assertion trust horizon,
  and without a cadence or health warning. It preserves rather than duplicates
  path provenance and may not extend validity beyond that original trust horizon.
  Repeated reassertions cannot extend authority indefinitely. An episode that
  never received authorization has no lineage to reopen and remains
  `correlated_flap_ignored`. The reopened token can authorize only a fresh
  distinct compatible target episode under the normal graph rules. The
  impossible-cadence preservation in REQ-TRAV-020 is not reopening, and a
  previously reopened token is ineligible for that exception.
- **REQ-TRAV-014:** A fresh-generation `correlated_positive` is target evidence
  and remains target-only by default. A dedicated path may authorize it from
  distinct trustworthy same-zone, adjacent, boundary, bounded missed-edge, or
  pending-pair physical context, consume an existing compatible pending source,
  and record bounded source-token uses. It may issue one ordinary finite target
  token and transfer/coalesce existing anonymous support only when its
  authorization reason is `adjacent_authorized`, `track_confirmed`, or
  `missed_edge_authorized` and at least one selected source token occurs before
  the target on the accepted path with an eligible support binding under
  `token.accepted_at >= support.updated_at`. The resulting token may authorize a
  later distinct physical episode under normal graph rules. Correlation alone
  may not remember the target as pending, apply outward source context, create
  support, or become a same-event prediction or learning source. If no eligible
  support-backed source exists, no target token is issued and the current
  target-only behavior is unchanged. The exact settled-endpoint rebind in
  `REQ-TRAV-016` and consumable handoff in `REQ-TRAV-018` are the only other
  support mutations. An isolated correlated
  target and positive count alone remain unauthorized. A current cadence warning
  blocks ordinary source authority except REQ-TRAV-020's original historical
  transition token, and does not block this bounded support continuation or
  independently authorized target confirmation; health degradation remains a
  block. Ordinary distinct graph evidence remains valid.

  **Current correlated-token lifecycle:** selected-consumption cleanup preserves
  existing active/retained token authority only when source-ledger origin and
  physical generation are correlated; physical/source/token node, episode and
  original occurrence agree; provenance is `adjacent` or
  `settled_adjacent_transfer`; and that exact episode is absent from every retained
  selected visit and route. Remove other tokens normally, then apply ordinary
  synchronization, expiry and availability rules. This is an exemption from that
  cleanup only, not broadly pruning-free authority or new acquisition eligibility.
  Never issue/reinsert a token, weaken support validation, adopt a selected slot or
  rearm an origin from this exception. Selected success destroys its legacy authority;
  later history eviction cannot reconstruct it. Same-event correlated selection
  seeding, learning, prediction-source issuance, outward evidence and refresh remain
  excluded; ordinary prediction cancellation still runs. Later distinct physical
  traversal may consume independently authorized surviving authority.
- **REQ-TRAV-015:** When a trustworthy non-interaction stay episode stably
  clears without a live source token, the engine may commit
  `cleared_with_outward` only from an independently confirmed three-node path
  that began at a different-zone directed neighbor while that source episode
  was asserted. The unexpired one-node pending source, two-node provisional
  predecessor, and three-node confirmed leader must have an exact persisted
  authorization-use chain; all acceptance times must be monotonic and no later
  than the physical source clear. The superseded REQ-TRAV-019 plan additionally
  proposed that a consumed source
  may prove departure through its exact current source episode, still-unexpired
  pair-target token, and later third-distinct-node confirmed token with the exact
  target-to-third authorization use. That alternative never fabricates a source
  token or renews any deadline. The current belief generation must be either
  that source episode or a same-zone local-interaction episode accepted during
  it, and another trustworthy asserted or clearing same-zone stay episode vetoes
  the classification. This stable-clear-only rule neither authorizes a target,
  extends token validity, reapplies likelihood, nor consults public active or
  belief magnitude. Expiry equality and incomplete, disconnected, repeated-node,
  stale, future, or out-of-order lineage fail closed.
- **REQ-TRAV-016:** One retained settled support may authorize a fresh
  trustworthy positive only at its exact node and zone. The authorization reason
  is `settled_endpoint_reacquired`; it applies the ordinary arrival transition
  once and atomically rebinds, rather than clones, the support. A normal positive
  may issue its ordinary bounded target token. A `correlated_positive` remains
  target-only and issues no token. The authorization creates no source-token use
  and is excluded from same-event prediction, route learning, support transfer,
  and coalescence. Absent, moving, unavailable, warned, different-node,
  different-zone, ambiguous, or count-zero support cannot grant this authority.
  Belief-only outward decay does not remove retained support under COUNT-011;
  an actual qualified departure moves its endpoint and removes exact-source
  reacquisition authority. When the retained support has the transferred two-node
  shape, ordinary exact endpoint reacquisition resets traversal to one fresh
  target node with provisional, non-equivalent `settled_endpoint` provenance.
  Support identity and count strength remain separate. It cannot recycle the
  expired pair into confirmed traversal; fresh B -> C remains provisional and
  B -> C -> D confirms.
- **REQ-TRAV-017:** An already-authorized different-zone target may register
  outward context on the current trustworthy same-zone belief generation when
  its source-token set contains the exact unexpired predecessor token recorded
  by `AuthorizationUse(token_id, generation_episode_id)`. That use must have
  reason `same_zone_authorized`, its authorization time must equal the
  generation start, and the token zone must equal the generation zone. Another
  trustworthy asserted or clearing non-interaction stay episode in that zone
  vetoes transfer. Mismatch, ambiguity, warning, unavailable state, future
  generation, expiry equality, duplicate use, or count zero fails closed. This
  read-only lineage proof neither authorizes the target nor extends, creates, or
  persists authority; it invokes the existing generation-bound outward context.

- **REQ-TRAV-018, consumable settled-adjacent handoff:** Only after all existing
  physical authority, exact-endpoint and compatible-pending paths fail, and
  before remembering a pending target, a fresh ordinary or fresh-generation
  correlated non-interaction positive may consume exactly one eligible directly
  adjacent settled support. Count must be positive. The target must match its
  new episode at the event frontier, be known-on, asserted, healthy, without
  cadence warning, and inside its ordinary half-open traversal validity.
  The unique source must be a non-interaction stay node in a different zone,
  with a deadline-free settled support exactly matching its current episode.
  It must be known-on, asserted, healthy and without cadence warning; source
  belief must be healthy `asserted`, have generation and asserted IDs equal to
  the support episode, no outward context, and probability at least that belief
  profile's on threshold. Creation, mutation and episode times cannot be future.
  There is no source entry-age, traversal-window or assertion-trust deadline:
  current healthy physical assertion plus exact supported belief supplies trust,
  never support alone, raw-on alone, public active, timer renewal or prediction.
  Zero or multiple eligible sources fail closed, without arbitrary selection.
  Reason/provenance is `settled_adjacent_transfer`; no source token or use is
  invented. A frozen operation-local selection binds support ID, source endpoint,
  episode and mutation frontier to target episode and time. One bounded target
  token has the direct source-target pair, provisional confidence and equivalent
  strength only for preserving existing support, never generic support creation.
  Validate the complete transfer before policy publication, then commit after
  synchronous callback return (including caught failure) and before count work.
  Move the same support ID/creation time, purge all its old bindings including
  dormant and equal-time bindings, and bind only the new token; normal receiving
  zone coalescence may subsequently reduce cardinality. Settle by ordinary target
  eligibility, otherwise use exactly the target token deadline. Reapplication
  is a no-op; stale selection cannot rebind or create support. Do not alter source
  local belief/outward context or enter same-event prediction/learning. A later
  independent physical event may continue only fresh bounded traversal.

- **REQ-TRAV-019, historical consumable live-stay plan (superseded by PATH003):**
  The following is the earlier component design, not a live acquisition path or
  a requirement to implement the abandoned record. After all existing
  acquisition paths, including compatible pending, REQ-TRAV-018 and REQ-TRAV-021,
  fail and before remembering a pending target, a fresh healthy reliable ordinary
  or correlated noninteraction target may pair with exactly one directly adjacent
  different-node, different-zone healthy known-on asserted noninteraction stay
  source. Count must be positive; resolve due source-local count health before
  selection. Source must hold available accepted live provenance under STATE-012.
  Source age, belief magnitude/generation, public active, token and support are
  not prerequisites. Bootstrap, aliases, flaps, health recovery and time alone
  supply no authority. Zero or multiple eligible sources fail closed.
  Freeze the actual current source episode, live origin, target episode and event
  time in an operation-local `LiveStayAdjacentPair`. Reason and provenance are
  `live_stay_adjacent_pair`, with actual source episode references and no
  fabricated source tokens or authorization uses. Issue exactly one ordinary
  target-lifetime token with direct pair, provisional confidence and false
  equivalent strength, including for an eligible correlated target. Apply the
  shared target arrival transition; never retroactively activate the source.
  This acquisition cannot create/rebind/transfer support, change source outward
  belief, prepare prediction or learn. Later real third-distinct graph evidence
  may confirm normal traversal; two-node backtracking cannot. Prevalidate the
  complete target and consumption before callback, commit source consumption
  after callback including caught failure and before count. Read-only callbacks
  remain legal; mutation reentry must reject before mutation. Preserve coalesced
  persistence scheduling when committed publication failure is re-raised, without
  claiming crash-durable exactly-once delivery before the Store write.

- **REQ-TRAV-020, bounded original-token preservation:** On impossible cadence,
  preserve only the exact already-authorized, non-reopened original transition
  token still present in the unexpired frontier, matching the source's current
  episode, node, profile, zone, accepted start and original calibrated expiry.
  The source must remain raw known-on, asserted and free of health degradation,
  with impossible_cadence warning and null episode traversal validity. Remove
  physically-current status; leave token ID, accepted time, deadline, confidence,
  path, provenance and existing uses unchanged. A later distinct compatible
  target may use this noncurrent historical token through normal graph rules.
  Count-support binding is not a prerequisite. The flap itself supplies no
  source evidence, token issuance/renewal, reopening, refresh or support mutation.
  Always remove warned pending candidates. Health/degraded/unavailable input,
  including a live health callback on one alias while another remains on, raw
  clear, generation mismatch, reopened/ineligible role, or original expiry
  invalidates preservation. Never synthesize from raw assertion, create from
  pending, resurrect removed state, or recover dormant lineage. Repeated flaps
  cannot renew authority; a warned clear removes the token before reassertion.
  Event, timer, count and restore advancement apply the same predicate and purge
  expired warned lineage and its uses. Strict restore accepts only the eligible
  noncurrent shape and atomically rejects warned current tokens, pending
  candidates and ineligible warned lineage. Ordinary healthy historical
  generations and all existing graph/support rules otherwise remain unchanged.

- **REQ-TRAV-021, retained supported-gap component qualification only:** After existing legitimate
  acquisition paths fail, a fresh healthy unwarned noninteraction ordinary or
  correlated target may receive target-only authorization from exactly one
  original, unexpired, non-reopened `settled_adjacent_transfer` transition token.
  Count must be positive. Source must match its current healthy unwarned known-on
  asserted episode and original calibrated token timing, provisional direct-pair
  provenance and equivalent flag. Its exact moving support binding must match
  endpoint, episode, path, provenance, acceptance/update time and token expiry.
  Source and target are different-zone nonadjacent nodes connected by exactly
  two directed edges through a noninteraction transition intermediate. The
  intermediate supplies geography only, never evidence or renewed authority.
  Each directed edge uses its configured duration or a shared 15-second fallback
  when absent; total budget is capped at 30 seconds. Require positive elapsed
  time strictly below that budget and original source expiry. Evaluate all
  compatible intermediate paths; ambiguity is over source tokens, not paths.
  This shared provisional calibration applies only to this dedicated rule.
  Handoff provenance cannot use ordinary missed-edge traversal to bypass these
  restrictions; other existing missed-edge behavior remains unchanged.
  Reason/provenance is `supported_gap_acquisition`, confidence provisional,
  path singleton target, equivalent strength false. Apply the shared arrival
  transition and ordinary public policy; retain the actual source token/episode
  and one bounded deduplicated use. Issue no target token or pending candidate,
  mutate no support from the acquisition, and apply no outward source context,
  prediction or learning. Distinct targets may use the fixed original window;
  aliases/repeats never renew it and a gap target cannot chain source authority.
  Ordinary episode deadline advancement resolves transition health before
  selection. Historical policy/audit/use validation preserves actual source
  references and original bounded timing/geography without requiring that source
  or support still be live. A later reopening cannot retroactively invalidate a
  valid earlier use. No gap-provenance traversal token or support is valid.

## 8. Authoritative Count

Count is context, not identity and not a requirement to solve an exact whole-home
assignment.

In the current engine, count sets the exact selected-slot capacity (PATH001), not
an exact number of active zones. COUNT001/002/005/006 and categorical empty-house
behavior remain current. The strong-front, support-coalescence and COUNT009
health-conflict descriptions below are retained count/support component contracts,
not live count-driven sensor degradation or replacements for selected coverage.
Genuine independently authorized fallback supports still obey their creation,
transfer, binding and restore validators; a selected slot is never inferred from
those supports. Same-zone selected paths may overlap without being coalesced away.

For conflict and sensor-health evaluation, a strong tracked front is a bounded
graph-connected group outside the target anchored by an authorized traversal
frontier with `confirmed` provenance. It contains at least three distinct
sequential physical-node episodes with adjacency between each pair, or a reviewed
boundary/missed-edge equivalent with the same evidential strength, plus current
or recent trustworthy stay evidence and belief at or above the profile's on
threshold. `active`, a lone pending episode, and a two-node provisional track are
not strong tracked fronts. Connected or overlapping fronts are coalesced so one
movement corridor is not counted as several occupants.

An anonymous occupancy support is bounded count-only provenance for one
graph-confirmed movement lineage. It has exactly one current moving or settled
endpoint and never becomes a person assignment. It is distinct from a traversal
token: apart from the exact-endpoint rebind in REQ-TRAV-016 and single consumable
departure in REQ-TRAV-018, support cannot authorize movement or acquisition.
It never authorizes prediction or route learning, and a credible settled endpoint
may remain after ordinary token expiry.

- **REQ-COUNT-001:** $N=0$ sets every $q_z$ to the empty baseline, clears every
  `active` output, invalidates traversal tokens and prediction leases, and emits
  one explained edge per changed public entity. A local interaction pulse cannot
  bypass this categorical empty-house state.
- **REQ-COUNT-002:** A change to positive $N$ must not invent a room, movement,
  activation, or person identity. Boundary evidence may shape reacquisition.
- **REQ-COUNT-003:** For $N>0$, current capacity changes add U or remove U then
  weakest/oldest spatial evidence, without inventing movement or forcing N active
  zones. In the retained component contract, count is a bounded soft regularizer over independent
  anonymous occupancy supports derived from confirmed traversal provenance. It
  may reduce mutually
  incompatible weak beliefs and flag a disconnected pending candidate as
  count-conflicted when at least $N$ independent count supports already exist.
  The candidate remains publicly off but retained until normal expiry so later
  graph support can still promote it. Count may not force exactly $N$ active zones
  and may diagnose inference/traversal health only through the persistent
  stuck-sensor conflict in `REQ-COUNT-009`. Positive count is not local absence
  and cannot make a currently asserted stay episode publicly release-eligible.
- **REQ-COUNT-004:** Evidence for up to $N$ independent outside clusters may
  accelerate decay of a cleared origin. It is not injective proof of absence and
  is unnecessary when local filtered belief already satisfies release policy.
- **REQ-COUNT-005:** Same-zone multiplicity is always possible. Two occupants do
  not require two active zones, and one occupant may leave one of several recently
  active zones ambiguous. Multiple supports settling in one zone, including
  interaction-derived support, coalesce rather than force another room active.
- **REQ-COUNT-006:** Stale, duplicate, invalid, or unavailable count controls are
  ignored and diagnosed without changing the last valid count.
- **REQ-COUNT-007:** Current count diagnostics never delay selected or independently
  authorized acquisition while $N>0$. The following source-health qualifications
  belong to retained components, not an engine count-fault gate. Count conflict never delays an adjacent-token,
  adjacent-pair bootstrap, same-zone independent, boundary, bounded missed-edge,
  local-interaction, or mature prediction authorization while $N>0$. Those paths
  also include REQ-TRAV-018's uniquely supported consumable adjacent handoff and
  REQ-TRAV-019's unique live-stay pair. A source whose count-conflict degradation
  deadline has already matured is not a healthy source for a new pair; source
  eligibility resolves due source-local health before selection. These paths
  explain movement or establish a graph-supported front rather than inventing an
  isolated additional front.
- **REQ-COUNT-008:** Support construction is anonymous, deterministic,
  reliability-aware, and bounded by `PRODUCT_MAX_OCCUPANTS`. A support begins
  only from confirmed three-node adjacent provenance or a reviewed
  boundary/missed-edge equivalent already accepted by traversal, or one fresh
  unit-reliability `local_interaction` token. Local interaction is
  confirmed-equivalent only for creating one count-only support; the support
  gains no belief, traversal, prediction, or learning authority. Its settled
  endpoint may protect already evidence-active policy under REQ-POLICY-013. Its ID
  is derived from the first confirmed-equivalent target token. Accepted
  source-token mappings may select the same support for transfer only when each
  selecting token's `accepted_at` is at or after that support's `updated_at`
  causal mutation frontier and the token's node occurs before the target on the
  accepted authorization path; exact timestamp equality remains eligible.
  Linked authorization lineage outside that selected path cannot transfer or
  merge support. A mapped source set coalesces only supports selected by eligible
  tokens under the least ID before transfer.
  Coalescence preserves the least support ID and the minimum `created_at`
  across all selected members, not the encoded winning origin's occurrence.
  Connected current
  confirmed-equivalent token components likewise exclude temporally stale
  bindings; distinct supports settled in one zone still coalesce by endpoint. A
  stale or off-path binding remains bounded lineage and cannot cause target
  rebinding, but may remap to an independently selected coalescence winner to
  preserve referential integrity. A split never clones support.
  A support-backed `correlated_positive` admitted by `REQ-TRAV-014` uses this
  same source selection and may transfer/coalesce only the selected existing
  support set; it can never enter support creation.
  Current front evidence is never counted alongside its derived support, and
  lingering `active` or high belief alone cannot create support.
  Topology-preserving transfer retains identity and conflict dwell;
  selected-support loss, split, or merge cancels dwell.
  REQ-TRAV-018 is a separate selection-backed transfer branch, not support
  creation or source-token authority. Its provisional equivalent token is
  excluded from generic creation and confirmed-component coalescence.
- **REQ-COUNT-009, retained count-conflict component only:** When at least $N>0$ independent count supports outside an
  asserted target persist continuously for that target profile's release dwell,
  and the target receives no new independent episode or compatible traversal
  context, the count contradiction health-degrades that target episode. A count
  support has one current endpoint. Its `path_node_ids` contains at most three
  configured nodes from its latest confirmed traversal and is used only to
  exclude a target on that lineage from the outside set; the path does not claim
  current occupancy at every listed node. The target assertion no longer floors
  belief, its traversal authority remains closed, and normal probability-driven
  decay proceeds. Count does not switch the zone off directly and the same
  count-degraded stay episode vetoes creation or continuation of public release
  dwell while it remains `degraded` or is `clearing` inside stable-clear
  confirmation. Stable clear or unknown/unavailable state removes that veto and
  ordinary filter plus full release dwell applies. Count zero remains
  an immediate categorical release. A raw clear/reassert flap inside stable-clear
  confirmation returns to the same degraded episode, reopens no traversal, and
  accumulates no release dwell. Stable clear followed by a fresh trustworthy
  positive, or a compatible new traversal episode, clears the conflict and
  restores normal evaluation immediately. If any selected outside support is
  removed, coalesced, transferred through the target, or otherwise ceases to
  qualify after degradation, the conflict also clears in the same evaluation
  that observes the invalidation. A still-asserted matching stay episode returns
  atomically to its normal asserted belief context without a synthetic positive
  observation, renewed traversal authority, or retroactive public edge. Ordinary
  policy then evaluates that restored belief in the same model update.
- **REQ-COUNT-010:** A stuck-off or missed intermediate sensor cannot permanently
  break acquisition elsewhere. Current unobserved jumps remain rejected under
  PATH006, while a later pair of adjacent distinct episodes may bootstrap a new
  track without identity or continuity with the old frontier. Bounded missed-edge
  acceptance remains an isolated traversal-component qualification only.
- **REQ-COUNT-011:** A support is `moving` until its current target token expires
  or `settled` at one trustworthy stay endpoint whose graph-local belief is at or
  above the on threshold when support is created. A settled support survives
  finite clear debounce, stable clear, and subsequent belief decay below the on
  threshold, including belief-only `cleared_with_outward` context. A later
  trustworthy positive at that same endpoint may rebind its episode without
  creating or cloning support. Unavailability, health/cadence warning, moving
  expiry, or $N=0$ removes it and cancels dependent conflict dwell. Neither belief
  magnitude nor outward belief context alone proves support departure. A current
  settled endpoint protects evidence-active policy under REQ-POLICY-013 without
  acquiring an inactive zone. Ordinary traversal-token expiry does not remove settled support.
  A compatible accepted authorization advances it only when the complete source
  set contains a current support binding whose token is temporally eligible and
  occurs before the target on the selected authorization path. A token accepted
  before the support's `updated_at` frontier cannot prove departure or select it
  for binding-derived coalescence; linked off-path lineage cannot prove departure
  either. Qualified departure transfers the same support during the target event,
  independently of source clear timing, rather than removing it before transfer.
  Freeze the deadline-advanced source basis before authorization-side token
  mutation; prepare the complete transfer before publication and commit after
  callback return, including caught failure, before count work. Same-event pruning
  cannot erase already selected authority; support invalid before the operation
  is never resurrected. Final moving endpoints and bindings must remain valid
  within token capacity. Remote activity without an eligible mapped source cannot
  move, duplicate or erase support. TRAV-014 correlated continuation uses this
  same predicate; TRAV-018 remains the separate consumable support departure
  exception without a source token. TRAV-019 pairing never mutates support from
  that acquisition. No deferred departure ledger or new support field is required.
  Creation, transfer, coalescence, removal and mapping rewrite are validated and
  committed atomically in event-time order; ambiguity never invents support.

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
0 & q_z\le\theta_{off}\ \text{and release is eligible and dwell is satisfied},\\
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
  reacquisition authorization from Section 7. A fresh trustworthy
  human-interaction pulse is the sole source-free local-authorization exception
  and explicitly acquires immediately when $N>0$ and its bounded belief is above
  the ordinary on threshold. Its release uses the ordinary profile threshold and
  dwell after the REQ-POLICY-013 eligibility gate. Prediction acquisition instead requires the mature authorization in
  Section 12. Existing `active`, waiting, light/output state, and timer callbacks
  are not acquisition evidence.
- **REQ-POLICY-002:** Release occurs when filtered belief is at or below
  $\theta_{off}$ for the profile's release-confirmation dwell and no current
  physical-presence hold under PATH005 or selected-coverage hold under
  `REQ-POLICY-013` applies. POLICY014 preserves eligible elapsed progress.
  It does not require globally
  finalized movement, support certificates, or accounting for every occupant
  elsewhere.
- **REQ-POLICY-003:** Current trustworthy stay evidence may floor $q_z$ or extend
  release confirmation according to profile calibration. While a stay sensor
  remains asserted, assertion age alone cannot release the zone. Selected
  displacement and genuine presence protection follow PATH004/005: motion/PIR or
  interaction is not a presence witness. Hold loss permits ordinary decay and
  full dwell, never reuse of protected time. The older count-degraded asserted-stay
  veto remains a component qualification, not live count-health inference.
  Count zero releases immediately regardless of either hold.
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
- **REQ-POLICY-006:** Thresholds, dwell intervals, belief decay, likelihoods,
  traversal and bootstrap timing, and health horizons are coupled calibration.
  Changes require replay, adversarial tests, and shadow evidence rather than
  one-incident tuning.
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
  probability-driven after the release-eligibility gates are met. Current health
  diagnostics change neither those gates nor physical sensor health. Only an
  unconfirmed prediction lease has the shorter mandatory expiry described above.
- **REQ-POLICY-012:** Policy distinguishes confirming evidence from refresh-
  eligible evidence. An independently authorized `correlated_positive` may
  acquire an inactive zone or confirm an existing mature predicted phase, but it
  cannot emit `refreshed`; only ordinary trustworthy positive or interaction
  evidence is refresh eligible. Under the current engine's selected-coverage and
  physical-presence gates, an already-active stay generation that remains
  cadence-correlated and `asserted` or inside stable-clear confirmation
  cancels pending release dwell and vetoes release without creating a public
  refresh. Stable clear removes this asserted-state hold; the independent
  REQ-POLICY-013 hold can still prevent release. Authoritative count zero remains immediate.
- **REQ-POLICY-013, selected coverage and retained component endpoint:** Current
  retention belongs to selected coverage under PATH002/004, including retained
  endpoints after OFF and eligible earlier branches, not all historical visits
  or the union of alternative supports. Coverage protects only already
  evidence-acquired activity, never an inactive or merely predicted zone. Its
  loss consumes the actual displacement frontier; PATH005 independently defers
  departure decay through genuine presence protection, then POLICY014 requires
  the first eligible threshold crossing and full dwell. Count0 remains immediate.

  The following narrower settled-support contract remains a genuine component
  qualification; it does not make live retention support-only or authorize a new
  selected-track design. An evidence-active zone with a
  current settled endpoint cannot release from sensor clear, low belief, token
  expiry or elapsed time alone. Only the current endpoint is protective, not its
  historical route. This is a narrow retention rule, not selected-N attribution.
  Actual path/temporal-qualified support transfer (including TRAV-018) removes
  source retention; use the validated prospective support result while preserving
  post-publication commit. TRAV-015's exact confirmed departure or TRAV-017's
  on-selected-path generation departure may commit release eligibility even if
  count support stays at source. Weak or linked off-path outward is insufficient.
  A different healthy asserted/clearing same-zone stay still vetoes that release.
  While held, cancel pending release time. On loss of hold, lower-threshold dwell
  starts no earlier than committed qualified departure, or the current observed
  transfer/invalidation frontier when none exists; never reuse protected time.
  For a qualified evidence-active settled endpoint, pre-input elapsed processing
  preserves the original lower-threshold crossing even when the external input is
  duplicate or an invalid/unavailable count. Such inputs add no evidence; they
  cannot reset stored release progress. Coarse, repeated-input and restored
  continuations agree at equal frontiers; stale input still makes no advancement.
  Preserve count-zero release, existing health/unavailability support invalidation,
  and unconfirmed prediction expiry. Invalid count is not departure. The hold
  cannot acquire, change belief, create traversal, or make prediction evidence.
  Selected supportless/moving-front retention and stronger-alternative displacement
  are now governed by PATH001–005, not a pending extension of this component repair.

Current shared policy calibration is:

| Profile           | On threshold | Off threshold | Release dwell |
| ----------------- | ------------ | ------------- | ------------- |
| `transition_fast` | 0.70         | 0.30          | 15 seconds    |
| `stay_pir`        | 0.70         | 0.30          | 60 seconds    |
| `stay_presence`   | 0.70         | 0.30          | 120 seconds   |
| `entry_boundary`  | 0.70         | 0.30          | 15 seconds    |

## 10. Sensor Profiles and Hardware Settings

The supported profiles and current asserted-state calibration are:

| Profile           | Hardware clear/reset recommendation                                                         | Asserted local baseline | Traversal-context window | Track-bootstrap window | Software interpretation                                                                                             |
| ----------------- | ------------------------------------------------------------------------------------------- | ----------------------- | ------------------------ | ---------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `transition_fast` | Use the shortest reliable device setting, initially 5-15 seconds where hardware supports it | 0.15                    | 45 seconds               | 45 seconds             | Short zone persistence; may be the first or second observation that bootstraps a new adjacent track                 |
| `stay_pir`        | Start near 30 seconds; increase only if measured false clears are excessive                 | 0.90                    | 90 seconds               | 90 seconds             | Strong local retention evidence; a lone unsupported episode remains publicly off and creates no traversal authority |
| `stay_presence`   | Use the device's shortest stable presence/absence reporting                                 | 0.95                    | 180 seconds              | 120 seconds            | Strong current presence evidence; acquisition still requires selected/graph, pair, boundary, or prediction          |
| `entry_boundary`  | Use a short reliable reset consistent with the physical crossing                            | 0.10                    | 30 seconds               | 30 seconds             | Boundary reacquisition and count context, not long-lived room occupancy                                             |

The hardware recommendations are deployment starting points. The asserted local
baselines, traversal-context windows, and track-bootstrap windows are normative
current shared calibration. Device settings must be recorded with the map
profile because software timing must reflect actual hardware behavior.
Traversal/bootstrap windows bound ordinary component tokens/candidates, not
selected endpoint retention or ordinary live-origin pairing. The three-hour
cadence-warning window below is a legacy component calibration, not the live
ten-cycle diagnostic trigger. Device-parameter discovery/adaptation is deferred;
unknown device timing must not invalidate selected-path correctness.
See [deferred operational obligations](#deferred-operational-obligations) for the
retained timing research, historical evidence and unverified rollout requirements.

- **REQ-PROFILE-001:** Transition hardware should clear faster than stay-room
  hardware when reliable. This improves endpoint observability but correctness
  must not depend on the hallway producing a second edge before another room
  fires.
- **REQ-PROFILE-002:** A long asserted hallway supports the open traversal context
  described in `REQ-EVID-007`; it is not repeatedly counted and does not prevent
  another room from becoming a new leading edge.
- **REQ-PROFILE-003:** A stay room that fires and remains occupied retains belief
  through its longer local profile even after a fast transition sensor clears.
- **REQ-PROFILE-004:** Hardware or shared profile-timing changes are calibrated
  changes. Validate them with retained traces and shadow metrics before broad
  deployment.
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
  conflict evaluation. Reliability alone never authorizes an inactive zone. The
  conclusive interaction profile is restricted to nodes with reliability exactly
  `1.0`; uncertain physical interactions use an ordinary tempered profile.
- **REQ-PROFILE-009:** Track-bootstrap retention never delays or vetoes compatible
  selected, same-zone independent, adjacency, boundary, or mature prediction
  authorization. Its expiry removes only that candidate's authority, not a
  separately valid ordinary live origin. Missed-edge qualification is component-only.
- **REQ-PROFILE-010:** Cross-generation cycle correlation is enabled only for the
  shared `stay_presence` profile, with a ten-minute
  `cycle_correlation_window` and three-hour
  `sustained_cadence_warning_window`. Every other current profile sets both to
  zero. A nonzero warning window requires a nonzero correlation window and must
  be greater than it. Changes are shared calibration governed by
  `REQ-POLICY-006`, not room-specific incident tuning.

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
  Live result/edge callbacks read the completed accepted model frontier, including
  all policy decisions and committed support bindings. Read-only projection and
  strict save/restore are legal; mutation reentry rejects before mutation.
  External callback failure retains the accepted transition and learning debt,
  completes deferred cleanup and re-raises the failure. Local component
  prepare/decision/commit qualification must not be mistaken for exposing torn
  support state to a live subscriber. Learned counts remain unchanged until the
  explicit postpublication drain under PRED009, including on timer/count paths.
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
- **REQ-PUBLIC-006:** One enabled-by-default diagnostic sensor named
  `Predictive Controls Reliability Warnings` has unique ID
  `<entry_id>_predictive_controls_reliability_warnings`. Its native value counts
  distinct reportable `(node_id, kind)` rows from `REQ-DIAG-006`; bounded
  attributes expose `window_hours: 24`, active count, deterministic warning rows,
  a complete 24-hour summary, and an active-only summary without materializing
  policy audit. It is not an occupancy control authority. Deployment verifies
  its actual entity-registry ID before enabling any consumer.
- **REQ-PUBLIC-007:** The companion Home Assistant warning automation has stable
  top-level ID `predictive_controls_reliability_warning`, exactly one local
  `20:00:00` time trigger, `mode: single`, and no model-side detection. It sends
  `notify.notify` and one `persistent_notification.create` call with stable
  notification ID only when the sensor's `active_count` attribute is greater
  than zero; missing, unknown, unavailable, or zero active count sends nothing.
  Its message reports the sensor's deterministic active-only summary. Cleared
  retained history remains inspectable but never causes a notification.

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
  accepts only qualified confirmed adjacent token transitions. Selected-path
  confirmation enables execution under PRED008, not learning. Learning excludes provisional tracks,
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
- **REQ-PRED-007:** A `correlated_positive`, its dedicated authorization, and any
  confirmation of a predicted phase are excluded from prediction-source
  preparation, pending prediction learning, and route-statistic commit. The
  evidence may confirm a mature lease already created by a distinct confirmed
  source, but that outcome teaches nothing. The transfer-only support-backed
  continuation in `REQ-TRAV-014` may issue traversal authority for a later
  distinct physical episode; it does not create or renew a prediction lease or
  learning candidate from the correlated event itself.
  Ordinary as well as correlated `settled_adjacent_transfer` events are excluded
  from source preparation, pending learning and route commit. Existing mature
  predicted-target confirmation remains non-learning and creates no extra edge.

- **REQ-PRED-008, approved selected execution separation (2026-09-13):** A fresh
  ordinary positive selected arrival on a confirmed path may execute the mature
  prediction contract independently of learning. Its actual selected authorization,
  arrival episode and previous-source witness must match the operation's selected
  route suffix and a real final graph edge. Inherited confirmation may retain an
  actual two-node suffix; never fabricate a confirming triple or legacy token.
  Selected-only transitions do not enter pending learning or route commit.
  Each selected lease has an independent immutable `SelectedPredictionGrant` with
  the actual authorization, `effect_kind == positive`, predicted target node and
  original10second expiry. Both collections are bounded64 with a key composed of
  previous source/current arrival node/predicted target/arrival episode. Historical
  generation or four-visit eviction does not cancel a valid grant. Expiry, count0,
  authorizing-current-node unavailability, accepted target evidence, actual confirmed
  departure from that source and capacity eviction remove both records atomically.
  Departure uses the actual selected source, not a displaced endpoint. Equal-time
  accepted order governs cancellation; due expiry precedes duplicate classification.
  Confirmation remains nonissuing/nonlearning; selection stays4visits/at most2slots.
  Execution retains .85/support5, full-row statistics and existing health gates.
  This is approved authority, not a claim that global validation has passed.

- **REQ-PRED-009, approved durable learning (2026-09-14):** Already-qualified
  confirmed adjacent learning survives publication failure, restart, count0 and
  later source/history eviction without becoming new occupancy evidence or being
  requalified. Selected-only, correlated and prediction-confirmation events remain
  nonlearning. No learned count mutation precedes decision/result/edge, timer or
  count publication. Retain at most one optional prospective final count per
  configured directed edge, folded using the same per-observation capped addition
  as committed Markov counts, including fractional counts and the1e6 ceiling.
  Null denotes no effective increment. The latest bounded raw authorization batch
  may remain for diagnostics; after publication fold older work into the matrix.
  Writer projection includes both without mutation; restore retains only matrix
  debt, never a second representation of the same observation.
  An explicit postpublication drain commits a whole row only when no live lease
  has that current node, including diagnostic/equal-time/competing-target leases.
  Preparation alone cancels actual departures; historical learning cannot cancel
  newer leases or rewrite published full-row statistics, grants or policy. Consume
  debt only after successful atomic application; repeated restore/drain is inert.
  Continuous leases may defer a row indefinitely; bounded retained state, not a
  freshness deadline, is guaranteed. Count0 removes inference, not prior accepted
  statistical debt. Preparation failure accepts no new learning; subscriber failure
  retains accepted work. Runtime drains after publication in finally and preserves
  coalesced saving on failure and on learning-only timer/count changes. Durability
  begins at the completed Store write, not before unsaved operations reach disk.

## 13. Persistence and Restart

Persist only state needed to reproduce the next decision:

- map/profile fingerprint and authoritative count sequence;
- exactly N selected slots, their bounded visits/routes, per-node observed-origin
  and consumption records, displacement frontiers and per-zone physical holds;
- per-node episode identity, accepted state, timestamps, applied influence, and
  sensor-health state;
- per-zone filter state, last update time, public active state, acquisition phase
  and provenance, pending acquisition candidate, prediction confirmation
  deadline, and pending release dwell;
- unexpired traversal tokens with provisional/confirmed provenance and prediction
  leases;
- anonymous occupancy supports and bounded token-to-support mappings needed to
  preserve moving/settled state, endpoint, lineage, and deadlines;
- independent selected prediction grants paired with leases, bounded committed
  route statistics and deferred learning matrix, update sequence and audit metadata; and
- one bounded latest reliability-warning occurrence per configured physical
  node and warning reason.

- **REQ-STATE-001:** Restore validates schema, map fingerprint, count, timestamps,
  finite probabilities, episode identity, token expiry, supports, bindings, and
  policy state atomically, including every interaction episode, contribution,
  token, authorization, support, policy, and audit provenance enum.
  Every accepted episode frontier and serialized target snapshot satisfies
  `clear_emitted == (status == "clear")`; every transition away from `clear`
  resets the flag before effects or persistence. Restore does not normalize a
  mismatch: one invalid episode rejects the entire inference snapshot under
  `REQ-STATE-002`.
  Evidence-acquired active state remains bound to its acquisition episode, time,
  reason, bounded path, and source episodes. A prediction lease remains bound to
  the exact confirmed source token OR the independent selected prediction grant in
  REQ-PRED-008, distinguished by required persisted `authority_kind`. Selected grants
  and selected leases form a strict bijection, including diagnostic leases; missing,
  orphan, duplicated, malformed, expired-at-stored-frontier or over-bound records
  reject before pruning. Validate actual graph geometry, real current/historical
  episode generations and selected-source ledger chronology without requiring
  historical visits to remain selected. Equal-time older generations are allowed
  only by selected-derived chronology, not by weakening legacy token validation.
  Physical contribution/refresh and prediction-confirmed activation history use
  actual generation ordering at equal timestamps even after selected-visit eviction;
  these historical checks create no traversal, selection, lease or learning authority.
  A grant's previous-source witness matching the latest selected ledger generation
  must remain consumed; a newer ledger generation is not rewritten to describe an
  older witness. Baseline all-known-OFF may retain a previously issued historical
  grant, but cannot issue one. Unknown/unavailable revokes it.
  No missing current proof defaults or reconstruction from selection/startup.
  Every predicted policy matches exactly one mature retained lease; suppressed
  mature leases need not have a predicted policy. Its support must equal the retained target
  route count and its probability must equal the raw full-route probability from
  all retained competing counts and priors. The fingerprint covers every
  behavior-affecting map input plus sensor, belief, and policy calibrations.
- **REQ-STATE-002:** Invalid or incompatible state fails as a unit and bootstraps
  from current sensor/count snapshots without movement or public edges.
- **REQ-STATE-003:** Restore advances decay, traversal, moving-support expiry, and
  selected/physical-hold, diagnostic and policy frontiers exactly once to the restore
  frontier; count-conflict dwell remains a component qualification. Backward restore
  rejects before mutation. It must not reapply
  historical observation likelihoods, including finite-ceiling interaction
  updates, or reconstruct support from belief. After advancement and only for
  positive authoritative count, current raw `on` nodes may reselect an already
  restored matching episode that remains known-on, `asserted`, identity-valid,
  and healthy. This compatible-restore correction adds no episode, likelihood,
  traversal, support, policy acquisition, refresh, or public edge. A raw level
  with no matching restored asserted episode is ignored.
- **REQ-STATE-004:** The one-time exact-assignment schema-6 importer may preserve
  public `active` state only as a compatibility seed. It must not invent zone
  belief, traversal tokens, or support provenance. Migration is deferred until
  current sensor state is available, and a current valid authoritative count
  overrides the stored legacy count.
- **REQ-STATE-005:** The current persisted inference schema is
  `zone-belief-v4`, accepted only with the exact current behavioral fingerprint
  and every required current record. Matching the schema name alone is insufficient.
  Public restore rejects old-fingerprint v4 and all v3 inference; relabeling old
  records cannot supply missing current proof. Unknown interaction provenance
  rejects atomically without modifying configuration.
  Historical v3 decoding remains isolated and invents no support; it is not a
  current inference compatibility path. The separate `zone-belief-v2` importer
  retains only a validated count and Boolean active seed whose latest retained
  edge has allowed non-source-free provenance. It cold-builds from current raw
  sensors; it imports no old filter, episode, token, support, selection, pending
  or prediction state. Schema-6 likewise supplies only its validated compatibility
  seed. Both defer to a valid current authoritative count and invent no live origin.
  These paths are implemented by `decode_v2_seed`/`migrate_v2_seed` and
  `decode_schema6_seed`/`migrate_schema6_seed` in
  [persistence](custom_components/predictive_controls/zone_model/persistence.py),
  selected by [the facade](custom_components/predictive_controls/occupancy_tracker.py).
  Older `zone-belief-v1` state is incompatible and must cold bootstrap from current
  sensor/count snapshots. The canonical committed-outward belief shape is
  `context == cleared_with_outward` with a current generation and no pending
  outward object. A reader normalizes the legacy object-bearing committed shape
  only when its source equals that generation, no asserted episode remains, and
  its deadline is strictly later than the stored frontier; malformed legacy
  shapes reject atomically. REQ-POLICY-013 additionally stores optional qualified
  pending-outward expiry and committed generation-local departure time. Qualification
  uses its own half-open witness deadline, never a weak extension; committed time
  survives expiry and resets with generation/context supersession.
  Validate any pending qualified expiry against the stored frontier before legacy
  committed-shape normalization can discard its object; equality is expired.
- **REQ-STATE-006:** A currently asserted stay sensor observed during cold
  bootstrap seeds belief but cannot by itself turn on an inactive zone. It may
  restore evidence-acquired `active` only from validated compatible persistence,
  or acquire after current same-zone, adjacent-pair bootstrap, boundary,
  selected movement, or mature prediction authorization. Bootstrap emits no synthetic
  public edge.
- **REQ-STATE-007:** Restored pending and predicted phases remain bound to their
  original event-time deadlines. Restart cannot extend a track-bootstrap window,
  renew a prediction lease, or turn an expired phase on.
- **REQ-STATE-008:** Restart preserves provisional/confirmed track provenance
  and local-interaction provenance without increasing confidence or converting
  restored same-node callbacks into new episodes. Unexpired historical tokens
  from an older valid generation may coexist with the node's exact
  current-generation token; only the latter may be marked physically current or
  authorize a finite-ceiling update. Support bindings reference only tokens
  present in the same active/retained traversal snapshot; settled support may
  retain no binding after traversal retention expires. An inactive restored
  policy remains inactive when asserted context is reselected; current level
  alone cannot synthesize reacquisition. A later fresh trustworthy positive may
  reacquire through eligible selected authority or an independently qualified
  fallback such as `REQ-TRAV-016`, identically before and after restart.
- **REQ-STATE-009:** Every validity window is half-open: evidence is usable for
  `created_at <= event_at < expires_at`. At one timestamp, stored timer
  frontiers with deadline less than or equal to that timestamp are advanced
  before the external input. Thus evidence exactly at a pending, token, trust,
  prediction, stable-clear, conflict, or release deadline cannot renew or extend
  the expired deadline. Uninterrupted execution and restore at that timestamp
  emit the same ordered result.
- **REQ-STATE-010:** Supports restore only when IDs, bounded paths, endpoint
  node/zone/episode, provenance, state/deadline, bindings, current episode health,
  and belief context are mutually compatible, including unit reliability for
  local-interaction provenance. New settled support requires belief at or above
  the on threshold; an existing settled support may restore below that threshold
  in either valid cleared belief context without health or cadence warning.
  Belief-only outward context is independent of support-qualified departure.
  A moving support requires its mapped current target token; a settled support
  has no deadline and may outlive all bindings.
  Dedicated handoff tokens require a direct different-zone pair, provisional
  confidence and equivalence; their exact-endpoint derivatives permit only a
  non-equivalent one-node provisional token. Current transferred support may
  retain a direct adjacent pair without satisfying the three-node creation
  predicate. Independently validate encoded origin node/episode and require its
  occurrence in the inclusive interval `support.created_at <= origin_at <=
  support.updated_at`. Existing least-ID/min-created coalescence compacts member
  history; coalesced supports and later descendants cannot require origin-time
  equality, even when the latest transition no longer says `coalesced`.
  When retained, independently validate the origin token's valid original
  creation class
  (never handoff). Compare original/current provenance only for an untransferred
  origin. Current interaction provenance still requires an interaction endpoint
  and unit reliability regardless of update time. Current bindings agree with
  endpoint and mutation frontier; exact rebind may reset token path separately.
  Historical source evidence in active policy/audit uses historical episode
  references and direct pair identity, not current source ownership or health.
  Bounded origin eviction cannot prove an entire historical transfer chain;
  timestamp inverses reject origins before support creation or after mutation,
  not a reconstructible creation chronology that bounded history does not retain.
  Structural validation cannot provide cryptographic authenticity.
  Restored active and retained bindings use the same temporal authority rule as
  uninterrupted execution: a token older than the mapped support's `updated_at`
  remains lineage but cannot select, coalesce, transfer, or target-rebind that
  support. Restore does not rewrite that binding or invent movement. Invalid or
  unknown v4 interaction provenance rejects atomically. The historical accepted-v3
  migration copied its payload once to a distinct immutable rollback store before
  the first v4 primary write. The retained setup branch is conditional on successful
  v3 restore; current strict restore rejects v3, so this is not a current migration
  path or a promise of a new backup. Preserve existing rollback copies; downgrade
  requires a matching backup or cold bootstrap, never fingerprint rewriting or
  configuration destruction.
  REQ-POLICY-013 policy state includes a boolean retained-endpoint hold, valid only
  for evidence-active state with no pending release. Intrinsic component snapshot
  validation must not equate prospective policy with not-yet-committed supports;
  live callbacks instead read the fully committed frontier under PUBLIC001.
  Current readers require hold/qualification fields; isolated historical readers
  default them empty without inventing departure. Committed departure must be UTC,
  no newer than its belief frontier, generation-scoped and cleared-with-outward.
- **REQ-STATE-011:** Home Assistant Store remains `7`, inference remains
  `zone-belief-v4`, and current restore requires the exact semantic fingerprint
  from `_target_map_fingerprint_payload` in
  [persistence](custom_components/predictive_controls/zone_model/persistence.py).
  Alongside map, capability/profile, reliability, route-prior, belief, policy,
  arrival and prediction calibration, its current top-level integer version keys
  (all `1`) are `settled_adjacent_transfer_version`, `support_departure_version`,
  `impossible_cadence_preservation_version`, `supported_gap_acquisition_version`,
  `settled_endpoint_release_version`, `selected_path_version`,
  `presence_gated_departure_version`, `selected_prediction_execution_version`,
  `unsupported_jump_diagnostics_version` and `deferred_prediction_learning_version`.
  `path_health_calibration` includes unsupported-ON duration, quick-cycle window,
  maximum ON duration and completion count. Retained component keys do not enable
  those components as current acquisition/health policy.
  The September16 HEALTH002 amendment changes window/count from3600s/6 to1200s/10;
  unsupported600s and maximumON60s remain. Old fingerprints reject before snapshot
  decoding; the user approved cold inference rather than a partial health migration.
  No Store/schema bump, fingerprint rewriting or configuration reset is required.

  Required current state includes selected paths/sources, path health, displacement
  and physical-hold fields, selected prediction grants, lease `authority_kind` and
  deferred learning. Missing proof never defaults from startup or old inference.
  Earlier v4 compatibility windows are superseded; mismatched fingerprints reject
  before decoding. Historical recipes and archived expected hashes remain unchanged.
  Only isolated historical decoders may default absent selected/grant/hold records
  empty, or absent cadence state to no run, zero cycles and uncorrelated. Historical
  cadence/health conversion retains actual event/degradation times. UTC ordering,
  reason/kind, node/zone, unique sorted occurrences and half-open deadlines still
  validate at their actual component boundary; that alone does not certify a current
  engine snapshot. Separate v2/schema-6 seeds and pre-existing rollback copies are
  not full inference compatibility. No fingerprint edits or synthetic edges.

- **REQ-STATE-012, superseded live-stay plan and current provenance scope:**
  The earlier REQ-TRAV-019 plan for nested `StayPairingState`, `live_observed`,
  `origin_episode_id`, `available`, `last_use`, `clear_since` and fingerprint key
  `live_stay_adjacent_pair_version` is historical and was superseded by PATH003
  and PATH-STATE001. None is a required live field, missing implementation item,
  or permission to reinstate one-consumption stay-only pairing/rearm rules.
  `support_departure_version: 1` remains applicable to independent support
  retention and atomic departure under COUNT011/STATE010.

  Actual current origin authority is `SelectedSource(node_id, episode_id, at,
  origin, consumed)` in
  [selected paths](custom_components/predictive_controls/zone_model/selected_paths.py).
  Only an unconsumed ordinary live generation seeds a pair; correlated and
  interaction origins are accounted but cannot seed one. Interaction still has
  its explicit local acquisition path. Bootstrap, aliases, timers, positive count
  and history eviction cannot synthesize or replenish an origin. Current
  node/generation/occurrence, canonical slot inventory and consumption chronology
  are strict; missing, malformed, future or contradictory current records reject
  atomically. Physical alias reconciliation may revoke but never reconstruct
  authority. Independent historical episode validation remains in
  [the engine](custom_components/predictive_controls/zone_model/engine.py) and
  [snapshot validators](custom_components/predictive_controls/zone_model/validation.py);
  old references do not require current ownership or invent removed tokens.

- **REQ-STATE-013, durable learning matrix:** Current prediction state requires
  `deferred_counts` with exactly the configured node and directed adjacency keys,
  including empty rows. Each value is null or a finite nonboolean number satisfying
  `committed < deferred <= 1e6`; a saturated committed edge requires null. Missing,
  malformed, extra/missing-key, nonfinite or nonincreasing debt rejects atomically
  before expiry/pruning. Debt is statistical state like learned counts, not proof
  of occupancy. Existing strict count, lease/grant, stored-frontier, full-row
  probability/support and predicted-policy validation is unchanged. Add only
  current fingerprint discriminator `deferred_prediction_learning_version:1`,
  retaining Store7/zone-belief-v4. Old current fingerprints reject before decode;
  historical recipes exclude the later key without changing archived expected
  hashes. No missing-current-field defaults or fingerprint rewriting are allowed.
  Compatible save/restart at callbacks, before/after draining and after later
  advancement preserves each accepted increment exactly once without extending
  leases or replaying physical evidence.

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
anonymous supports, token bindings, selected conflict support IDs, latest bounded
support transition, pending candidates, reliability calibration, and
bounded audit retention. They do not need to serialize a whole-house exact
assignment graph.
Current diagnostics additionally expose selected paths/origins, displacement,
physical presence holds and independent prediction grants/debt. Legacy support
or conflict fields are component provenance, not current selected occupancy or
live episode-fault inference.

- **REQ-DIAG-001:** An operator can explain every public edge from one zone-local
  audit row plus referenced neighboring episodes.
- **REQ-DIAG-002:** Audit retention has fixed time, entry, and byte bounds with
  constant-time FIFO eviction.
- **REQ-DIAG-003:** A zone active longer than its profile expectation without
  current trustworthy evidence is directly observable as a diagnostic condition.
- **REQ-DIAG-004:** Current selected acquisition uses `selected_path`; prediction
  uses `prediction_authorized`. HEALTH001–004 project `assertion_timeout`,
  `sustained_flapping` and `unsupported_jump` as distinct diagnostic reasons.
  The following retained vocabulary applies only where its corresponding
  fallback/component contract actually runs, not as mandatory live emissions:
  `same_zone_authorized`, `adjacent_authorized`, `boundary_authorized`,
  `missed_edge_authorized`, `prediction_authorized`, `track_bootstrap_pending`,
  `provisional_track_acquired`, `track_confirmed`, `untracked_expired`,
  `correlated_flap_ignored`, `correlated_continuity_authorized`,
  `impossible_cadence`, `stuck_count_conflict`, `stuck_conflict_cleared`, and
  `prediction_unconfirmed`, plus `settled_adjacent_transfer` with its actual
  source episode and bounded support-transition explanation. A single local episode with only positive count is
  never labeled `source_free_corroborated`.
- **REQ-DIAG-005:** A retained component count-conflict audit row identifies the
  selected anonymous support IDs, endpoint zones, and reliability result without claiming occupant
  identities. Runtime status retains legacy ID arrays only as exact one-release
  aliases; v4 persistence contains no legacy front field names.
- **REQ-DIAG-006:** Current reliability warnings include quick-cycle flapping,
  unsupported continuously-ON evidence and unsupported spatial jumps under
  HEALTH001–004, not count-driven episode faults. The model retains at most one latest
  occurrence per `(node_id, reason)`, with exact UTC first, last, and optional
  clear timestamps. Recurrence replaces the cleared record for that identity.
  Status projects an occurrence when it is active or its last-observed time is
  strictly newer than 24 elapsed hours before the projection frontier; a cleared
  occurrence exactly 24 hours old is excluded. The ledger is diagnostics only
  and never evidence, traversal, count, policy, or prediction authority.
- **REQ-DIAG-007:** Reliability renders every active warning kind per physical node:
  `Flapping`, continuous presence without verified path support, and the distinct
  unsupported-spatial diagnostic. User-approved presentation amendment2026-09-15:
  a `suspected_stuck` row whose only reason is `assertion_timeout` is described
  as **Continuous presence detected; path unverified**, not a proven/suspected
  hardware fault. Keep the machine kind/reason, counts,600s qualification,
  recovery, persisted records and model behavior unchanged. This wording applies
  to active and retained cleared rows; mixed/legacy fault reasons retain their
  existing descriptions. It does not assert a known restart or person location.
  Both public Reliability summaries and panel labels honor the same rule.
  The Occupancy Graph derives current warnings from the same path-health projection,
  labels affected nodes, and gives red warning color precedence over active,
  frontier, border, shadow, and confidence-bar colors while preserving solid or
  dashed shape semantics. Cleared retained history does not keep a zone red.
- **REQ-DIAG-008:** The panel displays selected anonymous slots directly above
  the graph, preserving all zone cards and six existing workspaces. Derive route
  membership from selected_paths.route, not visit unions, belief or old policy
  authorizations. A current-presence occurrence requires branch_active, matching
  physical node/zone/current episode and aggregate phase ON (not clearing).
  All such occurrences have equal strength. Other retained occurrences are
  history, including OFF/unknown endpoints. Candidate destinations are only one
  outgoing configured hop from current-presence nodes. Aggregate strongest role
  presence > history > candidate > neutral across nodes/slots/zones while keeping
  all slot memberships and ordered revisit chips. Do not infer people, shorten
  routes across missing intermediates, expand candidates recursively, or evict
  endpoints by elapsed time. Provisional/confirmed badges do not change strength.
  Warnings override colors, not textual roles or line shape. Count0/null slots,
  malformed/unavailable/mismatched data are explicit; only absent selected_paths
  permits a labeled legacy-frontier fallback, never present empty or malformed.
- **REQ-DIAG-009:** Frontend sources are strict TypeScript with modular typed
  view components and pure path/layout/map/format/YAML helpers. Enable strict,
  noUncheckedIndexedAccess and exactOptionalPropertyTypes; no any, unchecked
  casts, non-null assertions or suppression escape hatches. Decode unknown wire
  inputs before use, preserve unknown map fields and YAML/alias types, escape
  dynamic text, and scope styles to the panel. Preserve dirty edits, focused
  controls and scroll during routine refresh; bound requests and prevent stale
  async responses or disconnect/reconnect from corrupting current state. Keep
  save and stale-entity preview/confirmation contracts with duplicate-write guards.
  Match the actual producer's nullable diagnostic-count contract:
  `occupancy_diagnostics.unsupported_count` is null when supported, otherwise the
  rejected integer greater than two; it is not a Boolean. Preserve an omitted
  historical field, reject invalid values without coercion, and keep valid
  beliefs/policies visible even when an unsupported count disables path display.
  Cross-language tests must feed real runtime status payloads through both the
  source decoder and shipped panel, including stale-response recovery; duplicated
  hand-authored frontend mocks alone do not establish wire compatibility.
- **REQ-DIAG-010:** HACS consumes prebuilt self-contained JavaScript inside the
  integration; it never runs a source build. Retain the native custom element,
  existing module_url/admin registration and version agreement. Locked development
  dependencies produce deterministic artifacts; strict typecheck, nonwriting
  freshness, pure/real-DOM unit tests and standalone bundle checks are blocking
  frontend gates. No CDN, bare runtime import, missing chunk or Node requirement.

## 15. Performance and Determinism

- **REQ-PERF-001:** A selected-path, adjacent-token, reopened correlated-continuity,
  cadence-correlated target, adjacent-pair bootstrap, same-zone independent,
  boundary, local-interaction, or mature prediction
  authorization produces its in-memory
  policy decision with p99 latency at or below 5 ms and hard latency below 10 ms
  on the 16-zone reference map at $N=2$. The retained 100-event benchmark must
  exercise and explicitly qualify each named fast path, including 100/100
  local-interaction acquisitions, cadence-correlated target decisions, and
  ordinary/correlated settled-adjacent transfers with corresponding public
  writes. The integration schedules
  the corresponding `active` publication in the same Home Assistant event-loop
  update in which it receives the accepted evidence. No confirmation timer,
  blocking I/O, persistence, audit materialization, or learning update may
  precede that decision and schedule.
  Retained historical workload names must explicitly qualify their current
  selected/fallback equivalent, never a no-op or a reason string alone. Ordinary
  missed-edge acquisition is replaced only by PERF008's rejected-jump workload.
- **REQ-PERF-002:** Routine benchmark validation uses 100 events. Every benchmark
  entry point hard-rejects more than 1,000 requested events. A standalone CLI
  invocation with an output path writes the complete JSON result there. If that
  result fails any gate, the invocation also emits the identical report to
  stderr before exiting nonzero; a passing file-output invocation remains
  silent.
  Evidence validation is strict without changing any limit: prediction proof
  checks the complete competing route row as finite nonboolean counts in
  `[0, 1e6]` before reconstruction; overflow cannot be silently discarded into
  a qualifying probability. Latencies are finite nonnegative nonboolean numbers;
  sample/output counters are actual integers, including required zero ON-write
  and acquired-event counts for rejected jumps. Boolean summary flags cannot
  substitute for complete measured samples, actual qualification or executed fanout.
- **REQ-PERF-003:** Per-event work is bounded by configured nodes, local graph
  degree, active traversal tokens, and fixed audit limits; it must not enumerate
  whole-home occupant assignments.
- **REQ-PERF-004:** Same inputs produce byte-stable persisted model state and
  deterministic diagnostics apart from explicitly excluded runtime timing fields.
- **REQ-PERF-005:** Routine entity publication must use bounded current-state
  projections without materializing retained policy audit. Shared automation
  summaries are computed at most once per runtime update. Each synchronous
  `DISPATCH_UPDATE` publication materializes at most one immutable model snapshot;
  `states`, `beliefs`, `policy_states`, `episode_states`, `traversal_tokens`,
  `diagnostics`, and `state_for_zone` reuse that snapshot until dispatch returns,
  including nested dispatch and failure cleanup. Full audit materialization is
  reserved for startup restoration, explicit diagnostics, persistence, and
  operator status requests.
  Health advancement reuses unchanged validated immutable records without
  skipping deadline, warning-refresh or frontier-validation work. Audit row
  sizing projects the flat immutable decision fields into fresh canonical JSON
  values without deep-copying them; exact bytes, bounds, eviction and post-write
  deferral ordering remain unchanged. No cross-operation cache is required.
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

**Scope reconciliation, 2026-09-17:** the existing requirements and named
amendments below are preserved, not newly rewritten acceptance. PATH001–008,
PATH-STATE001–002, HEALTH001–004, POLICY014, PRED008–009 and STATE013 govern current selected/runtime
behavior; superseded token/count-fault/gap expectations remain genuine separately
qualified component contracts. All originally frozen scenarios, material inputs,
numeric thresholds and public oracles remain unchanged in this completion pass.
Earlier explicitly approved amendments retain their recorded scope; this note
authorizes no further retiming, replacement oracle or relaxed qualification.

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
  normal belief decay; clearing/resetting it restores normal evaluation, while
  loss of a selected outside support after degradation clears the conflict in
  the same update and restores a matching still-asserted stay episode without a
  synthetic observation, traversal authority, or public edge;
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
15. the fast paths, including a 100-event local-interaction trace, meet
  `REQ-PERF-001` independently of diagnostics and retained audit size;
16. a mapped unit-reliability physical event pulse acquires at the finite
  numerical ceiling in the same update for $N=1$ and $N=2$, never acquires for
  $N=0$, deduplicates by current episode generation across eviction and restore,
  invalidates authority on either live alias health state, retains a settled
  evidence-active endpoint through fallback decay without departure, and releases
  through ordinary decay/dwell after qualified outward departure or transfer; and
17. the exact retained Shaila Office cadence incident remains below target
  belief `0.70`, inactive, and free of policy events without changing its
  timestamps or assertions;
18. one sustained stay assertion receives full evidence, retains an already-
  active zone, and never raises flapping at the cadence or trust deadlines;
19. a linked positive immediately before ten minutes is correlated, one exactly
  at ten minutes is full, and a warning starts exactly at three hours only after
  a completed linked cycle, with quiet winning an equal deadline;
20. an isolated or support-unbound correlated target cannot refresh, create
  pending, token, support, prediction, or learning state, while distinct valid
  graph context or an existing mature prediction may confirm genuine target
  reentry; only the transfer-only support-backed exception in `REQ-TRAV-014`
  may issue a bounded token for later distinct graph use;
21. count zero and unknown/unavailable reset cadence without synthetic effects,
  nonzero count does not, and active correlated stay release remains vetoed
  through stable-clear confirmation before ordinary full dwell;
22. pre-handoff inference rejection, isolated historical decoding, exact warning/quiet deadline restart, bounded warning
  recurrence, active inclusion, and cleared 24-hour cutoff are deterministic and
  atomic;
23. the diagnostic sensor, dual Reliability labels, warning-red graph precedence,
  and single 20:00 automation satisfy `REQ-DIAG-006`, `REQ-DIAG-007`,
  `REQ-PUBLIC-006`, and `REQ-PUBLIC-007`; and
24. the exact stale EventEntity recovery incident creates no Shaila Office or
  Upstairs Bathroom interaction generation or public activation, while Alex
  Office retains the original asserted mmWave belief identity beyond the
  production false-release frontier without a new likelihood, traversal, or
  public edge; and
25. the exact retained 2026-08-28 bathroom departure commits outward decay past
  the former authority deadline and publishes one ordinary release, while the
  kitchen-to-foyer missed edge uses the exact matching kitchen clear frontier
  without renewing its still-valid token; and
26. all retained production incident regressions pass at the public contract.

### Public-timeline replay boundary

**Named release/S29 amendment, 2026-09-13:** the86 synthetic endpoint-ordering
qualifications retain physical inputs/maps/counts. Replace obsolete legacy
support/token/qualified-departure premises with actual selected displacement and
physical hold; unknown aliases are unavailable, not fabricated stable clears.
The ordinary5s control crosses1046.484750s and releases1170s with unchanged120s
dwell; require OFF by1200 for ignored-input variants and exact-deadline parity.
Add restored checks around the new crossing while retaining original observations.
`test_s29_elapsed_time_and_low_confidence_preserve_public_keep_on` retains hallON0,
roomON2, roomOFF3/count1/checkpoint720 and now requires retainedON without onward
evidence, consistent with PATH002. No sourced production report is asserted for
these synthetic cases. Other incident outcomes remain frozen.

**2026-09-12 user-approved migration:** all currently failing incident acceptance
primaries move to black-box runtime/public-entity replay, preserving actual recorded
inputs, timestamps, order, map/count/reliability and required public outcomes.
Remove token/support/provenance/q prerequisites from these primary acceptance tests;
do not merely rename old internal reasons. Captured latent marginals are not input
events: retain sourced values and separately qualified seeded boundaries without
injecting private state into the new black-box replay. Such seedless replays do not
claim exact historical posterior equivalence. Synthetic donor composites and
calibration/performance qualification remain outside incident acceptance, explicitly
identified as legacy/internal coverage rather than silently deleted.
Required newON at a particular detection, continuedON and requiredOFF by an original
deadline remain binding; alreadyON does not silently replace an acquired-at-return
requirement. Conflicting public outcomes stay red and must be reported.

**Named health acceptance amendment, 2026-09-12:** the supported Aug23 0556 target
must remain warning-free through610 seconds ON; add an explicitly synthetic
unsupported target at599/600/610 seconds with warning qualified at600, observed
through the actual sampled Reliability entity. The original retained-ON replay's
captured events and original checkpoint remain. The Aug23 2318 original two-cycle
sequence now expects no flap warning at its preserved checkpoints; explicitly
distinguish no publication from an empty published snapshot. Add analogous
synthetic five/six completed-cycle cases proving no warning atfive and a warning
at the next actual publication aftersix, with sixth-OFF occurrence timestamp.
Warnings remain diagnostic and do not activate/release lighting.

**Named health recalibration amendment, 2026-09-16:** the user approved10 completed
short ON/OFF cycles in20minutes, including synthetic boundary-test updates and
old-fingerprint rejection. The original Aug23 2318 primary's five timestamped
inputs and expectations remain unchanged. Its synthetic5/6 cases now stay quiet;
additional9/10 cases retain sampled-publication and exact tenthOFF/20minute expiry
proof. The Sep15 allocation primary remains verbatim; only its synthetic pruning
supplement adopts10/1200 while retaining immutable-state/exact-expiry/restore
checks. Nonincident count-reset, alias, coexistence, status/Problem, selected-path,
corruption, restart and benchmark-report state-cap qualifications use the new
boundary. No original lighting oracle, benchmark workload/sample or latency limit
changes. The separately retained
[foyer incident](tests/incidents/test_inc_2026_09_16_0418z_foyer_flapping_warning.py)
protects the newly reported sparse-motion warning failure.

**Named follow-up acceptance amendment, 2026-09-13:** September8's primary keeps
all14 original inputs, effective reliability1.0, counts1/2, setup, and pre-return
restore. Require closet input-phaseON12:13:34.142281 and uninterruptedON through
return12:16:24.972720 and checkpoint12:16:56.291116, rather than forbidding earlier
ON and requiring another ON while already active. Add a separately synthetic
no-return case retaining the11-input prefix through closetOFF; omit the entire
return/entrance/top suffix and prove eventual release under real runtime timers.
The20 ordinary long-stay qualifications remain unchanged.

The two synthetic endpoint tests formerly named
`test_runtime_off_path_linked_outward_cannot_release_settled_endpoint` and
`test_runtime_causal_transfer_of_low_belief_endpoint_starts_full_dwell` describe
one selected path plusU, not two independently converged paths. Preserve their
source0/hall1/room2/hall2at3 andOFF4..7 inputs (and latterhallON85); amend independent
legacy support retention to roomON2 then ordinary branch-displacement release.
Add an analogous genuinely converged two-path public scenario: one leaving must
retain the other room endpoint despite all sensorsOFF/time. N1 andN2 without
the independent second approach must release; restore must preserve each outcome.
Count2 alone never places an unlocated slot in the former room.

**Qualification migration approval, 2026-09-13:** comparator component fixtures
may explicitly construct complete documents at both authorization locations;
retain all240 location-parametrized mutation checks and genuine runtime capture
integration, including selected-only empty learning. Benchmark acquisition
fixtures must qualify actual current selected movement, initiallyOFF target,
acquired decision and matching public write before accepting latency. Retired
support/token and count-conflict timer premises get named current equivalents,
not skipped checks or weaker timing limits. Seeded legacy component qualifications
remain separate, with per-case named replacements and no invented historical state.

The migrated primaries use
[the shared runtime replay harness](tests/runtime_replay.py). Start at the
retained fixture origin, preserve timestamped input/receipt ordering, and run the
real runtime's registered recurring and one-shot callbacks against an aware UTC
fake clock. Due timers run before external inputs at the same timestamp, with
stable registration-order ties; this is a deterministic test convention, not a
claim about uncaptured Home Assistant event-loop ordering. Elapsed callbacks
must not synthesize physical observations.

Assert captured public `ZoneActiveSensor` writes and the complete boolean edge
timeline, not a forced engine evaluation at an assertion checkpoint. A checkpoint
with no scheduled work reads the last published value. Initial platform writes
are baseline, not acquisition; metadata-only writes are not boolean edges.
An immediate observation-caused ON must be captured in the input-dispatch phase;
a timer ON at the same timestamp cannot satisfy it. Delivery records distinguish
raw transport, occurrence, callback and receipt times, including rejected inputs
and count changes. Normalization is not proof of inference acceptance. Public
write attributes are captured copies, not later live-property reads.
These tests prove the public light-control signal, not downstream automation or
physical light actuation. Internal storage/support/token checks belong in separate
qualification suites, not prerequisites of migrated incident public oracles.
Passing incident tests are not implicitly rewritten. Reliability incidents observe
the actual sampled diagnostic entity, not internal warning state; no forced writes.

Keep both original baseline origins, maps, counts, sensor cycles and effective
observation reliabilities. September 5's historical `SensorInput` reliability
is 1.0 despite lower map aliases; its explicit compatibility adapter overrides
only the real normalizer's input reliability, not map-driven clear behavior.
Native replay input uses map reliability. Inference restore uses the runtime
storage API while retaining scheduler phase; it is not a full HA process restart.
Independent harness tests must cover cancellation, equal-time ordering, rejected
normalization, absent publication, distinct-state restoration and cleanup.

## 17. Change Governance

The dated approvals below retain their original scope and chronology. Their
then-pending/red implementation statements are historical, not current blockers
or instructions to restart a completed design review; Section 19.0 owns current
status. This documentation synchronization does not add a model amendment or
repeat the already-completed exactly three hardening passes.

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
  **Explicit completion repair approval (2026-09-13):** the user requests all
  performance, test and static failures repaired with meaningful qualifications
  aligned to the approved selected-path model, not coverage-only tests. This
  opens a new bounded repair cycle after the prior blocked handoff. Preserve
  incident files, numeric calibration, corruption mutations and parameter
  matrices; map each obsolete nonincident premise to current public behavior or
  its authentic isolated component guarantee before changing it. Performance
  and coverage limits remain unchanged; coverage instrumentation is not a
  wall-time acceptance environment under PERF007. Exact regression proof and
  three hardened passes governed the completed generic publication/count/restore
  fixes and necessary validator extraction. Their permanent
  [proof and disposition](#completion-proof-history) retain the qualified boundaries.
  No deployment, staging, compatibility relaxation or test exclusions are approved.
  **Additional explicit approval (2026-09-13):** implement PATH006/HEALTH004 and
  POLICY014/PERF008, the named release/S29 amendments above, and distinct warning
  regressions. This authorizes a new scoped warning/release correction cycle,
  not unbounded further prediction corrections. The working design completed three
  independent critique/rewrite passes; its implemented authority is the
  [warning/release amendment](#approved-unsupported-jump-and-release-follow-up--2026-09-13).
  Existing gap component qualifications remain; current positive gap-engine
  expectations require individually named negative/current replacements.
  **Explicit selected-path follow-up approval (2026-09-13):** apply the named
  September8 and two branch acceptance amendments in Section16, add converged
  two-path and no-return inverses, and migrate comparator/performance/component
  fixtures with preserved guarantees. Continue generic model repairs only after
  exact regression proof and scoped design; mature prediction execution must be
  separated from selected-only learning without fabricated persistence provenance.
  This is a new correction cycle; previous exhausted cycles are historical.
  Exactly3 initial hardening passes were completed for the follow-up. Later
  prediction/gap designs required their own explicit gates, subsequently resolved
  under [PRED008/009](#12-prediction-and-learning) and
  [PATH006](#approved-unsupported-jump-and-release-follow-up--2026-09-13), not
  implicitly approved by this earlier authorization.
  **Explicit presence/health follow-up approval (2026-09-12):** implement PATH005
  and the named health amendment in Section16. Keep Aug22 1745 observed inputs and
  retainedON oracle unchanged. Amend only the valid retired-C still-ON control in
  `test_strict_restore_rejects_null_displacement_for_retired_c` to retainedON; keep
  malformed null-displacement rejection required and failing if unresolved.
  Preserve the separately retained seeded Aug23 qualification and Sept8 oracle.
  Historical fingerprint recipe tests may remove later discriminator keys when
  reconstructing archived hashes, but must not change archived expected hashes.
  This authorizes a scoped presence-gate correction cycle, not repairs to the
  separately blocked prior-branch, startup-branch, corruption or prediction defects.
  Exactly3 grounded full-spec hardening passes were completed; permanent authority
  is [PATH005](#approved-selected-path-cutover-contract--2026-09-12), with
  [retained presence qualifications](tests/test_presence_gated_departure.py).
  **Explicit user-approved black-box migration (2026-09-12):** remove old model
  internals from currently failing incident acceptance tests in favor of the public
  entity boundary in Section16. Preserve recorded timestamps/order and public
  lighting expectations. Label synthetic/seedless coverage and retain non-equivalent
  scalar/composite/calibration/performance qualification separately with named
  traceability. Relocations are not fixed failures. This grants no permission to
  weaken public outcomes, xfail/skip reports, delete unrelated unit tests or repair
  production behavior under a test migration. Exactly3 migration hardening passes
  were completed; the permanent [public replay boundary](#public-timeline-replay-boundary)
  and [qualification provenance](#permanent-qualification-provenance)
  retain that scope.
  **Explicit user-approved acceptance exception (2026-09-11):** only
  [the 2026-09-05 0116Z closet replay](tests/incidents/test_inc_2026_09_05_0116z_settled_closet_reacquires_before_sleep_off.py),
  for both count parameterizations, replaces its sensor-clear/elapsed-time-only
  inactive expectation and dependent exactly-one later reacquisition with
  continuous active and no subsequent acquired/released edges. Preserve every
  captured input, timestamp, ordering, map/count setting, thirteen cycles, restart
  continuation and unrelated assertion. This is an intentional acceptance-policy
  correction, not a factual input correction or permission to modify any other
  frozen test. It remained red until evidence-based endpoint retention was
  implemented; the retained replay now passes in [final2](#current-local-conformance).
  The separately requested public-runtime/fake-clock test-mechanism migration
  preserves these outcomes and original inputs. It may expose an edge between
  old checkpoints; it does not authorize retiming inputs or weakening an oracle.
  **Additional explicit user approval (2026-09-11):** the separate
  [1556Z restore-rejection replay](tests/incidents/test_inc_2026_09_05_1556z_closet_active_missed_after_restore_rejection.py)
  also replaces its contradictory timeout-OFF and dependent forced reacquisition
  with retained ON/no subsequent acquisition. Preserve every input, count branch,
  background-unavailability sequence and storage continuation check. Do not delete
  the incident or extend this exception to unrelated assertions.
  **Additional explicit user approval after retention review (2026-09-11):**
  [the August 22 physical-button incident](tests/incidents/test_inc_2026_08_22_0728z_physical_press_acquires_then_decays_normally.py)
  applies the same endpoint-retention rule to its no-outward branch. Replace
  only the 70-minute timeout-OFF expectation with retained ON and no release;
  preserve the original interaction/map/times and the separate qualified-outward
  departure/release branch. Interaction-created settled support is not exempt
  from REQ-POLICY-013.
- **REQ-GOV-006:** A merged change to model behavior, public entities/events,
  persistence compatibility, shared calibration, or acceptance gates updates the
  implementation-conformance snapshot in Section 19 and any directly conflicting
  current-state documentation in the same change. Historical plans and changelog
  entries remain historical and must be labeled as such rather than rewritten as
  current authority.

## 18. Superseded Architecture

This specification intentionally replaces exact anonymous count-vector
occupancy, mandatory fixed-lag global movement assignment, `ArrivalSupported`,
`ReleaseSafe`, support-certificate renewal, and durable ownership in the current
system. Those mechanisms have no authority over current behavior and must not be
restored. It also replaces separate prediction/prelight control entities and
automation-side authorization splits: prediction is internal provenance behind
the one `active` output. The schema-6 decoder permitted by `REQ-STATE-004` is a
bounded data importer only and cannot execute retired inference.

## 19. Implementation Conformance Snapshot

[Section 19.0](#current-local-conformance) is the current local conformance result.
[Permanent qualification provenance](#permanent-qualification-provenance) records
the retained proof boundaries without intermediate implementation-stage ledgers.
The preamble and Sections 1–18 remain governing authority, including every named
acceptance/governance exception. Operational obligations and frozen textual
references remain in [Section 19.5](#deferred-operational-obligations) and
[Section 19.6](#retired-working-record-provenance).

<a id="current-local-conformance"></a>

### 19.0 Current local conformance — validation recorded 2026-09-17

**PASS, local qualification only.** The office-overlap fix and the complete test
repair pass every required gate. All3330 original Python case IDs, including the
61 prior failures, remain and now pass;21 additive qualifications bring the total
to3351. No frozen incident inputs/public oracles, coverage exclusions or performance
limits were weakened. Separate corpus/scenario runs are not substituted by the
full suite. Results below follow the final source/test changes and shipped build.

| Executed gate                                                           | Completed result                                                                                                                                                                                                  |
| ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Exact retained office regression, separate run                          | **1 passed**,0.83s                                                                                                                                                                                                |
| `.venv/bin/pytest --no-cov -q tests -k 'test_inc_'`                     | **83 passed**,32.75s, no failures/errors/skips                                                                                                                                                                    |
| `.venv/bin/pytest --no-cov -q -m scenario`                              | **111 passed**,32.15s, no failures/errors/skips                                                                                                                                                                   |
| `.venv/bin/pytest -q` with XML/coverage-JSON reports                    | **3351 passed**,182.02s pytest/183.848s outer; exit0, no failures/errors/skips                                                                                                                                    |
| Statement / branch coverage, fresh full run                             | **100% /100%**,7980/7980 statements,3072/3072 branches; zero missing/partial,12 existing exclusions unchanged                                                                                                     |
| `npm run test:frontend`                                                 | **308 passed**,3618.141102ms, no failures/cancellations/skips                                                                                                                                                     |
| Repository Ruff / mypy                                                  | Pass;172 files checked by default mypy                                                                                                                                                                            |
| `npm run build:frontend` then final `npm run check:frontend`            | Standard build, strict typecheck and nonwriting freshness pass; matching panels346980bytes, helpers7280bytes                                                                                                      |
| `.venv/bin/python benchmarks/occupancy_performance.py --events 100`     | **Pass**,17.935s;11 positive workloads100/100 each, worst p99 **3.281639ms**, max **3.315469ms**; rejected100/100 p99 **2.789493ms**, max **2.984092ms**, zero ON; all timer/correctness/sample/fanout gates pass |
| Frozen-source / index / editor / diff checks / independent final review | Pass; all250 pre-gate files unchanged through validation, index retained; no outstanding code blocker                                                                                                             |

**Office incident and falsifiable cause:** approved read-only history, status,
manual-press trace and logbook captures are retained in sibling Homelab's ignored
tmp/missed-office-path-20260917/ (capture naming, not the incident date).
Both stair sensors remained ON at office motion20:56:10.437899UTC on September16;
foyer reactivation20:56:00.241805 had prematurely retired the upstairs branch.
Live office active/light appeared only after manual press20:57:08.336000
(recorder callback20:57:08.336333). Full31-node and induced9-node cold replays
reproduced the miss; omitting only that foyer ON allowed motion-time activation.
This isolates selected retirement, not an automation or sensitivity defect.
Exact pre-walk inference/complete policy audit is unavailable; replay probabilities
are not asserted as live beliefs, and the railing/physical direction is unproven.
Primary history SHA256:
`9adcc7c50bae18182f6d4c7a19f7ed6e03ae03de256b99467f1d57d7d403431b`.

The permanent [office regression](tests/incidents/test_inc_2026_09_16_2054z_office_overlap_arrival.py)
keeps all46 recorded deliveries/12 entities, exact9-node map, explicit11 binary
OFF startup levels, neutral old button timestamp and configured count2. It failed
before the production change (1failed0.25s: ON only at the press), passed immediately
afterward, and now independently passes0.83s. It requires exactly one office ON
at motion20:56:10.437899, no premature activation/release/reacquisition through
the press, and no arrival-time unsupported_jump. September17 approval changed
summary comments only; executable AST stayed unchanged. Frozen current file SHA256:
`14b72ba80a0f70152429f1d7a089c00171b7d683a597472891aa23ed0b7a8bf0`.

**Preserved qualification and named replacements:**

- [Overlap reducer/engine tests](tests/test_selected_overlap.py) and
  [real-map wire tests](tests/test_overlap_wire_contract.py) cover bounded count0/1/2,
  pre-append source choice, all-copy revocation, strict restart/geometry and72 real
  producer frames. Historical prefixes never become raw-ON authority. The approved
  two synthetic room releases move OFF95 to105: actual support loss12, threshold
  crossing42.084982 plus unchanged60s dwell gives due102.084982 and timer publication
  105. Existing sensor streams remain; the separate presence case retains YON701
  and Coff1050. [Retirement fixtures](tests/overlap_retirement_fixture.py) and
  [selected-path boundaries](tests/test_selected_path_cutover_boundaries.py) give
  rejection/corruption cases actual clear/generation/history eviction, rather than
  falsely assuming a still-supported overlap is already retired.
- Learning/publication repair resolves43 failures without enabling selected-only
  learning or weakening callbacks/debt. [The qualification fixture](tests/learning_qualification_fixture.py)
  extends the synthetic graph from Z by three actually observed nodes at36;
  original E37 then evicts current C36, so T38 legitimately uses independently
  qualified adjacent traversal. Original U39 callbacks still see uncommitted
  statistics and exactly-once debt. [Eight controls](tests/test_learning_qualification.py)
  require true eviction, old endpoint versus current generation separation,
  strict roundtrips and no-token/unavailable rejection; same-row fixtures and
  every original assertion remain unchanged.
- Engine repair resolves16 failures with observed Z/E unavailable→ON generations
  at37, preserving current C36 physical/token/support provenance and the original
  T38/U39 acceptance. Retirement-only cases use actual OFF4/stable-clear14, not
  immediate X4 retirement; route-only inputs are unchanged. [Three replacement
  qualifications](tests/test_engine_overlap_qualification.py) retain the original
  held-ON history-eviction/nonrearm sequence at count1/2 and assert the actual token
  at real support preparation. No injected authorization or private path erasure.
- The two [status producer failures](tests/test_status_wire_contract.py) were
  synthetic missing-map-edge errors. Transport the actual reciprocal producer
  map with lossless mapping/YAML roundtrip, keeping original status frames and
  recovery assertions. [Frontend strict boundaries](tests/frontend/overlap_wire_boundaries.test.js)
  supply source/shipped RED26/positive7 before the decoder fix, then34 passing
  controls. Reject revoked-active endpoints and contradictory combined numeric
  generation chronology; preserve valid forks, opaque identities, exact recovery
  and fresh independent policy. The sole existing false-eligibility fixture
  correction makes its default endpoint inactive; its original assertion stays.
- [Physical provenance](tests/test_overlap_restore_provenance.py) retains18
  one-way correlation/legitimate-reset controls. [Prefix-only authority](tests/test_overlap_prefix_authority.py)
  covers the last previously missed constructor/codec guard at count1/2 using a
  consistent two-copy ancestor corruption, unchanged receiver and real continuation.

All repairs were mapped before editing, with exactly three parent/child hardening
passes and independent scoped/final reviews. Selected-only movement remains
nonlearning; real independent traversal is qualified at its actual boundary.
The latest test-repair stage changed no backend, captured incident, shared runtime
harness, benchmark or configuration. Original3330 IDs and all61 failed IDs are
verified green; explicit83/111 corpus cases are subsets of full3351, not inferred
passes. Coverage is a new non-append full measurement, not merged focused data.

Final evidence: sibling Homelab tmp/missed-office-path-20260917/repair-final-*
contains exact command vectors/exits, complete logs/XML, coverage JSON, benchmark
JSON and preservation intake. Scoped repair-learning/engine/wire/prefix artifacts
retain RED/GREEN and assertion/input preservation. The earlier verification audit
remains historical:3269pass/61fail,99.891422% coverage; its first interrupted
terminal attempt lacks final coverage and is never counted as complete.
All commands finished; staged-entry digest remains
`de69f1ed2d735c94fc2a110d61bad1dd4ff047c5fb844687f9b923f45114ce55`.

Canonical contracts/results are reconciled; the completed office working spec and
three scoped qualification plans are removed. Frozen source comments referring
to those working records are provenance, not surviving design authority. The
separate unresolved September5 external-office spec remains. No deployment,
live restart, state reset, staging, commit or physical actuation is claimed.
Rollout needs matching backend/346980byte panels and browser reload; selected v2
changes the semantic fingerprint while Store7/v4 stays. Preserve configuration
and backups; old full inference rejects and cold-reconstructs from subsequent
evidence. Rollback requires a matching snapshot or cold bootstrap, never an edited
fingerprint. Deferred operational checks below remain open.

#### Historical green baseline — 2026-09-16, before overlapping-branch changes

**Foyer flapping recalibration:** approved read-only status/logbook captures in
sibling Homelab's ignored tmp/foyer-flapping-20260916/ confirm the former6/hour
predicate, not a panel defect. At05:40:32.801267UTC the foyer was5%/inactive with
an active sustained_flapping warning qualified05:32:26.113086UTC. Its latest six
OFFs span48m16.944002s; only two fall in the latest20minutes. Count2; physical
episode cadence/health flags false. Status SHA256
`7d5cd76082a87090b57ce3b4ca35046b02f17f1890e2e4c2d919899952423b55`; history SHA256
`5307463b23f65ba82003b8172e67a349a6a533c8b011dce845981f3d49b14ded`.
The [permanent replay](tests/incidents/test_inc_2026_09_16_0418z_foyer_flapping_warning.py)
retains all18 exact state/time/entity inputs from04:18:01.614430 to05:32:26.113086
UTC and uses real scheduled Reliability publications through the capture frontier.
It uses the causal one-node map slice at0.85, not invented neighbors, receipt times,
selected paths or latent posterior. It proves warning behavior, not actuation.

The disconfirming check was unchanged-runtime replay: it reproduced a public
flapping warning at04:46:31.614430, qualified at the sixthOFF04:46:23.110889.
Exact test failed0.35s before edits and passed0.33s immediately after the first
production edit. Only path_health.py's window/count constants and matching
comment/error wording changed. No occupancy algorithm, frontend, hardware setting,
original incident primary, harness, package or benchmark source changed. The user
explicitly approved10/1200 and the named synthetic qualification migrations above.
The wider state cap remains bounded at10; old fingerprints reject before decode,
new snapshots round-trip before/during/after qualification. Independent reviews
found no grounded blocker. Exactly three spec hardening passes completed.

Focused194cases passed4.47s. The first full run found two additional old6-cycle
synthetic expectations: benchmark-report state cap and coexistence of three warning
kinds. These now preserve the new10 cap and original coexistence event pairs/day
frontiers, respectively; focused3cases passed1.30s. Every final gate was rerun
after those edits; final2 results below supersede the retained failed first run.
Canonical requirements/results are reconciled; the completed foyer working spec
is removed and its exact regression retained. Nothing was deployed/restarted.
Deployment must use the updated backend, expect old inference rejection/cold
reconstruction, and retain configuration/backups; rollback needs a matching snapshot
or cold bootstrap. Do not clear state or edit fingerprints to force compatibility.

**Earlier warning-label and strict-panel qualification:** the user approved
a presentation-only fix followed by a strict modular UX refactor. Approved
read-only diagnostics/history in sibling Homelab's ignored
tmp/occupied-room-warning-20260915 capture count2/U-U after incompatible-fingerprint
restore rejection, both rooms legitimately ON per the report, and exact600s
assertion_timeout frontiers17:34:15.769618/.791089UTC. Diagnostics SHA256
`cc7d089dd4acd91d60ca82e2d8688d9eb826ce7759ea459f9272d18db7529162`;
history SHA256`4a0fd2a1069504ae7cb1e16b87a7216df2a8cb7fb08006963752f6b35ca9529f`.
Missing selected evidence caused the warning, not proof of hardware failure;
warning and inactive policy independently followed missing path context. Time
alone need not clear it. The disconfirming check was exact-node selected support
or OFF/unknown recovery, preserved in neighboring tests. This does not reproduce
an actual restart or prove physical actuation.

The permanent [incident replay](tests/incidents/test_inc_2026_09_15_1724z_occupied_rooms_stuck_warning.py)
retains12 exact observations/processing frontiers and real scheduled public
Reliability writes. Pre-fix it failed only the no-stuck-label assertion
(0.37s, repeated0.35s); immediately after the first Python label edit it passed
(0.34s), with147 nearby diagnostic/status/inverse cases passing4.99s.
Counts, reasons,600s warning timestamps and frozen replay inputs remain intact.
The warning fix itself changes only status.py's label helper and summary call.
Existing display-only expectations in test_status.py and the graph test adopt
the approved wording; no other old test assertion/fixture/harness changed.

Frontend uses19strict TypeScript modules including9typed view components.
Selected paths/current-presence/history/candidate rules implement DIAG008, with
all old workspaces/cards preserved.231frontend cases cover31baseline,
117pure/layout/decoder/YAML,56shipped-bundle DOM,5artifact gates and22additional
strict diagnostic-count contracts. Browser
smoke at desktop/390px retains16zone cards,17Map nodes, no card overlap or page
overflow, equal ON3 roles, retained first2OFF history and warning-red border/bar.
That layout smoke used only local mock data. The self-contained0.2.6panel is337083bytes;
compatibility panel has identical bytes; generated helpers7280bytes. CI installs
locked dependencies and checks strict types and nonwriting freshness. No loader,
inference, persistence or fingerprint changes. The larger asset includes the
local YAML serializer instead of external runtime imports.

| Historical gate                                              | September16 result before overlapping-branch changes                                                                                                                                   |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full Python `.venv/bin/pytest -q`                            | **3245 passed**,168.32s pytest /169.425s outer (2m49s); **100% statement/branch**,7874 statements/3002 branches, zero missing/partial                                                  |
| Explicit `.venv/bin/pytest --no-cov -q tests -k 'test_inc_'` | **82 passed**,48.59s /48.739s outer                                                                                                                                                    |
| Separate `.venv/bin/pytest --no-cov -q -m scenario`          | **110 passed**,48.32s /48.453s outer                                                                                                                                                   |
| `npm run test:frontend`                                      | **231 passed**,3229.811516ms; zero failures/skips                                                                                                                                      |
| Ruff / mypy                                                  | Pass; repository-default mypy163 files                                                                                                                                                 |
| Strict typecheck / build / freshness                         | Pass; deterministic self-contained artifacts and unchanged0.2.6registration                                                                                                            |
| Editor / diff / frozen-source preservation                   | Pass; original incident primary bodies verbatim; harness/benchmark/frontend/packages unchanged; intake index9eddf4c4797446b4fdcdee778b37830859a13447a2b8ab26a99b2a36d4b6e909 preserved |
| Standalone100-event benchmark                                | **Pass**,14.924s; positive worst p99 **2.094580ms**, max **2.192460ms**; rejected p99 **2.188260ms**, max **2.724374ms**; all qualification, count, fanout, timer and hard gates pass  |

Fresh final artifacts: sibling Homelab's ignored tmp/foyer-flapping-20260916/
(final2-* logs and final-performance.json). Coverage is fresh/non-append and all
gates finished. Earlier panel artifacts remain in tmp/panel-unavailable-20260915/;
prior allocation artifacts remain in `/tmp/callback-perf-20260915/`.
During that earlier task the first frontend gate
correctly rejected stale generated assets after intervening source formatting.
The ordinary build regenerated only settings-callback formatting; strict freshness
and all frontend tests passed, and Python/corpus/scenario gates were rerun after
that final asset change. No failed attempt is counted as passing.

**2056Z panel-unavailable incident resolved locally:** the user reported all
cards unavailable after walking from Alex Office to Upstairs Hallway. Screenshot
time/movement onset are unknown; report receipt20:56UTC identifies the retained
[incident test](tests/incidents/test_inc_2026_09_15_2056z_panel_status_unavailable.py).
Approved read-only WebSocket status succeeded: count2,17zones,31nodes,two selected
paths, `unsupported_count=null`, policy frontier20:56:48.839419UTC. Raw capture
SHA256 `901a1e1ca49366ab990c299bed788fcc1528ae236c0979616d56a5cd1088652d`.
At capture office belief0.816069260847201/active and hallway0.050341895826638734/
inactive were valid; no claim about their exact screenshot-time state or physical
actuation. The frontend Boolean decoder rejected legitimate null and discarded
the entire status. Removing only this field in a private diagnostic copy decoded
all17zones/two paths, disconfirming other consumed-field failures in this capture.

Only the TS field type/validator changed, with rebuilt337083byte bundles. Null
and finite integers>2 are accepted without coercion; all true Boolean fields
remain strict. Three old synthetic frontend fixtures incorrectly used false/true;
they now use producer-faithful null/3. The old null-rejection assertion for this
non-Boolean field was replaced by22 dedicated strict domain/inverse cases, not
relaxed globally. No Python model, physical input, scenario, timing, layout or
benchmark changed. The sourced two-zone slice failed the actual shipped-panel
unavailable-banner oracle before edits (1failed0.50s), then passed immediately
(1passed0.36s). Full35,998,166byte capture also renders all17cards/two paths offline,
including bad-response stale retention and subsequent recovery.

[Producer-to-consumer tests](tests/test_status_wire_contract.py) feed actual
runtime_status_payload outputs through the source decoder and shipped JSDOM panel
for count0/1/2, authoritative unsupported3/5 and recovery (12cases in3Python tests).
Larger diagnostic counts have separate decoder checks; HA's existing state parser
accepts only0..5. The test runner compiles only the source decoder in memory using
esbuild for Node22 compatibility; it never repairs shipped assets. Python quality
gates now require installed frontend dev dependencies as CI already supplies.
Independent preimplementation/final reviews found no blocker. The working spec
is reconciled and removed; the sourced regression remains. Live HA was read only:
deploy rebuilt frontend assets and refresh browser cache before claiming live
recovery. No restart/deployment, staging or commit was performed.

**Performance blocker resolved without raising limits:** earlier UI qualification
under observed unrelated CPU contention failed (positive p99 5.634570ms/rejected
5.984307ms); CPU0 and original-status in-memory counterfactuals also failed.
Those failures remain in `/tmp/strict-panel-20260915-final/`; they did not establish
a label-induced regression. Fresh unmodified intake later passed at 4.097385ms /
4.212224ms. Host variability is a contributor hypothesis, not a proven cause.
The user explicitly requested optimization while retaining 5ms where feasible.

Callback-only profiling of exactly1200 measured runtime observations isolated
redundant unchanged health-state replacement and audit `asdict`/deepcopy work.
Only [health advancement](custom_components/predictive_controls/zone_model/path_health.py)
and [audit sizing](custom_components/predictive_controls/zone_model/policy.py)
were optimized; no model decisions, call order, validation, timing or schema changed.
The retained [computational regression](tests/incidents/test_inc_2026_09_15_2004z_callback_allocation.py)
explicitly uses local report-intake time, not fabricated HA events. Before edits,
its two work guards failed (200 redundant replacements/600 deepcopy calls), while
four public-diagnostic/byte-boundary proofs passed; immediately after edits all6
passed, with405 nearest tests green. It is not a host-independent latency replay.
Independent raw captures for all five trace profiles, count0/1/2 and100events each
(1500events) are exactly equal, including diagnostics, persisted state, strict
restore and continuation. This disconfirms semantic drift in those traces.

Matching instrumented callbacks reduced total calls from35,275,106 to23,402,306;
dataclass replacements449800→77900 (82.7% fewer), health-state validation392900→
21000, and audit `asdict` calls19400→0. Profile elapsed9.701→7.117s includes
instrumentation and is not acceptance latency. Both optimized uninstrumented
runs passed; the final authoritative result is in the table. All eleven positive
workloads qualify100/100; rejection qualifies100/100 with zero acquired/ON writes.
Unchanged5ms p99 and hard<10ms gates apply. No unrelated process was stopped.

Independent preimplementation and final read-only reviews found no blocker.
Canonical contracts and results are reconciled; the completed warning, UX and
allocation working specs and the later panel-status working spec are removed,
with their permanent regressions retained.
The unresolved external-office working record remains separate. No deployment,
restart, staging, commit or physical-light verification occurred.

#### Earlier test-runtime optimization qualification (historical baseline)

**Previous completed full-suite verification (before this UI/label work):**
the first fresh process-parallel coverage attempt passed
all **3217 unchanged tests** in **260.403s outer elapsed / 258.45s pytest elapsed**,
below the user-requested **300s** local coverage-command target. Collection, worker
startup, all fixtures, teardown, fresh coverage combination and JSON reporting were
inside the measured process boundary; a monotonic 300s supervisor would terminate
the controller/workers on timeout. No timeout occurred. Ordinary pytest itself has
no new wall-time enforcement. The canceled earlier serial documentation-validation
run remains incomplete evidence, not a passing run.
The request/artifact prefix is dated2026-09-14; actual JUnit execution starts at
2026-09-15T10:59:27.244636-04:00 and coverage records2026-09-15T11:03:44.617808.
Execution timestamps, not the filename prefix, date this verification.

The only execution change is a test-only `pytest-xdist>=3.8` dependency and default
`-n auto --maxprocesses=16 --dist=load --maxschedchunk=1 --max-worker-restart=0
--durations=20` arguments. xdist3.8.0 and execnet2.1.2 were installed without
upgrading existing packages; Python3.12 and coverage7.14.1/CTracer are unchanged.
Individual test cases distribute across processes, never across threads or partial
scenario timelines. No production/test/fixture/harness or benchmark source changed.
Use `-n0` for focused debugging; lower worker counts suit smaller machines.
No Turborepo, prior-result cache, coverage append, skipped case or altered threshold
contributed to this result. Current CI inherits the options through its existing
pytest command; five-minute completion on a smaller CI runner is unmeasured.

The serial baseline was **1712.380s**. One long-stay incident module accounted for
**686.016s**, including four 24-hour replay cases of104–106s each; benchmark tests
accounted for214.162s. These execute genuine callbacks and retain their exact proof.
The new outer elapsed is **6.58× faster** on the Ryzen 9 7950X3D (16cores/32threads).
Replicated fixtures and contention remain real overhead: individual long cases
took123–134s and semantic fixture setup reached24.30s in the parallel run. Child
maximum RSS was191544KiB; this is not aggregate process-tree peak memory, which
was not sampled. The subsequent verbose incident run confirms16workers; no worker
override was set in the full run. No universal speedup or no-swapping claim follows.

| Latest completed gate                | Verified result                                                                                                                                                                                                     |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full Python / fresh coverage         | **3217 passed**, zero failures/errors/skips; **100%**, identical42Python-file coverage inventory,7867statements/2996branches and exact executed-line/arc sets; zero missing/partial,12existing exclusions unchanged |
| Explicit retained `test_inc_` corpus | **69 passed**,37.48s pytest /37.673s outer                                                                                                                                                                          |
| Separate scenario marker             | **103 passed**,62.08s pytest /62.256s outer                                                                                                                                                                         |
| Frontend / build                     | **31 passed**,91.707255ms test runner; build passed,74425bytes                                                                                                                                                      |
| Ruff / mypy                          | Both pass; mypy157source files                                                                                                                                                                                      |
| Standalone100-event benchmark        | All gates pass;11positive/1negative/2timer workloads each100/100                                                                                                                                                    |
| Positive acquisition                 | Worst p99 **3.886930ms**, max **4.324091ms**; unchanged p99<=5ms/hard<10ms                                                                                                                                          |
| Mature prediction                    | p99 **2.935525ms**, max **2.976738ms**                                                                                                                                                                              |
| Rejected jump                        | p99 **3.803794ms**, max **4.347036ms**,100qualified/zeroON                                                                                                                                                          |
| Timers / core                        | Timer maxima0.329255/1.267318ms; core p954.425681/max4.941158ms; bounded-state and byte-stable persistence pass                                                                                                     |
| Diff / preservation                  | Worktree and cached diff checks pass; existing sources/tests unchanged; current staged-entry digest retained exactly                                                                                                |

Fresh full-run artifacts are `/tmp/test-runtime-20260914-parallel-1/` (run JSON,
log, JUnit, unique coverage database and coverage JSON); remaining gates and the
benchmark are under `/tmp/test-runtime-20260914-gates/`. Exact testcase identity
multiplicity, measured source inventory and covered arcs were compared with final2,
not merely counts/percentages. All required processes exited0; no tests remain
running. The additional gate commands sum122.232s: full coverage plus those distinct
checks totals **382.635s (6m23s)** in command time, not an under-five-minute claim
for the whole redundant validation sequence. Standalone benchmark SHA256:
`2cf75b622dd5a0a7d610afea27bda28507874ad8f1f13be9887d42414fc352ea`.

The earlier tooling-optimization intake index was
`1310bc69d61a1699ab1d1c80dc1f6a1d9293d60d066f2593e761bfd057cf4f10`;
older index hashes below are historical. This tooling optimization changes only
test configuration and current documentation; no deployment, staging or commit.
Its temporary design record was deleted after independent review, exact proof
preservation and canonical reconciliation. The review distinguished42Python
coverage files from47preserved production files/assets and verified146local links.

The approved selected-path, presence, warning/release and selected-prediction
contracts are implemented locally. Durable learning is also implemented:
postpublication row-blocked debt, strict writer/restore projection and count0
statistical retention follow PRED009/STATE013. It is no longer awaiting a production
fix. Current token/support, cadence/count and gap component qualifications remain
real boundaries, not re-enabled legacy control paths. All originally frozen
scenarios and incident inputs/oracles remain unchanged in the completion work.

The final correlated-token repair preserves only the exact independently
authorized correlated generation outside all selected visit/route history under
TRAV014's lifecycle clarification. Live callbacks can strictly read/restore the
committed frontier; selected-only and same-event correlated learning remain excluded.
Benchmark evidence now rejects overflowing prediction counts and Boolean numeric
substitutes without changing limits. Permanent proof is retained in
[engine contracts](tests/test_engine_completion_contracts.py),
[benchmark evidence contracts](tests/test_benchmark_evidence_contracts.py) and
[current-wire contracts](tests/test_current_wire_contracts.py).
The exact original 489-byte `_supported_gap_source` helper and 100-byte import
were restored for component qualification and frozen string-based interception
compatibility; there are **zero production callers**. This does not re-enable
unobserved-middle acquisition. A sole-field deletion of required
`path_displaced_at` from an accepted current snapshot rejects strictly, preserves
a populated receiver and supports unchanged real-observation/restore continuation.

The following are the **previously verified final2 results**, not a fresh rerun
for this documentation cleanup. All distinct final2 runs completed after that
last engine restoration.
Their XMLs contain zero failures, errors or skips; full coverage is measured from
the complete run, not a focused union. Retained evidence uses
`/tmp/full-green-final2-{incidents,scenarios,python,frontend,build,ruff,mypy,benchmark,semantic}.log`,
the three corresponding Python-run XMLs, and the final2 coverage/benchmark JSONs.

| Final2 gate                           | Verified result                                                                                                                           |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Explicit retained `test_inc_` corpus  | **69 passed**, 3148 deselected, **242.69s**                                                                                               |
| Separately marked scenarios           | **103 passed**, 3114 deselected, **273.45s**                                                                                              |
| Full Python / unchanged coverage gate | **3217 passed**, **1712.39s**; **7867 statements / 2996 branches all covered, 100%**, zero missing or partial branches                    |
| Frontend tests / build                | **31 passed**, **72.872569ms**; build passed, **74425 bytes**                                                                             |
| Repository Ruff / mypy                | Ruff clean; mypy clean in **157 source files**                                                                                            |
| Standalone 100-event benchmark        | All gates pass: **11 positive / 1 negative / 2 timer workloads**, every workload complete at **100/100**                                  |
| Positive acquisition latency          | Worst p99 **2.968193ms**, worst max **3.593307ms** across the 11 paths; each has 100 qualified acquisitions and 100 target writes         |
| Mature prediction latency             | p99 **2.558397ms**, max **2.586536ms**; 100 qualified acquisitions / 100 target writes                                                    |
| Rejected-jump workload                | p99 **3.281529ms**, max **3.300619ms**; 100 qualified rejections, **zero ON writes**                                                      |
| Timer workloads                       | Pending-expiry max **0.282167ms**; unsupported-ON health-deadline max **1.433717ms**                                                      |
| Core / bounded-state gates            | p95 **3.689646ms**, max **4.246241ms**; all core/state-bound/persistence gates pass                                                       |
| Five-profile semantic comparison      | Each profile: **20 events, count 2, zero differences**, 21 allowed all-null matrix normalizations plus explicit fingerprint handling only |
| Independent reviews                   | Code, contract, documentation and preservation reviews found no blocker within the reviewed local scope                                   |

Standalone report SHA-256:
`bf79935e6147e1ee445d845cb3cbbbd642f9e39a45ba91de8f66e456f313a4ae`.
Positive/rejection timing limits remain p99<=5ms and hard<10ms. All attempted
reports, including earlier failures, remain evidence; no timing waiver or
retry-selected success is claimed. Semantic profiles are `deterministic`,
`correlated_burst`, `maximum_lag`, `out_of_order` and `all_episodes_active`;
the retained comparison is `/tmp/durable-learning-semantic-comparison.json`.
Only the declared all-null matrix representation and explicit fingerprint
differences are normalized. Non-null differences, cardinality/order and other
semantic fields remain visible; this is not blanket payload equivalence.

<a id="completion-proof-history"></a>

#### Bounded completion proof and preservation

- Earlier full runs **2930 passed / 98.12%** and **3213 passed / 2 failed /
  99.981585%** failed the unchanged acceptance gates; focused passes and coverage
  unions did not establish conformance. The two failures were frozen helper-
  interception tests. Exact helper/import restoration plus two sole-field/current-
  wire controls preceded the distinct final2 **3217 passed / 100%** result above.
  The last engine correction cycle exhausted **3/3**; cleanup grants no further
  production correction authority.
- The synthetic correlated-token lifecycle regression was **1 red before the
  production edit → 1 green immediately afterward**, before subsequent test
  expansion. It protects the exact nonselected authorized generation, not token
  recreation, relaxed support validation or selected-only learning.
- The four approved original qualification functions had **3 red / 1 pass** in
  the focused baseline (the import-order defect also reproduced independently),
  then **4 green** in0.56s; their three modules passed288cases in14.82s. The
  84 additional benchmark evidence cases were **12 red / 72 green → 84 green**.
  These were discriminating boundary repairs, not weakened timing/coverage oracles.
- Final intake preservation: **all2930 original IDs retained +287 new =3217**;
  **240 comparator IDs, nine bodies and23 assertions intact**. The223-path intake
  hash audit found **211 unchanged /12 expected changed**, before deletion;
  **121 original test files were untouched**. Only the four previously approved
  functions in three original test files changed in the final qualification
  correction; the remainder of those files was byte-identical to that intake.
  These are scoped preservation facts, not a claim that all implementation files
  were unchanged across the whole migration.
- All14 protected configuration/reference-map/historical-report/instruction files
  and the staged-entry digest
  `64b7e69cd307c3ce5fb29923f2717a57be238f67b5ac7c2fbbb1ff07383e79ee`
  remained unchanged. Unstaged `git diff --check` passed. **Cached diff checking
  was not green:** it retained **eight preexisting EOF whitespace findings** in
  the event-driven working record, September5/10 incidents, and count/restore,
  presence, selected-path, unsupported-jump and gap tests. The exact unchanged
  index establishes these were not introduced by that final2 reconciliation.
  No staging, reset, scenario change or whitespace repair is implied.

**Documentation disposition:** the **38 completed/superseded working records**
were already deleted after final2 canonical verification. This cleanup additionally
removes **two obsolete historical ledgers**: the root migration plan and the test
requirement matrix; these are not part of the prior 38. Their current guarantees
remain in the governing requirements and permanent qualifications, with generic
rollout/backout constraints retained in Section 19.5. Only the unresolved external-
office working record remains. Factual scenario/test fixtures, frozen tests and
the user's async-todo prose are retained, not rewritten as migration plans. The
[frozen-reference map in Section19.6](#retired-working-record-provenance) retains
historical comment provenance without editing tests or promising that deleted
paths resolve. [Section19.5](#deferred-operational-obligations) preserves every
deferred timing/physical-interaction/anonymous-support rollout obligation and the
sole retained [external office issue](#unresolved-external-office-incident).
This cleanup changes documentation only, not production, tests or staged entries.
Repository conformance is not deployment approval, a live HA restart, physical-
actuation verification or external-incident closure.

<a id="permanent-qualification-provenance"></a>

### 19.1 Permanent qualification and provenance

The removed intermediate ledgers supplied no additional current model requirement
beyond the preamble and Sections 1–18. Earlier failed gates remain failed evidence,
not retrospectively passing runs; only distinct completed final runs establish
the recorded local conformance. Exactly-three-pass design reviews and narrowly
approved acceptance changes retain their original scope under
[GOV005](#17-change-governance); deleting ledgers grants no new test amendment.

- **Public replay, not inferred historical state:** the approved migration of
  17 failing incident files preserved sourced inputs, receipt/occurrence order,
  effective reliability and public outcomes except the separately named approvals
  in [Section 16](#public-timeline-replay-boundary). The
  [runtime harness](tests/runtime_replay.py), [scheduler qualifications](tests/test_runtime_replay.py)
  and [transport qualifications](tests/test_runtime_replay_transport.py) exercise
  actual registered 5/60/30-second callbacks, prediction deadlines, dispatch and
  copied public writes, including absent publication and sampled Reliability.
  Storage continuation preserves timer phase; it proves neither full HA restart
  nor disk durability. Seedless replay cannot reconstruct captured latent marginals.
  Separately retained [0326 seeded](tests/test_legacy_incident_0326_seeded.py),
  [2055 seeded](tests/test_legacy_incident_2055_seeded.py),
  [Aug23 seeded](tests/test_legacy_incident_aug23_seeded.py),
  [Aug28 seeded](tests/test_legacy_incident_aug28_seeded.py),
  [Sept8 composite](tests/test_legacy_incident_sept8_qualification.py) and
  [publication](tests/test_legacy_incident_publication.py) suites preserve
  non-equivalent qualification; relocation was not a production fix.
- **Selected authority and presence:** [selected-path boundaries](tests/test_selected_path_cutover_boundaries.py),
  [follow-up state](tests/test_selected_path_followup_state.py) and
  [presence qualifications](tests/test_presence_gated_departure.py) retain all six
  clear orders, count1/2, consumed-origin and prior-branch generation ordering,
  startup mismatch, null-displacement rejection and immediate mixed-alias strict
  roundtrips. Aggregate startup levels cannot mint movement or protection; hold
  loss uses its actual frontier and never charges protected time to release.
  PATH001–008 govern selection/retention; no device-timeout polling is implied.
- **Scoped red-to-green proof:** the unchanged
  [Aug22 retained-presence incident](tests/incidents/test_inc_2026_08_22_1745z_prearrival_token_cannot_release_asserted_target.py)
  was **1 red → 1 green**, eliminating the reproduced 17:50:43Z public OFF.
  Synthetic [unsupported-jump warnings](tests/test_unsupported_jump_warning.py)
  were **2 red → 2 green** immediately after the first production batch; no sourced
  never-observed-middle production incident was established. Ignored-input release
  proof was **20 red / 10 passed → 30 passed** immediately after the first edit:
  [86 original ordering cases](tests/test_zone_model_endpoint_retention_ordering.py)
  retain inputs/IDs and full120s dwell, with [20 public controls](tests/test_selected_release_public.py),
  exact deadline1166.484750, 5s-timer OFF1170 and coarse OFF1200. These proofs do not
  substitute for the final full suites or authorize other public-oracle changes.
- **Component guarantees remain genuine:** [traversal](tests/test_zone_model_traversal.py),
  [supports](tests/test_zone_model_supports.py), [handoff](tests/test_zone_model_handoff.py),
  [gap](tests/test_zone_model_supported_gap_acquisition.py),
  [count](tests/test_zone_model_count.py) and [cadence](tests/test_zone_model_cadence_preservation.py)
  retain accepted specimens, original mutations, numeric boundaries and inverse
  continuations at their actual production-component/validator boundary. This
  includes causal on-path support transfer, least-ID/min-created coalescence,
  age-independent qualified handoff, bounded original-token preservation,
  exact-endpoint reacquisition, generation-bound outward context and count-conflict
  recovery/held-stay dwell cancellation. These are not selected slots, time-only
  occupancy expiry, live count-driven faults or current unobserved-gap acquisition.
  Current callbacks observe fully committed state under PUBLIC001, not the old
  component prepare/callback/commit arrangement as live publication authority.
- **Strict persistence, not historical compatibility:** [persistence](tests/test_zone_model_persistence.py),
  [component validators](tests/test_persistence_component_validation.py),
  [count/restore](tests/test_count_restore_completion.py) and
  [current-wire tests](tests/test_current_wire_contracts.py) cover accepted current
  snapshots, atomic rejection and real continuation. Store7/v4 still requires
  every current record and exact fingerprint; old-fingerprint v4 and all v3
  inference reject. Historical readers and v2/schema6 compatibility seeds stay
  isolated, never supply missing selected proof, and never rewrite archived hashes.
  `clear_emitted` consistency and coalesced-origin chronology remain strict.
- **Execution is not learning:** [selected prediction](tests/test_selected_prediction.py)
  qualifies independent grants, mature same-entity activation, no duplicate
  confirmation edge, nonrenewing10s expiry and strict lease/grant restore.
  [Deferred learning](tests/test_deferred_learning.py) and the unchanged
  [publication regression](tests/test_learning_publication_completion.py) retain
  postpublication exactly-once debt under PRED009/STATE013. Only the explicitly
  approved supplementary same-row nonincident oracle changed from immediate
  learning to retained debt until row leases cancel/expire. Selected-only movement
  and same-event correlated evidence do not teach routes; count0 retains statistics.
- **Measurement boundaries:** [publication contracts](tests/test_publication_completion.py)
  and [benchmark qualification](tests/test_occupancy_performance_benchmark.py)
  require actual committed callbacks, complete fanout and initially-OFF target
  acquisition/write, not a reason string or no-op. All240 comparator mutations at
  both authorization locations remain; optional absent/null normalization is
  field/location-specific, never a blanket payload exemption. Diagnostic prediction
  execution is distinct from learning; rejected jumps have their own mandatory
  zero-ON workload. [Evidence validation](tests/test_benchmark_evidence_contracts.py)
  preserves strict counts, Boolean rejection and unchanged timing/coverage gates.
  Final2's five-profile comparison and allowed normalization remain exactly as
  recorded above; component equivalence is not a new selected-engine equivalence claim.

<a id="deferred-operational-obligations"></a>

### 19.5 Deferred operational obligations

These are carried-forward, deferred research and operational obligations, not new
model or policy requirements. Repository-green validation neither performs nor
closes them. Documentation cleanup authorizes no deployment, device-setting change,
new polling implementation, calibration amendment or external-incident closure.
[Section 19.0](#current-local-conformance) records the latest verified local
results; those local results do not close the obligations below.

<a id="deferred-device-timing"></a>

#### Device timing research — deferred

- No timing-discovery/cache adapter is implemented. The deferred proposal prefers
  available cached configuration at startup, configuration-change subscriptions
  and nonblocking availability/reconnect handling. Repeated radio polling is not
  the default; any refresh fallback needs a supported adapter and an explicitly
  bounded policy. Disabled-value access still requires an approved read-only
  script extension; cleanup permits neither enabling entities nor ad hoc live
  Home Assistant access.
- Bind context to the physical node/device/endpoint/parameter, never room names
  or guessed entity suffixes. Preserve raw value, verified unit/meaning, normalized
  value, source/model/firmware, observation timestamp and known/unknown/stale status.
  Observation time does not prove hardware application time. Version effective
  timing separately from shared policy; preserve open-episode interpretation across
  restart without retroactively rewriting accepted movement. Mid-episode changes
  and unavailable configuration need explicit design; unknown timing uses a labeled
  conservative fallback without compromising selected-path correctness.
- **Historical cached evidence, not current hardware verification:** the approved
  registry lookup at **2026-09-12T07:22:51.996928Z** found six parameter entities.
  Hallway Stay Life/Detection Timeout and Bedroom Entrance Reset Cycle/Timeout
  Duration were disabled; the closet's two timing entities were enabled. Subsequent
  approved cached reads returned closet Stay Life **300** and Detection Timeout
  **30**. Under the **archived September 5 VZW32** definitions only, parameter108
  uses **50 ms/unit**, so 300 represents **15 seconds**; parameter114 uses seconds,
  so 30 represents **30 seconds**, described as delay before a no-presence report.
  Definitions came from the September 5 diagnostic capture, not a current hardware
  interview or verified applied setting. Registry presence does not prove a readable
  or current value. Do not infer additive composition, exact departure or GE/Enbrighten
  motion-report versus local-load semantics from parameter names; model/firmware
  enumeration and exceptions require verification.
- A hardware latch may retrigger without another ON edge. Configuration reads and
  retriggers are not independent movement, cycles or occupancy evidence. Never turn
  settings into occupancy/adjacency TTLs, subtract them to invent departure, or
  rewrite shared profiles per device. Do not silently change the **600-second**
  unsupported-ON or **ten-cycle/20-minute** health rules; handling a genuinely long hardware
  latch under the unsupported-ON warning remains deferred, not an approved exception.
- Retain the future proof matrix: all six A/B/C clear orders; unequal/equal/unknown
  holds; retrigger without ON; middle-node flap/unavailability; restart before/after
  clear; mid-episode parameter changes; overlapping tracks; no polling-created
  traversal; retained endpoint without departure; and fresh side-branch detection
  after its authority is withdrawn. Use public runtime replay edges and path
  diagnostics, not only private token assertions. This remains a timing-adaptation
  proof obligation, not a claim that that matrix has run. Implemented route/history
  continuity and branch withdrawal already belong to
  [REQ-PATH-002/003](#approved-selected-path-cutover-contract--2026-09-12), not the
  superseded union proposal; they are not reopened by this research transfer.

<a id="deferred-physical-interaction-rollout"></a>

#### Physical-interaction rollout — unverified

After a separately authorized deployment, observe **at least one physical press,
one outward transition, one missed-outward continuation and one restart**. Preserve
the missed-outward observation, not its superseded timeout-only OFF oracle:
without qualified departure, retained ON is expected under current PATH retention;
assess eventual release only when current
[REQ-POLICY-013](#9-automation-policy)/[REQ-POLICY-014](#approved-unsupported-jump-and-release-follow-up--2026-09-13)
eligibility applies, including the
[REQ-PATH-005](#approved-selected-path-cutover-contract--2026-09-12) presence gate.
Back out on output-state false acquisition, replayed startup presses, failure of an
**eligible** release, duplicate supports, restore loops or latency-budget breach.

Deploy code before or atomically with its interaction map. Older code may retain
interaction nodes only when verified to ignore event timestamps; otherwise remove
only those nodes before starting that version. Preserve configuration and compatible
inference backups. Cold bootstrap must not replay retained timestamps or synthesize
movement/public edges.

<a id="deferred-anonymous-support-rollout"></a>

#### Anonymous-support rollout and rollback — unverified

Observe support/conflict diagnostics during representative **two-occupant movement
and at least one normal long stay** before operational acceptance. Require expected
transitions without false target degradation, duplication, restore-rejection loops
or performance breach; do not re-enable historical count-health inference to conduct
the observation. Prior repository review and conditional backup behavior did not
perform this still-outstanding production observation.

For a separately approved rollout, validate the retained corpus and performance
gates, use a maintenance window, and walk representative valid paths after startup,
including shared areas, reversals and quiet stays. Agree observation/acceptance
criteria before activation; a conservative cold bootstrap may leave a previously
active zone off until fresh graph-supported acquisition. These generic safeguards
survive the obsolete v3 rollout checklist; they neither mandate a v3 shadow switch
nor assert that any live observation or rollout has occurred.

Preserve configuration, a separately labeled pre-upgrade inference backup and a
usable downgrade/cold-bootstrap procedure. Retain the matching backup through a
stable release and the agreed observation period before considering its removal;
existing immutable rollback copies must not be overwritten.
Accepted-v3 backup creation was historical and conditional; current strict restore
rejects v3. Keep existing immutable copies, but promise no fresh v3 backup under
current code. Under [REQ-STATE-005/010/011](#13-persistence-and-restart), restore a
backup compatible with the rollback release or cold-bootstrap only incompatible
inference. Never rewrite fingerprints or delete map/options, entities, registry or
learned/user configuration. Disclose lost unsaved/post-upgrade inference continuity;
the completed-write durability boundary remains
[REQ-PRED-009](#12-prediction-and-learning), not a rollout guarantee.

Two retained operational cautions also remain: stale-input prevention cannot
retroactively distinguish old false interaction likelihood from a genuine press,
so it authorizes no historical belief subtraction/reset or synthetic reacquisition;
warning consumers stay disabled during rollback until their actual entity ID,
numeric state and [current contract](#11-public-contract) are verified.

<a id="unresolved-external-office-incident"></a>

#### External office incident — unresolved

The [retained office incident record](docs/spec/INC-2026-09-05-1707Z-office-light-reverted-after-correct-active-edge.md)
remains unchanged and open. Capture recurrence-time **node 282 Z-Wave command/value
evidence** through approved read-only access to distinguish local load action,
firmware action or an unsolicited/incorrect report. Correct public acquisition
does not explain the physical OFF. No unconditional retry or override of intentional
manual OFF is authorized.

<a id="retired-working-record-provenance"></a>

### 19.6 Retired working-record provenance map

This map preserves provenance for the 38 completed/superseded records deleted
after final2 validation and canonical reconciliation. Literal working-record references
in the **15 retained test modules** below identify historical pre-edit provenance,
not live documentation dependencies after disposition. Their comments/docstrings,
inputs and oracles remain unchanged. The labels are conceptual ledger stems, not
links to retiring paths; only retained tests and canonical requirement owners are
linked. These prose destinations do not make deleted filesystem paths resolve:
frozen textual references remain intentional, not "zero remaining references."
Disposition does not recreate superseded engine authority.

| Historical ledger label            | Retained referring tests                                                                                                                                                                     | Permanent contract / qualification owner                                                                                                                                                                                                                                                                                                                           |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| selected-path-completion           | [Count/restore](tests/test_count_restore_completion.py#L1), [learning publication](tests/test_learning_publication_completion.py#L1), [publication](tests/test_publication_completion.py#L1) | [COUNT006](#8-authoritative-count) identity and [STATE001/003](#13-persistence-and-restart) atomic restore; [PRED009](#12-prediction-and-learning) postpublication learning; [PUBLIC001](#11-public-contract)/[PERF005](#15-performance-and-determinism) committed public frontier/cache behavior.                                                                 |
| completion-learning-mapping        | [Deferred learning](tests/test_deferred_learning.py#L1)                                                                                                                                      | [PRED009](#12-prediction-and-learning)/[STATE013](#13-persistence-and-restart): the historical callback blocker is addressed by durable row debt, not premature count mutation.                                                                                                                                                                                    |
| completion-legacy-mapping          | [0326 seeded](tests/test_legacy_incident_0326_seeded.py#L1), [2055 seeded](tests/test_legacy_incident_2055_seeded.py#L1)                                                                     | Preserve **L0326/L2055**, exact scalar/timing qualification under [TRAV021/TRAV020](#72-retained-traversal-component-contracts), [BELIEF](#6-per-zone-belief-model) and [STATE009](#13-persistence-and-restart), separately from [seedless public replay](#public-timeline-replay-boundary).                                                                       |
| completion-physical-records        | [Physical contracts](tests/test_physical_record_contracts.py#L1)                                                                                                                             | Actual constructors and physical-frontier validation under [EVID](#5-physical-sensor-episodes), [HEALTH/PATH-STATE001](#approved-selected-path-cutover-contract--2026-09-12) and [STATE001/002](#13-persistence-and-restart), including atomicity and continuation.                                                                                                |
| selected-prediction-execution      | [Prediction](tests/test_prediction.py#L1)                                                                                                                                                    | [PRED001–009](#12-prediction-and-learning): authentic component learning versus selected execution; [PATH004](#approved-selected-path-cutover-contract--2026-09-12) never permits selected-only learning.                                                                                                                                                          |
| completion-runtime-wire            | [Runtime/wire](tests/test_runtime_wire_contracts.py#L1)                                                                                                                                      | [PUBLIC001/002](#11-public-contract)/[PRED009](#12-prediction-and-learning) publication-failure saving; [COUNT006](#8-authoritative-count) timestamps; [STATE001/003/013](#13-persistence-and-restart) grants and strict wire rejection.                                                                                                                           |
| completion-scalar-retention        | [Scalar retention](tests/test_scalar_retention_contracts.py#L1)                                                                                                                              | [PATH004/005](#approved-selected-path-cutover-contract--2026-09-12) displacement, [POLICY013](#9-automation-policy)/[POLICY014](#approved-unsupported-jump-and-release-follow-up--2026-09-13) full dwell, [TRAV016/018](#72-retained-traversal-component-contracts) qualified reacquisition and [COUNT008/011](#8-authoritative-count) genuine support boundaries. |
| completion-selected-boundaries     | [Selected contracts](tests/test_selected_path_contracts.py#L1)                                                                                                                               | [PATH001–004/PATH-STATE001](#approved-selected-path-cutover-contract--2026-09-12) origin/route/slot integrity and consumption chronology; [STATE001/002/008](#13-persistence-and-restart) atomic continuation.                                                                                                                                                     |
| selected-path-followup             | [Follow-up state](tests/test_selected_path_followup_state.py#L1)                                                                                                                             | [PATH001–005](#approved-selected-path-cutover-contract--2026-09-12)/[STATE001/008/009](#13-persistence-and-restart) follow-up guarantees; stored learned counts are calibration, not selected learning under [PATH004](#approved-selected-path-cutover-contract--2026-09-12).                                                                                      |
| completion-persistence-mapping     | [Cadence preservation](tests/test_zone_model_cadence_preservation.py#L1)                                                                                                                     | Preserve **A–K/R–S/V/W** component, **L–Q/X–Y** frontier and **T/U/current-zero** distinctions; [TRAV020](#72-retained-traversal-component-contracts)/[EVID013](#5-physical-sensor-episodes) qualification and [STATE009/011](#13-persistence-and-restart) deadlines/fingerprints do not restore legacy live authority.                                            |
| completion-engine-endpoint-mapping | [Engine](tests/test_zone_model_engine.py#L1)                                                                                                                                                 | Original-ID component/current-engine separation under [PATH/HEALTH](#approved-selected-path-cutover-contract--2026-09-12), [COUNT](#8-authoritative-count), [POLICY](#9-automation-policy) and [STATE](#13-persistence-and-restart); preserved inputs and genuine qualification boundaries.                                                                        |
| completion-gap-mapping             | [Supported gap](tests/test_zone_model_supported_gap_acquisition.py#L1)                                                                                                                       | Current [PATH006/HEALTH004](#approved-unsupported-jump-and-release-follow-up--2026-09-13) rejection/next-pair behavior versus retained [TRAV021](#72-retained-traversal-component-contracts) component authority; no current gap acquisition.                                                                                                                      |
