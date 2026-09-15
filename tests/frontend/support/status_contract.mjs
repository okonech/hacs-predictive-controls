// Cross-language consumer: stdin contains status payloads emitted by Python or
// the retained incident slice. No live access, source writes or artifact repair.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { JSDOM, VirtualConsole } from 'jsdom';

const compiled = await build({
    entryPoints: [fileURLToPath(new URL('../../../frontend/decoders.ts', import.meta.url))],
    bundle: true, write: false, platform: 'node', format: 'esm', target: 'node22',
});
const { decodeStatus } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].contents).toString('base64')}`);
const bundle = readFileSync(new URL('../../../custom_components/predictive_controls/frontend/panel-v0.2.6.js', import.meta.url), 'utf8');
const cases = JSON.parse(readFileSync(0, 'utf8'));
assert.ok(Array.isArray(cases) && cases.length > 0);
for (const { status, recover = false } of cases) {
    const original = structuredClone(status);
    const errors = [];
    const console = new VirtualConsole();
    console.on('jsdomError', error => errors.push(error.message));
    const dom = new JSDOM('<!doctype html><body></body>', { runScripts: 'dangerously', url: 'https://offline.invalid/', virtualConsole: console });
    try {
        const { window } = dom;
        window.eval(bundle);
        const panel = window.document.createElement('predictive-controls-panel');
        window.document.body.append(panel);
        const zones = Object.keys(status.zone_states);
        assert.ok(zones.length > 0);
        // Layout-only synthetic map: all state/policy values come from the input.
        const map = { nodes: Object.fromEntries(zones.map(zone => [zone, { zone, label: zone }])) };
        let current = status;
        panel._hass = {
            async callWS(message) {
                switch (message.type) {
                    case 'predictive_controls/config': return { entry_id: 'offline', map, map_yaml: 'nodes: {}', expected_occupants: status.expected_occupants, transition_window_seconds: 30 };
                    case 'predictive_controls/entities': return { entities: [] };
                    case 'predictive_controls/status': return current;
                    default: throw new Error(`Unexpected/non-read command: ${message.type}`);
                }
            }
        };
        await panel.loadData();
        const banner = () => panel.querySelector('[data-status-banner]').textContent;
        assert.equal(banner(), '', `Valid server status must render, not fail: ${banner()}`);
        for (const zone of zones) {
            const card = [...panel.querySelectorAll('[data-zone]')].find(el => el.dataset.zone === zone);
            assert.ok(card, zone);
            const expected = status.occupancy_diagnostics.policy[zone];
            assert.equal(card.querySelector('.zone-belief-state strong').textContent, expected.active ? 'Active' : 'Inactive');
            const belief = status.occupancy_diagnostics.beliefs[zone];
            assert.equal(card.querySelector('.zone-card-head span').textContent, `${Math.round(belief * 100)}% belief`);
            assert.doesNotMatch(card.textContent, /unavailable/);
        }
        const decoded = decodeStatus(status);
        assert.equal(decoded.occupancy_diagnostics.unsupported_count, status.occupancy_diagnostics.unsupported_count);
        if (Object.hasOwn(status.occupancy_diagnostics, 'selected_paths')) {
            assert.equal(decoded.occupancy_diagnostics.selected_paths_error, undefined);
            if (status.occupancy_diagnostics.unsupported_count !== null) {
                assert.match(panel.textContent, /Selected paths unavailable/);
            } else {
                assert.doesNotMatch(panel.textContent, /Legacy path display|Selected paths unavailable/);
                assert.equal(decoded.occupancy_diagnostics.selected_paths.length, status.expected_occupants);
            }
        }
        if (recover) {
            const before = panel.querySelector('.occupancy-graph').innerHTML;
            current = structuredClone(status);
            current.occupancy_diagnostics.unsupported_count = '3';
            await panel.refreshStatus();
            assert.match(banner(), /Stale \/ unavailable/);
            assert.equal(panel.querySelector('.occupancy-graph').innerHTML, before);
            current = status;
            await panel.refreshStatus();
            assert.equal(banner(), '');
        }
        assert.deepEqual(status, original, 'decoding/rendering must not mutate wire input');
        assert.deepEqual(errors, []);
    } finally {
        dom.window.close();
    }
}
console.log(`Validated ${cases.length} source-decoder/shipped-panel status contracts`);