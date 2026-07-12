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
maintains a probability distribution over joint occupant locations, learns
first-order Markov transitions from sufficiently certain movement, and
publishes a small, stable set of Home Assistant entities plus a graphical
editor.

The first target use case is predictive lighting, but actions are generic Home
Assistant service calls, so other domains can be added without redesigning the
model.

### At a glance

- **Input:** binary sensors (PIR, mmWave presence/target, radar) grouped into
  *nodes*, and nodes grouped into *zones* on an *adjacency graph*.
- **Core idea:** each event updates graph-valid joint location hypotheses. A
  low-prior missed-movement path remains possible, but isolated evidence cannot
  silently relocate an already-accounted-for occupant.
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

## Occupancy Inference

Predictive Controls publishes posterior occupancy diagnostics from the same node
map. Each mapped node may define `floor`, `zone`, `role`, and
`occupancy_behavior` metadata. Roles such as `room_occupancy`,
`transition_gate`, `ambiguous_open_plan`, `subzone_occupancy`, and
`anchor_sensor` describe the kind of sensor or place. Occupancy behaviors select
observation profiles and describe how evidence should be interpreted:

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

Physical adjacency is undirected and must be declared reciprocally. Optional
`transition_seconds` values are directed timing overrides for an existing
physical edge; a missing override uses the default and never borrows the reverse
direction's value.

For each zone, the integration exposes:

- an activation-plausible binary sensor for deciding whether a fresh raw local
  detection is safe enough to turn outputs on;
- a keep-on binary sensor for deciding whether outputs should stay on even
  after raw motion clears;
- a prelight-plausible binary sensor for soft pre-lighting before a person
  arrives, with probability and threshold attributes;
- diagnostic confidence and entry-path sensors, with status, timing, source,
  and reason attributes for troubleshooting.

`activation_plausible` is intentionally stricter than posterior occupancy. A
positive event must raise occupied probability above the activation thresholds
and have graph support, independent corroboration, prior unlocated mass, or a
trusted recovery. Prediction alone never makes activation plausible.

The three automation signals are independent:

- `activation_plausible` is a short pulse authorizing a fresh local turn-on;
- `keep_on` is a conservative latch released only by sufficiently strong
  departure/relocation evidence or an authoritative reset/count of zero;
- `prelight_plausible` is a time-bounded prediction lease and is never occupancy
  evidence.

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

Room automations should normally turn on from zone `activation_plausible`, turn
off when zone `keep_on` clears, and optionally soft pre-light from zone
`prelight_plausible`. Raw entities remain inputs and diagnostics, not the
recommended automation contract.

## Entities

For every configured zone (`<zone>` is the zone id):

| Entity                                                 | Value   | Meaning                                                                                               |
| ------------------------------------------------------ | ------- | ----------------------------------------------------------------------------------------------------- |
| `binary_sensor.<zone>_activation_plausible`            | on/off  | Fresh raw local detection is plausible enough to turn outputs on                                      |
| `binary_sensor.<zone>_keep_on`                         | on/off  | Conservative occupancy-policy latch; a clear sensor alone does not turn it off                        |
| `binary_sensor.<zone>_prelight_plausible`              | on/off  | Zone is predicted next *above threshold* (use this for gated pre-lighting)                            |
| `sensor.<zone>_diagnostic_confidence`                  | 0–100 % | Diagnostic occupancy confidence, with `status`, `reason`, `occupancy_behavior`, and timing attributes |
| `binary_sensor.<zone>_diagnostic_entry_path_plausible` | on/off  | Diagnostic fresh adjacent/path evidence into the zone, without prediction mixed in                    |

Whole-home aggregates:

