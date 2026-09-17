// Synthetic REQ-PATH-007/008, PATH-STATE-002 and DIAG-011 qualification.
// Not a production replay or proof of the backend consumed-origin ledger. The
// parent owns real producer/actual-map coverage and the frozen September cases.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM, VirtualConsole } from 'jsdom';
import { decodeDiagnostics, decodeMap, decodeSelectedPaths, decodeStatus } from '../../frontend/decoders.ts';
import { projectPaths } from '../../frontend/paths.ts';

const at = (second, fraction = '') => `2026-09-16T20:00:${String(second).padStart(2, '0')}${fraction}+00:00`;
const visit = (node, second, overrides = {}) => ({ node_id: node, zone: node, episode_id: `${node}:1:${at(second)}`, at: at(second), kind: 'positive', branch_active: true, ...overrides });
function specimen() {
    const r = visit('r', 0, { branch_active: false, kind: 'interaction' });
    const a = visit('a', 1); const b = visit('b', 2, { kind: 'correlated_positive' });
    const c = visit('c', 3); const x = visit('x', 4);
    return {
        visits: [a, b, c, x], route: [r, x], spatial_at: x.at,
        branch_routes: [[r, a], [r, b], [r, c]],
        track_confidence: 'confirmed', endpoint_eligible: true,
        endpoint: x, updated_at: x.at,
        covered_node_ids: ['a', 'b', 'c', 'x'], covered_zones: ['a', 'b', 'c', 'x'],
        eligible_node_ids: ['a', 'b', 'c', 'x'],
    };
}
function mapWire() {
    const edges = { r: ['a', 'b', 'c', 'x', 'r_next'], a: ['a_next'], b: ['b_next'], c: ['c_next'], x: ['x_next'], r_next: [], a_next: ['deep'], b_next: ['deep'], c_next: ['deep'], x_next: ['deep'], deep: [], inbound: ['a'], raw: ['raw_next'], raw_next: [] };
    return { nodes: Object.fromEntries(Object.entries(edges).map(([id, adjacent]) => [id, { zone: id, adjacent, label: id }])) };
}
function diagnostics(path = specimen()) {
    const unique = [...new Map([...path.visits, ...path.route, ...path.branch_routes.flat()].map(v => [v.node_id, v])).values()];
    return {
        model: 'zone_belief', selected_path_version: 2, selected_paths: [path], expected_occupants: 1, unsupported_count: null,
        episodes: unique.map(v => ({ node_id: v.node_id, zone: v.zone, episode_id: v.episode_id, status: 'asserted' })),
        path_health: unique.map(v => ({ node_id: v.node_id, zone: v.zone, phase: 'on' })),
        beliefs: { x: 0.8, r: 0.9 }, policy: { x: { active: true }, r: { active: false } },
        traversal_frontier: [{ token_id: 'legacy', zone: 'raw' }],
        authorizations: [{ authorized: true, source_token_ids: ['legacy'], target_zone: 'raw_next' }],
    };
}
function project(d = diagnostics(), map = mapWire()) { return projectPaths(decodeMap(map), decodeDiagnostics(d), d.expected_occupants); }
function role(result, id, expected, slots = [1]) { assert.deepEqual(result.nodes.get(id), { role: expected, slots }); }
function freeze(value) {
    if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
    return value;
}
function unavailable(d, map = mapWire()) {
    const decoded = decodeDiagnostics(d);
    const result = projectPaths(decodeMap(map), decoded, d.expected_occupants);
    assert.equal(result.state, 'unavailable');
    assert.deepEqual(result.slots, []); assert.deepEqual(result.segments, []);
    assert.deepEqual(result.frontierTokens, []); assert.deepEqual(result.authorizedPaths, []);
    for (const membership of result.nodes.values()) assert.deepEqual(membership, { role: 'neutral', slots: [] });
    assert.deepEqual(decoded.beliefs, d.beliefs); assert.deepEqual(decoded.policy, d.policy);
}

