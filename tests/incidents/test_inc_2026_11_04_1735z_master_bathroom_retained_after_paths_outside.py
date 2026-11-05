"""User-reported issue: master bathroom light stuck on for hours at about5% belief.
User: "the master bathroom is currently on, the % chance is at 5%, so why is the
light on? It has not been active for 4 hours." Expected: once the house's selected
paths are established outside the room, its retained hold resolves and the room
decays OFF normally. Live report November4 21:43:53Z: active, reason
retained_endpoint_hold, belief0.0534, last bathroom detection17:35:24.702647Z.
Source: approved read-only Homelab tmp/master-bathroom-stuck-20261104/
{status,history}.json. Status SHA256
eaee4a1b5883136db7cda5e55c09ef2b1f0a7b4aab62e87ae990689b343da890; history SHA256
64ec0b3e70a59688b04d1cffed6a137555ffc07ce008c0e13b358d390e8666e4.
Retain383 recorder changes/18 entities through19:10Z, count2 and the repository
map at capture (labels/positions/sizes dropped). Cold inference starts16:00Z with
recorded boundary levels; other entities are unobserved, not invented OFF.
The16:43:52.592477Z activation edge reproduces the live edge exactly. The17:39:22Z
closet return is 58s outside the bathroom's180s traversal window, so no direct
departure exists. At19:01:07.082482Z both selected slots are confirmed paths whose
endpoints are outside the bathroom and newer than its latest detection, but the
pre-fix all-N proof also required current head ON/trust and three distinct suffix
nodes, so the hold never resolved. The public oracle requires release after that
outside proof plus the normal release dwell, not earlier and not a timeout.
"""

from datetime import UTC, datetime, timedelta

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
    "binary_sensor.guest_bedroom_guest_bedroom_motion_motion_detection",
    "binary_sensor.island_monitor_radar_moving_target",
    "binary_sensor.island_monitor_radar_still_target",
    "binary_sensor.island_monitor_radar_target",
    "binary_sensor.island_monitor_radar_zone_3_occupancy",
    "binary_sensor.master_bathroom_master_bathroom_light_motion_motion_detection",
    "binary_sensor.master_bedroom_closet_motion_motion_detection",
    "binary_sensor.master_bedroom_entrance_pir_motion_motion_detection",
    "binary_sensor.mmwave_dimmer_motion_detection_2",
    "binary_sensor.top_of_staircase_motion_motion_detection",
    "binary_sensor.upstairs_bathroom_motion_motion_detection",
    "event.upstairs_bathroom_motion_scene_002",
)

