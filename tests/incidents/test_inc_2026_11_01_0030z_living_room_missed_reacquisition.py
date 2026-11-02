"""User-reported issue: "it turned off the light while she was still inside".
User expected: uninterrupted living-room lighting while Shaila remained inside.
Observed: right active OFF00:30:48.537020Z, light OFF00:30:48.992452Z;
fresh radar ON00:30:53.992028Z did not restore activity. Both arrived home;
Alex went upstairs while Shaila stayed downstairs. Human entry/exit times unknown.
Source: Oct31 local/Nov1 UTC report; approved recorder/audit/automation evidence
in Homelab tmp/living-room-20261031-*.json, 194 captured changes across14 entities.
Test scope: actual RuntimeScenario public control signal, not physical actuation.
Synthetic all-OFF cold startup and timer phase do not reconstruct the historical
posterior or assign people to tracks. Full/induced maps reproduced OFF00:30:50Z.
All captured inputs remain; continuous ON is required only22:06..31:06, not an
invented claim that Shaila stayed through the later dining input or recovery.
"""

from datetime import UTC, datetime

import pytest
import yaml

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, RuntimeScenario

_ENTITIES = (
    "binary_sensor.alex_office_alex_office_motion_motion_detection",
    "binary_sensor.bottom_of_staircase_motion_motion_detection",
    "binary_sensor.dining_room_motion_motion_detection",
    "binary_sensor.entrance_mmwave_dimmer_motion_detection",
    "binary_sensor.foyer_pir_motion_motion_detection",
    "binary_sensor.ground_floor_bathroom_laundry_room_motion_detection",
    "binary_sensor.island_monitor_radar_moving_target",
    "binary_sensor.island_monitor_radar_still_target",
    "binary_sensor.island_monitor_radar_target",
    "binary_sensor.island_monitor_radar_zone_3_occupancy",
    "binary_sensor.master_bedroom_closet_motion_motion_detection",
    "binary_sensor.master_bedroom_entrance_pir_motion_motion_detection",
    "binary_sensor.mmwave_dimmer_motion_detection_2",
    "binary_sensor.top_of_staircase_motion_motion_detection",
)

_MAP = """
nodes:
  entrance_mmwave_dimmer:
    floor: first_floor
    zone: entrance_hallway
    role: transition_gate
    entities: {mmwave: binary_sensor.entrance_mmwave_dimmer_motion_detection}
    adjacent: [ground_floor_bathroom_laundry_room, dining_room_motion,
      kitchen_overhead_mmwave_dimmer]
    initial_weight: 0.75
  ground_floor_bathroom_laundry_room:
    floor: first_floor
    zone: first_floor_bathroom_laundry_room
    role: room_occupancy
    entities:
      motion: binary_sensor.ground_floor_bathroom_laundry_room_motion_detection
    adjacent: [entrance_mmwave_dimmer]
    initial_weight: 0.8
  dining_room_motion:
    floor: first_floor
    zone: dining_room
    role: transition_gate
    entities: {mmwave: binary_sensor.dining_room_motion_motion_detection}
    adjacent: [entrance_mmwave_dimmer, kitchen_overhead_mmwave_dimmer,
      living_room_fireplace_right, foyer_pir_motion]
    transition_seconds: {kitchen_overhead_mmwave_dimmer: 15, foyer_pir_motion: 15}
    initial_weight: 0.75
  kitchen_overhead_mmwave_dimmer:
    floor: first_floor
    zone: kitchen
    role: room_occupancy
    entities: {mmwave: binary_sensor.mmwave_dimmer_motion_detection_2}
    adjacent: [entrance_mmwave_dimmer, dining_room_motion]
    transition_seconds: {dining_room_motion: 15}
    initial_weight: 0.8
  foyer_pir_motion:
    floor: first_floor
    zone: foyer
    role: transition_gate
    entities: {motion: binary_sensor.foyer_pir_motion_motion_detection}
    adjacent: [dining_room_motion, bottom_of_staircase_motion]
    transition_seconds: {dining_room_motion: 15}
    initial_weight: 0.85
  living_room_fireplace_right:
    floor: first_floor
    zone: living_room_right
    role: anchor_sensor
    entities:
      target: binary_sensor.island_monitor_radar_target
      moving_target: binary_sensor.island_monitor_radar_moving_target
      still_target: binary_sensor.island_monitor_radar_still_target
      zone_3_occupancy: binary_sensor.island_monitor_radar_zone_3_occupancy
    adjacent: [dining_room_motion]
    initial_weight: 0.9
  bottom_of_staircase_motion:
    floor: first_floor
    zone: staircase_bottom
    role: transition_gate
    entities: {mmwave: binary_sensor.bottom_of_staircase_motion_motion_detection}
    adjacent: [foyer_pir_motion, top_of_staircase_motion]
    initial_weight: 0.85
  top_of_staircase_motion:
    floor: second_floor
    zone: upstairs_hallway
    role: transition_gate
    entities: {mmwave: binary_sensor.top_of_staircase_motion_motion_detection}
    adjacent: [bottom_of_staircase_motion, alex_office_motion,
      master_bedroom_entrance]
    initial_weight: 0.85
  alex_office_motion:
    floor: second_floor
    zone: alex_office
    role: room_occupancy
    entities: {mmwave: binary_sensor.alex_office_alex_office_motion_motion_detection}
    adjacent: [top_of_staircase_motion]
    initial_weight: 0.75
  master_bedroom_entrance:
    floor: second_floor
    zone: master_bedroom_entrance
    role: transition_gate
    entities:
      motion: binary_sensor.master_bedroom_entrance_pir_motion_motion_detection
    adjacent: [master_bedroom_closet, top_of_staircase_motion]
    initial_weight: 0.8
  master_bedroom_closet:
    floor: second_floor
    zone: master_bedroom_closet
    role: subzone_occupancy
    entities: {mmwave: binary_sensor.master_bedroom_closet_motion_motion_detection}
    adjacent: [master_bedroom_entrance]
    initial_weight: 0.8
zones:
  entrance_hallway:
    {floor: first_floor, role: transition_gate, occupancy_behavior: transient}
  first_floor_bathroom_laundry_room:
    {floor: first_floor, role: room_occupancy, occupancy_behavior: sustained}
  dining_room:
    {floor: first_floor, role: transition_gate, occupancy_behavior: transient}
  kitchen:
    {floor: first_floor, role: room_occupancy, occupancy_behavior: sustained}
  foyer:
    {floor: first_floor, role: transition_gate, occupancy_behavior: transient}
  living_room_right:
    {floor: first_floor, role: anchor_sensor, occupancy_behavior: sticky}
  staircase_bottom:
    {floor: first_floor, role: transition_gate, occupancy_behavior: transient}
  upstairs_hallway:
    {floor: second_floor, role: transition_gate, occupancy_behavior: transient}
  alex_office:
    {floor: second_floor, role: room_occupancy, occupancy_behavior: sustained}
  master_bedroom_entrance:
    {floor: second_floor, role: transition_gate, occupancy_behavior: transient}
  master_bedroom_closet:
    {floor: second_floor, role: subzone_occupancy, occupancy_behavior: sticky}
"""

