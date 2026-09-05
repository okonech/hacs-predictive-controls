# INC-2026-09-05-1707Z: Office Light Reverted After Correct Active Edge

Status: Hardened blocked working specification - no Predictive Controls failure reproduced

Hardening: exactly three adversarial critique-and-rewrite passes completed

Affected layers: `PUBLICATION`, `AUTOMATION`, `EXTERNAL`

Authority: `REQ-POLICY-001`, `REQ-POLICY-005`, `REQ-PUBLIC-001`,
`REQ-PUBLIC-003`, `REQ-GOV-002`, and `REQ-GOV-006` in `SPECIFICATION.md`.

## Objective

Preserve the separately reported office incident and determine its controlling
layer without inventing Predictive Controls behavior. Do not change model or
automation semantics unless a reproducible failure shows that an owned contract
was violated.

## Evidence Record

All runtime facts came from approved read-only Home Assistant history, trace,
registry, and integration-diagnostic scripts in the sibling Homelab repository.

- Top-stair motion asserted at `2026-09-05T17:07:00.146Z`.
- Office raw motion asserted at `17:07:03.733305Z`.
- `binary_sensor.alex_office_active` asserted at `17:07:03.735Z`.
- The office automation verified the light was off and issued
  `light.turn_on` at `17:07:03.740Z`; its trace completed without an action
  error about 1.6 seconds later.
- The light acknowledged `on` at `17:07:05.342Z` and changed back to `off` at
  `17:07:09.857Z` while raw motion and public `active` remained on.
- The retained logbook attributes the `17:07:05.342297Z` `on` state to the
  automation domain and gives the `17:07:09.857244Z` `off` state no Home
  Assistant domain, service, user, event, or context identity. The exact-window
  trace inventory contains no second office automation run or other retained
  writer for the off edge.
- None of the switch's three Central Scene entities changed in the incident
  window, so Home Assistant retained no ordinary paddle scene for the off edge.
- The exact authoritative count at the incident frontier was not retained. The
  classification replay therefore checks both positive supported counts, one
  and two, without claiming either as observed fact.
- The switch reported no overheat, Z-Wave node 282 was ready/listening, its
  auto-off timer was `0`, and diagnostics reported zero dropped transmit
  commands. RSSI was approximately `-83 dBm` and two historical response
  timeouts were present, but neither proves why this command reverted.
- A later read-only node snapshot also reports firmware `2.2.0`, disabled
  built-in presence control, unprotected local and RF control, no overheat,
  zero dropped transmit commands, and two cumulative response timeouts. These
  current values constrain but do not prove the device configuration at the
  incident frontier.

## Diagnosis And Disconfirming Check

Predictive Controls satisfied its public contract: the graph sequence produced
the required office `off -> on` edge and retained it. The automation consumed
that edge and the device acknowledged the command. The lowest demonstrated
failure is therefore `EXTERNAL` after actuation. The context-free off state and
absence of another automation identify a device-originated Z-Wave state report,
but retained data cannot distinguish a local load action without a Central Scene
event, a firmware action, or an unsolicited/incorrect report.

The cheapest model disconfirming check is an exact public engine replay of the
top-stair and office edges followed by advancement through `17:07:09.857Z`. It
must emit one office `acquired` event, emit no office `released` event, and
remain active. A failure would reopen Predictive Controls diagnosis. A passing
replay confirms that this sensor sequence cannot reproduce the reported light
reversion inside the model.

## Scope

- Add one separately named incident scenario preserving the exact sensor order,
  public acquisition edge, and retained active state.
- Record the downstream light transition as external evidence, not model input.
- Keep this working specification until the external cause is identified or the
  incident is explicitly closed as non-reproducible.

## Non-Goals

- Do not feed light, switch, automation, or actuator state into occupancy belief.
- Do not emit repeated `active` edges while public state remains on.
- Do not synthesize `refreshed` without a distinct eligible physical episode.
- Do not add an automation that fights intentional manual-off behavior.
- Do not attribute the reversion to Z-Wave signal quality or a competing writer
  without evidence.

