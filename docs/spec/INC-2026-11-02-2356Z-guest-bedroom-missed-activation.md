# Guest Bedroom Missed Activation

Status: November3 approved reciprocal Foyer/Guest motion-node correction applied
to the local Homelab map. Exact actual-map red/green proof, seven boundary cases,
YAML/schema validation and independent final review PASS for this local scope. No package
source/test change or live deployment. Original-map primary remains red and
unchanged. Physical detector coverage and original loaded-map equivalence are
not newly proven; preserve those limits and the path-required safety contract.
Layers: MAP_PROFILE topology/coverage candidate; TRAVERSAL / POLICY reject as
configured. PATH_HEALTH is diagnostic only; no retention defect established.
Authority: SPECIFICATION.md REQ-PATH-003/004/006/009, HEALTH001/003, DIAG007, GOV005.

## Report And Provenance

Original November2, 2026 local-date report: continuous-presence warnings while
Shaila really is in the guest bedroom. The user explicitly expected active
occupancy and requested the failed path sequence and a retained bug scenario.
No physical light-actuation failure was reported. Source UTC crosses November3.

Approved read-only Homelab evidence:

- `tmp/guest-bedroom-warning-20261102/status.json`, collected through
  `home-assistant/scripts/ha-ws-readonly.py predictive-controls-status`.
  SHA256 ea3a8da939cf534b2778c9d23447afddf4d6b32862bd874a79f0b8b88ac04eaa.
- `tmp/guest-bedroom-warning-20261102/history.json`, collected through approved
  `ha-history-states.sh` for17 exact entities, November2 23:55:00 through
  November3 01:01:05 UTC.
  SHA256 4365137b4a9ec3955749128eb94792d2feb419e2ffc8d9804e7782852a148fa3.
- Final `scenario-final.log` and `scenario-final.xml` in the same ignored evidence
  directory:2 complete cases,1 expected failure,1 pass, no errors/skips.

The first captured material callback is November2 23:56:09.627305 UTC, which
determines the incident identity. The recorder query boundary is not an event.
Boundary levels have right target/still/zone3 and Alex Office ON; other captured
levels OFF. Count2 is available, source configured_expected_occupants, not a
replayed person count or identity assignment.

## Verified Sequence And Diagnosis

All following times are November3 UTC:

| Time            | Recorded event or decision                                                                                                                                                 |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 00:04:48.509882 | Dining ON, bootstrap pending                                                                                                                                               |
| 00:04:52.523361 | Foyer ON acquired through selected path                                                                                                                                    |
| 00:05:03.683190 | Guest ON generation163, trustworthy positive; belief0.349579133361807 ->0.9442349949477727 above0.7; authorization false, track_bootstrap_pending/acquisition_unauthorized |
| 00:07:05.952296 | Live pending guest candidate untracked_expired; this is a timer row, not another sensor detection                                                                          |
| 00:19:12.371936 | Left radar target ON acquired via selected_path; evidence cites its own episode and guest generation163                                                                    |
| 00:42:05.938824 | Guest path-health unsupported interval begins; this does not establish loss of an acquired guest destination                                                               |
| 00:52:05.938824 | Guest continuous-presence warning qualified exactly600s later                                                                                                              |
| 01:01:04.222491 | Report snapshot: guest confidence0.949649587198776, inactive/acquisition_unauthorized, sensor asserted and no episode health fault                                         |

The guest node's adjacent sources are bottom staircase and left radar, not
Dining/Foyer. Bottom staircase and all left-radar aliases were OFF at23:55 and
had no changes before guest arrival. Thus no eligible recorded adjacent source
authorized that arrival. The ordinary guest origin survived pending expiry and
later formed Guest -> Left, acquiring only the new Left target. PATH004 expressly
forbids retroactive source acquisition; PATH009 only retains occupancy admitted
by acquisition-qualified local evidence. This is a legitimate-occupancy recovery
gap against the user's expectation, not a warning-driven release or a proven
hardware fault. No guest active edges exist in the retained audit.