test('three witnessed overlaps remain one slot, with equally strong main/tip presence and no prefix candidates', () => {
    const wire = freeze(diagnostics()); const before = structuredClone(wire);
    const decoded = decodeDiagnostics(wire);
    assert.deepEqual(decoded.selected_paths, wire.selected_paths, 'keep all derived fields and exact occurrence copies');
    const result = project(wire);
    assert.equal(result.state, 'selected'); assert.equal(result.slots.length, 1);
    assert.deepEqual(result.slots[0].occurrences.map(o => [o.visit.node_id, o.role]), [['r', 'history'], ['x', 'presence']]);
    assert.deepEqual(result.slots[0].overlaps.map(route => route.map(o => [o.visit.node_id, o.role])), [
        [['r', 'history'], ['a', 'presence']], [['r', 'history'], ['b', 'presence']], [['r', 'history'], ['c', 'presence']],
    ]);
    for (const id of ['a', 'b', 'c', 'x']) role(result, id, 'presence');
    role(result, 'r', 'history');
    for (const id of ['a_next', 'b_next', 'c_next', 'x_next']) role(result, id, 'candidate');
    for (const id of ['r_next', 'deep', 'inbound', 'raw', 'raw_next']) role(result, id, 'neutral', []);
    assert.deepEqual(result.segments.map(s => [s.from, s.to]), [['r', 'x'], ['r', 'a'], ['r', 'b'], ['r', 'c']]);
    assert.deepEqual(wire, before);
});

test('prefix outside main and retained visits stays history even with matching aggregate ON', () => {
    const p = specimen(); const root = p.route[0];
    p.route = [p.endpoint];
    assert.ok(!p.visits.includes(root));
    const result = project(diagnostics(p));
    assert.equal(result.state, 'selected'); role(result, 'r', 'history'); role(result, 'r_next', 'neutral', []);
    assert.ok(result.slots[0].overlaps.every(route => route[0].role === 'history'));
});

for (const [phase, status, generation] of [
    ['off', 'clear', 'same'], ['unknown', 'unavailable', 'same'],
    ['clearing', 'clearing', 'same'], ['on', 'clearing', 'same'], ['on', 'asserted', 'new'],
]) {
    test(`overlap tip ${phase}/${status}/${generation} cannot borrow presence or candidates`, () => {
        const d = diagnostics(); d.path_health.find(v => v.node_id === 'b').phase = phase;
        const episode = d.episodes.find(v => v.node_id === 'b'); episode.status = status;
        if (generation === 'new') episode.episode_id = 'b:2:new';
        const result = project(d);
        assert.equal(result.state, 'selected'); role(result, 'b', 'history'); role(result, 'b_next', 'neutral', []);
        role(result, 'a', 'presence'); role(result, 'c', 'presence'); role(result, 'x', 'presence');
        assert.equal(result.slots[0].overlaps.length, 3, 'physical mismatch does not invent a replacement route');
    });
}

test('stable-clear removal and later held ON do not resurrect an omitted tip', () => {
    const d = diagnostics(); const p = d.selected_paths[0];
    p.branch_routes = p.branch_routes.filter(route => route.at(-1).node_id !== 'b');
    p.visits.find(v => v.node_id === 'b').branch_active = false;
    for (const phase of ['off', 'unknown', 'on']) {
        d.path_health.find(v => v.node_id === 'b').phase = phase;
        const result = project(d);
        assert.equal(result.state, 'selected'); role(result, 'b', 'neutral', []); role(result, 'b_next', 'neutral', []);
        assert.equal(result.slots[0].overlaps.length, 2);
    }
});

