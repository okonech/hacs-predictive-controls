import type { PredictiveMap } from '../types.ts';
import type { Occurrence, PathProjection } from '../paths.ts';
import { escapeHtml as e, titleFromId } from '../formatting.ts';

export function renderPathList(paths: PathProjection, map: PredictiveMap): string {
  const chips = (occurrences: Occurrence[], label: string): string => `<ol class="path-chips" aria-label="${e(label)}">${occurrences.map(o => `<li class="path-chip path-role-${o.role}" data-node-id="${e(o.visit.node_id)}" data-episode-id="${e(o.visit.episode_id)}">
      <strong>${e(map.nodes[o.visit.node_id]?.label || titleFromId(o.visit.node_id))}</strong>
      <span>${o.role === 'presence' ? 'Current presence' : 'Retained history'} · ${o.phase}</span>
      ${o.issue ? `<small>${e(o.issue)}</small>` : ''}</li>`).join('')}</ol>`;
  return `<section class="selected-paths" aria-label="Selected anonymous paths">
    <h3>${e(paths.message)}</h3>
    ${paths.state === 'selected' ? paths.slots.map(row => {
    if (!row.path) return `<article class="path-slot"><strong>Slot ${row.slot} · Unlocated</strong></article>`;
    const last = row.occurrences.at(-1);
    return `<article class="path-slot" data-slot="${row.slot}">
        <strong>Slot ${row.slot}</strong> <span class="path-badge">${titleFromId(row.path.track_confidence)}</span>
        <div class="path-main-route"><h4>Main route</h4>${chips(row.occurrences, `Slot ${row.slot} main route`)}</div>
        <p>Retained endpoint · ${last?.phase || 'Unknown'} · Continuation eligible: ${row.path.endpoint_eligible ? 'yes' : 'no'}</p>
        ${row.overlaps.map((route, index) => `<section class="path-overlap" aria-label="Observed overlap ${index + 1}"><h4>Observed overlap ${index + 1}</h4>${chips(route, `Slot ${row.slot} observed overlap ${index + 1}`)}<small>Observed prefix to a retained tip; not a separate occupant or a continuation after the main endpoint.</small></section>`).join('')}
        <small>Retained history is not a claim of current physical presence.</small>
      </article>`;
  }).join('') : ''}
  </section>`;
}