import type { Point, Size } from './layout.ts';

/** Unknown map extensions are data, never an escape hatch for known fields. */
export interface MapNode {
    [extension: string]: unknown;
    label?: string;
    zone?: string;
    floor?: string;
    role?: string;
    occupancy_behavior?: string;
    entities?: Record<string, string | string[]>;
    adjacent?: string[];
    position?: Point;
    reliability?: number;
    route_prior_weight?: number;
}
export interface MapZone {
    [extension: string]: unknown;
    label?: string;
    floor?: string;
    role?: string;
    occupancy_behavior?: string;
    position?: Point;
    size?: Size;
}
export interface PredictiveMap {
    [extension: string]: unknown;
    nodes: Record<string, MapNode>;
    zones?: Record<string, MapZone>;
    floors?: string[];
}
export interface Config {
    entry_id: string;
    map: PredictiveMap;
    map_yaml: string;
    transition_window_seconds: number;
    expected_occupants: number;
    expected_occupants_entity?: string;
    title?: string;
}
export interface Entity {
    entity_id: string;
    name?: string;
    state?: string;
    device_class?: string | null;
}
export interface Visit {
    node_id: string;
    zone: string;
    episode_id: string;
    branch_active: boolean;
    at?: string;
    kind?: string;
}
export interface SelectedPath {
    route: Visit[];
    track_confidence: 'provisional' | 'confirmed';
    endpoint_eligible: boolean;
    endpoint?: Visit;
}
export interface Episode {
    node_id: string;
    zone?: string;
    episode_id?: string | null;
    status?: string;
}
export interface PathHealth {
    node_id: string;
    zone: string;
    phase: 'on' | 'off' | 'unknown' | 'clearing';
}
export interface Warning {
    node_id: string;
    zone: string;
    kind: string;
    active: boolean;
    reasons?: string[];
    last_observed_at?: string | null;
}
export interface Policy {
    active: boolean;
    profile?: string;
    pending_release_since?: string | null;
}
export interface AuditEntry {
    event_at?: string;
    zone?: string;
    active_before?: boolean;
    active_after?: boolean;
    belief_after?: number;
    traversal_reason?: string | null;
    evidence_ids?: string[];
    event_kind?: string | null;
    reason?: string;
}
export interface Frontier {
    token_id: string;
    zone?: string;
    valid_until?: string;
}
export interface Authorization {
    authorized: boolean;
    source_token_ids?: string[];
    target_zone?: string;
    reason?: string;
}
export interface Diagnostics {
    model?: string;
    expected_occupants?: number;
    unsupported_count?: boolean;
    beliefs?: Record<string, number>;
    policy?: Record<string, Policy>;
    policy_audit?: AuditEntry[];
    episodes?: Episode[];
    path_health?: PathHealth[];
    selected_paths?: (SelectedPath | null)[];
    selected_paths_error?: string;
    reliability_warnings?: Warning[];
    health_warnings?: string[];
    processing?: { token_count?: number };
    traversal_frontier?: Frontier[];
    authorizations?: Authorization[];
}
export interface ZoneState {
    confidence?: number;
    status?: string;
    reason?: string;
    occupancy_behavior?: string;
    last_node_id?: string | null;
}
export interface Status {
    expected_occupants?: number;
    zone_states?: Record<string, ZoneState>;
    transition_counts?: Record<string, Record<string, number>>;
    occupancy_diagnostics?: Diagnostics;
}
export type Request =
    | { type: 'predictive_controls/config' | 'predictive_controls/entities' }
    | { type: 'predictive_controls/status'; entry_id?: string }
    | { type: 'predictive_controls/cleanup_entities'; entry_id: string; dry_run: boolean }
    | {
        type: 'predictive_controls/save_config'; entry_id: string; map: PredictiveMap;
        map_yaml: string; map_yaml_dirty: boolean; transition_window_seconds: number;
        expected_occupants: number; expected_occupants_entity: string
    };
export interface Hass { callWS(message: Request): Promise<unknown> }
export type Tab = 'occupancy' | 'reliability' | 'activity' | 'map' | 'yaml' | 'settings';
export type ActivityFilter = 'edges' | 'rejected' | 'observations' | 'all';
export interface ViewContext {
    map: PredictiveMap;
    status: Status | undefined;
    statusError: string | undefined;
    updated: Date | undefined;
}