test('shared main prefix copies retain strength and geometry without duplicate segment rendering', () => {
    const p = specimen(); const root = p.route[0]; root.kind = 'positive'; root.branch_active = true;
    const result = project(diagnostics(p));
    role(result, 'r', 'presence'); role(result, 'r_next', 'candidate');
    assert.ok(result.slots[0].overlaps.every(route => route[0].role === 'presence'));
    // A shared R->A edge appears twice in witnesses but represents one edge.
    p.branch_routes[1] = [root, p.visits[0], p.visits[1]];
    const map = mapWire(); map.nodes.a.adjacent.push('b');
    const fork = project(diagnostics(p), map);
    assert.equal(fork.state, 'selected');
    assert.equal(fork.segments.filter(s => s.from === 'r' && s.to === 'a').length, 1);
    assert.ok(fork.segments.some(s => s.from === 'a' && s.to === 'b'));
    assert.equal(fork.slots[0].overlaps[0].at(-1).role, 'presence');
    assert.equal(fork.slots[0].overlaps[1][1].role, 'presence', 'the identical tip copied inside another prefix has equal authority');
    role(fork, 'a', 'presence'); role(fork, 'a_next', 'candidate');
});

test('strongest roles and all memberships survive same-zone overlap across distinct slots', () => {
    const d = diagnostics(); const other = visit('other', 5, { zone: 'a' });
    d.selected_paths.push({ visits: [other], route: [other], spatial_at: other.at, branch_routes: [], track_confidence: 'provisional', endpoint_eligible: true });
    d.expected_occupants = 2;
    d.episodes.push({ node_id: 'other', zone: 'a', episode_id: other.episode_id, status: 'asserted' });
    d.path_health.push({ node_id: 'other', zone: 'a', phase: 'on' });
    const map = mapWire(); map.nodes.other = { zone: 'a', adjacent: ['a_next', 'r'] };
    const result = project(d, map);
    assert.equal(result.slots.length, 2);
    assert.deepEqual(result.zones.get('a'), { role: 'presence', slots: [1, 2] });
    role(result, 'r', 'history', [1, 2]); role(result, 'a_next', 'candidate', [1, 2]);
});

test('equal-time input order is independent of canonical tip name order', () => {
    const p = specimen();
    for (const v of new Set([...p.visits, ...p.route])) v.at = at(0);
    p.visits = [p.visits[2], p.visits[1], p.visits[0], p.endpoint]; // C then B then A then X, not lexical.
    p.spatial_at = at(0); p.updated_at = at(0);
    const decoded = decodeSelectedPaths([p])[0];
    assert.deepEqual(decoded.visits.map(v => v.node_id), ['c', 'b', 'a', 'x']);
    assert.deepEqual(decoded.branch_routes.map(route => route.at(-1).node_id), ['a', 'b', 'c']);
    assert.equal(project(diagnostics(p)).state, 'selected');
    const reversed = structuredClone(p); reversed.branch_routes.reverse();
    assert.throws(() => decodeSelectedPaths([reversed]), /canonical/);
});

test('sub-millisecond chronology is validated without Date millisecond rounding', () => {
    const p = specimen();
    p.visits[0].at = at(1, '.000002'); p.visits[1].at = at(1, '.000001');
    assert.throws(() => decodeSelectedPaths([p]), /out of order/);
    p.visits[0].at = at(1, '.000000');
    assert.doesNotThrow(() => decodeSelectedPaths([p]));
});

test('equal-time observed fork is legal, but conflicting parents and causal cycles reject', () => {
    const root = visit('r', 0, { branch_active: false });
    const b = visit('b', 0); const c = visit('c', 0); const x = visit('x', 0);
    const p = { visits: [root, b, c, x], route: [root, b, x], branch_routes: [[root, b, c]], spatial_at: at(0), track_confidence: 'confirmed', endpoint_eligible: true };
    assert.doesNotThrow(() => decodeSelectedPaths([p]), 'R-B-X and R-B-C do not assert a C-X geometric edge');
    const badParent = structuredClone(p); badParent.branch_routes = [[root, c, b, visit('a', 0)]];
    badParent.visits = [b, c, badParent.branch_routes[0].at(-1), x];
    assert.throws(() => decodeSelectedPaths([badParent]), /conflicting parents/);
    const cycle = structuredClone(p); cycle.visits = [c, root, b, x];
    assert.throws(() => decodeSelectedPaths([cycle]), /cyclic/);
});

