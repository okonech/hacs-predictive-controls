import assert from "node:assert/strict";
import test from "node:test";
import { parse as parseYaml } from "yaml";

import { decodeMap } from "../../frontend/decoders.ts";
import { dumpMapYaml, formatEntities, parseEntities, parseMapYaml } from "../../frontend/yaml.ts";

// Compare values and types, not a preferred quoting/layout style. The default
// YAML 1.2 reader and Home Assistant-compatible YAML 1.1 reader must agree on
// every serialized map and inspector entity dictionary.
const readers = [
    ["default YAML 1.2", source => parseYaml(source)],
    ["YAML 1.1", source => parseYaml(source, { version: "1.1" })],
];

const trickyStrings = [
    "on", "off", "ON", "Off", "true", "false", "True", "FALSE",
    "null", "Null", "NULL", "~", "yes", "no", "y", "n", "Y", "N",
    "0", "1", "-1", "+1", "001", "012", "0x10", "0o10", "1.0",
    "1e3", "1:20", ".nan", ".inf", "-.Inf", "2026-09-15", "",
    "  padded  ", "# not a comment", "a: b", "[not, an, array]",
    "{not: a mapping}", "*not_an_alias", "&not_an_anchor", "line one\nline two\n",
    "quote \"double\" and 'single'", "tab\tvalue", "Presence · 未知",
];

function ambiguousMap() {
    return {
        nodes: {
            on: {
                label: "off", zone: "true", floor: "001",
                entities: { motion: ["binary_sensor.on", "binary_sensor.off"], interaction: "event.null" },
                adjacent: ["off"], position: { x: 12.5, y: -2 }, reliability: 0.75,
                string_samples: trickyStrings,
            },
            off: { label: "null", zone: "true", adjacent: ["on"], entities: { presence: [] } },
        },
        zones: { true: { label: "001", floor: "001", position: { x: 0, y: 0 }, size: { width: 210, height: 112 } } },
        floors: ["001", "null"],
        extension: Object.fromEntries(trickyStrings.map((key, index) => [key, { text: key, index }])),
    };
}

function assertReaders(source, expected) {
    for (const [name, read] of readers) assert.deepEqual(read(source), expected, name);
}

function freeze(value) {
    if (value !== null && typeof value === "object") {
        for (const child of Object.values(value)) freeze(child);
        Object.freeze(value);
    }
    return value;
}

test("map strings with YAML Boolean, null and numeric meanings round-trip in both parser versions", () => {
    const map = decodeMap(ambiguousMap());
    const source = dumpMapYaml(map);
    assertReaders(source, map);
    assert.deepEqual(parseMapYaml(source), map);
    for (const [, read] of readers) {
        const roundTrip = read(source);
        assert.ok(roundTrip.nodes.on.string_samples.every(value => typeof value === "string"));
        assert.equal(typeof roundTrip.nodes.on.reliability, "number");
        assert.deepEqual(roundTrip.nodes.on.adjacent, ["off"]);
    }
});

test("ambiguous and punctuation-rich mapping keys remain exact string keys, never normalized Boolean keys", () => {
    const map = ambiguousMap();
    const source = dumpMapYaml(map);
    for (const [name, read] of readers) {
        const value = read(source);
        assert.deepEqual(Object.keys(value.nodes), ["on", "off"], name);
        assert.deepEqual(Object.keys(value.zones), ["true"], name);
        assert.deepEqual(Object.keys(value.extension), Object.keys(map.extension), name);
        for (const key of trickyStrings) assert.deepEqual(value.extension[key], map.extension[key], `${name}: ${key}`);
    }
    assert.deepEqual(parseMapYaml(source), map);
});

test("multiline strings preserve line breaks, trailing newlines, indentation and embedded quotes", () => {
    for (const label of ["first\nsecond", "first\nsecond\n", "first\nsecond\n\n", "first\n  indented\n# still text", "\nleading\n", "a: b\n\"quoted\"\n'on'"]) {
        const map = { nodes: { a: { label } }, documentation: label };
        const source = dumpMapYaml(map);
        assertReaders(source, map);
        assert.equal(parseMapYaml(source).nodes.a.label, label);
        assert.equal(parseMapYaml(source).documentation, label);
    }
});

test("unknown root, node and zone extensions retain JSON types rather than stringify or flatten them", () => {
    const map = {
        nodes: { a: { entities: { motion: ["binary_sensor.a"] }, metadata: { enabled: false, absent: null, count: 0, ratio: 0.125, values: [true, null, "false", 2] } } },
        zones: { z: { metadata: { mapping: { on: "off" }, empty: {}, sequence: [] } } },
        metadata: { revision: 2, allow: true, note: "null", nested: [{ unknown: [0, false, null, "0"] }] },
    };
    const source = dumpMapYaml(map);
    assertReaders(source, map);
    assert.deepEqual(parseMapYaml(source), map);
});

