import assert from "node:assert/strict";
import { test } from "node:test";
import {
    countCrossings,
    estimateCardHeight,
    floorBands,
    minimizeCrossings,
    pointInRect,
    segmentIntersectsRect,
    segmentsCross,
    separateFloorRows,
    spacedZoneSummaries,
    stackFloorsByBand,
    zoneAdjacencyPairs,
} from "../../frontend/layout.ts";
import { panelStyles } from "../../frontend/styles.ts";

function zone(zoneId, x = 0, y = 0, floor = "ground", overrides = {}) {
    return {
        zoneId,
        label: zoneId,
        floor,
        role: "room_occupancy",
        occupancyBehavior: "sustained",
        position: { x, y },
        size: { width: 120, height: 112 },
        nodeIds: [zoneId],
        ...overrides,
    };
}

function freeze(value) {
    if (value && typeof value === "object") {
        for (const child of Object.values(value)) freeze(child);
        Object.freeze(value);
    }
    return value;
}

function byId(zones, id) {
    const found = zones.find((item) => item.zoneId === id);
    assert.ok(found, `Expected zone ${id}`);
    return found;
}

function centers(zones) {
    return Object.fromEntries(zones.map((item) => [item.zoneId, {
        x: item.position.x + item.size.width / 2,
        y: item.position.y + estimateCardHeight(item) / 2,
    }]));
}

function overlaps(a, b) {
    return a.position.x < b.position.x + b.size.width &&
        a.position.x + a.size.width > b.position.x &&
        a.position.y < b.position.y + estimateCardHeight(b) &&
        a.position.y + estimateCardHeight(a) > b.position.y;
}

function assertNoOverlap(zones) {
    for (let i = 0; i < zones.length; i += 1) {
        for (let j = i + 1; j < zones.length; j += 1) {
            assert.equal(overlaps(zones[i], zones[j]), false,
                `${zones[i].zoneId} overlaps ${zones[j].zoneId}`);
        }
    }
}

// Public geometry reconstructs the documented objective, not a search hook.
function objective(zones, nodes) {
    const pairs = zoneAdjacencyPairs(zones, nodes);
    const center = centers(zones);
    let cardCrossings = 0;
    for (const [a, b] of pairs) {
        for (const item of zones) {
            if (item.zoneId === a || item.zoneId === b) continue;
            if (segmentIntersectsRect(center[a], center[b], {
                ...item.position, w: item.size.width, h: estimateCardHeight(item),
            })) cardCrossings += 1;
        }
    }
    return countCrossings(pairs, center) + 4 * cardCrossings;
}

test("empty inputs return empty layouts, bands and adjacency without infinities", () => {
    const empty = freeze([]);
    assert.deepEqual(spacedZoneSummaries(empty), []);
    assert.deepEqual(separateFloorRows(empty), []);
    assert.deepEqual(stackFloorsByBand(empty), []);
    assert.deepEqual(minimizeCrossings(empty, {}), []);
    assert.deepEqual(floorBands(empty), []);
    assert.deepEqual(zoneAdjacencyPairs(empty, {}), []);
    assert.equal(countCrossings([], {}), 0);
});

test("height retains legacy title wrapping and configured minimum", () => {
    const short = zone("a", 0, 0, "ground", { size: { width: 210, height: 112 } });
    assert.equal(estimateCardHeight(short), 168);
    assert.equal(estimateCardHeight({ ...short, label: "a".repeat(11) }), 168);
    assert.equal(estimateCardHeight({ ...short, label: "a".repeat(12) }), 192);
    assert.equal(estimateCardHeight({ ...short, label: "a".repeat(34) }), 240);
    assert.equal(estimateCardHeight({ ...short, size: { width: 210, height: 500 } }), 500);
    assert.equal(estimateCardHeight({ ...short, label: "" }), 168);
    assert.equal(estimateCardHeight({ ...short, label: "ab", size: { width: 24, height: 0 } }), 192);
});

