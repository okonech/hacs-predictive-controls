# Sustained Sensor Cadence Reliability

**Status:** Implementation, validation, and deployment verification complete

**Affected layers:** shared sensor profiles, physical episodes, zone belief,
traversal and acquisition, count support, policy, prediction learning,
persistence, diagnostics, Home Assistant entities, Reliability UI, Occupancy
Graph, and operator notification automation

**Related authority:** `REQ-MAP-002`, `REQ-MAP-005`, `REQ-EVID-001` through
`REQ-EVID-006`, `REQ-EVID-010`, `REQ-BELIEF-005`, `REQ-BELIEF-006`,
`REQ-BELIEF-009`, `REQ-TRAV-001`, `REQ-TRAV-013`, `REQ-COUNT-001`,
`REQ-POLICY-001` through `REQ-POLICY-003`, `REQ-PRED-003`, `REQ-PUBLIC-001`
through `REQ-PUBLIC-007`, `REQ-STATE-001` through `REQ-STATE-010`,
`REQ-DIAG-001` through `REQ-DIAG-007`, `REQ-PERF-001` through
`REQ-PERF-005`, and `REQ-GOV-001` through `REQ-GOV-006`

## 1. Objective

Treat repeated completed clear/reassert cycles from one `stay_presence` physical
node as correlated evidence without weakening one sustained assertion. Preserve
the first positive after a quiet boundary at its configured reliability. Scale
later linked positives so each paired stable-clear/positive cycle contributes no
net sensor likelihood in log space, while ordinary continuous-time context decay
continues.

The public and operational outcomes are:

1. the exact retained Shaila Office excerpt remains below target belief `0.70`
   and cannot independently activate, refresh, create traversal, move count
   support, or teach prediction;
2. one continuously asserted stay sensor remains strong local retention evidence
   and is never called flapping because of elapsed time alone;
3. an already-active stay zone cannot release while a cadence-correlated episode
   is asserted or inside stable-clear confirmation, but ordinary full-dwell
   release may proceed after stable clear;
4. a distinct trustworthy graph source may authorize a cadence-correlated target
   as genuine reentry without making that target a traversal or support source;
5. current flapping and suspected-stuck nodes appear in Reliability and their
   zones are highlighted red on the Occupancy Graph; and
6. at 20:00 local time, Home Assistant sends at most one daily summary only when
   one or more model-owned reliability warnings are current; cleared warnings
   remain available in bounded 24-hour history without causing a current-fault
   notification.

## 2. Retained Evidence And Verified Current State

The retained production record is
`tests/fixtures/zone_model/INC-2026-08-23-shaila-office-sustained-flapping.md`.
The immutable public regression is
`tests/test_zone_model_engine.py::test_inc_2026_08_23_shaila_office_sustained_flapping_stays_below_on_threshold`.
Against unchanged code, its nine `on` generations drive isolated target belief
to `0.9970341715801893`; the required assertion is `< 0.70`.

The complete August 20 through 22 read-only corpus contains 1,674 Shaila Office
state changes. A ten-minute per-edge linker produces one 800.6-minute run with
577 changes. The next longest run among all 12 mapped mmWave entities is 125.0
minutes and every other mapped sensor is below 62 minutes. This evidence supports
shared `stay_presence` calibration of ten minutes for cycle linkage and three
hours for a visible sustained-cadence warning. It does not support applying the
same long-cycle detector to PIR, transition, entry, or interaction profiles.

The controlling implementation paths are:

1. `PhysicalEpisodes._continues_flap` in
   `custom_components/predictive_controls/zone_model/episodes.py` correlates only
   reassertions within three seconds of clear start or inside the five-second
   hardware hold.
2. Later reassertions call `PhysicalEpisodes._start_episode`, create a fresh
   generation, clear `cadence_warning`, and emit `positive`.
3. `ZoneModelEngine._apply_effect` calls
   `ZoneBeliefFilter.apply_positive`, then normal traversal authorization.
4. `ZoneBeliefFilter.apply_positive` adds the full reliability-tempered positive
   log likelihood. `apply_stable_clear` adds a much weaker negative likelihood.
5. `renderReliability` in `frontend/panel.js` filters only `health_warning`.
   Episode status already transports both `health_warning` and
   `cadence_warning`.
6. `renderOccupancyGraph` consumes `model.health_warnings`, and
   `renderZoneCard` has no warning-zone class. Active/frontier visuals can
   therefore remain blue/green while a node is unhealthy.
7. No persisted warning-occurrence history or automation-facing reliability
   warning entity exists. Current booleans cannot answer “detected in the past
   24 hours” after a warning clears.

The local falsifiable hypothesis is that fresh-generation positive likelihood,
not short-window edge density alone, causes the incident. The retained replay
disconfirms the alternative: unchanged code recognizes only 22 correlated flaps
but applies 814 fresh positives over the full Shaila history, and the exact
isolated excerpt reaches `0.9970341715801893`.

## 3. Authority Amendment

Current `REQ-EVID-001`, `REQ-EVID-003`, and `REQ-EVID-010` specify fresh episodes
and same-episode flaps but do not govern completed cycles across episode
generations. Current `REQ-BELIEF-009` applies configured reliability to every
local observation but does not distinguish a later correlated observation.
Current diagnostics describe current warning state but not a bounded 24-hour
occurrence projection.

Before production changes, `SPECIFICATION.md` must be amended to require:

- shared-profile long-cycle correlation for completed `stay_presence` cycles;
- one full positive after a quiet boundary and likelihood-neutral later cycles;
- source-authority and learning exclusion for cadence-correlated positives;
- asserted/stable-clear-confirmation retention safety for an already-active stay
   zone;
