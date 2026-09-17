// September17 final-review qualification, not another incident replay.
// DIAG011/PATH-STATE002: backend rejects revoked active endpoints and generation
// contradictions. Source + actual shipped DOM must reject those without hiding
// fresh belief/policy. Original September15/16 incident files stay unchanged.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM, VirtualConsole } from 'jsdom';
import { decodeMap, decodeSelectedPaths, decodeStatus } from '../../frontend/decoders.ts';
import { projectPaths } from '../../frontend/paths.ts';

const at = (second = '00') => `2026-09-17T00:00:${second}+00:00`;
const visit = (node, generation = '1', time = at(), active = false) => ({
    node_id: node, zone: node, episode_id: `${node}:${generation}:${time}`,
    at: time, kind: 'positive', branch_active: active,
});
function path(visits, overrides = {}) {
    return {
        visits, route: visits, branch_routes: [], spatial_at: visits.at(-1).at,
        track_confidence: 'provisional', endpoint_eligible: false, ...overrides
    };
}
function fork() {
    const a = visit('a'); const b = visit('b', '1', at(), true);
    const c = visit('c', '1', at(), true); const x = visit('x', '1', at(), true);
    return [path([a, b, c, x], {
        route: [a, b, x], branch_routes: [[a, b, c]],
        track_confidence: 'confirmed', endpoint_eligible: true
    })];
}
function mapWire() {
    const edges = { a: ['b', 'c'], b: ['a', 'c', 'x'], c: ['a', 'b'], x: ['b', 'next'], next: ['x'], 'node:with:colons': [] };
    return {
        nodes: Object.fromEntries(Object.entries(edges).map(([id, adjacent]) =>
            [id, { zone: id, label: id, adjacent }]))
    };
}
function status(paths, active = true, belief = 0.8) {
    const occurrences = paths.filter(Boolean).flatMap(p => [...p.visits, ...p.route, ...p.branch_routes.flat()]);
    const current = [...new Map(occurrences.map(v => [v.node_id, v])).values()];
    return {
        expected_occupants: paths.length, occupancy_diagnostics: {
            model: 'zone_belief', expected_occupants: paths.length, unsupported_count: null,
            selected_path_version: 2, selected_paths: paths,
            beliefs: { x: belief }, policy: { x: { active } },
            episodes: current.map(v => ({ node_id: v.node_id, zone: v.zone, episode_id: v.episode_id, status: 'asserted' })),
            path_health: current.map(v => ({ node_id: v.node_id, zone: v.zone, phase: 'on' })),
            traversal_frontier: [{ token_id: 'legacy', zone: 'a' }],
            authorizations: [{ authorized: true, source_token_ids: ['legacy'], target_zone: 'b' }],
        }
    };
}
function freeze(value) {
    if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
    return value;
}
function reversal(node = 'a', older = '1', newer = '2', bridge = false) {
    const old = visit(node, older); const next = visit(node, newer);
    const middle = bridge ? [{ ...visit('b'), episode_id: 'opaque-bridge' }] : [];
    return [[path([old, ...middle, next])], [path([next, ...middle, old])]];
}
const defects = [
    ['revoked endpoint retains active branch', () => {
        const good = fork(); const bad = structuredClone(good); bad[0].endpoint_eligible = false;
        return [good, bad];
    }, /Revoked endpoint/],
    ['same-node equal-time generation reversal', () => reversal(), /generation|cyclic/],
    ['numeric nine then ten', () => reversal('a', '9', '10'), /generation|cyclic/],
    ['generations beyond Number precision', () => reversal('a', '9007199254740992', '9007199254740993'), /generation|cyclic/],
    ['exact colon-containing node prefix', () => reversal('node:with:colons'), /generation|cyclic/],
    ['opaque intermediate participates in generation cycle', () => reversal('a', '1', '2', true), /generation|cyclic/],
    ['history-only generation reversal', () => {
        const old = visit('a'); const next = visit('a', '2'); const x = visit('x');
        return [[path([old, next, x], { route: [x] })], [path([next, old, x], { route: [x] })]];
    }, /generation|cyclic/],
    ['main-only historical generation reversal', () => {
        const old = visit('a'); const next = visit('a', '2'); const x = visit('x');
        return [[path([next, x], { route: [old, next, x] })], [path([next, x], { route: [next, old, x] })]];
    }, /generation|cyclic/],
    ['witness-only prefix generation reversal', () => {
        const old = visit('a'); const next = visit('a', '2');
        const c = visit('c', '1', at(), true); const x = visit('x');
        return [[path([c, x], { route: [x], branch_routes: [[old, next, c]] })],
        [path([c, x], { route: [x], branch_routes: [[next, old, c]] })]];
    }, /generation|cyclic/],
    ['cross-slot equal-time combined cycle', () => {
        const a1 = visit('a'); const a2 = visit('a', '2'); const b1 = visit('b'); const b2 = visit('b', '2');
        return [[path([a1, b1]), path([b2, a2])], [path([a2, b1]), path([b2, a1])]];
    }, /generation|cyclic/],
    ['cross-slot generation time reversal', () => [
        [path([visit('a', '1', at('00'))]), path([visit('a', '2', at('01'))])],
        [path([visit('a', '1', at('01'))]), path([visit('a', '2', at('00'))])],
    ], /generation/],
    ['microsecond generation time reversal', () => [
        [path([visit('a', '1', at('00.000001'))]), path([visit('a', '2', at('00.000002'))])],
        [path([visit('a', '1', at('00.000002'))]), path([visit('a', '2', at('00.000001'))])],
    ], /generation/],
    ['one generation claims distinct occurrences', () => [
        [path([visit('a', '1', at('00'))]), path([visit('a', '2', at('01'))])],
        [path([visit('a', '1', at('00'))]), path([visit('a', '1', at('01'))])],
    ], /generation/],
];

