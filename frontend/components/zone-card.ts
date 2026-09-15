import type { ZoneSummary } from '../layout.ts';
import type { ViewContext } from '../types.ts';
import type { PathProjection } from '../paths.ts';
import { escapeHtml as e, formatPercent, formatTimestamp, policyModel, titleFromId, warningLabel } from '../formatting.ts';

export function renderZoneCard(zone: ZoneSummary, minX: number, minY: number, ctx: ViewContext, paths: PathProjection): string {
    const state = ctx.status?.zone_states?.[zone.zoneId] || {};
    const model = policyModel(ctx.status);
    const policy = model?.policy?.[zone.zoneId];
    const belief = model?.beliefs?.[zone.zoneId] ?? state.confidence;
    const confidence = belief === undefined ? 0 : Math.round(belief * 100);
    const frontier = paths.frontierTokens.find(t => t.zone === zone.zoneId);
    const warnings = (model?.reliability_warnings || []).filter(w => w.active && w.zone === zone.zoneId);
    const membership = paths.zones.get(zone.zoneId);
    const role = membership?.role || 'neutral';
    return `<article class="zone-card status-${e(state.status || 'rejected')}${policy?.active ? ' is-active' : ''}${frontier ? ' has-frontier' : ''}${warnings.length ? ' has-warning' : ''}${role !== 'neutral' ? ` path-role-${role}` : ''}" data-zone="${e(zone.zoneId)}" style="left:${zone.position.x - minX + 24}px;top:${zone.position.y - minY + 24}px;width:${zone.size.width}px;min-height:${zone.size.height}px" title="${e(state.reason || 'no evidence')}">
    <div class="zone-card-head"><strong>${e(zone.label)}</strong><span>${formatPercent(belief)}${belief !== undefined ? ' belief' : ''}</span></div>
    <div class="confidence-bar"><span style="width:${confidence}%"></span></div>
    <div class="zone-belief-state"><strong>${policy ? (policy.active ? 'Active' : 'Inactive') : 'Policy unavailable'}</strong><span>${e(policy?.profile || 'unprofiled')}</span></div>
    <small>${e(titleFromId(state.status || 'rejected'))} · ${e(titleFromId(state.occupancy_behavior || zone.occupancyBehavior))} · ${e(titleFromId(zone.role))}</small>
    <small>${zone.nodeIds.length} ${zone.nodeIds.length === 1 ? 'sensor' : 'sensors'}${state.last_node_id ? ` · ${e(state.last_node_id)}` : ''}</small>
    ${role !== 'neutral' ? `<small class="path-role-label">${role === 'presence' ? 'Current presence' : role === 'history' ? 'Retained history' : 'One-hop candidate'} · ${(membership?.slots || []).map(n => `Slot ${n}`).join(', ')}</small>` : ''}
    ${warnings.map(w => `<small class="zone-warning-label">${e(warningLabel(w))} warning · ${e(w.node_id)} · active · ${e(formatTimestamp(w.last_observed_at))}</small>`).join('')}
    ${frontier ? `<small class="path-frontier-label">Anonymous path frontier · until ${e(formatTimestamp(frontier.valid_until))}</small>` : ''}
  </article>`;
}