# Predictive Controls

Predictive Controls is a Home Assistant custom integration that turns a graph of
motion and presence sensors into stable zone-level automation entities. Its
first use case is fast, accurate lighting through one `active` entity per zone.

## Design and Current Model

[`SPECIFICATION.md`](SPECIFICATION.md) is the sole source of product and model
requirements. Code, tests, documentation, and historical changelog entries must
remain consistent with it.

The integration now runs graph-local per-zone probability filters, bounded
anonymous traversal context, and hysteretic probability-driven `active`
decisions. Home Assistant Store schema 7 can import schema-6 state once and can
conservatively migrate `zone-belief-v2`; current state persists as
`zone-belief-v3`. Unsafe v2 traversal, prediction, and source-free authority are
discarded. Older `zone-belief-v1` inference is rejected and rebuilt from current
sensor states.
Historical changelog entries may still describe the retired architecture.

## Installation

### HACS custom repository

1. In HACS, open Integrations -> Custom repositories.
2. Add this repository URL as an Integration.
3. Install Predictive Controls.
4. Restart Home Assistant.
5. Add the integration from Settings -> Devices & services.

## Configuration

The integration stores its node map in config-entry options. Use the Predictive
Controls sidebar panel or Configure on the integration entry to edit it.

The map groups raw entity aliases into physical nodes, assigns nodes to zones,
and declares physical adjacency. Current maps may use role names such as
`transition_gate`, `room_occupancy`, `subzone_occupancy`, and `anchor_sensor`,
plus occupancy behaviors `transient`, `sustained`, `sticky`, and `ambiguous`.
Profile assignment is capability-based: transient gates use `transition_fast`;
room and subzone motion/PIR sensors use `stay_pir` even when their zone is
sticky; true presence/mmWave sensors and reviewed sticky non-motion nodes use
`stay_presence`; and configured household boundaries use `entry_boundary`.
Runtime logic must not infer a profile from a room name.

Example map:

```yaml
nodes:
  entry:
    label: Entry
    zone: entry
    role: transition_gate
    occupancy_behavior: transient
    reliability: 0.98
    route_prior_weight: 1
    entities:
      motion: binary_sensor.example_entry_motion
    adjacent:
      - hallway
  hallway:
    label: Hallway
    zone: hallway
    role: transition_gate
    occupancy_behavior: transient
    entities:
      motion: binary_sensor.example_hallway_motion
    adjacent:
      - entry
      - kitchen
  kitchen:
    label: Kitchen
    zone: kitchen
    role: room_occupancy
    occupancy_behavior: sustained
    entities:
      motion: binary_sensor.example_kitchen_motion
    adjacent:
      - hallway
```

Physical adjacency is undirected and should be declared reciprocally. Directed
`transition_seconds` values may override timing for an existing edge; a missing
override uses the shared default rather than the reverse edge's value.

The authoritative occupant count supports 0 through 2. Count 0 is categorical
nobody-home. Positive count supplies anonymous context and never identifies a
person.

## Public Entities

The normal automation surface is intentionally small:

| Entity                                      | Meaning                                                  |
| ------------------------------------------- | -------------------------------------------------------- |
| `binary_sensor.<zone>_active`               | Desired normal-output state for the zone                 |
| `binary_sensor.home_active`                 | Logical OR of per-zone `active` states                   |
| `binary_sensor.predictive_controls_problem` | Diagnostic integration problem state; never policy input |

Optional probability and path diagnostics are disabled by default. The current
surface keeps the stable `active` and `home_active` IDs, adds a
deduplicated `refreshed` type on optional `event.<zone>_arrival` for accepted
evidence while already active, and exposes zone belief, authorization reason,
release dwell, sensor health, and bounded policy audit diagnostics.

`active` is policy intent, not actual light state. A controlled light or switch
must never feed occupancy inference.

## Automation Example

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.living_room_active
    to: "on"
    id: active
  - trigger: state
    entity_id: binary_sensor.living_room_active
    to: "off"
    id: inactive
actions:
  - choose:
      - conditions: [{ condition: trigger, id: active }]
        sequence:
          - action: light.turn_on
            target: { entity_id: light.living_room }
      - conditions: [{ condition: trigger, id: inactive }]
        sequence:
          - action: light.turn_off
            target: { entity_id: light.living_room }
mode: restart
```

Mature predictions are internal authorization for this same `active` entity;
there is no separate prelight control or prediction-driven service action.
Automations should consume public desired-state edges rather than duplicate map,
probability, authorization, or timing logic.

## Sensor Timing

Transition sensors should generally use the shortest reliable hardware reset,
initially 5-15 seconds when supported. Stay-room PIRs should start around 30
seconds and be adjusted only from measured false-clear behavior. True-presence
sensors should report stable absence promptly. A continuously asserted stay
sensor remains strong bounded local evidence; its ability to authorize movement
to neighboring zones still expires.

Hardware timing and software profiles are calibrated together. A long-open
hallway remains bounded traversal context and may authorize distinct fresh room
episodes; it is never counted repeatedly as new motion. See the specification
for behavior, calibration, rollout, and measurement requirements.

## Development

Create the Python environment and install the development dependencies declared
in `pyproject.toml`, then use these quality gates:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
npm run test:frontend
.venv/bin/python benchmarks/occupancy_performance.py \
  --events 100 \
  --output /tmp/predictive-controls-performance.json
```

The Python suite enforces 100% branch coverage. Routine benchmarks use 100
events, and every benchmark entry point must reject more than 1,000 events.

Reported behavior failures follow
`.github/skills/predictive-controls-regression-review/SKILL.md`: preserve the
observed public failure with exact timestamps, prove it against unchanged
behavior, review the generic proposal independently, then implement and run all
quality gates.

## Repository Documents

- [`SPECIFICATION.md`](SPECIFICATION.md): sole normative design authority.
- [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md): phased implementation, compatibility,
  validation, rollout, and backout plan for the v3 acquisition model.
- [`CHANGELOG.md`](CHANGELOG.md): historical release record.
- [`PERFORMANCE_RESULTS.json`](PERFORMANCE_RESULTS.json): latest checked-in
  performance artifact where applicable.