| Entity                                         | Value   | Meaning                                                                         |
| ---------------------------------------------- | ------- | ------------------------------------------------------------------------------- |
| `binary_sensor.home_keep_on`                   | on/off  | Any zone currently wants outputs kept on                                        |
| `sensor.activation_plausible_zones`            | count   | Activation-plausible zones listed in the `activation_plausible_zones` attribute |
| `sensor.keep_on_zones`                         | count   | Keep-on zones listed in the `keep_on_zones` attribute                           |
| `sensor.diagnostic_entry_path_plausible_zones` | count   | Diagnostic entry-path zones listed in attribute                                 |
| `sensor.diagnostic_predicted_next_zone`        | zone id | Diagnostic arg-max predicted zone, with `zone_probabilities` attribute          |

> `sensor.diagnostic_predicted_next_zone` names the most likely zone *even when its
> probability is below the threshold*. For pre-lighting decisions, trigger on the
> per-zone `binary_sensor.<zone>_prelight_plausible`, which respects the threshold.

## Using it in automations

The recommended room pattern uses only the three stable policy outputs: turn on
from **activation-plausible**, turn off when **keep-on** clears, and optionally
soft pre-light from **prelight-plausible**.

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.living_room_activation_plausible
    to: "on"
    id: occupancy_detected
  - trigger: state
    entity_id: binary_sensor.living_room_keep_on
    to: "off"
    id: occupancy_cleared
  - trigger: state
    entity_id: binary_sensor.living_room_prelight_plausible
    to: "on"
    id: prelight
actions:
  - choose:
      - conditions: [{ condition: trigger, id: occupancy_detected }]
        sequence:
          - action: light.turn_on
            target: { entity_id: light.living_room }
      - conditions: [{ condition: trigger, id: occupancy_cleared }]
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

Remove the `prelight` trigger and branch when predictive lighting is not wanted.
`activation_plausible` already incorporates the fresh local event and its graph
support; `keep_on` provides conservative false-off protection.

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

### Joint posterior lifecycle

Every hypothesis contains exactly `expected_occupants` anonymous positions.
Positions are canonicalized, so swapping hypothetical identities does not
create duplicate physical explanations. The supported state space is fixed at
17 configurations for one occupant and 153 for two occupants on the repository
map. For every sensor event the filter:

1. leaves clears and duplicate states in place, while a positive event generates
  stay plus one-occupant movement into only the observed zone;
2. replaces that entity's previous likelihood contribution, so duplicate
   same-state events cannot compound their own evidence;
3. merges equivalent configurations in log space, normalizes, and derives
  per-zone occupied/count marginals and path-specific movement evidence;
4. updates policy latches and prediction leases without feeding either result
   back into occupancy probability.

There is no ambient diffusion and no supported-count occupancy pruning. Every
valid one- or two-occupant configuration remains represented, impossible states
have exact zero mass, and bounded directional contexts preserve their parent
occupancy mass when compacted.

### Movement and uncertainty

Adjacent trails receive the normal movement prior. Non-adjacent relocation is
represented explicitly with a low prior instead of being declared impossible.
A weak disconnected hit therefore retains the origin and does not authorize the
candidate; independent corroboration can eventually overcome that prior. The
filter preserves crossing and same-room ambiguity rather than inventing an
identity.

### Counting people (`expected_occupants`)

Set `expected_occupants` (a fixed number, or bind it to an entity) to enable
multi-occupant reasoning. This release supports zero, one, or two occupants:

- Every posterior configuration contains exactly N positions, including
  `unlocated` positions when the evidence does not identify a room.
- Multiple positions may occupy the same zone, so same-room joins and partial
  departures preserve multiplicity without assigning identities.
- Increasing the count adds unlocated positions without creating activation.
  Decreasing it marginalizes deterministically and retains the strongest
  supported policy latches.

`expected_occupants: 0` is authoritative nobody-home. It clears activation,
keep-on, and prediction outputs; it no longer means unbounded tracking.
Static counts above two are rejected. If a dynamic count entity reports above
two, the integration publishes an explicit unsupported-count diagnostic,
retains established `keep_on` latches, clears activation and prediction, and
suspends occupancy transitions instead of entering an approximate filter.
Returning to one or two performs an atomic bootstrap from current entity states
without emitting activation.

