import assert from "node:assert/strict";
import test from "node:test";

import { decodeDiagnostics, decodeMap, decodeStatus } from "../../frontend/decoders.ts";
import { projectPaths } from "../../frontend/paths.ts";
import { zoneSummaries } from "../../frontend/map-helpers.ts";
import { renderZoneEdges } from "../../frontend/components/graph.ts";
import { renderPathList } from "../../frontend/components/path-list.ts";

// Synthetic presentation contracts from strict-modular-panel.md, not incident
// replays or a substitute for backend selection. Every projection input crosses
// its real decoder; malformed wire data never masquerades as typed diagnostics.
function mapWire() {
    return {
        nodes: {
            a: { zone: "za", adjacent: ["b", "a_next"] },
            b: { zone: "zb", adjacent: ["c", "b_next"] },
            c: { zone: "zc", adjacent: ["b", "c_next"] },
            x: { zone: "zx", adjacent: ["y", "a_next"] },
            y: { zone: "zy", adjacent: ["c", "c_next"] },
            a_next: { zone: "za_next", adjacent: ["deep"] },
            b_next: { zone: "zb_next", adjacent: ["deep"] },
            c_next: { zone: "zc_next", adjacent: ["deep"] },
            deep: { zone: "zdeep", adjacent: [] },
            raw: { zone: "zraw", adjacent: ["raw_next"] },
            raw_next: { zone: "zraw_next", adjacent: [] },
        },
        zones: { empty_zone: { label: "Configured without a sensor" } },
    };
}

function visit(node, overrides = {}) {
    return { node_id: node, zone: `z${node}`, episode_id: `${node}:1`, branch_active: true, ...overrides };
}

function path(nodes = ["a", "b", "c"], overrides = {}) {
    return { route: nodes.map(node => visit(node)), track_confidence: "confirmed", endpoint_eligible: true, ...overrides };
}

function diagnosticsWire(paths = [path()]) {
    const current = new Map();
    for (const selected of paths) {
        for (const occurrence of selected?.route ?? []) current.set(occurrence.node_id, occurrence);
    }
    return {
        model: "zone_belief",
        expected_occupants: paths.length,
        selected_paths: paths,
        episodes: [...current.values()].map(v => ({ node_id: v.node_id, zone: v.zone, episode_id: v.episode_id, status: "asserted" })),
        // status.py publishes no episode_id in path_health. Generation comes only
        // from episodes, keyed by physical node, not array order or alias identity.
        path_health: [...current.values()].map(v => ({ node_id: v.node_id, zone: v.zone, phase: "on" })),
    };
}

function project(wire = diagnosticsWire(), rawMap = mapWire(), snapshotCount) {
    const map = decodeMap(rawMap);
    const status = decodeStatus({ occupancy_diagnostics: wire, ...(snapshotCount === undefined ? {} : { expected_occupants: snapshotCount }) });
    const result = projectPaths(map, status.occupancy_diagnostics, status.expected_occupants);
    return { result, map, status };
}

function membership(result, id, role, slots = [], kind = "nodes") {
    assert.deepEqual(result[kind].get(id), { role, slots }, `${kind}.${id}`);
}

function idsWithRole(result, role) {
    return [...result.nodes].filter(([, value]) => value.role === role).map(([id]) => id).sort();
}

function segments(result) {
    return result.segments.map(s => [s.slot, s.from, s.to, s.sourceZone, s.targetZone]);
}

function edgeMarkup({ map, status, result }) {
    return renderZoneEdges(zoneSummaries(map), 0, 0, { map, status, statusError: undefined, updated: undefined }, result);
}

function legacyWire() {
    return {
        traversal_frontier: [{ token_id: "old-a", zone: "za" }],
        authorizations: [{ authorized: true, source_token_ids: ["old-a"], target_zone: "zraw" }],
    };
}

function assertUnavailable(projected) {
    assert.equal(projected.state, "unavailable");
    assert.match(projected.message, /^Selected paths unavailable/);
    assert.deepEqual(projected.slots, []);
    assert.deepEqual(projected.segments, []);
    assert.deepEqual(projected.frontierTokens, []);
    assert.deepEqual([...projected.frontierZones], []);
    assert.deepEqual(projected.authorizedPaths, []);
    for (const value of [...projected.nodes.values(), ...projected.zones.values()]) {
        assert.deepEqual(value, { role: "neutral", slots: [] });
    }
}

