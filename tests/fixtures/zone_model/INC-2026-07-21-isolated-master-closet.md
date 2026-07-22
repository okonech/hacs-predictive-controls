# INC-2026-07-21 isolated master-closet activation

## Public contract

- Affected entity: `binary_sensor.master_bedroom_closet_active`.
- Observed behavior: the entity changed from `off` to `on` twice and the normal
  closet-light automation received those edges.
- Expected behavior: an isolated closet sensor episode remains publicly `off`
  unless supported by graph-local traversal or a mature prediction.
- Retained event times: 2026-07-21 02:22 EDT and 03:33 EDT. The retained source
  has minute precision; the regression does not claim unobserved seconds.

## Evidence

Verified from the incident report and repository configuration:

- authoritative occupant count was 2;
- tracked activity existed in Alex office and Guest Bedroom;
- no master-bedroom-entrance or master-bedroom path supported the closet;
- the closet physical node is adjacent only to master-bedroom entrance and
  master bathroom, uses the `stay_pir` profile, and had legacy map weight 0.8;
- the current engine labels the isolated acquisition
  `source_free_corroborated` and reproduces an `off -> on` edge at both retained
  minute frontiers.

The entity aliases in the executable fixture are reconstructed from the
checked-in map plus the incident report; they are not claimed to be exported
raw Home Assistant rows. Only the retained public edge times and topology facts
above are treated as incident evidence.

The executable acceptance trace realizes the reported Alex-office and
Guest-Bedroom activity as two deterministic, disconnected, three-node confirmed
fronts immediately before each retained closet minute. Those synthetic setup
offsets are not claimed as production timestamps; they make the reported
`occupancy = 2` and two-current-front precondition explicit so the regression
can also prove pending expiry and the `untracked_expired` audit outcome.

Retained diagnostic values from the incident discussion were approximately
0.05 before and 0.72 after the closet edge. Full raw Home Assistant rows,
sub-minute timestamps, and the exact token payload were not retained in this
repository, so the frozen test does not invent or assert them.

## Controlling layer and requirements

- Layer: `TRAVERSAL`, projected by `POLICY`.
- Mechanism: positive count and the stay profile's
  `single_node_reacquisition` flag authorize a lone local episode.
- Governing requirements: `REQ-GOAL-003`, `REQ-GOAL-005`, `REQ-EVID-008`,
  `REQ-TRAV-005`, `REQ-POLICY-001`, `REQ-GOV-002`, and `REQ-GOV-005`.
- Disconfirming check: if the unchanged engine kept the closet inactive without
  any adjacent event, the source-free hypothesis would be false. The focused
  regression failed because the engine instead activated it at both frontiers.

## Retained regression

`tests/test_zone_model_public_contract.py::test_inc_2026_07_21_isolated_master_closet_never_acquires`

The immutable public assertion is that no closet `acquired` edge occurs, the
closet remains inactive while both disconnected fronts are current, and the
unsupported candidate eventually records `untracked_expired`. Other track and
belief internals may evolve as long as they continue to satisfy the
specification.
