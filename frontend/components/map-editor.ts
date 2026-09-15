import type { Entity, MapNode, PredictiveMap } from '../types.ts';
import { escapeHtml, labelFromValue } from '../formatting.ts';
import { formatEntities } from '../yaml.ts';
import { defaultBehaviorForRole } from '../map-helpers.ts';

export interface MapEditorProps {
    map: PredictiveMap;
    entities: readonly Entity[];
    selectedNode: string | undefined;
    connectMode: boolean;
    filter: string;
    fieldError?: string | undefined;
}

export interface MapActions {
    select(nodeId: string): void;
    add(): void;
    remove(): void;
    connect(): void;
    move(nodeId: string, x: number, y: number): void;
    addEntity(entityId: string, x: number, y: number): void;
    updateField(field: string, value: string): void;
    removeEdge(target: string): void;
    filter(value: string): void;
}

function nodeBehavior(map: PredictiveMap, node: MapNode): string {
    const zone = Object.entries(map.zones ?? {}).find(([zoneId]) => zoneId === node.zone)?.[1];
    return node.occupancy_behavior || zone?.occupancy_behavior || defaultBehaviorForRole(node.role);
}

function nodeEntitySummary(node: MapNode, fallback: string): string {
    const entities = Object.values(node.entities ?? {}).flatMap(value => typeof value === 'string' ? [value] : value);
    const first = entities[0];
    if (first === undefined) return fallback;
    return entities.length === 1 ? first : `${first} + ${entities.length - 1} more`;
}

/** Inspector presentation only. Alias arrays remain arrays in YAML flow syntax. */
function entityMappingText(node: MapNode): string {
    return formatEntities(node.entities ?? {});
}

function displayCoordinate(value: number | undefined): number {
    return value !== undefined && Number.isFinite(value) ? value : 80;
}

function renderEntities(entities: readonly Entity[], filter: string): string {
    const query = filter.toLowerCase();
    let visible = 0;
    const rows = entities.map(entity => {
        const matches = [entity.entity_id, entity.name, entity.device_class, entity.state]
            .some(value => value !== undefined && value !== null && value.toLowerCase().includes(query));
        if (matches) visible += 1;
        return `
      <div class="entity" draggable="true" data-entity="${escapeHtml(entity.entity_id)}"${matches ? '' : ' hidden'}>
        <strong>${escapeHtml(entity.name || entity.entity_id)}</strong>
        <span>${escapeHtml(entity.entity_id)}</span>
        <small>${escapeHtml(entity.device_class || 'binary_sensor')} · ${escapeHtml(entity.state ?? 'unknown')}</small>
        <button type="button" data-add-entity="${escapeHtml(entity.entity_id)}" aria-label="${escapeHtml(`Add ${entity.name || entity.entity_id} to map`)}">Add to Map</button>
      </div>
    `;
    }).join('');
    return rows + (visible ? '' : `<p class="empty-state">${entities.length ? 'No entities match the filter.' : 'No motion entities available.'}</p>`);
}

function renderNode(props: MapEditorProps, nodeId: string, node: MapNode): string {
    return `
    <button type="button" class="node ${props.selectedNode === nodeId ? 'selected' : ''}" draggable="true" data-node="${escapeHtml(nodeId)}" aria-pressed="${props.selectedNode === nodeId ? 'true' : 'false'}" style="left:${displayCoordinate(node.position?.x)}px;top:${displayCoordinate(node.position?.y)}px">
      <strong>${escapeHtml(node.label || nodeId)}</strong>
      <span>${escapeHtml(nodeEntitySummary(node, nodeId))}</span>
      <small>${escapeHtml(labelFromValue(nodeBehavior(props.map, node)))} · ${escapeHtml(labelFromValue(node.role || 'room_occupancy'))}</small>
    </button>
  `;
}

function renderEdges(nodes: ReadonlyMap<string, MapNode>): string {
    const seen = new Set<string>();
    const lines: string[] = [];
    for (const [sourceId, source] of nodes) {
        for (const targetId of source.adjacent ?? []) {
            const target = nodes.get(targetId);
            if (!target || targetId === sourceId) continue;
            const key = JSON.stringify([sourceId, targetId].sort());
            if (seen.has(key)) continue;
            seen.add(key);
            lines.push(`<line x1="${displayCoordinate(source.position?.x) + 90}" y1="${displayCoordinate(source.position?.y) + 28}" x2="${displayCoordinate(target.position?.x) + 90}" y2="${displayCoordinate(target.position?.y) + 28}" />`);
        }
    }
    return lines.join('');
}

