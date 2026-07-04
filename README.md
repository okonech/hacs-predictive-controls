# Predictive Controls

Predictive Controls is a Home Assistant custom integration that turns a graph of
motion/presence sensors into **zone-level occupancy inference** that ordinary
automations can consume. It answers questions raw motion sensors cannot on their
own:

- *Is this zone still occupied even though motion just cleared?* — `keep_on`
- *Is a fresh raw detection plausible enough to turn something on?* — `activation_plausible`
- *Which zone is a person most likely to enter next?* — `prelight_plausible`
- *How many people are inside, and where?* — anonymous multi-occupant tracking

It models the home as anonymous people moving over a sensor adjacency graph,
maintains a decaying **confidence** per zone, learns first-order Markov
transition probabilities for prediction, and publishes a small, stable set of
Home Assistant entities plus a graphical editor.

The first target use case is predictive lighting, but actions are generic Home
Assistant service calls, so other domains can be added without redesigning the
model.

### At a glance

- **Input:** binary sensors (PIR, mmWave presence/target, radar) grouped into
  *nodes*, and nodes grouped into *zones* on an *adjacency graph*.
- **Core idea:** every real move is observed as a trail across adjacent zones,
  so confidence flows along the graph; a detection with no connecting trail is
  treated as a false positive.
- **Output:** per-zone `activation_plausible`, `keep_on`, and
  `prelight_plausible` entities plus diagnostic confidence/path/prediction
  entities and whole-home aggregates.
- **Learning:** Markov edge probabilities for next-zone prediction.

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

Zone adjacency is derived from node `adjacent` edges. Cross-floor movement should
be modeled as a normal edge between the two adjacent transition nodes, such as a
bottom-of-staircase node connected only to the top-of-staircase or upstairs
hallway node. The occupancy tab renders same-floor zone edges on each board and
cross-floor links as one connected graph, with floor bands behind the current
occupancy cards.

When a sticky room clears shortly after adjacent transition evidence, and a
stronger active track exists on the other side of that transition, the cleared
room decays faster as a likely departure instead of waiting for normal passive
sticky decay.

For each zone, the integration exposes:

- an activation-plausible binary sensor for deciding whether a fresh raw local
  detection is safe enough to turn outputs on;
- a keep-on binary sensor for deciding whether outputs should stay on even
  after raw motion clears;
- a prelight-plausible binary sensor for soft pre-lighting before a person
  arrives, with probability and threshold attributes;
- diagnostic confidence and entry-path sensors, with status, timing, source,
  and reason attributes for troubleshooting.

`activation_plausible` is intentionally stricter than occupancy confidence. It
is based on evidence that existed before the raw local detection: a fresh
adjacent entry path, another same-zone sensor already active, or the zone already
being held occupied. Prediction alone does not make activation plausible.

These entities are intended as an inference layer between raw motion sensors and
lighting automations. Node-level prediction, separate status sensors,
prediction-probability sensors, and motion-plausible entities are kept in the
panel/status diagnostics instead of being exported as default HA entities.

The automation-facing aggregate entities are:

- `binary_sensor.home_keep_on` for whole-home occupied/vacant logic;
- `sensor.activation_plausible_zones` and `sensor.keep_on_zones`, each with the
  relevant zones in attributes.

The diagnostic aggregate entities are:

- `sensor.diagnostic_entry_path_plausible_zones` for fresh adjacent path hints;
- `sensor.diagnostic_predicted_next_zone` with per-zone prediction
  probabilities in attributes.

Room automations should normally use raw local motion for immediate turn-on,
zone activation-plausible as the turn-on guard, zone keep-on to prevent
false-offs, and zone prelight-plausible entities for soft pre-lighting.

## Entities

For every configured zone (`<zone>` is the zone id):

| Entity | Value | Meaning |
| --- | --- | --- |
| `binary_sensor.<zone>_activation_plausible` | on/off | Fresh raw local detection is plausible enough to turn outputs on |
| `binary_sensor.<zone>_keep_on` | on/off | Keep outputs on while the zone is still plausibly occupied (on at ≥ "possible") |
| `binary_sensor.<zone>_prelight_plausible` | on/off | Zone is predicted next *above threshold* (use this for gated pre-lighting) |
| `sensor.<zone>_diagnostic_confidence` | 0–100 % | Diagnostic occupancy confidence, with `status`, `reason`, `occupancy_behavior`, and timing attributes |
| `binary_sensor.<zone>_diagnostic_entry_path_plausible` | on/off | Diagnostic fresh adjacent/path evidence into the zone, without prediction mixed in |

Whole-home aggregates:

| Entity | Value | Meaning |
| --- | --- | --- |
| `binary_sensor.home_keep_on` | on/off | Any zone currently wants outputs kept on |
| `sensor.activation_plausible_zones` | count | Activation-plausible zones listed in the `activation_plausible_zones` attribute |
| `sensor.keep_on_zones` | count | Keep-on zones listed in the `keep_on_zones` attribute |
| `sensor.diagnostic_entry_path_plausible_zones` | count | Diagnostic entry-path zones listed in attribute |
| `sensor.diagnostic_predicted_next_zone` | zone id | Diagnostic arg-max predicted zone, with `zone_probabilities` attribute |

> `sensor.diagnostic_predicted_next_zone` names the most likely zone *even when its
> probability is below the threshold*. For pre-lighting decisions, trigger on the
> per-zone `binary_sensor.<zone>_prelight_plausible`, which respects the threshold.

## Using it in automations