for (const [name, specimen, message] of defects) {
    test(`source rejects ${name} after valid control`, () => {
        const [good, bad] = specimen(); const original = structuredClone(bad);
        assert.deepEqual(decodeSelectedPaths(freeze(good)), good);
        assert.throws(() => decodeSelectedPaths(freeze(bad)), message);
        const wire = status(bad, false, 0.37); const decoded = decodeStatus(wire);
        assert.match(decoded.occupancy_diagnostics.selected_paths_error, message);
        assert.equal(Object.hasOwn(decoded.occupancy_diagnostics, 'selected_paths'), false);
        assert.deepEqual(decoded.occupancy_diagnostics.beliefs, { x: 0.37 });
        assert.deepEqual(decoded.occupancy_diagnostics.policy, { x: { active: false } });
        const projection = projectPaths(decodeMap(mapWire()), decoded.occupancy_diagnostics, wire.expected_occupants);
        assert.equal(projection.state, 'unavailable');
        assert.deepEqual(projection.slots, []); assert.deepEqual(projection.segments, []);
        assert.deepEqual(projection.frontierTokens, []); assert.deepEqual(projection.authorizedPaths, []);
        assert.deepEqual(bad, original);
    });
}

test('source preserves the other three endpoint Boolean combinations without repair', () => {
    for (const [eligible, active] of [[true, true], [true, false], [false, false]]) {
        const p = path([visit('a'), visit('b', '1', at(), active)], { endpoint_eligible: eligible });
        assert.deepEqual(decodeSelectedPaths([p]), [p]);
    }
});
test('source retains opaque IDs and suffix-independent chronology compatibility', () => {
    for (const [first, second] of [
        ['a:2', 'a:1'], ['opaque-z', 'opaque-a'], ['another:2:time', 'another:1:time'],
        ['a:02:time', 'a:01:time'], ['a:2junk:time', 'a:1junk:time'],
    ]) {
        const p = path([{ ...visit('a'), episode_id: first }, { ...visit('a'), episode_id: second }]);
        assert.deepEqual(decodeSelectedPaths([p]), [p]);
    }
    const p = path([visit('a', '1', at('01')), visit('a', '2', at('02'))]);
    p.visits.forEach(v => { v.at = at(); }); p.spatial_at = at();
    assert.deepEqual(decodeSelectedPaths([p]), [p], 'no new suffix/at equality contract');
});
test('source preserves observed equal-time forks, reverse lexical cross-node inputs and slot order', () => {
    const paths = fork(); const projection = projectPaths(decodeMap(mapWire()), decodeStatus(status(paths)).occupancy_diagnostics, 1);
    assert.equal(projection.state, 'selected');
    assert.deepEqual(projection.segments.map(s => [s.from, s.to]), [['a', 'b'], ['b', 'x'], ['b', 'c']]);
    assert.ok(!projection.segments.some(s => s.from === 'c' && s.to === 'x'));
    assert.deepEqual(decodeSelectedPaths([path([visit('x'), visit('b'), visit('a')])])[0].visits.map(v => v.node_id), ['x', 'b', 'a']);
    const [good] = defects.find(([name]) => name === 'cross-slot equal-time combined cycle')[1]();
    assert.deepEqual(decodeSelectedPaths([...good].reverse()), [...good].reverse());
});
test('source rejects wrong types and raw overbounds before any nested generation access', () => {
    for (const value of [undefined, null, 0, 1, 'false', [], {}]) {
        const p = fork()[0]; p.endpoint_eligible = value;
        assert.throws(() => decodeSelectedPaths([p]), /Boolean/);
        const q = path([visit('a')]); q.visits[0].episode_id = value;
        if (typeof value === 'string') assert.deepEqual(decodeSelectedPaths([q]), [q]);
        else assert.throws(() => decodeSelectedPaths([q]), /string/);
    }
    const poison = { get episode_id() { assert.fail('generation decoded before all raw bounds'); } };
    for (const mutate of [p => p.visits = Array(5).fill(poison), p => p.route = [],
    p => p.branch_routes = Array(4).fill([poison]), p => p.branch_routes = [Array(5).fill(poison)]]) {
        const first = path([poison]); const second = fork()[0]; mutate(second);
        assert.throws(() => decodeSelectedPaths([first, second]), /bounded selected/);
    }
});