- model-owned current and retained reliability warnings;
- a structured diagnostic sensor for the preceding-24-hour projection; and
- Reliability and Occupancy Graph warning presentation.

Phase 1 does not pass merely because this design document names those changes.
The numbered contracts must appear in `SPECIFICATION.md`, their acceptance
scenario must be added to Section 16, and Section 19 must remain descriptive
until implementation evidence exists. No matched production Python edit may
precede that authority edit.

This is not static reliability reduction. Reliability still tempers both the
first positive and each later paired clear/positive update.

## 4. Scope And Non-Goals

### In scope

- shared `stay_presence` cycle calibration only;
- completed stable-clear followed by reassertion across fresh generations;
- exact half-open event-time boundaries, timer advancement, count zero,
  unknown/unavailable, restore, and deterministic replay;
- target-only graph authorization from distinct trustworthy context;
- active-zone assertion and stable-clear-confirmation release protection;
- current warning state and one bounded latest occurrence per node/reason;
- status, one enabled-by-default diagnostic sensor, Reliability UI, Occupancy
  Graph warning priority, frontend tests, and one individual 20:00 Home Assistant
  automation; and
- retained incident, inverse, persistence, public-contract, entity, frontend,
  YAML, performance, and full repository gates.

### Non-goals

- no Shaila Office, room, entity, person, household member, or incident-time
  production branch;
- no static map reliability reduction and no change to configured reliability;
- no cadence inference from actuator/light/fan state, callback count, policy,
  prediction, or notification history;
- no long-cycle correlation for `stay_pir`, `transition_fast`,
  `entry_boundary`, or interaction pulses without a separate retained corpus;
- no suppression of the first positive after a quiet boundary;
- no classification of one sustained `on` as flapping;
- no automation-side cadence or stuck detection;
- no person identity, forced exact room count, or one-zone-per-occupant rule; and
- no notification service call or live Home Assistant mutation by repository
  tooling.

## 5. Shared Calibration And Likelihood Contract

`SensorProfile` gains two fingerprinted, validated fields:

- `cycle_correlation_window`; and
- `sustained_cadence_warning_window`.

For `stay_presence`, they are ten minutes and three hours. For all other current
profiles both are zero, which disables cross-generation cadence state. A
nonzero warning window requires a nonzero correlation window and must be greater
than the correlation window.

Let the configured positive and stable-clear likelihoods be
`p_e`, `p_o`, `c_e`, and `c_o`, where positive favors occupied and clear favors
empty. Let node reliability be `r`. The first positive after a quiet boundary
adds

$$
\Delta_+ = r\ln\left(\frac{p_o}{p_e}\right).
$$

Each later cadence-correlated positive adds

$$
\Delta_{c+} = r s\ln\left(\frac{p_o}{p_e}\right),\qquad
s = \frac{\ln(c_e/c_o)}{\ln(p_o/p_e)}.
$$

Its preceding stable clear adds

$$
\Delta_- = r\ln\left(\frac{c_o}{c_e}\right),
$$

so `Delta_c+ + Delta_- == 0` within absolute tolerance `1e-12`. For current
`stay_presence` calibration,
`s = 0.040879518931593604`. The implementation derives `s` from the belief
profile and validates `0 < s <= 1`; it does not store a duplicate magic constant.
Continuous-time decay still advances before each update, so the total belief
trajectory is not frozen.

A cadence-correlated positive creates a new deterministic episode generation,
sets the belief generation and asserted context to that episode, and records a
`correlated_positive` contribution. It does not reuse the previous episode ID.
Generation identity preserves restore idempotency.

`correlated_positive` is intentionally both a new `EpisodeEffect.kind` and a new
`BeliefContribution.kind`; they describe the same accepted fact at different
layers. `EpisodeEffect.reliability` remains the configured node reliability and
is never pre-scaled. Add
`ZoneBeliefFilter.apply_correlated_positive(episode_id, at, reliability)`. That
method advances decay, derives `s` from its own `BeliefProfile`, applies the
scaled likelihood, updates generation/asserted context exactly as
`apply_positive` does, and records the actual scaled log-odds delta. Deriving the
scale inside the filter prevents episode code from duplicating belief
calibration and prevents diagnostics from misreporting a pre-scaled value as
physical reliability. The constant-size calculation may run per correlated
positive; no persisted or mutable scale cache is required.

## 6. Cadence State Machine

Each `EpisodeState` adds these bounded fields:

- `cadence_run_started_at: datetime | None`;
- `cadence_last_transition_at: datetime | None`;
- `cadence_cycle_count: int`, saturated at `65535`;
- `cadence_correlated: bool`, describing the current generation; and
- `cadence_warning_reason: str | None`, one of `impossible_cadence` or
  `sustained_flapping` when `cadence_warning` is true.

The existing `cadence_warning` boolean remains the current warning projection.
A run is enabled only for a profile with nonzero cycle correlation.

The frozen-state invariants are exact:

- run start and last transition are both present or both absent;
- when present, run start is not after last transition and both are at or before
   the episode frontier;
- absent run timestamps require cycle count zero;
- positive cycle count requires an enabled profile and an open run;
- `cadence_correlated` requires an enabled profile and a current generation but
   does not require a current warning;
- `cadence_warning` is equivalent to a non-null cadence warning reason;
- `sustained_flapping` requires an open run and at least one completed cycle;
   `impossible_cadence` retains the existing same-episode hardware rule; and
- a profile with cross-generation correlation disabled retains no run, cycle,
   correlated, or `sustained_flapping` state; it may still retain the existing
   same-episode `impossible_cadence` warning and reason.

