import assert from "node:assert/strict";
import test from "node:test";

import {
    decodeCleanup,
    decodeConfig,
    decodeDiagnostics,
    decodeEntitiesMap,
    decodeMap,
    decodeNode,
    decodeSelectedPaths,
    decodeStatus,
    dictionary,
    finite,
    list,
    normalizeEntityResponse,
    record,
    text,
    validateSettings,
} from "../../frontend/decoders.ts";
import {
    auditKind,
    auditTransition,
    decisionExplanation,
    escapeHtml,
    formatPercent,
    warningLabel,
} from "../../frontend/formatting.ts";
import { moveNode, renameNode } from "../../frontend/map-helpers.ts";

// Wire specimens follow status.py, with optional historical fields deliberately
// absent where the panel does not consume them. These are decoder contracts, not
// stricter backend snapshot validators or changes to the original 31 tests.
function visit(node = "a", overrides = {}) {
    return { node_id: node, zone: `z${node}`, episode_id: `${node}:1`, branch_active: true, ...overrides };
}

function selected(overrides = {}) {
    return { route: [visit("a"), visit("b")], track_confidence: "provisional", endpoint_eligible: true, ...overrides };
}

function configWire(overrides = {}) {
    return {
        entry_id: "entry",
        map: { nodes: {} },
        map_yaml: "nodes: {}\n",
        transition_window_seconds: 15,
        expected_occupants: 2,
        ...overrides,
    };
}

function warningWire(overrides = {}) {
    return { node_id: "a", zone: "za", kind: "suspected_stuck", active: true, reasons: ["assertion_timeout"], ...overrides };
}

function decodedWarning(wire) {
    const result = decodeDiagnostics({ reliability_warnings: [wire] });
    assert.equal(result.reliability_warnings.length, 1);
    return result.reliability_warnings[0];
}

function rejectEach(decode, values, context) {
    for (const value of values) assert.throws(() => decode(value), Error, `${context}: ${String(value)}`);
}

function freeze(value) {
    if (value !== null && typeof value === "object") {
        for (const child of Object.values(value)) freeze(child);
        Object.freeze(value);
    }
    return value;
}

const nonRecords = [undefined, null, false, true, 0, 1, "", "{}", []];
const nonNumbers = [undefined, null, false, true, "0", "0.75", [], {}, NaN, Infinity, -Infinity];
const badProbabilities = [...nonNumbers, -0.001, 1.001];
const badBooleans = [undefined, null, 0, 1, "true", "false", [], {}];

test("object boundaries reject null, arrays and primitive values without coercion", () => {
    for (const [name, decode] of [
        ["record", record], ["map", decodeMap], ["node", decodeNode], ["config", decodeConfig],
        ["status", decodeStatus], ["diagnostics", decodeDiagnostics], ["entity response", normalizeEntityResponse],
    ]) rejectEach(decode, nonRecords, name);
    assert.deepEqual(record({ key: null }), { key: null });
});

test("string, finite-number, array and dictionary primitives validate rather than convert", () => {
    rejectEach(text, [null, undefined, true, 7, [], {}], "text");
    assert.equal(text("0"), "0");
    assert.equal(text(""), "");
    rejectEach(finite, nonNumbers, "finite");
    for (const value of [-3, 0, 0.25, 1e6]) assert.equal(finite(value), value);
    rejectEach(value => list(value, text), [null, undefined, {}, "[]", 1, false, ["ok", 1]], "string list");
    assert.deepEqual(list(["on", "off"], text), ["on", "off"]);
    rejectEach(value => dictionary(value, finite), [null, [], true, "{}", { a: "1" }], "number dictionary");
    assert.deepEqual(dictionary({ a: 0, b: 0.5 }, finite), { a: 0, b: 0.5 });
});

test("minimal maps and omitted known optional node and zone fields remain accepted", () => {
    assert.deepEqual(decodeMap({ nodes: {} }), { nodes: {} });
    assert.deepEqual(decodeMap({ nodes: { a: {} }, zones: { room: {} } }), { nodes: { a: {} }, zones: { room: {} } });
    assert.deepEqual(decodeNode({}), {});
    rejectEach(decodeMap, [{}, { nodes: null }, { nodes: [] }, { nodes: "{}" }, { nodes: { a: null } }], "required nodes");
});

