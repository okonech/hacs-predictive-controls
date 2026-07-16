# Change Governance

Every reported regression and every proposed change to inference, movement,
prediction, policy, thresholds, map semantics, or persistence uses the
repository skill at
`.github/skills/predictive-controls-regression-review/SKILL.md`.

## Requirements

- **GOV-001:** State observed public behavior, expected public behavior, and
  governing requirement IDs before proposing a fix.
- **GOV-002:** Separate verified evidence from assumptions and identify the
  controlling layer.
- **GOV-003:** Preserve a diagnosed incident with the smallest permanent test
  containing material event order, timings, states, probabilities, and gates.
- **GOV-004:** The regression MUST assert public `active` or `prelight` state, or
  an `arrival` event when that optional contract controls the behavior. Internal
  assertions are supplementary. During compatibility migration, a regression
  MAY additionally assert the corresponding legacy projection.
- **GOV-005:** Confirm the regression fails for the diagnosed reason before the
  production edit. If it cannot reproduce, improve diagnostics instead of
  guessing.
- **GOV-006:** State whether a change modifies observation likelihood, duration
  likelihood, transition prior, posterior, context, prediction, policy, or
  persistence. Do not hide a change in the wrong layer.
- **GOV-007:** For model changes, compare at least two approaches for
  probabilistic coherence, temporal correlation, multi-occupant behavior,
  missed events, sensor faults, persistence, calibration, and runtime.
- **GOV-008:** Reject room-specific conditions or constants, event count as
  independent evidence, prediction feedback, policy-to-posterior feedback,
  timer-only release, and automation workarounds for predictor defects.
- **GOV-009:** Calibration changes require a generic replay corpus, incident
  regressions, boundary tests, and documented before/after public effects.
- **GOV-010:** Run the focused regression immediately after the first production
  edit, then related suites and every repository quality gate.
- **GOV-011:** Amend and agree on the specification first when desired behavior
  conflicts with it.
- **GOV-012:** Every optimized inference operator MUST match a simple brute-force
  exact oracle on randomized small maps, all supported counts feasible on those
  maps, count changes, and adversarial event sequences before performance
  results may be accepted.

## Required Scenario Families

The retained suite MUST cover these orthogonal behavior families:

1. **Correlated observation:** episode emissions and sustained confidence are
  bounded and independent of callback/evaluation frequency; rapid toggles and
  aliases from one node remain one episode and cannot manufacture corroboration,
  movement, activation, release, or learning. A clear adds a false-negative-
  aware emission and never subtracts historical positive evidence from a later
  occupancy state.
2. **False-negative safety:** local clear, silence, low marginal, and periodic
  evaluation alone produce no `active -> off` edge; quiet occupants remain
  protected without wall-time diffusion.
3. **Current-positive safety:** a valid sustained room-positive assertion
  protects a long-held room from graph departure, count-accounted exclusion,
  another occupant's shared-corridor route, and interleaved paths.
4. **Stuck-on tradeoff:** a continuously asserted sustained room sensor blocks
  automatic `active` release and produces actionable health diagnostics until
  authoritative count/away, explicit reset, or device recovery.
5. **Ordinary graph movement:** directly observed adjacent arrival activates and
  final departure releases when source, destination, final-origin, local
  evidence, and competition gates agree.
6. **Delayed causal confirmation:** quick room entry and exit through an already
  asserted transition gate remains unresolved while local positive evidence is
  current, then may release across later causally linked updates after stable
  clear, assignment finalization, and qualifying release-event probability.
  Incompatible order, timing, topology, or evidence provenance cannot produce
  the same release.
7. **Multi-occupant crossings:** one open transition interval may support
  distinct crossings up to the authoritative count when each has a unique
  endpoint event and feasible predecessor multiplicity; one endpoint event
  never moves two occupants, and one departure from a shared source retains
  ownership for anyone remaining. Count reconciliation and same-zone
  multiplicity MUST be exercised for every supported count from zero through
  two, including the maximum count. The richest routine and incident-derived
  replay corpus MUST use the primary two-occupant profile; other counts cover
  count transitions, boundaries, and scale without receiving weaker assertions.
  Tests MUST cover $0\to1$, $1\to2$, $2\to1$, $1\to0$, multi-step changes,
  boundary-conditioned arrival/departure, and exchangeable unlocated fallback.
  Only $N=0$ may categorically release every held zone.
8. **Missed movement:** strong independent destination evidence and exact
  count-accounting may confirm strict relocation; one isolated or flapping
  remote source, contextless mass, or prediction cannot.
9. **Posterior support-event policy:** activation uses the forward probability of
  `ArrivalSupported`; release uses finalized $P(\operatorname{ReleaseSafe})$.
  Resolved departure, strict relocation, and count-accounting contribute to the
  same release event. Local clear, low marginal, `unlocated` mass, one remote
  flap, unavailable state, and prediction each fail release in isolation.
10. **Ordering and restart:** in-lag out-of-order input recomputes the retained
  graph; input at or behind the watermark is rejected. Forward posterior,
  unresolved factors, endpoint tokens, deadlines/watermark, support-event
  marginals, count sequence, and policy hysteresis round-trip deterministically
  without synthetic edges or probability loss.
11. **Prediction separation:** independent leases coexist and cancel
  independently; repeated routes improve only compatible graph-valid
  predictions and never independently set or clear `active`, move occupancy, or
  become route-learning evidence. Finalized observed movement remains eligible
  for learning regardless of prior `prelight` state.
12. **Latency and bounds:** the reference workload is the 16-zone, 17-node,
  23-entity map with the existing deterministic 10,000-accepted-update,
  one-millisecond-spacing replay plus separate correlated-burst, maximum-lag,
  out-of-order, and overload traces, measured at the maximum supported count
  $N=2$. The run MUST preserve every occupancy configuration and meet the
  preferred 50 ms and hard 100 ms callback budgets inside the declared
  `MOVE-020` envelope.
    Results MUST report p50/p95/p99/max callback latency, candidate operations,
    configuration count, peak memory, active episode and unresolved-assignment
    maxima, overload count, policy-audit size, persistence size, and
    serialize/restore/startup time. The replay MUST include all physical-node
    episodes active, correlated flap bursts, maximum configured route duration,
    maximum accepted lateness, and safe overload behavior. Numeric memory,
    graph-size, persistence, and startup ceilings MUST be approved from measured
    prototype results before production inference is migrated to this model.

## Calibration

Observation likelihoods, false-positive and false-negative rates, physical-node
episode correlation and validity bounds, transition priors, graph timing,
duration and stable-clear parameters, maximum accepted lateness, asymmetric
policy loss ratios, thresholds, and lease durations are coupled calibration.
Changing one value requires reviewing every gate that consumes the resulting
posterior or movement evidence and replaying the generic scenario corpus.
Event-count windows, room-specific inactivity timers, and incident-specific
thresholds are not valid calibration parameters.

## Completion Criteria

- The expected behavior follows from named requirements.
- Evidence and assumptions are separated.
- The incident fails at the public contract before the fix.
- The fix is generic and belongs to the controlling layer.
- Inverse, multi-occupant, sensor-fault, missed-event, ordering, and restart
  cases are covered where relevant.
- Full Python tests with 100% branch coverage, Ruff, mypy, frontend tests, and
  benchmark gates pass.
- Optimized inference matches the exact oracle under `GOV-012`, and reported
  performance uses the same semantics rather than a pruned or simplified mode.
- Documentation, diagnostics, persistence, and changelog are updated when their
  contracts change.