const bundle = readFileSync(new URL('../../custom_components/predictive_controls/frontend/panel-v0.2.6.js', import.meta.url), 'utf8');
async function browser(t, initial = status(fork()), map = mapWire()) {
    const errors = []; const virtualConsole = new VirtualConsole();
    virtualConsole.on('jsdomError', error => errors.push(error.message));
    const dom = new JSDOM('<!doctype html><body></body>', { runScripts: 'dangerously', url: 'https://offline.invalid/', virtualConsole });
    t.after(() => { dom.window.close(); assert.deepEqual(errors, []); });
    dom.window.eval(bundle);
    const panel = dom.window.document.createElement('predictive-controls-panel'); dom.window.document.body.append(panel);
    let current = initial; let fail = false;
    panel._hass = {
        async callWS(message) {
            if (message.type === 'predictive_controls/config') return { entry_id: 'wire-boundaries', map, map_yaml: 'nodes: {}', expected_occupants: initial.expected_occupants, transition_window_seconds: 30 };
            if (message.type === 'predictive_controls/entities') return { entities: [] };
            assert.equal(message.type, 'predictive_controls/status', 'no non-read operations');
            if (fail) throw new Error('offline transport'); return current;
        }
    };
    await panel.loadData();
    return {
        panel, async update(value) { current = value; await panel.refreshStatus(); },
        async transport(value) { fail = value; await panel.refreshStatus(); }
    };
}
function independentCards(panel, active, belief) {
    assert.equal(panel.querySelector('[data-status-banner]').textContent, '');
    assert.equal(panel.querySelector('[data-zone="x"] .zone-belief-state strong').textContent, active ? 'Active' : 'Inactive');
    assert.equal(panel.querySelector('[data-zone="x"] .zone-card-head span').textContent, `${Math.round(belief * 100)}% belief`);
}
function unavailablePanel(panel) {
    assert.match(panel.querySelector('.selected-paths h3').textContent, /Selected paths unavailable/);
    assert.equal(panel.querySelectorAll('.path-slot,.selected-path-edge,.authorized-path,.has-frontier').length, 0);
    independentCards(panel, false, 0.37);
}
for (const [name, specimen] of defects) {
    test(`shipped rejects ${name}, publishes fresh independent cards and recovers`, async t => {
        const [good, bad] = specimen();
        // Some source-only history examples lack configured a->x geometry;
        // supply that real reciprocal edge explicitly for these DOM controls.
        const map = mapWire(); map.nodes.a.adjacent.push('x'); map.nodes.x.adjacent.push('a');
        const h = await browser(t, status(good), map); independentCards(h.panel, true, 0.8);
        assert.equal(h.panel.querySelectorAll('.path-slot').length, good.length);
        assert.doesNotMatch(h.panel.querySelector('.selected-paths').textContent, /unavailable|Legacy/);
        const selectedBefore = h.panel.querySelector('.selected-paths').innerHTML;
        const edgesBefore = [...h.panel.querySelectorAll('.selected-path-edge')].map(el => el.dataset.path);
        const next = freeze(status(bad, false, 0.37)); const original = structuredClone(next);
        await h.update(next); unavailablePanel(h.panel); assert.deepEqual(next, original);
        await h.update(status(good)); independentCards(h.panel, true, 0.8);
        assert.equal(h.panel.querySelectorAll('.path-slot').length, good.length);
        assert.equal(h.panel.querySelector('.selected-paths').innerHTML, selectedBefore);
        assert.deepEqual([...h.panel.querySelectorAll('.selected-path-edge')].map(el => el.dataset.path), edgesBefore);
    });
}
test('shipped valid fork keeps one slot/separate observed prefix; transport is distinct from selection failure', async t => {
    const h = await browser(t); const { panel } = h;
    assert.equal(panel.querySelectorAll('.path-slot').length, 1);
    assert.deepEqual([...panel.querySelectorAll('.selected-path-edge')].map(el => el.dataset.path), ['a->b', 'b->x', 'b->c']);
    assert.equal(panel.querySelector('.path-overlap h4').textContent, 'Observed overlap 1');
    const before = panel.querySelector('.occupancy-graph').innerHTML;
    await h.transport(true); assert.match(panel.querySelector('[data-status-banner]').textContent, /Stale/);
    assert.equal(panel.querySelector('.occupancy-graph').innerHTML, before);
    await h.transport(false); independentCards(panel, true, 0.8);
    for (const paths of [[], [null], [null, null]]) {
        await h.update(status(paths)); assert.equal(panel.querySelectorAll('.path-slot').length, paths.length);
        assert.equal(panel.querySelectorAll('.selected-path-edge,.authorized-path,.has-frontier').length, 0);
    }
    await h.update(status(fork())); assert.equal(panel.querySelectorAll('.path-overlap').length, 1);
});
test('shipped mismatched current geometry rejects only selection, never hides beliefs or borrows legacy paths', async t => {
    const wire = status(fork(), false, 0.37); const original = structuredClone(wire);
    const decoded = decodeStatus(wire); assert.equal(decoded.occupancy_diagnostics.selected_paths_error, undefined);
    const map = mapWire(); map.nodes.b.adjacent = map.nodes.b.adjacent.filter(id => id !== 'c');
    const projected = projectPaths(decodeMap(map), decoded.occupancy_diagnostics, 1);
    assert.match(projected.message, /map geometry or membership/);
    const { panel } = await browser(t, wire, map); unavailablePanel(panel); assert.deepEqual(wire, original);
});