test("map extensions preserve nested JSON values across decoding and ordinary map edits", () => {
    const raw = {
        nodes: {
            a: {
                zone: "room", adjacent: ["b"], position: { x: 2, y: 3 },
                entities: { motion: ["binary_sensor.a", "binary_sensor.a_alias"], interaction: "event.a" },
                extension: { enabled: true, count: 2, absent: null, names: ["on", "00", { threshold: 0.25 }] },
            },
            b: { adjacent: ["a"] },
        },
        zones: { room: { label: "Room", extension: { array: [false, null, "off"] } } },
        floors: ["ground"],
        future_root: { schema: 99, graph: [{ id: "a", metadata: { text: "001" } }] },
    };
    const before = structuredClone(raw);
    const map = decodeMap(freeze(raw));
    assert.deepEqual(map, before);
    moveNode(map.nodes, "a", 4.2, 8.9);
    assert.equal(renameNode(map.nodes, "a", "renamed"), "renamed");
    assert.deepEqual(map.nodes.renamed.position, { x: 4, y: 9 });
    assert.deepEqual(map.nodes.b.adjacent, ["renamed"]);
    assert.deepEqual(map.nodes.renamed.extension, before.nodes.a.extension);
    assert.deepEqual(map.nodes.renamed.entities, before.nodes.a.entities);
    assert.deepEqual(map.zones, before.zones);
    assert.deepEqual(map.future_root, before.future_root);
    assert.deepEqual(raw, before);
});

test("unknown nested node position fields survive decoding and moving a node", () => {
    // Retained even if current point decoding drops metadata: do not weaken the
    // round-trip oracle or fix production from this test-only task.
    const position = { x: 10, y: 20, unit: "px", calibration: { anchor: ["on", null], scale: 1.5 } };
    const map = decodeMap({ nodes: { a: { position } } });
    assert.deepEqual(map.nodes.a.position, position);
    moveNode(map.nodes, "a", 30, 40);
    assert.deepEqual(map.nodes.a.position, { ...position, x: 30, y: 40 });
});

test("unknown nested zone position fields survive decoding", () => {
    const position = { x: -10, y: 20, anchor: { id: "null", enabled: false } };
    const map = decodeMap({ nodes: {}, zones: { room: { position } } });
    assert.deepEqual(map.zones.room.position, position);
});

test("unknown nested zone size fields survive decoding", () => {
    const size = { width: 210, height: 112, unit: "px", constraints: { minimum: [100, 80] } };
    const map = decodeMap({ nodes: {}, zones: { room: { size } } });
    assert.deepEqual(map.zones.room.size, size);
});

test("map JSON extensions reject nonfinite values at every nesting depth", () => {
    for (const invalid of [NaN, Infinity, -Infinity, undefined]) {
        for (const specimen of [
            { nodes: {}, future: invalid },
            { nodes: { a: { future: { nested: [invalid] } } } },
            { nodes: {}, zones: { z: { future: [{ value: invalid }] } } },
            { nodes: { a: { position: { x: 1, y: 2, future: invalid } } } },
        ]) assert.throws(() => decodeMap(specimen), Error);
    }
});

test("coordinates, sizes, reliability and route weights validate their consumed numeric types", () => {
    for (const value of nonNumbers) {
        assert.throws(() => decodeNode({ position: { x: value, y: 0 } }), Error);
        assert.throws(() => decodeNode({ position: { x: 0, y: value } }), Error);
        assert.throws(() => decodeMap({ nodes: {}, zones: { z: { position: { x: value, y: 0 } } } }), Error);
    }
    for (const value of [...nonNumbers, 0, -1]) {
        assert.throws(() => decodeMap({ nodes: {}, zones: { z: { size: { width: value, height: 112 } } } }), Error);
        assert.throws(() => decodeMap({ nodes: {}, zones: { z: { size: { width: 210, height: value } } } }), Error);
        assert.throws(() => decodeNode({ route_prior_weight: value }), Error);
    }
    for (const value of badProbabilities) assert.throws(() => decodeNode({ reliability: value }), Error);
    assert.deepEqual(decodeNode({ position: { x: -2.5, y: 0 }, reliability: 0.75, route_prior_weight: 0.25 }), {
        position: { x: -2.5, y: 0 }, reliability: 0.75, route_prior_weight: 0.25,
    });
    // No tests impose backend-only reliability/profile restrictions on unused fields.
});