test("total render height reserves membership and warning text without double counting", () => {
    const base = zone("a");
    assert.equal(estimateCardHeight({ ...base, contentHeight: 380 }), 380);
    assert.equal(estimateCardHeight({ ...base, contentHeight: 100 }), 168);
    assert.equal(estimateCardHeight({ ...base, contentHeight: 0 }), 168);
    for (const contentHeight of [NaN, Infinity, -Infinity, -1]) {
        assert.throws(() => estimateCardHeight({ ...base, contentHeight }), RangeError);
    }
});

test("spacing scales about minimum coordinates, rounds, and never edits supplied objects", () => {
    const input = freeze([zone("a", -20, 40), zone("b", 80, 140)]);
    const before = structuredClone(input);
    const result = spacedZoneSummaries(input);
    assert.deepEqual(result.map((item) => item.position), [{ x: -20, y: 40 }, { x: 102, y: 158 }]);
    assert.deepEqual(spacedZoneSummaries(input, 2, 3).map((item) => item.position),
        [{ x: -20, y: 40 }, { x: 180, y: 340 }]);
    assert.deepEqual(input, before);
    assert.notEqual(result[0].position, input[0].position);
    result[0].size.width = 999;
    result[0].nodeIds.push("extra");
    assert.deepEqual(input, before);
});

test("row separation uses rendered height, horizontal overlap and stable vertical order", () => {
    const input = freeze([
        zone("lower", 0, 20),
        zone("upper", 0, 0, "ground", { contentHeight: 380 }),
        zone("side", 120, 0),
        zone("other", 0, 0, "upstairs"),
    ]);
    const before = structuredClone(input);
    const result = separateFloorRows(input);
    assert.deepEqual(result.map((item) => item.zoneId), ["lower", "upper", "side", "other"]);
    assert.equal(byId(result, "upper").position.y, 0);
    assert.equal(byId(result, "lower").position.y, 428);
    assert.equal(byId(result, "side").position.y, 0, "touching horizontal spans need no shift");
    assert.equal(byId(result, "other").position.y, 0, "floors are handled independently");
    assert.equal(byId(separateFloorRows(input, 12), "lower").position.y, 392);
    assert.deepEqual(input, before);
});

test("rows consider every previously placed overlapping span, not only the last card", () => {
    const input = freeze([
        zone("a", 0, 0, "ground", { contentHeight: 400 }),
        zone("b", 300, 0),
        zone("c", 50, 10),
        zone("d", 100, 20),
    ]);
    const result = separateFloorRows(input);
    assert.equal(byId(result, "c").position.y, 448);
    assert.equal(byId(result, "d").position.y, 664);
    assertNoOverlap(result);
});

test("floor bands include the tallest content and sort by top then floor name", () => {
    const input = freeze([
        zone("a", 0, 100, "zebra"),
        zone("b", 300, 100, "alpha", { contentHeight: 400 }),
        zone("c", 600, 150, "alpha"),
        zone("d", 0, -100, "basement"),
    ]);
    assert.deepEqual(floorBands(input), [
        { floor: "basement", top: -100, bottom: 68 },
        { floor: "alpha", top: 100, bottom: 500 },
        { floor: "zebra", top: 100, bottom: 268 },
    ]);
});

test("floor stacking respects configured order, then original top and lexical ties", () => {
    const input = freeze([
        zone("a", 0, 0, "alpha"),
        zone("z", 0, 0, "zebra"),
        zone("g1", 0, 100, "ground"),
        zone("g2", 300, 200, "ground", { contentHeight: 300 }),
        zone("u", 0, -500, "upstairs"),
    ]);
    const order = freeze(["missing", "ground", "upstairs"]);
    const before = structuredClone(input);
    const result = stackFloorsByBand(input, order);
    assert.deepEqual(result.map((item) => item.zoneId), ["g1", "g2", "u", "a", "z"]);
    assert.deepEqual(result.map((item) => item.position.y), [100, 200, 596, 860, 1124]);
    assert.equal(byId(result, "g2").position.x, 300);
    assert.deepEqual(floorBands(stackFloorsByBand(input)).map((band) => band.floor),
        ["upstairs", "alpha", "zebra", "ground"]);
    assertNoOverlap(result);
    assert.deepEqual(input, before);
});