function deepFreeze(value) {
    if (value !== null && typeof value === "object") {
        for (const child of Object.values(value)) deepFreeze(child);
        Object.freeze(value);
    }
    return value;
}

test("A/B/C ON have equally strong presence independently of confidence badges and policy", () => {
    for (const confidence of ["provisional", "confirmed"]) {
        for (const active of [false, true]) {
            const wire = diagnosticsWire([path(undefined, { track_confidence: confidence })]);
            wire.policy = { za: { active }, zb: { active: !active }, zc: { active } };
            wire.beliefs = { za: 0, zb: 0.5, zc: 1 };
            const { result, map } = project(wire);
            assert.equal(result.state, "selected");
            assert.deepEqual(result.slots[0].occurrences.map(o => o.role), ["presence", "presence", "presence"]);
            for (const id of ["a", "b", "c"]) {
                membership(result, id, "presence", [1]);
                membership(result, `z${id}`, "presence", [1], "zones");
            }
            assert.deepEqual(idsWithRole(result, "candidate"), ["a_next", "b_next", "c_next"]);
            membership(result, "deep", "neutral");
            assert.equal(result.slots[0].path.track_confidence, confidence);
            assert.match(renderPathList(result, map), new RegExp(confidence === "confirmed" ? "Confirmed" : "Provisional"));
        }
    }
});

test("A/B OFF and C ON retain history and derive candidates only from C", () => {
    const wire = diagnosticsWire();
    for (const id of ["a", "b"]) {
        wire.selected_paths[0].route.find(v => v.node_id === id).branch_active = false;
        wire.path_health.find(h => h.node_id === id).phase = "off";
        wire.episodes.find(e => e.node_id === id).status = "clear";
    }
    const { result } = project(wire);
    assert.deepEqual(result.slots[0].occurrences.map(o => [o.role, o.phase]), [["history", "OFF"], ["history", "OFF"], ["presence", "ON"]]);
    membership(result, "a", "history", [1]);
    membership(result, "b", "history", [1]); // C -> B adjacency cannot downgrade history.
    membership(result, "c", "presence", [1]);
    assert.deepEqual(idsWithRole(result, "candidate"), ["c_next"]);
    membership(result, "a_next", "neutral");
    membership(result, "b_next", "neutral");
    membership(result, "deep", "neutral");
    assert.deepEqual(segments(result), [[1, "a", "b", "za", "zb"], [1, "b", "c", "zb", "zc"]]);
});

test("one-hop candidate union preserves overlapping anonymous slot memberships without recursion", () => {
    const { result } = project(diagnosticsWire([path(), path(["x", "y", "c"], { track_confidence: "provisional" })]), mapWire(), 2);
    membership(result, "a", "presence", [1]);
    membership(result, "x", "presence", [2]);
    membership(result, "c", "presence", [1, 2]);
    membership(result, "zc", "presence", [1, 2], "zones");
    membership(result, "a_next", "candidate", [1, 2]);
    membership(result, "c_next", "candidate", [1, 2]);
    membership(result, "b_next", "candidate", [1]);
    membership(result, "deep", "neutral");
    assert.deepEqual(segments(result), [
        [1, "a", "b", "za", "zb"], [1, "b", "c", "zb", "zc"],
        [2, "x", "y", "zx", "zy"], [2, "y", "c", "zy", "zc"],
    ]);
});

test("history supersedes another slot's adjacency while retaining both memberships", () => {
    const rawMap = mapWire();
    rawMap.nodes.y.adjacent.push("a");
    const wire = diagnosticsWire([path(), path(["x", "y"])]);
    wire.selected_paths[0].route[0].branch_active = false;
    wire.path_health.find(h => h.node_id === "a").phase = "off";
    const { result } = project(wire, rawMap);
    membership(result, "a", "history", [1, 2]);
    membership(result, "za", "history", [1, 2], "zones");
    membership(result, "y", "presence", [2]);
    assert.equal(result.slots[0].occurrences[0].role, "history");
});