test("known map strings and string arrays reject wrong shapes while optional omissions stay valid", () => {
    for (const field of ["label", "zone", "floor", "role", "occupancy_behavior"]) {
        for (const value of [null, true, 1, [], {}]) assert.throws(() => decodeNode({ [field]: value }), Error, field);
    }
    assert.throws(() => decodeNode({ zone: "" }), Error);
    rejectEach(value => decodeNode({ adjacent: value }), [null, "b", {}, [1], [false]], "adjacent");
    rejectEach(value => decodeMap({ nodes: {}, floors: value }), [null, "ground", [1], [null]], "floors");
    rejectEach(value => decodeMap({ nodes: {}, zones: value }), [null, [], "{}", { a: false }], "zones");
    for (const field of ["label", "floor", "role", "occupancy_behavior"]) {
        assert.throws(() => decodeMap({ nodes: {}, zones: { z: { [field]: false } } }), Error);
    }
});

test("entity alias arrays keep order, multiplicity and scalar-versus-array type", () => {
    const aliases = { motion: ["binary_sensor.a", "binary_sensor.a_alias", "binary_sensor.a"], presence: "binary_sensor.presence", interaction: [], future: ["on", "off", "001"] };
    assert.deepEqual(decodeEntitiesMap(aliases), aliases);
    assert.deepEqual(decodeNode({ entities: aliases }).entities, aliases);
    assert.deepEqual(decodeEntitiesMap({}), {});
    assert.deepEqual(decodeEntitiesMap({ motion: ["binary_sensor.a"] }), { motion: ["binary_sensor.a"] });
});

test("entity maps reject scalar roots and non-string or nested alias elements", () => {
    rejectEach(decodeEntitiesMap, [null, undefined, [], "binary_sensor.a", false, { motion: null }, { motion: 1 }, { motion: true }, { motion: ["binary_sensor.a", false] }, { motion: [["binary_sensor.a"]] }, { motion: {} }], "entity aliases");
});

test("configuration accepts supported counts, title and a real entity-id string without inventing defaults", () => {
    for (const expected_occupants of [0, 1, 2]) {
        const raw = configWire({ expected_occupants, title: "on", expected_occupants_entity: "sensor.people" });
        const decoded = decodeConfig(raw);
        assert.deepEqual(decoded, raw);
        assert.doesNotThrow(() => validateSettings(decoded));
    }
    const minimal = decodeConfig(configWire());
    assert.equal(Object.hasOwn(minimal, "title"), false);
    assert.equal(Object.hasOwn(minimal, "expected_occupants_entity"), false);
    assert.equal(decodeConfig(configWire({ expected_occupants_entity: "" })).expected_occupants_entity, "");
});

test("configuration rejects invalid counts, transition windows and known string fields", () => {
    for (const value of [...nonNumbers, -1, 0.5, 3]) assert.throws(() => decodeConfig(configWire({ expected_occupants: value })), Error);
    for (const value of [...nonNumbers, -1, 0, 1.5]) assert.throws(() => decodeConfig(configWire({ transition_window_seconds: value })), Error);
    for (const value of [undefined, null, "", true, 3]) assert.throws(() => decodeConfig(configWire({ entry_id: value })), Error);
    for (const field of ["title", "map_yaml", "expected_occupants_entity"]) {
        for (const value of [null, false, 3, []]) assert.throws(() => decodeConfig(configWire({ [field]: value })), Error);
    }
    assert.throws(() => decodeConfig(configWire({ expected_occupants_entity: "not-an-entity-id" })), Error);
});

test("entity response normalizes live shape and sorting without mutating the input", () => {
    const raw = {
        entities: [
            { entity_id: "binary_sensor.z", name: "Zone", state: "off", device_class: null, unused: { version: 1 } },
            { entity_id: "binary_sensor.a", name: "Alias", state: "on", device_class: "motion" },
            { entity_id: "event.button" },
        ]
    };
    const before = structuredClone(raw);
    assert.deepEqual(normalizeEntityResponse(freeze(raw)), [
        { entity_id: "binary_sensor.a", name: "Alias", state: "on", device_class: "motion" },
        { entity_id: "binary_sensor.z", name: "Zone", state: "off", device_class: null },
        { entity_id: "event.button" },
    ]);
    assert.deepEqual(raw, before);
    assert.deepEqual(normalizeEntityResponse({ entities: [] }), []);
});

