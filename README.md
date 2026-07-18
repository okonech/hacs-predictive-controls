# Predictive Controls

Predictive Controls is a Home Assistant custom integration that turns a graph of
motion and presence sensors into stable zone-level automation entities. Its
first use case is lighting, while configured actions may call other Home
Assistant services.

## Design and Migration Status

[`SPECIFICATION.md`](SPECIFICATION.md) is the sole source of product and model
requirements. [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md) is the step-by-step AI
agent handoff for implementing those requirements; it is not a second design
authority.

The integration now runs graph-local per-zone probability filters, bounded
anonymous traversal context, and hysteretic probability-driven `active`
decisions. Store schema 7 reads schema-6 state once to seed public active state,
then persists only target-model state. Historical changelog entries may still
describe the retired architecture.

## Installation

### HACS custom repository

1. In HACS, open Integrations -> Custom repositories.
2. Add this repository URL as an Integration.
3. Install Predictive Controls.
4. Restart Home Assistant.
5. Add the integration from Settings -> Devices & services.

## Configuration

The integration stores its node map and action configuration in config-entry
options. Use the Predictive Controls sidebar panel or Configure on the
integration entry to edit them.

The map groups raw entity aliases into physical nodes, assigns nodes to zones,
and declares physical adjacency. Current maps may use role names such as
`transition_gate`, `room_occupancy`, `subzone_occupancy`, and `anchor_sensor`,
plus occupancy behaviors `transient`, `sustained`, `sticky`, and `ambiguous`.
The migration plan defines deterministic conversion to the target shared sensor
profiles; target logic must not infer a profile from a room name.

Example map:

```yaml
nodes:
  entry:
    label: Entry
    zone: entry
    role: transition_gate
    occupancy_behavior: transient
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
| `binary_sensor.<zone>_prelight`             | Optional bounded predictive-lighting lease               |
| `binary_sensor.home_active`                 | Logical OR of per-zone `active` states                   |
| `binary_sensor.predictive_controls_problem` | Diagnostic integration problem state; never policy input |

Optional probability and path diagnostics are disabled by default. The current
surface keeps the stable `active`, `prelight`, and `home_active` IDs, adds a
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
  - trigger: state
    entity_id: binary_sensor.living_room_prelight
    to: "on"
    id: prelight
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
      - conditions: [{ condition: trigger, id: prelight }]
        sequence:
          - action: light.turn_on
            target: { entity_id: light.living_room }
            data: { brightness_pct: 20 }
mode: restart
```

Remove the prelight branch when predictive lighting is not useful. Ordinary
automations should consume public desired-state edges rather than duplicate map,
probability, or timing logic.

## Sensor Timing

Transition sensors should generally use the shortest reliable hardware reset,
initially 5-15 seconds when supported. Stay-room PIRs should start around 30
seconds and be adjusted only from measured false-clear behavior. True-presence
sensors should report stable absence promptly while retaining a finite software
trust horizon.

Hardware timing and software profiles are calibrated together. A long-open
hallway remains bounded traversal context and may authorize distinct fresh room
episodes; it is never counted repeatedly as new motion. See the specification
for behavior and the migration plan for rollout and measurement steps.

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
- [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md): non-normative implementation and
  rollout sequence.
- [`CHANGELOG.md`](CHANGELOG.md): historical release record.
- [`PERFORMANCE_RESULTS.json`](PERFORMANCE_RESULTS.json): latest checked-in
  performance artifact where applicable.