test("zone aggregation takes the strongest physical role and unions memberships rather than choosing a person", () => {
    const rawMap = mapWire();
    rawMap.nodes.x.zone = "za";
    const second = path(["x", "y"]);
    second.route[0].zone = "za";
    const wire = diagnosticsWire([path(), second]);
    wire.selected_paths[0].route[0].branch_active = false;
    wire.path_health.find(h => h.node_id === "a").phase = "off";
    const { result } = project(wire, rawMap);
    membership(result, "a", "history", [1]);
    membership(result, "x", "presence", [2]);
    membership(result, "za", "presence", [1, 2], "zones");
    membership(result, "empty_zone", "neutral", [], "zones");
});

test("unrelated raw ON, full belief and active policy remain neutral and cannot source candidates", () => {
    const wire = diagnosticsWire();
    wire.episodes.push({ node_id: "raw", zone: "zraw", episode_id: "raw:1", status: "asserted" });
    wire.path_health.push({ node_id: "raw", zone: "zraw", phase: "on" });
    wire.policy = { zraw: { active: true } };
    wire.beliefs = { zraw: 1, zraw_next: 1 };
    const { result } = project(wire);
    membership(result, "raw", "neutral");
    membership(result, "raw_next", "neutral");
    membership(result, "zraw", "neutral", [], "zones");
});

test("route alone determines membership, not visits union, covered/eligible sets or old authorizations", () => {
    const selected = path();
    selected.visits = [...selected.route, visit("raw")];
    selected.covered_node_ids = ["a", "b", "c", "raw"];
    selected.covered_zones = ["za", "zb", "zc", "zraw"];
    selected.eligible_node_ids = ["a", "b", "c", "raw"];
    const wire = { ...diagnosticsWire([selected]), ...legacyWire() };
    wire.episodes.push({ node_id: "raw", zone: "zraw", episode_id: "raw:1", status: "asserted" });
    wire.path_health.push({ node_id: "raw", zone: "zraw", phase: "on" });
    const { result } = project(wire);
    assert.deepEqual(result.slots[0].occurrences.map(o => o.visit.node_id), ["a", "b", "c"]);
    membership(result, "raw", "neutral");
    assert.deepEqual(result.frontierTokens, []);
    assert.deepEqual(result.authorizedPaths, []);
});

test("zero occupants and present empty selection never fall back to historical paths", () => {
    const { result, map } = project({ ...diagnosticsWire([]), ...legacyWire() }, mapWire(), 0);
    assert.equal(result.state, "selected");
    assert.equal(result.message, "No selected paths");
    assert.deepEqual(result.slots, []);
    assert.deepEqual(result.authorizedPaths, []);
    assert.deepEqual(result.frontierTokens, []);
    assert.match(renderPathList(result, map), /No selected paths/);
    membership(result, "a", "neutral");
});

test("explicit empty selection without an available count still means no selected paths, not legacy", () => {
    const wire = { ...legacyWire(), selected_paths: [] };
    const { result } = project(wire);
    assert.equal(result.state, "selected");
    assert.equal(result.message, "No selected paths");
    assert.deepEqual(result.frontierTokens, []);
});

test("two null slots stay separately unlocated with no fabricated route or role", () => {
    const { result, map } = project(diagnosticsWire([null, null]), mapWire(), 2);
    assert.equal(result.state, "selected");
    assert.deepEqual(result.slots.map(s => [s.slot, s.path, s.occurrences]), [[1, null, []], [2, null, []]]);
    assert.deepEqual(result.segments, []);
    assert.match(renderPathList(result, map), /Slot 1 · Unlocated/);
    assert.match(renderPathList(result, map), /Slot 2 · Unlocated/);
    for (const value of result.nodes.values()) assert.deepEqual(value, { role: "neutral", slots: [] });
});

test("null slots before or after a located path do not compact anonymous slot indices", () => {
    for (const [paths, slot] of [[[null, path()], 2], [[path(), null], 1]]) {
        const { result } = project(diagnosticsWire(paths));
        assert.equal(result.slots.length, 2);
        membership(result, "a", "presence", [slot]);
        membership(result, "c_next", "candidate", [slot]);
        assert.ok(result.segments.every(s => s.slot === slot));
    }
});