test("entity response rejects missing identities and wrong known field types", () => {
    rejectEach(normalizeEntityResponse, [{}, { entities: null }, { entities: "[]" }, { entities: {} }, { entities: [null] }, { entities: [{}] }, { entities: [{ entity_id: "" }] }, { entities: [{ entity_id: 1 }] }], "entity response");
    for (const [field, value] of [["name", false], ["name", null], ["state", true], ["state", 1], ["device_class", 1], ["device_class", []]]) {
        assert.throws(() => normalizeEntityResponse({ entities: [{ entity_id: "binary_sensor.a", [field]: value }] }), Error);
    }
});

test("selected paths accept zero to two slots, nulls, optional historical fields and four visits", () => {
    for (const paths of [[], [null], [null, null], [selected()], [selected(), null], [null, selected()], [selected(), selected({ track_confidence: "confirmed" })]]) {
        assert.deepEqual(decodeSelectedPaths(paths), paths);
    }
    const route = [visit("a"), visit("b"), visit("c"), visit("d")];
    assert.deepEqual(decodeSelectedPaths([selected({ route })])[0].route, route);
    const minimal = decodeSelectedPaths([selected()])[0];
    assert.equal(Object.hasOwn(minimal, "endpoint"), false);
    assert.equal(Object.hasOwn(minimal.route[0], "at"), false);
    assert.equal(Object.hasOwn(minimal.route[0], "kind"), false);
});

test("selected paths reject malformed containers and slot values rather than fabricate unlocated slots", () => {
    rejectEach(decodeSelectedPaths, [undefined, null, false, 0, "[]", {}, [false], [0], ["null"], [{}], [null, null, null]], "selected paths");
    for (const route of [undefined, null, {}, "[]", [], [null], [false], [visit("a"), visit("b"), visit("c"), visit("d"), visit("e")]]) {
        assert.throws(() => decodeSelectedPaths([selected({ route })]), Error);
    }
});

test("selected path booleans and confidence labels are never coerced or upgraded", () => {
    for (const value of badBooleans) {
        assert.throws(() => decodeSelectedPaths([selected({ endpoint_eligible: value })]), Error);
        assert.throws(() => decodeSelectedPaths([selected({ route: [visit("a", { branch_active: value })] })]), Error);
    }
    for (const value of [undefined, null, false, 1, "mature", "Confirmed", "PROVISIONAL", ""]) {
        assert.throws(() => decodeSelectedPaths([selected({ track_confidence: value })]), Error);
    }
    assert.equal(decodeSelectedPaths([selected({ endpoint_eligible: false })])[0].endpoint_eligible, false);
});

test("visit identities, optional timestamps and optional event kinds validate only their actual wire contract", () => {
    for (const field of ["node_id", "zone", "episode_id"]) {
        for (const value of [undefined, null, "", false, 1, []]) {
            assert.throws(() => decodeSelectedPaths([selected({ route: [visit("a", { [field]: value })] })]), Error);
        }
    }
    for (const value of [null, 1, false, "", "not-a-date"]) {
        assert.throws(() => decodeSelectedPaths([selected({ route: [visit("a", { at: value })] })]), Error);
    }
    for (const value of [null, false, 1, "on", "timer", "Positive"]) {
        assert.throws(() => decodeSelectedPaths([selected({ route: [visit("a", { kind: value })] })]), Error);
    }
    for (const kind of ["positive", "correlated_positive", "interaction"]) {
        const occurrence = visit("a", { kind, at: "2026-09-15T17:24:15.791089+00:00" });
        assert.deepEqual(decodeSelectedPaths([selected({ route: [occurrence] })])[0].route, [occurrence]);
    }
});

test("revisiting a physical node with a new generation is valid, repeating an episode identity is not", () => {
    const route = [visit("a"), visit("b"), visit("a", { episode_id: "a:2" })];
    assert.deepEqual(decodeSelectedPaths([selected({ route })])[0].route, route);
    for (const duplicate of [visit("a"), visit("c", { episode_id: "a:1" })]) {
        assert.throws(() => decodeSelectedPaths([selected({ route: [visit("a"), duplicate] })]), /bounded selected route/);
    }
});