const corruptions = {
    'missing visits': p => { delete p.visits; },
    'missing overlap': p => { delete p.branch_routes; },
    'missing spatial time': p => { delete p.spatial_at; },
    'missing visit time': p => { delete p.visits[0].at; },
    'missing visit kind': p => { delete p.visits[0].kind; },
    'duplicate tip': p => { p.branch_routes[1] = p.branch_routes[0]; },
    'inactive tip': p => { p.visits[0].branch_active = false; },
    'interaction tip': p => { p.visits[0].kind = 'interaction'; },
    'tip not in history': p => { p.visits = p.visits.slice(1); },
    'tip in main': p => { p.branch_routes[0] = [p.endpoint]; },
    'copy flag disagrees': p => { p.branch_routes[0][0] = { ...p.branch_routes[0][0], branch_active: true }; },
    'copy time disagrees': p => { p.branch_routes[0][1] = { ...p.visits[0], at: at(0) }; },
    'copy zone disagrees': p => { p.branch_routes[0][1] = { ...p.visits[0], zone: 'other' }; },
    'copy kind disagrees': p => { p.branch_routes[0][1] = { ...p.visits[0], kind: 'correlated_positive' }; },
    'prefix-only active': p => { const old = visit('old', 0); p.branch_routes[0].unshift(old); },
    'history endpoint disagrees': p => { p.visits.reverse(); },
    'derived endpoint disagrees': p => { p.endpoint = { ...p.endpoint, at: at(3) }; },
    'derived update disagrees': p => { p.updated_at = at(5); },
    'unobserved spatial time': p => { p.spatial_at = at(1, '.5'); },
    'future spatial time': p => { p.spatial_at = at(5); },
    'invalid calendar': p => { p.visits[0].at = '2026-02-30T00:00:00Z'; },
    'naive timestamp': p => { p.visits[0].at = '2026-09-16T00:00:00'; },
    'duplicate within route': p => { p.route = [p.route[0], p.route[0], p.endpoint]; },
};
for (const [name, corrupt] of Object.entries(corruptions)) {
    test(`malformed v2 ${name} fails closed without losing beliefs or policy`, () => {
        const d = diagnostics(); corrupt(d.selected_paths[0]); unavailable(d);
        assert.ok(decodeDiagnostics(d).selected_paths_error);
    });
}

test('cross-slot copied observations reject rather than creating another occupant', () => {
    const d = diagnostics(); d.expected_occupants = 2; d.selected_paths.push(structuredClone(d.selected_paths[0]));
    unavailable(d); assert.match(decodeDiagnostics(d).selected_paths_error, /multiple slots/);
});

test('all raw bounds reject before nested visit getters in either slot are decoded', () => {
    const poison = { get node_id() { assert.fail('decoded nested leaf before bounds'); } };
    for (const [name, corrupt] of [
        ['slot', raw => raw.push(null)],
        ['visits', raw => { raw[1].visits = Array(5).fill(poison); }],
        ['route', raw => { raw[1].route = Array(5).fill(poison); }],
        ['overlap routes', raw => { raw[1].branch_routes = Array(4).fill([poison]); }],
        ['overlap route', raw => { raw[1].branch_routes = [Array(5).fill(poison)]; }],
        ['empty visits', raw => { raw[1].visits = []; }],
        ['empty route', raw => { raw[1].route = []; }],
        ['empty witness', raw => { raw[1].branch_routes = [[]]; }],
    ]) {
        const raw = [specimen(), specimen()]; raw[0].visits[0] = poison; corrupt(raw);
        assert.throws(() => decodeSelectedPaths(raw), /Invalid bounded selected/, name);
    }
});

test('four-record saved witnesses and main records outside four-visit history remain intact', () => {
    const p = specimen(); const early = visit('early', 0, { branch_active: false });
    const middle = visit('middle', 0, { branch_active: false });
    p.branch_routes[0] = [early, middle, p.route[0], p.visits[0]];
    const map = mapWire(); map.nodes.early = { zone: 'early', adjacent: ['middle'] }; map.nodes.middle = { zone: 'middle', adjacent: ['r'] };
    assert.equal(decodeSelectedPaths([p])[0].branch_routes[0].length, 4);
    const result = project(diagnostics(p), map);
    assert.equal(result.state, 'selected'); role(result, 'early', 'history'); role(result, 'middle', 'history');
});

