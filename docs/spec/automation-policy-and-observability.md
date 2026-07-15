# Automation Policy and Observability

## Public Entity Contract

- `active` is the default durable normal-output policy state. Its on edge is a
  supported acquisition and its off edge is a supported release. It is not a
  direct projection of one occupancy marginal, raw motion, or device state.
- `prelight` is the other default per-zone entity. It is an optional bounded
  prediction lease, never occupancy evidence.
- `arrival` is an optional disabled-by-default event for consumers that need a
  distinct accepted fresh episode while `active` is already on.
- Diagnostic confidence, paths, thresholds, and reasons are not required by
  ordinary room automations.

The normal automation contract is therefore one desired-state trigger:

1. `active -> on` turns normal outputs on;
2. `active -> off` turns normal outputs off; and
3. optional `prelight -> on` authorizes low-impact predictive lighting.

## Risk Policy

The project treats automation errors asymmetrically:

- False activation is controlled with fresh local evidence and whole-house
  arrival-support probability.
- False release is controlled by retaining trusted ownership until resolved
  posterior support accounts for every occupant outside the held zone.

Elapsed time, low marginal, posterior competition, local clear, unavailable
state, unrelated remote activity, restart, or reload MUST NOT alone change
`active` from on to off. A high empty-room posterior MAY authorize release only
through the joint support event defined below.

## Activation

For a fresh local episode in zone $z$, `ArrivalSupported(z)` is the event in the
augmented posterior that at least one occupant is in $z$ and the fresh endpoint
is assigned through a graph-valid arrival, prior `unlocated` mass, independent
local corroboration, strict missed-movement relocation, or eligible reacquisition
after a recorded false release. The endpoint MUST be count-feasible, unconsumed,
and attributable to the current physical-node episode.

Let

$$
a_z=P(\operatorname{ArrivalSupported}(z)\mid O_{1:k}).
$$

Acquisition is authorized when $a_z$ passes the calibrated false-activation risk
threshold and authoritative $N>0$. If `active` is off, that accepted acquisition
sets it on. Occupied marginal, increase, source, route, and competition values
remain decomposed diagnostics of this one posterior event, not independently
selected probability maxima.

A fresh local detection with coherent graph-arrival assignment is the ordinary
fast path. It SHOULD authorize activation unless count, local, ordering, or
competing-assignment mass keeps $a_z$ below the risk threshold.

- **POL-001:** Prediction alone cannot activate.
- **POL-002:** One physical entity cannot corroborate itself through repeated
  episodes or aliases.
- **POL-003:** Fresh evidence in an already active zone does not change `active`.
  A distinct accepted fresh episode MAY emit the optional `refreshed` arrival
  event defined by `ENT-004` when consumer-visible reacquisition is required.
- **POL-004:** Threshold changes require generic replay evidence and
  specification review.
- **POL-019:** The `active` off-to-on decision MUST be derived from $a_z$ and one
  shared threshold calibrated by declared sensor, role, or occupancy-behavior
  profile. It MUST NOT conjoin unrelated marginal maxima as if they were one
  hypothesis.
- **POL-005:** For a valid graph-backed local detection, the integration SHOULD
  compute and publish its in-memory `active` acquisition decision within 50 ms
  of callback
  receipt and MUST complete within 100 ms under the supported workload. This
  budget excludes downstream Home Assistant scheduling and physical device
  latency, which the integration does not control. When a trustworthy source
  event timestamp exists, diagnostics SHOULD also report raw-detection-to-public-
  state latency against the same 50 ms preferred and 100 ms hard targets.
- **POL-006:** Exceeding the preferred 50 ms target is diagnostic. Exceeding the
  100 ms hard budget MUST be recorded and MUST NOT turn an otherwise valid
  acquisition into a rejection.

## Active Ownership

Resolved graph or interval-censored departure, confirmed strict relocation, and
count-accounted exclusion are admissible ways to support one common posterior
release event. They are not separate policy paths with separately selected
threshold conjunctions. Authoritative $N=0$/away and explicit reset are the only
categorical overrides.

- **POL-007:** Trusted acquisition sets `active` ownership.
- **POL-008:** Local clear, elapsed time, low marginal, and unrelated activity
  cannot release ownership by themselves. They MAY contribute to a release only
  when the resulting augmented posterior satisfies `ReleaseSafe`.
- **POL-009:** Only `ReleaseSafe`, authoritative $N=0$/away, or explicit external
  operator reset may release `active` ownership. A nonzero authoritative count
  decrease updates the posterior through `MODEL-017` through `MODEL-021` but
  cannot choose a held zone to release.
- **POL-010:** A graph departure assignment is admissible outside support only
  when its joint mass also places zero occupants in the origin. Assignment and
  final-origin confirmation MAY arrive on different accepted updates inside the
  same retained fixed-lag graph. Policy MUST sum the joint qualifying mass and
  MUST NOT combine maxima, thresholds, or evidence from unrelated, stale, or
  expired episodes. Release waits for the qualifying assignments to finalize.
