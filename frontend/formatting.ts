import type { AuditEntry, Status, Warning, PredictiveMap } from './types.ts';

export function escapeHtml(value: unknown): string {
    return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
export function titleFromId(value: string | null | undefined): string {
    return (value || 'unknown').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}
export const labelFromValue = titleFromId;
export function formatTimestamp(value: string | null | undefined): string {
    if (!value) return 'never';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
export function formatPercent(value: number | undefined): string {
    return value !== undefined && Number.isFinite(value) && value >= 0 && value <= 1
        ? `${Math.round(value * 100)}%` : 'unavailable';
}
export function warningLabel(warning: Warning): string {
    return warning.kind === 'suspected_stuck' && warning.reasons?.length === 1
        && warning.reasons[0] === 'assertion_timeout'
        ? 'Continuous presence detected; path unverified' : titleFromId(warning.kind);
}
export function policyModel(status: Status | undefined) {
    return status?.occupancy_diagnostics?.model === 'zone_belief' ? status.occupancy_diagnostics : undefined;
}
export function zoneLabel(map: PredictiveMap, zone: string | undefined): string {
    return (zone ? map.zones?.[zone]?.label : undefined) || titleFromId(zone || 'whole home');
}
export function auditTransition(entry: AuditEntry): [boolean, boolean] {
    return [entry.active_before === true, entry.active_after === true];
}
export function auditKind(entry: AuditEntry): 'edges' | 'rejected' | 'observations' | 'other' {
    const [before, after] = auditTransition(entry);
    if (entry.active_before !== undefined && entry.active_after !== undefined && before !== after) return 'edges';
    if (entry.reason === 'acquisition_unauthorized') return 'rejected';
    return entry.event_kind ? 'other' : 'observations';
}
export function decisionExplanation(entry: AuditEntry): string {
    return `${titleFromId(entry.reason || 'policy observation')} at ${formatPercent(entry.belief_after)}`
        + (entry.traversal_reason ? ` via ${titleFromId(entry.traversal_reason)}` : '');
}
export function errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
}