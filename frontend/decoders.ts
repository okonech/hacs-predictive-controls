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
function unsupportedCount(value: unknown): number | null {
    if (value === null) return null;
    if (typeof value !== 'number' || !Number.isFinite(value) || !Number.isInteger(value) || value <= 2) {
        throw new Error('unsupported_count must be null or an integer greater than two');
    }
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
/** Compare UTC producer timestamps without losing sub-millisecond input order. */
function instant(value: string): bigint {
    const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(value);
    const seconds = match?.[1];
    const milliseconds = seconds === undefined ? NaN : Date.parse(`${seconds}Z`);
    if (!seconds || !Number.isFinite(milliseconds) || new Date(milliseconds).toISOString().slice(0, 19) !== seconds) throw new Error('Invalid visit timestamp');
    return BigInt(milliseconds) * 1000n + BigInt((match?.[2] || '').padEnd(6, '0'));
}
function timestamp(value: unknown): string { const s = text(value); instant(s); return s; }
function bounded(value: unknown, minimum: number, maximum: number, name: string): unknown[] {
    if (!Array.isArray(value) || value.length < minimum || value.length > maximum) throw new Error(`Invalid bounded selected ${name}`);
    return value;
}
function visit(value: unknown): Visit {
    const r = record(value); const kind = text(r.kind);
    if (kind !== 'positive' && kind !== 'correlated_positive' && kind !== 'interaction') throw new Error('Invalid visit kind');
    return { node_id: identity(r.node_id), zone: identity(r.zone), episode_id: identity(r.episode_id), branch_active: bool(r.branch_active), at: timestamp(r.at), kind };
}
function sameVisit(a: Visit, b: Visit): boolean {
    return a.node_id === b.node_id && a.zone === b.zone && a.episode_id === b.episode_id && a.at === b.at && a.kind === b.kind && a.branch_active === b.branch_active;
}
function compareVisits(a: Visit, b: Visit): number {
    const timeA = instant(a.at); const timeB = instant(b.at);
    if (timeA !== timeB) return timeA < timeB ? -1 : 1;
    // Python tuple/string ordering, not locale-dependent UI collation.
    for (const [left, right] of [[a.node_id, b.node_id], [a.zone, b.zone], [a.episode_id, b.episode_id], [a.kind, b.kind]]) {
        if (left !== undefined && right !== undefined && left !== right) {
            const l = Array.from(left, c => c.codePointAt(0) || 0); const r = Array.from(right, c => c.codePointAt(0) || 0);
            for (let i = 0; i < Math.min(l.length, r.length); i++) {
                const x = l[i]; const y = r[i];
                if (x !== undefined && y !== undefined && x !== y) return x < y ? -1 : 1;
            }
            return l.length < r.length ? -1 : 1;
        }
    }
    return Number(a.branch_active) - Number(b.branch_active);
}
function validateSelectedPath(path: SelectedPath): void {
    const routes = [path.route, ...path.branch_routes];
    const inventory = new Map<string, Visit>();
    const parents = new Map<string, string>();
    for (const records of [path.visits, ...routes]) {
        const seen = new Set<string>();
        for (const [index, item] of records.entries()) {
            if (seen.has(item.episode_id)) throw new Error('Invalid bounded selected route: repeated observation');
            seen.add(item.episode_id);
            const copy = inventory.get(item.episode_id);
            if (copy && !sameVisit(copy, item)) throw new Error('Selected occurrence copies disagree');
            inventory.set(item.episode_id, item);
            const previous = records[index - 1];
            if (previous) {
                if (instant(previous.at) > instant(item.at)) throw new Error('Selected observations are out of order');
                // Visits encode chronology, NOT geometry or recorded parentage.
                if (records !== path.visits) {
                    const parent = parents.get(item.episode_id);
                    if (parent && parent !== previous.episode_id) throw new Error('Selected occurrence has conflicting parents');
                    parents.set(item.episode_id, previous.episode_id);
                }
            }
        }
    }
    const endpoint = path.route.at(-1); const latest = path.visits.at(-1);
    if (!endpoint || !latest || !sameVisit(endpoint, latest)) throw new Error('Selected history endpoint disagrees with route');
    if (!path.endpoint_eligible && endpoint.branch_active) throw new Error('Revoked endpoint cannot retain branch authority');
    if (instant(path.spatial_at) > instant(latest.at)) throw new Error('Selected spatial frontier is in the future');
    if (path.endpoint && !sameVisit(path.endpoint, endpoint)) throw new Error('Selected endpoint disagrees with route');
    if (path.updated_at !== undefined && instant(path.updated_at) !== instant(latest.at)) throw new Error('Selected updated frontier disagrees with history');
    const first = path.visits[0];
    if (first && (path.visits.length < 4 || instant(path.spatial_at) >= instant(first.at)) && !path.visits.some(v => instant(v.at) === instant(path.spatial_at))) throw new Error('Selected spatial frontier was not observed');
    const main = new Set(path.route.map(v => v.episode_id));
    const tips = new Set<string>();
    let previousTip: Visit | undefined;
    for (const branch of path.branch_routes) {
        const tip = branch.at(-1);
        if (!tip || !tip.branch_active || tip.kind === 'interaction' || main.has(tip.episode_id) || !path.visits.some(v => sameVisit(v, tip))) throw new Error('Invalid selected overlap tip');
        if (tips.has(tip.episode_id) || (previousTip && compareVisits(previousTip, tip) >= 0)) throw new Error('Selected overlap tips are not canonical and unique');
        tips.add(tip.episode_id); previousTip = tip;
    }
    for (const item of inventory.values()) {
        if (item.branch_active && !main.has(item.episode_id) && !tips.has(item.episode_id)) throw new Error('Prefix-only history cannot retain branch authority');
    }
}
/** Validate the whole transmitted selection, without inventing a source ledger. */
function validateSelectedChronology(paths: (SelectedPath | null)[]): void {
    const inventory = new Map<string, Visit>();
    const order = new Map<string, Set<string>>();
    for (const path of paths) {
        if (!path) continue;
        for (const records of [path.visits, path.route, ...path.branch_routes]) {
            for (const [index, item] of records.entries()) {
                inventory.set(item.episode_id, item);
                if (!order.has(item.episode_id)) order.set(item.episode_id, new Set());
                const previous = records[index - 1];
                if (previous) order.get(previous.episode_id)?.add(item.episode_id);
            }
        }
    }
    const byNode = new Map<string, Map<bigint, Visit>>();
    for (const item of inventory.values()) {
        // The producer encodes node:canonical-decimal-generation:timestamp.
        // Existing opaque IDs remain supported: this is ordering evidence, not
        // a new mandatory identity format or suffix/occurrence equality check.
        const prefix = `${item.node_id}:`;
        if (!item.episode_id.startsWith(prefix)) continue;
        const digits = /^([1-9][0-9]*):/.exec(item.episode_id.slice(prefix.length))?.[1];
        if (digits === undefined) continue;
        const generation = BigInt(digits);
        const generations = byNode.get(item.node_id) || new Map<bigint, Visit>();
        const previous = generations.get(generation);
        if (previous && (previous.episode_id !== item.episode_id || instant(previous.at) !== instant(item.at))) throw new Error('Selected generation has conflicting occurrences');
        generations.set(generation, item); byNode.set(item.node_id, generations);
    }
    for (const generations of byNode.values()) {
        const ordered = [...generations.entries()].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
        for (let index = 1; index < ordered.length; index++) {
            const previous = ordered[index - 1]?.[1]; const current = ordered[index]?.[1];
            if (!previous || !current) continue;
            if (instant(previous.at) > instant(current.at)) throw new Error('Selected generation chronology is inconsistent');
            order.get(previous.episode_id)?.add(current.episode_id);
        }
    }
    // Repeated copies are one occurrence. Forks are legal; cycles are not, even
    // when equal-time history contradicts generation order in a different slot.
    const visiting = new Set<string>(); const complete = new Set<string>();
    function walk(id: string): void {
        if (visiting.has(id)) throw new Error('Selected occurrence chronology is cyclic');
        if (complete.has(id)) return;
        visiting.add(id);
        for (const next of order.get(id) || []) walk(next);
        visiting.delete(id); complete.add(id);
    }
    for (const id of inventory.keys()) walk(id);
}
export function decodeSelectedPaths(value: unknown): (SelectedPath | null)[] {
    // Preflight EVERY raw bound before decoding any leaf in any slot.
    const raw = bounded(value, 0, 2, 'slot count');
    const records = raw.map(v => {
        if (v === null) return null;
        const r = record(v);
        bounded(r.visits, 1, 4, 'visits'); bounded(r.route, 1, 4, 'route');
        for (const branch of bounded(r.branch_routes, 0, 3, 'overlap routes')) bounded(branch, 1, 4, 'overlap route');
        return r;
    });
    const owned = new Set<string>();
    const paths = records.map(r => {
        if (r === null) return null;
        const confidence = text(r.track_confidence);
        if (confidence !== 'provisional' && confidence !== 'confirmed') throw new Error('Invalid track confidence');
        const result: SelectedPath = { visits: list(r.visits, visit), route: list(r.route, visit), branch_routes: list(r.branch_routes, v => list(v, visit)), spatial_at: timestamp(r.spatial_at), track_confidence: confidence, endpoint_eligible: bool(r.endpoint_eligible) };
        optional(r, 'endpoint', visit, v => result.endpoint = v);
        optional(r, 'updated_at', timestamp, v => result.updated_at = v);
        optional(r, 'covered_node_ids', strings, v => result.covered_node_ids = v);
        optional(r, 'covered_zones', strings, v => result.covered_zones = v);
        optional(r, 'eligible_node_ids', strings, v => result.eligible_node_ids = v);
        validateSelectedPath(result);
        const ids = new Set([...result.visits, ...result.route, ...result.branch_routes.flat()].map(v => v.episode_id));
        for (const id of ids) {
            if (owned.has(id)) throw new Error('Selected occurrence belongs to multiple slots');
            owned.add(id);
        }
        return result;
    });
    validateSelectedChronology(paths);
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
    optional(r, 'unsupported_count', unsupportedCount, v => d.unsupported_count = v);
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
        try {
            if (r.selected_path_version !== 2) throw new Error('Unsupported selected_path_version: expected 2');
            d.selected_path_version = 2;
            d.selected_paths = decodeSelectedPaths(r.selected_paths);
        }
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