- **POL-011:** Every accepted and rejected release records gates, evidence IDs,
  prior latch, resulting latch, and reason.
- **POL-012:** Compatible restart or reload preserves `active` ownership without
  a synthetic state edge or arrival event.
- **POL-013:** Retained policy audit covers up to the preceding 12 hours, bounded
  by 8,192 decision entries and 12 MiB of compressed observation context so a
  sensor storm cannot create an unbounded Store file. Complete context MAY use
  a lossless compressed representation in memory, persistence, and transport,
  but restore MUST validate and reconstruct the same context atomically.
- **POL-014:** Reliability diagnostics MAY aggregate unique positive trigger
  events that policy rejected while `active` remained off, plus repeated short
  pulses whose positive edge failed the occupied gate. The aggregate MUST state
  its criteria and actual event coverage, deduplicate policy rows by trigger,
  exclude benign re-evaluation of an already-held zone, and remain diagnostic-
  only. It MUST NOT label a source definitively faulty or feed inference or
  policy.
- **POL-015:** The automatic false-off loss defines one shared high-confidence
  threshold over $P(\operatorname{ReleaseSafe}(z)\mid O_{1:k})$. A separate
  activation threshold provides hysteresis. Calibration MAY vary only by
  declared shared sensor, role, or occupancy-behavior profile; it MUST NOT vary
  by room or incident.
- **POL-016:** For held origin $z$, `ReleaseSafe(z)` is the event in augmented
  joint mass for which all of the following hold simultaneously:

  1. $N_z=0$;
  2. every one of the $N$ anonymous positions outside $z$ is injectively matched
    to a distinct admissible support item: a fresh independent local physical-
    node episode or a finalized causal movement assignment;
  3. one physical-node episode or external endpoint accounts for at most one
    occupant unless an explicit independent multiplicity observation exists;
  4. no occupant is accounted by `unlocated`, contextless, prediction-only,
    stale, duplicated, flap-derived, coarsened, or incomplete-overload support;
  5. no unresolved graph-valid competing assignment retains the origin; and
  6. no current valid sustained room-positive assertion remains in the origin.

  Its policy probability is

  $$
  r_z=\sum_{x,a}p_k(x,a)
  \mathbf{1}\{\operatorname{ReleaseSafe}(z;x,a)\}.
  $$

  Policy MUST release when finalized $r_z$ passes the `POL-015` threshold. When
  it does, historical ownership alone MUST NOT retain `active`.
- **POL-017:** Current valid positive evidence from a sustained room-occupancy
  sensor blocks automatic final-occupant release by graph departure, relocation,
  or count-accounted support by making `ReleaseSafe` false. Authoritative
  $N=0$/away and explicit reset MAY override it. Automatic recovery from a
  continuously stuck-on room sensor is intentionally unsupported. `EVID-011`
  and `EVID-018` define the exact event-time deadline at which a stable clear
  makes the prior positive historical. Crossing that deadline may re-evaluate
  $r_z$ but does not add evidence.
- **POL-018:** Each release decision MUST identify the causal episode or
  injective support matching used, $r_z$, the origin count marginal, active local
  evidence, competing assignments, risk threshold, and watermark/finalization
  state. Rejected and expired assignments MUST explain which evidence was
  missing or contradictory.

If evidence remains ambiguous, ownership remains held and diagnostics explain
what evidence is missing.

## Home Assistant Entity Requirements

- **ENT-001:** `binary_sensor.<zone>_active` is the default durable normal-output
  policy desired state. It turns on if and only if a distinct accepted fresh
  physical-node episode has $a_z$ at or above the activation threshold and
  authoritative $N>0$. It remains on while ownership is retained. It turns off
  if and only if finalized $r_z$ reaches the release threshold, authoritative
  $N=0$/away is asserted, or an explicit external operator reset is received.
  A nonzero count decrease alone cannot select a zone. Restore and reload
  preserve the state without a synthetic edge.
- **ENT-002:** `active` is policy intent, not a raw occupancy marginal, motion
  state, or actual controlled-device state. Actual light, switch, or other
  output state and manual changes MUST NOT feed inference or `active`. A default
  automation follows both `active` edges. A manual output-off while `active`
  remains on is respected until a later `active` edge; advanced consumers MAY
  opt into `ENT-004` when they deliberately want accepted fresh evidence to
  reassert an output. Explicit reset is an external policy override, not a
  posterior event; this contract does not prescribe its service transport.
- **ENT-003:** `binary_sensor.<zone>_prelight` is the other default per-zone
  entity. It is a bounded prediction lease that expires and cancels independently
  under `PRED-006`. The lease itself MUST NOT feed occupancy, movement,
  `active`, policy, or route learning. A later finalized graph-valid observed
  movement remains eligible for learning whether or not `prelight` was on.