function renderInspector(props: MapEditorProps, nodeId: string, node: MapNode): string {
    // Include inbound-only links as well: removal is a bidirectional parent action.
    const adjacent = new Set(node.adjacent ?? []);
    for (const [sourceId, source] of Object.entries(props.map.nodes)) {
        if (source.adjacent?.includes(nodeId)) adjacent.add(sourceId);
    }
    return `
    <label>Node ID<input data-field="node_id" value="${escapeHtml(nodeId)}" /></label>
    <label>Label<input data-field="label" value="${escapeHtml(node.label || nodeId)}" /></label>
    <label>Zone<input data-field="zone" value="${escapeHtml(node.zone ?? '')}" placeholder="Defaults to node ID" /></label>
    <label>Floor<input data-field="floor" value="${escapeHtml(node.floor ?? '')}" /></label>
    <label>Role<input data-field="role" value="${escapeHtml(node.role || 'room_occupancy')}" /></label>
    <label>Occupancy behavior<input data-field="occupancy_behavior" value="${escapeHtml(nodeBehavior(props.map, node))}" /></label>
    <label>Entities<textarea class="small" data-field="entities" spellcheck="false">${escapeHtml(entityMappingText(node))}</textarea></label>
    <small>One kind per line; use an array for aliases, for example motion: ["binary_sensor.a", "binary_sensor.b"].</small>
    <label>Sensor reliability<input data-field="reliability" type="number" min="0.01" max="1" step="0.01" value="${escapeHtml(node.reliability ?? 1)}" /></label>
    <label>Route prior weight<input data-field="route_prior_weight" type="number" min="0.01" step="0.01" value="${escapeHtml(node.route_prior_weight ?? 1)}" /></label>
    <label>X position<input data-field="x" type="number" min="0" step="1" value="${displayCoordinate(node.position?.x)}" /></label>
    <label>Y position<input data-field="y" type="number" min="0" step="1" value="${displayCoordinate(node.position?.y)}" /></label>
    <h3>Adjacent</h3>
    <div class="chips">
      ${adjacent.size ? [...adjacent].map(target => `<button type="button" data-remove-adjacent="${escapeHtml(target)}" aria-label="${escapeHtml(`Remove edge to ${target} in both directions`)}">${escapeHtml(target)} ×</button>`).join('') : '<p>No edges yet.</p>'}
    </div>
  `;
}

/** Rendering never edits a map, creates entities, or updates selection. */
export function renderMap(props: MapEditorProps): string {
    const nodes = new Map(Object.entries(props.map.nodes));
    const selected = props.selectedNode === undefined ? undefined : nodes.get(props.selectedNode);
    return `
    <main class="map-layout">
      <section class="entity-list">
        <h2>Motion Entities</h2>
        <input data-filter placeholder="Filter entities" aria-label="Filter entities" value="${escapeHtml(props.filter)}" />
        <div class="entities">${renderEntities(props.entities, props.filter)}</div>
      </section>
      <section class="board-wrap">
        <div class="toolbar">
          <button type="button" data-action="add-empty">Add Node</button>
          <button type="button" data-action="connect" class="${props.connectMode ? 'active' : ''}" aria-pressed="${props.connectMode ? 'true' : 'false'}">Connect</button>
          <button type="button" data-action="delete"${selected ? '' : ' disabled'}>Delete</button>
        </div>
        ${props.connectMode ? '<p role="status">Select a source node, then a different destination to connect them in both directions. Select Connect again to cancel.</p>' : ''}
        <div class="board" data-board role="group" aria-label="Editable motion graph">
          <svg class="edges" aria-hidden="true">${renderEdges(nodes)}</svg>
          ${[...nodes].map(([nodeId, node]) => renderNode(props, nodeId, node)).join('')}
        </div>
      </section>
      <section class="inspector">
        <h2>Node</h2>
        ${props.fieldError !== undefined ? `<p class="pc-error" role="alert">${escapeHtml(props.fieldError)}</p>` : ''}
        ${selected && props.selectedNode !== undefined ? renderInspector(props, props.selectedNode, selected) : '<p>Select a node to edit it.</p>'}
      </section>
    </main>
  `;
}

function bindButton(root: HTMLElement, selector: string, action: () => void): void {
    const button = root.querySelector(selector);
    if (!(button instanceof HTMLButtonElement)) return;
    button.addEventListener('click', event => {
        if (event.currentTarget instanceof HTMLButtonElement && !event.currentTarget.disabled) action();
    });
}

function startDrag(event: DragEvent, key: 'node_id' | 'entity_id', id: string): void {
    const transfer = event.dataTransfer;
    if (!transfer) return;
    try {
        // A drag has exactly one identity, even when the browser reuses its store.
        transfer.clearData('node_id');
        transfer.clearData('entity_id');
        transfer.setData(key, id);
        transfer.effectAllowed = key === 'node_id' ? 'move' : 'copy';
    } catch {
        // Unwritable drag stores must not cause an edit or break keyboard controls.
        event.preventDefault();
    }
}