_MAP = """
zones:
  entrance_hallway:
    floor: first_floor
    role: transition_gate
    occupancy_behavior: transient
  first_floor_bathroom_laundry_room:
    floor: first_floor
    role: room_occupancy
    occupancy_behavior: sustained
  dining_room:
    floor: first_floor
    role: transition_gate
    occupancy_behavior: transient
  kitchen: {floor: first_floor, occupancy_behavior: sustained, role: room_occupancy}
  foyer: {floor: first_floor, occupancy_behavior: transient, role: transition_gate}
  living_room_right:
    floor: first_floor
    role: anchor_sensor
    occupancy_behavior: sticky
  living_room_left:
    floor: first_floor
    role: anchor_sensor
    occupancy_behavior: sticky
  staircase_bottom:
    floor: first_floor
    role: transition_gate
    occupancy_behavior: transient
  guest_bedroom:
    floor: first_floor
    role: room_occupancy
    occupancy_behavior: sustained
  upstairs_hallway:
    floor: second_floor
    role: transition_gate
    occupancy_behavior: transient
  upstairs_bathroom:
    floor: second_floor
    role: room_occupancy
    occupancy_behavior: sticky
  alex_office:
    floor: second_floor
    role: room_occupancy
    occupancy_behavior: sustained
  master_bedroom_entrance:
    floor: second_floor
    role: transition_gate
    occupancy_behavior: transient
  master_bedroom_closet:
    floor: second_floor
    role: subzone_occupancy
    occupancy_behavior: sustained
  master_bathroom:
    floor: second_floor
    role: room_occupancy
    occupancy_behavior: sticky
  shaila_office:
    floor: second_floor
    role: room_occupancy
    occupancy_behavior: sustained
  gym: {floor: basement, occupancy_behavior: sustained, role: room_occupancy}
nodes:
  entrance_mmwave_dimmer:
    floor: first_floor
    zone: entrance_hallway
    role: transition_gate
    entities: {mmwave: binary_sensor.entrance_mmwave_dimmer_motion_detection}
    adjacent:
      - ground_floor_bathroom_laundry_room
      - dining_room_motion
      - dining_room_motion_interaction
      - kitchen_overhead_mmwave_dimmer
      - kitchen_overhead_mmwave_dimmer_interaction
    initial_weight: 0.75
  entrance_mmwave_dimmer_interaction:
    floor: first_floor
    zone: entrance_hallway
    role: transition_gate
    entities:
      interaction_scene_001: event.entrance_mmwave_dimmer_scene_001
      interaction_scene_002: event.entrance_mmwave_dimmer_scene_002
      interaction_scene_003: event.entrance_mmwave_dimmer_scene_003
    adjacent:
      - ground_floor_bathroom_laundry_room
      - dining_room_motion
      - kitchen_overhead_mmwave_dimmer
    initial_weight: 1.0
  ground_floor_bathroom_laundry_room:
    floor: first_floor
    zone: first_floor_bathroom_laundry_room
    role: room_occupancy
    entities:
      motion: binary_sensor.ground_floor_bathroom_laundry_room_motion_detection
    adjacent: [entrance_mmwave_dimmer, entrance_mmwave_dimmer_interaction]
    initial_weight: 0.8
  dining_room_motion:
    floor: first_floor
    zone: dining_room
    role: transition_gate
    entities: {mmwave: binary_sensor.dining_room_motion_motion_detection}
    adjacent:
      - entrance_mmwave_dimmer
      - entrance_mmwave_dimmer_interaction
      - kitchen_overhead_mmwave_dimmer
      - kitchen_overhead_mmwave_dimmer_interaction
      - living_room_fireplace_right
      - foyer_pir_motion
      - gym_lights_motion
      - gym_lights_motion_interaction
    transition_seconds: {foyer_pir_motion: 15, kitchen_overhead_mmwave_dimmer: 15}
    initial_weight: 0.75
  dining_room_motion_interaction:
    floor: first_floor
    zone: dining_room
    role: transition_gate
    entities:
      interaction_scene_001: event.dining_room_motion_scene_001
      interaction_scene_002: event.dining_room_motion_scene_002
      interaction_scene_003: event.dining_room_motion_scene_003
    adjacent:
      - entrance_mmwave_dimmer
      - kitchen_overhead_mmwave_dimmer
      - living_room_fireplace_right
      - foyer_pir_motion
      - gym_lights_motion
    initial_weight: 1.0
  kitchen_overhead_mmwave_dimmer:
    floor: first_floor
    zone: kitchen
    role: room_occupancy
    entities: {mmwave: binary_sensor.mmwave_dimmer_motion_detection_2}
    adjacent:
      - entrance_mmwave_dimmer
      - entrance_mmwave_dimmer_interaction
      - dining_room_motion
      - dining_room_motion_interaction
    transition_seconds: {dining_room_motion: 15}
    initial_weight: 0.8
  kitchen_overhead_mmwave_dimmer_interaction:
    floor: first_floor
    zone: kitchen
    role: room_occupancy
    occupancy_behavior: sticky
    entities:
      interaction_scene_001: event.mmwave_dimmer_scene_001_2
      interaction_scene_002: event.mmwave_dimmer_scene_002_2
      interaction_scene_003: event.mmwave_dimmer_scene_003_2
    adjacent: [entrance_mmwave_dimmer, dining_room_motion]
    initial_weight: 1.0
  foyer_pir_motion:
    floor: first_floor
    zone: foyer
    role: transition_gate
    entities: {motion: binary_sensor.foyer_pir_motion_motion_detection}
    adjacent:
      - dining_room_motion
      - dining_room_motion_interaction
      - bottom_of_staircase_motion
      - bottom_of_staircase_motion_interaction
      - guest_bedroom_motion
    transition_seconds: {dining_room_motion: 15}
    initial_weight: 0.85
  living_room_fireplace_left:
    floor: first_floor
    zone: living_room_left
    role: anchor_sensor
    entities:
      moving_target: binary_sensor.apollo_msr_2_2cb8b0_radar_moving_target
      still_target: binary_sensor.apollo_msr_2_2cb8b0_radar_still_target
      target: binary_sensor.apollo_msr_2_2cb8b0_radar_target
      zone_3_occupancy: binary_sensor.apollo_msr_2_2cb8b0_radar_zone_3_occupancy
    adjacent:
      - guest_bedroom_motion
      - guest_bedroom_motion_interaction
      - living_room_fireplace_right
    initial_weight: 0.9
  living_room_fireplace_right:
    floor: first_floor
    zone: living_room_right
    role: anchor_sensor
    entities:
      moving_target: binary_sensor.island_monitor_radar_moving_target
      still_target: binary_sensor.island_monitor_radar_still_target
      target: binary_sensor.island_monitor_radar_target
      zone_3_occupancy: binary_sensor.island_monitor_radar_zone_3_occupancy
    adjacent:
      - dining_room_motion
      - dining_room_motion_interaction
      - living_room_fireplace_left
    initial_weight: 0.9
  bottom_of_staircase_motion:
    floor: first_floor
    zone: staircase_bottom
    role: transition_gate
    entities: {mmwave: binary_sensor.bottom_of_staircase_motion_motion_detection}
    adjacent:
      - foyer_pir_motion
      - guest_bedroom_motion
      - guest_bedroom_motion_interaction
      - top_of_staircase_motion
      - top_of_staircase_motion_interaction
    initial_weight: 0.85
  bottom_of_staircase_motion_interaction:
    floor: first_floor
    zone: staircase_bottom
    role: transition_gate
    entities:
      interaction_scene_001: event.bottom_of_staircase_motion_scene_001
      interaction_scene_002: event.bottom_of_staircase_motion_scene_002
      interaction_scene_003: event.bottom_of_staircase_motion_scene_003
    adjacent: [foyer_pir_motion, guest_bedroom_motion, top_of_staircase_motion]
    initial_weight: 1.0
  guest_bedroom_motion:
    floor: first_floor
    zone: guest_bedroom
    role: room_occupancy
    entities:
      mmwave: binary_sensor.guest_bedroom_guest_bedroom_motion_motion_detection
    adjacent:
      - bottom_of_staircase_motion
      - bottom_of_staircase_motion_interaction
      - living_room_fireplace_left
      - foyer_pir_motion
    initial_weight: 0.75
  guest_bedroom_motion_interaction:
    floor: first_floor
    zone: guest_bedroom
    role: room_occupancy
    occupancy_behavior: sticky
    entities:
      interaction_scene_001: event.guest_bedroom_guest_bedroom_motion_scene_001
      interaction_scene_002: event.guest_bedroom_guest_bedroom_motion_scene_002
      interaction_scene_003: event.guest_bedroom_guest_bedroom_motion_scene_003
    adjacent: [bottom_of_staircase_motion, living_room_fireplace_left]
    initial_weight: 1.0
  top_of_staircase_motion:
    floor: second_floor
    zone: upstairs_hallway
    role: transition_gate
    entities: {mmwave: binary_sensor.top_of_staircase_motion_motion_detection}
    adjacent:
      - bottom_of_staircase_motion
      - bottom_of_staircase_motion_interaction
      - upstairs_bathroom_motion
      - upstairs_bathroom_light_interaction
      - upstairs_bathroom_fan_interaction
      - alex_office_motion
      - alex_office_motion_interaction
      - master_bedroom_entrance
      - shaila_office_fan_light
      - shaila_office_fan_light_interaction
    initial_weight: 0.85
  top_of_staircase_motion_interaction:
    floor: second_floor
    zone: upstairs_hallway
    role: transition_gate
    entities:
      interaction_scene_001: event.top_of_staircase_motion_scene_001
      interaction_scene_002: event.top_of_staircase_motion_scene_002
      interaction_scene_003: event.top_of_staircase_motion_scene_003
    adjacent:
      - bottom_of_staircase_motion
      - upstairs_bathroom_motion
      - alex_office_motion
      - master_bedroom_entrance
      - shaila_office_fan_light
    initial_weight: 1.0
  upstairs_bathroom_motion:
    floor: second_floor
    zone: upstairs_bathroom
    role: room_occupancy
    entities: {mmwave: binary_sensor.upstairs_bathroom_motion_motion_detection}
    adjacent:
      - top_of_staircase_motion
      - top_of_staircase_motion_interaction
      - shaila_office_fan_light
      - shaila_office_fan_light_interaction
    initial_weight: 0.7
  upstairs_bathroom_light_interaction:
    floor: second_floor
    zone: upstairs_bathroom
    role: room_occupancy
    entities:
      interaction_scene_001: event.upstairs_bathroom_motion_scene_001
      interaction_scene_002: event.upstairs_bathroom_motion_scene_002
      interaction_scene_003: event.upstairs_bathroom_motion_scene_003
    adjacent: [top_of_staircase_motion, shaila_office_fan_light]
    initial_weight: 1.0
  upstairs_bathroom_fan_interaction:
    floor: second_floor
    zone: upstairs_bathroom
    role: room_occupancy
    entities:
      interaction_scene_001: event.upstairs_bathroom_fan_scene_001
      interaction_scene_002: event.upstairs_bathroom_fan_scene_002
      interaction_scene_003: event.upstairs_bathroom_fan_scene_003
    adjacent: [top_of_staircase_motion, shaila_office_fan_light]
    initial_weight: 1.0
  alex_office_motion:
    floor: second_floor
    zone: alex_office
    role: room_occupancy
    entities: {mmwave: binary_sensor.alex_office_alex_office_motion_motion_detection}
    adjacent: [top_of_staircase_motion, top_of_staircase_motion_interaction]
    initial_weight: 0.75
  alex_office_motion_interaction:
    floor: second_floor
    zone: alex_office
    role: room_occupancy
    occupancy_behavior: sticky
    entities:
      interaction_scene_001: event.alex_office_alex_office_motion_scene_001
      interaction_scene_002: event.alex_office_alex_office_motion_scene_002
      interaction_scene_003: event.alex_office_alex_office_motion_scene_003
    adjacent: [top_of_staircase_motion]
    initial_weight: 1.0
  master_bedroom_entrance:
    floor: second_floor
    zone: master_bedroom_entrance
    role: transition_gate
    entities:
      motion: binary_sensor.master_bedroom_entrance_pir_motion_motion_detection
    adjacent:
      - master_bedroom_closet
      - master_bedroom_closet_motion_interaction
      - top_of_staircase_motion
      - top_of_staircase_motion_interaction
    initial_weight: 0.8
  master_bedroom_closet:
    floor: second_floor
    zone: master_bedroom_closet
    role: subzone_occupancy
    entities: {mmwave: binary_sensor.master_bedroom_closet_motion_motion_detection}
    adjacent:
      - master_bedroom_entrance
      - master_bathroom_fan_interaction
      - master_bathroom_light_interaction
      - master_bathroom_light_motion
    initial_weight: 0.8
  master_bedroom_closet_motion_interaction:
    floor: second_floor
    zone: master_bedroom_closet
    role: subzone_occupancy
    occupancy_behavior: sticky
    entities:
      interaction_scene_001: event.master_bedroom_closet_motion_scene_001
      interaction_scene_002: event.master_bedroom_closet_motion_scene_002
      interaction_scene_003: event.master_bedroom_closet_motion_scene_003
    adjacent:
      - master_bedroom_entrance
      - master_bathroom_fan_interaction
      - master_bathroom_light_interaction
      - master_bathroom_light_motion
    initial_weight: 1.0
  master_bathroom_fan_interaction:
    floor: second_floor
    zone: master_bathroom
    role: room_occupancy
    entities:
      interaction_scene_001: event.master_bathroom_master_bathroom_fan_scene_001
      interaction_scene_002: event.master_bathroom_master_bathroom_fan_scene_002
      interaction_scene_003: event.master_bathroom_master_bathroom_fan_scene_003
    adjacent: [master_bedroom_closet, master_bedroom_closet_motion_interaction]
    initial_weight: 1.0
  master_bathroom_light_interaction:
    floor: second_floor
    zone: master_bathroom
    role: room_occupancy
    entities:
      interaction_scene_001:
        event.master_bathroom_master_bathroom_light_motion_scene_001
      interaction_scene_002:
        event.master_bathroom_master_bathroom_light_motion_scene_002
      interaction_scene_003:
        event.master_bathroom_master_bathroom_light_motion_scene_003
    adjacent: [master_bedroom_closet, master_bedroom_closet_motion_interaction]
    initial_weight: 1.0
  master_bathroom_light_motion:
    floor: second_floor
    zone: master_bathroom
    role: room_occupancy
    entities:
      mmwave:
        binary_sensor.master_bathroom_master_bathroom_light_motion_motion_detection
    adjacent: [master_bedroom_closet, master_bedroom_closet_motion_interaction]
    initial_weight: 0.7
  shaila_office_fan_light:
    floor: second_floor
    zone: shaila_office
    role: room_occupancy
    entities: {mmwave: binary_sensor.shaila_office_fan_light_motion_detection}
    adjacent:
      - top_of_staircase_motion
      - top_of_staircase_motion_interaction
      - upstairs_bathroom_motion
      - upstairs_bathroom_light_interaction
      - upstairs_bathroom_fan_interaction
    initial_weight: 0.75
  shaila_office_fan_light_interaction:
    floor: second_floor
    zone: shaila_office
    role: room_occupancy
    occupancy_behavior: sticky
    entities:
      interaction_scene_001: event.shaila_office_fan_light_scene_001
      interaction_scene_002: event.shaila_office_fan_light_scene_002
      interaction_scene_003: event.shaila_office_fan_light_scene_003
    adjacent: [top_of_staircase_motion, upstairs_bathroom_motion]
    initial_weight: 1.0
  gym_lights_motion:
    floor: basement
    zone: gym
    role: room_occupancy
    entities: {mmwave: binary_sensor.gym_lights_motion_motion_detection}
    adjacent: [dining_room_motion, dining_room_motion_interaction]
    initial_weight: 0.75
    review_required: true
  gym_lights_motion_interaction:
    floor: basement
    zone: gym
    role: room_occupancy
    occupancy_behavior: sticky
    entities: {interaction_scene_001: event.gym_lights_motion_scene_001}
    adjacent: [dining_room_motion]
    initial_weight: 1.0
    review_required: true
"""

