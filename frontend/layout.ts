/** Pure graph layout; map decoding and zone grouping belong to the caller. */
export interface Point {
    x: number;
    y: number;
}

export interface Size {
    width: number;
    height: number;
}

export interface ZoneSummary {
    zoneId: string;
    label: string;
    floor: string;
    role: string;
    occupancyBehavior: string;
    position: Point;
    size: Size;
    nodeIds: string[];
    /** Total rendered border-box height, including path memberships and warnings.
     * Supply before spacing/stacking/search, not just when rendering the card.
     */
    contentHeight?: number;
}

/** Only adjacency is consumed. Richer decoded map nodes are structurally valid. */
export interface Nodes {
    readonly [nodeId: string]: { readonly adjacent?: readonly string[] };
}

export interface Rect {
    x: number;
    y: number;
    w: number;
    h: number;
}

export interface FloorBand {
    floor: string;
    top: number;
    bottom: number;
}

export type ZonePair = readonly [string, string];

function required<T>(value: T | undefined, context: string): T {
    if (value === undefined) throw new Error(`Missing layout value: ${context}`);
    return value;
}

function copyZone(zone: ZoneSummary, position: Point = zone.position): ZoneSummary {
    return {
        ...zone,
        position: { ...position },
        size: { ...zone.size },
        nodeIds: [...zone.nodeIds],
    };
}

function groupByFloor(zones: readonly ZoneSummary[]): Map<string, ZoneSummary[]> {
    const grouped = new Map<string, ZoneSummary[]>();
    for (const zone of zones) {
        const list = grouped.get(zone.floor) ?? [];
        list.push(zone);
        grouped.set(zone.floor, list);
    }
    return grouped;
}

/** Preserve the legacy title estimate and configured minimum, with a render hint. */
export function estimateCardHeight(zone: ZoneSummary): number {
    const charsPerLine = Math.max(1, Math.floor((zone.size.width - 24) / 16));
    const titleLines = Math.max(1, Math.ceil(zone.label.length / charsPerLine));
    const estimated = 168 + 24 * (titleLines - 1);
    const contentHeight = zone.contentHeight ?? 0;
    if (!Number.isFinite(contentHeight) || contentHeight < 0) {
        throw new RangeError("Card contentHeight must be finite and nonnegative");
    }
    return Math.max(estimated, zone.size.height, contentHeight);
}

/** Move down only where horizontal spans overlap, retaining stable row order. */
export function separateFloorRows(
    zones: readonly ZoneSummary[],
    minGap = 48,
): ZoneSummary[] {
    const adjustedY = new Map<string, number>();
    for (const list of groupByFloor(zones).values()) {
        const sorted = [...list].sort(
            (a, b) => a.position.y - b.position.y || a.position.x - b.position.x,
        );
        const placed: Rect[] = [];
        for (const zone of sorted) {
            const x = zone.position.x;
            const w = zone.size.width;
            const h = estimateCardHeight(zone);
            let y = zone.position.y;
            for (const previous of placed) {
                const overlapsX = x < previous.x + previous.w && x + w > previous.x;
                if (overlapsX && y < previous.y + previous.h + minGap) {
                    y = previous.y + previous.h + minGap;
                }
            }
            placed.push({ x, y, w, h });
            adjustedY.set(zone.zoneId, Math.round(y));
        }
    }
    return zones.map((zone) => copyZone(zone, {
        x: zone.position.x,
        y: required(adjustedY.get(zone.zoneId), zone.zoneId),
    }));
}

export function floorBands(zones: readonly ZoneSummary[]): FloorBand[] {
    const bands = new Map<string, FloorBand>();
    for (const zone of zones) {
        const top = zone.position.y;
        const bottom = top + estimateCardHeight(zone);
        const existing = bands.get(zone.floor) ?? { floor: zone.floor, top, bottom };
        existing.top = Math.min(existing.top, top);
        existing.bottom = Math.max(existing.bottom, bottom);
        bands.set(zone.floor, existing);
    }
    return [...bands.values()].sort(
        (left, right) => left.top - right.top || left.floor.localeCompare(right.floor),
    );
}

export function stackFloorsByBand(
    zones: readonly ZoneSummary[],
    floorOrder: readonly string[] = [],
    gap = 96,
): ZoneSummary[] {
    const rank = (floor: string): number => {
        const index = floorOrder.indexOf(floor);
        return index === -1 ? floorOrder.length : index;
    };
    const floors = [...groupByFloor(zones)].map(([floor, list]) => ({
        floor,
        list,
        top: Math.min(...list.map((zone) => zone.position.y)),
        bottom: Math.max(...list.map((zone) => zone.position.y + estimateCardHeight(zone))),
    })).sort((left, right) =>
        rank(left.floor) - rank(right.floor) ||
        left.top - right.top ||
        left.floor.localeCompare(right.floor),
    );
    const first = floors[0];
    if (first === undefined) return [];
    const result: ZoneSummary[] = [];
    let cursor = first.top;
    for (const { list, top, bottom } of floors) {
        const shift = cursor - top;
        for (const zone of list) {
            result.push(copyZone(zone, {
                x: zone.position.x,
                y: Math.round(zone.position.y + shift),
            }));
        }
        cursor += bottom - top + gap;
    }
    return result;
}

