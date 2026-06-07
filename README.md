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
- settings for transition learning window and binary prediction threshold.

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
same node map. Each mapped node may define `floor`, `zone`, and `role` metadata;
roles such as `room_occupancy`, `transition_gate`, `ambiguous_open_plan`,
`subzone_occupancy`, and `anchor_sensor` tune how strongly sensor on/off events
affect zone confidence.

Maps may also include optional top-level `zones` metadata for display labels,
floor grouping, and visual placement in the occupancy tab. If omitted, the panel
derives zones from node `zone`, `floor`, and `position` fields.

For each zone, the integration exposes:

- a confidence percentage sensor;
- a status sensor with `rejected`, `suspect`, `possible`, `probable`, or
  `confirmed`;
- a probable-occupancy binary sensor that turns on for `probable` and
  `confirmed` states.

These entities are intended as an inference layer between raw motion sensors and
lighting automations. Existing predicted-node entities remain available for
compatibility.

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