test("unknown fields nested inside positions and sizes survive a complete map YAML edit round-trip", () => {
    // This oracle intentionally exposes lossy point/size decoding if present.
    // Do not delete metadata from the expected map to make production pass.
    const map = {
        nodes: { a: { position: { x: 10, y: 20, unit: "px", anchor: { mode: "on", index: "001" } } } },
        zones: {
            z: {
                position: { x: 0, y: 0, reference: { text: "null", scale: 1.5 } },
                size: { width: 210, height: 112, constraints: { resizable: false, minimum: [100, 80] } },
            }
        },
    };
    const source = dumpMapYaml(map);
    assertReaders(source, map); // Distinguishes serialization loss from decoding loss.
    assert.deepEqual(parseMapYaml(source), map);
});

test("map entity singleton and multi-alias arrays remain arrays while scalar entities remain strings", () => {
    const entities = { motion: ["binary_sensor.a", "binary_sensor.alias", "binary_sensor.a"], presence: ["binary_sensor.single"], interaction: "event.button", unused: [] };
    const map = { nodes: { a: { entities } } };
    const source = dumpMapYaml(map);
    assertReaders(source, map);
    assert.deepEqual(parseMapYaml(source).nodes.a.entities, entities);
    for (const [, read] of readers) {
        const actual = read(source).nodes.a.entities;
        assert.equal(Array.isArray(actual.presence), true);
        assert.equal(Array.isArray(actual.unused), true);
        assert.equal(typeof actual.interaction, "string");
    }
});

test("map aliases resolve to valid node and entity-array data in both YAML versions", () => {
    const source = [
        "nodes:",
        '  "on": &node',
        '    label: "off"',
        '    zone: "null"',
        "    entities:",
        '      motion: &motion ["binary_sensor.a", "binary_sensor.alias"]',
        '  "off": *node',
        '  "null":',
        "    entities:",
        "      presence: *motion",
        "",
    ].join("\n");
    const entities = { motion: ["binary_sensor.a", "binary_sensor.alias"] };
    const node = { label: "off", zone: "null", entities };
    const expected = { nodes: { on: node, off: node, null: { entities: { presence: entities.motion } } } };
    assertReaders(source, expected);
    const map = parseMapYaml(source);
    assert.deepEqual(map, expected);
    assertReaders(dumpMapYaml(map), expected);
    assert.deepEqual(parseMapYaml(dumpMapYaml(map)), expected);
});

test("quoted scalar keys and strings in user-written map YAML do not change type on resave", () => {
    const source = [
        '"nodes":',
        '  "001":',
        '    "label": "true"',
        '    "zone": "null"',
        '    "entities": {"on": ["off", "null", "001"]}',
        '    "adjacent": ["off"]',
        '  "off": {}',
        '"on": {"null": "true", "001": "off"}',
        "",
    ].join("\n");
    const expected = { nodes: { "001": { label: "true", zone: "null", entities: { on: ["off", "null", "001"] }, adjacent: ["off"] }, off: {} }, on: { null: "true", "001": "off" } };
    assertReaders(source, expected);
    assert.deepEqual(parseMapYaml(source), expected);
    assertReaders(dumpMapYaml(parseMapYaml(source)), expected);
});

test("map serialization is deterministic, newline-terminated and does not mutate its input", () => {
    const map = freeze(decodeMap(ambiguousMap()));
    const before = structuredClone(map);
    const first = dumpMapYaml(map);
    const second = dumpMapYaml(map);
    assert.equal(second, first);
    assert.ok(first.endsWith("\n"));
    assert.doesNotMatch(first, /^%YAML/m); // Both readers must work without a version directive overriding them.
    assert.deepEqual(map, before);
    assertReaders(first, before);
});

test("empty maps, empty collections and absent optional fields survive serialization", () => {
    for (const map of [{ nodes: {} }, { nodes: {}, zones: {}, floors: [] }, { nodes: { a: { entities: {}, adjacent: [] } }, extension: { list: [], object: {}, nullable: null } }]) {
        const source = dumpMapYaml(map);
        assertReaders(source, map);
        assert.deepEqual(parseMapYaml(source), map);
    }
});

