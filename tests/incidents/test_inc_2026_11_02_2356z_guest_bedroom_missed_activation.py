"""User-reported issue: continuous guest-bedroom presence warnings while occupied.
User expected: "Why is it not active? It should be right?" Shaila is really there.
Observed: guest presence ON00:05:03Z, about95% belief but active false; warning
after path support loss00:42:05Z plus600s. No physical light failure was reported.
Source: November2 local/November3 UTC report and approved read-only Homelab
tmp/guest-bedroom-warning-20261102/{status,history}.json. Status SHA256
ea3a8da939cf534b2778c9d23447afddf4d6b32862bd874a79f0b8b88ac04eaa;
history SHA2564365137b4a9ec3955749128eb94792d2feb419e2ffc8d9804e7782852a148fa3.
Test scope: real runtime/public active signal, not person tracking or actuation.
Retain138 recorder changes/17entities/11physical nodes/count2; first captured
callback23:56:09.627305Z determines incident identity. Recorder boundary levels
at23:55 are synthetic cold-inference startup, not fresh positives or a restored
historical posterior. Receipt/timer phase is synthetic; event times are exact.
The final public occupied checkpoint is sourced from the report/status. The
later Guest->Left path and Left ON edge are supplementary causal qualifications.
The warning is documented, not an expectation that it be hidden to recover active.
"""

from datetime import UTC, datetime

import pytest
import yaml

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, RuntimeScenario

_ENTITIES = (
    "binary_sensor.guest_bedroom_guest_bedroom_motion_motion_detection",
    "binary_sensor.bottom_of_staircase_motion_motion_detection",
    "binary_sensor.apollo_msr_2_2cb8b0_radar_target",
    "binary_sensor.apollo_msr_2_2cb8b0_radar_moving_target",
    "binary_sensor.apollo_msr_2_2cb8b0_radar_still_target",
    "binary_sensor.apollo_msr_2_2cb8b0_radar_zone_3_occupancy",
    "binary_sensor.island_monitor_radar_target",
    "binary_sensor.island_monitor_radar_moving_target",
    "binary_sensor.island_monitor_radar_still_target",
    "binary_sensor.island_monitor_radar_zone_3_occupancy",
    "binary_sensor.foyer_pir_motion_motion_detection",
    "binary_sensor.dining_room_motion_motion_detection",
    "binary_sensor.top_of_staircase_motion_motion_detection",
    "binary_sensor.alex_office_alex_office_motion_motion_detection",
    "binary_sensor.master_bedroom_entrance_pir_motion_motion_detection",
    "binary_sensor.master_bedroom_closet_motion_motion_detection",
    "binary_sensor.upstairs_bathroom_motion_motion_detection",
)