Latest clarification cross-check: the original policy audit has no guest
active-before/active-after transition. At00:05:03 the guest output was already
inactive and remained inactive, with ordinary local positive evidence but
authorization false. The00:19:12 acquired event belongs to Left, using the guest
episode as its source. Therefore the retained sequence does not show an
authorized guest destination becoming inactive; later loss of source coverage
cannot explain the earlier acquisition failure. This does not deny the user's
reported physical occupancy or prove no physical route was taken. The follow-up
below distinguishes recorded source absence and missing graph adjacency from
source expiry in the replay; it does not prove detector coverage or fault.

Current selected endpoints Alex Office/Foyer do not prove earlier selected state.
Restore reports incompatible map fingerprint, but no causal role in this arrival
is established. The floor plan and configured main-level graph were consulted;
sensor paths cannot identify Shaila or reconstruct her entry/exit times.

### November3 Incoming-Path Investigation

Approved `ha-history-states.sh` follow-up fetched November2 22:00:00 through
November3 00:06:00 UTC for14 exact entities. Separate retained evidence:
Homelab `tmp/guest-bedroom-warning-20261102/arrival-source-history-20261103.json`.
SHA256:901e5e939733a6a9a5a2f9c4c5bdad34f357d40bc4e6c6a29690af161779eda5.
All14 groups contain only a query-boundary row and no subsequent changes:

- Bottom staircase motion and all four Left radar aliases are recorded OFF.
- Bottom staircase, Dining, and Guest scene001/002/003 have no new interaction.
  Their old event-state timestamps and unknown levels are not fresh presses;
  query-boundary `last_changed` values are not new observations.

This rules out a held-ON adjacent witness hidden by the original23:55 boundary
and an omitted recorded switch interaction in this interval. Recorder evidence
does not prove a person never crossed a detector's field or establish hardware
health. No sensor-positive row exists here for selection to consume or expire.

Independent read-only topology review and direct viewing of both labeled and
unlabeled main-level plans identify Foyer/Guest doorway access. The capture-time
sensor map has no `foyer_pir_motion`/`guest_bedroom_motion` edge; its shortest
connection requires `bottom_of_staircase_motion` or its interaction node. A
separate approach through Left also requires a Left observation. The plans do
not mark detector aiming/coverage, so physical adjacency alone does not establish
that a new sensor-graph edge is operationally correct. Guest's documented sensor
faces the bed. The evidence supports a map/coverage mismatch candidate, not a
proven detector fault. Edit approval was obtained separately below. Original live loaded-map
equivalence is not exposed by the retained status payload.

The falsifiable check was executed through Pylance RunCodeSnippet using the
repository `.venv/bin/python`, the unchanged RuntimeScenario, real registered
timers, and public active entities. An unchanged failure after adding only the
hypothetical reciprocal Foyer/Guest edge would have disproved missing adjacency
as a sufficient explanation in that replay.

| In-memory case                               | Inputs                  | Guest at00:05:03             | Guest at01:01:04 |
| -------------------------------------------- | ----------------------- | ---------------------------- | ---------------- |
| Frozen induced map                           | Original138             | OFF/acquisition_unauthorized | OFF              |
| Induced map plus reciprocal Foyer/Guest edge | Same138                 | ON/acquired                  | ON               |
| Full repository map                          | Same138                 | OFF/acquisition_unauthorized | OFF              |
| Full map plus reciprocal Foyer/Guest edge    | Same138                 | ON/acquired                  | ON               |
| Full map plus edge, isolated Guest control   | One Guest positive only | OFF/acquisition_unauthorized | OFF              |

Both138-input induced branches assert exact normalized-input equality. The
three full-map branches assert delivered counts and both public arrival/final
outcomes; all assertions pass. The isolated control is explicitly synthetic,
not an alteration of the retained incident. The full graph uses only the17
captured boundary levels; other entities remain unobserved, not invented OFF.

Immediately before Guest in both induced branches, Dining->Foyer remains
selected with endpoint_eligible=true. Foyer is asserted, healthy and not cadence
warned, started00:04:52.523361 with traversal_valid_until00:05:37.523361. Guest's
detection follows11.159829s later, before that trust frontier. Bottom/Left remain
baseline with no episode. With the new edge, normal selection produces the
confirmed Dining->Foyer->Guest route and evidence-provenance acquisition; Guest
publishes one ON at00:05:03 and no OFF through the report. Existing retention
therefore works in this counterfactual without any policy or timer change.

