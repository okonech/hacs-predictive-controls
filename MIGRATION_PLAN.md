# Zone-Belief Model Migration Plan

**Status:** Phases 0-9 implementation and final local stabilization complete;
Phase 10 hardware/production observation remains external
**Authority:** Non-normative execution plan for `SPECIFICATION.md`
**Current production:** Graph-local zone-belief engine, Store schema 7, with a
read-only schema-6 compatibility seed

This plan is an AI-agent handoff. It sequences implementation and temporary
compatibility but does not define product behavior. `SPECIFICATION.md` is the
only source of requirements. If this plan conflicts with it, stop and correct
the plan before editing production code.

## 1. Migration Outcome

The completed migration will:

- replace `ExactInferenceEngine`, global fixed-lag assignment, augmented support
  events, `ArrivalSupported`, `ReleaseSafe`, support certificates, and durable
  ownership with a per-zone probability filter and bounded anonymous traversal
  frontier;
- retain physical-node episode deduplication, aliases, map adjacency, sensor
  behavior profiles, authoritative count, `active`, optional `prelight`, route
  learning where still useful, deterministic persistence, bounded diagnostics,
  and incident regressions;
- use `active` only as Schmitt-trigger hysteresis around filtered zone belief;
- allow a still-open transition node to authorize multiple distinct fresh target
  episodes without treating it as repeated evidence;
- introduce bounded sensor-health degradation so stuck sensors cannot create
  indefinite policy ownership;
- expose accepted fresh evidence while already active through a deduplicated
  `refresh` event; and
- remove the legacy exact engine and its global assignment/support state after
  the target acceptance corpus is executable and green.

## 2. Non-Negotiable Execution Rules

1. Read `SPECIFICATION.md` and this plan before every implementation phase.
2. Work in one phase at a time. A phase is ready to hand off when its code tasks
   and quick focused checks pass; exhaustive repository validation is not an
   intermediate phase gate.
3. Add or update the smallest focused target test for each coherent behavior
   slice. Run it once after the implementation batch, not after every mechanical
   edit. For a production incident, follow
   `.github/skills/predictive-controls-regression-review/SKILL.md`.
4. The target engine is authoritative. The only retained exact-model code is the
   minimal schema-6 read-only migration identifier/decoder required to create a
   finite target seed; it cannot execute legacy inference.
5. Do not mutate `custom_components/predictive_controls/inference/` into the new
   architecture. Build the replacement under
   `custom_components/predictive_controls/zone_model/` so differential replay is
   possible and rollback remains mechanical.
6. Never make room-specific logic, thresholds, or timeouts. Use shared named
   profiles and graph relationships.
7. Never change Home Assistant automation YAML to hide a model defect.
8. Preserve user changes in the worktree. Do not reset, revert, or reformat
   unrelated files.
9. Phases 0-9 are complete. Future changes use focused tests while editing and
   the complete Section 3.2 gate before handoff.
10. A superseded internal test may be changed or removed only in the same commit
    as its target replacement. Record its old test name, replacement test name,
    and governing `REQ-*` IDs in the phase requirement matrix.
11. Public incident facts and expected user outcomes are preserved. Never weaken,
    retime, skip, or delete a public regression merely because it exposes a
    target defect.
12. Benchmark runs are part of final validation or an explicitly performance-
    focused change only. They use 100 events and hard-reject more than 1,000.

## 3. Migration Validation Strategy

### 3.1 Quick checks during implementation

After one coherent phase batch, run one focused test command with coverage
disabled and lint only the changed Python files:

```bash
.venv/bin/python -m pytest -q --no-cov <focused-test-files-or-node-ids>
.venv/bin/python -m ruff check <changed-python-files>
```

Run a targeted mypy command only when the batch changes a typed interface and a
type check is the cheapest relevant discriminator. Run the specific frontend
test only in a phase that changes frontend code. Do not add tests merely to fill
coverage branches during implementation.

### 3.2 Final validation after implementation

After Phases 2-9 are implemented, and before Phase 10 production rollout, run
the exhaustive gates once as a dedicated stabilization pass:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
npm run test:frontend
.venv/bin/python benchmarks/occupancy_performance.py \
  --events 100 \
  --output /tmp/predictive-controls-performance.json
