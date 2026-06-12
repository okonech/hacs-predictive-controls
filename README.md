# Predictive Controls

Predictive Controls is a Home Assistant custom integration for generic predictive automation. It learns first-order Markov transition probabilities from configured sensor nodes and exposes predicted next-node entities that normal Home Assistant automations can consume.

The first target use case is predictive lighting, but action configuration uses generic Home Assistant service calls so other domains can be added without redesigning the model.

## Installation

### HACS custom repository

1. In HACS, go to Integrations -> Custom repositories.
2. Add this repository URL as an Integration.
3. Install Predictive Controls.
4. Restart Home Assistant.
5. Add the integration from Settings -> Devices & services.

## Configuration

The integration stores its map and predictive action configuration in the Home Assistant config entry options. Use the Predictive Controls sidebar entry for the graphical editor, or Configure on the integration entry to edit both YAML documents.

The sidebar panel includes:

- a motion-entity list discovered from Home Assistant binary sensors;
- a drag-and-drop board for placing predictive nodes;
- an occupancy tab that visualizes configured zones by floor with live
  confidence and status;
- a connect mode for creating adjacency edges between nodes;
- a node inspector for labels, entity bindings, initial weights, and edge removal;
- an actions tab for generic Home Assistant service-call YAML;
- settings for transition learning window, binary prediction threshold, and
  expected occupant count.

The default map is intentionally generic:

```yaml
nodes:
  entry:
    label: Entry
    entities:
      motion: binary_sensor.example_entry_motion
    adjacent:
      - hallway
  hallway:
    label: Hallway
    entities:
      motion: binary_sensor.example_hallway_motion
    adjacent:
      - entry
      - kitchen
  kitchen:
    label: Kitchen
    entities:
      motion: binary_sensor.example_kitchen_motion
    adjacent:
      - hallway
```

Actions are generic service calls. The v1 examples use lights:

```yaml
actions:
  prelight_kitchen:
    when:
      predicted_node: kitchen
      min_probability: 0.6
    call:
      service: light.turn_on
      target:
        entity_id: light.example_kitchen
      data:
        brightness_pct: 35
```

## Occupancy Confidence

Predictive Controls also publishes derived occupancy-confidence entities from the
same node map. Each mapped node may define `floor`, `zone`, `role`, and
`occupancy_behavior` metadata. Roles such as `room_occupancy`,
`transition_gate`, `ambiguous_open_plan`, `subzone_occupancy`, and
`anchor_sensor` describe the kind of sensor or place. Occupancy behaviors tune
how confidence grows while evidence remains active and how quickly it decays:

- `transient`: pass-through areas such as hallways and stairs;
- `sustained`: normal rooms such as offices, kitchens, closets, and gyms;
- `sticky`: rooms where occupancy should remain trusted longer, such as living
  rooms or bathrooms;
- `ambiguous`: open-plan or overlapping areas that should rise more cautiously.

Maps may also include optional top-level `zones` metadata for display labels,
floor grouping, occupancy behavior, and visual placement in the occupancy tab.
If omitted, the panel derives zones from node `zone`, `floor`, `role`, and
`position` fields.

For each zone, the integration exposes:

- a confidence percentage sensor;
- a status sensor with `rejected`, `suspect`, `possible`, `probable`, or
  `confirmed`;
- a probable-occupancy binary sensor that turns on for `probable` and
  `confirmed` states;
- a possible-occupancy binary sensor that turns on for `possible`, `probable`,
  and `confirmed` states;
- a motion-plausible binary sensor that turns on when the zone is probably
  occupied, part of the active movement corridor, or predicted next;
- a predicted-next binary sensor and zone prediction-probability sensor for
  pre-lighting adjacent zones before a person arrives.

These entities are intended as an inference layer between raw motion sensors and
lighting automations. Existing predicted-node entities remain available for
compatibility.

The automation-facing aggregate entities are:

- `sensor.probable_inside_count` and `sensor.possible_inside_count`, derived
  from anonymous occupant tracks rather than named people;
- `binary_sensor.home_probable_occupancy` for whole-home occupied/vacant logic;
- `sensor.probable_occupied_zones`, `sensor.possible_occupied_zones`,
  `sensor.motion_plausible_zones`, and `sensor.active_movement_corridor`, each
  with the relevant zones in attributes;
- `sensor.predicted_next_zone` with per-zone prediction probabilities in
  attributes;
- `sensor.occupancy_explanation` for a short human-readable summary.

Room automations should normally use raw local motion for immediate turn-on,
zone probable occupancy for sustained keep-on behavior, zone motion plausibility
to block non-adjacent noisy triggers, and zone predicted-next entities for soft
pre-lighting.

### Occupancy Tracking Architecture

Occupancy confidence is modeled as anonymous multi-person tracking over the
configured adjacency graph. The system does not try to identify a specific
person. Instead, it asks which set of occupied zones best explains the recent
sensor evidence.

The implementation is split into small modules:

- `occupancy_graph.py`: derives a zone-level graph from node adjacency and
  answers neighbor, movement-corridor, and shortest-path questions;
- `occupancy_scoring.py`: contains pure confidence math for sensor-on evidence,
  clear events, sustained active evidence, passive time decay, and conflict
  decay;
- `occupancy_tracker.py`: keeps zone state, active sensor evidence, recent
  events, and anonymous occupant-track reconciliation;
- `confidence.py`: compatibility facade used by existing runtime, entity, and
  test imports.

When `expected_occupants` is greater than zero, fresh evidence competes with
older explanations. The tracker preserves the strongest occupied tracks and
their adjacent movement corridor, then sharply lowers stale zones that are not
needed to explain the configured number of people. For example, if two offices
have fresh motion and `expected_occupants` is `2`, stale confidence in an
unrelated bathroom or guest bedroom drops even if those sensors have not emitted
another event.

Passive time decay also runs during periodic refreshes. This prevents cleared
zones from keeping high confidence indefinitely just because no later event
touched the same room.

The next learning layer should attach to these module boundaries: transition
probabilities belong to graph edges, dwell-time distributions belong to zones,
and sensor reliability belongs to node/entity bindings. Learning should only
update those statistics when the tracker has a high-confidence explanation for
which anonymous track produced the evidence.

## Debugging

Enable debug logging with:

```yaml
logger:
  default: info
  logs:
    custom_components.predictive_controls: debug
```

Diagnostics are available from the integration entry and include loaded nodes, entity bindings, current probabilities, and transition counts.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
pytest
ruff check .
mypy
npm run test:frontend
```