test("stacking honors an explicit inter-floor gap after a tall warning card", () => {
    const input = [zone("a", 0, 80, "a", { contentHeight: 420 }), zone("b", 0, 0, "b")];
    const result = stackFloorsByBand(input, ["a", "b"], 144);
    assert.equal(byId(result, "b").position.y, 644);
    assertNoOverlap(result);
});

test("adjacency groups physical nodes, deduplicates reverse links, and omits missing/same-zone targets", () => {
    const input = freeze([
        zone("A", 0, 0, "ground", { nodeIds: ["a", "a2", "not_configured"] }),
        zone("B", 300, 0, "ground", { nodeIds: ["b"] }),
        zone("C", 600, 0, "ground", { nodeIds: [] }),
    ]);
    const nodes = freeze({
        a: { adjacent: ["a", "a2", "missing", "b", "b"] },
        a2: { adjacent: ["b"] },
        b: { adjacent: ["a"] },
        orphan: { adjacent: ["b"] },
    });
    assert.deepEqual(zoneAdjacencyPairs(input, nodes), [["A", "B"]]);
    assert.deepEqual(zoneAdjacencyPairs(input, {}), []);
    assert.deepEqual(zoneAdjacencyPairs(input, { a: {}, b: { adjacent: ["a"] } }), [["B", "A"]]);
});

test("zone IDs containing edge separators or object-property names do not collide", () => {
    const input = [zone("a->b"), zone("c"), zone("a"), zone("b->c"), zone("__proto__")];
    assert.deepEqual(zoneAdjacencyPairs(input, {
        "a->b": { adjacent: ["c"] },
        a: { adjacent: ["b->c", "__proto__"] },
    }), [["a->b", "c"], ["a", "b->c"], ["a", "__proto__"]]);
});

test("geometry distinguishes crossings, parallel lines, collinear lines and inclusive rectangles", () => {
    assert.equal(segmentsCross({ x: 0, y: 0 }, { x: 10, y: 10 }, { x: 0, y: 10 }, { x: 10, y: 0 }), true);
    assert.equal(segmentsCross({ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 0, y: 1 }, { x: 10, y: 1 }), false);
    assert.equal(segmentsCross({ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 5, y: 0 }, { x: 15, y: 0 }), false);
    const box = { x: 2, y: 3, w: 6, h: 4 };
    assert.equal(pointInRect({ x: 2, y: 3 }, box), true);
    assert.equal(pointInRect({ x: 8, y: 7 }, box), true);
    assert.equal(pointInRect({ x: 8.01, y: 7 }, box), false);
    assert.equal(segmentIntersectsRect({ x: 0, y: 5 }, { x: 10, y: 5 }, box), true);
    assert.equal(segmentIntersectsRect({ x: 5, y: 0 }, { x: 5, y: 10 }, box), true);
    assert.equal(segmentIntersectsRect({ x: 3, y: 4 }, { x: 4, y: 5 }, box), true);
    assert.equal(segmentIntersectsRect({ x: 0, y: 0 }, { x: 1, y: 1 }, box), false);
    assert.equal(segmentIntersectsRect({ x: 0, y: 2 }, { x: 10, y: 2 }, box), false);
});

test("crossing count ignores shared endpoints and fails explicitly for required missing centers", () => {
    const center = freeze({ a: { x: 0, y: 0 }, b: { x: 10, y: 10 }, c: { x: 0, y: 10 }, d: { x: 10, y: 0 } });
    assert.equal(countCrossings([["a", "b"], ["c", "d"]], center), 1);
    assert.equal(countCrossings([["a", "b"], ["b", "c"], ["c", "d"]], center), 1);
    assert.equal(countCrossings([["a", "b"], ["a", "c"]], center), 0);
    assert.throws(() => countCrossings([["a", "b"], ["c", "missing"]], center), /Missing layout value: center missing/);
});