_INPUTS = """
04T16:01:08.601798 12 on
04T16:01:39.057986 12 off
04T16:01:43.672813 12 on
04T16:02:14.104641 12 off
04T16:02:28.767197 12 on
04T16:02:59.199264 12 off
04T16:03:27.424976 12 on
04T16:04:27.527046 12 off
04T16:04:52.218417 12 on
04T16:05:46.243709 12 off
04T16:05:50.870493 12 on
04T16:07:35.573625 12 off
04T16:07:37.697803 12 on
04T16:20:01.705902 12 off
04T16:20:19.016505 12 on
04T16:20:49.577285 12 off
04T16:21:01.310234 12 on
04T16:25:48.924348 12 off
04T16:26:24.854609 12 on
04T16:26:59.257590 12 off
04T16:30:05.910903 12 on
04T16:31:05.254417 12 off
04T16:31:13.249021 12 on
04T16:33:59.210447 12 off
04T16:34:31.418621 12 on
04T16:34:58.041981 11 on
04T16:35:25.584169 12 off
04T16:42:51.429951 12 on
04T16:43:19.458306 11 off
04T16:43:40.839820 13 on
04T16:43:51.918435 15 on
04T16:43:52.592477 11 on
04T16:44:01.236614 0 on
04T16:44:07.971056 11 off
04T16:44:08.479348 15 off
04T16:44:08.672730 13 off
04T16:44:30.483174 12 off
04T16:54:51.777990 6 off
04T16:54:53.501100 6 on
04T17:02:44.226428 6 off
04T17:02:45.967170 6 on
04T17:02:59.314556 6 off
04T17:03:01.465104 6 on
04T17:04:15.704230 1 on
04T17:04:18.409991 4 on
04T17:04:20.203838 15 on
04T17:04:28.624743 6 off
04T17:04:30.733323 4 off
04T17:04:34.600268 1 off
04T17:04:42.099419 15 off
04T17:04:52.739148 15 on
04T17:04:59.108216 16 on
04T17:05:01.143651 17 pressed
04T17:05:03.279835 15 off
04T17:05:12.144639 0 off
04T17:06:00.371802 15 on
04T17:06:09.419117 15 off
04T17:06:09.497457 15 on
04T17:06:24.980910 0 on
04T17:06:31.281559 16 off
04T17:06:38.638710 15 off
04T17:08:23.145680 15 on
04T17:08:32.404985 16 on
04T17:08:39.140118 15 off
04T17:08:39.891793 0 off
04T17:08:48.266248 15 on
04T17:08:53.239856 0 on
04T17:09:00.169288 15 off
04T17:09:09.416739 16 off
04T17:09:10.381326 16 on
04T17:10:26.342321 15 on
04T17:10:36.911864 15 off
04T17:10:39.652369 16 off
04T17:12:51.192908 15 on
04T17:13:00.428613 1 on
04T17:13:05.067168 4 on
04T17:13:10.011956 15 off
04T17:13:13.429919 2 on
04T17:13:20.680296 1 off
04T17:13:25.984680 14 on
04T17:13:26.877165 4 off
04T17:13:37.994863 2 off
04T17:14:36.368325 2 on
04T17:14:54.659040 2 off
04T17:15:39.293352 2 on
04T17:15:47.884780 4 on
04T17:15:50.669293 1 on
04T17:15:54.962887 6 on
04T17:15:55.247433 14 off
04T17:15:58.547832 2 off
04T17:16:03.147430 4 off
04T17:16:05.168319 1 off
04T17:16:28.270596 1 on
04T17:16:30.729063 4 on
04T17:16:34.550645 2 on
04T17:16:37.783770 9 on
04T17:16:37.790559 7 on
04T17:16:38.083457 8 on
04T17:16:39.804229 10 on
04T17:16:40.278069 6 off
04T17:16:40.896251 7 off
04T17:16:41.286582 7 on
04T17:16:41.657318 1 off
04T17:16:46.300022 7 off
04T17:16:46.699935 7 on
04T17:16:47.222966 4 off
04T17:16:48.938348 2 off
04T17:16:54.483209 7 off
04T17:16:54.984198 7 on
04T17:16:57.175683 7 off
04T17:16:57.383996 10 off
04T17:17:00.108617 7 on
04T17:17:01.823654 7 off
04T17:17:10.814444 7 on
04T17:17:10.819164 10 on
04T17:17:11.409031 7 off
04T17:17:11.415107 10 off
04T17:17:13.132328 10 on
04T17:17:24.582733 7 on
04T17:17:28.475371 2 on
04T17:17:28.982593 7 off
04T17:17:30.885806 14 on
04T17:17:35.883302 9 off
04T17:17:35.888830 8 off
04T17:17:35.893646 10 off
04T17:17:43.403682 2 off
04T17:18:23.365306 2 on
04T17:18:26.983283 9 on
04T17:18:26.991005 7 on
04T17:18:26.996129 10 on
04T17:18:27.098387 8 on
04T17:18:28.797354 10 off
04T17:18:30.504807 10 on
04T17:18:33.497458 7 off
04T17:18:35.213348 7 on
04T17:18:35.328804 14 off
04T17:18:37.381428 7 off
04T17:18:38.295060 2 off
04T17:18:38.381160 7 on
04T17:18:40.544545 7 off
04T17:18:42.260461 7 on
04T17:18:45.003206 7 off
04T17:18:53.381166 7 on
04T17:18:57.581019 7 off
04T17:19:00.280874 7 on
04T17:19:02.472430 7 off
04T17:19:02.477000 7 on
04T17:19:02.797149 7 off
04T17:19:18.981449 7 on
04T17:19:20.717697 7 off
04T17:19:29.080639 7 on
04T17:19:31.390518 7 off
04T17:19:31.496660 7 on
04T17:19:39.296453 7 off
04T17:21:38.078147 7 on
04T17:21:43.193586 7 off
04T17:21:47.788067 7 on
04T17:21:49.529882 7 off
04T17:22:36.693950 7 on
04T17:22:39.909989 7 off
04T17:22:43.579785 7 on
04T17:22:45.308005 7 off
04T17:22:47.464506 7 on
04T17:22:48.102125 7 off
04T17:22:48.692756 7 on
04T17:22:50.415846 7 off
04T17:22:55.894966 7 on
04T17:22:58.087797 7 off
04T17:23:00.876355 7 on
04T17:23:02.607430 7 off
04T17:23:04.486629 7 on
04T17:23:05.594419 7 off
04T17:23:05.976168 7 on
04T17:23:08.484727 7 off
04T17:23:28.675986 7 on
04T17:23:30.414747 7 off
04T17:23:52.975026 9 off
04T17:23:52.980831 8 off
04T17:23:52.985538 10 off
04T17:25:15.173874 9 on
04T17:25:15.180472 7 on
04T17:25:15.185285 8 on
04T17:25:15.192030 10 on
04T17:25:17.373212 7 off
04T17:25:19.573422 7 on
04T17:25:21.308898 7 off
04T17:26:03.088854 7 on
04T17:26:05.888861 7 off
04T17:26:29.085342 7 on
04T17:26:30.783484 7 off
04T17:26:30.973156 7 on
04T17:26:32.670276 7 off
04T17:26:32.674598 7 on
04T17:26:33.387712 7 off
04T17:27:25.571633 7 on
04T17:27:27.290029 7 off
04T17:27:54.870555 7 on
04T17:27:59.786938 7 off
04T17:27:59.970538 7 on
04T17:28:01.671170 7 off
04T17:28:10.771044 7 on
04T17:28:12.473930 7 off
04T17:28:18.870194 7 on
04T17:28:20.546842 7 off
04T17:28:24.272098 7 on
04T17:28:26.372856 7 off
04T17:28:56.371370 7 on
04T17:28:58.465679 7 off
04T17:29:13.532015 7 on
04T17:29:15.484924 7 off
04T17:29:22.268960 7 on
04T17:29:23.970245 7 off
04T17:29:24.872079 7 on
04T17:29:26.977755 7 off
04T17:29:29.668666 7 on
04T17:29:31.347989 7 off
04T17:29:33.685568 7 on
04T17:29:35.885319 7 off
04T17:29:44.672768 7 on
04T17:29:48.269358 7 off
04T17:29:55.969277 7 on
04T17:29:57.652292 7 off
04T17:30:14.168121 7 on
04T17:30:16.192079 7 off
04T17:30:26.174227 7 on
04T17:30:27.802099 7 off
04T17:30:41.567762 7 on
04T17:30:43.200217 7 off
04T17:30:56.291963 7 on
04T17:30:58.066966 7 off
04T17:30:59.700690 7 on
04T17:31:01.339027 7 off
04T17:31:05.484024 7 on
04T17:31:07.123616 7 off
04T17:31:07.972614 7 on
04T17:31:09.603392 7 off
04T17:31:09.935074 7 on
04T17:31:11.966718 7 off
04T17:31:19.766727 7 on
04T17:31:21.883220 7 off
04T17:31:25.766734 7 on
04T17:31:28.466595 7 off
04T17:31:31.576128 7 on
04T17:31:34.566197 7 off
04T17:31:41.983472 7 on
04T17:31:43.713794 7 off
04T17:31:43.969968 7 on
04T17:31:45.692876 7 off
04T17:31:47.566087 7 on
04T17:31:49.691707 7 off
04T17:31:59.666084 7 on
04T17:32:01.386173 7 off
04T17:32:32.465428 7 on
04T17:32:35.381512 7 off
04T17:32:36.265350 7 on
04T17:32:37.992616 7 off
04T17:32:43.973824 7 on
04T17:32:45.686474 7 off
04T17:32:48.764937 7 on
04T17:32:51.082183 7 off
04T17:32:51.465470 7 on
04T17:32:53.182076 7 off
04T17:32:54.872470 7 on
04T17:32:57.083182 7 off
04T17:33:06.764757 7 on
04T17:33:10.164574 7 off
04T17:33:11.076835 7 on
04T17:33:12.807274 7 off
04T17:33:14.983616 7 on
04T17:33:15.564238 7 off
04T17:33:20.664539 7 on
04T17:33:22.564950 7 off
04T17:33:23.180356 7 on
04T17:33:25.679950 7 off
04T17:33:29.864156 7 on
04T17:33:31.591570 7 off
04T17:33:45.877986 12 on
04T17:33:52.563603 7 on
04T17:33:54.822581 7 off
04T17:33:56.534658 7 on
04T17:33:58.242948 7 off
04T17:33:58.679983 7 on
04T17:34:00.857722 7 off
04T17:34:01.863558 7 on
04T17:34:03.574684 7 off
04T17:34:05.463299 7 on
04T17:34:07.178665 7 off
04T17:34:09.912083 7 on
04T17:34:11.677330 7 off
04T17:34:12.463091 7 on
04T17:34:14.194103 7 off
04T17:34:20.665309 12 off
04T17:34:49.262627 7 on
04T17:34:51.471319 7 off
04T17:34:54.562664 7 on
04T17:34:56.293667 7 off
04T17:35:06.662169 7 on
04T17:35:08.850957 7 off
04T17:35:09.181017 7 on
04T17:35:10.930290 7 off
04T17:35:18.362037 7 on
04T17:35:20.528567 7 off
04T17:35:24.702647 11 on
04T17:35:35.585209 11 off
04T17:35:36.064388 7 on
04T17:35:38.267047 7 off
04T17:36:04.477559 7 on
04T17:36:06.659994 7 off
04T17:36:11.661041 7 on
04T17:36:13.411397 7 off
04T17:36:16.561075 7 on
04T17:36:18.307519 7 off
04T17:36:20.260891 7 on
04T17:36:21.976677 7 off
04T17:36:57.076753 7 on
04T17:36:59.259958 7 off
04T17:37:28.459557 7 on
04T17:37:30.200599 7 off
04T17:37:33.565555 7 on
04T17:37:35.304913 7 off
04T17:37:35.309380 7 on
04T17:37:39.261337 7 off
04T17:37:47.159335 7 on
04T17:37:49.069665 2 on
04T17:37:49.275408 7 off
04T17:37:51.745866 4 on
04T17:37:55.559050 9 off
04T17:37:55.564668 8 off
04T17:37:55.569512 10 off
04T17:37:56.327393 1 on
04T17:38:00.769286 6 on
04T17:38:03.372741 2 off
04T17:38:06.380990 1 off
04T17:38:08.559941 4 off
04T17:39:22.814080 12 on
04T17:39:57.688754 12 off
04T18:07:51.725533 6 off
04T18:07:53.853705 6 on
04T18:42:35.529309 6 off
04T18:42:39.638200 6 on
04T18:42:54.514759 6 off
04T18:43:03.160580 6 on
04T18:44:11.945375 6 off
04T18:44:22.572661 6 on
04T18:44:41.507961 6 off
04T18:44:43.194527 6 on
04T18:46:30.989041 6 off
04T18:46:31.601423 6 on
04T18:57:00.324797 1 on
04T18:57:04.066966 4 on
04T18:57:07.009925 2 on
04T18:57:12.209253 3 on
04T18:57:12.830307 6 off
04T18:57:14.575954 5 on
04T18:57:14.644473 1 off
04T18:57:19.615553 4 off
04T18:57:23.404372 2 off
04T18:57:25.113109 3 off
04T18:57:49.542932 5 off
04T18:57:54.713328 5 on
04T18:58:42.293195 3 on
04T18:58:44.018035 2 on
04T18:58:44.658285 14 on
04T18:58:53.652442 5 off
04T18:59:00.962278 3 off
04T18:59:29.375756 3 on
04T18:59:32.532091 5 on
04T18:59:39.834465 14 off
04T18:59:40.368432 2 off
04T18:59:42.497107 3 off
04T19:00:34.505433 3 on
04T19:00:36.245495 2 on
04T19:00:37.979729 14 on
04T19:00:42.255193 4 on
04T19:00:45.907752 1 on
04T19:00:46.847831 5 off
04T19:00:47.847341 14 off
04T19:00:51.793941 3 off
04T19:00:52.238084 2 off
04T19:00:59.995818 4 off
04T19:01:07.082482 6 on
04T19:01:12.508499 1 off
04T19:09:42.142350 6 off
"""