The exact induced probe code and output are retained in Homelab
`tmp/guest-bedroom-warning-20261102/arrival-map-probe-20261103.md`,
SHA256:9c36d834116528dc0f931310e6dd7f5938ead820f038d8fa8e3f12af91fa07cb.
The unchanged full repository map used for the follow-up has SHA256
7e5a2175442d11d5387f9917c952eb3abe91726a9a237170c5ec7a57853af96f.

Important limitation: the changed graph also changes later path allocation. In
the induced counterfactual, Left is OFF at00:19:12 rather than satisfying the
frozen scenario's Guest->Left/publicLeftON supplementary qualifications. This
is not a pass of the complete frozen incident, and is not validation of a
configuration repair. Any proposed repair must explicitly reconcile captured
topology and those qualifications under GOV005, preserve the original evidence,
and run its required gates. No original sensor input, test, map, production
source, or Home Assistant state was modified by these probes.

Conclusion: the Foyer path was not timed out or dropped before Guest in the
reproduced sequence. Selection rejects Guest because its configured neighbors
provide no observation and Foyer is not one of them. The floor plan supplies a
concrete reason to verify/correct the sensor adjacency instead of relaxing
path-required acquisition. Hardware failure and the original loaded graph are
not proven; the saved status exposes neither adjacency nor a current map hash.

## Frozen Scenario And Disconfirming Check

Permanent incident module and matching primary:
`tests/incidents/test_inc_2026_11_02_2356z_guest_bedroom_missed_activation.py`.
It embeds all138 recorder changes/17entities/11 physical nodes/count2 and the
induced map with configured weights, roles, alias groups, adjacency,15s directed
timings and zone occupancy behaviors. It has no ignored-file dependency.

RuntimeScenario uses actual normalization, registered timers and public active
entities. Synthetic cold inference starts23:55 with recorded boundary levels;
initial ON levels are not fabricated fresh positives. Historical posterior,
generation numbering, registration phase and receipt time are not reconstructed.
Delivery is at recorder event time. Live processing-time microsecond lag remains
in source evidence, not silently presented as replayed receipt timing.

The cheap disconfirming check was the exact runtime replay. It verifies all138
normalized inputs, Guest->Left selected pair and actual Left ON publication at
00:19:12.371936, then expects public guest active at the report checkpoint.
All qualifiers pass and the final public assertion fails with no guest edges,
explanation acquisition_unauthorized. No exact human entry time, historical
probability, physical actuation or changed warning behavior is asserted.

Exact command: `.venv/bin/pytest -n0 --no-cov -q
tests/incidents/test_inc_2026_11_02_2356z_guest_bedroom_missed_activation.py`.
Confirmed pre-fix RED:1failed in2.07s at final active assertion. Initial2.04s
attempt failed fixture row-count137/138 and is not red proof. Structured source
comparison identified only omitted left still_target OFF00:59:03.723907, restored
before proof. Ruff subsequently added only the missing final newline. The final
combined run with unchanged September15 occupied-room warning regression is
1failed/1passed in2.21s; XML verifies both complete cases and no errors/skips.

## Scope, Alternatives And Authority

The earlier adjacent-source recovery proposal is superseded by the user's
clarification: the guest bedroom should already have qualified for activity and
then benefited from existing retention. Do not solve this by discounting Living
Room Left, treating every radar burst as departure, or waiting for it to
retroactively activate the guest bedroom.

The subsequent local-presence admission proposal is also rejected by the user's
latest clarification: fresh presence is not independently trustworthy without
a path. Preserve isolated-positive and unsupported-jump OFF expectations. Do not
ask for their amendment merely to make the guest regression pass.

