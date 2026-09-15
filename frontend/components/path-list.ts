import type { PredictiveMap } from '../types.ts';
import type { PathProjection } from '../paths.ts';
import { escapeHtml as e, titleFromId } from '../formatting.ts';

export function renderPathList(paths: PathProjection, map: PredictiveMap): string {
    return `<section class="selected-paths" aria-label="Selected anonymous paths">
    <h3>${e(paths.message)}</h3>
    ${paths.state === 'selected' ? paths.slots.map(row => {
        if (!row.path) return `<article class="path-slot"><strong>Slot ${row.slot} · Unlocated</strong></article>`;
        const last = row.occurrences.at(-1);
        return `<article class="path-slot" data-slot="${row.slot}">
        <strong>Slot ${row.slot}</strong> <span class="path-badge">${titleFromId(row.path.track_confidence)}</span>
        <ol class="path-chips">${row.occurrences.map(o => `<li class="path-chip path-role-${o.role}" data-node-id="${e(o.visit.node_id)}" data-episode-id="${e(o.visit.episode_id)}">
          <strong>${e(map.nodes[o.visit.node_id]?.label || titleFromId(o.visit.node_id))}</strong>
          <span>${o.role === 'presence' ? 'Current presence' : 'Retained history'} · ${o.phase}</span>
          ${o.issue ? `<small>${e(o.issue)}</small>` : ''}</li>`).join('')}</ol>
        <p>Retained endpoint · ${last?.phase || 'Unknown'} · Continuation eligible: ${row.path.endpoint_eligible ? 'yes' : 'no'}</p>
        <small>Retained history is not a claim of current physical presence.</small>
      </article>`;
    }).join('') : ''}
  </section>`;
}