### 6.1 Start and link

1. A physical aggregate `known_on: false -> true` transition when no run is open
   starts a run at the positive timestamp, records that timestamp as the last
   transition, sets cycle count to zero, and emits ordinary `positive`.
2. A physical aggregate `known_on: true -> false` transition updates the
   last-transition timestamp only when a run is open. Stable clear retains the
   run. An individual alias callback that does not change aggregate `known_on`
   is still deduplicated under `REQ-EVID-002` and does not mutate cadence.
3. After stable clear, an aggregate `false -> true` transition at time `t` is
   correlated iff the run is open
   and `t < cadence_last_transition_at + cycle_correlation_window`. It increments
   the saturated cycle count, sets `cadence_correlated = true`, preserves the run
   start, updates the last transition, and emits `correlated_positive`.
4. An `on` exactly at the quiet deadline is not correlated. Deadline advancement
   happens before the external edge under `REQ-STATE-009`; it starts a new run
   and receives full configured reliability.
5. Existing same-generation burst/hardware cadence remains authoritative first.
   Such a reassertion emits the existing same-episode effect and never also emits
   `correlated_positive`, but its aggregate physical transition still updates
   `cadence_last_transition_at` for an open run. An impossible-cadence warning
   remains current across later linked generations until quiet/reset; later
   sustained cycles do not replace its reason or open a second occurrence.

### 6.2 Quiet, health, and reset

The quiet deadline is
`cadence_last_transition_at + cycle_correlation_window`. At that half-open
frontier the run fields and current cadence warning clear. The current
generation's `cadence_correlated` marker does not become trustworthy merely
because time passed; it remains until a later fresh independent generation,
unknown/unavailable, or categorical count-zero reset.

Unknown/unavailable atomically clears run fields, current cadence warning, and
the current correlated marker without adding absence evidence. Count zero does
the same while preserving existing categorical empty-house behavior. Neither
operation synthesizes a sensor edge.

Nonzero count changes do not reset, forgive, or extend cadence state. A remote
count transition does not establish local hardware recovery; count 1 to 2 or 2
to 1 therefore leaves the run, warning, and correlated marker unchanged. Fresh
distinct graph evidence can still authorize genuine reentry under Section 7.
An interaction `pressed` event is orthogonal to cadence: an interaction-only
node retains no cadence run, and the pulse neither updates a motion/presence
node's transition time nor counts as a cycle. Stale and duplicate observations
return before cadence mutation.

The sustained warning deadline is
`cadence_run_started_at + sustained_cadence_warning_window`. It is eligible only
after at least one completed linked cycle. If that deadline is earlier than the
current quiet deadline, advancement emits `sustained_flapping` exactly at the
warning deadline. If one advancement crosses both warning and quiet deadlines,
it emits the warning start first and warning clear second at their stored event
times. One uninterrupted `on` cannot satisfy the linked-cycle condition.

If `impossible_cadence` is already current when the three-hour sustained
deadline crosses, no sustained-warning start effect is emitted. The current
impossible reason remains until quiet/reset, and its occurrence remains the one
current cadence record for that node.

Timer processing orders stored frontiers by
`(timestamp, node_id, effect_priority, effect_kind)`, where cadence-warning
clear has priority `0` and sustained-warning start has priority `1`. At equal
timestamps, quiet expiry therefore wins and an exactly quiet run never flashes
a warning. If one later advancement crosses
an earlier warning deadline and a later quiet deadline, it first activates the
warning at the stored warning timestamp, then clears the warning and run fields
at the stored quiet timestamp. The final state has no open run or current
warning, while the ledger retains one cleared occurrence with both exact times.
Deadline processing completes before an external edge at the same timestamp;
the edge observes the post-deadline state and cannot double-clear it.

`EpisodeEffect` gains an optional validated `warning_reason`. New effects are
`correlated_positive`, `sustained_flapping`, and
`cadence_warning_cleared`. Warning-start effects carry their reason;
`cadence_warning_cleared` and `health_recovered` carry the reason being closed.
An engine-owned bounded ledger applies these effects in sorted event-time order
inside the same atomic model operation as episode, belief, and policy state.
`warning_reason` is null for every other effect kind. `impossible_cadence` and
`sustained_flapping` require their matching reason; a clear/recovery requires one
of the four ledger reasons. `EpisodeEffect.reliability` remains the unmodified
configured reliability for every effect.

A stable clear or unknown/unavailable state clears current suspected-stuck
warning state and closes the matching occurrence. For `count_conflict`, the
conflict tracker also removes that no-longer-asserted target at the same
frontier; for `assertion_timeout`, the episode and belief health state recover.
The existing count-conflict release veto still covers physical assertion and
the stable-clear confirmation window. A node that is no longer asserted after
stable clear, or is unavailable, is historical rather than currently
suspected-stuck. A later warning creates a new occurrence.

At stable clear, `stable_clear` applies first, then `health_recovered` with the
old degradation reason, then count-conflict reevaluation and policy. This
preserves the calibrated clear likelihood, closes health state without restoring
an asserted belief floor, records existing `stuck_conflict_cleared`/`recovered`
diagnostics for a count conflict, and starts ordinary release dwell only after
the clear is stable. Unknown/unavailable closes health and conflict state before
the unavailable belief context is applied. Neither path emits a synthetic
positive, acquisition, refresh, traversal, or support event.

## 7. Evidence, Traversal, Policy, And Learning Ordering

For a cadence-correlated positive at one accepted frontier:

1. advance all earlier episode, quiet, warning, belief, token, support,
   prediction, conflict, and policy deadlines;
2. create the new correlated episode and apply `Delta_c+` after normal elapsed
   decay;