_INPUTS = """
00:09:06.751169 3 on
00:09:13.676872 2 on
00:09:13.735643 12 on
00:09:49.970463 12 off
00:09:54.533306 4 on
00:09:56.152466 12 on
00:10:05.174463 3 off
00:10:07.776153 4 off
00:10:18.523867 3 on
00:11:01.933790 4 on
00:11:13.890172 4 off
00:11:36.516285 3 off
00:11:45.143306 3 on
00:12:01.587769 4 on
00:12:10.026522 3 off
00:12:12.992548 4 off
00:12:18.877979 3 on
00:12:48.738418 3 off
00:12:55.137323 12 off
00:12:56.770638 12 on
00:13:12.433217 12 off
00:13:12.622019 12 on
00:13:32.825193 3 on
00:13:49.643792 3 off
00:14:36.976719 4 on
00:14:40.262578 3 on
00:14:48.258955 4 off
00:14:56.522166 3 off
00:14:56.528992 4 on
00:14:58.611404 8 on
00:14:58.615835 7 on
00:14:58.618610 9 on
00:15:00.248473 6 on
00:15:00.718755 6 off
00:15:00.722404 9 off
00:15:06.008847 8 off
00:15:06.012339 7 off
00:15:08.294180 4 off
00:15:09.109150 8 on
00:15:09.113652 7 on
00:15:09.116474 9 on
00:15:09.560092 2 off
00:15:11.306631 6 on
00:15:11.310352 7 off
00:15:11.313175 9 off
00:15:12.944582 6 off
00:15:12.948312 7 on
00:15:12.951786 2 on
00:15:17.608300 8 off
00:15:17.612332 7 off
00:15:18.566905 4 on
00:15:32.302502 4 off
00:15:36.767520 4 on
00:15:46.359758 4 off
00:16:27.380081 12 off
00:16:47.768540 12 on
00:17:11.770818 4 on
00:17:24.529389 4 off
00:17:35.500679 12 off
00:17:35.595155 12 on
00:18:21.043960 4 on
00:18:21.782461 3 on
00:18:33.647091 4 off
00:18:45.183139 3 off
00:18:54.911499 2 off
00:19:17.102835 2 on
00:19:31.610979 4 on
00:19:54.786814 4 off
00:20:05.392290 3 on
00:20:23.045158 4 on
00:20:34.857210 4 off
00:20:35.443323 5 on
00:20:46.059791 4 on
00:20:46.304323 3 off
00:20:46.713753 12 off
00:20:57.746210 2 off
00:21:02.904504 4 off
00:21:58.036288 3 on
00:21:59.769452 2 on
00:22:01.795192 12 on
00:22:06.422096 8 on
00:22:06.429447 7 on
00:22:06.434019 9 on
00:22:09.924252 5 off
00:22:10.683352 12 off
00:22:15.536170 3 off
00:22:27.306117 12 on
00:22:31.796111 8 off
00:22:31.801114 7 off
00:22:31.805234 9 off
00:22:43.204705 2 off
00:22:54.813546 2 on
00:22:59.098512 8 on
00:22:59.104767 7 on
00:22:59.108811 9 on
00:23:01.103271 6 on
00:23:03.119814 6 off
00:23:07.034508 12 off
00:23:10.690742 2 off
00:23:13.394587 6 on
00:23:13.399565 7 off
00:23:15.424297 9 off
00:23:17.494679 6 off
00:23:17.499242 7 on
00:23:17.502200 9 on
00:23:17.802354 2 on
00:23:22.501766 12 on
00:23:22.805534 8 off
00:23:22.809318 7 off
00:23:22.812126 9 off
00:23:25.242872 3 on
00:23:35.707813 4 on
00:23:37.456682 12 off
00:23:47.188177 4 off
00:23:49.218632 8 on
00:23:49.224880 7 on
00:23:49.228095 9 on
00:23:50.997517 6 on
00:23:53.023897 6 off
00:23:53.028770 9 off
00:23:53.101341 6 on
00:23:53.651284 4 on
00:23:55.343090 6 off
00:23:58.300297 9 on
00:24:00.001132 3 off
00:24:05.218417 4 off
00:24:17.097908 12 on
00:24:29.762485 2 off
00:24:35.022913 2 on
00:24:48.199042 3 on
00:25:10.368846 4 on
00:25:19.124322 12 off
00:25:23.285898 3 off
00:25:23.352541 4 off
00:25:24.989780 8 off
00:25:24.994345 7 off
00:25:24.997535 9 off
00:25:46.594594 12 on
00:25:57.878459 4 on
00:26:00.780298 1 on
00:26:05.039542 13 on
00:26:05.258702 12 off
00:26:09.541435 2 off
00:26:11.471247 11 on
00:26:13.095101 10 on
00:26:16.445486 4 off
00:26:16.538313 1 off
00:26:18.488274 0 on
00:26:25.508554 13 off
00:26:27.798356 11 off
00:26:45.181678 10 off
00:30:53.992028 8 on
00:30:53.998096 7 on
00:30:54.002466 9 on
00:31:00.289706 6 on
00:31:01.291613 9 off
00:31:03.396074 6 off
00:31:06.593370 9 on
00:31:06.959904 2 on
00:31:12.902267 6 on
00:31:12.907786 9 off
00:31:14.928871 6 off
00:31:17.088585 6 on
00:31:19.199988 6 off
00:31:21.287223 9 on
00:31:27.494121 8 off
00:31:27.499160 7 off
00:31:27.503688 9 off
00:31:31.557218 12 on
00:31:43.551525 2 off
00:32:22.157410 2 on
00:32:33.032000 2 off
00:32:40.681542 2 on
00:32:51.056827 2 off
00:33:11.725308 2 on
00:33:22.991090 8 on
00:33:22.999215 6 on
00:33:23.991702 6 off
00:33:23.996590 7 on
00:33:24.000774 9 on
00:33:26.029329 6 on
00:33:26.090715 6 off
00:33:26.095963 9 off
00:33:28.194032 9 on
00:33:29.853224 12 off
00:33:34.561415 6 on
00:33:36.491441 6 off
00:33:38.588080 6 on
00:33:40.245956 6 off
00:33:42.877147 2 off
00:33:43.790410 6 on
00:33:45.485656 6 off
00:33:49.088624 6 on
00:33:50.095132 6 off
"""