git diff --check
```

`npm test` is not a repository command. Use `npm run test:frontend`.

The final Python suite enforces 100% branch coverage. The benchmark measures the
authoritative target engine only; the removed legacy/shadow engines are not
valid benchmark subjects.

## 4. Target Package and Ownership

Create this package incrementally:

| Module                      | Responsibility                                                                                                           |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `zone_model/types.py`       | Immutable accepted events, episode IDs, beliefs, traversal tokens, contributions, policy decisions, and engine snapshots |
| `zone_model/profiles.py`    | Shared role/profile calibration and map migration from current role/behavior names                                       |
| `zone_model/episodes.py`    | Physical-node alias collapse, flap grouping, stable clear, bounded assertion trust, and health state                     |
| `zone_model/filter.py`      | Per-zone Bayesian/log-odds update and continuous role/context decay                                                      |
| `zone_model/traversal.py`   | Bounded anonymous leading-edge frontier, graph authorization, missed-edge path, and source-free reacquisition            |
| `zone_model/count.py`       | Count validation, `N=0` categorical behavior, and optional bounded positive-count context                                |
| `zone_model/policy.py`      | Activation authorization, Schmitt hysteresis, release dwell, and refresh deduplication                                   |
| `zone_model/prediction.py`  | Optional downstream-only leases and anonymous bounded learning adapter                                                   |
| `zone_model/persistence.py` | Target Store payload, validation, schema-6 compatibility seed, and deterministic restore                                 |
| `zone_model/engine.py`      | Ordered orchestration and immutable result construction                                                                  |

Continue using `OccupancyTracker` as the production-facing integration seam.
Do not move Home Assistant entity or runtime wiring into `zone_model`.

## 5. Concrete Target Semantics

The implementation selected by this plan is a binary hidden-state filter per
zone represented in log odds.

For an observation with profile likelihoods
$P(e\mid O_z=1)$ and $P(e\mid O_z=0)$:

$$
\ell_z^+ = \ell_z^- +
\log\frac{P(e\mid O_z=1)}{P(e\mid O_z=0)}.
$$

Between accepted observations, convert log odds to $q_z$, apply the declared
context decay from `REQ-BELIEF-006`, then convert back. Apply elapsed decay once
from `last_updated_at`; timer cadence must not change the answer.

Use these implementation rules:

1. Fresh local positives update only their zone's observation likelihood.
2. Traversal authorization changes the target transition prior and policy
   authorization; it is not a second copy of the local observation.
3. Stable clear applies one weak absence likelihood and selects the appropriate
   residual decay context.
4. A fresh adjacent target records bounded outward context for a plausible
   source. If that source is already clear, faster departure-conditioned decay
   starts immediately. If it clears later, the retained unexpired outward
   context selects faster decay then.
5. Current trustworthy stay evidence uses the asserted profile. Once its trust
   horizon is crossed, health degradation transitions it toward a finite floor.
6. Transition assertions and tokens may authorize distinct target episodes while
   valid. Deduplicate by target episode ID, not by globally consuming the
   hallway token.
7. Positive counts do not force exactly `N` active zones. The initial target
   implementation uses count only for `N=0`, activation eligibility, boundary
   reacquisition, and diagnostics. Add a nonzero count regularizer later only if
   Phase 6 shadow evidence proves it improves declared metrics without erasing
   strong local evidence.
8. `active` thresholds and dwell consume $q_z$ but never change it.

Do not copy the old `ArrivalSupported` or `ReleaseSafe` calculations behind new
names. Do not retain exact occupancy configurations in target state.

## 6. Test Preservation Strategy

Before implementation, generate `tests/zone_model_requirement_matrix.md` with
one row per current test module:

| Existing test/module            | Disposition                                                       | Target replacement                                        | Requirements                   | Phase  |
| ------------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------ | ------ |
| Public incident/acceptance      | Preserve factual timeline and public outcome                      | Same test or explicitly named target variant              | Relevant `REQ-*`               | 1-7    |
| Episode behavior                | Reuse behavior where specification agrees                         | `test_zone_model_episodes.py`                             | `REQ-EVID-*`                   | 2      |
| Exact state/operator/oracle     | Retire after cutover                                              | Zone-filter normalization/determinism tests               | `REQ-BELIEF-007`, `REQ-PERF-*` | 3, 8   |
| Assignment/support/finalization | Retire after cutover                                              | Traversal, belief-release, and local explainability tests | `REQ-TRAV-*`, `REQ-POLICY-*`   | 4-5, 8 |
| Policy audit                    | Migrate compact fields and bounds                                 | `test_zone_model_diagnostics.py`                          | `REQ-DIAG-*`                   | 5      |
| Persistence                     | Preserve atomicity/restart outcomes                               | `test_zone_model_persistence.py`                          | `REQ-STATE-*`                  | 6      |
| Prediction                      | Preserve separation and useful leases                             | Target prediction tests                                   | `REQ-PRED-*`                   | 9      |
| Entities/runtime/frontend       | Preserve public contract except specified probability diagnostics | Existing tests plus target refresh/health tests           | `REQ-PUBLIC-*`                 | 6-8    |

Rules for the matrix:

- Use `preserve`, `replace`, or `retire`; never use an unreviewed "obsolete".
- Every `replace` row names at least one executable target test.
- Every public incident is `preserve` unless independently retained evidence
  proves the expected outcome was factually wrong.
- Exact internal tests remain in place and passing while the old engine exists.
  Remove them only in Phase 8 after the target equivalents pass.

## 7. Phase 0 - Consolidate Design Authority

**Status:** Completed by the documentation change that created this plan.

Tasks:

1. Create root `SPECIFICATION.md` as the sole normative design source.
2. Replace the completed exact-model migration ledger with this plan.
3. Remove the fragmented `docs/spec/` files and absorbed `async-todo.md`.
4. Update repository instructions, review skill, README, and all live design
   links to point to `SPECIFICATION.md`.
5. Keep changelog references as historical statements only; label any text that
   could be mistaken for current authority.
6. Remove or rewrite the old exact-model shadow checklist. The target rollout
   checklist lives in Phase 10 of this plan until results are recorded.

Gate:

- `SPECIFICATION.md` contains all normative requirements.
- No live repository instruction or documentation calls another file normative,
  canonical, a product requirement, or a specification.
- `rg 'docs/spec|async-todo|ArrivalSupported|ReleaseSafe'` returns only code,
  tests, migration history, or explicitly labeled legacy material.
- Phase 1 owns creation and review of the test requirement matrix; no matrix is
   required to complete this documentation-only phase.
- Every Phase 1 task has an existing repository seam or declared fixture format
   and is unblocked by a missing Phase 0 artifact.

## 8. Phase 1 - Freeze Baseline and Build Requirement Matrix

**Status:** Completed. The requirement matrix, versioned fixture schema, and all
seven mandatory target traces are frozen and schema-validated.

**Goal:** Preserve current correctness and make intentional divergences explicit
before production edits.

Tasks:

1. Run all validation commands and store the 100-event baseline under a new
   ignored or test-fixture-safe artifact. Record failures without changing tests.
2. Create `tests/zone_model_requirement_matrix.md` using Section 6.
3. Enumerate every public acceptance and production incident test. Map each to
   target requirements and classify expected target behavior.
4. Add reviewed target scenario fixtures and expected public timelines for these
   mandatory traces if they are not already represented by a frozen public test:
   - hallway -> room A -> still-open hallway -> room B;
   - direct room arrival followed by quiet stay;
   - two independent occupants using the same open transition node;
   - low occupancy belief releasing `active` while legacy `ReleaseSafe` is
     unavailable;
   - stuck transition through trust-horizon degradation and eventual release;
   - stuck stay evidence through trust-horizon degradation without indefinite
     `active`;
   - manual output off followed by accepted refresh evidence.
5. Store target-only scenarios as immutable structured test data plus expected
   public outcomes; do not add a skipped, xfailed, or deliberately failing test
   to the full suite. The owning implementation phase turns each scenario into
   a focused executable test and runs it after the coherent implementation
   batch. A pre-edit red-test proof is required only for a reported production
   incident, not for every planned migration slice.
6. Store each scenario as `tests/fixtures/zone_model/<scenario>.json` with a
   versioned schema containing: scenario ID, requirement IDs, owning phase,
   topology, physical-node profiles, hardware timing, authoritative count,
   initial states, ordered `event_at` and `received_at` inputs, expected public
   timeline, and expected reason classes. Add a schema-only test that validates
   every fixture while the target engine is absent. The later replay adapter
   feeds these same normalized inputs to legacy and target engines.

Gate:

- Existing suite remains green.
- Every existing test module has a reviewed matrix disposition.
- All seven mandatory target scenarios have immutable inputs, expected public
   timelines, requirement mappings, and named owning phases.
- No target scenario is skipped, xfailed, or collected as a deliberate failure.
- Incident timestamps and public expectations are frozen.

## 9. Phase 2 - Implement Profiles and Physical Episodes

**Status:** Completed. Shared physical profiles, compatibility mapping, episode
aggregation, stable clear, finite trust, and health degradation are implemented.

**Goal:** Produce target episode state without changing public behavior.

Tasks:

1. Add immutable types and strict finite-value/time validation.
2. Implement shared profiles for `transition_fast`, `stay_pir`,
   `stay_presence`, and `entry_boundary`.
3. Add a deterministic compatibility mapping from current map metadata:
   - `transition_gate` or `transient` -> `transition_fast`;
   - sustained room/subzone PIR -> `stay_pir`;
   - sticky or true-presence/mmWave signal -> `stay_presence`;
   - configured boundary node -> `entry_boundary`.
4. Require ambiguous mappings to remain on the legacy engine and emit a shadow
   configuration error. Do not guess from a room name.
5. Implement physical alias aggregation, flap episodes, stable clear, hold,
   assertion trust horizon, and health degradation.
6. Make duration/health advancement idempotent by event time.
7. Reuse current episode fixtures where semantics agree, but do not import exact
   assignment or support types into `zone_model`.

Focused tests:

```bash
.venv/bin/python -m pytest -q \
  tests/test_zone_model_profiles.py \
  tests/test_zone_model_episodes.py