Current diagnosis: this captured failure is an unrecognized incoming arrival,
not release of a previously acquired guest destination. The original audit's
false->false arrival, absence of guest active transitions, expanded source
history, and map-only experiments support it. An earlier retained guest
acquisition or accepted incoming route would disconfirm that distinction.
Missing Foyer/Guest adjacency is sufficient for the replayed failure; verify
actual detector coverage and loaded topology before selecting a configuration
repair. A physically necessary route is not itself a recorded sensor path.
No new duration, probability calibration, fabricated intermediate observation,
or pathless acquisition is authorized.

### Independently Reviewed Activation Conflict

November3 preimplementation read-only review found a concrete acceptance
conflict, verified against the retained test bodies and a scoped unchanged run:

- `tests/incidents/test_inc_2026_08_20_1700z_isolated_gym_assertion_never_activates.py`
  feeds a real ordinary Gym mmWave ON at17:06:39.497066/count2 without a preceding
  adjacent source, then requires inactive at17:11:14 and18:00. It is the same
  stay_presence/fresh/trustworthy/above-threshold local shape as Guest. The
  retained replay does not contain a Gym OFF; do not infer physical occupancy
  or add an OFF from outside evidence without explicit test disposition.
- `tests/test_unsupported_jump_warning.py::test_public_unsupported_jump_warning`
  at counts1/2 requires C stay inactive after A->B and a fresh C detection with
  the middle unobserved, despite all nodes being presence sensors. The related
  rejected-target/restore controls explicitly prohibit later source activation.
- PATH005 forbids inactive acquisition from physical retention alone; PATH006
  forbids targetON through missing intermediate evidence. A new local-presence
  admission contract must explicitly distinguish local activation from invented
  traversal while reconciling their existing targetOFF public expectations.

Verification command: `.venv/bin/pytest -n0 --no-cov -q
tests/incidents/test_inc_2026_11_02_2356z_guest_bedroom_missed_activation.py
tests/incidents/test_inc_2026_08_20_1700z_isolated_gym_assertion_never_activates.py
tests/test_unsupported_jump_warning.py -k 'test_inc_ or
test_public_unsupported_jump_warning'`:1failed Guest/3passed controls,
44deselected,2.21s. No production edit occurred. The review did not establish a
non-arbitrary local discriminator preserving all frozen expectations. The
user's legitimate-occupancy goal is clear, but changing those specific prior
OFF expectations needs explicit agreement under GOV005 before implementation.
The user's subsequent response rejects that proposed policy change, so this is
a rejected alternative, not a pending request to relax the safeguards.

Inputs and public expectation are frozen after red proof. Existing incident
oracles, replay helpers, production, calibration and live Home Assistant remain
unchanged. No room/person-specific fix, synthetic input, stale ON reseeding,
warning-only suppression or high-belief bypass is authorized. The user requested
the active outcome and scenario, not blanket permission to weaken PATH004.

A future generic repair must preserve path-required acquisition and address a
verified arrival or retention defect, including count0/1/2, aliases, startup,
unknown/unavailable, genuine isolated positives, same-zone multiplicity, unrelated
remote movement and restart. The current trace does not justify changing
PATH004's source prohibition. A warning-label change alone cannot pass this
public active scenario. If no qualifying incoming evidence can be established,
retain that evidence gap rather than claim a retention fix or invent movement.

No persistence migration, deployment or rollback occurs in this capture-only
scope. Future repair needs tracked red-before-implementation proof, inverse and
boundary checks, full explicit incident corpus, full Python coverage, frontend,
Ruff/mypy, applicable build/benchmark/diff gates and independent review. No broad
suite or global-green claim is made for this intentionally red capture.

## Approved Local Configuration Repair

November3 explicit user approval: "I'm fine adding a graph from foyer to guest."
Implement only reciprocal adjacency between `foyer_pir_motion` and
`guest_bedroom_motion` in Homelab `home-assistant/predictive-controls-map.yaml`;
update its existing last_updated field to November3. Preserve all prior edges,
aliases, interaction nodes, profiles, thresholds, timers, counts and package
source. This is configured graph data under PATH003/006, not an exception to
path-required acquisition or a normative model-rule amendment.