@pytest.mark.scenario
@pytest.mark.target_model
def test_inc_2026_11_01_0030z_living_room_missed_reacquisition() -> None:
    predictive_map = PredictiveMap.from_mapping(yaml.safe_load(_MAP))
    expected_inputs = tuple(
        SensorInput(
            _ENTITIES[int(index)], state,
            datetime.fromisoformat(f"2026-11-01T{clock}+00:00"),
        )
        for clock, index, state in (
            row.split() for row in _INPUTS.strip().splitlines()
        )
    )
    start = datetime(2026, 11, 1, 0, 22, 6, 422096, tzinfo=UTC)
    end = datetime(2026, 11, 1, 0, 31, 6, tzinfo=UTC)
    with RuntimeScenario(datetime(2026, 11, 1, tzinfo=UTC)) as scenario:
        replay = scenario.create(
            predictive_map, 2, initial_states=dict.fromkeys(_ENTITIES, "off"),
        )
        for event in expected_inputs:
            published = replay.observe(event)
            if event.event_at == start:
                assert published.active("living_room_right")
        replay.advance(datetime(2026, 11, 1, 0, 34, tzinfo=UTC))
        assert len(expected_inputs) == 194
        assert replay.normalized_inputs == list(expected_inputs)
        assert ActiveEdge(
            datetime(2026, 11, 1, 0, 26, 18, 488274, tzinfo=UTC),
            "alex_office", True,
        ) in replay.input_edges_for("alex_office")
        forbidden = tuple(
            edge for edge in replay.edges_for("living_room_right")
            if start <= edge.at <= end and not edge.active
        )
        assert not forbidden, forbidden