_MAP = """
nodes:
  dining_room_motion:
    floor: first_floor
    zone: dining_room
    role: transition_gate
    entities: {mmwave: binary_sensor.dining_room_motion_motion_detection}
    adjacent: [living_room_fireplace_right, foyer_pir_motion]
    transition_seconds: {foyer_pir_motion: 15}
    initial_weight: 0.75
  foyer_pir_motion:
    floor: first_floor
    zone: foyer
    role: transition_gate
    entities: {motion: binary_sensor.foyer_pir_motion_motion_detection}
    adjacent: [dining_room_motion, bottom_of_staircase_motion]
    transition_seconds: {dining_room_motion: 15}
    initial_weight: 0.85
  living_room_fireplace_left:
    floor: first_floor
    zone: living_room_left
    role: anchor_sensor
    entities:
      target: binary_sensor.apollo_msr_2_2cb8b0_radar_target
      moving_target: binary_sensor.apollo_msr_2_2cb8b0_radar_moving_target
      still_target: binary_sensor.apollo_msr_2_2cb8b0_radar_still_target
      zone_3_occupancy: binary_sensor.apollo_msr_2_2cb8b0_radar_zone_3_occupancy
    adjacent: [guest_bedroom_motion, living_room_fireplace_right]
    initial_weight: 0.9
  living_room_fireplace_right:
    floor: first_floor
    zone: living_room_right
    role: anchor_sensor
    entities:
      target: binary_sensor.island_monitor_radar_target
      moving_target: binary_sensor.island_monitor_radar_moving_target
      still_target: binary_sensor.island_monitor_radar_still_target
      zone_3_occupancy: binary_sensor.island_monitor_radar_zone_3_occupancy
    adjacent: [dining_room_motion, living_room_fireplace_left]
    initial_weight: 0.9
  bottom_of_staircase_motion:
    floor: first_floor
    zone: staircase_bottom
    role: transition_gate
    entities: {mmwave: binary_sensor.bottom_of_staircase_motion_motion_detection}
    adjacent: [foyer_pir_motion, guest_bedroom_motion, top_of_staircase_motion]
    initial_weight: 0.85
  guest_bedroom_motion:
    floor: first_floor
    zone: guest_bedroom
    role: room_occupancy
    entities:
      mmwave: binary_sensor.guest_bedroom_guest_bedroom_motion_motion_detection
    adjacent: [bottom_of_staircase_motion, living_room_fireplace_left]
    initial_weight: 0.75
  top_of_staircase_motion:
    floor: second_floor
    zone: upstairs_hallway
    role: transition_gate
    entities: {mmwave: binary_sensor.top_of_staircase_motion_motion_detection}
    adjacent: [bottom_of_staircase_motion, upstairs_bathroom_motion,
      alex_office_motion, master_bedroom_entrance]
    initial_weight: 0.85
  upstairs_bathroom_motion:
    floor: second_floor
    zone: upstairs_bathroom
    role: room_occupancy
    entities: {mmwave: binary_sensor.upstairs_bathroom_motion_motion_detection}
    adjacent: [top_of_staircase_motion]
    initial_weight: 0.7
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
  dining_room:
    {floor: first_floor, role: transition_gate, occupancy_behavior: transient}
  foyer:
    {floor: first_floor, role: transition_gate, occupancy_behavior: transient}
  living_room_left:
    {floor: first_floor, role: anchor_sensor, occupancy_behavior: sticky}
  living_room_right:
    {floor: first_floor, role: anchor_sensor, occupancy_behavior: sticky}
  staircase_bottom:
    {floor: first_floor, role: transition_gate, occupancy_behavior: transient}
  guest_bedroom:
    {floor: first_floor, role: room_occupancy, occupancy_behavior: sustained}
  upstairs_hallway:
    {floor: second_floor, role: transition_gate, occupancy_behavior: transient}
  upstairs_bathroom:
    {floor: second_floor, role: room_occupancy, occupancy_behavior: sticky}
  alex_office:
    {floor: second_floor, role: room_occupancy, occupancy_behavior: sustained}
  master_bedroom_entrance:
    {floor: second_floor, role: transition_gate, occupancy_behavior: transient}
  master_bedroom_closet:
    {floor: second_floor, role: subzone_occupancy, occupancy_behavior: sustained}
"""

