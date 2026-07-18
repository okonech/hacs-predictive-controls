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
      role: "room_occupancy",
      occupancy_behavior: "sustained",
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
      role: "room_occupancy",
      occupancy_behavior: "sustained",
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

function titleFromId(value) {
  return String(value || "unknown")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function statusRank(status) {
  return {
    rejected: 0,
    suspect: 1,
    possible: 2,
    probable: 3,
    confirmed: 4,
  }[status] ?? 0;
}

function labelFromValue(value) {
  return titleFromId(value || "unknown");
}

function formatTimestamp(value) {
  if (!value) return "never";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

function formatOccupiedPeak(value) {
  const probability = Number(value);
  return Number.isFinite(probability)
    ? `Peak occupied ${Math.round(probability * 100)}%`
    : "Occupied confidence unavailable";
}

function policyModel(status) {
  const diagnostics = status?.occupancy_diagnostics;
  return diagnostics?.model === "zone_belief" ? diagnostics : null;
}

function auditTransition(entry) {
  return [Boolean(entry?.active_before), Boolean(entry?.active_after)];
}

function auditKind(entry) {
  const [priorActive, resultingActive] = auditTransition(entry);
  if (priorActive !== resultingActive) return "edges";
  if (entry?.reason === "acquisition_unauthorized") return "rejected";
  if (!entry?.event_kind) return "observations";
  return "other";
}

function formatPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0
    ? `${Math.round(number * 100)}%`
    : "unavailable";
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MiB`;
}

function decisionExplanation(decision) {
  const probability = formatPercent(decision?.belief_after);
  const reason = labelFromValue(decision?.reason || "policy observation");
  const traversal = decision?.traversal_reason
    ? ` via ${labelFromValue(decision.traversal_reason)}`
    : "";
  return `${reason} at ${probability}${traversal}`;
}

function defaultBehaviorForRole(role) {
  if (role === "transition_gate") return "transient";
  if (role === "ambiguous_open_plan") return "ambiguous";
  if (role === "anchor_sensor") return "sticky";
  return "sustained";
}

function zoneSummaries(map) {
  const nodes = map?.nodes || {};
  const configuredZones = map?.zones || {};
  const grouped = new Map();
  for (const [nodeId, node] of Object.entries(nodes)) {
    const zoneId = node.zone || nodeId;
    if (!grouped.has(zoneId)) grouped.set(zoneId, []);
    grouped.get(zoneId).push({ nodeId, node });
  }
  for (const zoneId of Object.keys(configuredZones)) {
    if (!grouped.has(zoneId)) grouped.set(zoneId, []);
  }

  return [...grouped.entries()]
    .map(([zoneId, entries]) => {
      const config = configuredZones[zoneId] || {};
      const positions = entries
        .map(({ node }) => node.position)
        .filter((position) => position && Number.isFinite(Number(position.x)) && Number.isFinite(Number(position.y)));
      const average = positions.length
        ? {
          x: Math.round(positions.reduce((sum, position) => sum + Number(position.x), 0) / positions.length),
          y: Math.round(positions.reduce((sum, position) => sum + Number(position.y), 0) / positions.length),
        }
        : { x: 80, y: 80 };
      const roles = new Set(entries.map(({ node }) => node.role).filter(Boolean));
      const behaviors = new Set(entries.map(({ node }) => node.occupancy_behavior).filter(Boolean));
      const role = config.role || (roles.size === 1 ? [...roles][0] : "mixed");
      return {
        zoneId,
        label: config.label || titleFromId(zoneId),
        floor: config.floor || entries.find(({ node }) => node.floor)?.node.floor || "unassigned",
        role,
        occupancyBehavior: config.occupancy_behavior || (behaviors.size === 1 ? [...behaviors][0] : defaultBehaviorForRole(role)),
        position: config.position || average,
        size: config.size || { width: 210, height: 112 },
        nodeIds: entries.map(({ nodeId }) => nodeId),
      };
    })
    .sort((left, right) => left.floor.localeCompare(right.floor) || left.label.localeCompare(right.label));
}

function learnedTransitionRows(map, status) {
  const nodes = map?.nodes || {};
  const counts = status?.transition_counts || {};
  const rows = [];
  for (const [sourceId, targets] of Object.entries(counts)) {
    for (const [targetId, count] of Object.entries(targets || {})) {
      const learnedCount = Number(count || 0);
      if (learnedCount <= 0) continue;
      rows.push({
        sourceId,
        targetId,
        sourceLabel: nodes[sourceId]?.label || titleFromId(sourceId),
        targetLabel: nodes[targetId]?.label || titleFromId(targetId),
        count: learnedCount,
      });
    }
  }
  return rows.sort((left, right) => right.count - left.count || left.sourceLabel.localeCompare(right.sourceLabel) || left.targetLabel.localeCompare(right.targetLabel));
}

// Estimate the height a zone card actually renders at. Cards use a min-height
// from their configured size but grow to fit their content, and a long title
// wraps onto extra lines (e.g. "Ground Floor Bathroom/Laundry Room" renders
// ~182px, not the 112px default). The layout math must reserve this real
// height so vertically stacked cards keep a visible gap for their edges.
function estimateCardHeight(zone) {
  const width = Number(zone.size?.width ?? 210);
  const charsPerLine = Math.max(1, Math.floor((width - 24) / 16));
  const titleLines = Math.max(1, Math.ceil(String(zone.label ?? "").length / charsPerLine));
  const estimated = 138 + 24 * (titleLines - 1);
  return Math.max(estimated, Number(zone.size?.height ?? 0));
}

// Push apart cards on the same floor whose horizontal spans overlap so there is
// always a clear vertical gap (for the connecting edge) between them. Only adds
// downward space and preserves top-to-bottom order, so it stays deterministic.
function separateFloorRows(zones, minGap = 48) {
  if (!zones.length) return zones;
  const byFloor = new Map();
  for (const zone of zones) {
    const list = byFloor.get(zone.floor) || [];
    list.push(zone);
    byFloor.set(zone.floor, list);
  }
  const adjustedY = new Map();
  for (const list of byFloor.values()) {
    const sorted = [...list].sort(
      (a, b) =>
        Number(a.position.y ?? 80) - Number(b.position.y ?? 80) ||
        Number(a.position.x ?? 80) - Number(b.position.x ?? 80),
    );
    const placed = [];
    for (const zone of sorted) {
      const x = Number(zone.position.x ?? 80);
      const w = Number(zone.size?.width ?? 210);
      const h = estimateCardHeight(zone);
      let y = Number(zone.position.y ?? 80);
      for (const p of placed) {
        const overlapsX = x < p.x + p.w && x + w > p.x;
        if (overlapsX && y < p.y + p.h + minGap) {
          y = p.y + p.h + minGap;
        }
      }
      placed.push({ x, y, w, h });
      adjustedY.set(zone.zoneId, Math.round(y));
    }
  }
  return zones.map((zone) => ({
    ...zone,
    position: { ...zone.position, y: adjustedY.get(zone.zoneId) },
  }));
}

function floorBands(zones) {
  const bands = new Map();
  for (const zone of zones) {
    const top = Number(zone.position.y ?? 80);
    const bottom = top + estimateCardHeight(zone);
    const existing = bands.get(zone.floor) || { floor: zone.floor, top, bottom };
    existing.top = Math.min(existing.top, top);
    existing.bottom = Math.max(existing.bottom, bottom);
    bands.set(zone.floor, existing);
  }
  return [...bands.values()].sort((left, right) => left.top - right.top || left.floor.localeCompare(right.floor));
}

function stackFloorsByBand(zones, floorOrder = [], gap = 96) {
  if (!zones.length) return zones;
  const order = Array.isArray(floorOrder) ? floorOrder : [];
  const rank = (floor) => {
    const index = order.indexOf(floor);
    return index === -1 ? order.length : index;
  };
  const byFloor = new Map();
  for (const zone of zones) {
    const list = byFloor.get(zone.floor) || [];
    list.push(zone);
    byFloor.set(zone.floor, list);
  }
  const floors = [...byFloor.entries()]
    .map(([floor, list]) => {
      const top = Math.min(...list.map((zone) => Number(zone.position.y ?? 80)));
      const bottom = Math.max(
        ...list.map((zone) => Number(zone.position.y ?? 80) + estimateCardHeight(zone)),
      );
      return { floor, list, top, bottom };
    })
    .sort(
      (left, right) =>
        rank(left.floor) - rank(right.floor) ||
        left.top - right.top ||
        left.floor.localeCompare(right.floor),
    );
  const result = [];
  let cursor = floors[0].top;
  for (const { list, top, bottom } of floors) {
    const shift = cursor - top;
    for (const zone of list) {
      result.push({
        ...zone,
        position: { ...zone.position, y: Math.round(Number(zone.position.y ?? 80) + shift) },
      });
    }
    cursor += bottom - top + gap;
  }
  return result;
}

function zoneAdjacencyPairs(zones, nodes) {
  const zonesByNode = new Map();
  for (const zone of zones) {
    for (const nodeId of zone.nodeIds) zonesByNode.set(nodeId, zone);
  }
  const seen = new Set();
  const pairs = [];
  for (const zone of zones) {
    for (const nodeId of zone.nodeIds) {
      for (const targetId of nodes?.[nodeId]?.adjacent || []) {
        const target = zonesByNode.get(targetId);
        if (!target || target.zoneId === zone.zoneId) continue;
        const key = [zone.zoneId, target.zoneId].sort().join("->");
        if (seen.has(key)) continue;
        seen.add(key);
        pairs.push([zone.zoneId, target.zoneId]);
      }
    }
  }
  return pairs;
}

function segmentsCross(a, b, c, d) {
  const direction = (p, q, r) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
  const d1 = direction(c, d, a);
  const d2 = direction(c, d, b);
  const d3 = direction(a, b, c);
  const d4 = direction(a, b, d);
  return d1 > 0 !== d2 > 0 && d3 > 0 !== d4 > 0;
}

function pointInRect(point, box) {
  return (
    point.x >= box.x &&
    point.x <= box.x + box.w &&
    point.y >= box.y &&
    point.y <= box.y + box.h
  );
}

function segmentIntersectsRect(p1, p2, box) {
  if (pointInRect(p1, box) || pointInRect(p2, box)) return true;
  const corners = [
    { x: box.x, y: box.y },
    { x: box.x + box.w, y: box.y },
    { x: box.x + box.w, y: box.y + box.h },
    { x: box.x, y: box.y + box.h },
  ];
  for (let i = 0; i < 4; i += 1) {
    if (segmentsCross(p1, p2, corners[i], corners[(i + 1) % 4])) return true;
  }
  return false;
}

function countCrossings(pairs, centerById) {
  let crossings = 0;
  for (let i = 0; i < pairs.length; i += 1) {
    for (let j = i + 1; j < pairs.length; j += 1) {
      const [a1, a2] = pairs[i];
      const [b1, b2] = pairs[j];
      if (a1 === b1 || a1 === b2 || a2 === b1 || a2 === b2) continue;
      if (segmentsCross(centerById[a1], centerById[a2], centerById[b1], centerById[b2])) {
        crossings += 1;
      }
    }
  }
  return crossings;
}

// Reduce visual clutter by swapping zones between positions within the same
// floor band. It minimizes a weighted cost of edge-edge crossings plus
// edge-card crossings (a line cutting through an unrelated card), with card
// crossings weighted higher because they read as messier than open crossings.
// Edge crossing minimization is NP-hard, so this is a deterministic iterated
// local search: only same-floor zones swap (keeping the floor bands and
// footprint unchanged, edges straight and center-to-center, and no card
// overlaps), and a few fixed starting orders are tried to escape local minima.
function minimizeCrossings(zones, nodes) {
  if (zones.length < 3) return zones;
  const pairs = zoneAdjacencyPairs(zones, nodes);
  if (pairs.length < 2) return zones;

  const CARD_CROSSING_WEIGHT = 4;
  const size = {};
  const originalPos = {};
  const originalCenterX = {};
  for (const zone of zones) {
    const w = Number(zone.size.width ?? 210);
    const h = estimateCardHeight(zone);
    size[zone.zoneId] = { w, h };
    originalPos[zone.zoneId] = { x: Number(zone.position.x ?? 80), y: Number(zone.position.y ?? 80) };
    originalCenterX[zone.zoneId] = originalPos[zone.zoneId].x + w / 2;
  }

  const byFloor = new Map();
  for (const zone of zones) {
    const list = byFloor.get(zone.floor) || [];
    list.push(zone.zoneId);
    byFloor.set(zone.floor, list);
  }

  // Fixed set of positions ("slots") available to each floor, and the zone
  // order that reproduces the original layout.
  const slots = new Map();
  const identityOrder = new Map();
  for (const [floor, ids] of byFloor) {
    const sorted = [...ids].sort(
      (a, b) => originalPos[a].x - originalPos[b].x || originalPos[a].y - originalPos[b].y,
    );
    identityOrder.set(floor, sorted);
    slots.set(floor, sorted.map((id) => ({ ...originalPos[id] })));
  }

  const position = {};
  const applyOrder = (order) => {
    for (const [floor, ids] of order) {
      const floorSlots = slots.get(floor);
      ids.forEach((id, index) => {
        position[id] = { ...floorSlots[index] };
      });
    }
  };
  const rectOf = (id) => ({ x: position[id].x, y: position[id].y, w: size[id].w, h: size[id].h });
  const cost = () => {
    const center = {};
    for (const zone of zones) {
      center[zone.zoneId] = { x: position[zone.zoneId].x + size[zone.zoneId].w / 2, y: position[zone.zoneId].y + size[zone.zoneId].h / 2 };
    }
    let total = countCrossings(pairs, center);
    for (const [a, b] of pairs) {
      for (const zone of zones) {
        if (zone.zoneId === a || zone.zoneId === b) continue;
        if (segmentIntersectsRect(center[a], center[b], rectOf(zone.zoneId))) {
          total += CARD_CROSSING_WEIGHT;
        }
      }
    }
    return total;
  };
  const overlaps = () => {
    for (let i = 0; i < zones.length; i += 1) {
      for (let j = i + 1; j < zones.length; j += 1) {
        const a = rectOf(zones[i].zoneId);
        const b = rectOf(zones[j].zoneId);
        if (a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y) {
          return true;
        }
      }
    }
    return false;
  };
  const localSearch = () => {
    let best = cost();
    let improved = true;
    let rounds = 0;
    while (improved && rounds < 8 && best > 0) {
      improved = false;
      rounds += 1;
      for (const ids of byFloor.values()) {
        for (let i = 0; i < ids.length; i += 1) {
          for (let j = i + 1; j < ids.length; j += 1) {
            const a = ids[i];
            const b = ids[j];
            const swapped = position[a];
            position[a] = position[b];
            position[b] = swapped;
            const trial = cost();
            if (trial < best && !overlaps()) {
              best = trial;
              improved = true;
            } else {
              const restore = position[a];
              position[a] = position[b];
              position[b] = restore;
            }
          }
        }
      }
    }
    return best;
  };

  const neighborsOf = (id) =>
    pairs.filter(([a, b]) => a === id || b === id).map(([a, b]) => (a === id ? b : a));
  const barycenterOrder = new Map();
  for (const [floor, ids] of byFloor) {
    barycenterOrder.set(floor, [...ids].sort((a, b) => {
      const bary = (id) => {
        const neighbors = neighborsOf(id);
        if (!neighbors.length) return originalCenterX[id];
        return neighbors.reduce((sum, n) => sum + originalCenterX[n], 0) / neighbors.length;
      };
      return bary(a) - bary(b) || originalPos[a].x - originalPos[b].x;
    }));
  }
  const reversedOrder = new Map(
    [...identityOrder].map(([floor, ids]) => [floor, [...ids].reverse()]),
  );

  let bestCost = Infinity;
  let bestPositions = null;
  for (const start of [identityOrder, barycenterOrder, reversedOrder]) {
    applyOrder(start);
    const result = localSearch();
    if (result < bestCost) {
      bestCost = result;
      bestPositions = {};
      for (const zone of zones) bestPositions[zone.zoneId] = { ...position[zone.zoneId] };
    }
  }
  return zones.map((zone) => ({ ...zone, position: { ...bestPositions[zone.zoneId] } }));
}

function spacedZoneSummaries(zones, scaleX = 1.22, scaleY = 1.18) {
  if (!zones.length) return zones;
  const originX = Math.min(...zones.map((zone) => Number(zone.position.x ?? 80)));
  const originY = Math.min(...zones.map((zone) => Number(zone.position.y ?? 80)));
  return zones.map((zone) => {
    const x = Number(zone.position.x ?? 80);
    const y = Number(zone.position.y ?? 80);
    return {
      ...zone,
      position: {
        ...zone.position,
        x: Math.round(originX + (x - originX) * scaleX),
        y: Math.round(originY + (y - originY) * scaleY),
      },
    };
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function dumpMapYaml(map) {
  return `${dumpValue(map, 0)}\n`;
}

function dumpValue(value, indent) {
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    return value
      .map((item) => `${" ".repeat(indent)}- ${dumpListItem(item, indent + 2)}`)
      .join("\n");
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value);
    if (entries.length === 0) return "{}";
    return entries
      .map(([key, item]) => {
        const prefix = `${" ".repeat(indent)}${key}:`;
        if (Array.isArray(item) && item.length === 0) {
          return `${prefix} []`;
        }
        if (item && typeof item === "object" && Object.entries(item).length === 0) {
          return `${prefix} {}`;
        }
        if (item && typeof item === "object") {
          return `${prefix}\n${dumpValue(item, indent + 2)}`;
        }
        return `${prefix} ${dumpScalar(item)}`;
      })
      .join("\n");
  }
  return dumpScalar(value);
}

function dumpListItem(value, indent) {
  if (value && typeof value === "object") return `\n${dumpValue(value, indent)}`;
  return dumpScalar(value);
}

function dumpScalar(value) {
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /^[a-zA-Z0-9_.:/ -]+$/.test(text) ? text : JSON.stringify(text);
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
      const [config, entityResponse, statusResponse] = await Promise.all([
        this._hass.callWS({ type: "predictive_controls/config" }),
        this._hass.callWS({ type: "predictive_controls/entities" }),
        this._hass.callWS({ type: "predictive_controls/status" }),
      ]);
      this._config = config;
      this._status = statusResponse;
      this._entities = normalizeEntityResponse(entityResponse);
      this._selectedNode = undefined;
      this._mapYamlDirty = false;
      this._tab = this._tab || "occupancy";
      this._statusUpdated = new Date();
      this.render();
    } catch (error) {
      this._error = error.message || String(error);
      this.render();
    }
  }

  connectedCallback() {
    this.render();
    this.startStatusRefresh();
  }

  disconnectedCallback() {
    if (this._statusTimer) clearInterval(this._statusTimer);
    this._statusTimer = undefined;
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
    this._tab = this._tab || "occupancy";

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
          <button class="${this._tab === "occupancy" ? "active" : ""}" data-tab="occupancy">Occupancy</button>
          <button class="${this._tab === "reliability" ? "active" : ""}" data-tab="reliability">Reliability</button>
          <button class="${this._tab === "activity" ? "active" : ""}" data-tab="activity">Activity</button>
          <button class="${this._tab === "map" ? "active" : ""}" data-tab="map">Map</button>
          <button class="${this._tab === "yaml" ? "active" : ""}" data-tab="yaml">YAML</button>
          <button class="${this._tab === "actions" ? "active" : ""}" data-tab="actions">Actions</button>
          <button class="${this._tab === "settings" ? "active" : ""}" data-tab="settings">Settings</button>
        </nav>
        ${this.renderActiveTab()}
      </div>
    `;
    this.bindEvents();
  }

  renderActiveTab() {
    if (this._tab === "occupancy") return this.renderOccupancy();
    if (this._tab === "reliability") return this.renderReliability();
    if (this._tab === "activity") return this.renderActivity();
    if (this._tab === "yaml") return this.renderYaml();
    if (this._tab === "actions") return this.renderActions();
    if (this._tab === "settings") return this.renderSettings();
    return this.renderMap();
  }

  renderOccupancy() {
    const zones = zoneSummaries(this._config.map);
    return `
      <main class="occupancy-layout">
        <section class="occupancy-toolbar">
          <div>
            <h2>Occupancy</h2>
            <p>${this._statusError ? escapeHtml(this._statusError) : `Updated ${this._statusUpdated ? this._statusUpdated.toLocaleTimeString() : "never"}`}</p>
          </div>
          <button data-action="refresh-status">Refresh</button>
        </section>
        ${this.renderOccupancyDiagnostics()}
        ${this.renderOccupancyGraph(zones)}
        ${this.renderLearnedTransitions()}
      </main>
    `;
  }

  renderOccupancyDiagnostics() {
    const diagnostics = this._status?.occupancy_diagnostics;
    const expected = Number(diagnostics?.expected_occupants || this._status?.expected_occupants || 0);
    if (!diagnostics) {
      return `
        <section class="track-section">
          <div class="section-head"><div class="section-title"><h3>Zone Beliefs</h3><small>Current filtered state</small></div></div>
          <p class="empty-state">No zone belief is available yet.</p>
        </section>
      `;
    }
    const beliefs = Object.entries(diagnostics.beliefs || {}).sort(([left], [right]) =>
      this.zoneLabel(left).localeCompare(this.zoneLabel(right)),
    );
    const active = Object.values(diagnostics.policy || {}).filter((state) => state?.active).length;
    const tokens = diagnostics.traversal_frontier || [];
    const warnings = diagnostics.health_warnings || [];
    return `
      <section class="track-section">
        <div class="section-head">
          <div class="section-title"><h3>Zone Beliefs</h3><small>Independent filtered probabilities</small></div>
          <strong>${beliefs.length} configured</strong>
        </div>
        <div class="track-list">
          ${beliefs.length ? beliefs.map(([zone, belief]) => `
            <article class="track-row">
              <div><strong>${escapeHtml(this.zoneLabel(zone))}</strong><span>${diagnostics.policy?.[zone]?.active ? "Active" : "Inactive"}</span></div>
              <div class="track-state"><strong>${escapeHtml(formatPercent(belief))}</strong><span>${escapeHtml(diagnostics.policy?.[zone]?.profile || "unprofiled")}</span></div>
            </article>
          `).join("") : `<p class="empty-state">No zone belief is available yet.</p>`}
        </div>
      </section>
      <section class="diagnostics-panel">
        <div class="diagnostics-strip">
          <span>Expected ${expected || "auto"}</span>
          <span>${active} active ${active === 1 ? "zone" : "zones"}</span>
          <span>${tokens.length} traversal ${tokens.length === 1 ? "token" : "tokens"}</span>
          <span>${warnings.length} health ${warnings.length === 1 ? "warning" : "warnings"}</span>
        </div>
      </section>
    `;
  }

  renderReliability() {
    const diagnostics = this._status?.occupancy_diagnostics || {};
    const episodes = diagnostics.episodes || [];
    const warnings = episodes.filter((item) => item.health_warning);
    return `
      <main class="reliability-layout">
        <section class="occupancy-toolbar">
          <div>
            <h2>Reliability</h2>
            <p>${this._statusError ? escapeHtml(this._statusError) : `Updated ${this._statusUpdated ? this._statusUpdated.toLocaleTimeString() : "never"}`}</p>
          </div>
          <button data-action="refresh-status">Refresh</button>
        </section>
        <section class="reliability-summary">
          <div class="reliability-metrics">
            <div><strong>${episodes.length}</strong><span>Physical nodes</span></div>
            <div><strong>${warnings.length}</strong><span>Health warnings</span></div>
            <div><strong>${Number(diagnostics.processing?.token_count || 0)}</strong><span>Traversal tokens</span></div>
          </div>
          <p>Finite assertion trust makes stuck or unavailable physical sensors directly observable.</p>
        </section>
        <section class="reliability-section">
          <div class="section-head">
            <h3>Sensor Health</h3>
            <small>${warnings.length} ${warnings.length === 1 ? "warning" : "warnings"}</small>
          </div>
          <div class="reliability-list">
            ${warnings.length ? warnings.map((item) => `
              <article class="reliability-row">
                <div class="reliability-row-head"><strong>${escapeHtml(item.node_id)}</strong><span>${escapeHtml(this.zoneLabel(item.zone))}</span></div>
                <p>${escapeHtml(labelFromValue(item.status))} &middot; ${escapeHtml(item.profile)}</p>
                <small>Last event ${escapeHtml(formatTimestamp(item.last_event_at))}</small>
              </article>
            `).join("") : `<p class="empty-state">No sensor health warnings.</p>`}
          </div>
        </section>
      </main>
    `;
  }

  renderActivity() {
    const model = policyModel(this._status);
    const policy = model?.policy || {};
    const audit = Array.isArray(model?.policy_audit) ? model.policy_audit : [];
    const activeCount = Object.values(policy).filter((state) => state?.active).length;
    this._activityFilter = this._activityFilter || "edges";
    this._auditLimit = this._auditLimit || 50;
    return `
      <main class="activity-layout">
        <section class="occupancy-toolbar">
          <div>
            <h2>Activity</h2>
            <p>${this._statusError ? escapeHtml(this._statusError) : `Updated ${this._statusUpdated ? this._statusUpdated.toLocaleTimeString() : "never"}`}</p>
          </div>
          <button data-action="refresh-status">Refresh</button>
        </section>
        ${model ? `
          ${this.renderPolicyOwnership(policy, model, activeCount)}
          ${this.renderAuditRetention(audit, activeCount)}
          ${this.renderPolicyAudit(audit)}
        ` : `
          <section class="activity-empty">
            <h3>Waiting for zone-belief activity</h3>
            <p>Policy activity will appear after the first observation.</p>
          </section>
        `}
      </main>
    `;
  }

  renderPolicyOwnership(policy, model, activeCount) {
    const entries = Object.entries(policy).sort(([left], [right]) =>
      this.zoneLabel(left).localeCompare(this.zoneLabel(right)),
    );
    const beliefs = model?.beliefs || {};
    return `
      <section class="ownership-section">
        <div class="section-head">
          <div class="section-title">
            <h3>Current Ownership</h3>
            <small>Hysteretic zone-belief projection</small>
          </div>
          <strong>${activeCount} active ${activeCount === 1 ? "zone" : "zones"}</strong>
        </div>
        <div class="ownership-grid">
          ${entries.length ? entries.map(([zone, state]) => `
            <article class="ownership-row ${state.active ? "is-active" : ""}">
              <div class="ownership-name">
                <span class="state-indicator" aria-hidden="true"></span>
                <div><strong>${escapeHtml(this.zoneLabel(zone))}</strong><small>${state.active ? "Active" : "Inactive"}</small></div>
              </div>
              <p>${state.pending_release_since ? `Release dwell since ${escapeHtml(formatTimestamp(state.pending_release_since))}` : "No release dwell pending"}</p>
              <div class="ownership-probabilities">
                <span>Belief ${escapeHtml(formatPercent(beliefs[zone]))}</span>
                <span>${escapeHtml(state.profile || "unprofiled")}</span>
              </div>
            </article>
          `).join("") : `<p class="empty-state">No zone ownership state is available yet.</p>`}
        </div>
      </section>
    `;
  }

  renderAuditRetention(audit, activeCount) {
    const oldest = audit.length ? audit[0].event_at : null;
    const newest = audit.length ? audit[audit.length - 1].event_at : null;
    return `
      <section class="activity-metrics">
        <div><strong>${activeCount}</strong><span>Active now</span></div>
        <div><strong>${audit.length.toLocaleString()}</strong><span>Retained decisions</span></div>
        <p>Bounded audit &middot; ${escapeHtml(formatTimestamp(oldest))} to ${escapeHtml(formatTimestamp(newest))}</p>
      </section>
    `;
  }

  renderPolicyAudit(audit) {
    const filter = this._activityFilter;
    const ordered = [...audit].sort(
      (left, right) => new Date(right.event_at || 0) - new Date(left.event_at || 0),
    );
    const filtered = filter === "all"
      ? ordered
      : ordered.filter((entry) => auditKind(entry) === filter);
    const visible = filtered.slice(0, this._auditLimit);
    const labels = {
      edges: "Production edges",
      rejected: "Rejected decisions",
      observations: "Policy observations",
      all: "All retained",
    };
    return `
      <section class="audit-section">
        <div class="audit-heading">
          <div class="section-title"><h3>Decision Timeline</h3><small>Newest first</small></div>
          <div class="activity-filters" role="group" aria-label="Activity filter">
            ${Object.entries(labels).map(([value, label]) => `<button class="${filter === value ? "active" : ""}" data-activity-filter="${value}" aria-pressed="${filter === value ? "true" : "false"}">${label}</button>`).join("")}
          </div>
        </div>
        <div class="audit-list">
          ${visible.length ? visible.map((entry) => this.renderAuditEntry(entry)).join("") : `<p class="empty-state">No ${escapeHtml(labels[filter].toLowerCase())} in retained activity.</p>`}
        </div>
        ${filtered.length > visible.length ? `<button class="show-more" data-action="show-more-audit">Show 50 more</button>` : ""}
      </section>
    `;
  }

  renderAuditEntry(entry) {
    const [priorActive, resultingActive] = auditTransition(entry);
    const kind = auditKind(entry);
    const title = kind === "edges"
      ? (resultingActive ? "Turned on" : "Turned off")
      : kind === "rejected"
        ? "Decision rejected"
        : "Policy observation";
    const evidenceCount = Array.isArray(entry.evidence_ids) ? entry.evidence_ids.length : 0;
    return `
      <article class="audit-row kind-${kind}">
        <div class="audit-marker" aria-hidden="true"></div>
        <div class="audit-content">
          <div class="audit-row-head">
            <div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(this.zoneLabel(entry.zone))}</span></div>
            <time>${escapeHtml(formatTimestamp(entry.event_at))}</time>
          </div>
          <p>${escapeHtml(decisionExplanation(entry))}</p>
          <div class="audit-meta">
            <span class="context-badge lightweight">Zone-local decision</span>
            ${kind === "edges" ? `<span>${priorActive ? "On" : "Off"} to ${resultingActive ? "On" : "Off"}</span>` : ""}
            ${evidenceCount ? `<span>${evidenceCount} evidence ${evidenceCount === 1 ? "item" : "items"}</span>` : ""}
          </div>
        </div>
      </article>
    `;
  }

  zoneLabel(zone) {
    return this._config?.map?.zones?.[zone]?.label || titleFromId(zone || "whole home");
  }

  renderRejectedCapture(item) {
    const reasons = Object.entries(item.reason_counts || {})
      .map(([reason, count]) => `${labelFromValue(reason)} (${count})`)
      .join(", ");
    return `
      <article class="reliability-row">
        <div class="reliability-row-head">
          <strong>${escapeHtml(item.entity_id)}</strong>
          <span>${Number(item.capture_count || 0)} rejected</span>
        </div>
        <p>${escapeHtml(labelFromValue(item.zone))} &middot; ${escapeHtml(formatOccupiedPeak(item.max_occupied_marginal))} &middot; Last ${escapeHtml(formatTimestamp(item.last_capture_at))}</p>
        <small>${escapeHtml(reasons || "Policy rejection")}</small>
      </article>
    `;
  }

  renderLowConfidenceFlap(item) {
    return `
      <article class="reliability-row">
        <div class="reliability-row-head">
          <strong>${escapeHtml(item.entity_id)}</strong>
          <span>${Number(item.pulse_count || 0)} pulses</span>
        </div>
        <p>${escapeHtml(labelFromValue(item.zone))} &middot; ${escapeHtml(formatOccupiedPeak(item.max_occupied_marginal))} &middot; Shortest ${Number(item.shortest_pulse_seconds || 0).toFixed(1)}s</p>
        <small>Last ${escapeHtml(formatTimestamp(item.last_flap_at))}</small>
      </article>
    `;
  }

  renderLearnedTransitions() {
    const rows = learnedTransitionRows(this._config.map, this._status);
    return `
      <section class="transition-section">
        <div class="section-head">
          <h3>Learned Transitions</h3>
          <small>${rows.length} active ${rows.length === 1 ? "edge" : "edges"}</small>
        </div>
        ${rows.length ? `
          <table class="transition-table">
            <thead><tr><th>From</th><th>To</th><th>Count</th></tr></thead>
            <tbody>
              ${rows.map((row) => `
                <tr>
                  <td><strong>${escapeHtml(row.sourceLabel)}</strong><small>${escapeHtml(row.sourceId)}</small></td>
                  <td><strong>${escapeHtml(row.targetLabel)}</strong><small>${escapeHtml(row.targetId)}</small></td>
                  <td>${row.count.toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        ` : `<p>No learned transitions yet.</p>`}
      </section>
    `;
  }

  renderOccupancyGraph(zones) {
    const floorOrder = Array.isArray(this._config.map?.floors) ? this._config.map.floors : [];
    const layoutZones = minimizeCrossings(
      stackFloorsByBand(separateFloorRows(spacedZoneSummaries(zones)), floorOrder),
      this.nodes,
    );
    const graphLabelGutter = 64;
    const minX = Math.min(...layoutZones.map((zone) => Number(zone.position.x ?? 80))) - graphLabelGutter;
    const minY = Math.min(...layoutZones.map((zone) => Number(zone.position.y ?? 80)));
    const maxX = Math.max(...layoutZones.map((zone) => Number(zone.position.x ?? 80) + Number(zone.size.width ?? 210)));
    const maxY = Math.max(...layoutZones.map((zone) => Number(zone.position.y ?? 80) + estimateCardHeight(zone)));
    const width = Math.max(900, maxX - minX + 48, Number(this.clientWidth || 0) - 48);
    const bandBottom = floorBands(layoutZones).reduce((lowest, band) => {
      const bandTop = Number(band.top) - minY + 12;
      const bandHeight = Math.max(120, Number(band.bottom) - Number(band.top) + 72);
      return Math.max(lowest, bandTop + bandHeight);
    }, 0);
    const height = Math.max(520, maxY - minY + 48, bandBottom + 24);
    return `
      <section class="floor-section occupancy-graph-section">
        <h3>Zone Graph</h3>
        <div class="occupancy-board occupancy-graph" style="height:${height}px;width:${width}px">
          ${this.renderFloorBands(layoutZones, minY, width)}
          <svg class="zone-edges" viewBox="0 0 ${width} ${height}">${this.renderZoneEdges(layoutZones, minX, minY)}</svg>
          ${layoutZones.map((zone) => this.renderZoneCard(zone, minX, minY)).join("")}
        </div>
      </section>
    `;
  }

  renderFloorBands(zones, minY, width) {
    return floorBands(zones).map((band) => {
      const top = Number(band.top) - minY + 12;
      const height = Math.max(120, Number(band.bottom) - Number(band.top) + 72);
      return `
        <div class="floor-band" style="top:${top}px;height:${height}px;width:${width - 24}px">
          <span>${escapeHtml(titleFromId(band.floor))}</span>
        </div>
      `;
    }).join("");
  }

  renderZoneEdges(zones, minX, minY) {
    const zonesByNode = new Map();
    for (const zone of zones) {
      for (const nodeId of zone.nodeIds) zonesByNode.set(nodeId, zone);
    }
    const lines = [];
    const seen = new Set();
    for (const zone of zones) {
      for (const nodeId of zone.nodeIds) {
        const node = this.nodes[nodeId];
        for (const targetId of node?.adjacent || []) {
          const target = zonesByNode.get(targetId);
          if (!target || target.zoneId === zone.zoneId) continue;
          const edgeId = [zone.zoneId, target.zoneId].sort().join("->");
          if (seen.has(edgeId)) continue;
          seen.add(edgeId);
          lines.push(`<line data-edge="${escapeHtml(edgeId)}" x1="${Number(zone.position.x ?? 80) - minX + Number(zone.size.width ?? 210) / 2 + 24}" y1="${Number(zone.position.y ?? 80) - minY + estimateCardHeight(zone) / 2 + 24}" x2="${Number(target.position.x ?? 80) - minX + Number(target.size.width ?? 210) / 2 + 24}" y2="${Number(target.position.y ?? 80) - minY + estimateCardHeight(target) / 2 + 24}" />`);
        }
      }
    }
    return lines.join("");
  }

  renderZoneCard(zone, minX, minY) {
    const state = this._status?.zone_states?.[zone.zoneId] || { confidence: 0, status: "rejected", reason: "no evidence" };
    const confidence = Math.round(Number(state.confidence || 0) * 100);
    const left = Number(zone.position.x ?? 80) - minX + 24;
    const top = Number(zone.position.y ?? 80) - minY + 24;
    const width = Number(zone.size.width ?? 210);
    const height = Number(zone.size.height ?? 112);
    return `
      <article class="zone-card status-${state.status}" style="left:${left}px;top:${top}px;width:${width}px;min-height:${height}px" title="${escapeHtml(state.reason || "no evidence")}">
        <div class="zone-card-head">
          <strong>${escapeHtml(zone.label)}</strong>
          <span>${confidence}%</span>
        </div>
        <div class="confidence-bar"><span style="width:${confidence}%"></span></div>
        <small>${escapeHtml(state.status || "rejected")} · ${escapeHtml(labelFromValue(state.occupancy_behavior || zone.occupancyBehavior))}</small>
        <small>${escapeHtml(labelFromValue(zone.role))}</small>
        <small>${zone.nodeIds.length} ${zone.nodeIds.length === 1 ? "sensor" : "sensors"}${state.last_node_id ? ` · ${escapeHtml(state.last_node_id)}` : ""}</small>
      </article>
    `;
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
    const behavior = this.nodeOccupancyBehavior(node);
    return `
      <button class="node ${this._selectedNode === nodeId ? "selected" : ""}" draggable="true" data-node="${nodeId}" style="left:${x}px;top:${y}px">
        <strong>${node.label || nodeId}</strong>
        <span>${this.nodeEntitySummary(node, nodeId)}</span>
        <small>${escapeHtml(labelFromValue(behavior))} · ${escapeHtml(labelFromValue(node.role || "room_occupancy"))}</small>
      </button>
    `;
  }

  nodeOccupancyBehavior(node) {
    return node.occupancy_behavior
      || this._config?.map?.zones?.[node.zone]?.occupancy_behavior
      || defaultBehaviorForRole(node.role);
  }

  nodeEntitySummary(node, fallback) {
    const entities = Object.values(node.entities || {});
    if (entities.length === 0) return fallback;
    if (entities.length === 1) return entities[0];
    return `${entities[0]} + ${entities.length - 1} more`;
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
      <label>Role<input data-field="role" value="${node.role || "room_occupancy"}" /></label>
      <label>Occupancy behavior<input data-field="occupancy_behavior" value="${this.nodeOccupancyBehavior(node)}" /></label>
      <label>Entities<textarea class="small" data-field="entities">${escapeHtml(this.formatEntities(node.entities || {}))}</textarea></label>
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

  renderYaml() {
    if (!this._mapYamlDirty) this.syncMapYamlFromMap();
    return `
      <main class="single-panel">
        <h2>Map YAML</h2>
        <textarea data-map-yaml>${escapeHtml(this._config.map_yaml || "")}</textarea>
      </main>
    `;
  }

  renderSettings() {
    return `
      <main class="single-panel settings">
        <label>Transition window seconds<input data-setting="transition_window_seconds" type="number" min="1" value="${this._config.transition_window_seconds}" /></label>
        <label>Prediction threshold<input data-setting="prediction_threshold" type="number" min="0" max="1" step="0.01" value="${this._config.prediction_threshold}" /></label>
        <label>Expected occupants<input data-setting="expected_occupants" type="number" min="0" max="2" step="1" value="${this._config.expected_occupants || 0}" /></label>
        <label>Expected occupants entity<input data-setting="expected_occupants_entity" type="text" value="${escapeHtml(this._config.expected_occupants_entity || "")}" /></label>
        <section class="maintenance-section">
          <h3>Entities</h3>
          <button data-action="cleanup-entities">Clean Stale Entities</button>
          ${this._cleanupMessage ? `<p>${escapeHtml(this._cleanupMessage)}</p>` : ""}
        </section>
      </main>
    `;
  }

  bindEvents() {
    this.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => {
      this._tab = button.dataset.tab;
      if (["occupancy", "reliability", "activity"].includes(this._tab)) this.refreshStatus();
      this.render();
    }));
    this.querySelector('[data-action="reload"]')?.addEventListener("click", () => this.loadData());
    this.querySelector('[data-action="refresh-status"]')?.addEventListener("click", () => this.refreshStatus());
    this.querySelectorAll("[data-activity-filter]").forEach((button) => button.addEventListener("click", () => {
      this._activityFilter = button.dataset.activityFilter;
      this._auditLimit = 50;
      this.render();
    }));
    this.querySelector('[data-action="show-more-audit"]')?.addEventListener("click", () => {
      this._auditLimit += 50;
      this.render();
    });
    this.querySelector('[data-action="save"]')?.addEventListener("click", () => this.save());
    this.querySelector('[data-action="add-empty"]')?.addEventListener("click", () => this.addNode());
    this.querySelector('[data-action="cleanup-entities"]')?.addEventListener("click", () => this.cleanupEntities());
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
    this.querySelector("[data-map-yaml]")?.addEventListener("input", (event) => {
      this._config.map_yaml = event.target.value;
      this._mapYamlDirty = true;
    });
    this.querySelectorAll("[data-setting]").forEach((input) => input.addEventListener("input", () => {
      this._config[input.dataset.setting] = input.type === "number" ? Number(input.value) : input.value;
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
    this.markMapChanged();
    this.render();
  }

  addNode() {
    const { nodeId, node } = createEmptyNode(this.nodes);
    this.nodes[nodeId] = node;
    this._selectedNode = nodeId;
    this.markMapChanged();
    this.render();
  }

  moveNode(nodeId, x, y) {
    moveNode(this.nodes, nodeId, x, y);
    this.markMapChanged();
    this.render();
  }

  updateSelectedField(input) {
    const node = this.nodes[this._selectedNode];
    if (!node) return;
    if (input.dataset.field === "node_id") {
      this._selectedNode = renameNode(this.nodes, this._selectedNode, input.value);
    } else if (input.dataset.field === "entities") {
      node.entities = this.parseEntities(input.value);
    } else if (input.dataset.field === "initial_weight") {
      node.initial_weight = Number(input.value);
    } else {
      node[input.dataset.field] = input.value;
    }
    this.markMapChanged();
    this.render();
  }

  addEdge(source, target) {
    addBidirectionalEdge(this.nodes, source, target);
    this.markMapChanged();
  }

  removeEdge(source, target) {
    if (!source || !target) return;
    removeBidirectionalEdge(this.nodes, source, target);
    this.markMapChanged();
    this.render();
  }

  deleteSelected() {
    if (!this._selectedNode) return;
    deleteNode(this.nodes, this._selectedNode);
    this._selectedNode = undefined;
    this.markMapChanged();
    this.render();
  }

  formatEntities(entities) {
    return Object.entries(entities)
      .map(([key, value]) => `${key}: ${value}`)
      .join("\n");
  }

  parseEntities(value) {
    const entities = {};
    for (const rawLine of value.split("\n")) {
      const line = rawLine.trim();
      if (!line) continue;
      const separator = line.indexOf(":");
      if (separator === -1) {
        entities.motion = line;
        continue;
      }
      const key = line.slice(0, separator).trim();
      const entityId = line.slice(separator + 1).trim();
      if (key && entityId) entities[key] = entityId;
    }
    return entities;
  }

  markMapChanged() {
    this._mapYamlDirty = false;
    this.syncMapYamlFromMap();
  }

  syncMapYamlFromMap() {
    this._config.map_yaml = dumpMapYaml(this._config.map);
  }

  filterEntities(value) {
    this.querySelectorAll("[data-entity]").forEach((item) => {
      const entity = this._entities.find(
        (candidate) => candidate.entity_id === item.dataset.entity,
      );
      item.hidden = entity ? !entityMatchesFilter(entity, value) : true;
    });
  }

  startStatusRefresh() {
    if (this._statusTimer) return;
    this._statusTimer = setInterval(() => this.refreshStatus(), 5000);
  }

  async refreshStatus() {
    if (!this._hass || !this._config) return;
    try {
      this._status = await this._hass.callWS({
        type: "predictive_controls/status",
        entry_id: this._config.entry_id,
      });
      this._statusError = undefined;
      this._statusUpdated = new Date();
      if (["occupancy", "reliability", "activity"].includes(this._tab)) this.render();
    } catch (error) {
      this._statusError = error.message || String(error);
      if (["occupancy", "reliability", "activity"].includes(this._tab)) this.render();
    }
  }

  async save() {
    try {
      if (!this._mapYamlDirty) this.syncMapYamlFromMap();
      this._config = await this._hass.callWS({
        type: "predictive_controls/save_config",
        entry_id: this._config.entry_id,
        map: this._config.map,
        map_yaml: this._config.map_yaml,
        map_yaml_dirty: this._mapYamlDirty === true,
        actions_yaml: this._config.actions_yaml,
        transition_window_seconds: Number(this._config.transition_window_seconds),
        prediction_threshold: Number(this._config.prediction_threshold),
        expected_occupants: Number(this._config.expected_occupants || 0),
        expected_occupants_entity: this._config.expected_occupants_entity || "",
      });
      this._mapYamlDirty = false;
      this.render();
    } catch (error) {
      alert(error.message || String(error));
    }
  }

  async cleanupEntities() {
    try {
      const preview = await this._hass.callWS({
        type: "predictive_controls/cleanup_entities",
        entry_id: this._config.entry_id,
        dry_run: true,
      });
      if (!preview.stale_count) {
        this._cleanupMessage = "No stale entities found.";
        this.render();
        return;
      }
      const confirmed = confirm(`Remove ${preview.stale_count} stale Predictive Controls entities?`);
      if (!confirmed) return;
      const result = await this._hass.callWS({
        type: "predictive_controls/cleanup_entities",
        entry_id: this._config.entry_id,
        dry_run: false,
      });
      this._cleanupMessage = `Removed ${result.removed_count} stale entities.`;
      this.render();
    } catch (error) {
      alert(error.message || String(error));
    }
  }

  styles() {
    return `
      predictive-controls-panel { display:block; width:100%; min-width:0; }
      .pc-shell { padding: 24px; color: var(--primary-text-color); }
      header { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:16px; }
      h1 { margin:0; font-size:28px; }
      h2 { margin:0 0 12px; font-size:18px; }
      h3 { margin:18px 0 8px; font-size:14px; }
      p { color: var(--secondary-text-color); }
      button { border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); border-radius:6px; padding:8px 12px; cursor:pointer; }
      button.primary, button.active { background:var(--primary-color); color:var(--text-primary-color); border-color:var(--primary-color); }
      button:disabled { opacity:.5; cursor:not-allowed; }
      nav { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
      .pc-actions { display:flex; gap:8px; }
      .map-layout { display:grid; grid-template-columns:280px minmax(420px, 1fr) 280px; gap:16px; min-height:640px; }
      .entity-list, .board-wrap, .inspector, .single-panel { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:8px; padding:16px; }
      .entity-list input, label input, textarea { width:100%; box-sizing:border-box; margin-top:6px; padding:8px; color:var(--primary-text-color); background:var(--secondary-background-color); border:1px solid var(--divider-color); border-radius:6px; }
      .entities { margin-top:12px; display:grid; gap:8px; max-height:560px; overflow:auto; }
      .entity { border:1px solid var(--divider-color); border-radius:6px; padding:10px; cursor:grab; }
      .entity span, .entity small, .node span, .node small { display:block; color:var(--secondary-text-color); font-size:12px; overflow:hidden; text-overflow:ellipsis; }
      .toolbar { display:flex; gap:8px; margin-bottom:12px; }
      .board { position:relative; min-height:580px; overflow:auto; background:var(--secondary-background-color); border:1px dashed var(--divider-color); border-radius:8px; }
      .edges { position:absolute; inset:0; width:2000px; height:1200px; pointer-events:none; }
      .edges line { stroke:var(--primary-color); stroke-width:3; opacity:.75; }
      .node { position:absolute; width:180px; min-height:56px; text-align:left; cursor:grab; box-shadow:var(--ha-card-box-shadow, none); }
      .node.selected { outline:3px solid var(--primary-color); }
      .inspector label, .settings label { display:block; margin-bottom:12px; }
      .maintenance-section { margin-top:20px; padding-top:16px; border-top:1px solid var(--divider-color); }
      .chips { display:flex; flex-wrap:wrap; gap:8px; }
      textarea { min-height:520px; font-family:monospace; }
      textarea.small { min-height:96px; }
      .occupancy-layout, .reliability-layout, .activity-layout { display:grid; grid-template-columns:minmax(0, 1fr); gap:16px; }
      .occupancy-toolbar, .track-section, .diagnostics-panel, .floor-section, .transition-section, .reliability-summary, .reliability-section, .ownership-section, .activity-metrics, .audit-section, .activity-empty { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:8px; padding:16px; }
      .occupancy-toolbar { display:flex; align-items:center; justify-content:space-between; gap:16px; }
      .occupancy-toolbar p { margin:4px 0 0; }
      .section-title h3 { margin:0; }
      .section-title small { display:block; margin-top:4px; }
      .track-list, .reliability-list { display:grid; grid-template-columns:minmax(0, 1fr); margin-top:12px; }
      .track-row, .reliability-row { display:grid; gap:6px; padding:12px 0; border-top:1px solid var(--divider-color); }
      .track-row:first-child, .reliability-row:first-child { border-top:0; }
      .track-row { grid-template-columns:minmax(140px, 1fr) auto minmax(200px, 2fr); align-items:center; }
      .reliability-row { grid-template-columns:minmax(0, 1fr); }
      .track-row div { display:grid; gap:2px; }
      .track-row span, .track-row small { color:var(--secondary-text-color); overflow:hidden; text-overflow:ellipsis; }
      .track-state { text-align:right; }
      .empty-state { margin:12px 0 0; }
      .diagnostics-strip { display:flex; flex-wrap:wrap; gap:8px; }
      .diagnostics-strip span { border:1px solid var(--divider-color); border-radius:999px; padding:4px 8px; }
      .diagnostics-list { display:grid; gap:8px; margin-top:12px; }
      .diagnostics-list p { margin:0; display:grid; gap:2px; }
      .diagnostics-list span { color:var(--secondary-text-color); }
      .section-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
      .section-head small { color:var(--secondary-text-color); }
      .reliability-metrics { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:1px; background:var(--divider-color); }
      .reliability-metrics div { display:grid; gap:4px; padding:14px; background:var(--card-background-color); }
      .reliability-metrics strong { font-size:24px; }
      .reliability-metrics span, .reliability-summary p, .reliability-row p, .reliability-row small { color:var(--secondary-text-color); }
      .reliability-summary p, .reliability-row p { margin:10px 0 0; }
      .reliability-row-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
      .reliability-row-head strong { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      .reliability-row-head span { border:1px solid var(--warning-color, #f2a900); border-radius:999px; padding:3px 8px; white-space:nowrap; }
      .ownership-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:1px; margin-top:14px; background:var(--divider-color); }
      .ownership-row { min-width:0; padding:14px; background:var(--card-background-color); border-left:4px solid var(--disabled-text-color); }
      .ownership-row.is-active { border-left-color:var(--success-color, #43a047); }
      .ownership-name { display:flex; align-items:center; gap:9px; }
      .ownership-name div { min-width:0; display:grid; gap:2px; }
      .ownership-name strong, .ownership-name small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      .ownership-name small, .ownership-row p, .ownership-probabilities { color:var(--secondary-text-color); }
      .state-indicator { width:9px; height:9px; flex:0 0 auto; border-radius:50%; background:var(--disabled-text-color); }
      .is-active .state-indicator { background:var(--success-color, #43a047); box-shadow:0 0 0 4px color-mix(in srgb, var(--success-color, #43a047) 18%, transparent); }
      .ownership-row p { min-height:2.7em; margin:10px 0; line-height:1.35; }
      .ownership-probabilities { display:flex; flex-wrap:wrap; gap:6px 12px; font-size:12px; }
      .activity-metrics { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:1px; background:var(--divider-color); }
      .activity-metrics div { display:grid; gap:4px; padding:14px; background:var(--card-background-color); }
      .activity-metrics strong { font-size:22px; }
      .activity-metrics span, .activity-metrics p { color:var(--secondary-text-color); }
      .activity-metrics p { grid-column:1 / -1; margin:0; padding:12px 14px; background:var(--card-background-color); }
      .audit-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
      .activity-filters { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:6px; }
      .activity-filters button { padding:6px 9px; }
      .audit-list { margin-top:12px; }
      .audit-row { display:grid; grid-template-columns:14px minmax(0, 1fr); gap:12px; padding:14px 0; border-top:1px solid var(--divider-color); }
      .audit-row:first-child { border-top:0; }
      .audit-marker { width:10px; height:10px; margin-top:5px; border-radius:50%; background:var(--disabled-text-color); }
      .kind-edges .audit-marker { background:var(--primary-color); }
      .kind-rejected .audit-marker { background:var(--warning-color, #f2a900); }
      .kind-observations .audit-marker { background:var(--info-color, #4797ff); }
      .audit-content { min-width:0; }
      .audit-row-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
      .audit-row-head div { min-width:0; display:flex; flex-wrap:wrap; gap:5px 10px; }
      .audit-row-head span, .audit-row-head time, .audit-content p, .audit-meta { color:var(--secondary-text-color); }
      .audit-row-head time { flex:0 0 auto; font-size:12px; }
      .audit-content p { margin:7px 0 9px; }
      .audit-meta { display:flex; flex-wrap:wrap; gap:6px 12px; font-size:12px; }
      .context-badge { border:1px solid var(--divider-color); border-radius:999px; padding:2px 7px; }
      .show-more { width:100%; margin-top:10px; }
      .activity-empty h3 { margin-top:0; }
      .floor-section, .transition-section { overflow:auto; }
      .occupancy-graph-section h3 { margin-top:0; }
      .occupancy-board { position:relative; overflow:auto; background:var(--secondary-background-color); border:1px solid var(--divider-color); border-radius:8px; }
      .occupancy-graph { background:var(--secondary-background-color); }
      .floor-band { position:absolute; left:12px; box-sizing:border-box; border:1px solid color-mix(in srgb, var(--divider-color) 78%, transparent); border-radius:8px; background:color-mix(in srgb, var(--card-background-color) 10%, transparent); pointer-events:none; }
      .floor-band span { position:absolute; left:12px; top:10px; color:var(--primary-text-color); font-size:13px; font-weight:700; }
      .zone-edges { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }
      .zone-edges line { stroke:var(--primary-color); stroke-width:3; opacity:.72; }
      .zone-card { position:absolute; box-sizing:border-box; border:1px solid var(--divider-color); border-left-width:6px; border-radius:8px; padding:12px; background:var(--card-background-color); box-shadow:var(--ha-card-box-shadow, none); z-index:1; }
      .zone-card-head { display:flex; align-items:center; justify-content:space-between; gap:8px; }
      .zone-card-head strong, .zone-card small { overflow:hidden; text-overflow:ellipsis; }
      .zone-card small { display:block; margin-top:6px; color:var(--secondary-text-color); }
      .confidence-bar { height:8px; margin-top:10px; border-radius:999px; background:var(--divider-color); overflow:hidden; }
      .confidence-bar span { display:block; height:100%; background:var(--primary-color); }
      .status-rejected { border-left-color:var(--disabled-text-color); }
      .status-suspect { border-left-color:var(--warning-color, #f2a900); }
      .status-possible { border-left-color:var(--info-color, #4797ff); }
      .status-probable { border-left-color:var(--success-color, #43a047); }
      .status-confirmed { border-left-color:var(--primary-color); }
      .transition-table { width:100%; border-collapse:collapse; margin-top:12px; }
      .transition-table th, .transition-table td { text-align:left; border-top:1px solid var(--divider-color); padding:10px 8px; vertical-align:top; }
      .transition-table th { color:var(--secondary-text-color); font-weight:600; }
      .transition-table small { display:block; color:var(--secondary-text-color); margin-top:2px; }
      @media (max-width: 1000px) { .map-layout { grid-template-columns:1fr; } }
      @media (max-width: 700px) {
        .pc-shell { padding:12px; }
        header, .occupancy-toolbar, .audit-heading { align-items:flex-start; flex-direction:column; }
        .track-row { grid-template-columns:1fr auto; }
        .track-row small { grid-column:1 / -1; }
        .reliability-metrics { grid-template-columns:1fr; }
        .activity-metrics { grid-template-columns:1fr; }
        .activity-metrics p { grid-column:1; }
        .activity-filters { justify-content:flex-start; }
        .audit-row-head { display:grid; }
      }
    `;
  }
}

if (!customElements.get("predictive-controls-panel")) {
  customElements.define("predictive-controls-panel", PredictiveControlsPanel);
}
