import type { ActivityFilter, AuditEntry, Diagnostics, ViewContext } from '../types.ts';
import {
    auditKind,
    auditTransition,
    decisionExplanation,
    escapeHtml,
    formatPercent,
    formatTimestamp,
    policyModel,
    zoneLabel,
} from '../formatting.ts';

export interface ActivityActions {
    filter(value: ActivityFilter): void;
    more(): void;
}

const filterLabels: Readonly<Record<ActivityFilter, string>> = {
    edges: 'Production edges',
    rejected: 'Rejected decisions',
    observations: 'Policy observations',
    all: 'All retained',
};
const filters: readonly ActivityFilter[] = ['edges', 'rejected', 'observations', 'all'];
const pageSize = 50;

function auditTime(entry: AuditEntry): number {
    const time = entry.event_at === undefined ? NaN : Date.parse(entry.event_at);
    return Number.isFinite(time) ? time : 0;
}

function renderOwnership(ctx: ViewContext, model: Diagnostics, activeCount: number): string {
    const entries = Object.entries(model.policy ?? {}).sort(([left], [right]) =>
        zoneLabel(ctx.map, left).localeCompare(zoneLabel(ctx.map, right)),
    );
    return `
    <section class="ownership-section">
      <div class="section-head">
        <div class="section-title">
          <h3>Current Ownership</h3>
          <small>Hysteretic zone-belief projection</small>
        </div>
        <strong>${activeCount} active ${activeCount === 1 ? 'zone' : 'zones'}</strong>
      </div>
      <div class="ownership-grid">
        ${entries.length ? entries.map(([zone, state]) => `
          <article class="ownership-row ${state.active ? 'is-active' : ''}">
            <div class="ownership-name">
              <span class="state-indicator" aria-hidden="true"></span>
              <div><strong>${escapeHtml(zoneLabel(ctx.map, zone))}</strong><small>${state.active ? 'Active' : 'Inactive'}</small></div>
            </div>
            <p>${state.pending_release_since
            ? `Release dwell since ${escapeHtml(formatTimestamp(state.pending_release_since))}`
            : 'No release dwell pending'}</p>
            <div class="ownership-probabilities">
              <span>Belief ${escapeHtml(formatPercent(model.beliefs?.[zone]))}</span>
              <span>${escapeHtml(state.profile || 'unprofiled')}</span>
            </div>
          </article>
        `).join('') : '<p class="empty-state">No zone ownership state is available yet.</p>'}
      </div>
    </section>
  `;
}

function renderRetention(ordered: readonly AuditEntry[], activeCount: number): string {
    return `
    <section class="activity-metrics">
      <div><strong>${activeCount}</strong><span>Active now</span></div>
      <div><strong>${escapeHtml(ordered.length.toLocaleString())}</strong><span>Retained decisions</span></div>
      <p>Bounded audit &middot; ${escapeHtml(formatTimestamp(ordered[ordered.length - 1]?.event_at))} to ${escapeHtml(formatTimestamp(ordered[0]?.event_at))}</p>
    </section>
  `;
}

function renderAuditEntry(ctx: ViewContext, entry: AuditEntry): string {
    const [before, after] = auditTransition(entry);
    const kind = auditKind(entry);
    const title = kind === 'edges' ? (after ? 'Turned on' : 'Turned off')
        : kind === 'rejected' ? 'Decision rejected' : 'Policy observation';
    const evidenceCount = entry.evidence_ids?.length ?? 0;
    return `
    <article class="audit-row kind-${kind}">
      <div class="audit-marker" aria-hidden="true"></div>
      <div class="audit-content">
        <div class="audit-row-head">
          <div><strong>${title}</strong><span>${escapeHtml(zoneLabel(ctx.map, entry.zone))}</span></div>
          <time>${escapeHtml(formatTimestamp(entry.event_at))}</time>
        </div>
        <p>${escapeHtml(decisionExplanation(entry))}</p>
        <div class="audit-meta">
          <span class="context-badge lightweight">Zone-local decision</span>
          ${kind === 'edges' ? `<span>${before ? 'On' : 'Off'} to ${after ? 'On' : 'Off'}</span>` : ''}
          ${evidenceCount ? `<span>${evidenceCount} evidence ${evidenceCount === 1 ? 'item' : 'items'}</span>` : ''}
        </div>
      </div>
    </article>
  `;
}