test('geometry checks include prefix-only records, direction, zones and same-zone legal crossings', () => {
    for (const mutate of [
        map => { delete map.nodes.r; }, map => { map.nodes.r.zone = 'wrong'; },
        map => { map.nodes.r.adjacent = ['x', 'a', 'c']; map.nodes.b.adjacent.push('r'); },
    ]) { const map = mapWire(); mutate(map); unavailable(diagnostics(), map); }
    const d = diagnostics(); const map = mapWire();
    const p = d.selected_paths[0]; p.visits[1].zone = 'r'; map.nodes.b.zone = 'r';
    map.nodes.r.adjacent = map.nodes.r.adjacent.filter(id => id !== 'b');
    d.episodes.find(v => v.node_id === 'b').zone = 'r'; d.path_health.find(v => v.node_id === 'b').zone = 'r';
    assert.equal(project(d, map).state, 'selected', 'same-zone witness does not require a configured edge');
});

test('v2 marker is mandatory for present empty and null selections as well as located records', () => {
    for (const paths of [[], [null], [null, null], [specimen()]]) {
        for (const version of [undefined, 1, 0, 3, null, '2', true]) {
            const d = diagnostics(); d.selected_paths = paths; d.expected_occupants = paths.length;
            if (version === undefined) delete d.selected_path_version; else d.selected_path_version = version;
            unavailable(d); assert.match(decodeDiagnostics(d).selected_paths_error, /selected_path_version/);
        }
        const d = diagnostics(); d.selected_paths = paths; d.expected_occupants = paths.length;
        const result = project(d); assert.equal(result.state, 'selected'); assert.equal(result.slots.length, paths.length);
        assert.deepEqual(result.frontierTokens, []);
    }
    const absent = diagnostics(); delete absent.selected_paths; absent.selected_path_version = 1;
    assert.equal(project(absent).state, 'legacy');
});

const bundle = readFileSync(new URL('../../custom_components/predictive_controls/frontend/panel-v0.2.6.js', import.meta.url), 'utf8');
async function browser(t) {
    const errors = []; const console = new VirtualConsole(); console.on('jsdomError', error => errors.push(error.message));
    const dom = new JSDOM('<!doctype html><body></body>', { runScripts: 'dangerously', url: 'https://offline.invalid/', virtualConsole: console });
    t.after(() => { dom.window.close(); assert.deepEqual(errors, []); });
    const { window } = dom; window.eval(bundle);
    const panel = window.document.createElement('predictive-controls-panel'); window.document.body.append(panel);
    let current = { expected_occupants: 1, occupancy_diagnostics: diagnostics() }; let failure = false;
    const map = mapWire(); map.nodes.r.label = '<img src=x onerror="bad()">';
    panel._hass = {
        async callWS(message) {
            if (message.type === 'predictive_controls/config') return { entry_id: 'overlap', map, map_yaml: 'nodes: {}', expected_occupants: 1, transition_window_seconds: 30 };
            if (message.type === 'predictive_controls/entities') return { entities: [] };
            assert.equal(message.type, 'predictive_controls/status', 'no write operations');
            if (failure) throw new Error('offline'); return current;
        }
    };
    await panel.loadData();
    return { panel, current, async update(value) { current = value; await panel.refreshStatus(); }, async fail(value) { failure = value; await panel.refreshStatus(); } };
}

