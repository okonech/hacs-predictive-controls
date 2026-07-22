export function sanitizeNodeId(value) {
  const sanitized = String(value || "node")
    .replace(/^.*\./, "")
    .replace(/[^a-zA-Z0-9_]/g, "_")
    .replace(/^_+|_+$/g, "");
  return sanitized || "node";
}

export function uniqueNodeId(nodes, base) {
  const sanitizedBase = sanitizeNodeId(base);
  let candidate = sanitizedBase;
  let index = 2;
  while (nodes[candidate]) {
    candidate = `${sanitizedBase}_${index}`;
    index += 1;
  }
  return candidate;
}

export function createNodeForEntity(nodes, entity, x, y) {
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
      reliability: 1,
      route_prior_weight: 1,
      position: { x: Math.round(Math.max(0, x)), y: Math.round(Math.max(0, y)) },
    },
  };
}

export function createEmptyNode(nodes) {
  const nodeId = uniqueNodeId(nodes, "node");
  return {
    nodeId,
    node: {
      label: nodeId,
      entities: {},
      adjacent: [],
      role: "room_occupancy",
      occupancy_behavior: "sustained",
      reliability: 1,
      route_prior_weight: 1,
      position: { x: 80, y: 80 },
    },
  };
}

export function moveNode(nodes, nodeId, x, y) {
  if (!nodes[nodeId]) return nodes;
  nodes[nodeId].position = {
    x: Math.round(Math.max(0, x)),
    y: Math.round(Math.max(0, y)),
  };
  return nodes;
}

export function addBidirectionalEdge(nodes, source, target) {
  if (!nodes[source] || !nodes[target] || source === target) return nodes;
  nodes[source].adjacent = Array.from(
    new Set([...(nodes[source].adjacent || []), target]),
  );
  nodes[target].adjacent = Array.from(
    new Set([...(nodes[target].adjacent || []), source]),
  );
  return nodes;
}

export function removeBidirectionalEdge(nodes, source, target) {
  if (!nodes[source] || !nodes[target]) return nodes;
  nodes[source].adjacent = (nodes[source].adjacent || []).filter(
    (item) => item !== target,
  );
  nodes[target].adjacent = (nodes[target].adjacent || []).filter(
    (item) => item !== source,
  );
  return nodes;
}

export function renameNode(nodes, oldId, newId) {
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

export function deleteNode(nodes, nodeId) {
  if (!nodes[nodeId]) return nodes;
  delete nodes[nodeId];
  for (const node of Object.values(nodes)) {
    node.adjacent = (node.adjacent || []).filter((target) => target !== nodeId);
  }
  return nodes;
}

export function entityMatchesFilter(entity, filterText) {
  const query = String(filterText || "").toLowerCase();
  if (!query) return true;
  return [entity.entity_id, entity.name, entity.device_class, entity.state]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(query));
}

export function normalizeEntityResponse(response) {
  return [...(response?.entities || [])].sort((left, right) =>
    left.entity_id.localeCompare(right.entity_id),
  );
}
