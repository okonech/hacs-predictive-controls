import type { ActivityFilter, Config, Entity, Hass, Status, Tab, ViewContext } from './types.ts';
import type { ZoneSummary } from './layout.ts';
import { request } from './api.ts';
import { decodeCleanup, decodeConfig, decodeMap, decodeNode, decodeStatus, normalizeEntityResponse, validateSettings } from './decoders.ts';
import { errorMessage, escapeHtml as e } from './formatting.ts';
import { addBidirectionalEdge, createEmptyNode, createNodeForEntity, deleteNode, entityMatchesFilter, moveNode, removeBidirectionalEdge, renameNode } from './map-helpers.ts';
import { dumpMapYaml, parseEntities, parseMapYaml } from './yaml.ts';
import { projectPaths } from './paths.ts';
import { panelStyles } from './styles.ts';
import { renderOccupancy } from './components/occupancy.ts';
import { renderZoneCard } from './components/zone-card.ts';
import { bindActivity, renderActivity } from './components/activity.ts';
import { renderReliability } from './components/reliability.ts';
import { bindMap, renderMap } from './components/map-editor.ts';
import { bindSettings, renderSettings } from './components/settings.ts';
import { bindYaml, renderYaml } from './components/yaml-editor.ts';

const tabs: readonly Tab[] = ['occupancy', 'reliability', 'activity', 'map', 'yaml', 'settings'];
function isTab(value: string | undefined): value is Tab { return tabs.some(tab => tab === value); }

/** Lifecycle/request and edit state only. Components own templates and DOM bindings. */
export class PredictiveControlsPanel extends HTMLElement {
    _hass: Hass | undefined;
    _config: Config | undefined;
    _status: Status | undefined;
    _entities: Entity[] = [];
    _error: string | undefined;
    _statusError: string | undefined;
    _statusUpdated: Date | undefined;
    _cleanupMessage: string | undefined;
    _selectedNode: string | undefined;
    _mapYamlDirty = false;
    _tab: Tab = 'occupancy';
    _activityFilter: ActivityFilter = 'edges';
    _auditLimit = 50;
    _connectMode = false;
    private entityFilter = '';
    private revision = 0;
    private savedRevision = 0;
    private generation = 0;
    private loaded = false;
    private detached = false;
    private loading = false;
    private saving = false;
    private cleaning = false;
    private fieldError: string | undefined;
    private invalidFields = new Map<string, { node: string; field: string; value: string; error: string }>();
    private deferredRender = false;
    private readonly finishDeferredRender = (): void => {
        queueMicrotask(() => { if (this.deferredRender && !this.detached) this.render(true); });
    };
    private statusTask: Promise<void> | undefined;
    private statusTimer: ReturnType<typeof setInterval> | undefined;
    narrow = false;
    panel: unknown;