test("map parsing rejects malformed YAML and required shape errors instead of producing an empty map", () => {
    for (const source of ["", "null", "on", "true", "123", "[]", "{}", '"nodes: {}"', "nodes: null", "nodes: []", "nodes: { a: null }", "nodes: [", "nodes: *missing", "nodes: {}\nnodes: {}\n"]) {
        assert.throws(() => parseMapYaml(source), Error, source);
    }
});

test("map parsing rejects wrong known YAML types and nonfinite values without coercion", () => {
    for (const source of [
        "nodes: { a: { label: true } }",
        "nodes: { a: { zone: null } }",
        "nodes: { a: { adjacent: b } }",
        "nodes: { a: { entities: { motion: false } } }",
        "nodes: { a: { entities: { motion: [on] } } }",
        "nodes: { a: { position: { x: .inf, y: 0 } } }",
        'nodes: { a: { position: { x: "1", y: 0 } } }',
        "nodes: { a: { reliability: .nan } }",
        "nodes: {}\nzones: { z: { size: { width: 0, height: 112 } } }",
        "nodes: {}\nfuture: { nested: [.inf] }",
    ]) assert.throws(() => parseMapYaml(source), Error, source);
});

test("inspector formatting preserves ambiguous keys and scalar string values in both YAML versions", () => {
    const entities = Object.fromEntries(trickyStrings.map(value => [value, value]));
    const source = formatEntities(entities);
    assertReaders(source, entities);
    assert.deepEqual(parseEntities(source), entities);
    for (const [, read] of readers) assert.ok(Object.values(read(source)).every(value => typeof value === "string"));
});

test("inspector aliases retain order, multiplicity, empty arrays and singleton arrays", () => {
    const entities = { motion: ["binary_sensor.a", "binary_sensor.alias", "binary_sensor.a"], presence: ["on", "off", "null", "001"], single: ["binary_sensor.single"], interaction: "event.button", empty: [] };
    const source = formatEntities(entities);
    assertReaders(source, entities);
    assert.deepEqual(parseEntities(source), entities);
    assert.equal(Array.isArray(parseEntities(source).single), true);
    assert.equal(typeof parseEntities(source).interaction, "string");
});

test("inspector multiline alias strings and quoted keys round-trip without flattening arrays", () => {
    const entities = { "on\nsecond": ["off\nnull\n", " 001 ", 'quote "in" value'], "a: b": "line one\nline two" };
    const source = formatEntities(entities);
    assertReaders(source, entities);
    assert.deepEqual(parseEntities(source), entities);
});

test("inspector parsing accepts plain entity shorthand, quoted ambiguous shorthand and empty input", () => {
    assert.deepEqual(parseEntities("binary_sensor.a"), { motion: "binary_sensor.a" });
    assert.deepEqual(parseEntities("event.button"), { motion: "event.button" });
    for (const value of ["on", "off", "true", "null", "001", "1e3", ""]) {
        assert.deepEqual(parseEntities(JSON.stringify(value)), { motion: value });
    }
    for (const source of ["", " ", "\n\t "]) assert.deepEqual(parseEntities(source), {});
    assertReaders(formatEntities({}), {});
    assert.deepEqual(parseEntities(formatEntities({})), {});
});

test("inspector YAML alias references resolve as arrays and resave in both parser versions", () => {
    const source = 'motion: &aliases ["binary_sensor.a", "binary_sensor.alias", "on"]\npresence: *aliases\n';
    const aliases = ["binary_sensor.a", "binary_sensor.alias", "on"];
    const expected = { motion: aliases, presence: aliases };
    assertReaders(source, expected);
    assert.deepEqual(parseEntities(source), expected);
    assertReaders(formatEntities(parseEntities(source)), expected);
});

test("inspector parsing rejects implicit Boolean/null/number values, malformed aliases and nested arrays", () => {
    for (const source of [
        "on", "off", "true", "false", "null", "~", "001", "1.5", "[]", "[binary_sensor.a]",
        "motion: on", "motion: false", "motion: null", "motion: 1", "motion: {}",
        "motion: [binary_sensor.a, false]", "motion: [[binary_sensor.a]]", "motion: [",
        "motion: *missing", "motion: a\nmotion: b\n",
    ]) assert.throws(() => parseEntities(source), Error, source);
});

test("inspector serialization is deterministic and leaves a frozen alias dictionary unchanged", () => {
    const entities = freeze({ motion: ["on", "off", "001"], presence: "null", interaction: [] });
    const before = structuredClone(entities);
    const first = formatEntities(entities);
    assert.equal(formatEntities(entities), first);
    assert.deepEqual(entities, before);
    assertReaders(first, before);
    assert.deepEqual(parseEntities(first), before);
});
