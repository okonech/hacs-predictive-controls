# INC-2026-08-23 stale interaction recovery

## Public contract

- Affected outputs: `binary_sensor.alex_office_active`,
  `binary_sensor.shaila_office_active`, and
  `binary_sensor.upstairs_bathroom_active`.
- Actual behavior: stale retained values from mapped Home Assistant event
  entities were accepted as fresh physical interaction presses when the event
  entities became available after deployment. Shaila Office and Upstairs
  Bathroom falsely acquired. An unavailable alias then replaced Alex Office's
  still-asserted mmWave context, and Alex Office falsely released at
  `2026-08-23T19:38:22.962581+00:00`.
- Expected behavior: a retained event timestamp older than its state-change
  callback is not a new physical interaction and emits no acquisition or
  refresh. One unavailable interaction alias invalidates only that physical
  node's authority; it cannot erase a distinct, currently asserted same-zone
  stay episode. Alex Office remains active, while Shaila Office and Upstairs
  Bathroom remain inactive.

## Retained live evidence

Read-only evidence came from `ha-entity-states.sh`, `ha-history-states.sh`, and
the `predictive-controls-status` WebSocket lookup.

- Authoritative count was `2` and available.
- Alex Office mmWave asserted at `2026-08-23T19:09:26.138958+00:00`, after Top
  of Staircase asserted at `19:09:17.250589+00:00`; the staircase cleared at
  `19:09:33.708108+00:00`. At the incident query the Alex episode remained
  `asserted`, reliable at `0.75`, with no health warning.
- Shaila Office and Upstairs Bathroom physical sensors were clear.
- At `19:23:01.242662+00:00`, Shaila's retained scene 001 value from
  `2026-08-21T08:16:35.309+00:00` was accepted as `local_interaction`. Belief
  moved from `0.05` to `0.9999999999999065`, and public policy acquired.
- Five more stale bathroom scene values were accepted from
  `19:23:01.516623+00:00` through `19:23:01.562480+00:00`. The first moved
  belief from `0.06494706545543413` to `0.9999999999999065` and acquired the
  bathroom; the others falsely refreshed it.
- Alex's retained scene values from `2026-07-01T09:07:28.501+00:00` and
  `2026-08-20T06:14:11.299+00:00` falsely refreshed at
  `19:23:01.627256+00:00` and `19:23:01.633659+00:00`. Scene 003 was `unknown`
  at `19:23:01.640059+00:00`.
- At `19:41:42.996920+00:00`, Alex belief was `0.19657446637658177` in
  `unavailable` context and inactive despite the asserted mmWave. Shaila and
  the bathroom remained active at `0.679029556766388` and
  `0.6791013450166011` in `cleared_without_outward` context.
- The traversal frontier and count-conflict list were empty. Restore status was
  `restored`.

The retained regression uses every material physical edge, stale event value,
callback timestamp, profile, reliability, count, and public expectation above.

## Controlling layers and disconfirming check

- Layers: Home Assistant event normalization, physical-node availability, zone
  belief, and policy.
- Leading cause: timestamp-valued interaction state changes are classified as
  `pressed` without proving that the state timestamp belongs to that callback;
  zone-wide unavailable handling then clears a distinct asserted episode.
- Disconfirming check: unchanged code would refute the cause if the exact stale
  callbacks neither acquired the clear zones nor made the asserted Alex zone
  release. The retained public regression instead fails on those outputs.