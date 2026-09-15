import type { Authorization, AuditEntry, Config, Diagnostics, Entity, Episode, Frontier, MapNode, MapZone, PathHealth, Policy, PredictiveMap, SelectedPath, Status, Visit, Warning, ZoneState } from './types.ts';

export function record(value: unknown): Record<string, unknown> {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('Expected an object');
    return Object.fromEntries(Object.entries(value));
}
export function text(value: unknown): string {
    if (typeof value !== 'string') throw new Error('Expected a string');
    return value;
}
function identity(value: unknown): string {
    const result = text(value);
    if (!result) throw new Error('Expected a nonempty identity');
    return result;
}
export function finite(value: unknown): number {
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('Expected a finite number');
    return value;
}
function probability(value: unknown): number {
    const n = finite(value);
    if (n < 0 || n > 1) throw new Error('Probability must be between zero and one');
    return n;
}
function positive(value: unknown): number {
    const n = finite(value);
    if (n <= 0) throw new Error('Expected a positive number');
    return n;
}
function bool(value: unknown): boolean {
    if (typeof value !== 'boolean') throw new Error('Expected a Boolean');
    return value;
}
function nullableText(value: unknown): string | null { return value === null ? null : text(value); }
export function list<T>(value: unknown, decode: (value: unknown) => T): T[] {
    if (!Array.isArray(value)) throw new Error('Expected an array');
    // Array.isArray narrows the container; each item is still untrusted.
    return value.map((item: unknown) => decode(item));
}
function strings(value: unknown): string[] { return list(value, text); }
export function dictionary<T>(value: unknown, decode: (value: unknown) => T): Record<string, T> {
    return Object.fromEntries(Object.entries(record(value)).map(([key, item]) => [key, decode(item)]));
}
function optional<T>(source: Record<string, unknown>, key: string, decode: (v: unknown) => T, assign: (v: T) => void): void {
    if (Object.hasOwn(source, key)) assign(decode(source[key]));
}
function point(value: unknown) {
    const p = record(value);
    return { ...dictionary(p, jsonData), x: finite(p.x), y: finite(p.y) };
}
/** Validate extensions recursively, without normalizing/removing their values. */
function jsonData(value: unknown): unknown {
    if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
    if (typeof value === 'number') return finite(value);
    if (Array.isArray(value)) return list(value, jsonData);
    return dictionary(value, jsonData);
}
export function decodeEntitiesMap(value: unknown): Record<string, string | string[]> {
    return dictionary(value, v => Array.isArray(v) ? strings(v) : text(v));
}
export function decodeNode(value: unknown): MapNode {
    const r = record(value);
    const node: MapNode = dictionary(r, jsonData);
    optional(r, 'label', text, v => node.label = v);
    optional(r, 'zone', identity, v => node.zone = v);
    optional(r, 'floor', text, v => node.floor = v);
    optional(r, 'role', text, v => node.role = v);
    optional(r, 'occupancy_behavior', text, v => node.occupancy_behavior = v);
    optional(r, 'entities', decodeEntitiesMap, v => node.entities = v);
    optional(r, 'adjacent', strings, v => node.adjacent = v);
    optional(r, 'position', point, v => node.position = v);
    optional(r, 'reliability', probability, v => node.reliability = v);
    optional(r, 'route_prior_weight', positive, v => node.route_prior_weight = v);
    return node;
}
function decodeZone(value: unknown): MapZone {
    const r = record(value);
    const zone: MapZone = dictionary(r, jsonData);
    optional(r, 'label', text, v => zone.label = v);
    optional(r, 'floor', text, v => zone.floor = v);
    optional(r, 'role', text, v => zone.role = v);
    optional(r, 'occupancy_behavior', text, v => zone.occupancy_behavior = v);
    optional(r, 'position', point, v => zone.position = v);
    optional(r, 'size', v => { const s = record(v); return { ...dictionary(s, jsonData), width: positive(s.width), height: positive(s.height) }; }, v => zone.size = v);
    return zone;
}
export function decodeMap(value: unknown): PredictiveMap {
    const r = record(value);
    const map: PredictiveMap = { ...dictionary(r, jsonData), nodes: dictionary(r.nodes, decodeNode) };
    optional(r, 'zones', v => dictionary(v, decodeZone), v => map.zones = v);
    optional(r, 'floors', strings, v => map.floors = v);
    return map;
}
export function decodeConfig(value: unknown): Config {
    const r = record(value);
    const config: Config = {
        entry_id: identity(r.entry_id), map: decodeMap(r.map), map_yaml: text(r.map_yaml),
        transition_window_seconds: positive(r.transition_window_seconds), expected_occupants: finite(r.expected_occupants),
    };
    optional(r, 'title', text, v => config.title = v);
    optional(r, 'expected_occupants_entity', text, v => config.expected_occupants_entity = v);
    validateSettings(config);
    return config;
}
export function validateSettings(config: Config): void {
    if (!Number.isInteger(config.transition_window_seconds) || config.transition_window_seconds < 1) throw new Error('Transition window must be a positive integer');
    if (!Number.isInteger(config.expected_occupants) || config.expected_occupants < 0 || config.expected_occupants > 2) throw new Error('Expected occupants must be zero, one or two');
    if (config.expected_occupants_entity && !config.expected_occupants_entity.includes('.')) throw new Error('Expected occupants entity must be an entity id');
}
export function normalizeEntityResponse(value: unknown): Entity[] {
    const r = record(value);
    return list(r.entities, v => {
        const row = record(v);
        const e: Entity = { entity_id: identity(row.entity_id) };
        optional(row, 'name', text, x => e.name = x);
        optional(row, 'state', text, x => e.state = x);
        optional(row, 'device_class', nullableText, x => e.device_class = x);
        return e;
    }).sort((a, b) => a.entity_id.localeCompare(b.entity_id));
}
function visit(value: unknown): Visit {
    const r = record(value);
    const result: Visit = { node_id: identity(r.node_id), zone: identity(r.zone), episode_id: identity(r.episode_id), branch_active: bool(r.branch_active) };
    optional(r, 'at', text, v => { if (!Number.isFinite(Date.parse(v))) throw new Error('Invalid visit timestamp'); result.at = v; });
    optional(r, 'kind', text, v => { if (!['positive', 'correlated_positive', 'interaction'].includes(v)) throw new Error('Invalid visit kind'); result.kind = v; });
    return result;
}
export function decodeSelectedPaths(value: unknown): (SelectedPath | null)[] {
    const paths = list(value, v => {
        if (v === null) return null;
        const r = record(v);
        const confidence = text(r.track_confidence);
        if (confidence !== 'provisional' && confidence !== 'confirmed') throw new Error('Invalid track confidence');
        const route = list(r.route, visit);
        if (route.length < 1 || route.length > 4 || new Set(route.map(item => item.episode_id)).size !== route.length) throw new Error('Invalid bounded selected route');
        const result: SelectedPath = { route, track_confidence: confidence, endpoint_eligible: bool(r.endpoint_eligible) };
        optional(r, 'endpoint', visit, endpoint => {
            const last = route.at(-1);
            if (!last || endpoint.node_id !== last.node_id || endpoint.zone !== last.zone || endpoint.episode_id !== last.episode_id || endpoint.branch_active !== last.branch_active) throw new Error('Selected endpoint disagrees with route');
            result.endpoint = endpoint;
        });
        return result;
    });
    if (paths.length > 2) throw new Error('Unsupported selected slot count');
    return paths;
}
function episode(value: unknown): Episode {
    const r = record(value); const result: Episode = { node_id: identity(r.node_id) };
    optional(r, 'zone', text, v => result.zone = v);
    optional(r, 'episode_id', nullableText, v => result.episode_id = v);
    optional(r, 'status', text, v => result.status = v);
    return result;
}
function health(value: unknown): PathHealth {
    const r = record(value); const phase = text(r.phase);
    if (phase !== 'on' && phase !== 'off' && phase !== 'unknown' && phase !== 'clearing') throw new Error('Invalid physical phase');
    return { node_id: identity(r.node_id), zone: identity(r.zone), phase };
}
function warning(value: unknown): Warning {
    const r = record(value);
    const result: Warning = { node_id: identity(r.node_id), zone: identity(r.zone), kind: text(r.kind), active: bool(r.active) };
    optional(r, 'reasons', strings, v => result.reasons = v);
    optional(r, 'last_observed_at', nullableText, v => result.last_observed_at = v);
    return result;
}
function policy(value: unknown): Policy {
    const r = record(value); const result: Policy = { active: bool(r.active) };
    optional(r, 'profile', text, v => result.profile = v);
    optional(r, 'pending_release_since', nullableText, v => result.pending_release_since = v);
    return result;
}
function audit(value: unknown): AuditEntry {
    const r = record(value); const result: AuditEntry = {};
    optional(r, 'event_at', text, v => result.event_at = v);
    optional(r, 'zone', text, v => result.zone = v);
    optional(r, 'active_before', bool, v => result.active_before = v);
    optional(r, 'active_after', bool, v => result.active_after = v);
    optional(r, 'belief_after', probability, v => result.belief_after = v);
    optional(r, 'traversal_reason', nullableText, v => result.traversal_reason = v);
    optional(r, 'evidence_ids', strings, v => result.evidence_ids = v);
    optional(r, 'event_kind', nullableText, v => result.event_kind = v);
    optional(r, 'reason', text, v => result.reason = v);
    return result;
}
function frontier(value: unknown): Frontier {
    const r = record(value); const result: Frontier = { token_id: identity(r.token_id) };
    optional(r, 'zone', text, v => result.zone = v);
    optional(r, 'valid_until', text, v => result.valid_until = v);
    return result;
}
function authorization(value: unknown): Authorization {
    const r = record(value); const result: Authorization = { authorized: bool(r.authorized) };
    optional(r, 'source_token_ids', strings, v => result.source_token_ids = v);
    optional(r, 'target_zone', text, v => result.target_zone = v);
    optional(r, 'reason', text, v => result.reason = v);
    return result;
}
export function decodeDiagnostics(value: unknown): Diagnostics {
    const r = record(value); const d: Diagnostics = {};
    optional(r, 'model', text, v => d.model = v);
    optional(r, 'expected_occupants', finite, v => d.expected_occupants = v);
    optional(r, 'unsupported_count', bool, v => d.unsupported_count = v);
    optional(r, 'beliefs', v => dictionary(v, probability), v => d.beliefs = v);
    optional(r, 'policy', v => dictionary(v, policy), v => d.policy = v);
    optional(r, 'policy_audit', v => list(v, audit), v => d.policy_audit = v);
    optional(r, 'episodes', v => list(v, episode), v => d.episodes = v);
    optional(r, 'path_health', v => list(v, health), v => d.path_health = v);
    optional(r, 'reliability_warnings', v => list(v, warning), v => d.reliability_warnings = v);
    optional(r, 'health_warnings', strings, v => d.health_warnings = v);
    optional(r, 'processing', v => { const p = record(v); const result: { token_count?: number } = {}; optional(p, 'token_count', finite, n => result.token_count = n); return result; }, v => d.processing = v);
    optional(r, 'traversal_frontier', v => list(v, frontier), v => d.traversal_frontier = v);
    optional(r, 'authorizations', v => list(v, authorization), v => d.authorizations = v);
    if (Object.hasOwn(r, 'selected_paths')) {
        try { d.selected_paths = decodeSelectedPaths(r.selected_paths); }
        catch (error) { d.selected_paths_error = error instanceof Error ? error.message : 'Invalid selected paths'; }
    }
    return d;
}
function zoneState(value: unknown): ZoneState {
    const r = record(value); const result: ZoneState = {};
    optional(r, 'confidence', probability, v => result.confidence = v);
    optional(r, 'status', text, v => result.status = v);
    optional(r, 'reason', text, v => result.reason = v);
    optional(r, 'occupancy_behavior', text, v => result.occupancy_behavior = v);
    optional(r, 'last_node_id', nullableText, v => result.last_node_id = v);
    return result;
}
export function decodeStatus(value: unknown): Status {
    const r = record(value); const result: Status = {};
    optional(r, 'expected_occupants', finite, v => result.expected_occupants = v);
    optional(r, 'zone_states', v => dictionary(v, zoneState), v => result.zone_states = v);
    optional(r, 'transition_counts', v => dictionary(v, row => dictionary(row, finite)), v => result.transition_counts = v);
    optional(r, 'occupancy_diagnostics', decodeDiagnostics, v => result.occupancy_diagnostics = v);
    return result;
}
export function decodeCleanup(value: unknown, preview: boolean): number {
    const r = record(value); const count = finite(preview ? r.stale_count : r.removed_count);
    if (!Number.isInteger(count) || count < 0) throw new Error('Invalid cleanup count');
    return count;
}