3. call a dedicated `TraversalFrontier.authorize_correlated_target` path against
   distinct trustworthy same-zone, adjacent, pending-pair, or bounded
   missed-edge physical context;
4. when independently authorized, apply the normal
   `ZoneBeliefFilter.apply_arrival_transition` and allow ordinary inactive-zone
   acquisition;
5. never issue a traversal token for the correlated target, remember it as a
   pending candidate, reopen prior target continuity, create/rebind/move count
   support from it, apply source outward context from it, publish an
   already-active refresh, or enqueue it for route learning or prediction-source
   preparation;
6. apply policy with an asserted/clearing hold for an already-active stay zone;
7. persist and publish through existing edge-gated runtime ordering.

The dedicated traversal path may consume and remove an already-open candidate
from a distinct physical node and may issue that candidate's source token under
the existing adjacent-pair contract. It never calls `_remember_pending` for the
correlated target. It records ordinary bounded authorization use against source
tokens but returns no issuable target token. `stay_presence` is a stay role, so
count-transition boundary authorization is structurally inapplicable and is not
added as a substitute for physical independence. Positive count alone is never
sufficient.

Its signature mirrors ordinary authorization and returns one
`TraversalAuthorization`:

```python
authorize_correlated_target(
   target: EpisodeState,
   at: datetime,
) -> TraversalAuthorization
```

The returned authorization may carry existing source tokens, new authorization
uses, confidence, path, and provenance. It never reopens retained source
continuity, creates a target pending candidate, or yields a target token. The
existing `TraversalAuthorization` dataclass has no target-token field. The engine
therefore returns `(authorization, effect, None)` from `_apply_effect`; the final
`None` is the separate issuable-token result. No caller may pass this
authorization to `TraversalFrontier.issue`.

Policy separates `confirming_evidence` from `refresh_eligible`. A
`correlated_positive` at the current frontier is confirming evidence only: with
a valid target-only authorization it may acquire an inactive zone, and it may
confirm a `predicted` phase whose mature lease was already created by a distinct
confirmed source. Only ordinary `positive` and `interaction` effects are refresh
eligible. The correlated authorization may remain in the result/audit as the
public acquisition reason, but `_prepare_predictions`, pending prediction
learning, `TargetPredictionManager.commit`, and support application must filter
it explicitly. Prediction itself never changes belief.

`ZonePolicy._trustworthy` is split into two predicates. `confirming_evidence`
accepts ordinary positive, interaction, or `correlated_positive`; the correlated
case requires a valid dedicated authorization for inactive acquisition but may
confirm an already-predicted phase without creating source authority.
`refresh_eligible` accepts only ordinary positive and interaction. A current
cadence warning does not invalidate independently authorized target confirmation;
it only prevents this node from becoming a source. Health degradation remains a
block. These rules amend the current target-health prediction block narrowly and
do not let an isolated flapping node acquire.

The engine keeps `authorizations` for policy/audit and a separate
`source_authorizations` tuple containing only ordinary trustworthy source
effects. Only `source_authorizations` reaches `_prepare_predictions`, pending
learning, support application, and later `TargetPredictionManager.commit`.
For a correlated target, support application receives no effect,
authorization, or target token; existing supports merely advance to the event
frontier.

When no independent authorization exists, correlated local belief remains
accepted but the inactive zone stays public `off`; no pending candidate is
created. Positive count alone is not independent authorization.

The target-only path does not call `TraversalFrontier.apply_outward_context`.
The suspect target observation therefore cannot accelerate source-zone decay.
Existing source token state and uses remain bounded and otherwise unchanged.

`ZoneModelEngine._asserted_stay_hold_zones` includes a cadence-correlated stay
generation while its episode status is `asserted` or `clearing`. This means raw
`on` and the bounded stable-clear confirmation window both veto creation or
continuation of release dwell. The hold applies in both
`_release_due_policies` and `_evaluate_policies`, clears pending release dwell,
and emits no public refresh. The stable-clear effect removes this cadence hold;
ordinary threshold evaluation may start a new full release dwell at that exact
frontier. Count zero remains higher priority and immediately clears active
output.

## 8. Reliability Warning Ledger

The target snapshot adds a sorted tuple of `ReliabilityWarningOccurrence`.
Each record contains:

- `node_id` and `zone`;
- `kind`: `flapping` or `suspected_stuck`;
- `reason`: `impossible_cadence`, `sustained_flapping`, `assertion_timeout`, or
  `count_conflict`;
- `first_observed_at`;
- `last_observed_at`; and
- `cleared_at: datetime | None`.

Identity is `(node_id, reason)`. At most one latest record per identity is
retained, so storage is bounded by four records per configured physical node.
Activation creates or updates the current occurrence. Clearing stamps
`cleared_at` and `last_observed_at`. A recurrence after clear replaces that
identity with a new first-observed time. Records are deterministically sorted by
node and reason.

“Replaces” means overwrite in place: the prior cleared record for that identity
is discarded, not appended or marked superseded. There is never more than one
record, open or cleared, for one identity. Distinct reasons remain separately
bounded identities; the cadence state machine never keeps both cadence reasons
current on one episode.

A warning is reportable at projection time `t` iff it is active or
`last_observed_at > t - 24 hours`. Exactly 24-hour-old cleared warnings are
excluded. Old latest records may remain in the fixed-size persisted tuple, but
status and entities never project them as within-window. Restore at `t` validates
all fields, reconstructs no missing occurrence, and applies the same projection.
No queue, daily bucket, or unbounded history is permitted.

