# Predictive Controls

> **Entity contract migration:** Release `0.1.20` still exposes the legacy
> `activation_plausible`, `keep_on`, and `prelight_plausible` entities. The
> canonical target under [`docs/spec`](docs/spec/README.md) replaces the default
> room contract with one durable `active` desired state plus optional `prelight`.
> The target implementation is pending; legacy and target projections will
> coexist for at least one full released version during cutover.

Predictive Controls is a Home Assistant custom integration that turns a graph of
motion/presence sensors into **zone-level occupancy inference** that ordinary
automations can consume. It answers questions raw motion sensors cannot on their
own:

- *Should normal outputs for this zone currently be on?* — target `active`
- *Which zone is a person most likely to enter next?* — target `prelight`
- *How many people are inside, and where?* — anonymous multi-occupant tracking

It models the home as anonymous people moving over a sensor adjacency graph,
maintains a probability distribution over joint occupant locations, learns
first-order transitions and bounded multi-step route prefixes from sufficiently
certain movement, and publishes a small, stable set of Home Assistant entities
plus a graphical editor.

The first target use case is predictive lighting, but actions are generic Home
Assistant service calls, so other domains can be added without redesigning the
model.

### At a glance

- **Input:** binary sensors (PIR, mmWave presence/target, radar) grouped into
  *nodes*, and nodes grouped into *zones* on an *adjacency graph*.
- **Core idea:** each event updates graph-valid joint location hypotheses. A
  low-prior missed-movement path remains possible, but isolated evidence cannot
  silently relocate an already-accounted-for occupant.
- **Target output:** per-zone `active` and optional `prelight`, whole-home
  `home_active`, an actionable problem entity, and disabled-by-default arrival
  events and probability diagnostics. Release `0.1.20` uses the legacy names
  described below.
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
  confidence, status, and current anonymous posterior tracks;
- a reliability tab that ranks repeated policy-rejected motion captures and
  repeated short low-confidence pulses over retained audit coverage;
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

## Target Entity Contract

The target default per-zone surface has two binary sensors, not three:

| Entity                          | Meaning                                                                                                               |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `binary_sensor.<zone>_active`   | Durable normal-output desired state. A supported fresh acquisition turns it on; supported final release turns it off. |
| `binary_sensor.<zone>_prelight` | Optional bounded prediction lease for low-impact path lighting.                                                       |

The default whole-home entities are:

| Entity                                      | Meaning                                                                           |
| ------------------------------------------- | --------------------------------------------------------------------------------- |
| `binary_sensor.home_active`                 | Pure OR of per-zone `active` policy states; off is not proof of physical vacancy. |
| `binary_sensor.predictive_controls_problem` | Actionable current integration fault; diagnostic only and never policy input.     |

`active` is policy intent, not raw motion, a direct occupancy marginal, or the
actual light state. Manually switching a light off never changes `active` and is
respected until a later `active` state edge. Advanced consumers that deliberately
want later accepted motion to reassert a manually disabled output may enable the
optional `event.<zone>_arrival` and consume its `refreshed` event type.

Arrival events and these probability sensors are disabled by default:

- `sensor.<zone>_occupancy_probability`;
- `sensor.<zone>_arrival_supported_probability`;
- `sensor.<zone>_release_safe_probability`; and
- `sensor.authoritative_occupant_count`.

Detailed paths, competing assignments, evidence IDs, thresholds, and reasons
remain in bounded panel, status, and policy-audit diagnostics.

### Current `0.1.20` Compatibility Entities

The released implementation still provides:

- `binary_sensor.<zone>_activation_plausible`, a short fresh-arrival lease;
- `binary_sensor.<zone>_keep_on`, the current ownership latch;
- `binary_sensor.<zone>_prelight_plausible`, the current prediction lease;
- `binary_sensor.home_keep_on`;
- per-zone diagnostic confidence and entry-path entities; and
- aggregate activation, keep-on, entry-path, and prediction sensors.

At target cutover, `keep_on` aliases `active`, `prelight_plausible` aliases
`prelight`, and `home_keep_on` aliases `home_active`; `activation_plausible`
retains its short accepted-arrival lease for compatibility. Existing registry
entries remain usable for at least one full released version. Legacy removal is
a separately reviewed breaking change.

## Using It in Automations

After target cutover, one state entity controls the normal light lifecycle:

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

Remove the `prelight` trigger and branch when predictive lighting is not wanted.
The `active` latch combines strict acquisition and conservative false-off
protection without making the automation reconstruct the policy lifecycle.

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