test("a supplied endpoint must agree with the last route occurrence without requiring unused metadata", () => {
    const endpoint = visit("b");
    assert.deepEqual(decodeSelectedPaths([selected({ endpoint })])[0].endpoint, endpoint);
    for (const override of [{ node_id: "a" }, { zone: "other" }, { episode_id: "b:2" }, { branch_active: false }]) {
        assert.throws(() => decodeSelectedPaths([selected({ endpoint: { ...endpoint, ...override } })]), /endpoint disagrees/);
    }
    for (const value of [null, false, "b", [], {}]) assert.throws(() => decodeSelectedPaths([selected({ endpoint: value })]), Error);
});

test("malformed selected data is an explicit recoverable diagnostic error, not absent/empty authoritative data", () => {
    for (const invalid of [undefined, null, {}, "[]", [selected({ endpoint_eligible: "false" })]]) {
        const result = decodeDiagnostics({ model: "zone_belief", selected_paths: invalid, beliefs: { za: 0.5 }, policy: { za: { active: false } } });
        assert.equal(typeof result.selected_paths_error, "string");
        assert.ok(result.selected_paths_error.length > 0);
        assert.equal(Object.hasOwn(result, "selected_paths"), false);
        assert.deepEqual(result.beliefs, { za: 0.5 });
        assert.deepEqual(result.policy, { za: { active: false } });
    }
    assert.deepEqual(decodeDiagnostics({}), {});
    assert.deepEqual(decodeDiagnostics({ selected_paths: [] }), { selected_paths: [] });
    assert.deepEqual(decodeDiagnostics({ selected_paths: [null] }), { selected_paths: [null] });
});

test("full current status shapes separate episodes, physical health, policy and selected endpoint coverage", () => {
    const route = [visit("a", { at: "2026-09-15T17:24:15Z", kind: "positive" }), visit("b", { branch_active: false })];
    const raw = {
        expected_occupants: 1,
        zone_states: { za: { confidence: 0.8, status: "active", occupancy_behavior: "sustained", last_node_id: "a", reason: "local_positive", explanation: {} } },
        transition_counts: { a: { b: 2.5 } },
        authoritative_count: { source: "sensor.people", accepted: 1, available: true },
        occupancy_diagnostics: {
            model: "zone_belief", expected_occupants: 1, requested_occupants: 1, unsupported_count: false,
            selected_paths: [selected({ route, endpoint: route[1], covered_node_ids: ["a", "b"], covered_zones: ["za", "zb"], eligible_node_ids: ["a", "b"] })],
            episodes: [{ node_id: "a", zone: "za", episode_id: "a:1", status: "asserted", reliability: 0.75, profile: "stay_presence" }],
            path_health: [{ node_id: "a", zone: "za", phase: "on", on_since: "2026-09-15T17:24:15Z", coverage_lost_at: null }],
            beliefs: { za: 0.8 }, policy: { za: { active: true, profile: "stay_presence", pending_release_since: null, phase: "active" } },
            reliability_warnings: [warningWire({ active_reasons: ["assertion_timeout"], first_observed_at: "2026-09-15T17:34:15Z", last_observed_at: "2026-09-15T17:34:15Z", cleared_at: null })],
            processing: { token_count: 2, ignored_extension: 40 },
        },
    };
    const result = decodeStatus(freeze(raw));
    assert.equal(result.expected_occupants, 1);
    assert.deepEqual(result.transition_counts, { a: { b: 2.5 } });
    assert.equal(result.zone_states.za.confidence, 0.8);
    assert.deepEqual(result.occupancy_diagnostics.selected_paths[0].route, route);
    assert.deepEqual(result.occupancy_diagnostics.path_health, [{ node_id: "a", zone: "za", phase: "on" }]);
    assert.equal(result.occupancy_diagnostics.episodes[0].episode_id, "a:1");
    assert.equal(Object.hasOwn(result.occupancy_diagnostics.path_health[0], "episode_id"), false);
    assert.equal(result.occupancy_diagnostics.policy.za.active, true);
    assert.deepEqual(result.occupancy_diagnostics.processing, { token_count: 2 });
});