_INPUTS = """
02T23:56:09.627305 7 on
02T23:56:11.347943 7 off
02T23:56:13.378179 7 on
02T23:56:15.073708 7 off
02T23:57:21.034009 6 off
02T23:57:21.039090 8 off
02T23:57:21.045830 9 off
03T00:00:58.730982 6 on
03T00:00:58.737523 8 on
03T00:00:58.741767 9 on
03T00:01:25.921912 12 on
03T00:01:29.391327 14 on
03T00:01:37.890836 12 off
03T00:01:43.381514 15 on
03T00:01:45.503952 14 off
03T00:01:45.966011 13 off
03T00:02:15.898994 12 on
03T00:02:16.390614 14 on
03T00:02:23.699633 16 on
03T00:02:29.037572 12 off
03T00:02:29.580653 14 off
03T00:02:31.680677 12 on
03T00:02:45.438022 16 off
03T00:02:51.243976 15 off
03T00:02:52.915265 6 off
03T00:02:52.919221 8 off
03T00:02:52.923772 9 off
03T00:02:55.055852 16 on
03T00:02:57.623145 6 on
03T00:02:57.628234 8 on
03T00:02:57.631511 9 on
03T00:02:59.647253 12 off
03T00:03:36.917726 6 off
03T00:03:36.923080 8 off
03T00:03:36.927357 9 off
03T00:03:48.123225 6 on
03T00:03:48.131932 8 on
03T00:03:48.138594 9 on
03T00:03:50.229262 7 on
03T00:03:51.879386 7 off
03T00:04:02.927716 7 on
03T00:04:04.618302 7 off
03T00:04:26.020680 7 on
03T00:04:27.021320 7 off
03T00:04:36.321411 7 on
03T00:04:38.010551 7 off
03T00:04:38.515578 7 on
03T00:04:40.186018 7 off
03T00:04:42.616559 7 on
03T00:04:43.616550 7 off
03T00:04:45.620712 7 on
03T00:04:47.629217 7 off
03T00:04:48.509882 11 on
03T00:04:52.523361 10 on
03T00:04:55.016654 6 off
03T00:04:55.021820 8 off
03T00:04:55.025964 9 off
03T00:05:03.683190 0 on
03T00:05:04.250066 11 off
03T00:05:11.748313 10 off
03T00:08:33.174513 12 on
03T00:08:37.763650 14 on
03T00:08:44.825930 12 off
03T00:08:46.478162 12 on
03T00:08:48.415856 16 off
03T00:08:54.601458 16 on
03T00:08:59.250950 14 off
03T00:08:59.306317 12 off
03T00:09:18.442869 12 on
03T00:09:23.296774 13 on
03T00:09:29.886708 12 off
03T00:09:38.886017 16 off
03T00:09:57.710190 12 on
03T00:10:03.742846 10 on
03T00:10:08.942147 12 off
03T00:10:10.576012 11 on
03T00:10:19.328614 13 off
03T00:10:23.285377 10 off
03T00:10:27.441654 11 off
03T00:11:06.044373 11 on
03T00:11:16.945101 11 off
03T00:11:38.510589 11 on
03T00:11:50.482133 10 on
03T00:11:58.674366 12 on
03T00:12:01.469372 11 off
03T00:12:06.463114 10 off
03T00:12:09.006530 13 on
03T00:12:15.083294 12 off
03T00:19:12.371936 2 on
03T00:19:12.379749 4 on
03T00:19:17.473061 2 off
03T00:19:17.478189 4 off
03T00:28:46.760159 2 on
03T00:28:46.764872 4 on
03T00:28:52.058138 2 off
03T00:28:52.063008 4 off
03T00:33:24.690780 15 on
03T00:34:13.180368 15 off
03T00:37:13.532814 12 on
03T00:37:22.137294 16 on
03T00:37:25.458474 12 off
03T00:37:35.595004 13 off
03T00:38:37.868176 12 on
03T00:38:40.619828 13 on
03T00:38:47.873563 12 off
03T00:38:55.530626 16 off
03T00:39:01.093329 12 on
03T00:39:06.530576 16 on
03T00:39:11.503591 12 off
03T00:39:24.113731 13 off
03T00:39:29.748507 16 off
03T00:39:45.087443 2 on
03T00:39:45.093031 3 on
03T00:39:46.039660 3 off
03T00:39:46.043974 4 on
03T00:39:50.242013 2 off
03T00:39:50.246294 4 off
03T00:40:06.402521 16 on
03T00:40:38.702439 12 on
03T00:40:43.828438 13 on
03T00:40:50.014027 12 off
03T00:40:52.995358 16 off
03T00:40:55.743466 12 on
03T00:41:07.040549 12 off
03T00:41:15.608076 13 off
03T00:42:00.677255 10 on
03T00:42:05.938824 11 on
03T00:42:18.582256 10 off
03T00:42:38.255692 10 on
03T00:42:45.598371 12 on
03T00:42:48.677455 11 off
03T00:42:57.857153 13 on
03T00:42:58.651851 10 off
03T00:43:04.205307 12 off
03T00:58:58.418148 2 on
03T00:58:58.424708 4 on
03T00:59:03.719685 2 off
03T00:59:03.723907 4 off
"""


@pytest.mark.scenario
@pytest.mark.target_model
def test_inc_2026_11_02_2356z_guest_bedroom_missed_activation() -> None:
    predictive_map = PredictiveMap.from_mapping(yaml.safe_load(_MAP))
    expected_inputs = tuple(
        SensorInput(
            _ENTITIES[int(index)], state,
            datetime.fromisoformat(f"2026-11-{clock}+00:00"),
        )
        for clock, index, state in (
            row.split() for row in _INPUTS.strip().splitlines()
        )
    )
    paired_at = datetime(2026, 11, 3, 0, 19, 12, 371936, tzinfo=UTC)
    report_at = datetime(2026, 11, 3, 1, 1, 4, 222491, tzinfo=UTC)
    initial_states = {
        entity: "on" if index in {6, 8, 9, 13} else "off"
        for index, entity in enumerate(_ENTITIES)
    }
    with RuntimeScenario(datetime(2026, 11, 2, 23, 55, tzinfo=UTC)) as scenario:
        replay = scenario.create(predictive_map, 2, initial_states=initial_states)
        for event in expected_inputs:
            published = replay.observe(event)
            if event.event_at == paired_at:
                assert published.active("living_room_left")
                assert any(
                    path is not None and tuple(
                        visit.node_id for visit in path.route
                    ) == ("guest_bedroom_motion", "living_room_fireplace_left")
                    for path in replay.inference_snapshot().selected_paths
                )
        reported = replay.advance(report_at)
        assert len(expected_inputs) == 138
        assert replay.normalized_inputs == list(expected_inputs)
        assert ActiveEdge(paired_at, "living_room_left", True) in (
            replay.input_edges_for("living_room_left")
        )
        assert reported.active("guest_bedroom"), (
            "Occupied guest bedroom never recovered its public active output",
            replay.edges_for("guest_bedroom"),
            replay.attributes["guest_bedroom"],
        )
