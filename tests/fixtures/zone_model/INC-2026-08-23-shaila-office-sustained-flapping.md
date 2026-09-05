# INC-2026-08-23 Shaila Office sustained sensor flapping

## Target belief contract

- Affected input: `binary_sensor.shaila_office_fan_light_motion_detection`.
- Observed shape: the mapped stay-presence mmWave alternated repeatedly between
  `on` and `off` for hours, including the exact 18-edge excerpt from
  `2026-08-22T12:12:00.312303+00:00` through
  `2026-08-22T12:34:34.286213+00:00` shown in Home Assistant history.
- Current behavior: the unchanged episode tracker turns the excerpt's nine `on`
  edges into nine independent positive likelihood updates. The isolated target
  belief reaches `0.9970341715801893`.
- Expected behavior: the first positive after a quiet boundary retains ordinary
  configured reliability. Later completed clear/reassert cycles in the same
  bounded burst are correlated evidence and cannot cumulatively move an
  isolated stay zone above the shared `0.70` acquisition threshold.
- Public safety: correlation must not fabricate traversal, count support,
  acquisition, or refresh. A single sustained `on` remains ordinary strong stay
  evidence and is not classified as flapping by elapsed time alone.

## Read-only retained evidence

History was retrieved through
`home-assistant/scripts/ha-history-states.sh` for the complete local calendar
days August 20 through 22, 2026. The raw ignored cache is
`homelab/tmp/shaila-office-motion-history-2026-08-20-through-22.json`.

The Shaila Office history contains:

- 1,675 rows: 836 `on`, 838 `off`, and one `unavailable`;
- 1,674 genuine state changes and no consecutive same-state rows;
- 70 changes on August 20, 1,005 on August 21, and 599 on August 22;
- median asserted and clear intervals of `52.429s` and `55.624s`;
- 699 of 836 asserted intervals and 627 of 837 clear intervals at or below
  `120s`;
- a densest hour with 63 changes; and
- a longest burst of 800.6 minutes when alternating edges no more than ten
  minutes apart are linked.

The same August 20 through 22 lookup covered all 12 mmWave entities explicitly
configured in the checked-in predictive map. Shaila Office sustained the
longest ten-minute-linked burst at 800.6 minutes. The next longest was Master
Bedroom Closet at 125.0 minutes; every other mapped sensor remained below 62
minutes. This corpus supports a shared three-hour cadence-health warning
boundary, not a room-specific threshold.

The exact screenshot excerpt retained by the regression is:

| UTC timestamp                      | State |
| ---------------------------------- | ----- |
| `2026-08-22T12:12:00.312303+00:00` | `on`  |
| `2026-08-22T12:13:21.696150+00:00` | `off` |
| `2026-08-22T12:15:14.321496+00:00` | `on`  |
| `2026-08-22T12:15:47.199246+00:00` | `off` |
| `2026-08-22T12:17:35.825838+00:00` | `on`  |
| `2026-08-22T12:18:32.255483+00:00` | `off` |
| `2026-08-22T12:20:32.331074+00:00` | `on`  |
| `2026-08-22T12:21:36.262743+00:00` | `off` |
| `2026-08-22T12:21:58.835773+00:00` | `on`  |
| `2026-08-22T12:22:40.214191+00:00` | `off` |
| `2026-08-22T12:23:20.335658+00:00` | `on`  |
| `2026-08-22T12:23:55.716778+00:00` | `off` |
| `2026-08-22T12:25:13.843043+00:00` | `on`  |
| `2026-08-22T12:26:04.772062+00:00` | `off` |
| `2026-08-22T12:31:54.352277+00:00` | `on`  |
| `2026-08-22T12:32:29.233070+00:00` | `off` |
| `2026-08-22T12:33:43.857402+00:00` | `on`  |
| `2026-08-22T12:34:34.286213+00:00` | `off` |

## Controlling layer and disconfirming check

- Layer: `EPISODE`, then `ZONE_BELIEF`.
- The `stay_presence` profile correlates reassertions only before its 10-second
  stable clear or 5-second hardware hold. The production excerpt's median clear
  is much longer, so every later `on` starts a fresh generation.
- Unchanged replay produced 814 positive effects and only 22 correlated-flap
  effects across the three-day Shaila history.
- Disconfirming check: if the unchanged engine kept the exact isolated excerpt
  below belief `0.70`, repeated full-weight episodes were not the controlling
  problem. The retained regression instead fails near `0.997`.

## Retained regression

`tests/incidents/test_inc_2026_08_22_1212z_shaila_office_sustained_flapping_stays_below_on_threshold.py::test_inc_2026_08_22_1212z_shaila_office_sustained_flapping_stays_below_on_threshold`

The timestamps, states, `stay_presence` profile, node reliability `0.75`, and
isolated target-belief expectation are immutable production evidence. Synthetic
room names in the executable test prevent room-specific production logic.