test("partial historical status fixtures retain known optional fields and do not require unused backend details", () => {
    const raw = {
        zone_states: { za: {}, zb: { last_node_id: null } },
        occupancy_diagnostics: {
            episodes: [{ node_id: "a" }, { node_id: "b", episode_id: null }],
            policy: { za: { active: false } },
            policy_audit: [{}, { traversal_reason: null, event_kind: null }],
            traversal_frontier: [{ token_id: "t" }],
            authorizations: [{ authorized: false }],
            reliability_warnings: [{ node_id: "a", zone: "za", kind: "suspected_stuck", active: false }],
            processing: {},
        },
    };
    assert.deepEqual(decodeStatus(raw), raw);
    assert.deepEqual(decodeStatus({ future: { nested: true } }), {});
    assert.deepEqual(decodeDiagnostics({ future: [null, { text: "on" }] }), {});
});

test("status numeric fields reject null, coercible primitives and nonfinite values", () => {
    for (const value of nonNumbers) {
        for (const raw of [
            { expected_occupants: value },
            { transition_counts: { a: { b: value } } },
            { occupancy_diagnostics: { expected_occupants: value } },
            { occupancy_diagnostics: { processing: { token_count: value } } },
        ]) assert.throws(() => decodeStatus(raw), Error);
    }
    // Finite unsupported/mismatched snapshot counts are preserved for the
    // projection's explicit unavailable state; the decoder must not clamp them.
    for (const count of [-1, 0, 0.5, 1, 2, 3]) {
        assert.equal(decodeStatus({ expected_occupants: count }).expected_occupants, count);
        assert.equal(decodeDiagnostics({ expected_occupants: count }).expected_occupants, count);
    }
});

test("all consumed probability surfaces reject nonfinite and out-of-range values", () => {
    for (const value of badProbabilities) {
        assert.throws(() => decodeStatus({ zone_states: { za: { confidence: value } } }), Error);
        assert.throws(() => decodeDiagnostics({ beliefs: { za: value } }), Error);
        assert.throws(() => decodeDiagnostics({ policy_audit: [{ belief_after: value }] }), Error);
    }
    for (const value of [0, 0.125, 1]) {
        assert.equal(decodeStatus({ zone_states: { za: { confidence: value } } }).zone_states.za.confidence, value);
        assert.equal(decodeDiagnostics({ beliefs: { za: value } }).beliefs.za, value);
        assert.equal(decodeDiagnostics({ policy_audit: [{ belief_after: value }] }).policy_audit[0].belief_after, value);
    }
});

test("policy, warning, audit and authorization Boolean fields reject strings and numbers", () => {
    for (const value of badBooleans) {
        for (const raw of [
            { unsupported_count: value }, { policy: { za: { active: value } } },
            { reliability_warnings: [warningWire({ active: value })] },
            { policy_audit: [{ active_before: value }] }, { policy_audit: [{ active_after: value }] },
            { authorizations: [{ authorized: value }] },
        ]) assert.throws(() => decodeDiagnostics(raw), Error);
    }
});

test("diagnostic collections and status dictionaries reject wrong container shapes", () => {
    for (const field of ["episodes", "path_health", "policy_audit", "reliability_warnings", "health_warnings", "traversal_frontier", "authorizations"]) {
        for (const value of [null, {}, false, 1, "[]"]) assert.throws(() => decodeDiagnostics({ [field]: value }), Error, field);
    }
    for (const field of ["beliefs", "policy", "processing"]) {
        for (const value of [null, [], false, "{}"]) assert.throws(() => decodeDiagnostics({ [field]: value }), Error, field);
    }
    for (const field of ["zone_states", "transition_counts", "occupancy_diagnostics"]) {
        for (const value of [null, [], false, "{}"]) assert.throws(() => decodeStatus({ [field]: value }), Error, field);
    }
    assert.throws(() => decodeStatus({ transition_counts: { a: [1] } }), Error);
    assert.throws(() => decodeStatus({ zone_states: { a: null } }), Error);
});

test("physical health validates real phases and identity without inventing an episode id", () => {
    for (const phase of ["on", "off", "unknown", "clearing"]) {
        const expected = { node_id: "a", zone: "za", phase };
        assert.deepEqual(decodeDiagnostics({ path_health: [expected] }).path_health, [expected]);
    }
    for (const phase of [null, true, 1, "ON", "unavailable", "asserted", ""]) {
        assert.throws(() => decodeDiagnostics({ path_health: [{ node_id: "a", zone: "za", phase }] }), Error);
    }
    for (const row of [{ zone: "za", phase: "on" }, { node_id: "a", phase: "on" }, { node_id: "", zone: "za", phase: "on" }]) {
        assert.throws(() => decodeDiagnostics({ path_health: [row] }), Error);
    }
});