The two entries refer to the motion nodes only; no Guest interaction-node edge
is approved by this scoped change. No captured sensor, startup level, map,
timing, count or assertion is edited in the permanent incident. In particular,
its later Left qualification remains on the original captured graph. The new
actual-map probe is separate: do not relabel it as a pass of that primary or
relax the isolated Gym/missing-middle OFF requirements. The user's approval is
for configuration, not for modifying those frozen public expectations.

Regression proof precedes the map edit: run the existing recorded138-input
sequence/count2 through RuntimeScenario using the actual full on-disk map, with
no in-memory edge insertion. Require public Guest ON at00:05:03 and still ON at
01:01:04; verify exact normalized inputs. Before the edit it must fail at the
public acquisition goal. Immediately after the edit rerun that same probe.
Then run the approved YAML validator, reciprocal-map parser, isolated-presence
inverse and count0/1 boundaries. Check the reverse Guest->Foyer path at counts1/2
and exactly one Guest ON/no intervening OFF through the report in the corrected
138-input branches. Record later Left allocation rather than claim
that the old embedded-map scenario has passed. No new permanent incident file
or Home Assistant access script is needed; retain the existing capture intact.

Rollout is a separate live operation and is not authorized here. Record the
pending deployment in Homelab recommendations; do not claim Home Assistant has
loaded the repository map. Rollback restores only the approved pair of new
edges and the metadata date, preserving unrelated changes and prior snapshots.
Adjacency is part of inference compatibility: inference saved under the old
graph will reject under the corrected graph, including embedded prediction
learning. Preserve matching configuration and storage backups before loading,
because normal saves can replace stored state soon afterward. Home Assistant
loads config-entry YAML, not this repository file automatically;
there is no schema conversion or storage edit in this task. Bootstrap ON levels
do not reconstruct the earlier arrival, and an already occupied room must not
be forcibly activated by replaying historical events into live Home Assistant.
Do not promise immediate recovery after reload without fresh qualifying
observations. Rollback uses matching prior configuration and preserved state,
not an unreviewed full-file reset. Leave staircase hardware settings unchanged.
Reconcile local configuration results in SPECIFICATION.md; keep this working
spec while the old-map primary remains red or operational requirements remain
unresolved. Package full-suite conformance is not claimed for a YAML-only edit.

Configured-map pre-fix proof executed: Pylance RunCodeSnippet, repository
`.venv/bin/python`, full map loaded from the actual Homelab YAML, exact138
normalized inputs. It exits1 at `assert arrival_active`, "Configured map rejects
the recorded Foyer-to-Guest arrival"; printed arrival=false/final=false/no Guest
edges. This is a genuine public failure, separate from the hypothetical probes.

After the actual map edit, the pinned probe exits0: exact138 normalized inputs,
arrival=true/final=true and exactly one Guest ON at00:05:03.683190, no OFF.
Additional schema/reciprocity and seven actual-map cases pass: recorded replay
at counts0/1/2 (Guest OFF/ON/ON, no extra edges); isolated Guest at counts1/2
stays OFF; reverse Guest->Foyer at counts1/2 acquires only Foyer. Left is OFF at
00:19:12 in corrected-map recorded replays, as already disclosed; no complete
frozen-scenario pass is claimed. Approved local YAML validation and staged/
unstaged map whitespace checks pass. No editor diagnostics on the YAML.
Independent final read-only review passes the local configuration phase only:
exactly two reciprocal motion-node entries plus metadata date, no package/test
changes, canonical status accurate, and frozen capture/live boundaries intact.

Exact configured-map probe body, executed with Pylance RunCodeSnippet, working
directory Predictive Controls and its `.venv/bin/python`; rerun unchanged after
the YAML edit:

```python
import json
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
import yaml
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import RuntimeScenario
incident = import_module('tests.incidents.test_inc_2026_11_02_2356z_guest_bedroom_missed_activation')
mapping = yaml.safe_load(Path('../homelab/home-assistant/predictive-controls-map.yaml').read_text())
inputs = tuple(SensorInput(incident._ENTITIES[int(index)], state, datetime.fromisoformat(f'2026-11-{clock}+00:00')) for clock, index, state in (row.split() for row in incident._INPUTS.strip().splitlines()))
initial = {entity: 'on' if index in {6, 8, 9, 13} else 'off' for index, entity in enumerate(incident._ENTITIES)}
guest_at = datetime.fromisoformat('2026-11-03T00:05:03.683190+00:00')
report_at = datetime.fromisoformat('2026-11-03T01:01:04.222491+00:00')
with RuntimeScenario(datetime(2026, 11, 2, 23, 55, tzinfo=UTC)) as scenario:
  replay = scenario.create(PredictiveMap.from_mapping(mapping), 2, initial_states=initial)
  for event in inputs:
    replay.observe(event)
    if event.event_at == guest_at:
      arrival_active = replay.view().active('guest_bedroom')
  final_active = replay.advance(report_at).active('guest_bedroom')
  assert replay.normalized_inputs == list(inputs) and len(inputs) == 138
  print(json.dumps({'actual_repository_map': True, 'inputs': len(inputs), 'arrival_active': arrival_active, 'final_active': final_active, 'guest_edges': [{'at': edge.at.isoformat(), 'active': edge.active} for edge in replay.edges_for('guest_bedroom')]}))
  assert arrival_active, 'Configured map rejects the recorded Foyer-to-Guest arrival'
  assert final_active, 'Configured map fails to retain Guest through the report'
```

Configuration-repair hardening is complete: exactly three full passes for this
new scoped design, separate from the earlier three capture-only passes.
Factual/architectural rewrites pinned motion-only scope and frozen artifacts;
failure/operations rewrites covered config-entry loading, whole-inference
compatibility, backups, bootstrap and rollback; implementation/proof rewrites
pinned the exact RED/green probe, no-OFF and reverse-path checks. Independent
read-only pre-review conditions are incorporated. No incident/global-green or
live-deployment approval is implied.

## Tracking And Disposition

| Phase                                        | Status   | Validated evidence                                                                                                                        | Next executable step                                                |
| -------------------------------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Regression proof                             | Complete | Exact RED at public guest output; all138 inputs and later pair/public Left edge qualified; final XML/log retained                         | Preserve frozen incident inputs and public oracle                   |
| Incoming-path investigation                  | Complete | Approved14-entity expanded history, both floor plans, independent topology review, two induced and three full-map/control probe branches  | Confirm detector coverage and original loaded-map adjacency         |
| Configured-map regression proof              | Complete | Actual-map probe exits1 at public arrival goal;138 normalized inputs, arrival/final bothfalse, no Guest edges                             | Rerun unchanged immediately after map edit                          |
| Local configuration repair                   | Complete | Actual map patched; unchanged probe RED->green, seven boundaries/schema/YAML/editor checks and independent final review PASS              | Local scope complete; separately authorize live loading             |
| Live deployment and incident closure         | Blocked  | No live write authorized; captured original-map scenario remains frozen                                                                   | Separately authorize loading and reconcile remaining incident scope |
| Capture validation and status reconciliation | Complete | Scoped Ruff/default mypy1file/editor clean; ordered source/startup/map equality; XML1fail/1pass; diff clean; canonical/README status open | Keep this working spec while unresolved                             |

Exactly three capture-only full critique/rewrite passes completed: factual/architectural
distinguished missing arrival adjacency from later successful pairing and named
PATH004; failure/operations preserved startup/alias/event ordering and unknown
receipt/timer phase; implementation/proof fixed identity, normalized-input
equality, real positive publication and final public oracle without a
warning-suppression loophole. The approved configuration phase above completed
its own three scoped hardening passes before the actual map edit.

SPECIFICATION.md preamble/Section19.0 and README now distinguish this open red
scenario from the prior3440-case green baseline. Normative behavior is unchanged.
The approved local map correction is validated separately in Section19.0;
Homelab recommendations record pending loading and backup/startup cautions.
Retain this working spec: the old-map primary and complete incident scope remain
unresolved, with no live deployment authorized. No broad Python/frontend/static/
benchmark gates were rerun for the YAML-only change, and no package fix or global
green is claimed. Keep the original incident regression permanently unchanged.