test("only absent selected_paths enables explicitly labeled legacy projection", () => {
    const wire = legacyWire();
    wire.authorizations.push(
        { authorized: true, source_token_ids: ["old-a", "old-a"], target_zone: "zraw" },
        { authorized: false, source_token_ids: ["old-a"], target_zone: "zb" },
        { authorized: true, source_token_ids: ["missing"], target_zone: "zc" },
        { authorized: true, source_token_ids: ["old-a"], target_zone: "za" },
    );
    const { result, map } = project(wire);
    assert.equal(result.state, "legacy");
    assert.match(result.message, /Legacy.*selected paths not supplied/);
    assert.deepEqual(result.authorizedPaths, [{ sourceZone: "za", targetZone: "zraw" }]);
    assert.deepEqual([...result.frontierZones], ["za"]);
    assert.deepEqual(result.slots, []);
    membership(result, "a", "neutral");
    assert.match(renderPathList(result, map), /Legacy/);
});

test("missing diagnostics is explicitly legacy/unavailable information, not an invented selected path", () => {
    const result = projectPaths(decodeMap(mapWire()), undefined);
    assert.equal(result.state, "legacy");
    assert.deepEqual(result.slots, []);
    assert.deepEqual(result.frontierTokens, []);
    assert.deepEqual(result.authorizedPaths, []);
    membership(result, "empty_zone", "neutral", [], "zones");
});

test("unsupported or inconsistent finite counts make selection unavailable without fallback", () => {
    for (const count of [-1, 0, 0.5, 2, 3]) {
        const wire = { ...diagnosticsWire(), ...legacyWire() };
        assertUnavailable(project(wire, mapWire(), count).result);
    }
    for (const count of [-1, 0, 0.5, 2, 3]) {
        const wire = { ...diagnosticsWire(), ...legacyWire(), expected_occupants: count };
        assertUnavailable(project(wire, mapWire(), 1).result);
    }
    assertUnavailable(project({ ...diagnosticsWire(), unsupported_count: true }).result);
    assertUnavailable(project({ ...diagnosticsWire([]), expected_occupants: 1 }).result);
    assertUnavailable(project(diagnosticsWire([null, null]), mapWire(), 1).result);
});

test("malformed present selection is decoded as an explicit error and cannot activate legacy fallback", () => {
    for (const selected of [null, undefined, false, 1, "[]", {}, [false], [path([], {})], [null, null, null]]) {
        const decoded = decodeDiagnostics({ ...legacyWire(), selected_paths: selected });
        assert.equal(typeof decoded.selected_paths_error, "string");
        assertUnavailable(projectPaths(decodeMap(mapWire()), decoded));
    }
});

test("four ordered occurrences are retained without truncation or extra route expansion", () => {
    const rawMap = mapWire();
    rawMap.nodes.c.adjacent.push("d");
    rawMap.nodes.d = { zone: "zd", adjacent: ["deep"] };
    const { result } = project(diagnosticsWire([path(["a", "b", "c", "d"])]), rawMap);
    assert.deepEqual(result.slots[0].occurrences.map(o => o.visit.node_id), ["a", "b", "c", "d"]);
    assert.deepEqual(segments(result), [[1, "a", "b", "za", "zb"], [1, "b", "c", "zb", "zc"], [1, "c", "d", "zc", "zd"]]);
    membership(result, "d", "presence", [1]);
    membership(result, "deep", "candidate", [1]);
});

test("revisited physical nodes retain old-generation history and new-generation presence in occurrence order", () => {
    const rawMap = mapWire();
    rawMap.nodes.b.adjacent.push("a");
    rawMap.nodes.a.adjacent.push("c");
    const route = [visit("a", { episode_id: "a:old" }), visit("b"), visit("a", { episode_id: "a:new" }), visit("c")];
    const { result, map } = project(diagnosticsWire([path([], { route })]), rawMap);
    const occurrences = result.slots[0].occurrences;
    assert.deepEqual(occurrences.map(o => [o.visit.node_id, o.visit.episode_id, o.role]), [
        ["a", "a:old", "history"], ["b", "b:1", "presence"], ["a", "a:new", "presence"], ["c", "c:1", "presence"],
    ]);
    assert.equal(occurrences[0].issue, "Earlier episode");
    assert.equal(occurrences[2].issue, undefined);
    membership(result, "a", "presence", [1]);
    assert.deepEqual(segments(result), [[1, "a", "b", "za", "zb"], [1, "b", "a", "zb", "za"], [1, "a", "c", "za", "zc"]]);
    const html = renderPathList(result, map);
    assert.ok(html.indexOf('data-episode-id="a:old"') < html.indexOf('data-episode-id="a:new"'));
    assert.equal((html.match(/data-node-id="a"/g) ?? []).length, 2);
});