```

Gate:

- `REQ-EVID-*`, `REQ-MAP-*`, and `REQ-PROFILE-*` tests pass.
- All four shared profiles have deterministic mapping and episode fixtures.
- Duplicate, alias, flap, unavailable, stale, stuck, and restart fixtures are
  deterministic.
- The focused profile and episode tests pass with `--no-cov`.

## 10. Phase 3 - Implement Per-Zone Filter

**Status:** Completed. The standalone log-odds filter and calibration harness
pass cadence, restore, retained-trace, coverage, and repository gates.

**Goal:** Compute calibrated, finite, independently explainable zone beliefs.

Tasks:

1. Implement log-odds storage and stable probability conversion.
2. Implement one-time positive/clear Bayes updates using profile likelihoods.
3. Implement exact elapsed-time decay from `last_updated_at` for every context:
   asserted, clear/no-outward-evidence, clear/outward-evidence, transition,
   degraded, and unavailable.
4. Represent current episode assertion separately from stable-clear generation
   and outward-context expiry. A prior episode's outward context cannot affect a
   later reassertion generation.
5. Store contribution records for local update, elapsed decay, and health state.
6. Implement neutral bootstrap priors and deterministic map-compatible restore
   in test fixtures only; production persistence remains unchanged.
7. Add a calibration harness that replays retained traces over a declared grid of
   shared likelihoods, baselines, time constants, thresholds, and dwell values.
8. Score candidates using public outcomes:
   - missed activation count and latency;
   - false release count and darkness duration;
   - unsupported activation count;
   - stale-active duration after confirmed departure;
   - edge chatter; and
   - stuck-sensor recovery time.
9. Weight false releases more heavily than delayed release, but report raw
   metrics as well as the aggregate score. Do not tune on one incident or room.
10. Freeze provisional shared calibration in `zone_model/profiles.py` only after
   every retained trace has a disposition. Record the evidence and candidate
   table in the pull request or phase report, not as a second specification.

Focused tests:

```bash
.venv/bin/python -m pytest -q \
  tests/test_zone_model_filter.py \
  tests/test_zone_model_calibration.py
