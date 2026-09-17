import type { Diagnostics, Frontier, PredictiveMap, SelectedPath, Visit } from './types.ts';

export type PathRole = 'neutral' | 'candidate' | 'history' | 'presence';
export interface Membership { role: PathRole; slots: number[] }
export interface Occurrence {
    visit: Visit; role: 'presence' | 'history'; valid: boolean;
    phase: 'ON' | 'OFF' | 'Unknown'; issue: string | undefined;
}
export interface PathSlot {
    slot: number; path: SelectedPath | null; occurrences: Occurrence[];
    overlaps: Occurrence[][];
}
export interface PathSegment {
    slot: number; from: string; to: string; sourceZone: string; targetZone: string;
}
export interface PathProjection {
    state: 'selected' | 'legacy' | 'unavailable'; message: string;
    slots: PathSlot[]; nodes: Map<string, Membership>; zones: Map<string, Membership>;
    segments: PathSegment[];
    frontierTokens: Frontier[]; frontierZones: Set<string>;
    authorizedPaths: { sourceZone: string; targetZone: string }[];
}
const strength: Record<PathRole, number> = { neutral: 0, candidate: 1, history: 2, presence: 3 };
function add(target: Map<string, Membership>, id: string, role: PathRole, slot: number): void {
    const previous = target.get(id) || { role: 'neutral', slots: [] };
    target.set(id, { role: strength[role] > strength[previous.role] ? role : previous.role, slots: [...new Set([...previous.slots, slot])].sort((a, b) => a - b) });
}
/** Duplicate identities are deliberately unjoinable, not last-writer-wins. */
function indexUnique<T extends { node_id: string }>(rows: readonly T[]): Map<string, T | undefined> {
    const index = new Map<string, T | undefined>();
    for (const row of rows) index.set(row.node_id, index.has(row.node_id) ? undefined : row);
    return index;
}
function validCount(count: number): boolean { return Number.isInteger(count) && count >= 0 && count <= 2; }
export function projectPaths(map: PredictiveMap, diagnostics: Diagnostics | undefined, snapshotCount?: number): PathProjection {
    const result: PathProjection = { state: 'selected', message: '', slots: [], nodes: new Map(), zones: new Map(), segments: [], frontierTokens: [], frontierZones: new Set(), authorizedPaths: [] };
    for (const [id, node] of Object.entries(map.nodes)) {
        result.nodes.set(id, { role: 'neutral', slots: [] });
        result.zones.set(node.zone || id, { role: 'neutral', slots: [] });
    }
    for (const zone of Object.keys(map.zones || {})) result.zones.set(zone, { role: 'neutral', slots: [] });
    if (diagnostics?.selected_paths_error) {
        result.state = 'unavailable'; result.message = `Selected paths unavailable: ${diagnostics.selected_paths_error}`; return result;
    }
    if (!diagnostics || !Object.hasOwn(diagnostics, 'selected_paths')) {
        result.state = 'legacy'; result.message = 'Legacy path display — selected paths not supplied by server';
        result.frontierTokens = diagnostics?.traversal_frontier || [];
        result.frontierZones = new Set(result.frontierTokens.flatMap(t => t.zone ? [t.zone] : []));
        const tokens = new Map(result.frontierTokens.map(t => [t.token_id, t]));
        const seen = new Set<string>();
        for (const auth of diagnostics?.authorizations || []) {
            if (!auth.authorized || !auth.target_zone) continue;
            for (const id of auth.source_token_ids || []) {
                const sourceZone = tokens.get(id)?.zone;
                const key = JSON.stringify([sourceZone, auth.target_zone]);
                if (sourceZone && sourceZone !== auth.target_zone && !seen.has(key)) {
                    seen.add(key); result.authorizedPaths.push({ sourceZone, targetZone: auth.target_zone });
                }
            }
        }
        return result;
    }
    const paths = diagnostics.selected_paths;
    const counts = [snapshotCount, diagnostics.expected_occupants].filter(v => v !== undefined);
    if (diagnostics.selected_path_version !== 2 || !paths || paths.length > 2 || diagnostics.unsupported_count || counts.some(count => !validCount(count) || count !== paths.length)) {
        result.state = 'unavailable'; result.message = 'Selected paths unavailable: inconsistent snapshot count'; return result;
    }
    const validVisit = (visit: Visit): boolean => Object.hasOwn(map.nodes, visit.node_id) && (map.nodes[visit.node_id]?.zone || visit.node_id) === visit.zone;
    // A partial or edited map cannot validate a witness. Fail selection closed,
    // retaining independent belief/policy cards rather than drawing a shortcut.
    for (const path of paths) {
        if (!path) continue;
        if (![...path.visits, ...path.route, ...path.branch_routes.flat()].every(validVisit) || [path.route, ...path.branch_routes].some(route => route.some((v, i) => {
            const previous = route[i - 1];
            return previous && previous.zone !== v.zone && !map.nodes[previous.node_id]?.adjacent?.includes(v.node_id);
        }))) {
            result.state = 'unavailable'; result.message = 'Selected paths unavailable: map geometry or membership disagrees'; return result;
        }
    }
    const episodes = indexUnique(diagnostics.episodes || []);
    const health = indexUnique(diagnostics.path_health || []);
    for (const [index, path] of paths.entries()) {
        const slot = index + 1;
        const row: PathSlot = { slot, path, occurrences: [], overlaps: [] };
        result.slots.push(row);
        if (!path) continue;
        function occurrence(visit: Visit, authoritative: boolean): Occurrence {
            const valid = validVisit(visit);
            const episode = episodes.get(visit.node_id);
            const state = health.get(visit.node_id);
            const identityMatches = valid && episode?.zone === visit.zone && state?.zone === visit.zone;
            const generationMatches = identityMatches && episode?.episode_id === visit.episode_id;
            const presence = authoritative && generationMatches && state?.phase === 'on' && visit.branch_active && episode?.status !== 'clearing';
            const role = presence ? 'presence' : 'history';
            // Endpoint phase describes observed physical state; generation remains an independent gate.
            const phase = valid && state?.zone === visit.zone ? (state.phase === 'on' ? 'ON' : state.phase === 'off' ? 'OFF' : 'Unknown') : 'Unknown';
            const issue = !valid ? 'Map membership unavailable' : !identityMatches ? 'Physical diagnostics unavailable' : !generationMatches ? 'Earlier episode' : undefined;
            if (valid) {
                add(result.nodes, visit.node_id, role, slot);
                add(result.zones, visit.zone, role, slot);
            }
            return { visit, role, valid, phase, issue };
        }
        row.occurrences = path.route.map(v => occurrence(v, true));
        // Shared main/tip copies keep equal presence strength. Only ancestors
        // absent from the authoritative inventory are prefix-only history.
        const authoritative = new Set([...path.route, ...path.branch_routes.flatMap(branch => branch.slice(-1))].map(v => v.episode_id));
        row.overlaps = path.branch_routes.map(branch => branch.map(v => occurrence(v, authoritative.has(v.episode_id))));
        const seen = new Set<string>();
        for (const route of [row.occurrences, ...row.overlaps]) {
            for (let i = 1; i < route.length; i++) {
                const previous = route[i - 1]; const current = route[i];
                if (!previous?.valid || !current?.valid) continue;
                const key = JSON.stringify([previous.visit.episode_id, current.visit.episode_id]);
                if (seen.has(key)) continue;
                seen.add(key);
                result.segments.push({ slot, from: previous.visit.node_id, to: current.visit.node_id, sourceZone: previous.visit.zone, targetZone: current.visit.zone });
            }
        }
    }
    for (const row of result.slots) {
        for (const occurrence of [...row.occurrences, ...row.overlaps.flat()]) {
            if (occurrence.role !== 'presence') continue;
            for (const id of map.nodes[occurrence.visit.node_id]?.adjacent || []) {
                const node = Object.hasOwn(map.nodes, id) ? map.nodes[id] : undefined;
                if (!node) continue;
                add(result.nodes, id, 'candidate', row.slot);
                add(result.zones, node.zone || id, 'candidate', row.slot);
            }
        }
    }
    result.message = paths.length ? 'Selected anonymous paths' : 'No selected paths';
    return result;
}