The duration is an exact UTC elapsed-time window, not a local calendar-day
window. Projection requires UTC-aware `t`; local daylight-saving changes do not
alter its length. Home Assistant's `20:00:00` trigger remains local wall time.

Current warning state remains episode-owned. The ledger is an occurrence record,
not evidence and not policy authority.

`ReliabilityWarningOccurrence.__post_init__` validates nonempty configured
identifiers, the exact kind/reason mapping, UTC times, and
`first_observed_at <= last_observed_at`. Active records have `cleared_at is None`;
cleared records require `first_observed_at <= cleared_at == last_observed_at`.
`ZoneModelSnapshot.__post_init__` requires unique identities sorted by
`(node_id, reason)`. Snapshot restore additionally verifies that every node and
zone match the current map. The ledger is separate from `EpisodeState`; snapshot
validation requires each active occurrence to agree with the corresponding
current episode warning and permits cleared historical records independently.

Every model result snapshot is taken only after all due warning starts, clears,
and ledger mutations for that frontier complete. Persistence cannot observe a
partially applied warning transition. A snapshot before a deadline contains
neither the later episode warning nor occurrence; restore advances and applies
it once. A snapshot at or after the deadline contains both and restore does not
repeat it.

## 9. Persistence, Upgrade, And Rollback

Home Assistant Store version remains `7` and the inference schema remains
`zone-belief-v4` only if all new fields are additive and strict decoders provide
explicit safe defaults:

- absent cadence timestamps -> `None`;
- absent cycle count -> `0`;
- absent correlated marker -> `false`; and
- absent warning occurrences -> an initially empty tuple before the deterministic
   active-warning migration below.

For an accepted pre-feature v4 episode, an absent cadence reason defaults to
`impossible_cadence` when the already-existing `cadence_warning` boolean is true,
otherwise to `None`. The migration creates an active impossible-cadence
occurrence at the episode's exact `last_event_at`. It also creates an active
suspected-stuck occurrence for an existing `health_warning`, using
`degradation_reason` and exact `degraded_at`. These are diagnostic migrations
from persisted current facts, not synthetic observations, likelihoods, edges,
or policy events. Missing required source timestamps reject atomically.

The profile fingerprint includes both new calibration fields. Restore accepts
exactly one pre-feature v4 fingerprint shape for an otherwise identical map,
then applies the additive defaults and writes the current fingerprint on the
next normal save. It must not accept arbitrary fingerprint mismatches. An
in-progress cadence run before upgrade is deliberately forgotten; the first
post-upgrade positive after stable clear receives one full positive and begins
new bounded correlation. Existing valid beliefs, active policy, traversal,
support, and prediction state remain intact and no public edge is synthesized.

The compatibility comparison is deterministic: factor the current fingerprint
payload builder, compute the current hash with both cadence fields, and compute
one legacy hash from the identical payload with only those two profile keys
omitted. The legacy hash is accepted only for `zone-belief-v4` payloads whose
episode rows contain none of the newly added run/cycle/correlation/reason keys
and whose snapshot has no occurrence key. The pre-existing `cadence_warning`
key is expected and does not disqualify legacy input. Mixed old/new shapes reject
atomically. This is a one-release reader, not a wildcard for map or calibration
changes.

Strict restore validates timestamp ordering, UTC awareness, field consistency,
warning enums, occurrence uniqueness/sort order, configured node/zone identity,
cycle count bounds, and that profiles with cross-generation correlation disabled
retain none of the new run/cycle/correlated/sustained state. Existing
same-episode impossible-cadence state remains valid. Invalid state fails
atomically through the existing cold-bootstrap path.

Rollback to code that does not recognize the new fingerprint may reject target
inference and cold bootstrap without changing map, learned, entity-registry, or
user configuration. Operational rollback should restore the pre-upgrade Store
payload when preservation of active inference is required. Notification YAML is
safe to leave disabled or remove independently because it owns no model state.

## 10. Diagnostics And Public Entity Contract

Status keeps existing episode booleans and adds cadence reason/run fields needed
for explanation. It adds structured current `reliability_warnings` and bounded
`reliability_warning_occurrences`; existing `health_warnings` remains a
compatibility list of current warning node IDs and includes either warning kind.
No warning list changes occupancy authority.

Add one enabled-by-default sensor:

- name/entity target: `sensor.predictive_controls_reliability_warnings`;
- unique ID: `<entry_id>_predictive_controls_reliability_warnings`;
- native value: count of distinct reportable `(node_id, kind)` pairs at the
  diagnostic publication frontier;
- icon: `mdi:alert-circle-outline`; and
- attributes: `window_hours: 24`, `active_count`, `warnings`, deterministic
   24-hour `summary`, and deterministic `active_summary`.

Implement it as a `sensor` platform entity with diagnostic entity category,
`_attr_entity_registry_enabled_default = True`, and stable unique ID. The name
`Predictive Controls Reliability Warnings` is intended to generate
`sensor.predictive_controls_reliability_warnings`; rollout must verify the
actual registry entity ID before enabling the checked-in automation because
Home Assistant may preserve an existing user rename.

Each `warnings` row exposes node, zone, kind, reasons, active reasons, first
observed, last observed, cleared time, and active state. The entity uses the existing bounded
30-second diagnostic dispatcher and does not materialize policy audit. A
30-second publication delay may affect display freshness but cannot create an
extra daily notification because the automation has one time trigger.

Projection groups reportable records by `(node_id, kind)`. One row exposes
sorted `reasons`, sorted `active_reasons`, the earliest first-observed time, the
latest last-observed time, `active == bool(active_reasons)`, and `cleared_at`
equal to `None` while active or the latest grouped clear time otherwise. The
native value is the number of grouped rows. This avoids double-counting one node
whose impossible and sustained cadence reasons both occurred in the window.