```

Gate:

- Callback cadence does not change belief.
- Every belief remains finite and in `[0, 1]`.
- Quiet stay, adjacent departure, transition decay, and stuck-sensor cases pass.
- Calibration has no room-specific constants.
- The focused filter and calibration tests pass with `--no-cov`.

## 11. Phase 4 - Implement Traversal Frontier and Count Context

**Status:** Completed. Independent proposal and implementation reviews passed.
The full suite reports 1,106 tests and 100% statement/branch coverage; Ruff,
mypy, frontend, legacy performance, standalone target timing, and diff gates
pass. Production remains on the exact engine with no target-model imports.

**Goal:** Authorize plausible arrivals and leading edges without exact tracks.

Tasks:

1. Create finite traversal tokens from accepted physical episodes.
2. Implement same-zone, adjacent-current, adjacent-recent, boundary, bounded
   missed-edge, and source-free authorization reasons.
3. Deduplicate use by `(token_id, target_episode_id)`. Do not globally consume a
   still-open hallway token after the first target.
4. Record outward context for plausible source zones. Apply it immediately to a
   cleared source or retain it until that source clears or the context expires.
5. Support multiple simultaneous frontiers without assigning identity. Enforce
   only evidence/token bounds, not one path per occupant.
6. Implement count validation and `N=0` categorical clearing in the target engine.
7. For `N=1..2`, permit activation but do not normalize beliefs to exactly N or
   force zone releases. Expose count-versus-active-cluster diagnostics.
8. Implement strict source-free reacquisition using trustworthy local evidence
   and independent-node corroboration or a reviewed profile capability.
9. Add disconnected, cyclic, cross-floor, same-open-gate, missed-edge,
   two-occupant, and same-zone-multiplicity tests.

Focused tests:

```bash
.venv/bin/python -m pytest -q \
  tests/test_zone_model_traversal.py \
  tests/test_zone_model_count.py \
  tests/test_acceptance_scenarios.py -m target_model
