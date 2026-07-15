# Pending Model Work

## Causal movement episodes and evidence-backed release

The canonical specification now prioritizes common false-positive and flapping
faults, permits calibrated false negatives, and treats continuously stuck-on
room sensors as operator-reset faults. Production implementation is pending.

Required implementation sequence:

1. Preserve the 2026-07-15 upstairs-bathroom incident as an exact-timestamp
	public `keep_on -> off` regression. Bathroom motion asserted at
	`2026-07-15T00:51:09.876269-04:00`. The first causal hallway exit evidence at
	`00:51:47.114892` occurred while bathroom motion was still positive, so the
	new sustained-local-evidence rule correctly defers release. Bathroom motion
	cleared at `00:52:01.260790`; the next linked hallway event occurred at
	`00:52:03.685300`. The causal exit had coherent probability
	`0.9992433790137859`, origin decrease `0.738765763110934`, destination
	marginal `0.9200366179579959`, origin marginal `0.08234455772865874`, and
	segment share `0.6062403912838237`. Later linked evidence reduced origin
	occupancy to `0.004307103580756644` after the implementation had discarded
	that strong segment. Expected behavior is to preserve the unresolved causal
	episode while local positive evidence remains, then emit `keep_on -> off`
	only after the clear is valid and linked posterior/count evidence confirms
	final departure. At target cutover, retain the factual legacy assertion and
	add the corresponding `active -> off` public edge.
2. Preserve the 2026-07-14 Alex-office competing-source incident and its
	continued-local-evidence public `keep_on` regression. At target cutover, add
	the corresponding assertion that `active` remains on.
3. Before production behavior edits, prototype the compact indexed occupancy
	array, complete precomputed move operators, exact small-model oracle, and
	fixed-lag assignment graph. Run the reference map at $N=2$ and $N=5$, declare
	numeric `MOVE-020` workload parameters, and approve latency, memory, graph,
	persistence, and startup ceilings. If exact $N=5$ is infeasible, return to the
	specification instead of weakening exactness silently.
4. Replace removable current-state likelihood factors with event-indexed
	physical-node episode emissions and incremental asserted-duration survival
	likelihood. Preserve exact parity with a brute-force small-model oracle.
5. Replace capped directional contexts with exact bounded fixed-lag anonymous
	movement assignments, interval-censored multi-crossing, event-time deadlines,
	a maximum-lateness watermark, and deterministic finalization.
6. Implement `ArrivalSupported` and `ReleaseSafe` as augmented-posterior events.
	Use one activation-risk threshold and one asymmetric release-risk threshold;
	do not preserve independent legacy gate conjunctions as hidden policy paths.
7. Implement exchangeable authoritative count-transition kernels. Only $N=0$
	may categorically release every zone; nonzero count decreases update the exact
	posterior without choosing an occupant or room.
8. Persist the forward posterior, unresolved factor graph, endpoint tokens,
	deadlines/watermark, episode state, support-event marginals, count sequence,
	and policy hysteresis atomically with deterministic restart.
9. Extend configuration, runtime, exact inference, persistence, diagnostics,
	and public controls from the currently implemented zero-through-two range to
	the canonical authoritative range $0 \le N \le 5$. Preserve exact posterior
	semantics and deterministic count reconciliation at every intermediate count.
	Treat $N=2$ as the primary implementation and calibration profile.
10. Rebuild the release benchmark for $N=2$ and $N=5$ using compact indexed
	numeric state
	and precomputed one-occupant move operators. The five-occupant run MUST cover
	all 20,349 configurations and the full fixed-lag workload without probability
	pruning. Record latency percentiles/max, operations, memory, graph size,
	overload, audit, persistence, serialize/restore, and startup measurements.
11. Run every scenario family in `docs/spec/change-governance.md`, full branch
	coverage, static checks, frontend tests, and performance gates before release.
12. Implement `ENT-001` through `ENT-010`: add target `active`, `prelight`,
	`home_active`, and problem entities; optional disabled arrival/probability
	diagnostics; dual-project legacy aliases for at least one full release; migrate
	repository-owned automations; and treat legacy entity removal as a separately
	reviewed breaking change.