function bindDragAndDrop(root: HTMLElement, actions: MapActions): void {
    const entityIds = new Set<string>();
    const nodeIds = new Set<string>();
    root.querySelectorAll('[data-entity]').forEach(item => {
        if (!(item instanceof HTMLElement)) return;
        const entityId = item.dataset.entity;
        if (entityId === undefined) return;
        entityIds.add(entityId);
        item.addEventListener('dragstart', event => {
            const target = event.currentTarget;
            if (target instanceof HTMLElement && target.dataset.entity === entityId && !target.hidden) {
                startDrag(event, 'entity_id', entityId);
            }
        });
    });
    root.querySelectorAll('[data-node]').forEach(button => {
        if (!(button instanceof HTMLButtonElement)) return;
        const nodeId = button.dataset.node;
        if (nodeId === undefined) return;
        nodeIds.add(nodeId);
        button.addEventListener('click', event => {
            const target = event.currentTarget;
            if (target instanceof HTMLButtonElement && !target.disabled) actions.select(nodeId);
        });
        button.addEventListener('dragstart', event => {
            const target = event.currentTarget;
            if (target instanceof HTMLButtonElement && !target.disabled) startDrag(event, 'node_id', nodeId);
        });
    });
    const board = root.querySelector('[data-board]');
    if (!(board instanceof HTMLElement)) return;
    board.addEventListener('dragover', event => {
        const transfer = event.dataTransfer;
        if (transfer && (transfer.types.includes('node_id') || transfer.types.includes('entity_id'))) {
            event.preventDefault();
        }
    });
    board.addEventListener('drop', event => {
        const target = event.currentTarget;
        const transfer = event.dataTransfer;
        if (!(target instanceof HTMLElement) || !transfer) return;
        event.preventDefault();
        let entityId: string;
        let nodeId: string;
        try {
            entityId = transfer.getData('entity_id');
            nodeId = transfer.getData('node_id');
        } catch {
            return;
        }
        // Ignore external, stale or ambiguous payloads; do not invent unknown entities.
        if (entityId && nodeId) return;
        const rect = target.getBoundingClientRect();
        const x = Math.max(0, event.clientX - rect.left - target.clientLeft + target.scrollLeft - 90);
        const y = Math.max(0, event.clientY - rect.top - target.clientTop + target.scrollTop - 28);
        if (!Number.isFinite(x) || !Number.isFinite(y)) return;
        if (entityId && entityIds.has(entityId)) actions.addEntity(entityId, x, y);
        else if (nodeId && nodeIds.has(nodeId)) actions.move(nodeId, x, y);
    });
}

/** Parent callbacks own pure map editing, field validation and connect-mode state. */
export function bindMap(root: HTMLElement, actions: MapActions): void {
    bindButton(root, '[data-action="add-empty"]', () => actions.add());
    bindButton(root, '[data-action="delete"]', () => actions.remove());
    bindButton(root, '[data-action="connect"]', () => actions.connect());
    bindDragAndDrop(root, actions);
    root.querySelectorAll('[data-add-entity]').forEach(button => {
        if (!(button instanceof HTMLButtonElement)) return;
        button.addEventListener('click', event => {
            const target = event.currentTarget;
            if (!(target instanceof HTMLButtonElement) || target.disabled) return;
            const entityId = target.dataset.addEntity;
            if (entityId !== undefined) actions.addEntity(entityId, 80, 80);
        });
    });
    root.querySelectorAll('[data-field]').forEach(input => {
        if (!(input instanceof HTMLInputElement) && !(input instanceof HTMLTextAreaElement)) return;
        input.addEventListener('change', event => {
            const target = event.target;
            if (!(target instanceof HTMLInputElement) && !(target instanceof HTMLTextAreaElement)) return;
            if (target !== input || target.disabled || target.readOnly) return;
            const field = target.dataset.field;
            if (field === 'node_id' || field === 'label' || field === 'zone' || field === 'floor'
                || field === 'role' || field === 'occupancy_behavior' || field === 'entities'
                || field === 'reliability' || field === 'route_prior_weight' || field === 'x' || field === 'y') {
                actions.updateField(field, target.value);
            }
        });
    });
    root.querySelectorAll('[data-remove-adjacent]').forEach(button => {
        if (!(button instanceof HTMLButtonElement)) return;
        button.addEventListener('click', event => {
            const target = event.currentTarget;
            if (!(target instanceof HTMLButtonElement) || target.disabled) return;
            const adjacent = target.dataset.removeAdjacent;
            if (adjacent !== undefined) actions.removeEdge(adjacent);
        });
    });
    const filter = root.querySelector('[data-filter]');
    if (filter instanceof HTMLInputElement) {
        filter.addEventListener('input', event => {
            const target = event.target;
            if (target instanceof HTMLInputElement && target === filter && !target.disabled) actions.filter(target.value);
        });
    }
}