The recommended room pattern: trigger from **raw local motion**, require the
zone **activation-plausible** guard before turning on, turn off from the zone
**keep-on** clearing (which absorbs the still/decay/departure logic), and
optionally pre-light from **prelight-plausible**.

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.living_room_motion      # raw local presence
    to: "on"
    id: occupancy_detected
  - trigger: state
    entity_id: binary_sensor.living_room_keep_on
    to: "off"
    id: occupancy_cleared
actions:
  - choose:
      - conditions: [{ condition: trigger, id: occupancy_detected }]
        sequence:
          - condition: state
            entity_id: binary_sensor.living_room_activation_plausible
            state: "on"
          - action: light.turn_on
            target: { entity_id: light.living_room }
      - conditions: [{ condition: trigger, id: occupancy_cleared }]
        sequence:
          - action: light.turn_off
            target: { entity_id: light.living_room }
mode: restart
```

Triggering from raw motion keeps the automation low-latency, while
`activation_plausible` blocks isolated raw hits and `keep_on` provides the
false-off protection.

## How It Works

Occupancy is modeled as **anonymous multi-person tracking** over the zone
adjacency graph. The system never identifies who someone is; it asks *which set
of occupied zones best explains the recent sensor evidence*.

### Zones, nodes, and the graph

- A **node** is one sensor or a tightly coupled sensor cluster (for example an
  mmWave device that exposes several target/moving/still entities).
- A **zone** groups nodes into a place and carries a `role` and an
  `occupancy_behavior`.
- **Adjacency** is taken from node `adjacent` edges and collapsed to a
  zone-level graph. Cross-floor movement is modeled as an edge between the two
  transition nodes at the boundary (for example bottom-of-staircase ↔
  top-of-staircase).

### Confidence lifecycle

Each zone holds a confidence in `[0, 1]` that maps to a status:

| Status | Confidence | `keep_on` |
| --- | --- | --- |
| rejected | < 0.05 | off |
| suspect | 0.05–0.35 | off |
| possible | 0.35–0.60 | on |
| probable | 0.60–0.85 | on |
| confirmed | ≥ 0.85 | on |

- **On-evidence** sets a floor by role and signal type (a `still_target` in an
  anchor room starts high; a hallway `transition_gate` starts lower) and nudges
  confidence up on repeats.
- **Sustained evidence** (a sensor that stays on) ramps confidence toward a
  per-behavior cap over time.
- **Passive decay** halves confidence on a per-behavior half-life once evidence
  clears, and runs on a periodic refresh so nothing stays high forever.
- **Conflict / departure decay** sharply cuts a zone (to roughly a third) when
  the evidence is better explained elsewhere.

Occupancy behaviors tune the growth cap and decay half-life:

| Behavior | Typical zones | Passive half-life |
| --- | --- | --- |
| `transient` | hallways, stairs | ~90 s |
| `ambiguous` | open-plan / overlapping | ~5 min |
| `sustained` | offices, kitchens, closets | ~15 min |
| `sticky` | living rooms, bathrooms | ~30 min |

### Movement is always a trail

With full sensor coverage a person cannot move between zones unobserved — every
move leaves a **trail** of motion across adjacent zones. This is the core
invariant:

- Confidence and occupant tracks flow along the graph following recent motion
  breadcrumbs (a **trail-following corridor**) rather than a fixed radius, so a
  genuine multi-hop move is carried to its destination.
- A detection that is **not connected by a recent trail** to any occupied track,
  when the occupant count is already saturated, is treated as a **false
  positive** and capped at "suspect".

The only thing sensors cannot resolve is *how many* people walked a shared path;
whether a move happened is never ambiguous.

### Counting people (`expected_occupants`)

Set `expected_occupants` (a fixed number, or bind it to an entity) to enable
multi-occupant reasoning:

- The tracker keeps the strongest N occupied **tracks** and their movement
  corridor, and decays stale zones that are not needed to explain N people. So
  two "stay" zones actively growing implies the rest of the house is clear.
- **A zone counts as one occupant while occupied, regardless of how many of its
  sensors or overlapping signals fire.** A slow walker trips both the "still"
  and "moving" entities of one radar; that is one person, not two. Extra
  occupants are added only from explicit join evidence.
- **Join:** when someone enters an already-occupied zone via an adjacent
  transition, an extra-occupant slot is added and persists while the zone stays
  occupied.
- **Departure / migration:** when a trail leads out of a multi-occupant zone,
  one occupant slot is released and follows the person, so the count moves with
  them instead of over-counting the origin. A single-occupant zone that is left
  decays normally.

With `expected_occupants` at `0`, the count/competition layer is disabled and
each zone simply rises and decays on its own.

### Prediction (pre-lighting)

A first-order Markov chain learns node→node transition probabilities from
observed movement. Predicted next zones are projected only along the current
adjacent edge — so pre-lighting follows the configured graph instead of jumping
to unrelated rooms or floors — and are published through the
`prelight_plausible` entities and `sensor.diagnostic_predicted_next_zone`.

### Code layout

- `occupancy_graph.py` — zone graph: neighbors, movement corridors, distances.
- `occupancy_scoring.py` — pure confidence math (on-floors, sustained ramp,
  passive/conflict/departure decay, status thresholds).
- `occupancy_tracker.py` — zone state, active evidence, trails, join/departure,
  anonymous track reconciliation.
- `occupancy_dwell.py` — learned per-zone dwell times feeding decay.
- `markov.py` / `engine.py` — transition learning and next-zone prediction.
- `automation_summary.py` — the stable automation-facing contract.
- `confidence.py` — compatibility facade over the tracker.

Learning updates attach to these boundaries: transition probabilities belong to
graph edges, dwell-time distributions belong to zones, and sensor reliability
belongs to node/entity bindings, updated only when the tracker has a
high-confidence explanation for which anonymous track produced the evidence.

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