test("episodes preserve partial nullable generations but reject wrong known types", () => {
    assert.deepEqual(decodeDiagnostics({ episodes: [{ node_id: "a", episode_id: null, status: "unavailable" }] }).episodes, [{ node_id: "a", episode_id: null, status: "unavailable" }]);
    for (const row of [null, {}, { node_id: 1 }, { node_id: "" }, { node_id: "a", zone: false }, { node_id: "a", episode_id: 1 }, { node_id: "a", status: true }]) {
        assert.throws(() => decodeDiagnostics({ episodes: [row] }), Error);
    }
    const duplicate = { node_id: "a", zone: "za", episode_id: "a:1" };
    assert.deepEqual(decodeDiagnostics({ episodes: [duplicate, duplicate] }).episodes, [duplicate, duplicate]);
    // Duplicate identities are deliberately passed to the projector's unjoinable
    // index, not silently deduplicated into an authoritative current episode.
});

test("warnings accept legacy omitted reasons and nullable time, but reject malformed reason arrays", () => {
    const old = warningWire({ last_observed_at: null });
    delete old.reasons;
    assert.deepEqual(decodedWarning(old), old);
    for (const reasons of [null, "assertion_timeout", false, {}, [1], [true], [["assertion_timeout"]]]) {
        assert.throws(() => decodedWarning(warningWire({ reasons })), Error);
    }
    for (const [field, value] of [["node_id", ""], ["zone", null], ["kind", true], ["last_observed_at", 1]]) {
        assert.throws(() => decodedWarning(warningWire({ [field]: value })), Error);
    }
});

test("known optional text and string-list fields remain strict without validating unused metadata", () => {
    for (const raw of [
        { model: false }, { health_warnings: [false] }, { policy: { za: { active: false, profile: 1 } } },
        { policy: { za: { active: true, pending_release_since: 1 } } },
        { policy_audit: [{ evidence_ids: "a" }] }, { policy_audit: [{ evidence_ids: [1] }] },
        { policy_audit: [{ event_at: false }] }, { policy_audit: [{ zone: 1 }] },
        { policy_audit: [{ traversal_reason: true }] }, { policy_audit: [{ event_kind: 1 }] },
        { policy_audit: [{ reason: null }] },
        { traversal_frontier: [{ token_id: "t", valid_until: false }] },
        { traversal_frontier: [{ token_id: "t", zone: 1 }] },
        { authorizations: [{ authorized: true, source_token_ids: "t" }] },
        { authorizations: [{ authorized: true, source_token_ids: [1] }] },
        { authorizations: [{ authorized: true, target_zone: false }] },
        { authorizations: [{ authorized: true, reason: null }] },
    ]) assert.throws(() => decodeDiagnostics(raw), Error);
    for (const field of ["status", "reason", "occupancy_behavior", "last_node_id"]) {
        assert.throws(() => decodeStatus({ zone_states: { za: { [field]: 1 } } }), Error);
    }
    const raw = { policy_audit: [{ event_kind: null, traversal_reason: null, future_details: { data: "ignored" } }] };
    assert.deepEqual(decodeDiagnostics(raw).policy_audit, [{ event_kind: null, traversal_reason: null }]);
});

test("cleanup uses the requested response counter and rejects invalid counts without coercion", () => {
    for (const count of [0, 1, 100]) {
        assert.equal(decodeCleanup({ stale_count: count, removed_count: 999 }, true), count);
        assert.equal(decodeCleanup({ stale_count: 999, removed_count: count }, false), count);
    }
    for (const count of [...nonNumbers, -1, 0.5]) {
        assert.throws(() => decodeCleanup({ stale_count: count }, true), Error);
        assert.throws(() => decodeCleanup({ removed_count: count }, false), Error);
    }
    assert.throws(() => decodeCleanup({ removed_count: 2 }, true), Error);
    assert.throws(() => decodeCleanup({ stale_count: 2 }, false), Error);
    rejectEach(value => decodeCleanup(value, true), nonRecords, "cleanup response");
});

