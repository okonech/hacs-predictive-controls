import { escapeHtml } from '../formatting.ts';

/** The parent chooses dirty raw YAML versus serialized map YAML; rendering never rewrites either. */
export function renderYaml(yaml: string): string {
    // HTML consumes one initial textarea newline. Supply that newline ourselves,
    // so an initial newline in the user's raw source is not lost during rendering.
    return `
    <main class="single-panel">
      <h2>Map YAML</h2>
      <textarea data-map-yaml aria-label="Map YAML" spellcheck="false">
${escapeHtml(yaml)}</textarea>
    </main>
  `;
}

/** Forward the raw value; the parent marks it dirty without parsing or trimming it. */
export function bindYaml(root: HTMLElement, input: (value: string) => void): void {
    const editor = root.querySelector('[data-map-yaml]');
    if (!(editor instanceof HTMLTextAreaElement)) return;
    editor.addEventListener('input', event => {
        const target = event.target;
        if (target instanceof HTMLTextAreaElement && target === editor && !target.disabled && !target.readOnly) {
            input(target.value);
        }
    });
}