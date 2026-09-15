import type { ViewContext } from '../types.ts';
import { escapeHtml, formatTimestamp, labelFromValue, warningLabel, zoneLabel } from '../formatting.ts';

/** All active kinds are visible; retained, cleared history is not an active warning. */
export function renderReliability(ctx: ViewContext): string {
    const diagnostics = ctx.status?.occupancy_diagnostics;
    const warnings = (diagnostics?.reliability_warnings ?? []).filter(warning => warning.active);
    const statusText = ctx.statusError !== undefined
        ? `Status unavailable: ${ctx.statusError}${ctx.status ? ' · Showing the last successful snapshot (stale).' : ''}`
        : `Updated ${ctx.updated?.toLocaleTimeString() ?? 'never'}`;
    return `
    <main class="reliability-layout">
      <section class="occupancy-toolbar">
        <div>
          <h2>Reliability</h2>
          <p${ctx.statusError !== undefined ? ' class="status-stale" role="status"' : ''}>${escapeHtml(statusText)}</p>
        </div>
        <button type="button" data-action="refresh-status">Refresh</button>
      </section>
      <section class="reliability-summary">
        <div class="reliability-metrics">
          <div><strong>${diagnostics?.episodes?.length ?? 0}</strong><span>Physical nodes</span></div>
          <div><strong>${warnings.length}</strong><span>Health warnings</span></div>
          <div><strong>${escapeHtml(diagnostics?.processing?.token_count ?? 0)}</strong><span>Traversal tokens</span></div>
        </div>
        <p>Warnings reflect observed sensor patterns or unverified paths. Continuous presence alone does not establish a sensor fault.</p>
      </section>
      <section class="reliability-section">
        <div class="section-head">
          <h3>Sensor Health</h3>
          <small>${warnings.length} ${warnings.length === 1 ? 'warning' : 'warnings'}</small>
        </div>
        <div class="reliability-list">
          ${warnings.length ? warnings.map(warning => `
            <article class="reliability-row">
              <div class="reliability-row-head"><strong>${escapeHtml(warning.node_id)}</strong><span>${escapeHtml(zoneLabel(ctx.map, warning.zone))}</span></div>
              <p>${escapeHtml(warningLabel(warning))}${warning.reasons?.length
            ? ` &middot; ${warning.reasons.map(reason => escapeHtml(labelFromValue(reason))).join(' · ')}` : ''}</p>
              <small>Last observed ${escapeHtml(formatTimestamp(warning.last_observed_at))}</small>
            </article>
          `).join('') : '<p class="empty-state">No sensor health warnings.</p>'}
        </div>
      </section>
    </main>
  `;
}