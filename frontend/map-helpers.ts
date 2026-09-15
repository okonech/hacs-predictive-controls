import type { Entity, MapNode, PredictiveMap, Status } from './types.ts';
import type { ZoneSummary } from './layout.ts';
import { titleFromId } from './formatting.ts';
export { normalizeEntityResponse } from './decoders.ts';

export function sanitizeNodeId(value: string): string {
    return (value || 'node').replace(/^.*\./, '').replace(/[^a-zA-Z0-9_]/g, '_').replace(/^_+|_+$/g, '') || 'node';
}
export function uniqueNodeId(nodes: Record<string, MapNode>, base: string): string {
    const sanitized = sanitizeNodeId(base);
    let candidate = sanitized;
    let index = 2;
    while (Object.hasOwn(nodes, candidate)) candidate = `${sanitized}_${index++}`;
    return candidate;
}
function coordinate(value: number): number {
    if (!Number.isFinite(value)) throw new Error('Coordinate must be finite');
    return Math.round(Math.max(0, value));
}
function defaults(): MapNode {
    return { entities: {}, adjacent: [], role: 'room_occupancy', occupancy_behavior: 'sustained', reliability: 1, route_prior_weight: 1, position: { x: 80, y: 80 } };
}
export function createNodeForEntity(nodes: Record<string, MapNode>, entity: Entity, x: number, y: number) {
    return { nodeId: uniqueNodeId(nodes, entity.entity_id), node: { ...defaults(), label: entity.name || entity.entity_id, entities: { motion: entity.entity_id }, position: { x: coordinate(x), y: coordinate(y) } } };
}
export function createEmptyNode(nodes: Record<string, MapNode>) {
    const nodeId = uniqueNodeId(nodes, 'node');
    return { nodeId, node: { ...defaults(), label: nodeId } };
}
export function moveNode(nodes: Record<string, MapNode>, nodeId: string, x: number, y: number) {
    const node = Object.hasOwn(nodes, nodeId) ? nodes[nodeId] : undefined;
    if (node) node.position = { ...node.position, x: coordinate(x), y: coordinate(y) };
    return nodes;
}
export function addBidirectionalEdge(nodes: Record<string, MapNode>, source: string, target: string) {
    const a = nodes[source]; const b = nodes[target];
    if (!Object.hasOwn(nodes, source) || !Object.hasOwn(nodes, target) || !a || !b || source === target) return nodes;
    a.adjacent = [...new Set([...(a.adjacent || []), target])];
    b.adjacent = [...new Set([...(b.adjacent || []), source])];
    return nodes;
}
export function removeBidirectionalEdge(nodes: Record<string, MapNode>, source: string, target: string) {
    const a = nodes[source]; const b = nodes[target];
    if (!Object.hasOwn(nodes, source) || !Object.hasOwn(nodes, target) || !a || !b) return nodes;
    a.adjacent = (a.adjacent || []).filter(id => id !== target);
    b.adjacent = (b.adjacent || []).filter(id => id !== source);
    return nodes;
}
export function renameNode(nodes: Record<string, MapNode>, oldId: string, newId: string): string {
    const id = sanitizeNodeId(newId); const node = nodes[oldId];
    if (!Object.hasOwn(nodes, oldId) || !node || id === oldId || Object.hasOwn(nodes, id)) return oldId;
    Object.defineProperty(nodes, id, { value: node, enumerable: true, writable: true, configurable: true });
    delete nodes[oldId];
    for (const n of Object.values(nodes)) n.adjacent = (n.adjacent || []).map(target => target === oldId ? id : target);
    return id;
}
export function deleteNode(nodes: Record<string, MapNode>, nodeId: string) {
    if (!Object.hasOwn(nodes, nodeId)) return nodes;
    delete nodes[nodeId];
    for (const node of Object.values(nodes)) node.adjacent = (node.adjacent || []).filter(id => id !== nodeId);
    return nodes;
}
export function entityMatchesFilter(entity: Entity, filter: string): boolean {
    const query = filter.toLowerCase();
    return !query || [entity.entity_id, entity.name, entity.device_class, entity.state].some(v => v?.toLowerCase().includes(query));
}
export function defaultBehaviorForRole(role: string | undefined): string {
    if (role === 'transition_gate') return 'transient';
    if (role === 'ambiguous_open_plan') return 'ambiguous';
    if (role === 'anchor_sensor') return 'sticky';
    return 'sustained';
}
export function zoneSummaries(map: PredictiveMap): ZoneSummary[] {
    const grouped = new Map<string, { nodeId: string; node: MapNode }[]>();
    for (const [nodeId, node] of Object.entries(map.nodes)) {
        const id = node.zone || nodeId;
        const list = grouped.get(id) || [];
        list.push({ nodeId, node }); grouped.set(id, list);
    }
    for (const id of Object.keys(map.zones || {})) if (!grouped.has(id)) grouped.set(id, []);
    return [...grouped].map(([zoneId, entries]) => {
        const config = map.zones?.[zoneId] || {};
        const positions = entries.flatMap(({ node }) => node.position ? [node.position] : []);
        const average = positions.length ? { x: Math.round(positions.reduce((sum, p) => sum + p.x, 0) / positions.length), y: Math.round(positions.reduce((sum, p) => sum + p.y, 0) / positions.length) } : { x: 80, y: 80 };
        const roles = new Set(entries.map(({ node }) => node.role).filter(v => v !== undefined));
        const behaviors = new Set(entries.map(({ node }) => node.occupancy_behavior).filter(v => v !== undefined));
        const role = config.role || (roles.size === 1 ? [...roles][0] : undefined) || 'mixed';
        return {
            zoneId, label: config.label || titleFromId(zoneId), floor: config.floor || entries.find(({ node }) => node.floor)?.node.floor || 'unassigned', role,
            occupancyBehavior: config.occupancy_behavior || (behaviors.size === 1 ? [...behaviors][0] : undefined) || defaultBehaviorForRole(role),
            position: { ...(config.position || average) }, size: { ...(config.size || { width: 210, height: 112 }) }, nodeIds: entries.map(e => e.nodeId)
        };
    }).sort((a, b) => a.floor.localeCompare(b.floor) || a.label.localeCompare(b.label));
}
export function learnedTransitionRows(map: PredictiveMap, status: Status | undefined) {
    const rows: { sourceId: string; targetId: string; sourceLabel: string; targetLabel: string; count: number }[] = [];
    for (const [sourceId, targets] of Object.entries(status?.transition_counts || {})) {
        for (const [targetId, count] of Object.entries(targets)) {
            if (count > 0) rows.push({ sourceId, targetId, sourceLabel: map.nodes[sourceId]?.label || titleFromId(sourceId), targetLabel: map.nodes[targetId]?.label || titleFromId(targetId), count });
        }
    }
    return rows.sort((a, b) => b.count - a.count || a.sourceLabel.localeCompare(b.sourceLabel) || a.targetLabel.localeCompare(b.targetLabel));
}