A pure projection helper accepts occurrences and an explicit UTC `at`, merges
multiple reasons to distinct `(node_id, kind)` rows deterministically, and is
used by status/entity tests. The entity supplies Home Assistant UTC-now when it
writes state; it does not use the model's last-event frontier as wall-clock now.
The `summary` is generated from the same projected rows, never from policy audit.

The pure helper's 24-hour cutoff is exact. The published Home Assistant state is
allowed to trail UTC-now by less than the existing 30-second diagnostic interval;
therefore the 20:00 report may conservatively include a warning that crossed its
24-hour cutoff less than 30 seconds after the last publication. It must never
omit an active warning present in the published episode state. This bounded
display/reporting tolerance does not alter model state or inference.

## 11. Frontend Contract

### Reliability

`renderReliability` includes an episode when `health_warning` or
`cadence_warning` is true. Each row displays one explicit label:

- `Flapping` for cadence warning; or
- `Suspected stuck on` for health warning.

When both are true, the row shows both labels. The count is the number of unique
warning nodes, not the sum of booleans. Empty state remains explicit.

One frontend helper derives warning descriptors from
`occupancy_diagnostics.episodes`, sorted by `(zone, node_id, kind)`. Reliability
and Occupancy Graph consume that same helper; neither consumes retained
occurrences for current styling. Existing `health_warnings` remains transport
compatibility, not a second frontend source.

### Occupancy Graph

A zone is warning-red when any current episode in that zone has either warning
boolean. `renderZoneCard` adds `has-reliability-warning`, an accessible title
that includes warning kind and node ID, and visible compact text listing the
warning kind. Warning red overrides active box shadow, normal status border,
frontier outline color, and confidence-bar color. Solid/dashed geometry may
continue to communicate active/frontier semantics, but no blue, green, or
status color may visually outrank the red health state. Add a red warning legend
item.

Zone aggregation is deterministic and deduplicates node IDs. Warning styling is
current-state only; a cleared 24-hour occurrence remains reportable to the daily
sensor but does not keep the graph red.

`renderOccupancyGraph` builds one `Map<zone, descriptors>` and passes it to
`renderZoneCard`. A warning card includes
`class="has-reliability-warning"`, a `.reliability-warning-label`, and a title
formed from its sorted node/kind descriptors. CSS uses
`var(--error-color, #db4437)` in selectors at least as specific as
`.zone-card.has-reliability-warning`,
`.zone-card.is-active.has-reliability-warning`, and
`.zone-card.has-frontier.has-reliability-warning`; these selectors set the left
border, outline, box shadow, label, and confidence-bar fill red. The frontier
outline remains dashed and the active shadow remains solid, preserving shape
semantics while red wins color precedence. Each zone card renders one
consolidated visible warning label; its title lists every deduplicated current
node/kind descriptor for that zone.

## 12. Daily Home Assistant Notification

Add one individual automation file under `home-assistant/automations/` with a
stable top-level `id: predictive_controls_reliability_warning`. It has exactly
one time trigger at `20:00:00`, so it runs at most once per local calendar day.
It proceeds only when the sensor's `active_count` attribute is greater than zero.

The action sends `notify.notify` and calls `persistent_notification.create` with
stable `notification_id: predictive_controls_reliability_warning`. The message
uses the sensor's deterministic `active_summary` and states that the listed
warnings are current. The
automation does not inspect raw motion entities, calculate cadence, retain its
own timestamps, or mutate Predictive Controls. An unavailable/missing diagnostic
sensor produces no notification rather than a false all-clear. The condition is
a defensive template using `state_attr(...) | int(0) > 0`, so missing, null,
`unknown`, and `unavailable` values are ordinary false conditions. Cleared-only
history never sends. The automation uses
`mode: single` and has no state, event, startup, or second time trigger. The time
trigger uses Home Assistant's configured system timezone.

## 13. Alternatives Considered

### Reduce Shaila Office static reliability

Rejected. It is room-specific and repeated positive likelihood still
accumulates toward certainty for any nonzero reliability.

### Warn only after three hours

Rejected as the inference repair. The exact 22-minute excerpt already reaches
`0.997`; warning-only behavior leaves the root cause unchanged. Three hours is a
health-presentation boundary, not permission to stack evidence for three hours.

### Suppress every repeated positive entirely

Rejected. A new generation still represents current local assertion. Scaling
its positive to neutralize the paired clear preserves finite current-state
influence and deterministic context without multiplying independent evidence.

### Detect by short-window edge density

Rejected. Guest Bedroom and Dining Room had denser ordinary 15-minute windows
than Shaila Office. Persistence over hours, not local density alone, separates
the retained corpus.

### Let the frontend or automation detect cadence

Rejected. It would duplicate model semantics, lose restart determinism, and let
consumers disagree about health.

### Read raw current episode booleans in the automation

Rejected. The model-owned entity already exposes a deterministic current
projection through `active_count` and `active_summary`; duplicating episode
interpretation in Home Assistant would couple the consumer to model internals.
The bounded historical projection remains useful for inspection but does not
authorize a current-fault notification.

## 14. Implementation Phases

### Phase 1: Authority and shared types

Amend `SPECIFICATION.md`, add shared profile fields, episode/ledger types, enums,
and strict invariants. Do not change episode behavior before authority lands.
Focused proof: `tests/test_zone_model_profiles.py` and type-construction tests in
`tests/test_zone_model_v3_types.py`.

### Phase 2: Episode and belief semantics