```

Gate:

- Hallway -> room A -> still-open hallway -> room B authorizes both fresh room
  episodes without duplicate hallway evidence.
- One open gate supports independent two-occupant fronts.
- Disconnected noise cannot use normal adjacent authorization.
- Count 0 clears all target state; positive count invents no room.
- The focused traversal and count tests pass with `--no-cov`.

## 12. Phase 5 - Implement Hysteretic Policy and Compact Diagnostics

**Status:** Implementation complete. The provisional policy calibration below
is implementation evidence, not normative behavior or production approval.

**Goal:** Convert belief into stable target `active` decisions.

Provisional calibration disposition:

| Candidate | `theta_on` | `theta_off` | Disposition                                                             |
| --------- | ---------: | ----------: | ----------------------------------------------------------------------- |
| A         |       0.65 |        0.35 | Preserves required single-positive acquisition; less conservative tie   |
| B         |       0.70 |        0.30 | Selected provisionally                                                  |
| C         |       0.75 |        0.25 | Reject: transition-fast and stay-PIR single positives remain below 0.75 |

The Phase 5 calibration gate derives first-positive posteriors from the frozen
filter and profile likelihoods: entry-boundary 0.625, transition-fast about
0.714286, stay-PIR about 0.720588, and stay-presence about 0.839662. Candidate B
ties A on required acquisition while using a higher acquisition boundary and a
lower release boundary, reducing false-on and false-off exposure respectively.
This is not a claim of end-to-end fixture or release quality.

Two shared dwell alternatives remain declared for replay:

| Candidate | Entry/transition |   Stay PIR | Stay presence | Disposition                                                                       |
| --------- | ---------------: | ---------: | ------------: | --------------------------------------------------------------------------------- |
| D1        |       15 seconds | 60 seconds |   120 seconds | Selected provisionally to reduce stale-active time while preserving role ordering |
| D2        |       30 seconds | 90 seconds |   180 seconds | Retained comparison candidate                                                     |

No release-quality metric is claimed before target-engine orchestration in
Phase 6 and shadow evidence in Phase 7. Final thresholds and dwells remain
blocked from production until differential replay and shadow calibration satisfy
`REQ-POLICY-006`. Production remains the exact assignment engine and does not
import target policy code during Phase 5.

Tasks:

1. Implement separate shared `theta_on` and `theta_off` with
   `theta_off < theta_on`.
2. Require fresh local episode plus traversal/reacquisition authorization for
   off-to-on acquisition.
3. Implement profile-specific release-confirmation dwell below `theta_off`.
   Cancel the pending release if belief rises above the release boundary.
4. Implement `refresh` once per accepted fresh episode while active.
5. Implement categorical count-0 release with explicit reason.
6. Record one compact decision row containing pre/post belief, active state,
   local and neighboring evidence, traversal reason, profile, health, thresholds,
   dwell, and evidence IDs.
7. Implement fixed time, count, and byte audit bounds with constant-time FIFO
   eviction.
8. Add exact threshold-boundary, dwell cancellation, timer-cadence, manual-off
   refresh, restart, false-off, stale-active, and chatter tests.

Focused tests:

```bash
.venv/bin/python -m pytest -q \
  tests/test_zone_model_policy.py \
  tests/test_zone_model_diagnostics.py \
  tests/test_acceptance_scenarios.py -m target_model