The predictor learns node-to-node transitions and bounded anonymous multi-step
route prefixes only when path-specific graph movement reaches `0.80`. At a
branch it uses the longest sufficiently supported compatible prefix, backs off
to shorter prefixes, then uses shared first-order counts. Learned route history
provides a capped branch-prior boost, ages over time, and learns outbound and
return paths independently. Predictions exclude the incoming zone, remain
independent for simultaneous path keys, and expire after their own lease. A
forced graph continuation needs no history. Predictions are published through
`prelight_plausible` and `sensor.diagnostic_predicted_next_zone` in release
`0.1.20`; the target default projection is `prelight`. Neither projection alters
the occupancy posterior, acquisition, `active`, or route learning. Later
finalized observed movement may still train the route model.

### Restart behavior

The existing Home Assistant Store persists the normalized posterior, map
fingerprint, authoritative count, policy latches/evidence IDs, unexpired leases,
entity evidence needed for bootstrap deduplication, and shared transition
counts plus bounded route statistics and live anonymous route contexts. Restore
is validated atomically before current HA states are replayed.
Bootstrap observations reconcile state without emitting activation or prediction
pulses. Expired leases are dropped; removed map zones become `unlocated` rather
than being guessed. Invalid schema, count, datetime, or probability data is
rejected with a diagnostic restore reason.

### Performance

Accuracy and deterministic consistency take precedence over preferred latency.
The hard callback ceiling is 100 ms; an over-budget update completes its state
change atomically but suppresses activation and predictive actions. Routine core
and runtime tail latency should remain at or below 30 ms.

The 0.1.20 release-candidate benchmark uses the checked-in 16-zone, 17-node,
23-entity reference map with two occupants and 10,000 deterministic events. On
CPython 3.12.13 it measured a 25.512 ms core maximum, 24.995 ms runtime p99,
and 45.068 ms runtime maximum, retained all 153 exact configurations, and
pruned zero occupancy probability. See `PERFORMANCE_RESULTS.json` for the
complete environment, percentiles, bootstrap timings, work bounds, and memory
measurements.

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
- `automation_policy.py` — acquisition leases and conservative ownership latches.
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

Diagnostics are available from the integration entry and include loaded nodes,
entity bindings, current probabilities, and transition counts. The
`occupancy_diagnostics.joint.policy_audit` retains up to 12 hours of policy
decisions across restarts, capped at 8,192 decision entries and 12 MiB of
compressed observation context. Each observation context remains complete but
is transported and persisted as a `zlib-json-v1` envelope: base64-decode its
`data` field, then zlib-decompress the canonical JSON. It contains provenance,
pre/post occupied marginals, count marginals, active positive evidence, movement
alternatives, and pending departures. Decision records retain gate values and
each affected latch's before/after state. Accepted, replacement, duplicate,
stale, and rejected observations all schedule a coalesced Store write. The
adjacent `policy_audit_retention` object reports configured time and size bounds,
current compressed-context bytes, entry count, and oldest/newest retained
timestamps so diagnostics state their actual coverage.

`occupancy_diagnostics.reliability` provides a compact review summary without
decompressing retained contexts. It deduplicates policy rows by sensor trigger,
groups repeated positive captures rejected while ownership remained off, and
reports repeated pulses of at most 30 seconds whose positive edge failed the
occupied gate. These are investigation signals, not automatic declarations of
sensor failure. The Occupancy tab also projects the most probable exact joint
configuration as current anonymous tracks; track labels do not claim persistent
person identity.

## Development

The [`docs/spec`](docs/spec/README.md) set is the canonical project and model
contract. Every reported error, regression, threshold change, or
inference/policy redesign must follow the repository-local
[`predictive-controls-regression-review`](.github/skills/predictive-controls-regression-review/SKILL.md)
skill before production behavior is edited.

For every diagnosed live incident, add a permanent regression containing the
observed event order, timing, posterior/gate values, and expected public
automation output. Establish that the test fails for the original behavior,
then make the smallest generic predictor change that passes it. Prefer
assertions on target `active` or `prelight` state, or the optional `arrival`
event when it controls the behavior. Migration-era regressions may additionally
assert factual legacy `activation_plausible`, `keep_on`, or
`prelight_plausible` projections.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest
python -m ruff check .
python -m mypy
npm run test:frontend
python benchmarks/occupancy_performance.py \
  --events 100 \
  --output /tmp/predictive-controls-performance.json
```

CI runs whole-package coverage, Ruff, strict mypy, frontend tests, and a portable
benchmark smoke test. The full 10,000-event wall-clock benchmark is a release
gate because shared CI timing is too noisy for a meaningful hard ceiling. Run
the full benchmark locally only for event-path performance changes, a smoke or
latency regression, or explicit release validation.