test("episodes and physical health join by node identity rather than array order", () => {
    const wire = diagnosticsWire();
    wire.episodes.reverse();
    wire.path_health = [wire.path_health[1], wire.path_health[2], wire.path_health[0]];
    const { result } = project(wire);
    assert.deepEqual(idsWithRole(result, "presence"), ["a", "b", "c"]);
});

test("missing or duplicate episode identity is unjoinable, including duplicate identical rows", () => {
    for (const mode of ["missing", "identical", "different-generation"]) {
        const wire = diagnosticsWire();
        const a = wire.episodes.find(e => e.node_id === "a");
        if (mode === "missing") wire.episodes = wire.episodes.filter(e => e.node_id !== "a");
        else wire.episodes.push({ ...a, ...(mode === "different-generation" ? { episode_id: "a:other" } : {}) });
        const { result } = project(wire);
        membership(result, "a", "history", [1]);
        membership(result, "a_next", "neutral");
        membership(result, "b", "presence", [1]);
        assert.equal(result.slots[0].occurrences[0].issue, "Physical diagnostics unavailable");
    }
});

test("missing or duplicate health identity is unjoinable rather than last-writer-wins", () => {
    for (const mode of ["missing", "identical", "conflicting"]) {
        const wire = diagnosticsWire();
        const a = wire.path_health.find(h => h.node_id === "a");
        if (mode === "missing") wire.path_health = wire.path_health.filter(h => h.node_id !== "a");
        else wire.path_health.push({ ...a, ...(mode === "conflicting" ? { phase: "off" } : {}) });
        const { result } = project(wire);
        membership(result, "a", "history", [1]);
        membership(result, "a_next", "neutral");
        assert.equal(result.slots[0].occurrences[0].phase, "Unknown");
        assert.equal(result.slots[0].occurrences[0].issue, "Physical diagnostics unavailable");
    }
});

test("partial historical episode rows cannot guess missing zone or generation", () => {
    for (const partial of [{ node_id: "a" }, { node_id: "a", zone: "za" }, { node_id: "a", zone: "za", episode_id: null }]) {
        const wire = diagnosticsWire();
        wire.episodes[0] = partial;
        const { result } = project(wire);
        membership(result, "a", "history", [1]);
        membership(result, "a_next", "neutral");
        assert.ok(result.slots[0].occurrences[0].issue);
    }
});

test("wrong episode or health zone cannot create presence or candidate sources", () => {
    for (const field of ["episodes", "path_health"]) {
        const wire = diagnosticsWire();
        wire[field][0].zone = "unrelated-zone";
        const { result } = project(wire);
        membership(result, "a", "history", [1]);
        membership(result, "a_next", "neutral");
        assert.equal(result.zones.has("unrelated-zone"), false);
    }
});

test("wrong map membership or zone keeps invalid occurrences visible but gives them no physical role membership", () => {
    for (const mode of ["missing-node", "wrong-zone"]) {
        const rawMap = mapWire();
        if (mode === "missing-node") delete rawMap.nodes.a;
        else rawMap.nodes.a.zone = "other-zone";
        const { result } = project(diagnosticsWire(), rawMap);
        assert.equal(result.slots[0].occurrences[0].valid, false);
        assert.equal(result.slots[0].occurrences[0].role, "history");
        assert.equal(result.slots[0].occurrences[0].issue, "Map membership unavailable");
        membership(result, "a_next", "neutral");
        if (mode === "wrong-zone") {
            membership(result, "a", "neutral");
            membership(result, "other-zone", "neutral", [], "zones");
        } else assert.equal(result.nodes.has("a"), false);
        assert.deepEqual(segments(result), [[1, "b", "c", "zb", "zc"]]);
    }
});

test("a missing or invalid middle never shortcuts A to C, even when a direct edge is configured", () => {
    for (const mode of ["missing", "wrong-zone"]) {
        const rawMap = mapWire();
        rawMap.nodes.a.adjacent.push("c");
        if (mode === "missing") delete rawMap.nodes.b;
        else rawMap.nodes.b.zone = "other-zone";
        const projected = project(diagnosticsWire(), rawMap);
        assert.deepEqual(projected.result.slots[0].occurrences.map(o => o.visit.node_id), ["a", "b", "c"]);
        assert.deepEqual(projected.result.segments, []);
        const html = edgeMarkup(projected);
        assert.doesNotMatch(html, /selected-path-edge|path-arrow/);
        assert.match(html, /zone-edge/); // Real configured topology is still drawn.
    }
});

