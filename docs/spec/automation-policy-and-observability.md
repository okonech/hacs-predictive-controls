# Automation Policy and Observability

## Public Entity Contract

- `activation_plausible` is a short authorization for a fresh local turn-on.
- `keep_on` is a conservative asymmetric-risk decision retained until supported
  release. It is not a direct projection of one occupancy marginal.
- `prelight_plausible` is an optional prediction lease, never occupancy evidence.
- Diagnostic confidence, paths, thresholds, and reasons are not required by
  ordinary room automations.

## Risk Policy

The project treats automation errors asymmetrically:

- False activation is controlled with fresh local evidence and whole-house
  arrival-support probability.
- False release is controlled by retaining trusted ownership until resolved
  posterior support accounts for every occupant outside the held zone.

Elapsed time, low marginal, posterior competition, local clear, unavailable
state, unrelated remote activity, restart, or reload MUST NOT alone change
`keep_on` from on to off. A high empty-room posterior MAY authorize release only
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

Activation is authorized when $a_z$ passes the calibrated false-activation risk
threshold. Occupied marginal, increase, source, route, and competition values
remain decomposed diagnostics of this one posterior event, not independently
selected probability maxima.

A fresh local detection with coherent graph-arrival assignment is the ordinary
fast path. It SHOULD authorize activation unless count, local, ordering, or
competing-assignment mass keeps $a_z$ below the risk threshold.

- **POL-001:** Prediction alone cannot activate.
- **POL-002:** One physical entity cannot corroborate itself through repeated
  episodes or aliases.
- **POL-003:** Fresh evidence in an already held zone need not emit another pulse
  unless consumer-visible reacquisition is required.
- **POL-004:** Threshold changes require generic replay evidence and
  specification review.
- **POL-019:** `activation_plausible` MUST be derived from $a_z$ and one shared
  threshold calibrated by declared sensor, role, or occupancy-behavior profile.
  It MUST NOT conjoin unrelated marginal maxima as if they were one hypothesis.
- **POL-005:** For a valid graph-backed local detection, the integration SHOULD
  compute and publish its in-memory activation state within 50 ms of callback
  receipt and MUST complete within 100 ms under the supported workload. This
  budget excludes downstream Home Assistant scheduling and physical device
  latency, which the integration does not control. When a trustworthy source
  event timestamp exists, diagnostics SHOULD also report raw-detection-to-public-
  state latency against the same 50 ms preferred and 100 ms hard targets.
- **POL-006:** Exceeding the preferred 50 ms target is diagnostic. Exceeding the
  100 ms hard budget MUST be recorded and MUST NOT turn an otherwise valid
  activation into a rejection.

## Keep-On Ownership

Resolved graph or interval-censored departure, confirmed strict relocation, and
count-accounted exclusion are admissible ways to support one common posterior
release event. They are not separate policy paths with separately selected
threshold conjunctions. Authoritative $N=0$/away and explicit reset are the only
categorical overrides.

- **POL-007:** Trusted activation sets ownership.
- **POL-008:** Local clear, elapsed time, low marginal, and unrelated activity
  cannot release ownership by themselves. They MAY contribute to a release only
  when the resulting augmented posterior satisfies `ReleaseSafe`.
- **POL-009:** Only `ReleaseSafe`, authoritative $N=0$/away, or explicit reset
  may release ownership. A nonzero authoritative count decrease updates the
  posterior through `MODEL-017` through `MODEL-021` but cannot choose a held zone
  to release.
- **POL-010:** A graph departure assignment is admissible outside support only
  when its joint mass also places zero occupants in the origin. Assignment and
  final-origin confirmation MAY arrive on different accepted updates inside the
  same retained fixed-lag graph. Policy MUST sum the joint qualifying mass and
  MUST NOT combine maxima, thresholds, or evidence from unrelated, stale, or
  expired episodes. Release waits for the qualifying assignments to finalize.
- **POL-011:** Every accepted and rejected release records gates, evidence IDs,
  prior latch, resulting latch, and reason.
- **POL-012:** Compatible restart or reload preserves ownership without synthetic
  activation.
- **POL-013:** Retained policy audit covers up to the preceding 12 hours, bounded
  by 8,192 decision entries and 12 MiB of compressed observation context so a
  sensor storm cannot create an unbounded Store file. Complete context MAY use
  a lossless compressed representation in memory, persistence, and transport,
  but restore MUST validate and reconstruct the same context atomically.
- **POL-014:** Reliability diagnostics MAY aggregate unique positive trigger
  events that policy rejected while ownership remained off, plus repeated short
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
  it does, historical ownership alone MUST NOT retain `keep_on`.
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
- Distinguish fresh activation corroboration from still-asserted release safety.
- Expose rejected alternatives and evidence needed for promotion.
- Expose repeated rejected positive observations and low-confidence pulse
  patterns for proactive review without expanding compressed contexts.
- Persist enough recent audit state across ordinary restart and reload.
- Live Home Assistant diagnosis remains read-only through approved deployment
  tooling.