function renderTimeline(
    ctx: ViewContext,
    ordered: readonly AuditEntry[],
    filter: ActivityFilter,
    limit: number,
): string {
    const filtered = filter === 'all' ? ordered : ordered.filter(entry => auditKind(entry) === filter);
    const rowLimit = Number.isFinite(limit) && limit >= pageSize
        ? Math.floor(limit / pageSize) * pageSize : pageSize;
    const visible = filtered.slice(0, rowLimit);
    return `
    <section class="audit-section">
      <div class="audit-heading">
        <div class="section-title"><h3>Decision Timeline</h3><small>Newest first</small></div>
        <div class="activity-filters" role="group" aria-label="Activity filter">
          ${filters.map(value => `<button type="button" class="${filter === value ? 'active' : ''}" data-activity-filter="${value}" aria-pressed="${filter === value ? 'true' : 'false'}">${filterLabels[value]}</button>`).join('')}
        </div>
      </div>
      <div class="audit-list">
        ${visible.length ? visible.map(entry => renderAuditEntry(ctx, entry)).join('')
            : `<p class="empty-state">No ${escapeHtml(filterLabels[filter].toLowerCase())} in retained activity.</p>`}
      </div>
      ${filtered.length > visible.length ? '<button type="button" class="show-more" data-action="show-more-audit">Show 50 more</button>' : ''}
    </section>
  `;
}

/** The parent owns filter changes, resets to 50 rows, and subsequent 50-row pages. */
export function renderActivity(ctx: ViewContext, filter: ActivityFilter, limit: number): string {
    const model = policyModel(ctx.status);
    const activeCount = Object.values(model?.policy ?? {}).filter(state => state.active).length;
    const ordered = [...(model?.policy_audit ?? [])].sort((left, right) => auditTime(right) - auditTime(left));
    const statusText = ctx.statusError !== undefined
        ? `Status unavailable: ${ctx.statusError}${ctx.status ? ' · Showing the last successful snapshot (stale).' : ''}`
        : `Updated ${ctx.updated?.toLocaleTimeString() ?? 'never'}`;
    return `
    <main class="activity-layout">
      <section class="occupancy-toolbar">
        <div>
          <h2>Activity</h2>
          <p${ctx.statusError !== undefined ? ' class="status-stale" role="status"' : ''}>${escapeHtml(statusText)}</p>
        </div>
        <button type="button" data-action="refresh-status">Refresh</button>
      </section>
      ${model ? `${renderOwnership(ctx, model, activeCount)}${renderRetention(ordered, activeCount)}${renderTimeline(ctx, ordered, filter, limit)}` : `
        <section class="activity-empty">
          <h3>Waiting for zone-belief activity</h3>
          <p>Policy activity will appear after the first observation.</p>
        </section>
      `}
    </main>
  `;
}

/** Bind once after rendering; the shared refresh button is owned by the parent. */
export function bindActivity(root: HTMLElement, actions: ActivityActions): void {
    root.querySelectorAll('[data-activity-filter]').forEach(button => {
        if (!(button instanceof HTMLButtonElement)) return;
        button.addEventListener('click', event => {
            const target = event.currentTarget;
            if (!(target instanceof HTMLButtonElement) || target.disabled) return;
            const value = target.dataset.activityFilter;
            if (value === 'edges' || value === 'rejected' || value === 'observations' || value === 'all') {
                actions.filter(value);
            }
        });
    });
    const more = root.querySelector('[data-action="show-more-audit"]');
    if (more instanceof HTMLButtonElement) {
        more.addEventListener('click', event => {
            if (event.currentTarget instanceof HTMLButtonElement && !event.currentTarget.disabled) actions.more();
        });
    }
}