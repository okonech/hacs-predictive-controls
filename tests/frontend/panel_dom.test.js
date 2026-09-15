import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { setImmediate as nextTurn } from "node:timers/promises";
import { JSDOM, VirtualConsole } from "jsdom";
import { parse, stringify } from "yaml";

// Exercise the shipped classic bundle, not imported components or an HTMLElement
// fake. Wire fixtures follow websocket.py and the fields consumed by decoders.ts.
// These are synthetic UI contracts from strict-modular-panel.md, not live incidents.
const bundle = readFileSync(new URL(
    "../../custom_components/predictive_controls/frontend/panel-v0.2.6.js",
    import.meta.url,
), "utf8");
const tag = "predictive-controls-panel";
const type = name => `predictive_controls/${name}`;
const clone = value => structuredClone(value);
const flush = () => nextTurn();

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}

function mapWire() {
    const adjacent = { a: ["b"], b: ["a", "c"], c: ["b", "d"], d: ["c", "e"], e: ["d"] };
    return {
        floors: ["ground"],
        future_root: { flags: [true, null, "off"], version: 7 },
        zones: Object.fromEntries([...Object.keys(adjacent), "empty"].map((id, index) => [id, {
            label: `Zone ${id.toUpperCase()}`, floor: "ground",
            position: { x: 80 + index * 260, y: 80 }, size: { width: 210, height: 112 },
        }])),
        nodes: Object.fromEntries(Object.entries(adjacent).map(([id, links], index) => [id, {
            label: `Sensor ${id.toUpperCase()}`, zone: id, floor: "ground",
            role: "room_occupancy", occupancy_behavior: "sustained",
            entities: { motion: `binary_sensor.${id}` }, adjacent: links,
            position: { x: 80 + index * 260, y: 80, unit: "px" },
            reliability: 0.8, route_prior_weight: 1,
            future_node: { literal: "null", aliases: ["on", "001"] },
        }])),
    };
}

function configWire(overrides = {}) {
    const map = overrides.map ?? mapWire();
    return {
        entry_id: "entry-dom", title: "DOM fixture", map,
        map_yaml: stringify(map, { compat: "yaml-1.1" }),
        transition_window_seconds: 15, expected_occupants: 1,
        expected_occupants_entity: "sensor.people", ...overrides,
    };
}

function entitiesWire() {
    return {
        entities: [
            { entity_id: "binary_sensor.spare", name: "Spare Motion", device_class: "motion", state: "off" },
            { entity_id: "binary_sensor.presence", name: "Desk Presence", device_class: "occupancy", state: "on" },
            { entity_id: "event.button", name: "Wall Button", device_class: null, state: "unknown" },
        ]
    };
}

function visit(id, overrides = {}) {
    return { node_id: id, zone: id, episode_id: `${id}:1`, branch_active: true, ...overrides };
}

function pathWire(route = [visit("a"), visit("b"), visit("c")], overrides = {}) {
    return { route, endpoint: clone(route.at(-1)), track_confidence: "provisional", endpoint_eligible: true, ...overrides };
}

function statusWire(overrides = {}) {
    const ids = ["a", "b", "c", "d", "e"];
    const count = overrides.expected_occupants ?? 1;
    return {
        expected_occupants: count,
        zone_states: Object.fromEntries(ids.map(id => [id, {
            confidence: 0.8, status: "possible", reason: "fixture observation",
            occupancy_behavior: "sustained", last_node_id: id,
        }])),
        transition_counts: { a: { b: 7 }, b: { c: 3 } },
        ...overrides,
        occupancy_diagnostics: {
            model: "zone_belief", expected_occupants: count, unsupported_count: null,
            beliefs: Object.fromEntries(ids.map(id => [id, id === "e" ? 0.99 : 0.8])),
            // Presence styling must not depend on the policy being active.
            policy: Object.fromEntries(ids.map(id => [id, { active: id === "c", profile: "stay_presence" }])),
            episodes: ids.map(id => ({ node_id: id, zone: id, episode_id: `${id}:1`, status: "asserted" })),
            path_health: ids.map(id => ({ node_id: id, zone: id, phase: "on" })),
            selected_paths: count === 0 ? [] : count === 2 ? [pathWire(), null] : [pathWire()],
            reliability_warnings: [], policy_audit: [], processing: { token_count: 0 },
            ...overrides.occupancy_diagnostics,
        },
    };
}

function warningWire(overrides = {}) {
    return {
        node_id: "a", zone: "a", kind: "suspected_stuck", active: true,
        reasons: ["assertion_timeout"], last_observed_at: "2026-09-15T17:34:15Z", ...overrides,
    };
}

function saveResponse(message) {
    return configWire({
        entry_id: message.entry_id,
        map: message.map_yaml_dirty ? parse(message.map_yaml, { version: "1.1" }) : clone(message.map),
        map_yaml: message.map_yaml,
        transition_window_seconds: message.transition_window_seconds,
        expected_occupants: message.expected_occupants,
        expected_occupants_entity: message.expected_occupants_entity,
    });
}

function harness(t, options = {}) {
    const browserErrors = [];
    const console = new VirtualConsole();
    console.on("jsdomError", error => browserErrors.push(error.message));
    const dom = new JSDOM("<!doctype html><html><body></body></html>", {
        url: "https://panel.test/", runScripts: "dangerously", pretendToBeVisual: true,
        virtualConsole: console,
    });
    const { window } = dom;
    t.after(() => {
        window.close();
        assert.deepEqual(browserErrors, [], "bundle must not throw uncaught DOM errors");
    });

    // Install before evaluation. No real interval, timeout, animation tick or sleep
    // is needed to control the host; timeout callbacks are fired explicitly below.
    let timerId = 0;
    const intervals = new Map();
    const timeouts = new Map();
    const intervalStarts = [];
    const intervalClears = [];
    window.setInterval = (callback, milliseconds) => {
        const id = ++timerId;
        intervals.set(id, { callback, milliseconds });
        intervalStarts.push(id);
        return id;
    };
    window.clearInterval = id => { intervalClears.push(id); intervals.delete(id); };
    window.setTimeout = (callback, milliseconds) => {
        const id = ++timerId;
        timeouts.set(id, { callback, milliseconds });
        return id;
    };
    window.clearTimeout = id => { timeouts.delete(id); };
    const confirmations = [];
    window.confirm = text => { confirmations.push(text); return options.confirm ?? true; };
    window.eval(bundle);

    const requests = [];
    const queues = new Map(Object.entries(options.queues ?? {}).map(([name, queue]) => [name, [...queue]]));
    const server = {
        config: clone(options.config ?? configWire()),
        entities: clone(options.entities ?? entitiesWire()),
        status: clone(options.status ?? statusWire()),
        stale: 2,
    };
    const hass = {
        async callWS(message) {
            // Normalize cross-realm prototypes only at the assertion/capture boundary.
            const captured = clone(message);
            requests.push(captured);
            const name = captured.type.replace("predictive_controls/", "");
            const queue = queues.get(name);
            if (queue?.length) return queue.shift()(captured);
            if (name === "config" || name === "entities" || name === "status") return clone(server[name]);
            if (name === "save_config") {
                const result = saveResponse(captured);
                server.config = clone(result);
                return result;
            }
            if (name === "cleanup_entities") {
                return captured.dry_run ? { stale_count: server.stale } : { removed_count: server.stale };
            }
            throw new Error(`Unexpected request ${captured.type}`);
        },
    };
    const panel = window.document.createElement(tag);
    panel.hass = hass;
    window.document.body.append(panel);
    const h = {
        dom, window, panel, hass, server, requests, confirmations,
        intervals, timeouts, intervalStarts, intervalClears,
        enqueue(name, action) {
            const queue = queues.get(name) ?? [];
            queue.push(action); queues.set(name, queue);
        },
        calls(name) { return requests.filter(message => message.type === type(name)); },
        $(selector) {
            const element = panel.querySelector(selector);
            assert.ok(element, `Expected DOM control: ${selector}`);
            return element;
        },
        click(selector) { h.$(selector).click(); },
        async tab(name) { h.click(`[data-tab="${name}"]`); await flush(); },
        edit(selector, value, event = "change") {
            const element = h.$(selector);
            element.value = value;
            element.dispatchEvent(new window.Event(event, { bubbles: true }));
            return element;
        },
        async save() { h.click('[data-action="save"]'); await flush(); return h.calls("save_config").at(-1); },
        fireTimeout(id) {
            const timer = timeouts.get(id);
            assert.ok(timer, "request timeout must be registered");
            timeouts.delete(id); timer.callback();
        },
    };
    return h;
}