```

Gate:

- Release follows low filtered belief and dwell without `ReleaseSafe`.
- A trustworthy current stay episode protects occupancy only within bounded
  profile semantics.
- No threshold chatter or duplicate refresh occurs.
- One local audit row explains every target edge.
- The focused policy, diagnostics, and calibration tests pass with `--no-cov`.

## 13. Phase 6 - Add Shadow Engine, Persistence, and Frontend Diagnostics

**Status:** Completed as an intermediate migration phase, then removed in Phase
8. No shadow engine, shadow Store writer, or comparator diagnostics remain in
production.

The tasks and evidence below describe that historical intermediate phase; they
are not current production architecture.

**Goal:** Run target inference on production inputs without controlling outputs.

Tasks:

1. Complete `zone_model/engine.py` and immutable result snapshots.
2. Add a shadow adapter at the `OccupancyTracker` observation/count/timer seam.
   Legacy processing completes normally even if shadow processing rejects an
   input; shadow errors are bounded diagnostics.
3. Do not let shadow processing write target public entities, actions, route
   learning, or schema-6 production state.
4. Add a new target Store schema payload in isolated shadow storage. Include the
   fields in `REQ-STATE-*`; validate atomically.
5. Implement schema-6 migration as a finite compatibility seed:
   - import current public `active` as a temporary seed;
   - initialize beliefs from current raw sensor snapshot and neutral priors;
   - create no traversal tokens, movements, refresh events, or predictions; and
   - guarantee the seed expires through ordinary target filter/policy behavior.
6. Add restart tests at assertion, clear, traversal, decay, and release-dwell
   frontiers.
7. Add shadow metrics and panel/API fields for:
   - legacy and target active timelines;
   - target belief and policy reason;
   - missed and unsupported activations;
   - suspected false release/retrigger;
   - stale-active duration;
   - edge latency and chatter;
   - sensor-health warnings; and
   - shadow errors and processing latency.
8. Update frontend tests and versioned panel assets together.

Focused tests:

```bash
.venv/bin/python -m pytest -q --no-cov \
  tests/test_zone_model_engine.py \
   tests/test_zone_model_persistence.py \
   tests/test_zone_model_shadow.py \
   tests/test_runtime.py \
   tests/test_status.py