test('shipped wrong types, bounds and timestamps reject after valid controls', async t => {
    const h = await browser(t);
    for (const corrupt of [
        p => { p.endpoint_eligible = 'false'; },
        p => { p.visits[0].branch_active = 1; },
        p => { p.visits = Array(5).fill(p.visits[0]); },
        p => { p.branch_routes = Array(4).fill(p.branch_routes[0]); },
        p => { p.route[0].at = '2026-02-30T00:00:00Z'; },
        p => { p.route[0].at = at('00.000002'); },
    ]) {
        await h.update(status(fork())); assert.equal(h.panel.querySelectorAll('.path-slot').length, 1);
        const next = status(fork(), false, 0.37); corrupt(next.occupancy_diagnostics.selected_paths[0]);
        await h.update(next); unavailablePanel(h.panel);
    }
});

test('shipped retains all valid endpoint flags and opaque/suffix identity compatibility', async t => {
    const h = await browser(t);
    for (const [eligible, active] of [[true, true], [true, false], [false, false]]) {
        const p = path([visit('a'), visit('b', '1', at(), active)], { endpoint_eligible: eligible });
        await h.update(status([p])); independentCards(h.panel, true, 0.8);
        assert.equal(h.panel.querySelectorAll('.path-slot').length, 1);
        assert.equal(h.panel.querySelector('[data-zone="b"]').classList.contains('path-role-presence'), active);
    }
    for (const paths of [
        [path([{ ...visit('a'), episode_id: 'opaque-first' }, { ...visit('b'), episode_id: 'b:1' }])],
        [path([visit('x'), visit('b'), visit('a')])],
    ]) {
        await h.update(status(paths)); independentCards(h.panel, true, 0.8);
        assert.equal(h.panel.querySelectorAll('.path-slot').length, 1);
        assert.doesNotMatch(h.panel.querySelector('.selected-paths').textContent, /unavailable|Legacy/);
    }
    const p = path([visit('a', '1', at('01')), visit('a', '2', at('02'))]);
    p.visits.forEach(v => { v.at = at(); }); p.spatial_at = at();
    await h.update(status([p])); assert.equal(h.panel.querySelectorAll('.path-slot').length, 1);
    independentCards(h.panel, true, 0.8);
});
