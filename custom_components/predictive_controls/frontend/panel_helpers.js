// Generated from frontend/ by scripts/build_frontend.mjs. Version 0.2.6. DO NOT EDIT.

// frontend/formatting.ts
function titleFromId(value) {
  return (value || "unknown").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// frontend/decoders.ts
function record(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("Expected an object");
  return Object.fromEntries(Object.entries(value));
}
function text(value) {
  if (typeof value !== "string") throw new Error("Expected a string");
  return value;
}
function identity(value) {
  const result = text(value);
  if (!result) throw new Error("Expected a nonempty identity");
  return result;
}
function nullableText(value) {
  return value === null ? null : text(value);
}
function list(value, decode) {
  if (!Array.isArray(value)) throw new Error("Expected an array");
  return value.map((item) => decode(item));
}
function optional(source, key, decode, assign) {
  if (Object.hasOwn(source, key)) assign(decode(source[key]));
}
function normalizeEntityResponse(value) {
  const r = record(value);
  return list(r.entities, (v) => {
    const row = record(v);
    const e = { entity_id: identity(row.entity_id) };
    optional(row, "name", text, (x) => e.name = x);
    optional(row, "state", text, (x) => e.state = x);
    optional(row, "device_class", nullableText, (x) => e.device_class = x);
    return e;
  }).sort((a, b) => a.entity_id.localeCompare(b.entity_id));
}

// frontend/map-helpers.ts
function sanitizeNodeId(value) {
  return (value || "node").replace(/^.*\./, "").replace(/[^a-zA-Z0-9_]/g, "_").replace(/^_+|_+$/g, "") || "node";
}
function uniqueNodeId(nodes, base) {
  const sanitized = sanitizeNodeId(base);
  let candidate = sanitized;
  let index = 2;
  while (Object.hasOwn(nodes, candidate)) candidate = `${sanitized}_${index++}`;
  return candidate;
}
function coordinate(value) {
  if (!Number.isFinite(value)) throw new Error("Coordinate must be finite");
  return Math.round(Math.max(0, value));
}
function defaults() {
  return { entities: {}, adjacent: [], role: "room_occupancy", occupancy_behavior: "sustained", reliability: 1, route_prior_weight: 1, position: { x: 80, y: 80 } };
}
function createNodeForEntity(nodes, entity, x, y) {
  return { nodeId: uniqueNodeId(nodes, entity.entity_id), node: { ...defaults(), label: entity.name || entity.entity_id, entities: { motion: entity.entity_id }, position: { x: coordinate(x), y: coordinate(y) } } };
}
function createEmptyNode(nodes) {
  const nodeId = uniqueNodeId(nodes, "node");
  return { nodeId, node: { ...defaults(), label: nodeId } };
}
function moveNode(nodes, nodeId, x, y) {
  const node = Object.hasOwn(nodes, nodeId) ? nodes[nodeId] : void 0;
  if (node) node.position = { ...node.position, x: coordinate(x), y: coordinate(y) };
  return nodes;
}
function addBidirectionalEdge(nodes, source, target) {
  const a = nodes[source];
  const b = nodes[target];
  if (!Object.hasOwn(nodes, source) || !Object.hasOwn(nodes, target) || !a || !b || source === target) return nodes;
  a.adjacent = [.../* @__PURE__ */ new Set([...a.adjacent || [], target])];
  b.adjacent = [.../* @__PURE__ */ new Set([...b.adjacent || [], source])];
  return nodes;
}
function removeBidirectionalEdge(nodes, source, target) {
  const a = nodes[source];
  const b = nodes[target];
  if (!Object.hasOwn(nodes, source) || !Object.hasOwn(nodes, target) || !a || !b) return nodes;
  a.adjacent = (a.adjacent || []).filter((id) => id !== target);
  b.adjacent = (b.adjacent || []).filter((id) => id !== source);
  return nodes;
}
function renameNode(nodes, oldId, newId) {
  const id = sanitizeNodeId(newId);
  const node = nodes[oldId];
  if (!Object.hasOwn(nodes, oldId) || !node || id === oldId || Object.hasOwn(nodes, id)) return oldId;
  Object.defineProperty(nodes, id, { value: node, enumerable: true, writable: true, configurable: true });
  delete nodes[oldId];
  for (const n of Object.values(nodes)) n.adjacent = (n.adjacent || []).map((target) => target === oldId ? id : target);
  return id;
}
function deleteNode(nodes, nodeId) {
  if (!Object.hasOwn(nodes, nodeId)) return nodes;
  delete nodes[nodeId];
  for (const node of Object.values(nodes)) node.adjacent = (node.adjacent || []).filter((id) => id !== nodeId);
  return nodes;
}
function entityMatchesFilter(entity, filter) {
  const query = filter.toLowerCase();
  return !query || [entity.entity_id, entity.name, entity.device_class, entity.state].some((v) => v?.toLowerCase().includes(query));
}
function defaultBehaviorForRole(role) {
  if (role === "transition_gate") return "transient";
  if (role === "ambiguous_open_plan") return "ambiguous";
  if (role === "anchor_sensor") return "sticky";
  return "sustained";
}
function zoneSummaries(map) {
  const grouped = /* @__PURE__ */ new Map();
  for (const [nodeId, node] of Object.entries(map.nodes)) {
    const id = node.zone || nodeId;
    const list2 = grouped.get(id) || [];
    list2.push({ nodeId, node });
    grouped.set(id, list2);
  }
  for (const id of Object.keys(map.zones || {})) if (!grouped.has(id)) grouped.set(id, []);
  return [...grouped].map(([zoneId, entries]) => {
    const config = map.zones?.[zoneId] || {};
    const positions = entries.flatMap(({ node }) => node.position ? [node.position] : []);
    const average = positions.length ? { x: Math.round(positions.reduce((sum, p) => sum + p.x, 0) / positions.length), y: Math.round(positions.reduce((sum, p) => sum + p.y, 0) / positions.length) } : { x: 80, y: 80 };
    const roles = new Set(entries.map(({ node }) => node.role).filter((v) => v !== void 0));
    const behaviors = new Set(entries.map(({ node }) => node.occupancy_behavior).filter((v) => v !== void 0));
    const role = config.role || (roles.size === 1 ? [...roles][0] : void 0) || "mixed";
    return {
      zoneId,
      label: config.label || titleFromId(zoneId),
      floor: config.floor || entries.find(({ node }) => node.floor)?.node.floor || "unassigned",
      role,
      occupancyBehavior: config.occupancy_behavior || (behaviors.size === 1 ? [...behaviors][0] : void 0) || defaultBehaviorForRole(role),
      position: { ...config.position || average },
      size: { ...config.size || { width: 210, height: 112 } },
      nodeIds: entries.map((e) => e.nodeId)
    };
  }).sort((a, b) => a.floor.localeCompare(b.floor) || a.label.localeCompare(b.label));
}
function learnedTransitionRows(map, status) {
  const rows = [];
  for (const [sourceId, targets] of Object.entries(status?.transition_counts || {})) {
    for (const [targetId, count] of Object.entries(targets)) {
      if (count > 0) rows.push({ sourceId, targetId, sourceLabel: map.nodes[sourceId]?.label || titleFromId(sourceId), targetLabel: map.nodes[targetId]?.label || titleFromId(targetId), count });
    }
  }
  return rows.sort((a, b) => b.count - a.count || a.sourceLabel.localeCompare(b.sourceLabel) || a.targetLabel.localeCompare(b.targetLabel));
}
export {
  addBidirectionalEdge,
  createEmptyNode,
  createNodeForEntity,
  defaultBehaviorForRole,
  deleteNode,
  entityMatchesFilter,
  learnedTransitionRows,
  moveNode,
  normalizeEntityResponse,
  removeBidirectionalEdge,
  renameNode,
  sanitizeNodeId,
  uniqueNodeId,
  zoneSummaries
};