- **ENT-004:** `event.<zone>_arrival` is optional and disabled by default. It
  emits event type `acquired` when a distinct accepted fresh physical-node
  episode changes `active` from off to on. It MAY emit event type `refreshed`
  when another distinct accepted fresh episode reaches the same $a_z$ threshold
  while `active` remains on. `refreshed` is not caused by actual output state;
  consumers opt into it when they deliberately want later accepted evidence to
  reassert a manually disabled output.
- **ENT-005:** Each arrival event carries zone, event type, the immutable
  physical-node episode/evidence ID assigned at episode creation, $a_z$, accepted
  event timestamp, and a machine-readable policy reason. Emission is deduplicated
  by episode/evidence ID. Duplicate callbacks or alias edges in the same episode,
  timer-only evaluation, bootstrap, restore, reload, count-only control,
  prediction, or movement finalization without a new accepted fresh target
  episode MUST NOT emit an arrival event. The event reports acquisition
  acceptance at that update and does not claim a finalized movement assignment.
- **ENT-006:** `binary_sensor.home_active` is the pure logical OR of current
  per-zone `active` states and adds no hysteresis. It is aggregate policy intent;
  off is not proof of physical vacancy.
- **ENT-007:** `binary_sensor.predictive_controls_problem` is a default
  diagnostic-only entity using Home Assistant problem semantics. It MUST NOT
  alter inference or policy and exposes only bounded reason codes and affected
  sources. Its initial reasons are exactly:

  1. `association_overload` while work exceeds the declared `MOVE-020` envelope
     and an exact update remains incomplete; clear after exact work drains and
     processing returns inside the envelope;
  2. `invalid_authoritative_count` while the latest count input cannot produce
     an accepted integer from zero through five and count-driven inference is
     suspended; clear on the next valid accepted count; and
  3. `restore_rejected` after target state is atomically rejected; clear after
     successful safe bootstrap and a valid target-state save.

  Historical or rejected events remain in audit and do not keep the entity on
  after their active condition clears. Sensor-health, rolling-latency, or other
  reasons require their own exact specification and calibration before addition.
- **ENT-008:** The following diagnostic sensors are optional and disabled by
  default: `sensor.<zone>_occupancy_probability` exposes the current marginal as
  a percentage; `sensor.<zone>_arrival_supported_probability` exposes $a_z$ for
  the current distinct fresh target episode and is unavailable when none exists;
  `sensor.<zone>_release_safe_probability` exposes current finalized $r_z$ for a
  held zone with explicit finalization availability and is unavailable when not
  meaningful; and `sensor.authoritative_occupant_count` exposes the current
  valid control and is unavailable while invalid. Complete provenance remains in
  bounded panel, status, and audit surfaces. `active` has no occupancy device
  class; the problem entity uses the problem device class.
- **ENT-009:** The default entity surface is `active` and `prelight` per zone,
  `home_active`, and `predictive_controls_problem`. Arrival events and probability
  sensors are disabled by default. Legacy aggregate list, path, and confidence
  entities are compatibility diagnostics disabled by default for new installs.
  There is no third default per-zone binary sensor.
- **ENT-010:** At target cutover, legacy projections remain for at least one full
  released version: `keep_on` aliases `active`; `activation_plausible` retains
  the short accepted-arrival lease; `prelight_plausible` aliases `prelight`; and
  `home_keep_on` aliases `home_active`. Existing entity-registry rows remain
  usable, while new installs receive legacy entities disabled by default during
  compatibility. Legacy removal is a separately reviewed breaking change after
  the compatibility release and migration evidence, not automatic cleanup.

## Observability

Wrong output must be reconstructable without enabling verbose logging before an
incident.

- Retain policy decisions and complete event context for up to the preceding 12
  hours within the entry and compressed-context bounds in `POL-013`.
- Record pre/post occupied and count marginals, $a_z$, $r_z$, fresh and asserted
  evidence, movement alternatives and dispositions, unresolved factor-graph
  assignments, endpoint tokens, deadlines and watermark, injective support
  matchings, latch transitions, prediction leases, learned route
  prefix/backoff/support, and performance counters.
- Keep retained context losslessly compact so routine audit persistence does not
  dominate callback memory or Home Assistant Store size.
- Expose the configured bounds, retained compressed bytes, entry count, and
  actual oldest/newest timestamps so truncated coverage is explicit.
- Distinguish fresh acquisition corroboration from still-asserted release safety.
- Expose rejected alternatives and evidence needed for promotion.
- Expose repeated rejected positive observations and low-confidence pulse
  patterns for proactive review without expanding compressed contexts.
- Persist enough recent audit state across ordinary restart and reload.
- Live Home Assistant diagnosis remains read-only through approved deployment
  tooling.
