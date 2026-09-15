import type { ViewContext } from '../types.ts';
import { escapeHtml as e } from '../formatting.ts';
import { zoneSummaries, learnedTransitionRows } from '../map-helpers.ts';
import { projectPaths } from '../paths.ts';
import { renderGraph } from './graph.ts';
import { renderPathList } from './path-list.ts';

export function renderOccupancy(ctx: ViewContext, clientWidth: number): string {
    const paths = projectPaths(ctx.map, ctx.status?.occupancy_diagnostics, ctx.status?.expected_occupants);
    const rows = learnedTransitionRows(ctx.map, ctx.status);
    return `<main class="occupancy-layout">
    <section class="occupancy-toolbar"><div><h2>Occupancy</h2><p>${ctx.statusError ? `Stale / unavailable: ${e(ctx.statusError)}` : `Updated ${ctx.updated?.toLocaleTimeString() || 'never'}`}</p></div><button data-action="refresh-status">Refresh</button></section>
    ${renderPathList(paths, ctx.map)}
    ${renderGraph(zoneSummaries(ctx.map), ctx, paths, clientWidth)}
    <section class="transition-section"><div class="section-head"><h3>Learned Transitions</h3><small>${rows.length} active ${rows.length === 1 ? 'edge' : 'edges'}</small></div>
      ${rows.length ? `<table class="transition-table"><thead><tr><th>From</th><th>To</th><th>Count</th></tr></thead><tbody>${rows.map(r => `<tr><td><strong>${e(r.sourceLabel)}</strong><small>${e(r.sourceId)}</small></td><td><strong>${e(r.targetLabel)}</strong><small>${e(r.targetId)}</small></td><td>${r.count.toLocaleString(undefined, { maximumFractionDigits: 1 })}</td></tr>`).join('')}</tbody></table>` : '<p>No learned transitions yet.</p>'}
    </section></main>`;
}