async function ready(t, options) {
    const h = harness(t, options);
    await flush();
    assert.equal(h.panel.querySelectorAll("[data-tab]").length, 6, "initial wire load must finish");
    return h;
}

function dataTransfer(initial = {}) {
    const data = new Map(Object.entries(initial));
    return {
        effectAllowed: "none",
        get types() { return [...data.keys()]; },
        clearData(key) { if (key === undefined) data.clear(); else data.delete(key); },
        setData(key, value) { data.set(key, value); },
        getData(key) { return data.get(key) ?? ""; },
    };
}

function drag(h, target, name, transfer, clientX = 350, clientY = 480) {
    // jsdom 26 has no DragEvent/DataTransfer implementation. Keep real DOM event
    // dispatch and precisely the browser fields consumed by the production binder.
    const event = new h.window.Event(name, { bubbles: true, cancelable: true });
    Object.defineProperties(event, {
        dataTransfer: { value: transfer }, clientX: { value: clientX }, clientY: { value: clientY },
    });
    target.dispatchEvent(event);
    return event;
}

function geometry(h) {
    const board = h.$("[data-board]");
    board.getBoundingClientRect = () => new h.window.DOMRect(100, 200, 1000, 800);
    Object.defineProperties(board, { clientLeft: { value: 4 }, clientTop: { value: 6 } });
    board.scrollLeft = 35; board.scrollTop = 57;
    return board;
}

function assertNoInjectedMarkup(h) {
    assert.equal(h.panel.querySelector("script,img,iframe,[onerror],[onload],[onmouseover]"), null);
    assert.equal(h.window.__panel_xss, undefined);
}

test("initial load uses exact no-entry contracts and all six labeled tabs remain usable", async t => {
    const h = await ready(t);
    assert.deepEqual(h.requests, [
        { type: type("config") }, { type: type("entities") }, { type: type("status") },
    ]);
    assert.deepEqual([...h.panel.querySelectorAll("[data-tab]")].map(el => el.textContent),
        ["Occupancy", "Reliability", "Activity", "Map", "YAML", "Settings"]);
    for (const [name, selector] of [
        ["reliability", ".reliability-layout"], ["activity", ".activity-layout"],
        ["map", ".map-layout"], ["yaml", "[data-map-yaml]"],
        ["settings", ".settings"], ["occupancy", ".occupancy-layout"],
    ]) {
        await h.tab(name);
        assert.ok(h.$(selector));
        assert.equal(h.$(`[data-tab="${name}"]`).getAttribute("aria-pressed"), "true");
    }
    assert.equal(h.calls("status").length, 4);
    for (const message of h.calls("status").slice(1)) {
        assert.deepEqual(message, { type: type("status"), entry_id: "entry-dom" });
    }
    assert.equal(h.calls("save_config").length, 0);
});

test("Map Add Node, selection, rename, label and delete use real controls", async t => {
    const h = await ready(t);
    await h.tab("map");
    assert.equal(h.$('[data-action="delete"]').disabled, true);
    h.click('[data-action="add-empty"]');
    assert.equal(h.$('[data-field="node_id"]').value, "node");
    h.edit('[data-field="node_id"]', "new_room");
    h.edit('[data-field="label"]', "New room sensor");
    assert.equal(h.$('[data-node="new_room"] strong').textContent, "New room sensor");
    h.click('[data-node="a"]');
    assert.equal(h.$('[data-field="node_id"]').value, "a");
    h.click('[data-node="new_room"]');
    assert.equal(h.$('[data-node="new_room"]').getAttribute("aria-pressed"), "true");
    h.click('[data-action="delete"]');
    assert.equal(h.panel.querySelector('[data-node="new_room"]'), null);
    assert.equal(h.$('[data-action="delete"]').disabled, true);
    const request = await h.save();
    assert.deepEqual(Object.keys(request.map.nodes).sort(), ["a", "b", "c", "d", "e"]);
});

test("renaming then deleting an existing node rewrites and removes inbound references", async t => {
    const h = await ready(t);
    await h.tab("map");
    h.click('[data-node="b"]');
    h.edit('[data-field="node_id"]', "renamed_b");
    const renamed = await h.save();
    assert.equal(Object.hasOwn(renamed.map.nodes, "b"), false);
    assert.deepEqual(renamed.map.nodes.a.adjacent, ["renamed_b"]);
    assert.deepEqual(renamed.map.nodes.c.adjacent, ["renamed_b", "d"]);
    h.click('[data-node="renamed_b"]');
    h.click('[data-action="delete"]');
    const deleted = await h.save();
    assert.equal(Object.hasOwn(deleted.map.nodes, "renamed_b"), false);
    assert.deepEqual(deleted.map.nodes.a.adjacent, []);
    assert.deepEqual(deleted.map.nodes.c.adjacent, ["d"]);
});

test("Connect and inspector remove-edge round-trip both directions without duplicate lines", async t => {
    const h = await ready(t);
    await h.tab("map");
    h.click('[data-node="a"]');
    h.click('[data-action="connect"]');
    assert.equal(h.$('[data-action="connect"]').getAttribute("aria-pressed"), "true");
    h.click('[data-node="c"]');
    assert.equal(h.$('[data-action="connect"]').getAttribute("aria-pressed"), "false");
    assert.equal(h.panel.querySelectorAll(".edges line").length, 5);
    const connected = await h.save();
    assert.deepEqual(connected.map.nodes.a.adjacent, ["b", "c"]);
    assert.deepEqual(connected.map.nodes.c.adjacent, ["b", "d", "a"]);
    h.click('[data-node="c"]');
    h.click('[data-remove-adjacent="a"]');
    assert.equal(h.panel.querySelectorAll(".edges line").length, 4);
    const removed = await h.save();
    assert.deepEqual(removed.map.nodes.a.adjacent, ["b"]);
    assert.deepEqual(removed.map.nodes.c.adjacent, ["b", "d"]);
});

test("inspector coordinates and scalar fields save without losing unknown extensions", async t => {
    const h = await ready(t);
    const original = clone(h.server.config.map);
    await h.tab("map");
    h.click('[data-node="a"]');
    for (const [field, value] of Object.entries({
        x: "191", y: "303", zone: "empty", floor: "upstairs", role: "anchor_sensor",
        occupancy_behavior: "sticky", reliability: "0.75", route_prior_weight: "2.5",
    })) h.edit(`[data-field="${field}"]`, value);
    assert.equal(h.$('[data-node="a"]').style.left, "191px");
    assert.equal(h.$('[data-node="a"]').style.top, "303px");
    const message = await h.save();
    assert.deepEqual(message.map.nodes.a.position, { x: 191, y: 303, unit: "px" });
    assert.equal(message.map.nodes.a.zone, "empty");
    assert.equal(message.map.nodes.a.floor, "upstairs");
    assert.equal(message.map.nodes.a.role, "anchor_sensor");
    assert.equal(message.map.nodes.a.occupancy_behavior, "sticky");
    assert.equal(message.map.nodes.a.reliability, 0.75);
    assert.equal(message.map.nodes.a.route_prior_weight, 2.5);
    assert.deepEqual(message.map.future_root, original.future_root);
    assert.deepEqual(message.map.nodes.a.future_node, original.nodes.a.future_node);
    assert.deepEqual(message.map.zones, original.zones);
});

test("inspector entity alias arrays retain scalar versus array types through YAML and save", async t => {
    const config = configWire();
    const aliases = { motion: ["binary_sensor.a", "binary_sensor.alias"], interaction: "event.button", future: ["on", "null", "001"] };
    config.map.nodes.a.entities = clone(aliases);
    const h = await ready(t, { config });
    await h.tab("map"); h.click('[data-node="a"]');
    assert.deepEqual(parse(h.$('[data-field="entities"]').value, { version: "1.1" }), aliases);
    const next = { ...aliases, motion: [...aliases.motion, "binary_sensor.third"], empty: [] };
    h.edit('[data-field="entities"]', stringify(next, { compat: "yaml-1.1", collectionStyle: "flow" }));
    await h.tab("yaml");
    assert.deepEqual(parse(h.$("[data-map-yaml]").value, { version: "1.1" }).nodes.a.entities, next);
    const message = await h.save();
    assert.equal(message.map_yaml_dirty, false);
    assert.deepEqual(message.map.nodes.a.entities, next);
    await h.tab("map"); h.click('[data-node="a"]');
    assert.deepEqual(parse(h.$('[data-field="entities"]').value, { version: "1.1" }), next);
});