test("decoding selected and status specimens never mutates or silently normalizes source data", () => {
    const raw = {
        expected_occupants: 1, occupancy_diagnostics: {
            selected_paths: [selected()], episodes: [{ node_id: "a", zone: "za", episode_id: "a:1" }],
            reliability_warnings: [warningWire()], beliefs: { za: 0.75 },
        }
    };
    const before = structuredClone(raw);
    const decoded = decodeStatus(freeze(raw));
    decoded.occupancy_diagnostics.selected_paths[0].route[0].node_id = "changed";
    decoded.occupancy_diagnostics.reliability_warnings[0].reasons.push("another-reason");
    assert.deepEqual(raw, before);
});

test("exact timeout-only warning wording applies equally to active and cleared rows", () => {
    for (const active of [false, true]) {
        const warning = decodedWarning(warningWire({ active }));
        assert.equal(warningLabel(warning), "Continuous presence detected; path unverified");
        assert.equal(warning.kind, "suspected_stuck");
        assert.deepEqual(warning.reasons, ["assertion_timeout"]);
    }
});

test("mixed, count-conflict, empty, missing and duplicate reasons never receive the timeout-only label", () => {
    for (const reasons of [["count_conflict"], ["assertion_timeout", "count_conflict"], ["count_conflict", "assertion_timeout"], ["assertion_timeout", "assertion_timeout"], []]) {
        assert.equal(warningLabel(decodedWarning(warningWire({ reasons }))), "Suspected Stuck", JSON.stringify(reasons));
    }
    const legacy = warningWire();
    delete legacy.reasons;
    assert.equal(warningLabel(decodedWarning(legacy)), "Suspected Stuck");
});

test("warning matching is exact and case-sensitive, not substring or normalized text matching", () => {
    for (const reasons of [["Assertion_timeout"], ["ASSERTION_TIMEOUT"], ["assertion_timeout "], [" assertion_timeout"], ["assertion_timeout_extra"]]) {
        assert.equal(warningLabel(decodedWarning(warningWire({ reasons }))), "Suspected Stuck");
    }
    for (const [kind, expected] of [["Suspected_Stuck", "Suspected Stuck"], ["SUSPECTED_STUCK", "SUSPECTED STUCK"], ["unsupported_jump", "Unsupported Jump"], ["impossible_cadence", "Impossible Cadence"], ["suspected_stuck_extra", "Suspected Stuck Extra"]]) {
        assert.equal(warningLabel(decodedWarning(warningWire({ kind }))), expected);
    }
});

test("warning label uses the entire reasons list, not the narrower active_reasons extension", () => {
    const warning = decodedWarning(warningWire({ reasons: ["assertion_timeout", "count_conflict"], active_reasons: ["assertion_timeout"] }));
    assert.equal(warningLabel(warning), "Suspected Stuck");
});

test("percentage formatting distinguishes unavailable values from a real zero probability", () => {
    for (const [value, expected] of [[undefined, "unavailable"], [NaN, "unavailable"], [Infinity, "unavailable"], [-0.1, "unavailable"], [1.1, "unavailable"], [0, "0%"], [0.125, "13%"], [0.8, "80%"], [1, "100%"]]) {
        assert.equal(formatPercent(value), expected);
    }
});

test("escaping protects user and server strings including quotes in attributes", () => {
    assert.equal(escapeHtml('<script title="x" data-q=\'y\'>&'), "&lt;script title=&quot;x&quot; data-q=&#39;y&#39;&gt;&amp;");
    assert.equal(escapeHtml("&lt;"), "&amp;lt;");
    assert.equal(escapeHtml(null), "");
    assert.equal(escapeHtml(undefined), "");
});

test("audit formatting preserves real edges and missing historical fields rather than infer truthiness", () => {
    const rows = decodeDiagnostics({
        policy_audit: [
            { active_before: false, active_after: true, reason: "acquired", belief_after: 0.8, traversal_reason: "track_confirmed" },
            { active_before: true, active_after: false },
            { active_before: false, active_after: false, reason: "acquisition_unauthorized" },
            {}, { event_kind: "positive" },
        ]
    }).policy_audit;
    assert.deepEqual(rows.map(auditTransition), [[false, true], [true, false], [false, false], [false, false], [false, false]]);
    assert.deepEqual(rows.map(auditKind), ["edges", "edges", "rejected", "observations", "other"]);
    assert.equal(decisionExplanation(rows[0]), "Acquired at 80% via Track Confirmed");
    assert.equal(decisionExplanation(rows[3]), "Policy Observation at unavailable");
});
