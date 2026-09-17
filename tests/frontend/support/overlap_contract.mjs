// stdin-only real-runtime status + SAME production-parsed YAML map consumer.
// Never build/write shipped assets, synthesize a map, patch positive payloads,
// connect to HA, or alter the borrowed status_contract/DOM harnesses.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { JSDOM, VirtualConsole } from 'jsdom';

const root = new URL('../../../', import.meta.url);
const compiled = await build({
    stdin: {
        contents: "export { decodeMap, decodeStatus } from './frontend/decoders.ts'; export { projectPaths } from './frontend/paths.ts';",
        resolveDir: fileURLToPath(root), sourcefile: 'overlap-contract-entry.ts',
    },
    bundle: true, write: false, platform: 'node', format: 'esm', target: 'node22',
});
const { decodeMap, decodeStatus, projectPaths } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].contents).toString('base64')}`);
const artifactPaths = [
    'frontend/decoders.ts', 'frontend/paths.ts',
    'custom_components/predictive_controls/frontend/panel-v0.2.6.js',
];
const artifacts = Object.fromEntries(artifactPaths.map(path => [path, createHash('sha256').update(readFileSync(new URL(path, root))).digest('hex')]));
const bundle = readFileSync(new URL(artifactPaths[2], root), 'utf8');
function freeze(value) {
    if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
    return value;
}
const input = freeze(JSON.parse(readFileSync(0, 'utf8')));
const before = structuredClone(input);
assert.ok(input.frames.length > 0);
const map = decodeMap(input.map);
const zoneFor = id => map.nodes[id].zone || id;
const ids = elements => [...elements].map(el => el.dataset.nodeId);
const errors = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', error => errors.push(error.message));
const dom = new JSDOM('<!doctype html><body></body>', {
    runScripts: 'dangerously', url: 'https://offline.invalid/', virtualConsole,
});
let current = input.frames[0].status;
let transportFailure = false;
let corruptionChecks = 0;
let transportRecoveries = 0;
try {
    const { window } = dom;
    window.eval(bundle);
    const panel = window.document.createElement('predictive-controls-panel');
    window.document.body.append(panel);
    panel._hass = {
        async callWS(message) {
            switch (message.type) {
                case 'predictive_controls/config': return {
                    entry_id: 'offline-overlap', map: input.map, map_yaml: input.map_yaml,
                    expected_occupants: input.frames[0].status.expected_occupants,
                    transition_window_seconds: 30,
                };
                case 'predictive_controls/entities': return { entities: [] };
                case 'predictive_controls/status':
                    if (transportFailure) throw new Error('offline test transport');
                    return current;
                default: throw new Error(`Unexpected/non-read operation: ${message.type}`);
            }
        }
    };
    const banner = () => panel.querySelector('[data-status-banner]').textContent;
    function checkPolicy(status) {
        for (const zone of Object.keys(status.zone_states)) {
            const card = [...panel.querySelectorAll('.zone-card')].find(el => el.dataset.zone === zone);
            assert.ok(card, `Missing actual-map zone ${zone}`);
            assert.equal(card.querySelector('.zone-belief-state strong').textContent, status.occupancy_diagnostics.policy[zone].active ? 'Active' : 'Inactive');
            assert.equal(card.querySelector('.zone-card-head span').textContent, `${Math.round(status.occupancy_diagnostics.beliefs[zone] * 100)}% belief`);
        }
    }
    function checkFrame(frame) {
        const { status, routes, overlaps, name } = frame;
        const decoded = decodeStatus(status);
        const diagnostics = decoded.occupancy_diagnostics;
        assert.equal(diagnostics.selected_paths_error, undefined, name);
        assert.equal(diagnostics.selected_path_version, 2, name);
        assert.deepEqual(diagnostics.selected_paths, status.occupancy_diagnostics.selected_paths, 'Source decoder preserves real occurrence/provenance records');
        const projection = projectPaths(map, diagnostics, decoded.expected_occupants);
        assert.equal(projection.state, 'selected', `${name}: ${projection.message}`);
        assert.deepEqual(projection.frontierTokens, []);
        assert.deepEqual(projection.authorizedPaths, []);
        assert.equal(projection.slots.length, status.expected_occupants, name);
        assert.deepEqual(projection.slots.map(s => s.path ? s.occurrences.map(o => o.visit.node_id) : null), routes, name);
        assert.deepEqual(projection.slots.map(s => s.overlaps.map(b => b.map(o => o.visit.node_id))), overlaps, name);
        assert.equal(banner(), '', name);
        assert.doesNotMatch(panel.querySelector('.selected-paths').textContent, /Legacy path display|Selected paths unavailable/);
        const slots = [...panel.querySelectorAll('.path-slot')];
        assert.equal(slots.length, status.expected_occupants, name);
        assert.equal(slots.filter(s => s.hasAttribute('data-slot')).length, routes.filter(Boolean).length, 'Overlap never manufactures a located slot');
        for (const [i, slot] of slots.entries()) {
            const route = routes[i];
            if (route === null) { assert.match(slot.textContent, /Unlocated/); continue; }
            assert.equal(slot.dataset.slot, String(i + 1));
            assert.deepEqual(ids(slot.querySelectorAll('.path-main-route .path-chip')), route, name);
            const branches = [...slot.querySelectorAll('.path-overlap')];
            assert.equal(branches.length, overlaps[i].length, name);
            for (const [j, branch] of branches.entries()) {
                assert.equal(branch.querySelector('h4').textContent, `Observed overlap ${j + 1}`);
                assert.equal(branch.getAttribute('aria-label'), `Observed overlap ${j + 1}`);
                assert.deepEqual(ids(branch.querySelectorAll('.path-chip')), overlaps[i][j], name);
                assert.match(branch.textContent, /not a separate occupant/);
            }
        }
        for (const id of Object.keys(map.nodes)) {
            const role = frame.presence.includes(id) ? 'presence' : frame.history.includes(id) ? 'history' : frame.candidates.includes(id) ? 'candidate' : 'neutral';
            assert.equal(projection.nodes.get(id).role, role, `${name}: source role ${id}`);
            const card = panel.querySelector(`[data-zone="${zoneFor(id)}"]`);
            for (const candidate of ['presence', 'history', 'candidate']) {
                assert.equal(card.classList.contains(`path-role-${candidate}`), role === candidate, `${name}: shipped role ${id}/${candidate}`);
            }
            for (const chip of panel.querySelectorAll(`.path-chip[data-node-id="${id}"]`)) {
                assert.equal(chip.querySelector('strong').textContent, map.nodes[id].label);
                assert.equal(chip.classList.contains('path-role-presence'), role === 'presence', `${name}: chip ${id}`);
                if (role !== 'presence') assert.match(chip.textContent, /Retained history/);
            }
        }
        const edges = routes.flatMap((route, i) => {
            const seen = new Set();
            return [route || [], ...overlaps[i]].flatMap(branch => branch.slice(1).flatMap((to, index) => {
                const from = branch[index]; const key = `${from}->${to}`;
                assert.ok(map.nodes[from].adjacent.includes(to), `${name}: nonedge in expected witness ${key}`);
                if (seen.has(key)) return []; seen.add(key); return [key];
            }));
        });
        assert.deepEqual(projection.segments.map(s => `${s.from}->${s.to}`), edges, name);
        assert.deepEqual([...panel.querySelectorAll('.selected-path-edge')].map(el => el.dataset.path), edges, name);
        assert.ok(!edges.includes('c->x') && !edges.includes('x->c'), 'Chronology is not geometry');
        assert.equal(panel.querySelectorAll('.authorized-path,.has-frontier').length, 0, 'Never draw a legacy fallback');
        checkPolicy(status);
    }
    await panel.loadData();
    for (const frame of input.frames) {
        current = frame.status;
        await panel.refreshStatus();
        checkFrame(frame);
        if (!frame.corrupt) continue;
        assert.ok(frame.status.occupancy_diagnostics.selected_paths.some(p => p?.branch_routes.length), 'Inverse must start with real nonempty overlap');
        // Deliberate corruption is confined to copies at the consumer boundary;
        // these are NOT claimed to be output of the valid runtime producer.
        for (const [message, corrupt] of [
            [/selected_path_version/, s => { s.occupancy_diagnostics.selected_path_version = 1; }],
            [/overlap routes/, s => { delete s.occupancy_diagnostics.selected_paths.find(p => p).branch_routes; }],
        ]) {
            current = structuredClone(frame.status); corrupt(current);
            const decoded = decodeStatus(current);
            assert.match(decoded.occupancy_diagnostics.selected_paths_error, message);
            const projection = projectPaths(map, decoded.occupancy_diagnostics, decoded.expected_occupants);
            assert.equal(projection.state, 'unavailable');
            assert.deepEqual(projection.slots, []); assert.deepEqual(projection.segments, []);
            assert.deepEqual(projection.frontierTokens, []); assert.deepEqual(projection.authorizedPaths, []);
            await panel.refreshStatus();
            assert.match(panel.querySelector('.selected-paths h3').textContent, /Selected paths unavailable/);
            assert.equal(panel.querySelectorAll('.path-slot,.selected-path-edge,.authorized-path,.has-frontier').length, 0);
            assert.equal(banner(), '', 'Bad selection must not hide independent status');
            checkPolicy(frame.status);
            current = frame.status; await panel.refreshStatus(); checkFrame(frame);
            corruptionChecks++;
        }
        const oldGraph = panel.querySelector('.occupancy-graph').innerHTML;
        transportFailure = true; await panel.refreshStatus();
        assert.match(banner(), /Stale/);
        assert.equal(panel.querySelector('.occupancy-graph').innerHTML, oldGraph);
        transportFailure = false; await panel.refreshStatus(); checkFrame(frame);
        transportRecoveries++;
    }
    assert.deepEqual(input, before, 'Source/shipped consumers cannot mutate producer map/status/oracles');
    assert.deepEqual(errors, []);
} finally {
    dom.window.close();
}
console.log(JSON.stringify({
    validated_frames: input.frames.length, corruption_checks: corruptionChecks,
    transport_recoveries: transportRecoveries, artifacts,
}));