test("entity filter and native keyboard-style Add to Map activation preserve filter and unique IDs", async t => {
    const h = await ready(t);
    await h.tab("map");
    const filter = h.edit("[data-filter]", "SPARE", "input");
    assert.equal(h.$('[data-entity="binary_sensor.spare"]').hidden, false);
    assert.equal(h.$('[data-entity="binary_sensor.presence"]').hidden, true);
    assert.equal(h.$("[data-filter]"), filter);
    const button = h.$('[data-add-entity="binary_sensor.spare"]');
    assert.ok(button instanceof h.window.HTMLButtonElement);
    assert.equal(button.type, "button");
    assert.equal(button.getAttribute("aria-label"), "Add Spare Motion to map");
    button.focus();
    assert.equal(h.window.document.activeElement, button);
    // jsdom does not implement the UA's Enter-to-click default action. Dispatch
    // its keyboard activation click (detail=0) explicitly, not a fake key handler.
    button.dispatchEvent(new h.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    button.dispatchEvent(new h.window.KeyboardEvent("keyup", { key: "Enter", bubbles: true }));
    button.dispatchEvent(new h.window.MouseEvent("click", { bubbles: true, detail: 0 }));
    assert.equal(h.$('[data-field="node_id"]').value, "spare");
    assert.equal(h.$("[data-filter]").value, "SPARE");
    h.click('[data-add-entity="binary_sensor.spare"]');
    assert.equal(h.$('[data-field="node_id"]').value, "spare_2");
    const message = await h.save();
    for (const id of ["spare", "spare_2"]) {
        assert.deepEqual(message.map.nodes[id].entities, { motion: "binary_sensor.spare" });
        assert.deepEqual(message.map.nodes[id].position, { x: 80, y: 80 });
    }
});

test("entity dragstart and drop account exactly for board borders, scroll and anchor offsets", async t => {
    const h = await ready(t); await h.tab("map");
    const transfer = dataTransfer({ node_id: "obsolete" });
    drag(h, h.$('[data-entity="binary_sensor.spare"]'), "dragstart", transfer);
    assert.deepEqual(transfer.types, ["entity_id"]);
    assert.equal(transfer.getData("entity_id"), "binary_sensor.spare");
    assert.equal(transfer.effectAllowed, "copy");
    const board = geometry(h);
    assert.equal(drag(h, board, "dragover", transfer).defaultPrevented, true);
    assert.equal(drag(h, board, "drop", transfer).defaultPrevented, true);
    // x=350-100-4+35-90; y=480-200-6+57-28.
    assert.equal(h.$('[data-node="spare"]').style.left, "191px");
    assert.equal(h.$('[data-node="spare"]').style.top, "303px");
    const message = await h.save();
    assert.deepEqual(message.map.nodes.spare.position, { x: 191, y: 303 });
});

test("node dragstart clears entity identity and drop moves only that node with clamping", async t => {
    const h = await ready(t); await h.tab("map");
    const transfer = dataTransfer({ entity_id: "binary_sensor.spare" });
    drag(h, h.$('[data-node="a"]'), "dragstart", transfer);
    assert.deepEqual(transfer.types, ["node_id"]);
    assert.equal(transfer.effectAllowed, "move");
    drag(h, geometry(h), "drop", transfer);
    const moved = await h.save();
    assert.deepEqual(moved.map.nodes.a.position, { x: 191, y: 303, unit: "px" });
    assert.equal(Object.hasOwn(moved.map.nodes, "spare"), false);
    drag(h, geometry(h), "drop", transfer, 0, 0);
    const clamped = await h.save();
    assert.deepEqual(clamped.map.nodes.a.position, { x: 0, y: 0, unit: "px" });
});

test("external, ambiguous, stale and nonfinite drag payloads cannot edit the graph", async t => {
    const h = await ready(t); await h.tab("map");
    const original = clone(h.server.config.map);
    const board = geometry(h);
    for (const [data, x] of [
        [{ "text/plain": "outside" }, 350], [{ node_id: "deleted" }, 350],
        [{ entity_id: "binary_sensor.unknown" }, 350],
        [{ node_id: "a", entity_id: "binary_sensor.spare" }, 350], [{ node_id: "a" }, NaN],
    ]) drag(h, board, "drop", dataTransfer(data), x);
    assert.deepEqual((await h.save()).map, original);
});

test("raw YAML input saves the exact dirty source with the real save_config contract", async t => {
    const h = await ready(t); await h.tab("yaml");
    const raw = '\n# preserve this raw source\nnodes:\n  raw_node:\n    label: "on"\n    entities:\n      motion: ["binary_sensor.a", "binary_sensor.alias"]\nfuture:\n  "null": ["001", "off"]\n';
    h.edit("[data-map-yaml]", raw, "input");
    const message = await h.save();
    assert.deepEqual(Object.keys(message).sort(), [
        "type", "entry_id", "map", "map_yaml", "map_yaml_dirty", "transition_window_seconds",
        "expected_occupants", "expected_occupants_entity",
    ].sort());
    assert.equal(message.type, type("save_config"));
    assert.equal(message.entry_id, "entry-dom");
    assert.equal(message.map_yaml_dirty, true);
    assert.equal(message.map_yaml, raw);
    // The backend chooses raw YAML when dirty; the graph member is still the old map.
    assert.ok(message.map.nodes.a);
    assert.equal(Object.hasOwn(message.map.nodes, "raw_node"), false);
    await h.tab("map");
    assert.equal(h.$('[data-node="raw_node"] strong').textContent, "on");
});

test("a graph edit after raw YAML parses that source and sends graph-authoritative dirty false", async t => {
    const h = await ready(t); await h.tab("yaml");
    h.edit("[data-map-yaml]", 'nodes:\n  raw_node:\n    label: "off"\n    entities:\n      motion: ["binary_sensor.a", "binary_sensor.alias"]\nfuture: {"null": "001"}\n', "input");
    await h.tab("map"); h.click('[data-action="add-empty"]');
    const message = await h.save();
    assert.equal(message.map_yaml_dirty, false);
    assert.deepEqual(Object.keys(message.map.nodes).sort(), ["node", "raw_node"]);
    assert.equal(message.map.nodes.raw_node.label, "off");
    assert.deepEqual(message.map.nodes.raw_node.entities.motion, ["binary_sensor.a", "binary_sensor.alias"]);
    assert.deepEqual(message.map.future, { null: "001" });
    assert.deepEqual(parse(message.map_yaml, { version: "1.1" }), message.map);
});

test("invalid raw YAML sends no save and preserves the exact editable source", async t => {
    const h = await ready(t); await h.tab("yaml");
    const raw = "\nnodes: [unterminated\n";
    h.edit("[data-map-yaml]", raw, "input");
    await h.save();
    assert.equal(h.calls("save_config").length, 0);
    assert.equal(h.$("[data-map-yaml]").value, raw);
    assert.ok(h.$("[data-error]").textContent.trim());
    assert.equal(h.$('[data-action="save"]').disabled, false);
});

test("invalid inspector position remains visible after rejected save and can be corrected", async t => {
    const h = await ready(t); await h.tab("map"); h.click('[data-node="a"]');
    const input = h.edit('[data-field="x"]', "-1");
    assert.equal(h.$('[data-field="x"]'), input);
    assert.equal(input.value, "-1");
    assert.match(h.$("[data-error]").textContent, /finite and nonnegative/);
    await h.save();
    assert.equal(h.calls("save_config").length, 0);
    // Save rejection must not silently replace the invalid edit with stored x=80.
    assert.equal(h.$('[data-field="x"]').value, "-1");
    h.edit('[data-field="x"]', "123");
    assert.equal((await h.save()).map.nodes.a.position.x, 123);
});

for (const count of [0, 1, 2]) {
    test(`Settings accepts count ${count} and saves the configured entity and transition window`, async t => {
        const h = await ready(t); await h.tab("settings");
        h.edit('[data-setting="expected_occupants"]', String(count), "input");
        h.edit('[data-setting="transition_window_seconds"]', "24", "input");
        h.edit('[data-setting="expected_occupants_entity"]', "sensor.authoritative_people", "input");
        const message = await h.save();
        assert.equal(message.expected_occupants, count);
        assert.equal(message.transition_window_seconds, 24);
        assert.equal(message.expected_occupants_entity, "sensor.authoritative_people");
        assert.equal(message.map_yaml_dirty, false);
        assert.equal(h.$('[data-setting="expected_occupants"]').value, String(count));
        assert.equal(h.$('[data-setting="transition_window_seconds"]').value, "24");
        assert.equal(h.$("[data-error]").textContent, "");
    });
}

test("invalid settings send no request and preserve all controls for correction", async t => {
    const h = await ready(t); await h.tab("settings");
    for (const [field, value, message] of [
        ["expected_occupants", "-1", /zero, one or two/],
        ["expected_occupants", "3", /zero, one or two/],
        ["expected_occupants", "0.5", /zero, one or two/],
        ["expected_occupants", "", /zero, one or two/],
        ["transition_window_seconds", "0", /positive integer/],
        ["transition_window_seconds", "1.5", /positive integer/],
        ["transition_window_seconds", "", /positive integer/],
        ["expected_occupants_entity", "not-an-id", /entity id/],
    ]) {
        const values = { expected_occupants: "2", transition_window_seconds: "24", expected_occupants_entity: "sensor.people", [field]: value };
        for (const [key, text] of Object.entries(values)) h.edit(`[data-setting="${key}"]`, text, "input");
        await h.save();
        assert.equal(h.calls("save_config").length, 0, `${field}=${value}`);
        assert.match(h.$("[data-error]").textContent, message);
        for (const [key, text] of Object.entries(values)) assert.equal(h.$(`[data-setting="${key}"]`).value, text);
    }
});

test("cleanup cancellation performs only the exact preview request", async t => {
    const h = await ready(t, { confirm: false }); await h.tab("settings");
    h.click('[data-action="cleanup-entities"]'); await flush();
    assert.deepEqual(h.calls("cleanup_entities"), [
        { type: type("cleanup_entities"), entry_id: "entry-dom", dry_run: true },
    ]);
    assert.deepEqual(h.confirmations, ["Remove 2 stale Predictive Controls entities?"]);
    assert.equal(h.$('[data-action="cleanup-entities"]').disabled, false);
    assert.doesNotMatch(h.$(".maintenance-section").textContent, /Removed/);
});

test("cleanup preview and confirmed execution each suppress duplicate requests while pending", async t => {
    const h = await ready(t); await h.tab("settings");
    const preview = deferred(); const execute = deferred();
    h.enqueue("cleanup_entities", () => preview.promise);
    h.enqueue("cleanup_entities", () => execute.promise);
    h.click('[data-action="cleanup-entities"]'); await flush();
    assert.equal(h.$('[data-action="cleanup-entities"]').disabled, true);
    h.click('[data-action="cleanup-entities"]');
    await h.panel.cleanupEntities(); await flush();
    assert.equal(h.calls("cleanup_entities").length, 1);
    preview.resolve({ stale_count: 3 }); await flush();
    assert.deepEqual(h.confirmations, ["Remove 3 stale Predictive Controls entities?"]);
    assert.deepEqual(h.calls("cleanup_entities")[1], { type: type("cleanup_entities"), entry_id: "entry-dom", dry_run: false });
    h.click('[data-action="cleanup-entities"]');
    await h.panel.cleanupEntities(); await flush();
    assert.equal(h.calls("cleanup_entities").length, 2);
    execute.resolve({ removed_count: 2 }); await flush();
    assert.match(h.$(".maintenance-section").textContent, /Removed 2 stale entities\./);
    assert.equal(h.$('[data-action="cleanup-entities"]').disabled, false);
});

test("cleanup with zero stale entities neither confirms nor executes", async t => {
    const h = await ready(t); await h.tab("settings"); h.server.stale = 0;
    h.click('[data-action="cleanup-entities"]'); await flush();
    assert.equal(h.calls("cleanup_entities").length, 1);
    assert.equal(h.calls("cleanup_entities")[0].dry_run, true);
    assert.deepEqual(h.confirmations, []);
    assert.match(h.$(".maintenance-section").textContent, /No stale entities found\./);
});

test("cleanup preview arriving after reload cannot prompt or execute a stale deletion", async t => {
    const h = await ready(t); await h.tab("settings");
    const preview = deferred(); h.enqueue("cleanup_entities", () => preview.promise);
    h.click('[data-action="cleanup-entities"]'); await flush();
    h.click('[data-action="reload"]'); await flush();
    preview.resolve({ stale_count: 99 }); await flush();
    assert.deepEqual(h.confirmations, []);
    assert.equal(h.calls("cleanup_entities").length, 1);
    assert.equal(h.$('[data-action="cleanup-entities"]').disabled, false);
});

test("configuration-load errors are escaped and Reload recovers through the real load path", async t => {
    const attack = '<img src=x onerror="window.__panel_xss=1">';
    const h = harness(t, { queues: { config: [() => Promise.reject(attack)] } });
    await flush();
    assert.equal(h.panel.querySelectorAll("[data-tab]").length, 0);
    assert.equal(h.$("[data-error]").textContent, `Configuration: ${attack}`);
    assert.match(h.panel.textContent, /Unable to load configuration/);
    assertNoInjectedMarkup(h);
    h.click('[data-action="reload"]'); await flush();
    assert.equal(h.panel.querySelectorAll("[data-tab]").length, 6);
    assert.equal(h.$("[data-error]").textContent, "");
});

test("save errors are escaped while dirty YAML stays intact and retry remains usable", async t => {
    const h = await ready(t); await h.tab("yaml");
    const attack = '</p><img src=x onerror="window.__panel_xss=1">';
    const raw = '\nnodes: {}\nmessage: "keep me"\n';
    h.edit("[data-map-yaml]", raw, "input");
    h.enqueue("save_config", () => Promise.reject(attack));
    await h.save();
    assert.equal(h.$("[data-error]").textContent, attack);
    assert.equal(h.$("[data-map-yaml]").value, raw);
    assertNoInjectedMarkup(h);
    const retry = await h.save();
    assert.equal(retry.map_yaml_dirty, true);
    assert.equal(retry.map_yaml, raw);
    assert.equal(h.calls("save_config").length, 2);
    assert.equal(h.$("[data-error]").textContent, "");
});

test("map labels, entity strings, status attributes and SVG path identities cannot inject markup", async t => {
    const attack = '\"><img src=x onerror="window.__panel_xss=1">';
    const oddZone = 'odd\" onmouseover="window.__panel_xss=1';
    const map = mapWire();
    map.nodes.a.label = attack; map.nodes.a.zone = oddZone;
    map.zones[oddZone] = { ...map.zones.a, label: attack }; delete map.zones.a;
    const status = statusWire();
    status.zone_states[oddZone] = { confidence: 0.8, status: attack, reason: attack };
    status.occupancy_diagnostics.selected_paths = [pathWire([visit("a", { zone: oddZone }), visit("b")])];
    status.occupancy_diagnostics.episodes[0].zone = oddZone;
    status.occupancy_diagnostics.path_health[0].zone = oddZone;
    const h = await ready(t, {
        config: configWire({ map }), status,
        entities: { entities: [{ entity_id: "binary_sensor.evil", name: attack, device_class: attack, state: attack }] },
    });
    const card = [...h.panel.querySelectorAll("[data-zone]")].find(el => el.dataset.zone === oddZone);
    assert.ok(card); assert.equal(card.title, attack);
    assert.equal(card.querySelector(".zone-card-head strong").textContent, attack);
    assert.ok([...h.panel.querySelectorAll("[data-path]")].some(el => el.dataset.path === `${oddZone}->b`));
    assertNoInjectedMarkup(h);
    await h.tab("map"); h.click('[data-node="a"]');
    assert.equal(h.$('[data-field="label"]').value, attack);
    assert.equal(h.$('[data-entity="binary_sensor.evil"] strong').textContent, attack);
    assertNoInjectedMarkup(h);
    await h.tab("yaml"); assertNoInjectedMarkup(h);
});

test("failed status refresh labels retained roles stale without blocking editing and later recovers", async t => {
    const h = await ready(t);
    const attack = '<img src=x onerror="window.__panel_xss=1">';
    h.enqueue("status", () => Promise.reject(attack));
    h.click('[data-action="refresh-status"]'); await flush();
    assert.match(h.$("[data-status-banner]").textContent, /Stale \/ unavailable/);
    assert.ok(h.$("[data-status-banner]").textContent.includes(attack));
    assert.match(h.$(".occupancy-toolbar").textContent, /Stale/);
    assert.equal(h.panel.querySelectorAll(".zone-card.path-role-presence").length, 3);
    assertNoInjectedMarkup(h);
    for (const tab of ["map", "yaml", "settings"]) await h.tab(tab);
    assert.equal(h.calls("save_config").length, 0);
    await h.tab("occupancy");
    assert.equal(h.$("[data-status-banner]").textContent, "");
    assert.doesNotMatch(h.$(".occupancy-toolbar").textContent, /Stale/);
});

test("warning-only partial baseline renders nonfault timeout wording in graph and Reliability", async t => {
    const h = await ready(t, {
        status: {
            occupancy_diagnostics: {
                model: "zone_belief", reliability_warnings: [warningWire()],
            }
        }
    });
    const wording = "Continuous presence detected; path unverified";
    const card = h.$('[data-zone="a"]');
    assert.ok(card.classList.contains("has-warning"));
    assert.ok(card.querySelector(".zone-warning-label").textContent.includes(wording));
    assert.doesNotMatch(card.textContent, /Suspected Stuck/);
    await h.tab("reliability");
    assert.equal(h.panel.querySelectorAll(".reliability-row").length, 1);
    assert.ok(h.$(".reliability-row").textContent.includes(wording));
    assert.doesNotMatch(h.$(".reliability-row").textContent, /Suspected Stuck/);
});

test("mixed-reason warnings retain their label and cleared history is absent from active cards and list", async t => {
    const warnings = [
        warningWire(), warningWire({ node_id: "b", zone: "b", reasons: ["assertion_timeout", "impossible_cadence"] }),
        warningWire({ node_id: "c", zone: "c", kind: "impossible_cadence", reasons: ["rapid_cycles"] }),
        warningWire({ node_id: "d", zone: "d", active: false }),
    ];
    const h = await ready(t, { status: statusWire({ occupancy_diagnostics: { reliability_warnings: warnings } }) });
    assert.match(h.$('[data-zone="a"] .zone-warning-label').textContent, /Continuous presence detected; path unverified/);
    assert.match(h.$('[data-zone="b"] .zone-warning-label').textContent, /Suspected Stuck/);
    assert.match(h.$('[data-zone="c"] .zone-warning-label').textContent, /Impossible Cadence/);
    assert.equal(h.$('[data-zone="d"]').classList.contains("has-warning"), false);
    assert.equal(h.panel.querySelectorAll(".zone-warning-label").length, 3);
    // Warning decoration must not erase the independent current-presence role.
    assert.ok(h.$('[data-zone="a"]').classList.contains("path-role-presence"));
    await h.tab("reliability");
    const rows = [...h.panel.querySelectorAll(".reliability-row")];
    assert.deepEqual(rows.map(row => row.querySelector("strong").textContent), ["a", "b", "c"]);
    assert.match(rows[1].textContent, /Suspected Stuck/);
});

test("selected paths sit above the graph and ON3 then cleared2 preserve equally strong C presence", async t => {
    const h = await ready(t);
    const toolbar = h.$(".occupancy-toolbar");
    const list = h.$(".selected-paths");
    const graph = h.$(".occupancy-graph-section");
    assert.ok(toolbar.compareDocumentPosition(list) & h.window.Node.DOCUMENT_POSITION_FOLLOWING);
    assert.ok(list.compareDocumentPosition(graph) & h.window.Node.DOCUMENT_POSITION_FOLLOWING);
    assert.equal(h.panel.querySelectorAll(".path-chip.path-role-presence").length, 3);
    assert.equal(h.panel.querySelectorAll(".zone-card.path-role-presence").length, 3);
    const cClasses = h.$('[data-zone="c"]').className;
    assert.match(h.$('[data-zone="a"] .zone-belief-state').textContent, /Inactive/);
    assert.equal(h.$('[data-zone="e"]').classList.contains("path-role-presence"), false);
    assert.ok(h.$('[data-zone="d"]').classList.contains("path-role-candidate"));
    assert.equal(h.panel.querySelectorAll(".zone-card").length, 6, "keep empty configured zones");
    assert.equal(h.panel.querySelectorAll(".transition-table tbody tr").length, 2);
    assert.deepEqual([...h.panel.querySelectorAll(".selected-path-edge")].map(el => el.dataset.path), ["a->b", "b->c"]);
    const next = statusWire();
    next.occupancy_diagnostics.selected_paths = [pathWire([
        visit("a", { branch_active: false }), visit("b", { branch_active: false }), visit("c"),
    ], { track_confidence: "confirmed" })];
    for (const row of next.occupancy_diagnostics.path_health) if (["a", "b"].includes(row.node_id)) row.phase = "off";
    h.server.status = next;
    h.click('[data-action="refresh-status"]'); await flush();
    assert.equal(h.panel.querySelectorAll(".path-chip.path-role-history").length, 2);
    assert.equal(h.panel.querySelectorAll(".zone-card.path-role-history").length, 2);
    assert.equal(h.panel.querySelectorAll(".zone-card.path-role-presence").length, 1);
    assert.equal(h.$('[data-zone="c"]').className, cClasses);
    assert.equal(h.$(".path-badge").textContent, "Confirmed");
    assert.match(h.$(".path-slot").textContent, /Retained endpoint · ON · Continuation eligible: yes/);
    assert.deepEqual([...h.panel.querySelectorAll(".selected-path-edge")].map(el => el.dataset.path), ["a->b", "b->c"]);
});

test("explicit empty selected paths suppress legacy fallback while an absent field labels legacy", async t => {
    const legacy = {
        traversal_frontier: [{ token_id: "old", zone: "a", valid_until: "2026-09-15T18:00:00Z" }],
        authorizations: [{ authorized: true, source_token_ids: ["old"], target_zone: "b" }],
    };
    const h = await ready(t, { status: statusWire({ expected_occupants: 0, occupancy_diagnostics: legacy }) });
    assert.equal(h.$(".selected-paths h3").textContent, "No selected paths");
    assert.equal(h.panel.querySelectorAll(".path-slot,.authorized-path,.has-frontier").length, 0);
    const absent = statusWire({ occupancy_diagnostics: legacy });
    delete absent.occupancy_diagnostics.selected_paths;
    h.server.status = absent; await h.panel.refreshStatus();
    assert.match(h.$(".selected-paths h3").textContent, /Legacy path display/);
    assert.equal(h.panel.querySelectorAll(".authorized-path").length, 1);
    assert.ok(h.$('[data-zone="a"]').classList.contains("has-frontier"));
});

test("malformed selected data and inconsistent counts display unavailable instead of fabricated slots", async t => {
    const h = await ready(t);
    for (const status of [
        statusWire({ occupancy_diagnostics: { selected_paths: "not-an-array" } }),
        statusWire({ expected_occupants: 2, occupancy_diagnostics: { selected_paths: [pathWire()] } }),
    ]) {
        h.server.status = status; await h.panel.refreshStatus();
        assert.match(h.$(".selected-paths h3").textContent, /Selected paths unavailable/);
        assert.equal(h.panel.querySelectorAll(".path-slot,.selected-path-edge,.authorized-path").length, 0);
        assert.equal(h.panel.querySelectorAll(".zone-card.path-role-presence,.zone-card.path-role-candidate").length, 0);
    }
});

test("overlapping slots retain all memberships and OFF endpoint remains history rather than Unlocated", async t => {
    const status = statusWire({ expected_occupants: 2 });
    status.occupancy_diagnostics.selected_paths = [pathWire(), pathWire([visit("b"), visit("c")], { track_confidence: "confirmed" })];
    const h = await ready(t, { status });
    assert.equal(h.panel.querySelectorAll(".path-slot").length, 2);
    assert.match(h.$('[data-zone="c"] .path-role-label').textContent, /Slot 1, Slot 2/);
    const next = clone(status);
    for (const path of next.occupancy_diagnostics.selected_paths) {
        path.route.at(-1).branch_active = false;
        path.endpoint.branch_active = false;
        path.endpoint_eligible = false;
    }
    next.occupancy_diagnostics.path_health.find(row => row.node_id === "c").phase = "off";
    h.server.status = next; await h.panel.refreshStatus();
    assert.ok(h.$('[data-zone="c"]').classList.contains("path-role-history"));
    assert.match(h.$('[data-zone="c"] .path-role-label').textContent, /Slot 1, Slot 2/);
    for (const row of h.panel.querySelectorAll(".path-slot")) {
        assert.match(row.textContent, /Retained endpoint · OFF · Continuation eligible: no/);
        assert.doesNotMatch(row.textContent, /Unlocated|absent/i);
    }
    next.occupancy_diagnostics.selected_paths[1] = null;
    next.occupancy_diagnostics.path_health.find(row => row.node_id === "c").phase = "unknown";
    h.server.status = next; await h.panel.refreshStatus();
    assert.match(h.$(".selected-paths").textContent, /Slot 2 · Unlocated/);
    assert.match(h.$('[data-slot="1"]').textContent, /Retained endpoint · Unknown/);
});

test("evaluating the classic bundle repeatedly preserves native custom-element registration", async t => {
    const h = await ready(t);
    const constructor = h.window.customElements.get(tag);
    assert.ok(h.panel instanceof constructor);
    h.window.eval(bundle); h.window.eval(bundle);
    assert.equal(h.window.customElements.get(tag), constructor);
    const second = h.window.document.createElement(tag);
    second.hass = h.hass; h.window.document.body.append(second); await flush();
    assert.ok(second instanceof constructor);
    assert.equal(second.querySelectorAll("[data-tab]").length, 6);
    second.querySelector('[data-tab="map"]').click();
    assert.ok(second.querySelector(".map-layout"));
    assert.ok(h.panel.querySelector(".occupancy-layout"));
    second.remove();
    assert.equal(h.intervals.size, 1);
});

test("polling preserves the actual dirty YAML control, focus, caret, selection and scroll", async t => {
    const h = await ready(t); await h.tab("yaml");
    const raw = '\nnodes: {}\nnote: "not yet saved"\n';
    const editor = h.edit("[data-map-yaml]", raw, "input");
    editor.focus(); editor.setSelectionRange(4, 12, "backward");
    editor.scrollTop = 70; editor.scrollLeft = 21;
    h.server.status = statusWire({ expected_occupants: 0 });
    await h.panel.refreshStatus();
    assert.equal(h.$("[data-map-yaml]"), editor);
    assert.equal(h.window.document.activeElement, editor);
    assert.equal(editor.value, raw);
    assert.equal(editor.selectionStart, 4); assert.equal(editor.selectionEnd, 12);
    assert.equal(editor.selectionDirection, "backward");
    assert.equal(editor.scrollTop, 70); assert.equal(editor.scrollLeft, 21);
    assert.equal(h.calls("save_config").length, 0);
});

test("focused live graph defers rerender, labels pending freshness, and updates on a later unfocused poll", async t => {
    const h = await ready(t);
    const graph = h.$('[data-scroll-key="graph"]');
    graph.focus(); graph.scrollLeft = 321; graph.scrollTop = 123;
    h.server.status = statusWire({ expected_occupants: 0 });
    await h.panel.refreshStatus();
    assert.equal(h.$('[data-scroll-key="graph"]'), graph);
    assert.equal(h.window.document.activeElement, graph);
    assert.equal(graph.scrollLeft, 321); assert.equal(graph.scrollTop, 123);
    assert.match(h.$("[data-status-banner]").textContent, /New snapshot received/);
    assert.equal(h.panel.querySelectorAll(".path-chip").length, 3, "focused display is intentionally deferred");
    graph.blur(); await h.panel.refreshStatus();
    assert.equal(h.$(".selected-paths h3").textContent, "No selected paths");
    assert.equal(h.$('[data-scroll-key="graph"]').scrollLeft, 321);
});

test("unfocused live rerender preserves host and nested graph scroll offsets", async t => {
    const h = await ready(t);
    const old = h.$('[data-scroll-key="graph"]');
    h.panel.scrollLeft = 12; h.panel.scrollTop = 23;
    h.$(".floor-section").scrollLeft = 234; h.$(".floor-section").scrollTop = 45;
    old.scrollLeft = 345; old.scrollTop = 67;
    h.server.status = statusWire({ expected_occupants: 0 });
    await h.panel.refreshStatus();
    assert.notEqual(h.$('[data-scroll-key="graph"]'), old);
    assert.equal(h.panel.scrollLeft, 12); assert.equal(h.panel.scrollTop, 23);
    assert.equal(h.$(".floor-section").scrollLeft, 234); assert.equal(h.$(".floor-section").scrollTop, 45);
    assert.equal(h.$('[data-scroll-key="graph"]').scrollLeft, 345);
    assert.equal(h.$('[data-scroll-key="graph"]').scrollTop, 67);
});

test("disconnect during initial load permits reconnect and ignores the old successful load", async t => {
    const oldConfig = deferred(); const oldStatus = deferred();
    const fresh = configWire({ expected_occupants: 2, transition_window_seconds: 27 });
    const h = harness(t, {
        config: fresh, status: statusWire({ expected_occupants: 2 }), queues: {
            config: [() => oldConfig.promise], status: [() => oldStatus.promise],
        }
    });
    await flush(); assert.equal(h.panel.querySelector("[data-tab]"), null);
    h.panel.remove(); assert.equal(h.intervals.size, 0);
    h.window.document.body.append(h.panel); await flush();
    assert.equal(h.panel.querySelectorAll("[data-tab]").length, 6);
    assert.match(h.$(".selected-paths").textContent, /Slot 2 · Unlocated/);
    oldConfig.resolve(configWire({ expected_occupants: 0, transition_window_seconds: 8 }));
    oldStatus.resolve(statusWire({ expected_occupants: 0 })); await flush();
    await h.tab("settings");
    assert.equal(h.$('[data-setting="expected_occupants"]').value, "2");
    assert.equal(h.$('[data-setting="transition_window_seconds"]').value, "27");
    assert.equal(h.$('[data-action="reload"]').disabled, false);
    assert.equal(h.intervals.size, 1);
    assert.deepEqual(h.calls("config"), [{ type: type("config") }, { type: type("config") }]);
});

test("old initial-load rejection after reconnect cannot overwrite newer successful state", async t => {
    const pending = deferred();
    const h = harness(t, { queues: { config: [() => pending.promise] } });
    await flush(); h.panel.remove(); h.window.document.body.append(h.panel); await flush();
    pending.reject("obsolete config failure"); await flush();
    assert.equal(h.panel.querySelectorAll("[data-tab]").length, 6);
    assert.equal(h.$("[data-error]").textContent, "");
    assert.equal(h.$('[data-action="reload"]').disabled, false);
});

test("old poll success after reload cannot replace the newer snapshot", async t => {
    const h = await ready(t);
    const pending = deferred(); h.enqueue("status", () => pending.promise);
    const oldPoll = h.panel.refreshStatus(); await flush();
    h.server.status = statusWire({ expected_occupants: 0 });
    h.click('[data-action="reload"]'); await flush();
    assert.equal(h.$(".selected-paths h3").textContent, "No selected paths");
    pending.resolve(statusWire()); await oldPoll; await flush();
    assert.equal(h.$(".selected-paths h3").textContent, "No selected paths");
    assert.deepEqual(h.calls("status").map(message => Object.hasOwn(message, "entry_id")), [false, true, false]);
});

test("old poll rejection after reload cannot mark a newer successful snapshot stale", async t => {
    const h = await ready(t);
    const pending = deferred(); h.enqueue("status", () => pending.promise);
    const oldPoll = h.panel.refreshStatus(); await flush();
    await h.panel.loadData();
    pending.reject("obsolete transport failure"); await oldPoll; await flush();
    assert.equal(h.$("[data-status-banner]").textContent, "");
    assert.doesNotMatch(h.$(".occupancy-toolbar").textContent, /obsolete|Stale/);
});

test("stale save success after confirmed Reload cannot replace the reloaded configuration", async t => {
    const h = await ready(t); await h.tab("settings");
    const pending = deferred(); h.enqueue("save_config", () => pending.promise);
    h.edit('[data-setting="transition_window_seconds"]', "21", "input");
    h.click('[data-action="save"]'); await flush();
    const submitted = h.calls("save_config")[0];
    h.server.config = configWire({ transition_window_seconds: 33 });
    h.click('[data-action="reload"]'); await flush();
    assert.deepEqual(h.confirmations, ["Discard unsaved edits and reload configuration?"]);
    assert.equal(h.$('[data-setting="transition_window_seconds"]').value, "33");
    pending.resolve(saveResponse(submitted)); await flush();
    assert.equal(h.$('[data-setting="transition_window_seconds"]').value, "33");
    assert.equal(h.$('[data-action="save"]').disabled, false);
});

test("stale save rejection after Reload cannot overwrite a newer successful load with an error", async t => {
    const h = await ready(t); await h.tab("settings");
    const pending = deferred(); h.enqueue("save_config", () => pending.promise);
    h.click('[data-action="save"]'); await flush();
    h.server.config = configWire({ transition_window_seconds: 35 });
    h.click('[data-action="reload"]'); await flush();
    pending.reject("obsolete save failure"); await flush();
    assert.equal(h.$("[data-error]").textContent, "");
    assert.equal(h.$('[data-setting="transition_window_seconds"]').value, "35");
});

test("edits during save survive the old response and duplicate saves are suppressed", async t => {
    const h = await ready(t); await h.tab("yaml");
    const before = 'nodes: {}\nrevision: "before"\n';
    const after = 'nodes: {}\nrevision: "after"\n';
    h.edit("[data-map-yaml]", before, "input");
    const pending = deferred(); h.enqueue("save_config", () => pending.promise);
    h.click('[data-action="save"]'); await flush();
    assert.equal(h.$('[data-action="save"]').disabled, true);
    h.click('[data-action="save"]'); await h.panel.save(); await flush();
    assert.equal(h.calls("save_config").length, 1);
    h.edit("[data-map-yaml]", after, "input");
    pending.resolve(saveResponse(h.calls("save_config")[0])); await flush();
    assert.equal(h.$("[data-map-yaml]").value, after);
    assert.equal(h.$('[data-action="save"]').disabled, false);
    const second = await h.save();
    assert.equal(h.calls("save_config").length, 2);
    assert.equal(second.map_yaml_dirty, true);
    assert.equal(second.map_yaml, after);
});

test("one connected five-second timer coalesces polls and is cleared on detach", async t => {
    const h = await ready(t);
    h.panel.hass = h.hass; h.panel.startStatusRefresh(); h.panel.startStatusRefresh();
    assert.equal(h.intervals.size, 1); assert.equal(h.intervalStarts.length, 1);
    const [id, timer] = [...h.intervals][0];
    assert.equal(timer.milliseconds, 5000);
    const pending = deferred(); h.enqueue("status", () => pending.promise);
    timer.callback(); await flush(); timer.callback();
    const joined = h.panel.refreshStatus(); await flush();
    assert.equal(h.calls("status").length, 2, "one initial status plus one in-flight poll");
    pending.resolve(statusWire()); await joined;
    timer.callback(); await flush();
    assert.equal(h.calls("status").length, 3, "settlement releases coalescing lock");
    h.panel.remove();
    assert.equal(h.intervals.size, 0); assert.deepEqual(h.intervalClears, [id]);
    timer.callback(); await h.panel.refreshStatus(); await flush();
    assert.equal(h.calls("status").length, 3, "detached host cannot poll even via stale callback");
    h.window.document.body.append(h.panel); await flush();
    assert.equal(h.intervals.size, 1); assert.equal(h.intervalStarts.length, 2);
});

test("a manually fired request timeout releases a hung poll and ignores its late success", async t => {
    const h = await ready(t);
    assert.equal(h.timeouts.size, 0, "settled initial requests clear all request deadlines");
    const pending = deferred(); h.enqueue("status", () => pending.promise);
    const hung = h.panel.refreshStatus(); await flush();
    const joined = h.panel.refreshStatus(); await flush();
    assert.equal(h.calls("status").length, 2);
    assert.equal(h.timeouts.size, 1);
    const [id, timer] = [...h.timeouts][0];
    assert.equal(timer.milliseconds, 15000);
    h.fireTimeout(id); await Promise.all([hung, joined]);
    assert.match(h.$("[data-status-banner]").textContent, /Stale.*Request timed out: predictive_controls\/status/);
    h.server.status = statusWire({ expected_occupants: 0 });
    await h.panel.refreshStatus();
    assert.equal(h.calls("status").length, 3);
    assert.equal(h.$(".selected-paths h3").textContent, "No selected paths");
    assert.equal(h.$("[data-status-banner]").textContent, "");
    pending.resolve(statusWire()); await flush();
    assert.equal(h.$(".selected-paths h3").textContent, "No selected paths");
    assert.equal(h.timeouts.size, 0);
});

test("Activity filters and 50-row pagination preserve ownership and newest-first ordering", async t => {
    const rows = Array.from({ length: 55 }, (_, i) => ({
        event_at: new Date(Date.UTC(2026, 8, 15, 12, 0, i)).toISOString(), zone: "a",
        active_before: false, active_after: true, belief_after: 0.8,
        reason: "acquired", evidence_ids: [`edge-${i}`],
    }));
    rows.push(
        { event_at: "2026-09-15T12:01:00Z", zone: "b", active_before: false, active_after: false, reason: "acquisition_unauthorized", belief_after: 0.2 },
        { event_at: "2026-09-15T12:01:01Z", zone: "c", active_before: true, active_after: true, reason: "retained", belief_after: 0.8 },
    );
    const h = await ready(t, { status: statusWire({ occupancy_diagnostics: { policy_audit: rows } }) });
    await h.tab("activity");
    assert.equal(h.panel.querySelectorAll(".ownership-row").length, 5);
    assert.equal(h.panel.querySelectorAll(".audit-row").length, 50);
    assert.match(h.$(".activity-metrics").textContent, /57/);
    assert.equal(h.$(".audit-row time").textContent, new h.window.Date(rows[54].event_at).toLocaleString());
    h.click('[data-action="show-more-audit"]');
    assert.equal(h.panel.querySelectorAll(".audit-row").length, 55);
    assert.equal(h.panel.querySelector('[data-action="show-more-audit"]'), null);
    h.click('[data-activity-filter="rejected"]');
    assert.equal(h.panel.querySelectorAll(".audit-row").length, 1);
    assert.match(h.$(".audit-row").textContent, /Decision rejected/);
    h.click('[data-activity-filter="observations"]');
    assert.equal(h.panel.querySelectorAll(".audit-row").length, 1);
    assert.match(h.$(".audit-row").textContent, /Policy observation/);
    h.click('[data-activity-filter="all"]');
    assert.equal(h.panel.querySelectorAll(".audit-row").length, 50, "changing filter resets pagination");
    assert.equal(h.$(".audit-row time").textContent, new h.window.Date(rows[56].event_at).toLocaleString());
    h.click('[data-action="show-more-audit"]');
    assert.equal(h.panel.querySelectorAll(".audit-row").length, 57);
    assert.equal(h.calls("save_config").length, 0);
});

// Source-review regressions from the 2026-09-15 request, not captured HA
// incidents. These exercise the existing strict-modular-panel.md contracts at
// the shipped bundle's DOM/request boundary; production fixes belong to parent.
test("Map entry displays dirty YAML deletions and renames before any graph edit", async t => {
    const h = await ready(t);
    await h.tab("map"); h.click('[data-node="a"]');
    await h.tab("yaml");
    const map = clone(h.server.config.map);
    delete map.nodes.a;
    map.nodes.z = map.nodes.b; delete map.nodes.b;
    for (const node of Object.values(map.nodes)) {
        node.adjacent = node.adjacent.filter(id => id !== "a").map(id => id === "b" ? "z" : id);
    }
    map.nodes.z.label = "Renamed in dirty YAML";
    const raw = `# still unsaved\n${stringify(map, { compat: "yaml-1.1" })}`;
    h.edit("[data-map-yaml]", raw, "input");
    await h.tab("map");
    assert.deepEqual([...h.panel.querySelectorAll("[data-node]")].map(node => node.dataset.node).sort(),
        ["c", "d", "e", "z"]);
    assert.equal(h.$('[data-node="z"] strong').textContent, "Renamed in dirty YAML");
    h.click('[data-node="z"]');
    assert.equal(h.$('[data-field="node_id"]').value, "z");
    await h.tab("yaml");
    assert.equal(h.$("[data-map-yaml]").value, raw, "viewing the graph must not rewrite dirty source");
    assert.equal(h.calls("save_config").length, 0);
});

test("Map entry reports invalid dirty YAML without discarding the editable source", async t => {
    const h = await ready(t); await h.tab("yaml");
    const raw = "\n# keep this invalid draft\nnodes: [unterminated\n";
    h.edit("[data-map-yaml]", raw, "input");
    await h.tab("map");
    assert.ok(h.$("[data-error]").textContent.trim(), "entering Map must expose the parse failure immediately");
    assert.equal(h.calls("save_config").length, 0);
    await h.tab("yaml");
    assert.equal(h.$("[data-map-yaml]").value, raw);
});

test("invalid coordinate drafts stop blocking save after deletion or rename and correction", async t => {
    const deleted = await ready(t); await deleted.tab("map"); deleted.click('[data-node="a"]');
    deleted.edit('[data-field="x"]', "-1");
    assert.match(deleted.$("[data-error]").textContent, /finite and nonnegative/);
    deleted.click('[data-action="delete"]');
    const deletion = await deleted.save();

    const renamed = await ready(t); await renamed.tab("map"); renamed.click('[data-node="a"]');
    renamed.edit('[data-field="x"]', "-1");
    assert.match(renamed.$("[data-error]").textContent, /finite and nonnegative/);
    renamed.edit('[data-field="node_id"]', "z");
    assert.equal(renamed.$('[data-field="node_id"]').value, "z");
    renamed.edit('[data-field="x"]', "123");
    const correction = await renamed.save();

    assert.deepEqual([deleted.calls("save_config").length, renamed.calls("save_config").length], [1, 1],
        "neither a deleted-node draft nor an obsolete pre-rename key may veto a valid save");
    assert.equal(Object.hasOwn(deletion.map.nodes, "a"), false);
    assert.equal(Object.hasOwn(correction.map.nodes, "a"), false);
    assert.equal(correction.map.nodes.z.position.x, 123);
    assert.equal(deleted.$("[data-error]").textContent, "");
    assert.equal(renamed.$("[data-error]").textContent, "");
});

for (const outcome of ["success", "rejection"]) {
    test(`deferred save ${outcome} preserves input-only label typing or freezes editing`, async t => {
        const h = await ready(t); await h.tab("map"); h.click('[data-node="a"]');
        h.edit('[data-field="label"]', "Submitted label");
        const pending = deferred(); h.enqueue("save_config", () => pending.promise);
        h.click('[data-action="save"]'); await flush();
        assert.equal(h.calls("save_config").length, 1);
        const submitted = h.calls("save_config")[0];
        assert.equal(submitted.map.nodes.a.label, "Submitted label");
        const input = h.$('[data-field="label"]');
        // The hardened contract permits read-only freezing instead of concurrent
        // edits. Do not synthesize browser typing into an actually frozen control.
        const frozen = input.readOnly || input.disabled;
        const expected = frozen ? "Submitted label" : "Newer input-only label";
        if (!frozen) {
            input.focus();
            h.edit('[data-field="label"]', expected, "input");
            input.setSelectionRange(6, 16, "backward");
        }
        if (outcome === "success") pending.resolve(saveResponse(submitted));
        else pending.reject("deferred label save failure");
        await flush();
        const current = h.$('[data-field="label"]');
        assert.equal(current.value, expected, "settlement must not replace newer input with the submitted label");
        if (!frozen) {
            assert.equal(h.window.document.activeElement, current);
            assert.equal(current.selectionStart, 6); assert.equal(current.selectionEnd, 16);
            assert.equal(current.selectionDirection, "backward");
        }
        assert.equal(current.readOnly || current.disabled, false, "the editor must be usable after settlement");
        assert.equal(h.$('[data-action="save"]').disabled, false);
        assert.equal(h.$("[data-error]").textContent, outcome === "rejection" ? "deferred label save failure" : "");
    });
}

test("save completion prevents an older in-flight status from being displayed as fresh", async t => {
    const h = await ready(t); await h.tab("settings");
    h.edit('[data-setting="expected_occupants"]', "2", "input");
    await h.tab("occupancy");
    const pending = deferred(); h.enqueue("status", () => pending.promise);
    const oldPoll = h.panel.refreshStatus(); await flush();
    h.server.status = statusWire({ expected_occupants: 2 });
    const saved = await h.save();
    assert.equal(saved.expected_occupants, 2);
    pending.resolve(statusWire({ expected_occupants: 1 })); await oldPoll; await flush();
    // Either retain explicitly stale data or show a genuinely newer poll. Do not
    // require eager polling: the old response simply cannot masquerade as fresh.
    const stale = /stale|unavailable/i.test(h.$("[data-status-banner]").textContent);
    if (!stale) {
        assert.match(h.$(".graph-summary").textContent, /Expected 2/);
        assert.equal(h.panel.querySelectorAll(".path-slot").length, 2);
    }
    await h.panel.refreshStatus(); await flush();
    assert.equal(h.$("[data-status-banner]").textContent, "");
    assert.match(h.$(".graph-summary").textContent, /Expected 2/);
    assert.equal(h.panel.querySelectorAll(".path-slot").length, 2);
});

test("Reload does not release the duplicate-write lock of an unsettled save", async t => {
    const h = await ready(t); await h.tab("settings");
    h.edit('[data-setting="transition_window_seconds"]', "21", "input");
    const pending = deferred(); h.enqueue("save_config", () => pending.promise);
    h.click('[data-action="save"]'); await flush();
    assert.equal(h.calls("save_config").length, 1);
    const submitted = h.calls("save_config")[0];
    h.server.config = configWire({ transition_window_seconds: 33 });
    h.click('[data-action="reload"]'); await flush();
    assert.equal(h.$('[data-setting="transition_window_seconds"]').value, "33");
    h.click('[data-action="save"]'); await flush();
    const writesWhilePending = h.calls("save_config").length;
    pending.resolve(saveResponse(submitted)); await flush();
    assert.equal(writesWhilePending, 1, "Reload invalidates responses, not an already dispatched write");
    assert.equal(h.$('[data-setting="transition_window_seconds"]').value, "33");
    assert.equal(h.$('[data-action="save"]').disabled, false);
    const retry = await h.save();
    assert.equal(h.calls("save_config").length, 2);
    assert.equal(retry.transition_window_seconds, 33);
});

test("Reload cannot overlap confirmed cleanup executions while the first is unsettled", async t => {
    const h = await ready(t); await h.tab("settings");
    const pending = deferred();
    h.enqueue("cleanup_entities", () => Promise.resolve({ stale_count: 3 }));
    h.enqueue("cleanup_entities", () => pending.promise);
    h.click('[data-action="cleanup-entities"]'); await flush();
    assert.deepEqual(h.confirmations, ["Remove 3 stale Predictive Controls entities?"]);
    assert.deepEqual(h.calls("cleanup_entities").map(message => message.dry_run), [true, false]);
    h.click('[data-action="reload"]'); await flush();
    h.click('[data-action="cleanup-entities"]'); await flush();
    const executionsWhilePending = h.calls("cleanup_entities").filter(message => message.dry_run === false).length;
    pending.resolve({ removed_count: 3 }); await flush();
    assert.equal(executionsWhilePending, 1, "a new generation must not permit overlapping destructive requests");
    assert.equal(h.$('[data-action="cleanup-entities"]').disabled, false);
    h.click('[data-action="cleanup-entities"]'); await flush();
    assert.equal(h.calls("cleanup_entities").filter(message => message.dry_run === false).length, 2,
        "settlement must release the cleanup lock even after Reload");
});

test("partial audit Boolean pairs never invent production edges or Turned on/off labels", async t => {
    const rows = [
        { event_at: "2026-09-15T12:00:00Z", zone: "a", active_after: true, reason: "retained", belief_after: 0.8 },
        { event_at: "2026-09-15T12:00:01Z", zone: "b", active_before: true, reason: "retained", belief_after: 0.8 },
    ];
    const h = await ready(t, { status: statusWire({ occupancy_diagnostics: { policy_audit: rows } }) });
    await h.tab("activity");
    h.click('[data-activity-filter="edges"]');
    assert.equal(h.panel.querySelectorAll(".audit-row").length, 0,
        "an omitted before or after value is unknown, not false");
    h.click('[data-activity-filter="all"]');
    const retained = [...h.panel.querySelectorAll(".audit-row")];
    assert.equal(retained.length, 2);
    for (const row of retained) {
        assert.equal(row.classList.contains("kind-edges"), false);
        assert.doesNotMatch(row.textContent, /Turned on|Turned off|Off to On|On to Off/i);
        assert.match(row.querySelector(".audit-row-head strong").textContent, /Policy observation|Unknown transition/i);
    }
});

test("malformed selected paths with expected two report unavailable in the graph summary", async t => {
    const h = await ready(t, {
        status: statusWire({
            expected_occupants: 2, occupancy_diagnostics: { selected_paths: "not-an-array" },
        })
    });
    assert.match(h.$(".selected-paths h3").textContent, /Selected paths unavailable/);
    assert.match(h.$(".graph-summary").textContent, /Expected 2/);
    assert.match(h.$(".graph-summary").textContent, /unavailable/i);
    assert.doesNotMatch(h.$(".graph-summary").textContent, /0 anonymous slots/);
    assert.equal(h.panel.querySelectorAll(".path-slot").length, 0);
});