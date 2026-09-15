import type { ZoneSummary } from '../layout.ts';
import { estimateCardHeight, floorBands, minimizeCrossings, separateFloorRows, spacedZoneSummaries, stackFloorsByBand } from '../layout.ts';
import type { ViewContext } from '../types.ts';
import type { PathProjection } from '../paths.ts';
import { escapeHtml as e, policyModel, titleFromId } from '../formatting.ts';
import { renderZoneCard } from './zone-card.ts';

function center(zone: ZoneSummary, minX: number, minY: number) {
    return { x: zone.position.x - minX + zone.size.width / 2 + 24, y: zone.position.y - minY + estimateCardHeight(zone) / 2 + 24 };
}
export function renderZoneEdges(zones: ZoneSummary[], minX: number, minY: number, ctx: ViewContext, paths: PathProjection): string {
    const byNode = new Map(zones.flatMap(z => z.nodeIds.map(id => [id, z] satisfies [string, ZoneSummary])));
    const byZone = new Map(zones.map(z => [z.zoneId, z]));
    const lines: string[] = [];
    const seen = new Set<string>();
    for (const zone of zones) for (const id of zone.nodeIds) for (const targetId of ctx.map.nodes[id]?.adjacent || []) {
        const target = byNode.get(targetId);
        if (!target || target.zoneId === zone.zoneId) continue;
        const key = [zone.zoneId, target.zoneId].sort().join('->');
        if (seen.has(key)) continue;
        seen.add(key);
        const a = center(zone, minX, minY); const b = center(target, minX, minY);
        const frontier = paths.frontierZones.has(zone.zoneId) || paths.frontierZones.has(target.zoneId);
        lines.push(`<line class="zone-edge${frontier ? ' frontier-edge' : ''}" data-edge="${e(key)}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />`);
    }
    const segments = paths.state === 'legacy' ? paths.authorizedPaths.map(p => ({ ...p, slot: 0 })) : paths.segments;
    for (const segment of segments) {
        const source = byZone.get(segment.sourceZone); const target = byZone.get(segment.targetZone);
        if (!source || !target || source.zoneId === target.zoneId) continue;
        const a = center(source, minX, minY); const b = center(target, minX, minY);
        const cls = paths.state === 'legacy' ? 'authorized-path' : 'selected-path-edge';
        // An inline arrow avoids document-global SVG marker IDs across panel instances.
        const angle = Math.atan2(b.y - a.y, b.x - a.x);
        const tx = a.x + (b.x - a.x) * 0.62; const ty = a.y + (b.y - a.y) * 0.62;
        lines.push(`<line class="${cls}" data-slot="${segment.slot}" data-path="${e(`${source.zoneId}->${target.zoneId}`)}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" /><path class="path-arrow" d="M ${tx} ${ty} l ${-12 * Math.cos(angle - 0.5)} ${-12 * Math.sin(angle - 0.5)} M ${tx} ${ty} l ${-12 * Math.cos(angle + 0.5)} ${-12 * Math.sin(angle + 0.5)}" />`);
    }
    return lines.join('');
}
export function renderGraph(input: ZoneSummary[], ctx: ViewContext, paths: PathProjection, clientWidth: number): string {
    const model = policyModel(ctx.status);
    // Reserve complete card text, including warning labels and memberships, before layout.
    const zones = input.map(zone => {
        const warningChars = (model?.reliability_warnings || []).filter(w => w.active && w.zone === zone.zoneId).reduce((n, w) => n + 130 + w.node_id.length, 0);
        const membership = paths.zones.get(zone.zoneId);
        const charsPerLine = Math.max(8, Math.floor((zone.size.width - 30) / 7));
        return { ...zone, contentHeight: estimateCardHeight(zone) + (membership?.slots.length ? 54 : 0) + Math.ceil(warningChars / charsPerLine) * 19 + (paths.frontierZones.has(zone.zoneId) ? 55 : 0) };
    });
    const layout = minimizeCrossings(stackFloorsByBand(separateFloorRows(spacedZoneSummaries(zones)), ctx.map.floors || []), ctx.map.nodes);
    const minX = (layout.length ? Math.min(...layout.map(z => z.position.x)) : 0) - 64;
    const minY = layout.length ? Math.min(...layout.map(z => z.position.y)) : 0;
    const maxX = layout.length ? Math.max(...layout.map(z => z.position.x + z.size.width)) : 0;
    const maxY = layout.length ? Math.max(...layout.map(z => z.position.y + estimateCardHeight(z))) : 0;
    const width = Math.max(900, maxX - minX + 48, clientWidth - 48);
    const bands = floorBands(layout);
    const bandBottom = bands.reduce((bottom, b) => Math.max(bottom, b.top - minY + 12 + Math.max(120, b.bottom - b.top + 72)), 0);
    const height = Math.max(520, maxY - minY + 48, bandBottom + 24);
    const expected = model?.expected_occupants ?? ctx.status?.expected_occupants;
    const active = Object.values(model?.policy || {}).filter(p => p.active).length;
    return `<section class="floor-section occupancy-graph-section">
    <div class="graph-section-head"><div class="section-title"><h3>Believed Occupancy Graph</h3><small>Beliefs are zone-local; highlighted paths are anonymous and do not identify a person.</small></div>
      <div class="graph-summary"><span>Expected ${expected ?? 'unavailable'}</span><span>${active} active ${active === 1 ? 'zone' : 'zones'}</span>
      <span>${paths.state === 'legacy' ? `${paths.frontierTokens.length} path ${paths.frontierTokens.length === 1 ? 'frontier' : 'frontiers'}` : paths.state === 'unavailable' ? 'Selected slots unavailable' : `${paths.slots.length} anonymous slots`}</span>
      <span>${(model?.reliability_warnings || []).filter(w => w.active).length} health warnings</span></div></div>
    <div class="graph-legend">${paths.state === 'legacy' ? '<span><i class="legend-line frontier"></i>Possible next path</span><span><i class="legend-line authorized"></i>Recently authorized path</span>' : '<span><i class="legend-line presence"></i>Current presence</span><span><i class="legend-line history"></i>Retained history</span><span><i class="legend-line candidate"></i>One-hop candidate</span>'}<span><i class="legend-zone warning"></i>Sensor warning</span></div>
    <div class="occupancy-board occupancy-graph" data-scroll-key="graph" tabindex="0" aria-label="Occupancy graph, scroll to explore" style="height:${height}px;width:${width}px">
      ${bands.map(b => `<div class="floor-band" style="top:${b.top - minY + 12}px;height:${Math.max(120, b.bottom - b.top + 72)}px;width:${width - 24}px"><span>${e(titleFromId(b.floor))}</span></div>`).join('')}
      <svg class="zone-edges" aria-hidden="true" viewBox="0 0 ${width} ${height}">${renderZoneEdges(layout, minX, minY, ctx, paths)}</svg>
      ${layout.map(z => renderZoneCard(z, minX, minY, ctx, paths)).join('')}
    </div></section>`;
}