test("an unobserved omitted middle cannot turn two-hop topology into a selected shortcut", () => {
    const projected = project(diagnosticsWire([path(["a", "c"])]));
    assert.deepEqual(projected.result.slots[0].occurrences.map(o => o.visit.node_id), ["a", "c"]);
    assert.deepEqual(projected.result.segments, []);
    membership(projected.result, "a", "presence", [1]);
    membership(projected.result, "c", "presence", [1]);
    membership(projected.result, "b", "candidate", [1]);
    assert.doesNotMatch(edgeMarkup(projected), /selected-path-edge|path-arrow/);
});

test("an OFF middle does not disconnect history or fabricate an A-to-C arrow", () => {
    const wire = diagnosticsWire();
    wire.path_health[1].phase = "off";
    wire.selected_paths[0].route[1].branch_active = false;
    const projected = project(wire);
    assert.deepEqual(projected.result.slots[0].occurrences.map(o => o.role), ["presence", "history", "presence"]);
    assert.deepEqual(segments(projected.result), [[1, "a", "b", "za", "zb"], [1, "b", "c", "zb", "zc"]]);
    const html = edgeMarkup(projected);
    assert.match(html, /data-path="za-&gt;zb"/);
    assert.match(html, /data-path="zb-&gt;zc"/);
    assert.doesNotMatch(html, /data-path="za-&gt;zc"/);
});

test("selected route segments and candidates respect configured direction without reverse inference", () => {
    const rawMap = mapWire();
    rawMap.nodes.a.adjacent = ["b"];
    rawMap.nodes.b.adjacent = ["c"];
    rawMap.nodes.c.adjacent = [];
    const wire = diagnosticsWire([path(["c", "b", "a"])]);
    for (const occurrence of wire.selected_paths[0].route.slice(1)) occurrence.branch_active = false;
    const projected = project(wire, rawMap);
    assert.deepEqual(projected.result.segments, []);
    assert.deepEqual(idsWithRole(projected.result, "candidate"), []);
    assert.doesNotMatch(edgeMarkup(projected), /selected-path-edge|path-arrow/);
    const forward = project(diagnosticsWire(), rawMap);
    assert.deepEqual(segments(forward.result), [[1, "a", "b", "za", "zb"], [1, "b", "c", "zb", "zc"]]);
});

test("same-zone physical segments are retained but graph arrows represent only real cross-zone movement", () => {
    const rawMap = mapWire();
    rawMap.nodes.b.zone = "za";
    const selected = path();
    selected.route[1].zone = "za";
    const projected = project(diagnosticsWire([selected]), rawMap);
    assert.deepEqual(segments(projected.result), [[1, "a", "b", "za", "za"], [1, "b", "c", "za", "zc"]]);
    const html = edgeMarkup(projected);
    assert.equal((html.match(/class="selected-path-edge"/g) ?? []).length, 1);
    assert.equal((html.match(/class="path-arrow"/g) ?? []).length, 1);
    assert.match(html, /data-path="za-&gt;zc"/);
    assert.doesNotMatch(html, /data-path="za-&gt;za"|data-path="za-&gt;zb"/);
});

test("OFF and unknown endpoints remain located history regardless of continuation eligibility", () => {
    for (const phase of ["off", "unknown"]) {
        for (const eligible of [false, true]) {
            const selected = path(undefined, { endpoint_eligible: eligible });
            selected.route[2].branch_active = false;
            selected.endpoint = { ...selected.route[2] };
            // These backend coverage sets deliberately include the retained endpoint;
            // neither endpoint coverage nor eligibility is a raw-ON indicator.
            selected.covered_node_ids = ["a", "b", "c"];
            selected.eligible_node_ids = eligible ? ["a", "b", "c"] : ["a", "b"];
            const wire = diagnosticsWire([selected]);
            wire.path_health[2].phase = phase;
            wire.episodes[2].status = phase === "off" ? "clear" : "unavailable";
            const { result, map } = project(wire);
            membership(result, "c", "history", [1]);
            membership(result, "c_next", "neutral");
            assert.equal(result.slots[0].occurrences.length, 3);
            assert.equal(result.slots[0].path.endpoint_eligible, eligible);
            const label = phase === "off" ? "OFF" : "Unknown";
            assert.match(renderPathList(result, map), new RegExp(`Retained endpoint · ${label} · Continuation eligible: ${eligible ? "yes" : "no"}`));
            assert.doesNotMatch(renderPathList(result, map), /Unlocated|\babsent\b/i);
        }
    }
});