test("crossing minimization preserves the exact deterministic same-floor swap on an X", () => {
    const input = freeze([zone("a", 0, 0, "top"), zone("b", 400, 0, "top"), zone("c", 0, 400, "bottom"), zone("d", 400, 400, "bottom")]);
    const nodes = freeze({ a: { adjacent: ["d"] }, b: { adjacent: ["c"] } });
    const before = structuredClone(input);
    assert.equal(objective(input, nodes), 1);
    const result = minimizeCrossings(input, nodes);
    assert.equal(objective(result, nodes), 0);
    assert.deepEqual(result.map((item) => item.position), [
        { x: 400, y: 0 }, { x: 0, y: 0 }, { x: 0, y: 400 }, { x: 400, y: 400 },
    ]);
    for (let repeat = 0; repeat < 4; repeat += 1) assert.deepEqual(minimizeCrossings(input, nodes), result);
    assert.deepEqual(input, before);
    assertNoOverlap(result);
});

test("weighted objective penalizes lines through unrelated cards, not only edge-edge crossings", () => {
    const input = freeze([
        zone("a", 0, 0), zone("b", 300, 0), zone("c", 600, 0),
        zone("d", 0, 400, "other"), zone("e", 300, 400, "other"),
    ]);
    const nodes = freeze({ a: { adjacent: ["c"] }, d: { adjacent: ["e"] } });
    const edgeCount = countCrossings(zoneAdjacencyPairs(input, nodes), centers(input));
    assert.equal(edgeCount, 0, "edge-only minimization would incorrectly stop immediately");
    assert.equal(objective(input, nodes) - edgeCount, 4, "one unrelated card costs four crossings");
    const result = minimizeCrossings(input, nodes);
    assert.equal(objective(result, nodes), 0);
    assert.deepEqual(byId(result, "d").position, { x: 0, y: 400 }, "cannot swap across floors");
    assertNoOverlap(result);
});

test("search never worsens a valid baseline or overlaps unequal cards across varied edge orders", () => {
    const input = freeze([
        zone("a", 0, 0, "top"),
        zone("b", 180, 0, "top", { size: { width: 500, height: 112 }, contentHeight: 360 }),
        zone("c", 800, 0, "top"),
        zone("d", 0, 600, "bottom"),
        zone("e", 180, 600, "bottom", { size: { width: 500, height: 112 }, contentHeight: 420 }),
        zone("f", 800, 600, "bottom"),
    ]);
    const edgeChoices = [
        ["a", "d"], ["a", "e"], ["a", "f"],
        ["b", "d"], ["b", "e"], ["b", "f"],
        ["c", "d"], ["c", "e"], ["c", "f"],
    ];
    assertNoOverlap(input);
    for (const mask of [3, 7, 19, 42, 85, 113, 170, 273, 341, 426, 455, 511]) {
        const nodes = {};
        edgeChoices.forEach(([source, target], index) => {
            if ((mask & (1 << index)) === 0) return;
            nodes[source] ??= { adjacent: [] };
            nodes[source].adjacent.push(target);
        });
        freeze(nodes);
        const result = minimizeCrossings(input, nodes);
        assertNoOverlap(result);
        assert.ok(objective(result, nodes) <= objective(input, nodes), `objective worsened for mask ${mask}`);
        assert.deepEqual(minimizeCrossings(input, nodes), result);
        for (const item of result) {
            const original = byId(input, item.zoneId);
            assert.equal(item.floor, original.floor);
            assert.deepEqual(item.size, original.size);
            assert.deepEqual(item.nodeIds, original.nodeIds);
            assert.equal(item.contentHeight, original.contentHeight);
            assert.ok(input.some((slot) => slot.floor === item.floor &&
                slot.position.x === item.position.x && slot.position.y === item.position.y));
        }
    }
});

