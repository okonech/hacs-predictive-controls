# Predictive Controls

Predictive Controls is a Home Assistant custom integration that turns a graph of
motion and presence sensors into stable zone-level automation entities. Its
first use case is fast, accurate lighting through one `active` entity per zone.

## Design and Current Model

[SPECIFICATION.md](SPECIFICATION.md) is the sole source of product and model
requirements. Code, tests, documentation, and historical changelog entries must
remain consistent with it.

The local implementation combines per-zone probability filters with one selected
set of exactly N anonymous slots, including unlocated slots. Each located path
retains at most four observed visits and four connected route occurrences;
same-zone overlap is allowed. One real positive advances at most one slot.
Selected coverage retains only already evidence-active zones: endpoint OFF or
elapsed time alone does not evict them, and rejected alternatives cannot hold
every possible room on. Movement can displace old coverage, but genuine
noninteraction presence separately protects local confidence through stable clear;
departure decay and full release dwell follow only after that protection ends.

Warnings are diagnostic, not occupancy or hardware-control gates. A missing,
unobserved intermediate does not authorize a target: it can produce a distinct
`unsupported_jump` warning, while later independent adjacent evidence remains valid.
Mature selected-path prediction uses independent bounded grants and ten-second
leases; selected-only transitions never train the route model. Already-qualified
adjacent learning is retained as bounded statistical debt after publication and
across compatible saves. A row commits only after its live prediction leases end;
unsaved operations are not claimed crash-durable.

**Validation status:** local implementation and final2 repository validation are
complete (2026-09-14): 3217 Python tests pass at 100% statement/branch coverage,
with the distinct incident/scenario, frontend, static and performance gates passed.
See [current local conformance](SPECIFICATION.md#current-local-conformance) for
exact evidence, preservation/diff caveats and deferred operational obligations,
not historical green or failed baselines. No deployment, live Home Assistant
restart or physical-light verification is claimed.

### Persistence compatibility

- Current inference uses Home Assistant Store version `7` and `zone-belief-v4`.
  Restore requires the **exact current semantic fingerprint** and complete strict
  selected, physical, policy and prediction/deferred-learning records. Old v4
  fingerprints, all v3 inference and v1 inference are rejected; a schema label
  or edited fingerprint cannot supply missing authority.
- The separate schema-6 and v2 import paths retain only validated count/Boolean
  active seeds; v2 requires a retained allowed non-source-free acquisition edge.
  Both cold-build from current raw sensors and prefer the valid authoritative
  count. They do not import old filters, episodes, tokens, supports, selected
  paths or prediction state. See `decode_schema6_seed`/`migrate_schema6_seed` and
  `decode_v2_seed`/`migrate_v2_seed` in
  [persistence](custom_components/predictive_controls/zone_model/persistence.py),
  routed by [the facade](custom_components/predictive_controls/occupancy_tracker.py).
- Historical v3/pre-feature component decoders remain isolated qualification
  boundaries, not public migration paths. The retained accepted-v3 rollback branch
  in [setup](custom_components/predictive_controls/__init__.py) requires successful
  v3 restore, which the current reader rejects. Existing rollback copies remain
  separate; current rollout needs a matching inference backup or conservative
  cold bootstrap, never rewritten fingerprints.

Historical changelog entries describe earlier architectures, not current
deployment instructions. Completed migration and intermediate-stage documents
have been removed; current contracts, validation and outstanding operational
obligations are maintained in [SPECIFICATION.md](SPECIFICATION.md).

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
sensor is one bounded correlated observation, not repeated motion. Ordinary
component tokens retain their finite expiry, but a matching unconsumed ordinary
live origin can pair with a fresh adjacent target without a token-age deadline.
Selected endpoints likewise do not expire from OFF or time alone. Startup ON,
aliases and timers cannot create or replenish that authority.

Hardware timing and software profiles are calibrated together. A long-open
hallway can remain an observed branch of the selected route. Clearing an
intermediate removes its branch authority, not the recorded connection or final
endpoint. Per-device timing discovery/adaptation is deferred, not required for
correct path retention. See [SPECIFICATION.md](SPECIFICATION.md) for behavior,
calibration, rollout and measurement requirements.

## Development

Create the Python environment and install the development dependencies declared
in [pyproject.toml](pyproject.toml), then use these quality gates:

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
[the regression-review workflow](.github/skills/predictive-controls-regression-review/SKILL.md): preserve the
observed public failure with exact timestamps, prove it against unchanged
behavior, review the generic proposal independently, then implement and run all
quality gates.

## Repository Documents

- [SPECIFICATION.md](SPECIFICATION.md): sole normative design authority and current
  local-conformance evidence.
- [CHANGELOG.md](CHANGELOG.md): unreleased changes and historical release records;
  neither overrides the current specification.
- [Outstanding operational obligations](SPECIFICATION.md#deferred-operational-obligations):
  deferred device research, live rollout verification and the unresolved external
  office-device incident. These are not completed migration stages.
- [PERFORMANCE_RESULTS.json](PERFORMANCE_RESULTS.json): checked-in performance
  artifact retained as historical evidence; the verified final2 benchmark is
  recorded in [current local conformance](SPECIFICATION.md#current-local-conformance).
