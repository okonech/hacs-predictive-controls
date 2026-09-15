import type { Config } from '../types.ts';
import { escapeHtml } from '../formatting.ts';

export interface SettingsActions {
    setting(field: string, value: string): void;
    cleanup(): void;
}

/** Values stay textual in the controls; validation and cleanup confirmation belong to the parent. */
export function renderSettings(config: Config, cleanupMessage: string | undefined, busy: boolean): string {
    const disabled = busy ? ' disabled' : '';
    return `
    <main class="single-panel settings" aria-busy="${busy ? 'true' : 'false'}">
      <label>Transition window seconds<input data-setting="transition_window_seconds" type="number" min="1" step="1" value="${escapeHtml(config.transition_window_seconds)}"${disabled} /></label>
      <label>Expected occupants<input data-setting="expected_occupants" type="number" min="0" max="2" step="1" value="${escapeHtml(config.expected_occupants)}"${disabled} /></label>
      <label>Expected occupants entity<input data-setting="expected_occupants_entity" type="text" value="${escapeHtml(config.expected_occupants_entity ?? '')}"${disabled} /></label>
      <section class="maintenance-section">
        <h3>Entities</h3>
        <button type="button" data-action="cleanup-entities"${disabled}>Clean Stale Entities</button>
        ${cleanupMessage !== undefined ? `<p role="status">${escapeHtml(cleanupMessage)}</p>` : ''}
      </section>
    </main>
  `;
}

export function bindSettings(root: HTMLElement, actions: SettingsActions): void {
    root.querySelectorAll('[data-setting]').forEach(input => {
        if (!(input instanceof HTMLInputElement)) return;
        input.addEventListener('input', event => {
            const target = event.target;
            if (!(target instanceof HTMLInputElement) || target !== input || target.disabled) return;
            const field = target.dataset.setting;
            if (field === 'transition_window_seconds' || field === 'expected_occupants' || field === 'expected_occupants_entity') {
                actions.setting(field, target.value);
            }
        });
    });
    const cleanup = root.querySelector('[data-action="cleanup-entities"]');
    if (cleanup instanceof HTMLButtonElement) {
        cleanup.addEventListener('click', event => {
            if (event.currentTarget instanceof HTMLButtonElement && !event.currentTarget.disabled) actions.cleanup();
        });
    }
}