node --test tests/frontend/panel_registration.test.js
```

If frontend diagnostics change, run only their specific Node test file in this
phase.

Gate:

- Shadow mode cannot alter production outputs or schema-6 state.
- Target state round-trips deterministically and rejects invalid data atomically.
- The focused engine and persistence tests pass with `--no-cov`.
- Target and combined-shadow timing is deferred to final validation.

Completion evidence:

- target state restores deterministically across assertion, clear, traversal
   expiry, elapsed decay, and release-dwell frontiers without synthetic restore
   edges;
- schema-6 migration imports only the finite public-active compatibility seed
   and current raw sensor snapshot;
- bounded API and Activity panel diagnostics expose target belief/reason,
   legacy/target comparisons, mismatch transitions, release/retrigger suspicion,
   stale-active age, edge latency, chatter, sensor health, processing latency, and
   shadow errors;
- the combined focused Python command passed `27` tests with `--no-cov`;
- the focused panel command passed `19` tests, including versioned asset parity;
- Ruff passed for all Phase 6 Python files and targeted mypy passed for `18`
   source files; and
- full coverage, repository-wide gates, benchmarks, and production rollout
   remain deferred as required by Sections 3.2 and 14.

## 14. Phase 7 - Target Cutover Behind a Rollback Switch

**Status:** Completed under the amended direct-cutover decision. The target
runtime became authoritative across all zones; the temporary mode switch was
not retained into the final architecture.

The rollback-switch sequence below is retained as the original migration
proposal and is superseded by the completed direct cutover.

**Goal:** Make target policy authoritative without deleting the comparator.

Preconditions:

- Every Phase 1 target incident and adversarial test passes.
- Differential replay has no unexplained mismatch.
- At least seven consecutive days of shadow data are collected under Phase 10
  metrics, including ordinary two-occupant activity and at least one restart.
- No target false release remains unexplained.
- The user approves provisional profile values and the first cutover zones.

Tasks:

1. Add one config-entry model mode: `legacy`, `shadow`, or `zone_belief`.
2. Keep default `shadow` for existing entries until explicit cutover. New entries
   may default to `zone_belief` only after the rollout gate passes.
3. Route `active`, occupancy probability, problem state, and refresh events from
   the selected authoritative engine.
4. Replace `arrival_supported_probability` and `release_safe_probability` target
   diagnostics with target belief, authorization, and release-dwell diagnostics.
   Retire registry rows only through tested entity migration.
5. Preserve `active`, `prelight`, and `home_active` entity IDs.
6. Update consuming documentation and example automations to optionally use
   refresh. Existing edge-only automations remain valid.
7. Convert conflicting internal policy tests in the requirement matrix to their
   named target replacements in the same change. Keep public incident tests.
8. Maintain a one-reload rollback to `legacy`; rollback restores the last valid
   schema-6 state and emits no synthetic edges.
9. Cut over one low-risk transition/stay path first, then the remaining zones
   only after its observation window passes.

Gate:

- Selected zones publish target results; unselected zones remain legacy without
  mixed-zone feedback.
- Rollback and re-enable are deterministic and edge-safe.
- Focused mode-switch, rollback, and public-edge tests pass with `--no-cov`.
- Production observation gate in Phase 10 passes for the cutover slice.

## 15. Phase 8 - Remove Exact Assignment From Production

**Status:** Completed. Exact inference, fixed-lag association, global support,
legacy policy/route/dwell layers, their production branches, and internal-only
tests are removed. Store schema 7 is target-native; schema 6 is read-only input
to a finite migration seed.

**Goal:** Delete superseded architecture only after target control is proven.

Preconditions:

- All zones have run `zone_belief` for the full Phase 10 validation window.
- No rollback has been required during that window.
- Every test matrix replacement is implemented and passing.

Tasks:

1. Remove production imports and runtime branches for
   `custom_components/predictive_controls/inference/`.
2. Remove exact count-vector, fixed-lag association, factor-chain, support,
   certificate renewal, `ArrivalSupported`, `ReleaseSafe`, exact audit context,
   and their schema writers.
3. Retain a minimal schema-6 read-only compatibility decoder for one released
   migration window if existing installs still require it. It must not be usable
   as a production engine.
4. Remove exact-internal tests only according to the reviewed requirement matrix.
   Verify every removed behavior has a target test or is explicitly prohibited by
   `SPECIFICATION.md`.
5. Remove the legacy/shadow mode switch and make `zone_belief` authoritative.
6. Rewrite benchmark metrics around zone updates, token bounds, audit bytes,
   persistence, startup, and public latency. Preserve the 100/1,000-event limits.
7. Remove dead dependencies, compatibility diagnostics, frontend fields, and
   stale changelog "current behavior" links.

Gate:

- No production import references `inference`, `ArrivalSupported`,
  `ReleaseSafe`, support certificates, exact configurations, or global
  assignments.
- Focused target migration, clean-install, and schema-6-upgrade tests pass with
   `--no-cov`.
- Full coverage and target benchmarks are deferred to final validation.
- Clean-install and schema-6-upgrade tests pass.

## 16. Phase 9 - Reintroduce or Remove Prediction Deliberately

**Status:** Completed. Prediction is retained as bounded 30-second graph-local
leases backed by the existing anonymous Markov counts. It consumes accepted
target traversal only, cancels on newer target-node evidence or count zero,
round-trips atomically, and cannot mutate belief, traversal, count, health, or
normal `active`. The duplicate route and dwell-learning layers were removed.

**Goal:** Keep prediction only if it adds measured value without model feedback.

Tasks:

1. Run prediction tests against accepted target traversal sequences.
2. Preserve graph-adjacent finite `prelight` leases, cancellation, restart, and
   learning only where `REQ-PRED-*` is satisfied.
3. Never train from source-free reacquisition, flaps, unavailable state, or a
   prediction outcome.
4. Compare production value with prediction disabled and enabled.
5. If prediction provides no measured benefit, remove `prelight` and route
   learning through a separately reviewed public-contract change. Do not retain
   complex learning solely for compatibility.

Gate:

- Prediction on/off produces identical normal occupancy and `active` timelines.
- Focused prediction separation, lease, and persistence tests pass with
   `--no-cov`.

## 17. Phase 10 - Sensor Settings and Production Validation

### 17.1 Hardware rollout

Inventory the actual hardware setting and observed clear latency for every
physical node. Change hardware in profile groups, not one room at a time:

1. Set transition PIRs to the shortest reliable reset, initially 5-15 seconds
   when supported.
2. Start stay-room PIRs near 30 seconds. Increase only when labeled target data shows
   repeated false clears without outward evidence.
3. Use short stable absence reporting for true-presence/mmWave sensors while
   retaining a finite software trust horizon.
4. Log device setting, firmware, effective observed clear distribution, and date.
5. After each profile-group hardware change, restart the target observation
   window because episode timing calibration changed.

For rollout, a `reliable reset` means the device can report a new positive after
its declared hold interval without an attributable missed crossing and without a
material increase in no-motion flap episodes. `Stable absence` means the device
reports clear within the profile's measured clearance target and remains clear
through `stable_clear_window` when no new movement occurs. Establish both from
labeled walk/stay traces before selecting the shortest setting; do not infer
them from a vendor setting label alone.

Fast transition clears are useful but not required for correctness. In
hallway -> room A -> hallway still asserted -> room B, the open hallway remains a
bounded traversal context and room B becomes the new leading edge from its own
fresh episode. Room A receives faster departure decay only after its local
evidence clears or degrades; the model does not fabricate a second hallway edge.

### 17.2 Seven-day target-production gate

Collect at least seven consecutive days with unchanged map, profiles, hardware
settings, count source, and code revision. Record:

- every missed credible activation;
- every unsupported activation;
- every false release and release-to-retrigger interval;
- stale-active duration after confirmed departure;
- activation/release latency and chatter;
- stuck, flapping, unavailable, and health-degraded sensors;
- restart, reload, count change, and map compatibility outcomes;
- labeled expected-versus-observed public timeline differences; and
- p50/p95/p99/max target callback latency.

Download diagnostics at the start, after every incident, and at the end. A
reported failure follows the regression-review workflow and restarts the window
after remediation.

### 17.3 Pass criteria

The initial cutover gate requires:

- zero unexplained false releases;
- zero unsupported disconnected activations;
- every retained incident regression passing;
- no missed credible activation left unexplained;
- bounded stale-active duration consistent with the declared profiles;
- no repeated threshold chatter;
- deterministic restart without synthetic edges or refresh;
- no callback above 100 ms;
- no room-specific calibration; and
- every observed mismatch assigned an accepted target reason or fixed defect.

Do not require exact edge parity with legacy. The target intentionally releases
low-belief zones without `ReleaseSafe` and accepts distinct destinations through
one open transition context.

## 18. AI-Agent Phase Report Template

At the end of each phase, leave this report in the pull request or handoff:

```text
Phase:
Commit/diff scope:
Specification requirements:
Focused tests added or changed:
Existing tests replaced (old -> new):
Focused validation result:
Known mismatches or blockers:
Next phase entry criteria satisfied: yes/no
```

An agent stops only for a focused behavioral failure, a specification conflict,
or a real dependency blocker. Coverage gaps, unrelated full-suite failures, and
deferred repository gates are final-stabilization work and do not block the next
implementation phase.

## 19. Completion Criteria

Code migration is complete when:

- `SPECIFICATION.md` is the only normative design source;
- all zones use the target engine and the rollback window has closed;
- the exact assignment/support engine and its production persistence are gone;
- all test matrix replacements are complete and every repository gate passes;
- the retained incident corpus passes at the public contract;
- local acceptance, determinism, coverage, static, frontend, and performance
  gates pass;
- diagnostics explain every target edge locally; and
- release notes describe the behavior and storage/entity migration without
  presenting the plan or historical implementation as product authority.

Operational rollout is complete separately when the Phase 10 seven-day target
production window passes and hardware settings/software profiles are recorded
and calibrated by role. Those observations require the actual Home Assistant
installation and are not represented as completed by repository tests.