test("ON with inactive branch remains history even when its retained endpoint is eligible", () => {
    const selected = path(["a"], { endpoint_eligible: true });
    selected.route[0].branch_active = false;
    const { result, map } = project(diagnosticsWire([selected]));
    membership(result, "a", "history", [1]);
    membership(result, "a_next", "neutral");
    assert.equal(result.slots[0].occurrences[0].phase, "ON");
    assert.match(renderPathList(result, map), /Retained endpoint · ON · Continuation eligible: yes/);
});

test("an active branch flag cannot manufacture physical ON from OFF or unknown health", () => {
    for (const phase of ["off", "unknown"]) {
        const wire = diagnosticsWire([path(["a"])]);
        wire.path_health[0].phase = phase;
        const { result } = project(wire);
        assert.equal(result.slots[0].occurrences[0].visit.branch_active, true);
        membership(result, "a", "history", [1]);
        membership(result, "b", "neutral");
        membership(result, "a_next", "neutral");
        assert.deepEqual(idsWithRole(result, "candidate"), []);
    }
});

test("clearing physical phase or episode status is never current ON presence", () => {
    for (const [phase, status] of [["clearing", "asserted"], ["on", "clearing"], ["clearing", "clearing"]]) {
        const wire = diagnosticsWire([path(["a"])]);
        wire.path_health[0].phase = phase;
        wire.episodes[0].status = status;
        const { result } = project(wire);
        membership(result, "a", "history", [1]);
        membership(result, "a_next", "neutral");
        assert.deepEqual(result.slots[0].occurrences.map(o => o.role), ["history"]);
    }
});

test("a stale route generation cannot borrow current physical ON or endpoint eligibility", () => {
    const wire = diagnosticsWire([path(["a"])]);
    wire.episodes[0].episode_id = "a:new";
    const { result } = project(wire);
    membership(result, "a", "history", [1]);
    membership(result, "a_next", "neutral");
    assert.equal(result.slots[0].occurrences[0].issue, "Earlier episode");
    assert.equal(result.slots[0].occurrences[0].phase, "ON");
});

test("diagnostic warning kinds and active flags cannot alter path roles or candidate authority", () => {
    const baseline = project().result;
    for (const [kind, reasons, active] of [["suspected_stuck", ["assertion_timeout"], true], ["suspected_stuck", ["count_conflict"], true], ["unsupported_jump", ["unsupported_jump"], false]]) {
        const wire = diagnosticsWire();
        wire.reliability_warnings = [{ node_id: "a", zone: "za", kind, reasons, active }];
        assert.deepEqual(project(wire).result, baseline);
    }
});

test("projection does not mutate frozen decoded map, routes, episodes, health or legacy diagnostics", () => {
    for (const wire of [diagnosticsWire([path(), path(["x", "y", "c"])]), legacyWire()]) {
        const map = deepFreeze(decodeMap(mapWire()));
        const diagnostics = deepFreeze(decodeDiagnostics(wire));
        const beforeMap = structuredClone(map);
        const beforeDiagnostics = structuredClone(diagnostics);
        const first = projectPaths(map, diagnostics);
        const second = projectPaths(map, diagnostics);
        assert.deepEqual(second, first);
        assert.deepEqual(map, beforeMap);
        assert.deepEqual(diagnostics, beforeDiagnostics);
    }
});

test("nodes with omitted zone use their own configured identity, without inventing zone membership", () => {
    const rawMap = { nodes: { single: { adjacent: [] } }, zones: { empty: {} } };
    const selected = path([], { route: [visit("single", { zone: "single" })] });
    const { result } = project(diagnosticsWire([selected]), rawMap);
    membership(result, "single", "presence", [1]);
    membership(result, "single", "presence", [1], "zones");
    membership(result, "empty", "neutral", [], "zones");
});