test('real shipped DOM labels each observed overlap in the same slot without fictitious concatenation', async t => {
    const h = await browser(t); const { panel } = h;
    assert.equal(panel.querySelector('[data-status-banner]').textContent, '');
    assert.equal(panel.querySelectorAll('.path-slot').length, 1);
    assert.deepEqual([...panel.querySelectorAll('.path-main-route .path-chip')].map(v => v.dataset.nodeId), ['r', 'x']);
    assert.deepEqual([...panel.querySelectorAll('.path-overlap')].map(section => [section.querySelector('h4').textContent, [...section.querySelectorAll('.path-chip')].map(v => v.dataset.nodeId)]), [
        ['Observed overlap 1', ['r', 'a']], ['Observed overlap 2', ['r', 'b']], ['Observed overlap 3', ['r', 'c']],
    ]);
    assert.equal(panel.querySelectorAll('.path-chip.path-role-presence').length, 4);
    assert.equal(panel.querySelectorAll('.zone-card.path-role-presence').length, 4);
    assert.equal(panel.querySelector('[data-zone="r_next"]').classList.contains('path-role-candidate'), false);
    assert.deepEqual([...panel.querySelectorAll('.selected-path-edge')].map(v => v.dataset.path), ['r->x', 'r->a', 'r->b', 'r->c']);
    assert.equal(panel.querySelector('img,[onerror]'), null);
    assert.match(panel.querySelector('.path-overlap').textContent, /<img src=x/);
});

test('real bundled warning, stale transport, clear/unknown and v2 recovery preserve independent policy', async t => {
    const h = await browser(t); const { panel } = h;
    const d = h.current.occupancy_diagnostics;
    d.reliability_warnings = [{ node_id: 'a', zone: 'a', kind: 'unsupported_jump', reasons: ['unsupported_jump'], active: true }];
    await h.update(h.current);
    const card = panel.querySelector('[data-zone="a"]');
    assert.ok(card.classList.contains('has-warning')); assert.ok(card.classList.contains('path-role-presence'));
    assert.match(card.querySelector('.zone-warning-label').textContent, /Unsupported Jump/);
    const oldGraph = panel.querySelector('.occupancy-graph').innerHTML;
    await h.fail(true);
    assert.match(panel.querySelector('[data-status-banner]').textContent, /Stale/);
    assert.equal(panel.querySelector('.occupancy-graph').innerHTML, oldGraph);
    await h.fail(false); assert.equal(panel.querySelector('[data-status-banner]').textContent, '');
    for (const phase of ['off', 'unknown']) {
        const next = structuredClone(h.current); next.occupancy_diagnostics.path_health.find(v => v.node_id === 'a').phase = phase;
        await h.update(next);
        assert.ok(panel.querySelector('[data-zone="a"]').classList.contains('path-role-history'));
        assert.ok(panel.querySelector('[data-zone="x"]').classList.contains('path-role-presence'));
        assert.equal(panel.querySelector('[data-zone="a_next"]').classList.contains('path-role-candidate'), false);
    }
    for (const corrupt of [
        s => { s.occupancy_diagnostics.selected_path_version = 1; },
        s => { delete s.occupancy_diagnostics.selected_paths[0].branch_routes; },
        s => { s.occupancy_diagnostics.selected_paths = null; },
    ]) {
        const next = structuredClone(h.current); corrupt(next); await h.update(next);
        assert.match(panel.querySelector('.selected-paths h3').textContent, /Selected paths unavailable/);
        assert.equal(panel.querySelectorAll('.path-slot,.authorized-path,.selected-path-edge').length, 0);
        assert.equal(panel.querySelector('[data-zone="x"] .zone-belief-state strong').textContent, 'Active');
        assert.equal(panel.querySelector('[data-zone="x"] .zone-card-head span').textContent, '80% belief');
        assert.equal(decodeStatus(next).occupancy_diagnostics.policy.x.active, true);
    }
    await h.update(h.current); assert.equal(panel.querySelectorAll('.path-overlap').length, 3);
    const empty = structuredClone(h.current); empty.expected_occupants = 0;
    empty.occupancy_diagnostics.expected_occupants = 0; empty.occupancy_diagnostics.selected_paths = [];
    await h.update(empty); assert.equal(panel.querySelector('.selected-paths h3').textContent, 'No selected paths');
    assert.equal(panel.querySelectorAll('.path-slot,.authorized-path,.has-frontier').length, 0);
});