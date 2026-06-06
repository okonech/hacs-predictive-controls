function sanitizeNodeId(value) {
  const sanitized = String(value || "node")
    .replace(/^.*\./, "")
    .replace(/[^a-zA-Z0-9_]/g, "_")
    .replace(/^_+|_+$/g, "");
  return sanitized || "node";
}

function uniqueNodeId(nodes, base) {
  const sanitizedBase = sanitizeNodeId(base);
  let candidate = sanitizedBase;
  let index = 2;
  while (nodes[candidate]) {
    candidate = `${sanitizedBase}_${index}`;
    index += 1;
  }
  return candidate;
}

function createNodeForEntity(nodes, entity, x, y) {
  const entityId = entity.entity_id;
  const nodeId = uniqueNodeId(nodes, entityId);
  return {
    nodeId,
    node: {
      label: entity.name || entityId,
      entities: { motion: entityId },
      adjacent: [],
      initial_weight: 1,
      position: { x: Math.round(Math.max(0, x)), y: Math.round(Math.max(0, y)) },
    },
  };
}

function createEmptyNode(nodes) {
  const nodeId = uniqueNodeId(nodes, "node");
  return {
    nodeId,
    node: {
      label: nodeId,
      entities: {},
      adjacent: [],
      initial_weight: 1,
      position: { x: 80, y: 80 },
    },
  };
}

function moveNode(nodes, nodeId, x, y) {
  if (!nodes[nodeId]) return nodes;
  nodes[nodeId].position = {
    x: Math.round(Math.max(0, x)),
    y: Math.round(Math.max(0, y)),
  };
  return nodes;
}

function addBidirectionalEdge(nodes, source, target) {
  if (!nodes[source] || !nodes[target] || source === target) return nodes;
  nodes[source].adjacent = Array.from(
    new Set([...(nodes[source].adjacent || []), target]),
  );
  nodes[target].adjacent = Array.from(
    new Set([...(nodes[target].adjacent || []), source]),
  );
  return nodes;
}

function removeBidirectionalEdge(nodes, source, target) {
  if (!nodes[source] || !nodes[target]) return nodes;
  nodes[source].adjacent = (nodes[source].adjacent || []).filter(
    (item) => item !== target,
  );
  nodes[target].adjacent = (nodes[target].adjacent || []).filter(
    (item) => item !== source,
  );
  return nodes;
}

function renameNode(nodes, oldId, newId) {
  const sanitizedNewId = sanitizeNodeId(newId);
  if (!nodes[oldId] || !sanitizedNewId || sanitizedNewId === oldId) {
    return oldId;
  }
  if (nodes[sanitizedNewId]) return oldId;

  nodes[sanitizedNewId] = nodes[oldId];
  delete nodes[oldId];
  for (const node of Object.values(nodes)) {
    node.adjacent = (node.adjacent || []).map((target) =>
      target === oldId ? sanitizedNewId : target,
    );
  }
  return sanitizedNewId;
}

function deleteNode(nodes, nodeId) {
  if (!nodes[nodeId]) return nodes;
  delete nodes[nodeId];
  for (const node of Object.values(nodes)) {
    node.adjacent = (node.adjacent || []).filter((target) => target !== nodeId);
  }
  return nodes;
}

function entityMatchesFilter(entity, filterText) {
  const query = String(filterText || "").toLowerCase();
  if (!query) return true;
  return [entity.entity_id, entity.name, entity.device_class, entity.state]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(query));
}

function normalizeEntityResponse(response) {
  return [...(response?.entities || [])].sort((left, right) =>
    left.entity_id.localeCompare(right.entity_id),
  );
}

class PredictiveControlsPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this.loadData();
    }
  }

  async loadData() {
    this._error = undefined;
    try {
      const [config, entityResponse] = await Promise.all([
        this._hass.callWS({ type: "predictive_controls/config" }),
        this._hass.callWS({ type: "predictive_controls/entities" }),
      ]);
      this._config = config;
      this._entities = normalizeEntityResponse(entityResponse);
      this._selectedNode = undefined;
      this._tab = this._tab || "map";
      this.render();
    } catch (error) {
      this._error = error.message || String(error);
      this.render();
    }
  }

  connectedCallback() {
    this.render();
  }

  get nodes() {
    return this._config?.map?.nodes || {};
  }

  render() {
    if (!this._hass) return;
    if (!this._config) {
      this.innerHTML = `<div class="pc-shell"><p>${this._error || "Loading Predictive Controls..."}</p></div>`;
      return;
    }

    this.innerHTML = `
      <style>${this.styles()}</style>
      <div class="pc-shell">
        <header>
          <div>
            <h1>Predictive Controls</h1>
            <p>Build the motion graph, tune predictive actions, and save it locally to Home Assistant.</p>
          </div>
          <div class="pc-actions">
            <button data-action="reload">Reload</button>
            <button class="primary" data-action="save">Save</button>
          </div>
        </header>
        <nav>
          <button class="${this._tab === "map" ? "active" : ""}" data-tab="map">Map</button>
          <button class="${this._tab === "actions" ? "active" : ""}" data-tab="actions">Actions</button>
          <button class="${this._tab === "settings" ? "active" : ""}" data-tab="settings">Settings</button>
        </nav>
        ${this._tab === "actions" ? this.renderActions() : this._tab === "settings" ? this.renderSettings() : this.renderMap()}
      </div>
    `;
    this.bindEvents();
  }

  renderMap() {
    const selected = this._selectedNode ? this.nodes[this._selectedNode] : undefined;
    return `
      <main class="map-layout">
        <section class="entity-list">
          <h2>Motion Entities</h2>
          <input data-filter placeholder="Filter entities" />
          <div class="entities">
            ${this.renderEntities()}
          </div>
        </section>
        <section class="board-wrap">
          <div class="toolbar">
            <button data-action="add-empty">Add Node</button>
            <button data-action="connect" class="${this._connectMode ? "active" : ""}">Connect</button>
            <button data-action="delete" ${this._selectedNode ? "" : "disabled"}>Delete</button>
          </div>
          <div class="board" data-board>
            <svg class="edges">${this.renderEdges()}</svg>
            ${Object.entries(this.nodes).map(([nodeId, node]) => this.renderNode(nodeId, node)).join("")}
          </div>
        </section>
        <section class="inspector">
          <h2>Node</h2>
          ${selected ? this.renderInspector(this._selectedNode, selected) : "<p>Select a node to edit it.</p>"}
        </section>
      </main>
    `;
  }

  renderEntities() {
    return (this._entities || [])
      .map((entity) => `
        <div class="entity" draggable="true" data-entity="${entity.entity_id}">
          <strong>${entity.name}</strong>
          <span>${entity.entity_id}</span>
          <small>${entity.device_class || "binary_sensor"} · ${entity.state}</small>
        </div>
      `)
      .join("");
  }

  renderNode(nodeId, node) {
    const position = node.position || {};
    const x = Number(position.x ?? 80);
    const y = Number(position.y ?? 80);
    return `
      <button class="node ${this._selectedNode === nodeId ? "selected" : ""}" draggable="true" data-node="${nodeId}" style="left:${x}px;top:${y}px">
        <strong>${node.label || nodeId}</strong>
        <span>${Object.values(node.entities || {})[0] || nodeId}</span>
      </button>
    `;
  }

  renderEdges() {
    const entries = Object.entries(this.nodes);
    const lines = [];
    for (const [sourceId, source] of entries) {
      for (const targetId of source.adjacent || []) {
        if (sourceId > targetId || !this.nodes[targetId]) continue;
        const a = source.position || {};
        const b = this.nodes[targetId].position || {};
        lines.push(`<line x1="${Number(a.x ?? 80) + 90}" y1="${Number(a.y ?? 80) + 28}" x2="${Number(b.x ?? 80) + 90}" y2="${Number(b.y ?? 80) + 28}" />`);
      }
    }
    return lines.join("");
  }

  renderInspector(nodeId, node) {
    return `
      <label>Node ID<input data-field="node_id" value="${nodeId}" /></label>
      <label>Label<input data-field="label" value="${node.label || nodeId}" /></label>
      <label>Entity<input data-field="entity" value="${Object.values(node.entities || {})[0] || ""}" /></label>
      <label>Initial weight<input data-field="initial_weight" type="number" min="0.01" step="0.01" value="${node.initial_weight || 1}" /></label>
      <h3>Adjacent</h3>
      <div class="chips">
        ${(node.adjacent || []).map((target) => `<button data-remove-adjacent="${target}">${target} ×</button>`).join("") || "<p>No edges yet.</p>"}
      </div>
    `;
  }

  renderActions() {
    return `
      <main class="single-panel">
        <h2>Predictive Actions</h2>
        <textarea data-actions-yaml>${this._config.actions_yaml || ""}</textarea>
      </main>
    `;
  }

  renderSettings() {
    return `
      <main class="single-panel settings">
        <label>Transition window seconds<input data-setting="transition_window_seconds" type="number" min="1" value="${this._config.transition_window_seconds}" /></label>
        <label>Prediction threshold<input data-setting="prediction_threshold" type="number" min="0" max="1" step="0.01" value="${this._config.prediction_threshold}" /></label>
      </main>
    `;
  }

  bindEvents() {
    this.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => {
      this._tab = button.dataset.tab;
      this.render();
    }));
    this.querySelector('[data-action="reload"]')?.addEventListener("click", () => this.loadData());
    this.querySelector('[data-action="save"]')?.addEventListener("click", () => this.save());
    this.querySelector('[data-action="add-empty"]')?.addEventListener("click", () => this.addNode());
    this.querySelector('[data-action="connect"]')?.addEventListener("click", () => {
      this._connectMode = !this._connectMode;
      this.render();
    });
    this.querySelector('[data-action="delete"]')?.addEventListener("click", () => this.deleteSelected());
    this.bindDragAndDrop();
    this.bindInspector();
    this.querySelector("[data-actions-yaml]")?.addEventListener("input", (event) => {
      this._config.actions_yaml = event.target.value;
    });
    this.querySelectorAll("[data-setting]").forEach((input) => input.addEventListener("input", () => {
      this._config[input.dataset.setting] = Number(input.value);
    }));
    this.querySelector("[data-filter]")?.addEventListener("input", (event) => this.filterEntities(event.target.value));
  }

  bindDragAndDrop() {
    this.querySelectorAll("[data-entity]").forEach((item) => item.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("entity_id", item.dataset.entity);
    }));
    this.querySelectorAll("[data-node]").forEach((nodeEl) => {
      nodeEl.addEventListener("click", () => this.selectOrConnect(nodeEl.dataset.node));
      nodeEl.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("node_id", nodeEl.dataset.node);
      });
    });
    const board = this.querySelector("[data-board]");
    board?.addEventListener("dragover", (event) => event.preventDefault());
    board?.addEventListener("drop", (event) => {
      event.preventDefault();
      const rect = board.getBoundingClientRect();
      const x = Math.max(0, event.clientX - rect.left - 90);
      const y = Math.max(0, event.clientY - rect.top - 28);
      const entityId = event.dataTransfer.getData("entity_id");
      const nodeId = event.dataTransfer.getData("node_id");
      if (entityId) this.addNodeForEntity(entityId, x, y);
      if (nodeId) this.moveNode(nodeId, x, y);
    });
  }

  bindInspector() {
    this.querySelectorAll("[data-field]").forEach((input) => input.addEventListener("change", () => this.updateSelectedField(input)));
    this.querySelectorAll("[data-remove-adjacent]").forEach((button) => button.addEventListener("click", () => this.removeEdge(this._selectedNode, button.dataset.removeAdjacent)));
  }

  selectOrConnect(nodeId) {
    if (this._connectMode && this._selectedNode && this._selectedNode !== nodeId) {
      this.addEdge(this._selectedNode, nodeId);
      this._connectMode = false;
    }
    this._selectedNode = nodeId;
    this.render();
  }

  addNodeForEntity(entityId, x, y) {
    const entity = this._entities.find((item) => item.entity_id === entityId);
    const { nodeId, node } = createNodeForEntity(
      this.nodes,
      entity || { entity_id: entityId, name: entityId },
      x,
      y,
    );
    this.nodes[nodeId] = node;
    this._selectedNode = nodeId;
    this.render();
  }

  addNode() {
    const { nodeId, node } = createEmptyNode(this.nodes);
    this.nodes[nodeId] = node;
    this._selectedNode = nodeId;
    this.render();
  }

  moveNode(nodeId, x, y) {
    moveNode(this.nodes, nodeId, x, y);
    this.render();
  }

  updateSelectedField(input) {
    const node = this.nodes[this._selectedNode];
    if (!node) return;
    if (input.dataset.field === "node_id") {
      this._selectedNode = renameNode(this.nodes, this._selectedNode, input.value);
    } else if (input.dataset.field === "entity") {
      node.entities = input.value.trim() ? { motion: input.value.trim() } : {};
    } else if (input.dataset.field === "initial_weight") {
      node.initial_weight = Number(input.value);
    } else {
      node[input.dataset.field] = input.value;
    }
    this.render();
  }

  addEdge(source, target) {
    addBidirectionalEdge(this.nodes, source, target);
  }

  removeEdge(source, target) {
    if (!source || !target) return;
    removeBidirectionalEdge(this.nodes, source, target);
    this.render();
  }

  deleteSelected() {
    if (!this._selectedNode) return;
    deleteNode(this.nodes, this._selectedNode);
    this._selectedNode = undefined;
    this.render();
  }

  filterEntities(value) {
    this.querySelectorAll("[data-entity]").forEach((item) => {
      const entity = this._entities.find(
        (candidate) => candidate.entity_id === item.dataset.entity,
      );
      item.hidden = entity ? !entityMatchesFilter(entity, value) : true;
    });
  }

  async save() {
    try {
      this._config = await this._hass.callWS({
        type: "predictive_controls/save_config",
        entry_id: this._config.entry_id,
        map: this._config.map,
        actions_yaml: this._config.actions_yaml,
        transition_window_seconds: Number(this._config.transition_window_seconds),
        prediction_threshold: Number(this._config.prediction_threshold),
      });
      this.render();
    } catch (error) {
      alert(error.message || String(error));
    }
  }

  styles() {
    return `
      .pc-shell { padding: 24px; color: var(--primary-text-color); }
      header { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:16px; }
      h1 { margin:0; font-size:28px; }
      h2 { margin:0 0 12px; font-size:18px; }
      h3 { margin:18px 0 8px; font-size:14px; }
      p { color: var(--secondary-text-color); }
      button { border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); border-radius:6px; padding:8px 12px; cursor:pointer; }
      button.primary, button.active { background:var(--primary-color); color:var(--text-primary-color); border-color:var(--primary-color); }
      button:disabled { opacity:.5; cursor:not-allowed; }
      nav { display:flex; gap:8px; margin-bottom:16px; }
      .pc-actions { display:flex; gap:8px; }
      .map-layout { display:grid; grid-template-columns:280px minmax(420px, 1fr) 280px; gap:16px; min-height:640px; }
      .entity-list, .board-wrap, .inspector, .single-panel { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:8px; padding:16px; }
      .entity-list input, label input, textarea { width:100%; box-sizing:border-box; margin-top:6px; padding:8px; color:var(--primary-text-color); background:var(--secondary-background-color); border:1px solid var(--divider-color); border-radius:6px; }
      .entities { margin-top:12px; display:grid; gap:8px; max-height:560px; overflow:auto; }
      .entity { border:1px solid var(--divider-color); border-radius:6px; padding:10px; cursor:grab; }
      .entity span, .entity small, .node span { display:block; color:var(--secondary-text-color); font-size:12px; overflow:hidden; text-overflow:ellipsis; }
      .toolbar { display:flex; gap:8px; margin-bottom:12px; }
      .board { position:relative; min-height:580px; overflow:auto; background:var(--secondary-background-color); border:1px dashed var(--divider-color); border-radius:8px; }
      .edges { position:absolute; inset:0; width:2000px; height:1200px; pointer-events:none; }
      .edges line { stroke:var(--primary-color); stroke-width:3; opacity:.75; }
      .node { position:absolute; width:180px; min-height:56px; text-align:left; cursor:grab; box-shadow:var(--ha-card-box-shadow, none); }
      .node.selected { outline:3px solid var(--primary-color); }
      .inspector label, .settings label { display:block; margin-bottom:12px; }
      .chips { display:flex; flex-wrap:wrap; gap:8px; }
      textarea { min-height:520px; font-family:monospace; }
      @media (max-width: 1000px) { .map-layout { grid-template-columns:1fr; } }
    `;
  }
}

if (!customElements.get("predictive-controls-panel")) {
  customElements.define("predictive-controls-panel", PredictiveControlsPanel);
}