Implement bounded run transitions, exact deadlines/resets, correlated-positive
likelihood, current warning lifecycle, and active asserted/clearing hold. Turn
the exact Shaila regression green without modifying its timestamps or
assertions.
Focused proof: `tests/test_zone_model_episodes.py`,
`tests/test_zone_model_filter.py`, the immutable test in
`tests/test_zone_model_engine.py`, and stable-clear recovery in
`tests/test_zone_model_count.py`.

### Phase 3: Authority exclusions and reentry

Implement target-only independent authorization and explicit exclusions from
pending, traversal token issue/reopen, supports, refresh, prediction source, and
learning. Retain graph-authorized true reentry and mature-prediction confirmation.
Focused proof: `tests/test_zone_model_traversal.py`,
`tests/test_zone_model_policy.py`, `tests/test_prediction.py`,
`tests/test_zone_model_supports.py`, and
`tests/test_zone_model_public_contract.py`.

### Phase 4: Persistence and diagnostics

Persist/restore cadence and warning occurrence state, accept only the reviewed
pre-feature fingerprint, expose status projections, and add the diagnostic
sensor.
Focused proof: `tests/test_zone_model_persistence.py`,
`tests/test_zone_model_diagnostics.py`, `tests/test_status.py`, and
`tests/test_entity_platforms.py`.

### Phase 5: Frontend and automation

Update Reliability and Occupancy Graph warning presentation, rebuild the versioned
panel artifact, add frontend tests, and add the 20:00 individual Home Assistant
automation with YAML validation.
Focused proof: `tests/frontend/panel_registration.test.js` plus the checked-in
automation validator.

### Phase 6: Full validation and rollout

Run all focused inverses, full repository gates, bounded benchmark, diff checks,
and independent conformance review. Update Section 19 only with executed counts
and evidence. Deploy model/integration first, verify the sensor entity ID and
attributes, then enable the automation. Roll back the automation independently
if notification behavior is wrong.

The reference benchmark adds cadence-correlated target authorization as a named
fast path and qualifies 100/100 in-memory decisions without target token,
support, prediction-learning, or audit-size dependence. It remains inside the
existing 100-event routine and 1,000-event hard cap.

## 15. Acceptance Matrix

The implementation is acceptable only when tests prove:

1. the immutable Shaila excerpt remains `< 0.70`, inactive, and edge-free;
2. one sustained `on` receives full evidence, retains an already-active zone,
   and never raises flapping at ten minutes, three hours, or trust horizon;
3. the first positive after quiet is full; later linked positives use the exact
   derived scale and paired likelihood deltas cancel;
4. a reassertion immediately before ten minutes is correlated, while one exactly
   at ten minutes is full;
5. warning starts exactly at three hours only with a completed linked cycle,
   and does not start when quiet expiry is first or equal;
6. one advancement crossing warning then quiet records both ordered occurrence
   transitions and leaves no current warning;
7. unknown, unavailable, and count zero reset bounded cadence without synthetic
   positive, clear, traversal, support, policy, prediction, or learning events,
   while nonzero count changes do not reset local cadence;
8. stale, duplicate, alias, and same-episode impossible-cadence inputs remain
   idempotent and cannot double-count cycles, and an interaction pulse neither
   creates nor changes a cadence run;
9. a cadence-correlated target alone cannot activate, create pending state,
   issue/reopen a token, create/move/rebind support, refresh active policy, or
   teach prediction;
10. a distinct valid same-zone/adjacent/missed-edge/pending-pair source and a
    mature existing prediction can authorize genuine target reentry, while the
    correlated target remains ineligible as a later source;
11. an already-active correlated stay zone cannot release while asserted or
   inside stable-clear confirmation; stable clear starts ordinary full release
   dwell, and count zero remains immediate;
12. count 0, 1, and 2, two occupants on separate fronts, and two occupants in one
    zone preserve non-identity and same-zone multiplicity;
13. restart before, exactly at, and after quiet and warning deadlines matches
   uninterrupted execution byte-for-byte apart from runtime timing fields, and
   no persisted snapshot contains only one side of a warning/ledger transition;
14. additive pre-feature v4 restore preserves active/public state without a
   synthetic edge, infers existing impossible-cadence and stuck warning
   occurrences from exact persisted timestamps, and rejects mixed or malformed
   cadence/ledger state atomically;
15. current stuck/flapping warnings activate and clear occurrence records;
   recurrence overwrites only the matching node/reason record, and an
   impossible-cadence warning remains one current occurrence across later linked
   sustained cycles until reset;
16. active warnings remain reportable; cleared warnings are included immediately
   before 24 elapsed UTC hours and excluded exactly at 24 hours;
17. the diagnostic sensor has stable unique ID, enabled default, bounded
    attributes, deterministic ordering, and no policy-audit materialization;
18. Reliability shows cadence and health warning labels without duplicates;
19. warning zones render red, including active/frontier zones, and red styling
    disappears when current warning clears while retained daily history remains;
20. the 20:00 automation does nothing for missing/unavailable/zero active count
   or cleared-only history, sends both notification actions once under normal
   successful service execution for current warnings, uses `active_summary` and
   the stable persistent notification ID, and has no second trigger;
21. touched fast paths stay within `REQ-PERF-001`, routine publication remains
    bounded, and the 100-event benchmark passes; and
22. every prior retained incident and full repository gate remains green.

## 16. Validation Commands

Focused implementation checks use `--no-cov` and touched-file lint after each
coherent phase. The minimum focused commands are:

```bash
.venv/bin/python -m pytest -q --no-cov tests/test_zone_model_profiles.py tests/test_zone_model_v3_types.py
.venv/bin/python -m pytest -q --no-cov tests/test_zone_model_episodes.py tests/test_zone_model_filter.py tests/test_zone_model_engine.py -k 'cadence or shaila_office or asserted_stay_hold'
.venv/bin/python -m pytest -q --no-cov tests/test_zone_model_traversal.py tests/test_zone_model_policy.py tests/test_prediction.py tests/test_zone_model_supports.py tests/test_zone_model_public_contract.py -k 'correlated or target or prediction or support'
.venv/bin/python -m pytest -q --no-cov tests/test_zone_model_persistence.py tests/test_zone_model_diagnostics.py tests/test_status.py tests/test_entity_platforms.py -k 'warning or cadence or reliability'
npm run test:frontend
npm run build:frontend
```

After each Python phase, run Ruff against its touched Python files. Final gates
are:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
npm run test:frontend
npm run build:frontend
.venv/bin/python benchmarks/occupancy_performance.py
```

From the homelab repository, validate the automation with the checked-in parser:

```bash
home-assistant/scripts/validate-automation-yaml.sh \
   "home-assistant/automations/Predictive Controls reliability warning.yml"
```

Final review also runs `git diff --check` in both repositories and verifies
generated `panel-v0.2.6.js` matches the source build.

## 17. Rollout And Failure Handling

1. Preserve the pre-upgrade Store payload before first current-fingerprint save.
2. Deploy integration code and reload the config entry.
3. Verify no synthetic public edges, current active zones, warning sensor entity
   ID, native count, and attributes.
4. Exercise a synthetic/replay cadence trace; do not deliberately flap live
   hardware for three hours.
5. Add or enable the 20:00 automation only after the sensor contract is visible.
6. If model behavior regresses, disable the automation, restore the preceding
   integration release and pre-upgrade Store payload, then reload. Map, learned,
   entity-registry, and user configuration are not rewritten by this repair.

The automation must remain disabled until Developer Tools confirms the actual
entity ID and a numeric warning state. If a preserved user rename differs from
the checked-in entity ID, update the automation reference before enabling it.
Rollback code will reject a new-fingerprint payload or cold-bootstrap if the
pre-upgrade payload is not restored. Either path loses new cadence run and
warning-ledger state; keeping the automation disabled during rollback prevents
stale diagnostic reporting. Rollback still emits no synthetic occupancy edge.

A malformed persisted warning ledger fails the entire target restore and uses the
existing cold-bootstrap path. A missing notification entity causes no send. A
notification service failure remains a Home Assistant automation error and does
not feed back into inference.

## 18. Implementation Surfaces

Expected Predictive Controls files:

- `SPECIFICATION.md`;
- `custom_components/predictive_controls/zone_model/types.py`;
- `custom_components/predictive_controls/zone_model/profiles.py`;
- `custom_components/predictive_controls/zone_model/episodes.py`;
- `custom_components/predictive_controls/zone_model/filter.py`;
- `custom_components/predictive_controls/zone_model/traversal.py`;
- `custom_components/predictive_controls/zone_model/engine.py`;
- `custom_components/predictive_controls/zone_model/persistence.py`;
- `custom_components/predictive_controls/occupancy_tracker.py`;
- `custom_components/predictive_controls/status.py`;
- `custom_components/predictive_controls/sensor.py`;
- `custom_components/predictive_controls/frontend/panel.js` and generated panel;
- focused Python/frontend tests and requirement matrix; and
- `benchmarks/occupancy_performance.py` only if an existing qualification must be
  extended for the touched fast path.

Expected homelab file:

- `home-assistant/automations/Predictive Controls reliability warning.yml`.

## 19. Tracking

| Phase                               | Status   | Completed evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                           | Next executable step |
| ----------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| 1. Authority and shared types       | Complete | Authority amended and independently reviewed; 28 focused profile/type tests and touched-file Ruff pass.                                                                                                                                                                                                                                                                                                                                                                      | None.                |
| 2. Episode and belief semantics     | Complete | Bounded cadence, correlated likelihood, warning ordering, stable-clear recovery, count-zero reset, and retention hold implemented; immutable Shaila regression and 136 focused tests pass; touched-file Ruff and editor diagnostics pass.                                                                                                                                                                                                                                    | None.                |
| 3. Authority exclusions and reentry | Complete | Dedicated target-only authorization, no-source exclusions, no-refresh acquisition, mature-prediction confirmation, and ordinary support transfer validated by 129 focused plus 67 adjacent tests; touched-file Ruff and editor diagnostics pass.                                                                                                                                                                                                                             | None.                |
| 4. Persistence and diagnostics      | Complete | Bounded occurrence mutation, exact pre-feature v4 migration, status projection, and enabled diagnostic sensor validated by 163 focused tests; touched-file Ruff and editor diagnostics pass.                                                                                                                                                                                                                                                                                 | None.                |
| 5. Frontend and automation          | Complete | Reliability renders explicit flapping/stuck rows; graph warning red overrides active/confirmed styling; 30 frontend tests pass and the versioned asset was rebuilt. Daily automation parses and its active-only one-trigger/two-notification contract passes structured validation. Live registry verification resolved `sensor.predictive_controls_reliability_warnings` and enabled stable-ID automation `automation.predictive_controls_reliability_warning_2`.           | None.                |
| 6. Full validation and rollout      | Complete | 657 Python tests pass at 100% statement/branch coverage; repository Ruff and mypy pass; 30 frontend tests and generated-asset build pass; retained 100-sample benchmark passes every gate, with worst reported fast-path p99 approximately 2.99 ms below the 5 ms limit; automation parser/contract and both diff checks pass; final independent conformance review found no code or specification findings. Live status verified separate current and retained projections. | None.                |