### Prediction (pre-lighting)

A first-order Markov chain learns node-to-node transitions only when posterior
movement mass reaches `0.80`. Predictions exclude the incoming zone, remain
independent for simultaneous path keys, and expire after their own lease. A
forced graph continuation needs no history; learned counts rank only ambiguous
forward branches. Predictions are published through `prelight_plausible` and
`sensor.diagnostic_predicted_next_zone` but never alter the posterior.

### Restart behavior

The existing Home Assistant Store persists the normalized posterior, map
fingerprint, authoritative count, policy latches/evidence IDs, unexpired leases,
entity evidence needed for bootstrap deduplication, and shared transition
counts. Restore is validated atomically before current HA states are replayed.
Bootstrap observations reconcile state without emitting activation or prediction
pulses. Expired leases are dropped; removed map zones become `unlocated` rather
than being guessed. Invalid schema, count, datetime, or probability data is
rejected with a diagnostic restore reason.

### Performance

Accuracy and deterministic consistency take precedence over preferred latency.
The hard callback ceiling is 100 ms; an over-budget update completes its state
change atomically but suppresses activation and predictive actions. Routine core
and runtime tail latency should remain at or below 30 ms.

The 0.1.19 release-candidate benchmark uses the checked-in 16-zone, 17-node,
23-entity reference map with two occupants and 10,000 deterministic events. On
CPython 3.12.13 it measured a 15.389 ms core maximum and 17.953 ms runtime
maximum, retained all 153 exact configurations, and pruned zero occupancy
probability. See `PERFORMANCE_RESULTS.json` for the complete environment,
percentiles, bootstrap timings, work bounds, and memory measurements.

Automated gates do not replace real sensor validation. The required seven-day
Home Assistant observation has not yet been collected; see
`SHADOW_VALIDATION.md` for the external rollout gate and `CHANGELOG.md` for the
release-candidate evidence ledger.

### Calibration workflow

Start with graph and sensor semantics, not policy thresholds:

1. Verify `zone`, `role`, `occupancy_behavior`, adjacency, and transition timing.
2. Set `initial_weight` to reflect entity reliability; reliability interpolates
  each observation profile toward neutral evidence.
3. Replay representative short clears, real departures, false positives,
  same-room joins/splits, and interleaved paths.
4. Inspect posterior marginals, provenance disposition, movement evidence,
   context compaction, policy reason/evidence IDs, and leases in diagnostics.
5. Change fixed likelihood/policy constants only with replay evidence and keep
  the complete 100% branch-coverage gate green.

### Code layout

- `occupancy_graph.py` — zone graph: neighbors, movement corridors, distances.
- `occupancy_state.py` — immutable canonical hypotheses and probability helpers.
- `observation_model.py` — calibrated replacement likelihoods and provenance.
- `transition_model.py` / `joint_filter.py` — graph propagation and Bayesian
  joint inference.
- `automation_policy.py` — activation leases and conservative keep-on latches.
- `prediction.py` / `markov.py` — path-keyed leases and posterior-consistent
  transition learning.
- `occupancy_persistence.py` — versioned atomic serialization and reconciliation.
- `occupancy_tracker.py` — compatibility facade over the joint stack.
- `automation_summary.py` — the stable automation-facing contract.
- `confidence.py` — compatibility facade over the tracker.

Learning updates attach to these boundaries: transition probabilities belong to
graph edges, dwell-time distributions belong to zones, and sensor reliability
belongs to node/entity bindings, updated only when path-specific evidence
identifies the movement without inventing a persistent occupant identity.

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
python -m pytest
python -m ruff check .
python -m mypy
npm run test:frontend
python benchmarks/occupancy_performance.py
```

CI runs whole-package coverage, Ruff, strict mypy, frontend tests, and a portable
benchmark smoke test. The full 10,000-event wall-clock benchmark is a release
gate because shared CI timing is too noisy for a meaningful hard ceiling.