@pytest.mark.scenario
@pytest.mark.target_model
def test_inc_2026_11_04_1735z_master_bathroom_retained_after_paths_outside() -> None:
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
    activated_at = datetime(2026, 11, 4, 16, 43, 52, 592477, tzinfo=UTC)
    closet_clear_at = datetime(2026, 11, 4, 17, 39, 57, 688754, tzinfo=UTC)
    outside_at = datetime(2026, 11, 4, 19, 1, 7, 82482, tzinfo=UTC)
    report_at = datetime(2026, 11, 4, 19, 10, tzinfo=UTC)
    initial_states = {
        entity: "on" if index in {6} else "off"
        for index, entity in enumerate(_ENTITIES)
        if entity.startswith("binary_sensor.")
    }
    with RuntimeScenario(datetime(2026, 11, 4, 16, tzinfo=UTC)) as scenario:
        replay = scenario.create(predictive_map, 2, initial_states=initial_states)
        for event in expected_inputs:
            published = replay.observe(event)
            if event.event_at == closet_clear_at:
                # Real uncertainty after the last bathroom detection stays held.
                assert published.active("master_bathroom")
            if event.event_at == outside_at:
                outside = tuple(
                    path for path in replay.inference_snapshot().selected_paths
                    if path is not None
                )
                assert len(outside) == 2
                assert all(
                    path.track_confidence == "confirmed"
                    and path.endpoint.zone != "master_bathroom"
                    and path.endpoint.at > datetime(
                        2026, 11, 4, 17, 35, 24, 702647, tzinfo=UTC,
                    )
                    for path in outside
                )
        reported = replay.advance(report_at)
        assert len(expected_inputs) == 383
        assert replay.normalized_inputs == list(expected_inputs)
        edges = replay.edges_for("master_bathroom")
        assert edges[0] == ActiveEdge(activated_at, "master_bathroom", True)
        assert not reported.active("master_bathroom"), (
            "Bathroom stayed held after both paths were established outside",
            edges,
            replay.attributes["master_bathroom"],
        )
        assert [edge.active for edge in edges] == [True, False]
        assert outside_at + timedelta(seconds=120) <= edges[-1].at < report_at
