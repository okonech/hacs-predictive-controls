# Pending Release Gates

The exact target migration is implemented through Phase 10 of
`MIGRATION_PLAN.md`. Do not reopen completed model phases without a canonical
requirement discrepancy or a retained public-contract regression.

## Immediate validation

1. Obtain a fresh independent post-implementation conformance verdict against
   `docs/spec`, including counts zero through two, same-zone multiplicity,
   physical-node episodes, fixed-lag assignments, `ArrivalSupported`,
   `ReleaseSafe`, prediction separation, persistence, and `ENT-001` through
   `ENT-010`.
2. Run the full Python suite with 100% branch coverage. Repair only migration
   defects or missing target coverage; do not weaken retained regressions or the
   coverage gate.
3. Run Ruff, strict mypy, and frontend tests.
4. Run the final 10,000-update release benchmark at two occupants
   and refresh `PERFORMANCE_RESULTS.json` from the validated release revision.
5. Record all gate results in `MIGRATION_PLAN.md`; mark migration completion only
   after every Definition of Done item passes.

## External rollout

Run the seven-day target-contract observation in `SHADOW_VALIDATION.md` on the
exact release revision. Keep `active`/`prelight` as the authoritative contract
and verify the `ENT-010` compatibility projections in parallel. Preserve any
incident evidence and restart the window after a remediated criterion breach.

Legacy entity removal and schema-5 reader removal are not part of this release.
Each requires a separately reviewed compatibility-breaking change after its
documented window.
