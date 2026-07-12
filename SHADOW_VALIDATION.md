# Seven-Day Shadow Validation

## Status

**Not yet collected.** Automated tests and synthetic benchmarks cannot establish real sensor ordering, entity flapping, Home Assistant event-loop contention, or household movement accuracy. This evidence is an external rollout gate for 0.1.18.

## Preconditions

- Run the exact 0.1.18 release-candidate code and record its commit SHA.
- Keep the map, expected-occupant source, and automation configuration unchanged for the observation window unless a change is logged as a restart of the window.
- Use the canonical public contract: `activation_plausible -> on`, `keep_on -> off`, and optional `prelight_plausible -> prelight`.
- Ensure diagnostics can be downloaded from the Home Assistant integration entry.
- Record a backup of the integration storage before starting.

## Evidence to collect

For at least seven consecutive days, keep a timestamped incident log containing:

- every observed false `keep_on -> off` while a zone remains occupied;
- every unsupported `activation_plausible -> on` without credible local, path, unlocated, corroborating, or recovery evidence;
- every missed activation for a credible arrival;
- every stale `keep_on` that persists after a confirmed departure;
- every incorrect or disruptive prelight;
- Home Assistant restart, integration reload, map change, and occupant-count transition outcomes;
- the downloaded diagnostics payload before and after each incident;
- the relevant automation trace and raw entity history around each incident.

Download diagnostics at the start and end of the window even when no incident occurs. The payload includes posterior/policy evidence, restore status, deterministic work counters, and runtime/event-loop latency.

## Daily checks

1. Confirm `occupancy_diagnostics.joint.pruned_probability` remains `0.0`.
2. Confirm `occupancy_diagnostics.joint.unsupported_count` is null unless the authoritative count is actually above two.
3. Confirm `latency.performance_budget_exceeded_count` has not increased.
4. Confirm `latency.max_ms <= 100` and note any routine p95/p99 above 30 ms.
5. Review policy decisions for unexplained releases or activations.
6. Review Home Assistant logs for rejected restore, invalid map, and performance warnings.

## Pass criteria

The window passes only when all of the following are true:

- no false `keep_on` clear;
- no unsupported activation;
- no occupancy probability pruning;
- no runtime callback above 100 ms;
- restart and reload preserve established `keep_on` without synthetic activation;
- supported count recovery bootstraps current entity states without activation;
- every reported difference has a recorded explanation and disposition.

Preferred latency misses above 30 ms are investigated and reported but do not fail the window when the state update remains exact, deterministic, and below 100 ms.

## Failure handling

A pass criterion breach restarts the seven-day window after remediation. Preserve the diagnostics, automation trace, raw entity history, map/configuration snapshot, integration storage backup, and exact code revision for the failed event. Do not lower a probability, state-space, or latency gate without a benchmark artifact, replay evidence, and specification change.

## Sign-off record

Complete this table after the external run. Do not prefill results.

| Field                       | Result |
| --------------------------- | ------ |
| Commit SHA                  |        |
| Home Assistant version      |        |
| Python/platform             |        |
| Start time                  |        |
| End time                    |        |
| Map fingerprint             |        |
| Expected-occupant source    |        |
| False keep-on clears        |        |
| Unsupported activations     |        |
| Missed credible activations |        |
| Stale keep-on incidents     |        |
| Prelight incidents          |        |
| Restarts/reloads observed   |        |
| Maximum runtime latency     |        |
| Performance budget breaches |        |
| Pruned probability          |        |
| Reviewer                    |        |
| Verdict                     |        |
