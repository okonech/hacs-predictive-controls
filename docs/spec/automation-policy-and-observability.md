# Automation Policy and Observability

## Public Entity Contract

- `activation_plausible` is a short authorization for a fresh local turn-on.
- `keep_on` is conservative ownership retained until supported release.
- `prelight_plausible` is an optional prediction lease, never occupancy evidence.
- Diagnostic confidence, paths, thresholds, and reasons are not required by
  ordinary room automations.

## Risk Policy

The project treats automation errors asymmetrically:

- False activation is controlled with fresh local evidence and whole-house
  plausibility.
- False release is controlled by retaining trusted ownership until positive
  departure or relocation evidence, authoritative count/away, or explicit reset.

Elapsed time, low marginal, posterior competition, local clear, unrelated remote
activity, restart, or reload MUST NOT alone change `keep_on` from on to off.

## Activation

Activation requires occupied support and increase gates plus at least one valid
support route: coherent graph arrival, prior unlocated mass, independent local
corroboration, strict relocation, or eligible reacquisition after a recorded
false release.

A fresh local detection with coherent graph-arrival evidence is the ordinary
fast path. It SHOULD authorize activation unless specific contradictory evidence
exists, such as an impossible occupant-count assignment, incompatible local
evidence, invalid event ordering, or a substantially stronger competing path.

- **POL-001:** Prediction alone cannot activate.
- **POL-002:** One physical entity cannot corroborate itself through repeated
  episodes or aliases.
- **POL-003:** Fresh evidence in an already held zone need not emit another pulse
  unless consumer-visible reacquisition is required.
- **POL-004:** Threshold changes require generic replay evidence and
  specification review.
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

Permitted release causes are:

1. path-specific graph departure carrying the final supported occupant out;
2. confirmed strict relocation after missed movement;
3. authoritative count reduction or away state;
4. explicit reset.

- **POL-007:** Trusted activation sets ownership.
- **POL-008:** Local clear, elapsed time, low marginal, and unrelated activity
  cannot release ownership.
- **POL-009:** Only the release causes above may release ownership.
- **POL-010:** Graph departure alone is not enough to release ownership. The
  same update MUST also support that the final occupant is no longer in the
  origin, using origin marginal, remaining count, or equivalent posterior
  evidence.
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

If evidence remains ambiguous, ownership remains held and diagnostics explain
what evidence is missing.

## Observability

Wrong output must be reconstructable without enabling verbose logging before an
incident.

- Retain policy decisions and complete event context for up to the preceding 12
  hours within the entry and compressed-context bounds in `POL-013`.
- Record pre/post occupied and count marginals, fresh and asserted evidence,
  movement alternatives and dispositions, pending departures, policy gates,
  latch transitions, prediction leases, learned route prefix/backoff/support,
  and performance counters.
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