test("search no-op cases return independent summaries without changing content", () => {
    for (const input of [freeze([zone("a")]), freeze([zone("a"), zone("b", 400)]), freeze([zone("a"), zone("b", 400), zone("c", 800)])]) {
        const result = minimizeCrossings(input, { a: { adjacent: ["b"] } });
        assert.deepEqual(result, input);
        assert.notEqual(result, input);
        assert.notEqual(result[0], input[0]);
        assert.notEqual(result[0].position, input[0].position);
    }
});

test("full layout pipeline reserves long labels, path memberships and warnings across floors", () => {
    const input = freeze([
        zone("a", 40, 20, "upstairs", { label: "Long descriptive room label with warnings", contentHeight: 580 }),
        zone("b", 50, 120, "upstairs", { contentHeight: 300 }),
        zone("c", 40, 20, "ground", { contentHeight: 350 }),
        zone("d", 50, 120, "ground", { contentHeight: 460 }),
    ]);
    const before = structuredClone(input);
    const nodes = freeze({ a: { adjacent: ["b", "d"] }, b: { adjacent: ["c"] } });
    const stacked = stackFloorsByBand(separateFloorRows(spacedZoneSummaries(input)), ["upstairs", "ground"]);
    const result = minimizeCrossings(stacked, nodes);
    assertNoOverlap(result);
    assert.deepEqual(floorBands(result).map((band) => band.floor), ["upstairs", "ground"]);
    assert.ok(objective(result, nodes) <= objective(stacked, nodes));
    assert.deepEqual(input, before);
});

test("every CSS selector, including generic controls and media rules, is host scoped", () => {
    let selectorCount = 0;
    for (const match of panelStyles.matchAll(/([^{}]+)\{/g)) {
        const prelude = match[1].trim();
        if (prelude.startsWith("@media")) continue;
        // The only selector lists inside parentheses are flat :is(...) lists.
        const selectors = prelude.replace(/:is\([^)]*\)/g, ":is-placeholder").split(",");
        for (const selector of selectors) {
            assert.match(selector.trim(), /^predictive-controls-panel(?:\s|$)/);
            selectorCount += 1;
        }
    }
    assert.ok(selectorCount > 200, "must inspect the full legacy and path stylesheet");
    assert.match(panelStyles, /predictive-controls-panel header\s*\{/);
    assert.match(panelStyles, /predictive-controls-panel button\s*\{/);
    assert.match(panelStyles, /:focus-visible/);
    assert.match(panelStyles, /@media \(forced-colors:active\)/);
});

test("role CSS retains solid presence/history, dashed candidates and the legacy red-warning selector", () => {
    assert.match(panelStyles, /\.zone-card\.path-role-presence[^{}]*\{[^}]*border:2px solid var\(--pc-presence\)/);
    assert.match(panelStyles, /\.zone-card\.path-role-history[^{}]*\{[^}]*border:2px solid var\(--pc-history\)/);
    assert.match(panelStyles, /\.zone-card\.path-role-candidate[^{}]*\{[^}]*border-style:dashed/);
    assert.match(panelStyles, /\.zone-card\.has-warning[^}]+#d32f2f/);
    const warning = panelStyles.match(/predictive-controls-panel \.zone-card\.has-warning \{([^}]+)\}/);
    assert.ok(warning);
    assert.match(warning[1], /border-color:#d32f2f/);
    assert.match(warning[1], /box-shadow:[^;]*#d32f2f/);
    assert.doesNotMatch(warning[1], /border(?:-style)?:/, "warning must preserve dashed candidate shape");
    const warningPosition = panelStyles.indexOf(warning[0]);
    assert.ok(warningPosition > panelStyles.indexOf(".zone-card.path-role-presence .confidence-bar span"));
    assert.ok(warningPosition > panelStyles.indexOf(".status-confirmed"));
    assert.match(panelStyles, /\.zone-card\.has-warning \.confidence-bar span \{ background:#d32f2f;/);
});