    set hass(value: Hass) {
        this._hass = value;
        if (!this.loaded && !this.detached) { this.loaded = true; void this.loadData(); }
    }
    get hass(): Hass | undefined { return this._hass; }
    connectedCallback(): void {
        const reconnect = this.detached;
        this.detached = false;
        if (this._hass && (!this.loaded || reconnect)) { this.loaded = true; void this.loadData(); }
        this.startStatusRefresh(); this.render();
    }
    disconnectedCallback(): void {
        this.detached = true; this.invalidate();
        if (this.statusTimer !== undefined) clearInterval(this.statusTimer);
        this.statusTimer = undefined;
    }
    private invalidate(): number {
        this.generation++;
        // Generation invalidation cannot cancel a write already dispatched to HA.
        // Keep destructive-request locks until their bounded requests settle.
        this.statusTask = undefined; this.loading = false;
        return this.generation;
    }
    private current(generation: number): boolean { return generation === this.generation && !this.detached; }
    get nodes() { return this._config?.map?.nodes || {}; }
    private context(): ViewContext {
        return { map: this._config?.map || { nodes: {} }, status: this._status, statusError: this._statusError, updated: this._statusUpdated };
    }
    async loadData(): Promise<void> {
        const hass = this._hass;
        if (!hass || this.detached) return;
        const generation = this.invalidate(); const revision = this.revision;
        this.loading = true; this._error = undefined;
        const configTask = request(hass, { type: 'predictive_controls/config' }).then(decodeConfig);
        const entitiesTask = request(hass, { type: 'predictive_controls/entities' }).then(normalizeEntityResponse);
        const statusTask = request(hass, { type: 'predictive_controls/status' }).then(decodeStatus);
        this.render();
        const [config, entities, status] = await Promise.allSettled([configTask, entitiesTask, statusTask]);
        if (!this.current(generation)) return;
        this.loading = false;
        if (config.status === 'fulfilled') {
            // Reconnect/reload cannot discard dirty edits or edits made while loading.
            if (this.revision === revision && this.revision === this.savedRevision) {
                this._config = config.value; this._selectedNode = undefined; this._mapYamlDirty = false;
            }
        } else this._error = `Configuration: ${errorMessage(config.reason)}`;
        if (entities.status === 'fulfilled') this._entities = entities.value;
        else this._error = [this._error, `Entities: ${errorMessage(entities.reason)}`].filter(Boolean).join(' · ');
        if (status.status === 'fulfilled') { this._status = status.value; this._statusError = undefined; this._statusUpdated = new Date(); }
        else this._statusError = errorMessage(status.reason);
        this.render();
    }
    startStatusRefresh(): void {
        if (this.statusTimer !== undefined) return;
        this.statusTimer = setInterval(() => { void this.refreshStatus(); }, 5000);
    }
    async refreshStatus(): Promise<void> {
        if (this.statusTask) return this.statusTask;
        const hass = this._hass; const config = this._config;
        if (!hass || !config || this.detached || this.loading || this.saving) return;
        const generation = this.generation;
        const task = (async () => {
            try {
                const status = decodeStatus(await request(hass, { type: 'predictive_controls/status', entry_id: config.entry_id }));
                if (!this.current(generation)) return;
                this._status = status; this._statusError = undefined; this._statusUpdated = new Date();
            } catch (error) {
                if (!this.current(generation)) return;
                this._statusError = errorMessage(error);
            }
            if (this.current(generation) && ['occupancy', 'reliability', 'activity'].includes(this._tab)) this.render(true);
        })();
        this.statusTask = task;
        try { await task; } finally { if (this.statusTask === task) this.statusTask = undefined; }
    }
    render(automatic = false): void {
        if (!this._hass) return;
        // Retain the actual focused control, caret and selection on routine polls.
        const focused = this.ownerDocument?.activeElement;
        if (automatic && focused && this.contains(focused) && focused.matches('input,textarea,select,button,[tabindex]')) {
            this.deferredRender = true;
            const banner = this.querySelector('[data-status-banner]');
            if (banner) banner.textContent = this._statusError ? `Stale / unavailable: ${this._statusError}. Displayed snapshot is not current.` : 'New snapshot received; display will update when focus leaves the control.';
            return;
        }
        this.deferredRender = false;
        const scrolls = [...this.querySelectorAll('[data-scroll-key],.floor-section,.board,.entities')].map(el => ({ key: el.getAttribute('data-scroll-key') || el.className, x: el.scrollLeft, y: el.scrollTop }));
        const top = this.scrollTop; const left = this.scrollLeft;
        this.innerHTML = `<style>${panelStyles}</style><div class="pc-shell">
      <header><div><h1>Predictive Controls</h1><p>Build the motion graph and configure one fast, evidence-aware active control per zone.</p></div>
        <div class="pc-actions"><button data-action="reload"${this.loading ? ' disabled' : ''}>Reload</button><button class="primary" data-action="save"${this.saving || !this._config ? ' disabled' : ''}>${this.saving ? 'Saving…' : 'Save'}</button></div></header>
      <p class="pc-error" role="alert" data-error>${e(this._error || this.fieldError || '')}</p>
      <p role="status" data-status-banner>${this._statusError ? `Stale / unavailable: ${e(this._statusError)}. Last successful snapshot is historical.` : ''}</p>
      ${this._config ? `<nav aria-label="Panel tabs">${tabs.map(tab => `<button class="${this._tab === tab ? 'active' : ''}" aria-pressed="${this._tab === tab}" data-tab="${tab}">${tab === 'yaml' ? 'YAML' : tab[0]?.toUpperCase() + tab.slice(1)}</button>`).join('\n')}</nav>${this.renderActiveTab()}` : `<p>${this._error ? 'Unable to load configuration. Use Reload to retry.' : 'Loading Predictive Controls...'}</p>`}
    </div>`;
        this.scrollTop = top; this.scrollLeft = left;
        for (const element of this.querySelectorAll('[data-scroll-key],.floor-section,.board,.entities')) {
            const key = element.getAttribute('data-scroll-key') || element.className;
            const previous = scrolls.find(item => item.key === key);
            if (previous) { element.scrollLeft = previous.x; element.scrollTop = previous.y; }
        }
        if (this.ownerDocument) {
            for (const input of this.querySelectorAll('[data-field]')) {
                if (!(input instanceof HTMLInputElement) && !(input instanceof HTMLTextAreaElement)) continue;
                const draft = this.invalidFields.get(`${this._selectedNode}\0${input.dataset.field}`);
                if (draft) { input.value = draft.value; input.setAttribute('aria-invalid', 'true'); }
            }
            // Inspector commits on change. Freeze graph controls during save so
            // uncommitted typing cannot disappear when the response rerenders it.
            if (this.saving) {
                for (const control of this.querySelectorAll('.map-layout button,.map-layout input,.map-layout textarea')) {
                    if (control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement || control instanceof HTMLButtonElement) control.disabled = true;
                }
                for (const draggable of this.querySelectorAll('.map-layout [draggable]')) {
                    if (draggable instanceof HTMLElement) draggable.draggable = false;
                }
            }
            this.bindEvents();
        }
    }
    private renderActiveTab(): string {
        const config = this._config;
        if (!config) return '';
        const ctx = this.context();
        if (this._tab === 'occupancy') return renderOccupancy(ctx, this.clientWidth || 0);
        if (this._tab === 'reliability') return renderReliability(ctx);
        if (this._tab === 'activity') return renderActivity(ctx, this._activityFilter, this._auditLimit);
        if (this._tab === 'settings') return renderSettings(config, this._cleanupMessage, this.cleaning);
        if (this._tab === 'yaml') { if (!this._mapYamlDirty) this.syncMapYamlFromMap(); return renderYaml(config.map_yaml); }
        return renderMap({ map: ctx.map, entities: this._entities, selectedNode: this._selectedNode, connectMode: this._connectMode, filter: this.entityFilter, fieldError: this.fieldError });
    }
    /** Generated compatibility asset delegates the old test helper to the actual card component. */
    renderZoneCard(zone: ZoneSummary, minX: number, minY: number): string {
        const ctx = this.context();
        const normalized = { ...zone, position: { x: zone.position.x ?? 80, y: zone.position.y ?? 80 }, size: { width: zone.size.width ?? 210, height: zone.size.height ?? 112 } };
        return renderZoneCard(normalized, minX, minY, ctx, projectPaths(ctx.map, ctx.status?.occupancy_diagnostics, ctx.status?.expected_occupants));
    }
    private bindEvents(): void {
        this.removeEventListener('focusout', this.finishDeferredRender);
        this.addEventListener('focusout', this.finishDeferredRender);
        this.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => {
            if (!(button instanceof HTMLElement) || !isTab(button.dataset.tab)) return;
            if (button.dataset.tab === 'map' && this._mapYamlDirty && this._config) {
                try {
                    this._config.map = parseMapYaml(this._config.map_yaml);
                    if (this._selectedNode && !Object.hasOwn(this.nodes, this._selectedNode)) this._selectedNode = undefined;
                    for (const [key, draft] of this.invalidFields) if (!Object.hasOwn(this.nodes, draft.node)) this.invalidFields.delete(key);
                    this.fieldError = this.invalidFields.values().next().value?.error;
                    this._error = undefined;
                } catch (error) { this._error = errorMessage(error); this.render(); return; }
            }
            this._tab = button.dataset.tab; this.render();
            if (['occupancy', 'reliability', 'activity'].includes(this._tab)) void this.refreshStatus();
        }));
        this.querySelector('[data-action="reload"]')?.addEventListener('click', () => {
            if (this.revision !== this.savedRevision || this.fieldError) {
                if (!confirm('Discard unsaved edits and reload configuration?')) return;
                this.savedRevision = ++this.revision; this.fieldError = undefined; this.invalidFields.clear();
            }
            void this.loadData();
        });
        this.querySelector('[data-action="save"]')?.addEventListener('click', () => { void this.save(); });
        this.querySelector('[data-action="refresh-status"]')?.addEventListener('click', () => { void this.refreshStatus(); });
        if (this._tab === 'activity') bindActivity(this, { filter: value => { this._activityFilter = value; this._auditLimit = 50; this.render(); }, more: () => { this._auditLimit += 50; this.render(); } });
        if (this._tab === 'map') bindMap(this, {
            select: id => this.selectOrConnect(id), add: () => this.addNode(), remove: () => this.deleteSelected(),
            connect: () => { this._connectMode = !this._connectMode; this.render(); }, move: (id, x, y) => this.moveNode(id, x, y),
            addEntity: (id, x, y) => this.addNodeForEntity(id, x, y), updateField: (field, value) => this.updateField(field, value),
            removeEdge: target => this.removeEdge(this._selectedNode, target), filter: value => this.filterEntities(value),
        });
        if (this._tab === 'settings') bindSettings(this, {
            setting: (field, value) => {
                if (!this._config) return;
                if (field === 'expected_occupants_entity') this._config.expected_occupants_entity = value;
                else if (field === 'expected_occupants') this._config.expected_occupants = value.trim() ? Number(value) : NaN;
                else if (field === 'transition_window_seconds') this._config.transition_window_seconds = value.trim() ? Number(value) : NaN;
                this.revision++;
            }, cleanup: () => { void this.cleanupEntities(); }
        });
        if (this._tab === 'yaml') bindYaml(this, value => {
            if (!this._config) return;
            this._config.map_yaml = value; this._mapYamlDirty = true; this.revision++;
        });
    }
    private edit(action: () => void, field?: { node: string; field: string; value: string }): void {
        const key = field ? `${field.node}\0${field.field}` : undefined;
        try {
            if (this._mapYamlDirty && this._config) this._config.map = parseMapYaml(this._config.map_yaml);
            action();
            if (key) this.invalidFields.delete(key);
            this.fieldError = this.invalidFields.values().next().value?.error;
            this.markMapChanged(); this.render();
        } catch (error) {
            this.fieldError = errorMessage(error);
            if (field && key) this.invalidFields.set(key, { ...field, error: this.fieldError });
            // Invalid user input remains in the actual input element, never discarded by render.
            const message = this.querySelector('[data-error]'); if (message) message.textContent = this.fieldError;
        }
    }
    selectOrConnect(id: string): void {
        if (!Object.hasOwn(this.nodes, id)) return;
        if (this._connectMode && this._selectedNode && this._selectedNode !== id) {
            this.addEdge(this._selectedNode, id); this._connectMode = false;
        }
        this._selectedNode = id; this.render();
    }
    addNodeForEntity(id: string, x: number, y: number): void {
        this.edit(() => {
            const entity = this._entities.find(item => item.entity_id === id);
            if (!entity) throw new Error('Entity is not in the current catalog');
            const { nodeId, node } = createNodeForEntity(this.nodes, entity, x, y);
            Object.defineProperty(this.nodes, nodeId, { value: node, enumerable: true, writable: true, configurable: true }); this._selectedNode = nodeId;
        });
    }
    addNode(): void { this.edit(() => { const { nodeId, node } = createEmptyNode(this.nodes); this.nodes[nodeId] = node; this._selectedNode = nodeId; }); }
    moveNode(id: string, x: number, y: number): void { this.edit(() => { moveNode(this.nodes, id, x, y); }); }
    private updateField(field: string, value: string): void {
        const selected = this._selectedNode;
        if (!selected) return;
        this.edit(() => {
            const id = this._selectedNode; const node = id ? this.nodes[id] : undefined;
            if (!node || !id) return;
            if (field === 'node_id') {
                const renamed = renameNode(this.nodes, id, value);
                this._selectedNode = renamed;
                if (renamed !== id) for (const [key, draft] of [...this.invalidFields]) {
                    if (draft.node !== id) continue;
                    this.invalidFields.delete(key);
                    if (draft.field !== 'node_id') this.invalidFields.set(`${renamed}\0${draft.field}`, { ...draft, node: renamed });
                }
                return;
            }
            const changed = { ...node };
            if (field === 'entities') changed.entities = parseEntities(value);
            else if (field === 'x' || field === 'y') {
                const number = value.trim() ? Number(value) : NaN;
                if (!Number.isFinite(number) || number < 0) throw new Error('Position must be finite and nonnegative');
                changed.position = { x: node.position?.x ?? 80, y: node.position?.y ?? 80, ...node.position, [field]: number };
            } else if (field === 'reliability' || field === 'route_prior_weight') {
                const number = value.trim() ? Number(value) : NaN;
                if (!(number > 0)) throw new Error('Weight must be positive');
                changed[field] = number;
            } else if (field === 'label' || field === 'role' || field === 'occupancy_behavior' || field === 'floor' || field === 'zone') {
                if (field === 'zone' && !value) delete changed.zone; else changed[field] = value;
            } else throw new Error('Unknown node field');
            this.nodes[id] = decodeNode(changed);
        }, { node: selected, field, value });
    }
    addEdge(source: string, target: string): void { this.edit(() => { addBidirectionalEdge(this.nodes, source, target); }); }
    removeEdge(source: string | undefined, target: string): void { if (source) this.edit(() => { removeBidirectionalEdge(this.nodes, source, target); }); }
    deleteSelected(): void {
        this.edit(() => {
            if (this._selectedNode) {
                deleteNode(this.nodes, this._selectedNode);
                for (const [key, draft] of this.invalidFields) if (draft.node === this._selectedNode) this.invalidFields.delete(key);
            }
            this._selectedNode = undefined;
        });
    }
    markMapChanged(): void { this.revision++; this._mapYamlDirty = false; this.syncMapYamlFromMap(); }
    syncMapYamlFromMap(): void { if (this._config) this._config.map_yaml = dumpMapYaml(this._config.map); }
    filterEntities(value: string): void {
        this.entityFilter = value;
        this.querySelectorAll('[data-entity]').forEach(item => {
            if (!(item instanceof HTMLElement)) return;
            const entity = this._entities.find(row => row.entity_id === item.dataset.entity);
            item.hidden = !entity || !entityMatchesFilter(entity, value);
        });
    }
    async save(): Promise<void> {
        const hass = this._hass; const config = this._config;
        if (!hass || !config || this.saving || this.cleaning || this.loading || this.detached) return;
        let generation = this.generation;
        const revision = this.revision;
        this.saving = true; this._error = undefined;
        try {
            if (this.fieldError) throw new Error(this.fieldError);
            validateSettings(config);
            if (this._mapYamlDirty) parseMapYaml(config.map_yaml); else this.syncMapYamlFromMap();
            const message = {
                type: 'predictive_controls/save_config', entry_id: config.entry_id, map: decodeMap(config.map), map_yaml: config.map_yaml,
                map_yaml_dirty: this._mapYamlDirty === true, transition_window_seconds: config.transition_window_seconds,
                expected_occupants: config.expected_occupants, expected_occupants_entity: config.expected_occupants_entity || ''
            } satisfies Parameters<Hass['callWS']>[0];
            generation = this.invalidate();
            this._statusError = 'Configuration save pending; awaiting a fresh runtime snapshot';
            this.render();
            const result = decodeConfig(await request(hass, message));
            if (!this.current(generation)) return;
            if (this.revision === revision) { this._config = result; this._mapYamlDirty = false; this.savedRevision = revision; }
        } catch (error) { if (this.current(generation)) this._error = errorMessage(error); }
        finally { this.saving = false; if (!this.detached) this.render(); }
    }
    async cleanupEntities(): Promise<void> {
        const hass = this._hass; const config = this._config;
        if (!hass || !config || this.cleaning || this.saving || this.detached) return;
        const generation = this.generation;
        this.cleaning = true; this._error = undefined; this.render();
        try {
            const count = decodeCleanup(await request(hass, { type: 'predictive_controls/cleanup_entities', entry_id: config.entry_id, dry_run: true }), true);
            if (!this.current(generation)) return;
            if (!count) { this._cleanupMessage = 'No stale entities found.'; return; }
            if (!confirm(`Remove ${count} stale Predictive Controls entities?`)) return;
            if (!this.current(generation)) return;
            const removed = decodeCleanup(await request(hass, { type: 'predictive_controls/cleanup_entities', entry_id: config.entry_id, dry_run: false }), false);
            if (this.current(generation)) this._cleanupMessage = `Removed ${removed} stale entities.`;
        } catch (error) { if (this.current(generation)) this._error = errorMessage(error); }
        finally { this.cleaning = false; if (!this.detached) this.render(); }
    }
}

if (!customElements.get('predictive-controls-panel')) customElements.define('predictive-controls-panel', PredictiveControlsPanel);