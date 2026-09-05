# INC-2026-08-23 Master Bathroom asserted-stay release

## Public contract

- Affected entity: `binary_sensor.master_bathroom_active`.
- Observed behavior: the entity changed from `on` to `off` at
  `2026-08-23T06:06:13.173267+00:00` while the same Master Bathroom mmWave
  episode remained physically asserted.
- Expected behavior: a positive-count contradiction may diagnose the asserted
  stay episode and close its movement authority, but must not emit `released`
  until that episode stably clears or becomes unavailable. Count zero remains
  an immediate categorical release.
- Consumer effect: the normal Home Assistant automation received the off edge
  and turned the light off five minutes later at 02:11:13 EDT.

## Retained evidence

Verified from the read-only Predictive Controls status, Home Assistant state,
automation trace, checked-in map, and upper-floor plan:

- authoritative occupant count was 2;
- the Master Bathroom node used `stay_presence`, reliability `0.7`, on/off
  thresholds `0.70/0.30`, and release dwell `120s`;
- the room is an upper-floor ensuite represented as adjacent to Master Bedroom
  Closet; no compatible outward traversal was retained;
- the mmWave episode acquired at `2026-08-23T05:56:40.122876+00:00`, with
  belief changing from `0.053852564884601356` to `0.7793789008408025`;
- two independent outside support IDs remained selected continuously through
  the conflict dwell;
- count conflict health-degraded the same asserted episode at
  `2026-08-23T05:58:43.075447+00:00`, at belief `0.7959950372145533`;
- the filter crossed the off threshold at
  `2026-08-23T06:04:11.052856+00:00`;
- policy released at `2026-08-23T06:06:13.173267+00:00`, changing belief from
  `0.21919698158049541` to `0.21639972587294073`;
- count conflict did not clear until `2026-08-23T06:10:18.237060+00:00`;
- raw mmWave remained on through the public release and later cleared at
  approximately 02:14:52 EDT; and
- Scene 002 at 02:11:20 EDT was not ingested by the then-running old map. That
  deployment issue is independent of the initial false release.

The exact public and belief frontiers above are retained production facts. The
executable fixture uses a generic two-support topology and synthetic setup
offsets to construct the two anonymous supports because their source sensor
event rows were not retained. It restores the exact observed post-acquisition
belief through the public target snapshot boundary so replay does not depend on
minor likelihood-arithmetic differences between the deployed and workspace
builds.

## Controlling layer and requirements

- Layers: `COUNT`, then `ZONE_BELIEF`, then `POLICY`.
- Mechanism: `REQ-COUNT-009` changed the asserted episode and belief context to
  health-degraded; timer advancement then crossed the ordinary off threshold
  and completed release dwell without a local clear or unavailable observation.
- Governing authority before this repair: `REQ-EVID-005`, `REQ-COUNT-003`,
  `REQ-COUNT-009`, `REQ-POLICY-002`, and `REQ-POLICY-003` explicitly permitted
  count conflict to remove the asserted-stay floor and begin public release.
- Disconfirming check: if the unchanged engine retained public `active` through
  `2026-08-23T06:06:13.173267+00:00`, count conflict was not the controlling
  cause. The exact regression instead failed with `active == false`.

## Retained regression

`tests/incidents/test_inc_2026_08_23_0556z_asserted_stay_never_releases_for_count_conflict.py::test_inc_2026_08_23_0556z_asserted_stay_never_releases_for_count_conflict`

The immutable public expectation is that the target remains active and emits no
`released` edge at the retained release frontier while the same raw stay
episode remains asserted. Retained input timestamps, count, profile,
reliability, thresholds, dwell, and belief checkpoints must not be weakened or
retimed to fit an implementation.