import assert from 'node:assert/strict';
import test from 'node:test';
import { decodeStatus, decodeDiagnostics } from '../../frontend/decoders.ts';
import { projectPaths } from '../../frontend/paths.ts';

for (const count of [null, 3, 7, 100]) {
    test(`unsupported_count preserves backend value ${count} without Boolean coercion`, () => {
        const wire = Object.freeze({ occupancy_diagnostics: Object.freeze({ unsupported_count: count }) });
        assert.equal(decodeStatus(wire).occupancy_diagnostics.unsupported_count, count);
    });
}
test('omitted unsupported_count remains omitted for historical status', () => {
    assert.deepEqual(decodeDiagnostics({}), {});
});
for (const count of [undefined, false, true, -1, 0, 1, 2, 2.5, 3.5, NaN, Infinity, -Infinity, '3', 'false', [], {}]) {
    test(`unsupported_count rejects wrong type/domain ${String(count)}`, () => {
        assert.throws(() => decodeDiagnostics({ unsupported_count: count }), /unsupported_count/);
    });
}
test('supported null retains selections; unsupported metadata hides paths but not policy', () => {
    for (const count of [0, 1, 2]) {
        const status = {
            expected_occupants: count, occupancy_diagnostics: {
                expected_occupants: count, unsupported_count: null, selected_path_version: 2,
                selected_paths: Array(count).fill(null),
                beliefs: { room: 0.8 }, policy: { room: { active: true } },
            }
        };
        const decoded = decodeStatus(status);
        assert.equal(projectPaths({ nodes: {} }, decoded.occupancy_diagnostics, count).state, 'selected');
        for (const unsupported of [3, 7]) {
            const rejected = structuredClone(status);
            rejected.occupancy_diagnostics.unsupported_count = unsupported;
            const result = decodeStatus(rejected);
            assert.equal(projectPaths({ nodes: {} }, result.occupancy_diagnostics, count).state, 'unavailable');
            assert.deepEqual(result.occupancy_diagnostics.policy, decoded.occupancy_diagnostics.policy);
            assert.deepEqual(result.occupancy_diagnostics.beliefs, decoded.occupancy_diagnostics.beliefs);
        }
    }
});