## Invariants And Event Ordering

1. The top-stair episode precedes and authorizes the office episode.
2. Office acquisition publishes once in deterministic event-time order.
3. Advancing through the observed light-off timestamp cannot release the office
   while its stay-presence episode remains asserted.
4. Actuator output state is not occupancy evidence.
5. A retry or reassertion requires a separately specified automation or hardware
   contract and must preserve intentional manual-off behavior.

## Design And Alternatives

No production change is authorized. Add a classification scenario at
`tests/incidents/test_inc_2026_09_05_1707z_office_light_reverted_after_correct_active_edge.py`
that proves the current public model behavior using the recorded timestamps. The
scenario uses the smallest map needed to preserve the material graph order: a
top-stair transition node adjacent to one stay-presence office node. It does not
model actuator state or reproduce unrelated full-map activity.

Rejected alternatives:

- Re-emit `active` when a light turns off: violates state-edge semantics and
  feeds actuator state into the wrong ownership layer.
- Treat the continuously asserted office sensor as repeated evidence: violates
  episode deduplication and refresh identity.
- Add an unconditional automation retry: risks overriding intentional manual
  control and lacks a diagnosed retry boundary.
- Tune Z-Wave or replace hardware from two historical timeouts: unsupported by
  the incident evidence.

## Compatibility, Operations, And Rollback

The retained scenario changes no runtime behavior, persistence, schema, map,
entity, or automation. No rollout or rollback is needed. Further investigation
requires device or integration evidence that can distinguish a local load-off,
unsolicited Z-Wave report, protection action, or another writer.

## Implementation Phases

### Phase 1: External-Cause Classification Artifact

Add the exact incident scenario and run:

```text
.venv/bin/pytest --no-cov -q tests/incidents/test_inc_2026_09_05_1707z_office_light_reverted_after_correct_active_edge.py
```

Expected unchanged-code result: pass, with one office `acquired` event and office
policy still active and no `released` event at the observed light-off timestamp.
This documents correct model behavior while external actuation failed; it is not
red proof of a Predictive Controls defect and therefore does not satisfy the
`REQ-GOV-002` prerequisite for a model repair. It is the separately retained
classification artifact required for this report and the stop condition for
model implementation. Actual result: `2 passed` for authoritative counts one and
two against unchanged production behavior.

### Phase 2: External Evidence

Blocked pending a reproducible device-level cause. Use only approved read-only
Home Assistant evidence. Retained logbook context, exact-window traces, scene
history, and current node configuration exclude a Home Assistant writer,
configured auto-off/presence behavior, current protection, and a recorded
Central Scene event. The next evidence must capture the Z-Wave command/value
traffic at recurrence to distinguish a local load action without a scene event,
a firmware action, or an unsolicited/incorrect report. Any eventual downstream
change belongs in the Homelab repository after a separate red/green acceptance
probe and must not override intentional manual off without an explicit contract.

## Tracking

| Phase | Status | Completed evidence | Next executable step |
| --- | --- | --- | --- |
| External-cause classification artifact | Complete | Exact focused command passed both positive-count cases with one acquisition, no release, and retained office active state. | None. |
| External evidence | Blocked | Correct active edge, successful turn-on trace, context-free device-originated off report, no competing trace or Central Scene event, and disabled current auto-off/presence/protection settings verified live. | Capture node 282 Z-Wave command/value traffic if the failure recurs. |

## Acceptance Gates

- The separately named incident scenario preserves the exact sensor order and
  proves one office acquisition, no model release, and retained active state
  through the light-off timestamp.
- The scenario remains in `tests/incidents/` because repository incident
  governance requires one artifact per report; its passing unchanged-code result
  is explicitly classification evidence, not authorization for a repair.
- No Predictive Controls production code, public contract, calibration,
  persistence, or automation changes are made for this unresolved external
  failure.
- The focused scenario, complete incident corpus, and `git diff --check` pass.
- This working specification remains until the external issue is resolved or
  explicitly closed; it must not be merged into canonical behavior as a model
  repair.