/** Undirected visual edges, retaining first-observed orientation and order. */
export function zoneAdjacencyPairs(
    zones: readonly ZoneSummary[],
    nodes: Nodes,
): ZonePair[] {
    const zonesByNode = new Map<string, ZoneSummary>();
    for (const zone of zones) {
        for (const nodeId of zone.nodeIds) zonesByNode.set(nodeId, zone);
    }
    const seen = new Set<string>();
    const pairs: ZonePair[] = [];
    for (const zone of zones) {
        for (const nodeId of zone.nodeIds) {
            for (const targetId of nodes[nodeId]?.adjacent ?? []) {
                const target = zonesByNode.get(targetId);
                if (target === undefined || target.zoneId === zone.zoneId) continue;
                // JSON avoids collisions when zone IDs themselves contain the delimiter.
                const key = JSON.stringify([zone.zoneId, target.zoneId].sort());
                if (seen.has(key)) continue;
                seen.add(key);
                pairs.push([zone.zoneId, target.zoneId]);
            }
        }
    }
    return pairs;
}

/** Legacy signed-orientation crossing predicate (collinear lines do not cross). */
export function segmentsCross(a: Point, b: Point, c: Point, d: Point): boolean {
    const direction = (p: Point, q: Point, r: Point): number =>
        (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
    const d1 = direction(c, d, a);
    const d2 = direction(c, d, b);
    const d3 = direction(a, b, c);
    const d4 = direction(a, b, d);
    return (d1 > 0) !== (d2 > 0) && (d3 > 0) !== (d4 > 0);
}

export function pointInRect(point: Point, box: Rect): boolean {
    return point.x >= box.x && point.x <= box.x + box.w &&
        point.y >= box.y && point.y <= box.y + box.h;
}

export function segmentIntersectsRect(p1: Point, p2: Point, box: Rect): boolean {
    if (pointInRect(p1, box) || pointInRect(p2, box)) return true;
    const corners: Point[] = [
        { x: box.x, y: box.y },
        { x: box.x + box.w, y: box.y },
        { x: box.x + box.w, y: box.y + box.h },
        { x: box.x, y: box.y + box.h },
    ];
    for (let index = 0; index < corners.length; index += 1) {
        if (segmentsCross(
            p1,
            p2,
            required(corners[index], "rectangle corner"),
            required(corners[(index + 1) % corners.length], "next rectangle corner"),
        )) return true;
    }
    return false;
}

export function countCrossings(
    pairs: readonly ZonePair[],
    centerById: Readonly<Record<string, Point>>,
): number {
    const center = (id: string): Point => required(
        Object.hasOwn(centerById, id) ? centerById[id] : undefined,
        `center ${id}`,
    );
    let crossings = 0;
    for (let i = 0; i < pairs.length; i += 1) {
        const [a1, a2] = required(pairs[i], "edge");
        for (let j = i + 1; j < pairs.length; j += 1) {
            const [b1, b2] = required(pairs[j], "edge");
            if (a1 === b1 || a1 === b2 || a2 === b1 || a2 === b2) continue;
            if (segmentsCross(center(a1), center(a2), center(b1), center(b2))) {
                crossings += 1;
            }
        }
    }
    return crossings;
}

/**
 * Same-floor slot swaps minimize edge crossings + 4 × unrelated-card crossings.
 * Retains the original stable iteration, strict improvements, eight-round bound,
 * and three starts: identity, neighbor barycenter, and reversed identity.
 * Supply separated/stacked cards first; this does not invent new slots.
 */
export function minimizeCrossings(zones: readonly ZoneSummary[], nodes: Nodes): ZoneSummary[] {
    const pairs = zoneAdjacencyPairs(zones, nodes);
    if (zones.length < 3 || pairs.length < 2) return zones.map((zone) => copyZone(zone));

    const size = new Map<string, Size>();
    const originalPos = new Map<string, Point>();
    const originalCenterX = new Map<string, number>();
    for (const zone of zones) {
        size.set(zone.zoneId, { width: zone.size.width, height: estimateCardHeight(zone) });
        originalPos.set(zone.zoneId, { ...zone.position });
        originalCenterX.set(zone.zoneId, zone.position.x + zone.size.width / 2);
    }
    const original = (id: string): Point => required(originalPos.get(id), `original ${id}`);
    const originalX = (id: string): number => required(originalCenterX.get(id), `center ${id}`);
    const byFloor = new Map<string, string[]>();
    for (const [floor, list] of groupByFloor(zones)) {
        byFloor.set(floor, list.map((zone) => zone.zoneId));
    }
    const slots = new Map<string, Point[]>();
    const identityOrder = new Map<string, string[]>();
    for (const [floor, ids] of byFloor) {
        const sorted = [...ids].sort((a, b) =>
            original(a).x - original(b).x || original(a).y - original(b).y,
        );
        identityOrder.set(floor, sorted);
        slots.set(floor, sorted.map((id) => ({ ...original(id) })));
    }

    const position = new Map<string, Point>();
    const current = (id: string): Point => required(position.get(id), `position ${id}`);
    const dimensions = (id: string): Size => required(size.get(id), `size ${id}`);
    const applyOrder = (order: ReadonlyMap<string, readonly string[]>): void => {
        for (const [floor, ids] of order) {
            const floorSlots = required(slots.get(floor), `floor ${floor}`);
            ids.forEach((id, index) => {
                position.set(id, { ...required(floorSlots[index], `slot ${floor}/${index}`) });
            });
        }
    };
    const rectOf = (id: string): Rect => ({
        ...current(id), w: dimensions(id).width, h: dimensions(id).height,
    });
    const cost = (): number => {
        const centers: Record<string, Point> = Object.fromEntries(zones.map((zone): [string, Point] => [
            zone.zoneId,
            {
                x: current(zone.zoneId).x + dimensions(zone.zoneId).width / 2,
                y: current(zone.zoneId).y + dimensions(zone.zoneId).height / 2,
            },
        ]));
        const center = (id: string): Point => required(centers[id], `center ${id}`);
        let total = countCrossings(pairs, centers);
        for (const [a, b] of pairs) {
            for (const zone of zones) {
                if (zone.zoneId === a || zone.zoneId === b) continue;
                if (segmentIntersectsRect(center(a), center(b), rectOf(zone.zoneId))) total += 4;
            }
        }
        return total;
    };
    const overlaps = (): boolean => {
        for (let i = 0; i < zones.length; i += 1) {
            const a = rectOf(required(zones[i], "zone").zoneId);
            for (let j = i + 1; j < zones.length; j += 1) {
                const b = rectOf(required(zones[j], "zone").zoneId);
                if (a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y) {
                    return true;
                }
            }
        }
        return false;
    };
    const swap = (a: string, b: string): void => {
        const saved = current(a);
        position.set(a, current(b));
        position.set(b, saved);
    };
    const localSearch = (): number => {
        let best = cost();
        let improved = true;
        let rounds = 0;
        while (improved && rounds < 8 && best > 0) {
            improved = false;
            rounds += 1;
            for (const ids of byFloor.values()) {
                for (let i = 0; i < ids.length; i += 1) {
                    for (let j = i + 1; j < ids.length; j += 1) {
                        const a = required(ids[i], "swap source");
                        const b = required(ids[j], "swap target");
                        swap(a, b);
                        const trial = cost();
                        if (trial < best && !overlaps()) {
                            best = trial;
                            improved = true;
                        } else {
                            swap(a, b);
                        }
                    }
                }
            }
        }
        return best;
    };

    const neighborsOf = (id: string): string[] => pairs
        .filter(([a, b]) => a === id || b === id)
        .map(([a, b]) => a === id ? b : a);
    const bary = (id: string): number => {
        const neighbors = neighborsOf(id);
        if (!neighbors.length) return originalX(id);
        return neighbors.reduce((sum, neighbor) => sum + originalX(neighbor), 0) / neighbors.length;
    };
    const barycenterOrder = new Map<string, string[]>();
    const reversedOrder = new Map<string, string[]>();
    for (const [floor, ids] of byFloor) {
        barycenterOrder.set(floor, [...ids].sort((a, b) =>
            bary(a) - bary(b) || original(a).x - original(b).x,
        ));
        reversedOrder.set(floor, [...required(identityOrder.get(floor), floor)].reverse());
    }

    let bestCost = Infinity;
    let bestPositions = new Map(originalPos);
    for (const start of [identityOrder, barycenterOrder, reversedOrder]) {
        applyOrder(start);
        const result = localSearch();
        // Alternate starts can overlap when slot occupants have unequal dimensions.
        // Guard the final start as well as each swap, including zero-cost starts.
        if (result < bestCost && !overlaps()) {
            bestCost = result;
            bestPositions = new Map(zones.map((zone) => [zone.zoneId, { ...current(zone.zoneId) }]));
        }
    }
    return zones.map((zone) => copyZone(
        zone, required(bestPositions.get(zone.zoneId), `best ${zone.zoneId}`),
    ));
}

export function spacedZoneSummaries(
    zones: readonly ZoneSummary[],
    scaleX = 1.22,
    scaleY = 1.18,
): ZoneSummary[] {
    if (!zones.length) return [];
    const originX = Math.min(...zones.map((zone) => zone.position.x));
    const originY = Math.min(...zones.map((zone) => zone.position.y));
    return zones.map((zone) => copyZone(zone, {
        x: Math.round(originX + (zone.position.x - originX) * scaleX),
        y: Math.round(originY + (zone.position.y - originY) * scaleY),
    }));
}