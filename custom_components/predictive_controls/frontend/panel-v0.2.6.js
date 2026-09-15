// Generated from frontend/ by scripts/build_frontend.mjs. Version 0.2.6. DO NOT EDIT.
"use strict";
(() => {
  // frontend/api.ts
  var REQUEST_TIMEOUT_MS = 15e3;
  function request(hass, message, timeout = REQUEST_TIMEOUT_MS) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`Request timed out: ${message.type}`)), timeout);
      Promise.resolve().then(() => hass.callWS(message)).then(
        (result) => {
          clearTimeout(timer);
          resolve(result);
        },
        (error) => {
          clearTimeout(timer);
          reject(error);
        }
      );
    });
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
  function finite(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) throw new Error("Expected a finite number");
    return value;
  }
  function probability(value) {
    const n = finite(value);
    if (n < 0 || n > 1) throw new Error("Probability must be between zero and one");
    return n;
  }
  function positive(value) {
    const n = finite(value);
    if (n <= 0) throw new Error("Expected a positive number");
    return n;
  }
  function bool(value) {
    if (typeof value !== "boolean") throw new Error("Expected a Boolean");
    return value;
  }
  function nullableText(value) {
    return value === null ? null : text(value);
  }
  function list(value, decode) {
    if (!Array.isArray(value)) throw new Error("Expected an array");
    return value.map((item) => decode(item));
  }
  function strings(value) {
    return list(value, text);
  }
  function dictionary(value, decode) {
    return Object.fromEntries(Object.entries(record(value)).map(([key, item]) => [key, decode(item)]));
  }
  function optional(source, key, decode, assign) {
    if (Object.hasOwn(source, key)) assign(decode(source[key]));
  }
  function point(value) {
    const p = record(value);
    return { ...dictionary(p, jsonData), x: finite(p.x), y: finite(p.y) };
  }
  function jsonData(value) {
    if (value === null || typeof value === "string" || typeof value === "boolean") return value;
    if (typeof value === "number") return finite(value);
    if (Array.isArray(value)) return list(value, jsonData);
    return dictionary(value, jsonData);
  }
  function decodeEntitiesMap(value) {
    return dictionary(value, (v) => Array.isArray(v) ? strings(v) : text(v));
  }
  function decodeNode(value) {
    const r = record(value);
    const node = dictionary(r, jsonData);
    optional(r, "label", text, (v) => node.label = v);
    optional(r, "zone", identity, (v) => node.zone = v);
    optional(r, "floor", text, (v) => node.floor = v);
    optional(r, "role", text, (v) => node.role = v);
    optional(r, "occupancy_behavior", text, (v) => node.occupancy_behavior = v);
    optional(r, "entities", decodeEntitiesMap, (v) => node.entities = v);
    optional(r, "adjacent", strings, (v) => node.adjacent = v);
    optional(r, "position", point, (v) => node.position = v);
    optional(r, "reliability", probability, (v) => node.reliability = v);
    optional(r, "route_prior_weight", positive, (v) => node.route_prior_weight = v);
    return node;
  }
  function decodeZone(value) {
    const r = record(value);
    const zone = dictionary(r, jsonData);
    optional(r, "label", text, (v) => zone.label = v);
    optional(r, "floor", text, (v) => zone.floor = v);
    optional(r, "role", text, (v) => zone.role = v);
    optional(r, "occupancy_behavior", text, (v) => zone.occupancy_behavior = v);
    optional(r, "position", point, (v) => zone.position = v);
    optional(r, "size", (v) => {
      const s = record(v);
      return { ...dictionary(s, jsonData), width: positive(s.width), height: positive(s.height) };
    }, (v) => zone.size = v);
    return zone;
  }
  function decodeMap(value) {
    const r = record(value);
    const map2 = { ...dictionary(r, jsonData), nodes: dictionary(r.nodes, decodeNode) };
    optional(r, "zones", (v) => dictionary(v, decodeZone), (v) => map2.zones = v);
    optional(r, "floors", strings, (v) => map2.floors = v);
    return map2;
  }
  function decodeConfig(value) {
    const r = record(value);
    const config = {
      entry_id: identity(r.entry_id),
      map: decodeMap(r.map),
      map_yaml: text(r.map_yaml),
      transition_window_seconds: positive(r.transition_window_seconds),
      expected_occupants: finite(r.expected_occupants)
    };
    optional(r, "title", text, (v) => config.title = v);
    optional(r, "expected_occupants_entity", text, (v) => config.expected_occupants_entity = v);
    validateSettings(config);
    return config;
  }
  function validateSettings(config) {
    if (!Number.isInteger(config.transition_window_seconds) || config.transition_window_seconds < 1) throw new Error("Transition window must be a positive integer");
    if (!Number.isInteger(config.expected_occupants) || config.expected_occupants < 0 || config.expected_occupants > 2) throw new Error("Expected occupants must be zero, one or two");
    if (config.expected_occupants_entity && !config.expected_occupants_entity.includes(".")) throw new Error("Expected occupants entity must be an entity id");
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
  function visit(value) {
    const r = record(value);
    const result = { node_id: identity(r.node_id), zone: identity(r.zone), episode_id: identity(r.episode_id), branch_active: bool(r.branch_active) };
    optional(r, "at", text, (v) => {
      if (!Number.isFinite(Date.parse(v))) throw new Error("Invalid visit timestamp");
      result.at = v;
    });
    optional(r, "kind", text, (v) => {
      if (!["positive", "correlated_positive", "interaction"].includes(v)) throw new Error("Invalid visit kind");
      result.kind = v;
    });
    return result;
  }
  function decodeSelectedPaths(value) {
    const paths = list(value, (v) => {
      if (v === null) return null;
      const r = record(v);
      const confidence = text(r.track_confidence);
      if (confidence !== "provisional" && confidence !== "confirmed") throw new Error("Invalid track confidence");
      const route = list(r.route, visit);
      if (route.length < 1 || route.length > 4 || new Set(route.map((item) => item.episode_id)).size !== route.length) throw new Error("Invalid bounded selected route");
      const result = { route, track_confidence: confidence, endpoint_eligible: bool(r.endpoint_eligible) };
      optional(r, "endpoint", visit, (endpoint) => {
        const last = route.at(-1);
        if (!last || endpoint.node_id !== last.node_id || endpoint.zone !== last.zone || endpoint.episode_id !== last.episode_id || endpoint.branch_active !== last.branch_active) throw new Error("Selected endpoint disagrees with route");
        result.endpoint = endpoint;
      });
      return result;
    });
    if (paths.length > 2) throw new Error("Unsupported selected slot count");
    return paths;
  }
  function episode(value) {
    const r = record(value);
    const result = { node_id: identity(r.node_id) };
    optional(r, "zone", text, (v) => result.zone = v);
    optional(r, "episode_id", nullableText, (v) => result.episode_id = v);
    optional(r, "status", text, (v) => result.status = v);
    return result;
  }
  function health(value) {
    const r = record(value);
    const phase = text(r.phase);
    if (phase !== "on" && phase !== "off" && phase !== "unknown" && phase !== "clearing") throw new Error("Invalid physical phase");
    return { node_id: identity(r.node_id), zone: identity(r.zone), phase };
  }
  function warning(value) {
    const r = record(value);
    const result = { node_id: identity(r.node_id), zone: identity(r.zone), kind: text(r.kind), active: bool(r.active) };
    optional(r, "reasons", strings, (v) => result.reasons = v);
    optional(r, "last_observed_at", nullableText, (v) => result.last_observed_at = v);
    return result;
  }
  function policy(value) {
    const r = record(value);
    const result = { active: bool(r.active) };
    optional(r, "profile", text, (v) => result.profile = v);
    optional(r, "pending_release_since", nullableText, (v) => result.pending_release_since = v);
    return result;
  }
  function audit(value) {
    const r = record(value);
    const result = {};
    optional(r, "event_at", text, (v) => result.event_at = v);
    optional(r, "zone", text, (v) => result.zone = v);
    optional(r, "active_before", bool, (v) => result.active_before = v);
    optional(r, "active_after", bool, (v) => result.active_after = v);
    optional(r, "belief_after", probability, (v) => result.belief_after = v);
    optional(r, "traversal_reason", nullableText, (v) => result.traversal_reason = v);
    optional(r, "evidence_ids", strings, (v) => result.evidence_ids = v);
    optional(r, "event_kind", nullableText, (v) => result.event_kind = v);
    optional(r, "reason", text, (v) => result.reason = v);
    return result;
  }
  function frontier(value) {
    const r = record(value);
    const result = { token_id: identity(r.token_id) };
    optional(r, "zone", text, (v) => result.zone = v);
    optional(r, "valid_until", text, (v) => result.valid_until = v);
    return result;
  }
  function authorization(value) {
    const r = record(value);
    const result = { authorized: bool(r.authorized) };
    optional(r, "source_token_ids", strings, (v) => result.source_token_ids = v);
    optional(r, "target_zone", text, (v) => result.target_zone = v);
    optional(r, "reason", text, (v) => result.reason = v);
    return result;
  }
  function decodeDiagnostics(value) {
    const r = record(value);
    const d = {};
    optional(r, "model", text, (v) => d.model = v);
    optional(r, "expected_occupants", finite, (v) => d.expected_occupants = v);
    optional(r, "unsupported_count", bool, (v) => d.unsupported_count = v);
    optional(r, "beliefs", (v) => dictionary(v, probability), (v) => d.beliefs = v);
    optional(r, "policy", (v) => dictionary(v, policy), (v) => d.policy = v);
    optional(r, "policy_audit", (v) => list(v, audit), (v) => d.policy_audit = v);
    optional(r, "episodes", (v) => list(v, episode), (v) => d.episodes = v);
    optional(r, "path_health", (v) => list(v, health), (v) => d.path_health = v);
    optional(r, "reliability_warnings", (v) => list(v, warning), (v) => d.reliability_warnings = v);
    optional(r, "health_warnings", strings, (v) => d.health_warnings = v);
    optional(r, "processing", (v) => {
      const p = record(v);
      const result = {};
      optional(p, "token_count", finite, (n) => result.token_count = n);
      return result;
    }, (v) => d.processing = v);
    optional(r, "traversal_frontier", (v) => list(v, frontier), (v) => d.traversal_frontier = v);
    optional(r, "authorizations", (v) => list(v, authorization), (v) => d.authorizations = v);
    if (Object.hasOwn(r, "selected_paths")) {
      try {
        d.selected_paths = decodeSelectedPaths(r.selected_paths);
      } catch (error) {
        d.selected_paths_error = error instanceof Error ? error.message : "Invalid selected paths";
      }
    }
    return d;
  }
  function zoneState(value) {
    const r = record(value);
    const result = {};
    optional(r, "confidence", probability, (v) => result.confidence = v);
    optional(r, "status", text, (v) => result.status = v);
    optional(r, "reason", text, (v) => result.reason = v);
    optional(r, "occupancy_behavior", text, (v) => result.occupancy_behavior = v);
    optional(r, "last_node_id", nullableText, (v) => result.last_node_id = v);
    return result;
  }
  function decodeStatus(value) {
    const r = record(value);
    const result = {};
    optional(r, "expected_occupants", finite, (v) => result.expected_occupants = v);
    optional(r, "zone_states", (v) => dictionary(v, zoneState), (v) => result.zone_states = v);
    optional(r, "transition_counts", (v) => dictionary(v, (row) => dictionary(row, finite)), (v) => result.transition_counts = v);
    optional(r, "occupancy_diagnostics", decodeDiagnostics, (v) => result.occupancy_diagnostics = v);
    return result;
  }
  function decodeCleanup(value, preview) {
    const r = record(value);
    const count = finite(preview ? r.stale_count : r.removed_count);
    if (!Number.isInteger(count) || count < 0) throw new Error("Invalid cleanup count");
    return count;
  }

  // frontend/formatting.ts
  function escapeHtml(value) {
    return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function titleFromId(value) {
    return (value || "unknown").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
  var labelFromValue = titleFromId;
  function formatTimestamp(value) {
    if (!value) return "never";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  }
  function formatPercent(value) {
    return value !== void 0 && Number.isFinite(value) && value >= 0 && value <= 1 ? `${Math.round(value * 100)}%` : "unavailable";
  }
  function warningLabel(warning2) {
    return warning2.kind === "suspected_stuck" && warning2.reasons?.length === 1 && warning2.reasons[0] === "assertion_timeout" ? "Continuous presence detected; path unverified" : titleFromId(warning2.kind);
  }
  function policyModel(status) {
    return status?.occupancy_diagnostics?.model === "zone_belief" ? status.occupancy_diagnostics : void 0;
  }
  function zoneLabel(map2, zone) {
    return (zone ? map2.zones?.[zone]?.label : void 0) || titleFromId(zone || "whole home");
  }
  function auditTransition(entry) {
    return [entry.active_before === true, entry.active_after === true];
  }
  function auditKind(entry) {
    const [before, after] = auditTransition(entry);
    if (entry.active_before !== void 0 && entry.active_after !== void 0 && before !== after) return "edges";
    if (entry.reason === "acquisition_unauthorized") return "rejected";
    return entry.event_kind ? "other" : "observations";
  }
  function decisionExplanation(entry) {
    return `${titleFromId(entry.reason || "policy observation")} at ${formatPercent(entry.belief_after)}` + (entry.traversal_reason ? ` via ${titleFromId(entry.traversal_reason)}` : "");
  }
  function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
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
  function zoneSummaries(map2) {
    const grouped = /* @__PURE__ */ new Map();
    for (const [nodeId, node] of Object.entries(map2.nodes)) {
      const id = node.zone || nodeId;
      const list2 = grouped.get(id) || [];
      list2.push({ nodeId, node });
      grouped.set(id, list2);
    }
    for (const id of Object.keys(map2.zones || {})) if (!grouped.has(id)) grouped.set(id, []);
    return [...grouped].map(([zoneId, entries]) => {
      const config = map2.zones?.[zoneId] || {};
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
  function learnedTransitionRows(map2, status) {
    const rows = [];
    for (const [sourceId, targets] of Object.entries(status?.transition_counts || {})) {
      for (const [targetId, count] of Object.entries(targets)) {
        if (count > 0) rows.push({ sourceId, targetId, sourceLabel: map2.nodes[sourceId]?.label || titleFromId(sourceId), targetLabel: map2.nodes[targetId]?.label || titleFromId(targetId), count });
      }
    }
    return rows.sort((a, b) => b.count - a.count || a.sourceLabel.localeCompare(b.sourceLabel) || a.targetLabel.localeCompare(b.targetLabel));
  }

  // node_modules/yaml/browser/dist/nodes/identity.js
  var ALIAS = Symbol.for("yaml.alias");
  var DOC = Symbol.for("yaml.document");
  var MAP = Symbol.for("yaml.map");
  var PAIR = Symbol.for("yaml.pair");
  var SCALAR = Symbol.for("yaml.scalar");
  var SEQ = Symbol.for("yaml.seq");
  var NODE_TYPE = Symbol.for("yaml.node.type");
  var isAlias = (node) => !!node && typeof node === "object" && node[NODE_TYPE] === ALIAS;
  var isDocument = (node) => !!node && typeof node === "object" && node[NODE_TYPE] === DOC;
  var isMap = (node) => !!node && typeof node === "object" && node[NODE_TYPE] === MAP;
  var isPair = (node) => !!node && typeof node === "object" && node[NODE_TYPE] === PAIR;
  var isScalar = (node) => !!node && typeof node === "object" && node[NODE_TYPE] === SCALAR;
  var isSeq = (node) => !!node && typeof node === "object" && node[NODE_TYPE] === SEQ;
  function isCollection(node) {
    if (node && typeof node === "object")
      switch (node[NODE_TYPE]) {
        case MAP:
        case SEQ:
          return true;
      }
    return false;
  }
  function isNode(node) {
    if (node && typeof node === "object")
      switch (node[NODE_TYPE]) {
        case ALIAS:
        case MAP:
        case SCALAR:
        case SEQ:
          return true;
      }
    return false;
  }
  var hasAnchor = (node) => (isScalar(node) || isCollection(node)) && !!node.anchor;

  // node_modules/yaml/browser/dist/visit.js
  var BREAK = Symbol("break visit");
  var SKIP = Symbol("skip children");
  var REMOVE = Symbol("remove node");
  function visit2(node, visitor) {
    const visitor_ = initVisitor(visitor);
    if (isDocument(node)) {
      const cd = visit_(null, node.contents, visitor_, Object.freeze([node]));
      if (cd === REMOVE)
        node.contents = null;
    } else
      visit_(null, node, visitor_, Object.freeze([]));
  }
  visit2.BREAK = BREAK;
  visit2.SKIP = SKIP;
  visit2.REMOVE = REMOVE;
  function visit_(key, node, visitor, path) {
    const ctrl = callVisitor(key, node, visitor, path);
    if (isNode(ctrl) || isPair(ctrl)) {
      replaceNode(key, path, ctrl);
      return visit_(key, ctrl, visitor, path);
    }
    if (typeof ctrl !== "symbol") {
      if (isCollection(node)) {
        path = Object.freeze(path.concat(node));
        for (let i = 0; i < node.items.length; ++i) {
          const ci = visit_(i, node.items[i], visitor, path);
          if (typeof ci === "number")
            i = ci - 1;
          else if (ci === BREAK)
            return BREAK;
          else if (ci === REMOVE) {
            node.items.splice(i, 1);
            i -= 1;
          }
        }
      } else if (isPair(node)) {
        path = Object.freeze(path.concat(node));
        const ck = visit_("key", node.key, visitor, path);
        if (ck === BREAK)
          return BREAK;
        else if (ck === REMOVE)
          node.key = null;
        const cv = visit_("value", node.value, visitor, path);
        if (cv === BREAK)
          return BREAK;
        else if (cv === REMOVE)
          node.value = null;
      }
    }
    return ctrl;
  }
  async function visitAsync(node, visitor) {
    const visitor_ = initVisitor(visitor);
    if (isDocument(node)) {
      const cd = await visitAsync_(null, node.contents, visitor_, Object.freeze([node]));
      if (cd === REMOVE)
        node.contents = null;
    } else
      await visitAsync_(null, node, visitor_, Object.freeze([]));
  }
  visitAsync.BREAK = BREAK;
  visitAsync.SKIP = SKIP;
  visitAsync.REMOVE = REMOVE;
  async function visitAsync_(key, node, visitor, path) {
    const ctrl = await callVisitor(key, node, visitor, path);
    if (isNode(ctrl) || isPair(ctrl)) {
      replaceNode(key, path, ctrl);
      return visitAsync_(key, ctrl, visitor, path);
    }
    if (typeof ctrl !== "symbol") {
      if (isCollection(node)) {
        path = Object.freeze(path.concat(node));
        for (let i = 0; i < node.items.length; ++i) {
          const ci = await visitAsync_(i, node.items[i], visitor, path);
          if (typeof ci === "number")
            i = ci - 1;
          else if (ci === BREAK)
            return BREAK;
          else if (ci === REMOVE) {
            node.items.splice(i, 1);
            i -= 1;
          }
        }
      } else if (isPair(node)) {
        path = Object.freeze(path.concat(node));
        const ck = await visitAsync_("key", node.key, visitor, path);
        if (ck === BREAK)
          return BREAK;
        else if (ck === REMOVE)
          node.key = null;
        const cv = await visitAsync_("value", node.value, visitor, path);
        if (cv === BREAK)
          return BREAK;
        else if (cv === REMOVE)
          node.value = null;
      }
    }
    return ctrl;
  }
  function initVisitor(visitor) {
    if (typeof visitor === "object" && (visitor.Collection || visitor.Node || visitor.Value)) {
      return Object.assign({
        Alias: visitor.Node,
        Map: visitor.Node,
        Scalar: visitor.Node,
        Seq: visitor.Node
      }, visitor.Value && {
        Map: visitor.Value,
        Scalar: visitor.Value,
        Seq: visitor.Value
      }, visitor.Collection && {
        Map: visitor.Collection,
        Seq: visitor.Collection
      }, visitor);
    }
    return visitor;
  }
  function callVisitor(key, node, visitor, path) {
    if (typeof visitor === "function")
      return visitor(key, node, path);
    if (isMap(node))
      return visitor.Map?.(key, node, path);
    if (isSeq(node))
      return visitor.Seq?.(key, node, path);
    if (isPair(node))
      return visitor.Pair?.(key, node, path);
    if (isScalar(node))
      return visitor.Scalar?.(key, node, path);
    if (isAlias(node))
      return visitor.Alias?.(key, node, path);
    return void 0;
  }
  function replaceNode(key, path, node) {
    const parent = path[path.length - 1];
    if (isCollection(parent)) {
      parent.items[key] = node;
    } else if (isPair(parent)) {
      if (key === "key")
        parent.key = node;
      else
        parent.value = node;
    } else if (isDocument(parent)) {
      parent.contents = node;
    } else {
      const pt = isAlias(parent) ? "alias" : "scalar";
      throw new Error(`Cannot replace node with ${pt} parent`);
    }
  }

  // node_modules/yaml/browser/dist/doc/directives.js
  var escapeChars = {
    "!": "%21",
    ",": "%2C",
    "[": "%5B",
    "]": "%5D",
    "{": "%7B",
    "}": "%7D"
  };
  var escapeTagName = (tn) => tn.replace(/[!,[\]{}]/g, (ch) => escapeChars[ch]);
  var Directives = class _Directives {
    constructor(yaml, tags) {
      this.docStart = null;
      this.docEnd = false;
      this.yaml = Object.assign({}, _Directives.defaultYaml, yaml);
      this.tags = Object.assign({}, _Directives.defaultTags, tags);
    }
    clone() {
      const copy = new _Directives(this.yaml, this.tags);
      copy.docStart = this.docStart;
      return copy;
    }
    /**
     * During parsing, get a Directives instance for the current document and
     * update the stream state according to the current version's spec.
     */
    atDocument() {
      const res = new _Directives(this.yaml, this.tags);
      switch (this.yaml.version) {
        case "1.1":
          this.atNextDocument = true;
          break;
        case "1.2":
          this.atNextDocument = false;
          this.yaml = {
            explicit: _Directives.defaultYaml.explicit,
            version: "1.2"
          };
          this.tags = Object.assign({}, _Directives.defaultTags);
          break;
      }
      return res;
    }
    /**
     * @param onError - May be called even if the action was successful
     * @returns `true` on success
     */
    add(line, onError) {
      if (this.atNextDocument) {
        this.yaml = { explicit: _Directives.defaultYaml.explicit, version: "1.1" };
        this.tags = Object.assign({}, _Directives.defaultTags);
        this.atNextDocument = false;
      }
      const parts = line.trim().split(/[ \t]+/);
      const name = parts.shift();
      switch (name) {
        case "%TAG": {
          if (parts.length !== 2) {
            onError(0, "%TAG directive should contain exactly two parts");
            if (parts.length < 2)
              return false;
          }
          const [handle, prefix] = parts;
          this.tags[handle] = prefix;
          return true;
        }
        case "%YAML": {
          this.yaml.explicit = true;
          if (parts.length !== 1) {
            onError(0, "%YAML directive should contain exactly one part");
            return false;
          }
          const [version] = parts;
          if (version === "1.1" || version === "1.2") {
            this.yaml.version = version;
            return true;
          } else {
            const isValid = /^\d+\.\d+$/.test(version);
            onError(6, `Unsupported YAML version ${version}`, isValid);
            return false;
          }
        }
        default:
          onError(0, `Unknown directive ${name}`, true);
          return false;
      }
    }
    /**
     * Resolves a tag, matching handles to those defined in %TAG directives.
     *
     * @returns Resolved tag, which may also be the non-specific tag `'!'` or a
     *   `'!local'` tag, or `null` if unresolvable.
     */
    tagName(source, onError) {
      if (source === "!")
        return "!";
      if (source[0] !== "!") {
        onError(`Not a valid tag: ${source}`);
        return null;
      }
      if (source[1] === "<") {
        const verbatim = source.slice(2, -1);
        if (verbatim === "!" || verbatim === "!!") {
          onError(`Verbatim tags aren't resolved, so ${source} is invalid.`);
          return null;
        }
        if (source[source.length - 1] !== ">")
          onError("Verbatim tags must end with a >");
        return verbatim;
      }
      const [, handle, suffix] = source.match(/^(.*!)([^!]*)$/s);
      if (!suffix)
        onError(`The ${source} tag has no suffix`);
      const prefix = this.tags[handle];
      if (prefix) {
        try {
          return prefix + decodeURIComponent(suffix);
        } catch (error) {
          onError(String(error));
          return null;
        }
      }
      if (handle === "!")
        return source;
      onError(`Could not resolve tag: ${source}`);
      return null;
    }
    /**
     * Given a fully resolved tag, returns its printable string form,
     * taking into account current tag prefixes and defaults.
     */
    tagString(tag) {
      for (const [handle, prefix] of Object.entries(this.tags)) {
        if (tag.startsWith(prefix))
          return handle + escapeTagName(tag.substring(prefix.length));
      }
      return tag[0] === "!" ? tag : `!<${tag}>`;
    }
    toString(doc) {
      const lines = this.yaml.explicit ? [`%YAML ${this.yaml.version || "1.2"}`] : [];
      const tagEntries = Object.entries(this.tags);
      let tagNames;
      if (doc && tagEntries.length > 0 && isNode(doc.contents)) {
        const tags = {};
        visit2(doc.contents, (_key, node) => {
          if (isNode(node) && node.tag)
            tags[node.tag] = true;
        });
        tagNames = Object.keys(tags);
      } else
        tagNames = [];
      for (const [handle, prefix] of tagEntries) {
        if (handle === "!!" && prefix === "tag:yaml.org,2002:")
          continue;
        if (!doc || tagNames.some((tn) => tn.startsWith(prefix)))
          lines.push(`%TAG ${handle} ${prefix}`);
      }
      return lines.join("\n");
    }
  };
  Directives.defaultYaml = { explicit: false, version: "1.2" };
  Directives.defaultTags = { "!!": "tag:yaml.org,2002:" };

  // node_modules/yaml/browser/dist/doc/anchors.js
  function anchorIsValid(anchor) {
    if (/[\x00-\x19\s,[\]{}]/.test(anchor)) {
      const sa = JSON.stringify(anchor);
      const msg = `Anchor must not contain whitespace or control characters: ${sa}`;
      throw new Error(msg);
    }
    return true;
  }
  function anchorNames(root) {
    const anchors = /* @__PURE__ */ new Set();
    visit2(root, {
      Value(_key, node) {
        if (node.anchor)
          anchors.add(node.anchor);
      }
    });
    return anchors;
  }
  function findNewAnchor(prefix, exclude) {
    for (let i = 1; true; ++i) {
      const name = `${prefix}${i}`;
      if (!exclude.has(name))
        return name;
    }
  }
  function createNodeAnchors(doc, prefix) {
    const aliasObjects = [];
    const sourceObjects = /* @__PURE__ */ new Map();
    let prevAnchors = null;
    return {
      onAnchor: (source) => {
        aliasObjects.push(source);
        prevAnchors ?? (prevAnchors = anchorNames(doc));
        const anchor = findNewAnchor(prefix, prevAnchors);
        prevAnchors.add(anchor);
        return anchor;
      },
      /**
       * With circular references, the source node is only resolved after all
       * of its child nodes are. This is why anchors are set only after all of
       * the nodes have been created.
       */
      setAnchors: () => {
        for (const source of aliasObjects) {
          const ref = sourceObjects.get(source);
          if (typeof ref === "object" && ref.anchor && (isScalar(ref.node) || isCollection(ref.node))) {
            ref.node.anchor = ref.anchor;
          } else {
            const error = new Error("Failed to resolve repeated object (this should not happen)");
            error.source = source;
            throw error;
          }
        }
      },
      sourceObjects
    };
  }

  // node_modules/yaml/browser/dist/doc/applyReviver.js
  function applyReviver(reviver, obj, key, val) {
    if (val && typeof val === "object") {
      if (Array.isArray(val)) {
        for (let i = 0, len = val.length; i < len; ++i) {
          const v0 = val[i];
          const v1 = applyReviver(reviver, val, String(i), v0);
          if (v1 === void 0)
            delete val[i];
          else if (v1 !== v0)
            val[i] = v1;
        }
      } else if (val instanceof Map) {
        for (const k of Array.from(val.keys())) {
          const v0 = val.get(k);
          const v1 = applyReviver(reviver, val, k, v0);
          if (v1 === void 0)
            val.delete(k);
          else if (v1 !== v0)
            val.set(k, v1);
        }
      } else if (val instanceof Set) {
        for (const v0 of Array.from(val)) {
          const v1 = applyReviver(reviver, val, v0, v0);
          if (v1 === void 0)
            val.delete(v0);
          else if (v1 !== v0) {
            val.delete(v0);
            val.add(v1);
          }
        }
      } else {
        for (const [k, v0] of Object.entries(val)) {
          const v1 = applyReviver(reviver, val, k, v0);
          if (v1 === void 0)
            delete val[k];
          else if (v1 !== v0)
            val[k] = v1;
        }
      }
    }
    return reviver.call(obj, key, val);
  }

  // node_modules/yaml/browser/dist/nodes/toJS.js
  function toJS(value, arg, ctx) {
    if (Array.isArray(value))
      return value.map((v, i) => toJS(v, String(i), ctx));
    if (value && typeof value.toJSON === "function") {
      if (!ctx || !hasAnchor(value))
        return value.toJSON(arg, ctx);
      const data = { aliasCount: 0, count: 1, res: void 0 };
      ctx.anchors.set(value, data);
      ctx.onCreate = (res2) => {
        data.res = res2;
        delete ctx.onCreate;
      };
      const res = value.toJSON(arg, ctx);
      if (ctx.onCreate)
        ctx.onCreate(res);
      return res;
    }
    if (typeof value === "bigint" && !ctx?.keep)
      return Number(value);
    return value;
  }

  // node_modules/yaml/browser/dist/nodes/Node.js
  var NodeBase = class {
    constructor(type) {
      Object.defineProperty(this, NODE_TYPE, { value: type });
    }
    /** Create a copy of this node.  */
    clone() {
      const copy = Object.create(Object.getPrototypeOf(this), Object.getOwnPropertyDescriptors(this));
      if (this.range)
        copy.range = this.range.slice();
      return copy;
    }
    /** A plain JavaScript representation of this node. */
    toJS(doc, { mapAsMap, maxAliasCount, onAnchor, reviver } = {}) {
      if (!isDocument(doc))
        throw new TypeError("A document argument is required");
      const ctx = {
        anchors: /* @__PURE__ */ new Map(),
        doc,
        keep: true,
        mapAsMap: mapAsMap === true,
        mapKeyWarned: false,
        maxAliasCount: typeof maxAliasCount === "number" ? maxAliasCount : 100
      };
      const res = toJS(this, "", ctx);
      if (typeof onAnchor === "function")
        for (const { count, res: res2 } of ctx.anchors.values())
          onAnchor(res2, count);
      return typeof reviver === "function" ? applyReviver(reviver, { "": res }, "", res) : res;
    }
  };

  // node_modules/yaml/browser/dist/nodes/Alias.js
  var Alias = class extends NodeBase {
    constructor(source) {
      super(ALIAS);
      this.source = source;
      Object.defineProperty(this, "tag", {
        set() {
          throw new Error("Alias nodes cannot have tags");
        }
      });
    }
    /**
     * Resolve the value of this alias within `doc`, finding the last
     * instance of the `source` anchor before this node.
     */
    resolve(doc, ctx) {
      if (ctx?.maxAliasCount === 0)
        throw new ReferenceError("Alias resolution is disabled");
      let nodes;
      if (ctx?.aliasResolveCache) {
        nodes = ctx.aliasResolveCache;
      } else {
        nodes = [];
        visit2(doc, {
          Node: (_key, node) => {
            if (isAlias(node) || hasAnchor(node))
              nodes.push(node);
          }
        });
        if (ctx)
          ctx.aliasResolveCache = nodes;
      }
      let found = void 0;
      for (const node of nodes) {
        if (node === this)
          break;
        if (node.anchor === this.source)
          found = node;
      }
      if (found && ctx) {
        const { anchors, doc: doc2, maxAliasCount } = ctx;
        let data = anchors.get(found);
        if (!data) {
          toJS(found, null, ctx);
          data = anchors.get(found);
        }
        if (data?.res === void 0) {
          const msg = "This should not happen: Alias anchor was not resolved?";
          throw new ReferenceError(msg);
        }
        if (maxAliasCount >= 0) {
          data.count += 1;
          if (data.aliasCount === 0)
            data.aliasCount = getAliasCount(doc2, found, anchors);
          if (data.count * data.aliasCount > maxAliasCount) {
            const msg = "Excessive alias count indicates a resource exhaustion attack";
            throw new ReferenceError(msg);
          }
        }
      }
      return found;
    }
    toJSON(_arg, ctx) {
      if (!ctx)
        return { source: this.source };
      const source = this.resolve(ctx.doc, ctx);
      if (!source) {
        const msg = `Unresolved alias (the anchor must be set before the alias): ${this.source}`;
        throw new ReferenceError(msg);
      }
      return ctx.anchors.get(source).res;
    }
    toString(ctx, _onComment, _onChompKeep) {
      const src = `*${this.source}`;
      if (ctx) {
        anchorIsValid(this.source);
        if (ctx.options.verifyAliasOrder && !ctx.anchors.has(this.source)) {
          const msg = `Unresolved alias (the anchor must be set before the alias): ${this.source}`;
          throw new Error(msg);
        }
        if (ctx.implicitKey)
          return `${src} `;
      }
      return src;
    }
  };
  function getAliasCount(doc, node, anchors) {
    if (isAlias(node)) {
      const source = node.resolve(doc);
      const anchor = anchors && source && anchors.get(source);
      return anchor ? anchor.count * anchor.aliasCount : 0;
    } else if (isCollection(node)) {
      let count = 0;
      for (const item of node.items) {
        const c = getAliasCount(doc, item, anchors);
        if (c > count)
          count = c;
      }
      return count;
    } else if (isPair(node)) {
      const kc = getAliasCount(doc, node.key, anchors);
      const vc = getAliasCount(doc, node.value, anchors);
      return Math.max(kc, vc);
    }
    return 1;
  }

  // node_modules/yaml/browser/dist/nodes/Scalar.js
  var isScalarValue = (value) => !value || typeof value !== "function" && typeof value !== "object";
  var Scalar = class extends NodeBase {
    constructor(value) {
      super(SCALAR);
      this.value = value;
    }
    toJSON(arg, ctx) {
      return ctx?.keep ? this.value : toJS(this.value, arg, ctx);
    }
    toString() {
      return String(this.value);
    }
  };
  Scalar.BLOCK_FOLDED = "BLOCK_FOLDED";
  Scalar.BLOCK_LITERAL = "BLOCK_LITERAL";
  Scalar.PLAIN = "PLAIN";
  Scalar.QUOTE_DOUBLE = "QUOTE_DOUBLE";
  Scalar.QUOTE_SINGLE = "QUOTE_SINGLE";

  // node_modules/yaml/browser/dist/doc/createNode.js
  var defaultTagPrefix = "tag:yaml.org,2002:";
  function findTagObject(value, tagName, tags) {
    if (tagName) {
      const match = tags.filter((t) => t.tag === tagName);
      const tagObj = match.find((t) => !t.format) ?? match[0];
      if (!tagObj)
        throw new Error(`Tag ${tagName} not found`);
      return tagObj;
    }
    return tags.find((t) => t.identify?.(value) && !t.format);
  }
  function createNode(value, tagName, ctx) {
    if (isDocument(value))
      value = value.contents;
    if (isNode(value))
      return value;
    if (isPair(value)) {
      const map2 = ctx.schema[MAP].createNode?.(ctx.schema, null, ctx);
      map2.items.push(value);
      return map2;
    }
    if (value instanceof String || value instanceof Number || value instanceof Boolean || typeof BigInt !== "undefined" && value instanceof BigInt) {
      value = value.valueOf();
    }
    const { aliasDuplicateObjects, onAnchor, onTagObj, schema: schema4, sourceObjects } = ctx;
    let ref = void 0;
    if (aliasDuplicateObjects && value && typeof value === "object") {
      ref = sourceObjects.get(value);
      if (ref) {
        ref.anchor ?? (ref.anchor = onAnchor(value));
        return new Alias(ref.anchor);
      } else {
        ref = { anchor: null, node: null };
        sourceObjects.set(value, ref);
      }
    }
    if (tagName?.startsWith("!!"))
      tagName = defaultTagPrefix + tagName.slice(2);
    let tagObj = findTagObject(value, tagName, schema4.tags);
    if (!tagObj) {
      if (value && typeof value.toJSON === "function") {
        value = value.toJSON();
      }
      if (!value || typeof value !== "object") {
        const node2 = new Scalar(value);
        if (ref)
          ref.node = node2;
        return node2;
      }
      tagObj = value instanceof Map ? schema4[MAP] : Symbol.iterator in Object(value) ? schema4[SEQ] : schema4[MAP];
    }
    if (onTagObj) {
      onTagObj(tagObj);
      delete ctx.onTagObj;
    }
    const node = tagObj?.createNode ? tagObj.createNode(ctx.schema, value, ctx) : typeof tagObj?.nodeClass?.from === "function" ? tagObj.nodeClass.from(ctx.schema, value, ctx) : new Scalar(value);
    if (tagName)
      node.tag = tagName;
    else if (!tagObj.default)
      node.tag = tagObj.tag;
    if (ref)
      ref.node = node;
    return node;
  }

  // node_modules/yaml/browser/dist/nodes/Collection.js
  function collectionFromPath(schema4, path, value) {
    let v = value;
    for (let i = path.length - 1; i >= 0; --i) {
      const k = path[i];
      if (typeof k === "number" && Number.isInteger(k) && k >= 0) {
        const a = [];
        a[k] = v;
        v = a;
      } else {
        v = /* @__PURE__ */ new Map([[k, v]]);
      }
    }
    return createNode(v, void 0, {
      aliasDuplicateObjects: false,
      keepUndefined: false,
      onAnchor: () => {
        throw new Error("This should not happen, please report a bug.");
      },
      schema: schema4,
      sourceObjects: /* @__PURE__ */ new Map()
    });
  }
  var isEmptyPath = (path) => path == null || typeof path === "object" && !!path[Symbol.iterator]().next().done;
  var Collection = class extends NodeBase {
    constructor(type, schema4) {
      super(type);
      Object.defineProperty(this, "schema", {
        value: schema4,
        configurable: true,
        enumerable: false,
        writable: true
      });
    }
    /**
     * Create a copy of this collection.
     *
     * @param schema - If defined, overwrites the original's schema
     */
    clone(schema4) {
      const copy = Object.create(Object.getPrototypeOf(this), Object.getOwnPropertyDescriptors(this));
      if (schema4)
        copy.schema = schema4;
      copy.items = copy.items.map((it) => isNode(it) || isPair(it) ? it.clone(schema4) : it);
      if (this.range)
        copy.range = this.range.slice();
      return copy;
    }
    /**
     * Adds a value to the collection. For `!!map` and `!!omap` the value must
     * be a Pair instance or a `{ key, value }` object, which may not have a key
     * that already exists in the map.
     */
    addIn(path, value) {
      if (isEmptyPath(path))
        this.add(value);
      else {
        const [key, ...rest] = path;
        const node = this.get(key, true);
        if (isCollection(node))
          node.addIn(rest, value);
        else if (node === void 0 && this.schema)
          this.set(key, collectionFromPath(this.schema, rest, value));
        else
          throw new Error(`Expected YAML collection at ${key}. Remaining path: ${rest}`);
      }
    }
    /**
     * Removes a value from the collection.
     * @returns `true` if the item was found and removed.
     */
    deleteIn(path) {
      const [key, ...rest] = path;
      if (rest.length === 0)
        return this.delete(key);
      const node = this.get(key, true);
      if (isCollection(node))
        return node.deleteIn(rest);
      else
        throw new Error(`Expected YAML collection at ${key}. Remaining path: ${rest}`);
    }
    /**
     * Returns item at `key`, or `undefined` if not found. By default unwraps
     * scalar values from their surrounding node; to disable set `keepScalar` to
     * `true` (collections are always returned intact).
     */
    getIn(path, keepScalar) {
      const [key, ...rest] = path;
      const node = this.get(key, true);
      if (rest.length === 0)
        return !keepScalar && isScalar(node) ? node.value : node;
      else
        return isCollection(node) ? node.getIn(rest, keepScalar) : void 0;
    }
    hasAllNullValues(allowScalar) {
      return this.items.every((node) => {
        if (!isPair(node))
          return false;
        const n = node.value;
        return n == null || allowScalar && isScalar(n) && n.value == null && !n.commentBefore && !n.comment && !n.tag;
      });
    }
    /**
     * Checks if the collection includes a value with the key `key`.
     */
    hasIn(path) {
      const [key, ...rest] = path;
      if (rest.length === 0)
        return this.has(key);
      const node = this.get(key, true);
      return isCollection(node) ? node.hasIn(rest) : false;
    }
    /**
     * Sets a value in this collection. For `!!set`, `value` needs to be a
     * boolean to add/remove the item from the set.
     */
    setIn(path, value) {
      const [key, ...rest] = path;
      if (rest.length === 0) {
        this.set(key, value);
      } else {
        const node = this.get(key, true);
        if (isCollection(node))
          node.setIn(rest, value);
        else if (node === void 0 && this.schema)
          this.set(key, collectionFromPath(this.schema, rest, value));
        else
          throw new Error(`Expected YAML collection at ${key}. Remaining path: ${rest}`);
      }
    }
  };

  // node_modules/yaml/browser/dist/stringify/stringifyComment.js
  var stringifyComment = (str) => str.replace(/^(?!$)(?: $)?/gm, "#");
  function indentComment(comment, indent) {
    if (/^\n+$/.test(comment))
      return comment.substring(1);
    return indent ? comment.replace(/^(?! *$)/gm, indent) : comment;
  }
  var lineComment = (str, indent, comment) => str.endsWith("\n") ? indentComment(comment, indent) : comment.includes("\n") ? "\n" + indentComment(comment, indent) : (str.endsWith(" ") ? "" : " ") + comment;

  // node_modules/yaml/browser/dist/stringify/foldFlowLines.js
  var FOLD_FLOW = "flow";
  var FOLD_BLOCK = "block";
  var FOLD_QUOTED = "quoted";
  function foldFlowLines(text2, indent, mode = "flow", { indentAtStart, lineWidth = 80, minContentWidth = 20, onFold, onOverflow } = {}) {
    if (!lineWidth || lineWidth < 0)
      return text2;
    if (lineWidth < minContentWidth)
      minContentWidth = 0;
    const endStep = Math.max(1 + minContentWidth, 1 + lineWidth - indent.length);
    if (text2.length <= endStep)
      return text2;
    const folds = [];
    const escapedFolds = {};
    let end = lineWidth - indent.length;
    if (typeof indentAtStart === "number") {
      if (indentAtStart > lineWidth - Math.max(2, minContentWidth))
        folds.push(0);
      else
        end = lineWidth - indentAtStart;
    }
    let split = void 0;
    let prev = void 0;
    let overflow = false;
    let i = -1;
    let escStart = -1;
    let escEnd = -1;
    if (mode === FOLD_BLOCK) {
      i = consumeMoreIndentedLines(text2, i, indent.length);
      if (i !== -1)
        end = i + endStep;
    }
    for (let ch; ch = text2[i += 1]; ) {
      if (mode === FOLD_QUOTED && ch === "\\") {
        escStart = i;
        switch (text2[i + 1]) {
          case "x":
            i += 3;
            break;
          case "u":
            i += 5;
            break;
          case "U":
            i += 9;
            break;
          default:
            i += 1;
        }
        escEnd = i;
      }
      if (ch === "\n") {
        if (mode === FOLD_BLOCK)
          i = consumeMoreIndentedLines(text2, i, indent.length);
        end = i + indent.length + endStep;
        split = void 0;
      } else {
        if (ch === " " && prev && prev !== " " && prev !== "\n" && prev !== "	") {
          const next = text2[i + 1];
          if (next && next !== " " && next !== "\n" && next !== "	")
            split = i;
        }
        if (i >= end) {
          if (split) {
            folds.push(split);
            end = split + endStep;
            split = void 0;
          } else if (mode === FOLD_QUOTED) {
            while (prev === " " || prev === "	") {
              prev = ch;
              ch = text2[i += 1];
              overflow = true;
            }
            const j = i > escEnd + 1 ? i - 2 : escStart - 1;
            if (escapedFolds[j])
              return text2;
            folds.push(j);
            escapedFolds[j] = true;
            end = j + endStep;
            split = void 0;
          } else {
            overflow = true;
          }
        }
      }
      prev = ch;
    }
    if (overflow && onOverflow)
      onOverflow();
    if (folds.length === 0)
      return text2;
    if (onFold)
      onFold();
    let res = text2.slice(0, folds[0]);
    for (let i2 = 0; i2 < folds.length; ++i2) {
      const fold = folds[i2];
      const end2 = folds[i2 + 1] || text2.length;
      if (fold === 0)
        res = `
${indent}${text2.slice(0, end2)}`;
      else {
        if (mode === FOLD_QUOTED && escapedFolds[fold])
          res += `${text2[fold]}\\`;
        res += `
${indent}${text2.slice(fold + 1, end2)}`;
      }
    }
    return res;
  }
  function consumeMoreIndentedLines(text2, i, indent) {
    let end = i;
    let start = i + 1;
    let ch = text2[start];
    while (ch === " " || ch === "	") {
      if (i < start + indent) {
        ch = text2[++i];
      } else {
        do {
          ch = text2[++i];
        } while (ch && ch !== "\n");
        end = i;
        start = i + 1;
        ch = text2[start];
      }
    }
    return end;
  }

  // node_modules/yaml/browser/dist/stringify/stringifyString.js
  var getFoldOptions = (ctx, isBlock2) => ({
    indentAtStart: isBlock2 ? ctx.indent.length : ctx.indentAtStart,
    lineWidth: ctx.options.lineWidth,
    minContentWidth: ctx.options.minContentWidth
  });
  var containsDocumentMarker = (str) => /^(%|---|\.\.\.)/m.test(str);
  function lineLengthOverLimit(str, lineWidth, indentLength) {
    if (!lineWidth || lineWidth < 0)
      return false;
    const limit = lineWidth - indentLength;
    const strLen = str.length;
    if (strLen <= limit)
      return false;
    for (let i = 0, start = 0; i < strLen; ++i) {
      if (str[i] === "\n") {
        if (i - start > limit)
          return true;
        start = i + 1;
        if (strLen - start <= limit)
          return false;
      }
    }
    return true;
  }
  function doubleQuotedString(value, ctx) {
    const json = JSON.stringify(value);
    if (ctx.options.doubleQuotedAsJSON)
      return json;
    const { implicitKey } = ctx;
    const minMultiLineLength = ctx.options.doubleQuotedMinMultiLineLength;
    const indent = ctx.indent || (containsDocumentMarker(value) ? "  " : "");
    let str = "";
    let start = 0;
    for (let i = 0, ch = json[i]; ch; ch = json[++i]) {
      if (ch === " " && json[i + 1] === "\\" && json[i + 2] === "n") {
        str += json.slice(start, i) + "\\ ";
        i += 1;
        start = i;
        ch = "\\";
      }
      if (ch === "\\")
        switch (json[i + 1]) {
          case "u":
            {
              str += json.slice(start, i);
              const code = json.substr(i + 2, 4);
              switch (code) {
                case "0000":
                  str += "\\0";
                  break;
                case "0007":
                  str += "\\a";
                  break;
                case "000b":
                  str += "\\v";
                  break;
                case "001b":
                  str += "\\e";
                  break;
                case "0085":
                  str += "\\N";
                  break;
                case "00a0":
                  str += "\\_";
                  break;
                case "2028":
                  str += "\\L";
                  break;
                case "2029":
                  str += "\\P";
                  break;
                default:
                  if (code.substr(0, 2) === "00")
                    str += "\\x" + code.substr(2);
                  else
                    str += json.substr(i, 6);
              }
              i += 5;
              start = i + 1;
            }
            break;
          case "n":
            if (implicitKey || json[i + 2] === '"' || json.length < minMultiLineLength) {
              i += 1;
            } else {
              str += json.slice(start, i) + "\n\n";
              while (json[i + 2] === "\\" && json[i + 3] === "n" && json[i + 4] !== '"') {
                str += "\n";
                i += 2;
              }
              str += indent;
              if (json[i + 2] === " ")
                str += "\\";
              i += 1;
              start = i + 1;
            }
            break;
          default:
            i += 1;
        }
    }
    str = start ? str + json.slice(start) : json;
    return implicitKey ? str : foldFlowLines(str, indent, FOLD_QUOTED, getFoldOptions(ctx, false));
  }
  function singleQuotedString(value, ctx) {
    if (ctx.options.singleQuote === false || ctx.implicitKey && value.includes("\n") || /[ \t]\n|\n[ \t]/.test(value))
      return doubleQuotedString(value, ctx);
    const indent = ctx.indent || (containsDocumentMarker(value) ? "  " : "");
    const res = "'" + value.replace(/'/g, "''").replace(/\n+/g, `$&
${indent}`) + "'";
    return ctx.implicitKey ? res : foldFlowLines(res, indent, FOLD_FLOW, getFoldOptions(ctx, false));
  }
  function quotedString(value, ctx) {
    const { singleQuote } = ctx.options;
    let qs;
    if (singleQuote === false)
      qs = doubleQuotedString;
    else {
      const hasDouble = value.includes('"');
      const hasSingle = value.includes("'");
      if (hasDouble && !hasSingle)
        qs = singleQuotedString;
      else if (hasSingle && !hasDouble)
        qs = doubleQuotedString;
      else
        qs = singleQuote ? singleQuotedString : doubleQuotedString;
    }
    return qs(value, ctx);
  }
  var blockEndNewlines;
  try {
    blockEndNewlines = new RegExp("(^|(?<!\n))\n+(?!\n|$)", "g");
  } catch {
    blockEndNewlines = /\n+(?!\n|$)/g;
  }
  function blockString({ comment, type, value }, ctx, onComment, onChompKeep) {
    const { blockQuote, commentString, lineWidth } = ctx.options;
    if (!blockQuote || /\n[\t ]+$/.test(value)) {
      return quotedString(value, ctx);
    }
    const indent = ctx.indent || (ctx.forceBlockIndent || containsDocumentMarker(value) ? "  " : "");
    const literal = blockQuote === "literal" ? true : blockQuote === "folded" || type === Scalar.BLOCK_FOLDED ? false : type === Scalar.BLOCK_LITERAL ? true : !lineLengthOverLimit(value, lineWidth, indent.length);
    if (!value)
      return literal ? "|\n" : ">\n";
    let chomp;
    let endStart;
    for (endStart = value.length; endStart > 0; --endStart) {
      const ch = value[endStart - 1];
      if (ch !== "\n" && ch !== "	" && ch !== " ")
        break;
    }
    let end = value.substring(endStart);
    const endNlPos = end.indexOf("\n");
    if (endNlPos === -1) {
      chomp = "-";
    } else if (value === end || endNlPos !== end.length - 1) {
      chomp = "+";
      if (onChompKeep)
        onChompKeep();
    } else {
      chomp = "";
    }
    if (end) {
      value = value.slice(0, -end.length);
      if (end[end.length - 1] === "\n")
        end = end.slice(0, -1);
      end = end.replace(blockEndNewlines, `$&${indent}`);
    }
    let startWithSpace = false;
    let startEnd;
    let startNlPos = -1;
    for (startEnd = 0; startEnd < value.length; ++startEnd) {
      const ch = value[startEnd];
      if (ch === " ")
        startWithSpace = true;
      else if (ch === "\n")
        startNlPos = startEnd;
      else
        break;
    }
    let start = value.substring(0, startNlPos < startEnd ? startNlPos + 1 : startEnd);
    if (start) {
      value = value.substring(start.length);
      start = start.replace(/\n+/g, `$&${indent}`);
    }
    const indentSize = indent ? "2" : "1";
    let header = (startWithSpace ? indentSize : "") + chomp;
    if (comment) {
      header += " " + commentString(comment.replace(/ ?[\r\n]+/g, " "));
      if (onComment)
        onComment();
    }
    if (!literal) {
      const foldedValue = value.replace(/\n+/g, "\n$&").replace(/(?:^|\n)([\t ].*)(?:([\n\t ]*)\n(?![\n\t ]))?/g, "$1$2").replace(/\n+/g, `$&${indent}`);
      let literalFallback = false;
      const foldOptions = getFoldOptions(ctx, true);
      if (blockQuote !== "folded" && type !== Scalar.BLOCK_FOLDED) {
        foldOptions.onOverflow = () => {
          literalFallback = true;
        };
      }
      const body = foldFlowLines(`${start}${foldedValue}${end}`, indent, FOLD_BLOCK, foldOptions);
      if (!literalFallback)
        return `>${header}
${indent}${body}`;
    }
    value = value.replace(/\n+/g, `$&${indent}`);
    return `|${header}
${indent}${start}${value}${end}`;
  }
  function plainString(item, ctx, onComment, onChompKeep) {
    const { type, value } = item;
    const { actualString, implicitKey, indent, indentStep, inFlow } = ctx;
    if (implicitKey && value.includes("\n") || inFlow && /[[\]{},]/.test(value)) {
      return quotedString(value, ctx);
    }
    if (/^[\n\t ,[\]{}#&*!|>'"%@`]|^[?-]$|^[?-][ \t]|[\n:][ \t]|[ \t]\n|[\n\t ]#|[\n\t :]$/.test(value)) {
      return implicitKey || inFlow || !value.includes("\n") ? quotedString(value, ctx) : blockString(item, ctx, onComment, onChompKeep);
    }
    if (!implicitKey && !inFlow && type !== Scalar.PLAIN && value.includes("\n")) {
      return blockString(item, ctx, onComment, onChompKeep);
    }
    if (containsDocumentMarker(value)) {
      if (indent === "") {
        ctx.forceBlockIndent = true;
        return blockString(item, ctx, onComment, onChompKeep);
      } else if (implicitKey && indent === indentStep) {
        return quotedString(value, ctx);
      }
    }
    const str = value.replace(/\n+/g, `$&
${indent}`);
    if (actualString) {
      const test = (tag) => tag.default && tag.tag !== "tag:yaml.org,2002:str" && tag.test?.test(str);
      const { compat, tags } = ctx.doc.schema;
      if (tags.some(test) || compat?.some(test))
        return quotedString(value, ctx);
    }
    return implicitKey ? str : foldFlowLines(str, indent, FOLD_FLOW, getFoldOptions(ctx, false));
  }
  function stringifyString(item, ctx, onComment, onChompKeep) {
    const { implicitKey, inFlow } = ctx;
    const ss = typeof item.value === "string" ? item : Object.assign({}, item, { value: String(item.value) });
    let { type } = item;
    if (type !== Scalar.QUOTE_DOUBLE) {
      if (/[\x00-\x08\x0b-\x1f\x7f-\x9f\u{D800}-\u{DFFF}]/u.test(ss.value))
        type = Scalar.QUOTE_DOUBLE;
    }
    const _stringify = (_type) => {
      switch (_type) {
        case Scalar.BLOCK_FOLDED:
        case Scalar.BLOCK_LITERAL:
          return implicitKey || inFlow ? quotedString(ss.value, ctx) : blockString(ss, ctx, onComment, onChompKeep);
        case Scalar.QUOTE_DOUBLE:
          return doubleQuotedString(ss.value, ctx);
        case Scalar.QUOTE_SINGLE:
          return singleQuotedString(ss.value, ctx);
        case Scalar.PLAIN:
          return plainString(ss, ctx, onComment, onChompKeep);
        default:
          return null;
      }
    };
    let res = _stringify(type);
    if (res === null) {
      const { defaultKeyType, defaultStringType } = ctx.options;
      const t = implicitKey && defaultKeyType || defaultStringType;
      res = _stringify(t);
      if (res === null)
        throw new Error(`Unsupported default string type ${t}`);
    }
    return res;
  }

  // node_modules/yaml/browser/dist/stringify/stringify.js
  function createStringifyContext(doc, options) {
    const opt = Object.assign({
      blockQuote: true,
      commentString: stringifyComment,
      defaultKeyType: null,
      defaultStringType: "PLAIN",
      directives: null,
      doubleQuotedAsJSON: false,
      doubleQuotedMinMultiLineLength: 40,
      falseStr: "false",
      flowCollectionPadding: true,
      indentSeq: true,
      lineWidth: 80,
      minContentWidth: 20,
      nullStr: "null",
      simpleKeys: false,
      singleQuote: null,
      trailingComma: false,
      trueStr: "true",
      verifyAliasOrder: true
    }, doc.schema.toStringOptions, options);
    let inFlow;
    switch (opt.collectionStyle) {
      case "block":
        inFlow = false;
        break;
      case "flow":
        inFlow = true;
        break;
      default:
        inFlow = null;
    }
    return {
      anchors: /* @__PURE__ */ new Set(),
      doc,
      flowCollectionPadding: opt.flowCollectionPadding ? " " : "",
      indent: "",
      indentStep: typeof opt.indent === "number" ? " ".repeat(opt.indent) : "  ",
      inFlow,
      options: opt
    };
  }
  function getTagObject(tags, item) {
    if (item.tag) {
      const match = tags.filter((t) => t.tag === item.tag);
      if (match.length > 0)
        return match.find((t) => t.format === item.format) ?? match[0];
    }
    let tagObj = void 0;
    let obj;
    if (isScalar(item)) {
      obj = item.value;
      let match = tags.filter((t) => t.identify?.(obj));
      if (match.length > 1) {
        const testMatch = match.filter((t) => t.test);
        if (testMatch.length > 0)
          match = testMatch;
      }
      tagObj = match.find((t) => t.format === item.format) ?? match.find((t) => !t.format);
    } else {
      obj = item;
      tagObj = tags.find((t) => t.nodeClass && obj instanceof t.nodeClass);
    }
    if (!tagObj) {
      const name = obj?.constructor?.name ?? (obj === null ? "null" : typeof obj);
      throw new Error(`Tag not resolved for ${name} value`);
    }
    return tagObj;
  }
  function stringifyProps(node, tagObj, { anchors, doc }) {
    if (!doc.directives)
      return "";
    const props = [];
    const anchor = (isScalar(node) || isCollection(node)) && node.anchor;
    if (anchor && anchorIsValid(anchor)) {
      anchors.add(anchor);
      props.push(`&${anchor}`);
    }
    const tag = node.tag ?? (tagObj.default ? null : tagObj.tag);
    if (tag)
      props.push(doc.directives.tagString(tag));
    return props.join(" ");
  }
  function stringify(item, ctx, onComment, onChompKeep) {
    if (isPair(item))
      return item.toString(ctx, onComment, onChompKeep);
    if (isAlias(item)) {
      if (ctx.doc.directives)
        return item.toString(ctx);
      if (ctx.resolvedAliases?.has(item)) {
        throw new TypeError(`Cannot stringify circular structure without alias nodes`);
      } else {
        if (ctx.resolvedAliases)
          ctx.resolvedAliases.add(item);
        else
          ctx.resolvedAliases = /* @__PURE__ */ new Set([item]);
        item = item.resolve(ctx.doc);
      }
    }
    let tagObj = void 0;
    const node = isNode(item) ? item : ctx.doc.createNode(item, { onTagObj: (o) => tagObj = o });
    tagObj ?? (tagObj = getTagObject(ctx.doc.schema.tags, node));
    const props = stringifyProps(node, tagObj, ctx);
    if (props.length > 0)
      ctx.indentAtStart = (ctx.indentAtStart ?? 0) + props.length + 1;
    const str = typeof tagObj.stringify === "function" ? tagObj.stringify(node, ctx, onComment, onChompKeep) : isScalar(node) ? stringifyString(node, ctx, onComment, onChompKeep) : node.toString(ctx, onComment, onChompKeep);
    if (!props)
      return str;
    return isScalar(node) || str[0] === "{" || str[0] === "[" ? `${props} ${str}` : `${props}
${ctx.indent}${str}`;
  }

  // node_modules/yaml/browser/dist/stringify/stringifyPair.js
  function stringifyPair({ key, value }, ctx, onComment, onChompKeep) {
    const { allNullValues, doc, indent, indentStep, options: { commentString, indentSeq, simpleKeys } } = ctx;
    let keyComment = isNode(key) && key.comment || null;
    if (simpleKeys) {
      if (keyComment) {
        throw new Error("With simple keys, key nodes cannot have comments");
      }
      if (isCollection(key) || !isNode(key) && typeof key === "object") {
        const msg = "With simple keys, collection cannot be used as a key value";
        throw new Error(msg);
      }
    }
    let explicitKey = !simpleKeys && (!key || keyComment && value == null && !ctx.inFlow || isCollection(key) || (isScalar(key) ? key.type === Scalar.BLOCK_FOLDED || key.type === Scalar.BLOCK_LITERAL : typeof key === "object"));
    ctx = Object.assign({}, ctx, {
      allNullValues: false,
      implicitKey: !explicitKey && (simpleKeys || !allNullValues),
      indent: indent + indentStep
    });
    let keyCommentDone = false;
    let chompKeep = false;
    let str = stringify(key, ctx, () => keyCommentDone = true, () => chompKeep = true);
    if (!explicitKey && !ctx.inFlow && str.length > 1024) {
      if (simpleKeys)
        throw new Error("With simple keys, single line scalar must not span more than 1024 characters");
      explicitKey = true;
    }
    if (ctx.inFlow) {
      if (allNullValues || value == null) {
        if (keyCommentDone && onComment)
          onComment();
        return str === "" ? "?" : explicitKey ? `? ${str}` : str;
      }
    } else if (allNullValues && !simpleKeys || value == null && explicitKey) {
      str = `? ${str}`;
      if (keyComment && !keyCommentDone) {
        str += lineComment(str, ctx.indent, commentString(keyComment));
      } else if (chompKeep && onChompKeep)
        onChompKeep();
      return str;
    }
    if (keyCommentDone)
      keyComment = null;
    if (explicitKey) {
      if (keyComment)
        str += lineComment(str, ctx.indent, commentString(keyComment));
      str = `? ${str}
${indent}:`;
    } else {
      str = `${str}:`;
      if (keyComment)
        str += lineComment(str, ctx.indent, commentString(keyComment));
    }
    let vsb, vcb, valueComment;
    if (isNode(value)) {
      vsb = !!value.spaceBefore;
      vcb = value.commentBefore;
      valueComment = value.comment;
    } else {
      vsb = false;
      vcb = null;
      valueComment = null;
      if (value && typeof value === "object")
        value = doc.createNode(value);
    }
    ctx.implicitKey = false;
    if (!explicitKey && !keyComment && isScalar(value))
      ctx.indentAtStart = str.length + 1;
    chompKeep = false;
    if (!indentSeq && indentStep.length >= 2 && !ctx.inFlow && !explicitKey && isSeq(value) && !value.flow && !value.tag && !value.anchor) {
      ctx.indent = ctx.indent.substring(2);
    }
    let valueCommentDone = false;
    const valueStr = stringify(value, ctx, () => valueCommentDone = true, () => chompKeep = true);
    let ws = " ";
    if (keyComment || vsb || vcb) {
      ws = vsb ? "\n" : "";
      if (vcb) {
        const cs = commentString(vcb);
        ws += `
${indentComment(cs, ctx.indent)}`;
      }
      if (valueStr === "" && !ctx.inFlow) {
        if (ws === "\n" && valueComment)
          ws = "\n\n";
      } else {
        ws += `
${ctx.indent}`;
      }
    } else if (!explicitKey && isCollection(value)) {
      const vs0 = valueStr[0];
      const nl0 = valueStr.indexOf("\n");
      const hasNewline = nl0 !== -1;
      const flow = ctx.inFlow ?? value.flow ?? value.items.length === 0;
      if (hasNewline || !flow) {
        let hasPropsLine = false;
        if (hasNewline && (vs0 === "&" || vs0 === "!")) {
          let sp0 = valueStr.indexOf(" ");
          if (vs0 === "&" && sp0 !== -1 && sp0 < nl0 && valueStr[sp0 + 1] === "!") {
            sp0 = valueStr.indexOf(" ", sp0 + 1);
          }
          if (sp0 === -1 || nl0 < sp0)
            hasPropsLine = true;
        }
        if (!hasPropsLine)
          ws = `
${ctx.indent}`;
      }
    } else if (valueStr === "" || valueStr[0] === "\n") {
      ws = "";
    }
    str += ws + valueStr;
    if (ctx.inFlow) {
      if (valueCommentDone && onComment)
        onComment();
    } else if (valueComment && !valueCommentDone) {
      str += lineComment(str, ctx.indent, commentString(valueComment));
    } else if (chompKeep && onChompKeep) {
      onChompKeep();
    }
    return str;
  }

  // node_modules/yaml/browser/dist/log.js
  function warn(logLevel, warning2) {
    if (logLevel === "debug" || logLevel === "warn") {
      console.warn(warning2);
    }
  }

  // node_modules/yaml/browser/dist/schema/yaml-1.1/merge.js
  var MERGE_KEY = "<<";
  var merge = {
    identify: (value) => value === MERGE_KEY || typeof value === "symbol" && value.description === MERGE_KEY,
    default: "key",
    tag: "tag:yaml.org,2002:merge",
    test: /^<<$/,
    resolve: () => Object.assign(new Scalar(Symbol(MERGE_KEY)), {
      addToJSMap: addMergeToJSMap
    }),
    stringify: () => MERGE_KEY
  };
  var isMergeKey = (ctx, key) => (merge.identify(key) || isScalar(key) && (!key.type || key.type === Scalar.PLAIN) && merge.identify(key.value)) && ctx?.doc.schema.tags.some((tag) => tag.tag === merge.tag && tag.default);
  function addMergeToJSMap(ctx, map2, value) {
    const source = resolveAliasValue(ctx, value);
    if (isSeq(source))
      for (const it of source.items)
        mergeValue(ctx, map2, it);
    else if (Array.isArray(source))
      for (const it of source)
        mergeValue(ctx, map2, it);
    else
      mergeValue(ctx, map2, source);
  }
  function mergeValue(ctx, map2, value) {
    const source = resolveAliasValue(ctx, value);
    if (!isMap(source))
      throw new Error("Merge sources must be maps or map aliases");
    const srcMap = source.toJSON(null, ctx, Map);
    for (const [key, value2] of srcMap) {
      if (map2 instanceof Map) {
        if (!map2.has(key))
          map2.set(key, value2);
      } else if (map2 instanceof Set) {
        map2.add(key);
      } else if (!Object.prototype.hasOwnProperty.call(map2, key)) {
        Object.defineProperty(map2, key, {
          value: value2,
          writable: true,
          enumerable: true,
          configurable: true
        });
      }
    }
    return map2;
  }
  function resolveAliasValue(ctx, value) {
    return ctx && isAlias(value) ? value.resolve(ctx.doc, ctx) : value;
  }

  // node_modules/yaml/browser/dist/nodes/addPairToJSMap.js
  function addPairToJSMap(ctx, map2, { key, value }) {
    if (isNode(key) && key.addToJSMap)
      key.addToJSMap(ctx, map2, value);
    else if (isMergeKey(ctx, key))
      addMergeToJSMap(ctx, map2, value);
    else {
      const jsKey = toJS(key, "", ctx);
      if (map2 instanceof Map) {
        map2.set(jsKey, toJS(value, jsKey, ctx));
      } else if (map2 instanceof Set) {
        map2.add(jsKey);
      } else {
        const stringKey = stringifyKey(key, jsKey, ctx);
        const jsValue = toJS(value, stringKey, ctx);
        if (stringKey in map2)
          Object.defineProperty(map2, stringKey, {
            value: jsValue,
            writable: true,
            enumerable: true,
            configurable: true
          });
        else
          map2[stringKey] = jsValue;
      }
    }
    return map2;
  }
  function stringifyKey(key, jsKey, ctx) {
    if (jsKey === null)
      return "";
    if (typeof jsKey !== "object")
      return String(jsKey);
    if (isNode(key) && ctx?.doc) {
      const strCtx = createStringifyContext(ctx.doc, {});
      strCtx.anchors = /* @__PURE__ */ new Set();
      for (const node of ctx.anchors.keys())
        strCtx.anchors.add(node.anchor);
      strCtx.inFlow = true;
      strCtx.inStringifyKey = true;
      const strKey = key.toString(strCtx);
      if (!ctx.mapKeyWarned) {
        let jsonStr = JSON.stringify(strKey);
        if (jsonStr.length > 40)
          jsonStr = jsonStr.substring(0, 36) + '..."';
        warn(ctx.doc.options.logLevel, `Keys with collection values will be stringified due to JS Object restrictions: ${jsonStr}. Set mapAsMap: true to use object keys.`);
        ctx.mapKeyWarned = true;
      }
      return strKey;
    }
    return JSON.stringify(jsKey);
  }

  // node_modules/yaml/browser/dist/nodes/Pair.js
  function createPair(key, value, ctx) {
    const k = createNode(key, void 0, ctx);
    const v = createNode(value, void 0, ctx);
    return new Pair(k, v);
  }
  var Pair = class _Pair {
    constructor(key, value = null) {
      Object.defineProperty(this, NODE_TYPE, { value: PAIR });
      this.key = key;
      this.value = value;
    }
    clone(schema4) {
      let { key, value } = this;
      if (isNode(key))
        key = key.clone(schema4);
      if (isNode(value))
        value = value.clone(schema4);
      return new _Pair(key, value);
    }
    toJSON(_, ctx) {
      const pair = ctx?.mapAsMap ? /* @__PURE__ */ new Map() : {};
      return addPairToJSMap(ctx, pair, this);
    }
    toString(ctx, onComment, onChompKeep) {
      return ctx?.doc ? stringifyPair(this, ctx, onComment, onChompKeep) : JSON.stringify(this);
    }
  };

  // node_modules/yaml/browser/dist/stringify/stringifyCollection.js
  function stringifyCollection(collection, ctx, options) {
    const flow = ctx.inFlow ?? collection.flow;
    const stringify4 = flow ? stringifyFlowCollection : stringifyBlockCollection;
    return stringify4(collection, ctx, options);
  }
  function stringifyBlockCollection({ comment, items }, ctx, { blockItemPrefix, flowChars, itemIndent, onChompKeep, onComment }) {
    const { indent, options: { commentString } } = ctx;
    const itemCtx = Object.assign({}, ctx, { indent: itemIndent, type: null });
    let chompKeep = false;
    const lines = [];
    for (let i = 0; i < items.length; ++i) {
      const item = items[i];
      let comment2 = null;
      if (isNode(item)) {
        if (!chompKeep && item.spaceBefore)
          lines.push("");
        addCommentBefore(ctx, lines, item.commentBefore, chompKeep);
        if (item.comment)
          comment2 = item.comment;
      } else if (isPair(item)) {
        const ik = isNode(item.key) ? item.key : null;
        if (ik) {
          if (!chompKeep && ik.spaceBefore)
            lines.push("");
          addCommentBefore(ctx, lines, ik.commentBefore, chompKeep);
        }
      }
      chompKeep = false;
      let str2 = stringify(item, itemCtx, () => comment2 = null, () => chompKeep = true);
      if (comment2)
        str2 += lineComment(str2, itemIndent, commentString(comment2));
      if (chompKeep && comment2)
        chompKeep = false;
      lines.push(blockItemPrefix + str2);
    }
    let str;
    if (lines.length === 0) {
      str = flowChars.start + flowChars.end;
    } else {
      str = lines[0];
      for (let i = 1; i < lines.length; ++i) {
        const line = lines[i];
        str += line ? `
${indent}${line}` : "\n";
      }
    }
    if (comment) {
      str += "\n" + indentComment(commentString(comment), indent);
      if (onComment)
        onComment();
    } else if (chompKeep && onChompKeep)
      onChompKeep();
    return str;
  }
  function stringifyFlowCollection({ items }, ctx, { flowChars, itemIndent }) {
    const { indent, indentStep, flowCollectionPadding: fcPadding, options: { commentString } } = ctx;
    itemIndent += indentStep;
    const itemCtx = Object.assign({}, ctx, {
      indent: itemIndent,
      inFlow: true,
      type: null
    });
    let reqNewline = false;
    let linesAtValue = 0;
    const lines = [];
    for (let i = 0; i < items.length; ++i) {
      const item = items[i];
      let comment = null;
      if (isNode(item)) {
        if (item.spaceBefore)
          lines.push("");
        addCommentBefore(ctx, lines, item.commentBefore, false);
        if (item.comment)
          comment = item.comment;
      } else if (isPair(item)) {
        const ik = isNode(item.key) ? item.key : null;
        if (ik) {
          if (ik.spaceBefore)
            lines.push("");
          addCommentBefore(ctx, lines, ik.commentBefore, false);
          if (ik.comment)
            reqNewline = true;
        }
        const iv = isNode(item.value) ? item.value : null;
        if (iv) {
          if (iv.comment)
            comment = iv.comment;
          if (iv.commentBefore)
            reqNewline = true;
        } else if (item.value == null && ik?.comment) {
          comment = ik.comment;
        }
      }
      if (comment)
        reqNewline = true;
      let str = stringify(item, itemCtx, () => comment = null);
      reqNewline || (reqNewline = lines.length > linesAtValue || str.includes("\n"));
      if (i < items.length - 1) {
        str += ",";
      } else if (ctx.options.trailingComma) {
        if (ctx.options.lineWidth > 0) {
          reqNewline || (reqNewline = lines.reduce((sum, line) => sum + line.length + 2, 2) + (str.length + 2) > ctx.options.lineWidth);
        }
        if (reqNewline) {
          str += ",";
        }
      }
      if (comment)
        str += lineComment(str, itemIndent, commentString(comment));
      lines.push(str);
      linesAtValue = lines.length;
    }
    const { start, end } = flowChars;
    if (lines.length === 0) {
      return start + end;
    } else {
      if (!reqNewline) {
        const len = lines.reduce((sum, line) => sum + line.length + 2, 2);
        reqNewline = ctx.options.lineWidth > 0 && len > ctx.options.lineWidth;
      }
      if (reqNewline) {
        let str = start;
        for (const line of lines)
          str += line ? `
${indentStep}${indent}${line}` : "\n";
        return `${str}
${indent}${end}`;
      } else {
        return `${start}${fcPadding}${lines.join(" ")}${fcPadding}${end}`;
      }
    }
  }
  function addCommentBefore({ indent, options: { commentString } }, lines, comment, chompKeep) {
    if (comment && chompKeep)
      comment = comment.replace(/^\n+/, "");
    if (comment) {
      const ic = indentComment(commentString(comment), indent);
      lines.push(ic.trimStart());
    }
  }

  // node_modules/yaml/browser/dist/nodes/YAMLMap.js
  function findPair(items, key) {
    const k = isScalar(key) ? key.value : key;
    for (const it of items) {
      if (isPair(it)) {
        if (it.key === key || it.key === k)
          return it;
        if (isScalar(it.key) && it.key.value === k)
          return it;
      }
    }
    return void 0;
  }
  var YAMLMap = class extends Collection {
    static get tagName() {
      return "tag:yaml.org,2002:map";
    }
    constructor(schema4) {
      super(MAP, schema4);
      this.items = [];
    }
    /**
     * A generic collection parsing method that can be extended
     * to other node classes that inherit from YAMLMap
     */
    static from(schema4, obj, ctx) {
      const { keepUndefined, replacer } = ctx;
      const map2 = new this(schema4);
      const add2 = (key, value) => {
        if (typeof replacer === "function")
          value = replacer.call(obj, key, value);
        else if (Array.isArray(replacer) && !replacer.includes(key))
          return;
        if (value !== void 0 || keepUndefined)
          map2.items.push(createPair(key, value, ctx));
      };
      if (obj instanceof Map) {
        for (const [key, value] of obj)
          add2(key, value);
      } else if (obj && typeof obj === "object") {
        for (const key of Object.keys(obj))
          add2(key, obj[key]);
      }
      if (typeof schema4.sortMapEntries === "function") {
        map2.items.sort(schema4.sortMapEntries);
      }
      return map2;
    }
    /**
     * Adds a value to the collection.
     *
     * @param overwrite - If not set `true`, using a key that is already in the
     *   collection will throw. Otherwise, overwrites the previous value.
     */
    add(pair, overwrite) {
      let _pair;
      if (isPair(pair))
        _pair = pair;
      else if (!pair || typeof pair !== "object" || !("key" in pair)) {
        _pair = new Pair(pair, pair?.value);
      } else
        _pair = new Pair(pair.key, pair.value);
      const prev = findPair(this.items, _pair.key);
      const sortEntries = this.schema?.sortMapEntries;
      if (prev) {
        if (!overwrite)
          throw new Error(`Key ${_pair.key} already set`);
        if (isScalar(prev.value) && isScalarValue(_pair.value))
          prev.value.value = _pair.value;
        else
          prev.value = _pair.value;
      } else if (sortEntries) {
        const i = this.items.findIndex((item) => sortEntries(_pair, item) < 0);
        if (i === -1)
          this.items.push(_pair);
        else
          this.items.splice(i, 0, _pair);
      } else {
        this.items.push(_pair);
      }
    }
    delete(key) {
      const it = findPair(this.items, key);
      if (!it)
        return false;
      const del = this.items.splice(this.items.indexOf(it), 1);
      return del.length > 0;
    }
    get(key, keepScalar) {
      const it = findPair(this.items, key);
      const node = it?.value;
      return (!keepScalar && isScalar(node) ? node.value : node) ?? void 0;
    }
    has(key) {
      return !!findPair(this.items, key);
    }
    set(key, value) {
      this.add(new Pair(key, value), true);
    }
    /**
     * @param ctx - Conversion context, originally set in Document#toJS()
     * @param {Class} Type - If set, forces the returned collection type
     * @returns Instance of Type, Map, or Object
     */
    toJSON(_, ctx, Type) {
      const map2 = Type ? new Type() : ctx?.mapAsMap ? /* @__PURE__ */ new Map() : {};
      if (ctx?.onCreate)
        ctx.onCreate(map2);
      for (const item of this.items)
        addPairToJSMap(ctx, map2, item);
      return map2;
    }
    toString(ctx, onComment, onChompKeep) {
      if (!ctx)
        return JSON.stringify(this);
      for (const item of this.items) {
        if (!isPair(item))
          throw new Error(`Map items must all be pairs; found ${JSON.stringify(item)} instead`);
      }
      if (!ctx.allNullValues && this.hasAllNullValues(false))
        ctx = Object.assign({}, ctx, { allNullValues: true });
      return stringifyCollection(this, ctx, {
        blockItemPrefix: "",
        flowChars: { start: "{", end: "}" },
        itemIndent: ctx.indent || "",
        onChompKeep,
        onComment
      });
    }
  };

  // node_modules/yaml/browser/dist/schema/common/map.js
  var map = {
    collection: "map",
    default: true,
    nodeClass: YAMLMap,
    tag: "tag:yaml.org,2002:map",
    resolve(map2, onError) {
      if (!isMap(map2))
        onError("Expected a mapping for this tag");
      return map2;
    },
    createNode: (schema4, obj, ctx) => YAMLMap.from(schema4, obj, ctx)
  };

  // node_modules/yaml/browser/dist/nodes/YAMLSeq.js
  var YAMLSeq = class extends Collection {
    static get tagName() {
      return "tag:yaml.org,2002:seq";
    }
    constructor(schema4) {
      super(SEQ, schema4);
      this.items = [];
    }
    add(value) {
      this.items.push(value);
    }
    /**
     * Removes a value from the collection.
     *
     * `key` must contain a representation of an integer for this to succeed.
     * It may be wrapped in a `Scalar`.
     *
     * @returns `true` if the item was found and removed.
     */
    delete(key) {
      const idx = asItemIndex(key);
      if (typeof idx !== "number")
        return false;
      const del = this.items.splice(idx, 1);
      return del.length > 0;
    }
    get(key, keepScalar) {
      const idx = asItemIndex(key);
      if (typeof idx !== "number")
        return void 0;
      const it = this.items[idx];
      return !keepScalar && isScalar(it) ? it.value : it;
    }
    /**
     * Checks if the collection includes a value with the key `key`.
     *
     * `key` must contain a representation of an integer for this to succeed.
     * It may be wrapped in a `Scalar`.
     */
    has(key) {
      const idx = asItemIndex(key);
      return typeof idx === "number" && idx < this.items.length;
    }
    /**
     * Sets a value in this collection. For `!!set`, `value` needs to be a
     * boolean to add/remove the item from the set.
     *
     * If `key` does not contain a representation of an integer, this will throw.
     * It may be wrapped in a `Scalar`.
     */
    set(key, value) {
      const idx = asItemIndex(key);
      if (typeof idx !== "number")
        throw new Error(`Expected a valid index, not ${key}.`);
      const prev = this.items[idx];
      if (isScalar(prev) && isScalarValue(value))
        prev.value = value;
      else
        this.items[idx] = value;
    }
    toJSON(_, ctx) {
      const seq2 = [];
      if (ctx?.onCreate)
        ctx.onCreate(seq2);
      let i = 0;
      for (const item of this.items)
        seq2.push(toJS(item, String(i++), ctx));
      return seq2;
    }
    toString(ctx, onComment, onChompKeep) {
      if (!ctx)
        return JSON.stringify(this);
      return stringifyCollection(this, ctx, {
        blockItemPrefix: "- ",
        flowChars: { start: "[", end: "]" },
        itemIndent: (ctx.indent || "") + "  ",
        onChompKeep,
        onComment
      });
    }
    static from(schema4, obj, ctx) {
      const { replacer } = ctx;
      const seq2 = new this(schema4);
      if (obj && Symbol.iterator in Object(obj)) {
        let i = 0;
        for (let it of obj) {
          if (typeof replacer === "function") {
            const key = obj instanceof Set ? it : String(i++);
            it = replacer.call(obj, key, it);
          }
          seq2.items.push(createNode(it, void 0, ctx));
        }
      }
      return seq2;
    }
  };
  function asItemIndex(key) {
    let idx = isScalar(key) ? key.value : key;
    if (idx && typeof idx === "string")
      idx = Number(idx);
    return typeof idx === "number" && Number.isInteger(idx) && idx >= 0 ? idx : null;
  }

  // node_modules/yaml/browser/dist/schema/common/seq.js
  var seq = {
    collection: "seq",
    default: true,
    nodeClass: YAMLSeq,
    tag: "tag:yaml.org,2002:seq",
    resolve(seq2, onError) {
      if (!isSeq(seq2))
        onError("Expected a sequence for this tag");
      return seq2;
    },
    createNode: (schema4, obj, ctx) => YAMLSeq.from(schema4, obj, ctx)
  };

  // node_modules/yaml/browser/dist/schema/common/string.js
  var string = {
    identify: (value) => typeof value === "string",
    default: true,
    tag: "tag:yaml.org,2002:str",
    resolve: (str) => str,
    stringify(item, ctx, onComment, onChompKeep) {
      ctx = Object.assign({ actualString: true }, ctx);
      return stringifyString(item, ctx, onComment, onChompKeep);
    }
  };

  // node_modules/yaml/browser/dist/schema/common/null.js
  var nullTag = {
    identify: (value) => value == null,
    createNode: () => new Scalar(null),
    default: true,
    tag: "tag:yaml.org,2002:null",
    test: /^(?:~|[Nn]ull|NULL)?$/,
    resolve: () => new Scalar(null),
    stringify: ({ source }, ctx) => typeof source === "string" && nullTag.test.test(source) ? source : ctx.options.nullStr
  };

  // node_modules/yaml/browser/dist/schema/core/bool.js
  var boolTag = {
    identify: (value) => typeof value === "boolean",
    default: true,
    tag: "tag:yaml.org,2002:bool",
    test: /^(?:[Tt]rue|TRUE|[Ff]alse|FALSE)$/,
    resolve: (str) => new Scalar(str[0] === "t" || str[0] === "T"),
    stringify({ source, value }, ctx) {
      if (source && boolTag.test.test(source)) {
        const sv = source[0] === "t" || source[0] === "T";
        if (value === sv)
          return source;
      }
      return value ? ctx.options.trueStr : ctx.options.falseStr;
    }
  };

  // node_modules/yaml/browser/dist/stringify/stringifyNumber.js
  function stringifyNumber({ format, minFractionDigits, tag, value }) {
    if (typeof value === "bigint")
      return String(value);
    const num = typeof value === "number" ? value : Number(value);
    if (!isFinite(num))
      return isNaN(num) ? ".nan" : num < 0 ? "-.inf" : ".inf";
    let n = Object.is(value, -0) ? "-0" : JSON.stringify(value);
    if (!format && minFractionDigits && (!tag || tag === "tag:yaml.org,2002:float") && /^-?\d/.test(n) && !n.includes("e")) {
      let i = n.indexOf(".");
      if (i < 0) {
        i = n.length;
        n += ".";
      }
      let d = minFractionDigits - (n.length - i - 1);
      while (d-- > 0)
        n += "0";
    }
    return n;
  }

  // node_modules/yaml/browser/dist/schema/core/float.js
  var floatNaN = {
    identify: (value) => typeof value === "number",
    default: true,
    tag: "tag:yaml.org,2002:float",
    test: /^(?:[-+]?\.(?:inf|Inf|INF)|\.nan|\.NaN|\.NAN)$/,
    resolve: (str) => str.slice(-3).toLowerCase() === "nan" ? NaN : str[0] === "-" ? Number.NEGATIVE_INFINITY : Number.POSITIVE_INFINITY,
    stringify: stringifyNumber
  };
  var floatExp = {
    identify: (value) => typeof value === "number",
    default: true,
    tag: "tag:yaml.org,2002:float",
    format: "EXP",
    test: /^[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)[eE][-+]?[0-9]+$/,
    resolve: (str) => parseFloat(str),
    stringify(node) {
      const num = Number(node.value);
      return isFinite(num) ? num.toExponential() : stringifyNumber(node);
    }
  };
  var float = {
    identify: (value) => typeof value === "number",
    default: true,
    tag: "tag:yaml.org,2002:float",
    test: /^[-+]?(?:\.[0-9]+|[0-9]+\.[0-9]*)$/,
    resolve(str) {
      const node = new Scalar(parseFloat(str));
      const dot = str.indexOf(".");
      if (dot !== -1 && str[str.length - 1] === "0")
        node.minFractionDigits = str.length - dot - 1;
      return node;
    },
    stringify: stringifyNumber
  };

  // node_modules/yaml/browser/dist/schema/core/int.js
  var intIdentify = (value) => typeof value === "bigint" || Number.isInteger(value);
  var intResolve = (str, offset, radix, { intAsBigInt }) => intAsBigInt ? BigInt(str) : parseInt(str.substring(offset), radix);
  function intStringify(node, radix, prefix) {
    const { value } = node;
    if (intIdentify(value) && value >= 0)
      return prefix + value.toString(radix);
    return stringifyNumber(node);
  }
  var intOct = {
    identify: (value) => intIdentify(value) && value >= 0,
    default: true,
    tag: "tag:yaml.org,2002:int",
    format: "OCT",
    test: /^0o[0-7]+$/,
    resolve: (str, _onError, opt) => intResolve(str, 2, 8, opt),
    stringify: (node) => intStringify(node, 8, "0o")
  };
  var int = {
    identify: intIdentify,
    default: true,
    tag: "tag:yaml.org,2002:int",
    test: /^[-+]?[0-9]+$/,
    resolve: (str, _onError, opt) => intResolve(str, 0, 10, opt),
    stringify: stringifyNumber
  };
  var intHex = {
    identify: (value) => intIdentify(value) && value >= 0,
    default: true,
    tag: "tag:yaml.org,2002:int",
    format: "HEX",
    test: /^0x[0-9a-fA-F]+$/,
    resolve: (str, _onError, opt) => intResolve(str, 2, 16, opt),
    stringify: (node) => intStringify(node, 16, "0x")
  };

  // node_modules/yaml/browser/dist/schema/core/schema.js
  var schema = [
    map,
    seq,
    string,
    nullTag,
    boolTag,
    intOct,
    int,
    intHex,
    floatNaN,
    floatExp,
    float
  ];

  // node_modules/yaml/browser/dist/schema/json/schema.js
  function intIdentify2(value) {
    return typeof value === "bigint" || Number.isInteger(value);
  }
  var stringifyJSON = ({ value }) => JSON.stringify(value);
  var jsonScalars = [
    {
      identify: (value) => typeof value === "string",
      default: true,
      tag: "tag:yaml.org,2002:str",
      resolve: (str) => str,
      stringify: stringifyJSON
    },
    {
      identify: (value) => value == null,
      createNode: () => new Scalar(null),
      default: true,
      tag: "tag:yaml.org,2002:null",
      test: /^null$/,
      resolve: () => null,
      stringify: stringifyJSON
    },
    {
      identify: (value) => typeof value === "boolean",
      default: true,
      tag: "tag:yaml.org,2002:bool",
      test: /^true$|^false$/,
      resolve: (str) => str === "true",
      stringify: stringifyJSON
    },
    {
      identify: intIdentify2,
      default: true,
      tag: "tag:yaml.org,2002:int",
      test: /^-?(?:0|[1-9][0-9]*)$/,
      resolve: (str, _onError, { intAsBigInt }) => intAsBigInt ? BigInt(str) : parseInt(str, 10),
      stringify: ({ value }) => intIdentify2(value) ? value.toString() : JSON.stringify(value)
    },
    {
      identify: (value) => typeof value === "number",
      default: true,
      tag: "tag:yaml.org,2002:float",
      test: /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]*)?(?:[eE][-+]?[0-9]+)?$/,
      resolve: (str) => parseFloat(str),
      stringify: stringifyJSON
    }
  ];
  var jsonError = {
    default: true,
    tag: "",
    test: /^/,
    resolve(str, onError) {
      onError(`Unresolved plain scalar ${JSON.stringify(str)}`);
      return str;
    }
  };
  var schema2 = [map, seq].concat(jsonScalars, jsonError);

  // node_modules/yaml/browser/dist/schema/yaml-1.1/binary.js
  var binary = {
    identify: (value) => value instanceof Uint8Array,
    // Buffer inherits from Uint8Array
    default: false,
    tag: "tag:yaml.org,2002:binary",
    /**
     * Returns a Buffer in node and an Uint8Array in browsers
     *
     * To use the resulting buffer as an image, you'll want to do something like:
     *
     *   const blob = new Blob([buffer], { type: 'image/jpeg' })
     *   document.querySelector('#photo').src = URL.createObjectURL(blob)
     */
    resolve(src, onError) {
      if (typeof atob === "function") {
        const str = atob(src.replace(/[\n\r]/g, ""));
        const buffer = new Uint8Array(str.length);
        for (let i = 0; i < str.length; ++i)
          buffer[i] = str.charCodeAt(i);
        return buffer;
      } else {
        onError("This environment does not support reading binary tags; either Buffer or atob is required");
        return src;
      }
    },
    stringify({ comment, type, value }, ctx, onComment, onChompKeep) {
      if (!value)
        return "";
      const buf = value;
      let str;
      if (typeof btoa === "function") {
        let s = "";
        for (let i = 0; i < buf.length; ++i)
          s += String.fromCharCode(buf[i]);
        str = btoa(s);
      } else {
        throw new Error("This environment does not support writing binary tags; either Buffer or btoa is required");
      }
      type ?? (type = Scalar.BLOCK_LITERAL);
      if (type !== Scalar.QUOTE_DOUBLE) {
        const lineWidth = Math.max(ctx.options.lineWidth - ctx.indent.length, ctx.options.minContentWidth);
        const n = Math.ceil(str.length / lineWidth);
        const lines = new Array(n);
        for (let i = 0, o = 0; i < n; ++i, o += lineWidth) {
          lines[i] = str.substr(o, lineWidth);
        }
        str = lines.join(type === Scalar.BLOCK_LITERAL ? "\n" : " ");
      }
      return stringifyString({ comment, type, value: str }, ctx, onComment, onChompKeep);
    }
  };

  // node_modules/yaml/browser/dist/schema/yaml-1.1/pairs.js
  function resolvePairs(seq2, onError) {
    if (isSeq(seq2)) {
      for (let i = 0; i < seq2.items.length; ++i) {
        let item = seq2.items[i];
        if (isPair(item))
          continue;
        else if (isMap(item)) {
          if (item.items.length > 1)
            onError("Each pair must have its own sequence indicator");
          const pair = item.items[0] || new Pair(new Scalar(null));
          if (item.commentBefore)
            pair.key.commentBefore = pair.key.commentBefore ? `${item.commentBefore}
${pair.key.commentBefore}` : item.commentBefore;
          if (item.comment) {
            const cn = pair.value ?? pair.key;
            cn.comment = cn.comment ? `${item.comment}
${cn.comment}` : item.comment;
          }
          item = pair;
        }
        seq2.items[i] = isPair(item) ? item : new Pair(item);
      }
    } else
      onError("Expected a sequence for this tag");
    return seq2;
  }
  function createPairs(schema4, iterable, ctx) {
    const { replacer } = ctx;
    const pairs2 = new YAMLSeq(schema4);
    pairs2.tag = "tag:yaml.org,2002:pairs";
    let i = 0;
    if (iterable && Symbol.iterator in Object(iterable))
      for (let it of iterable) {
        if (typeof replacer === "function")
          it = replacer.call(iterable, String(i++), it);
        let key, value;
        if (Array.isArray(it)) {
          if (it.length === 2) {
            key = it[0];
            value = it[1];
          } else
            throw new TypeError(`Expected [key, value] tuple: ${it}`);
        } else if (it && it instanceof Object) {
          const keys = Object.keys(it);
          if (keys.length === 1) {
            key = keys[0];
            value = it[key];
          } else {
            throw new TypeError(`Expected tuple with one key, not ${keys.length} keys`);
          }
        } else {
          key = it;
        }
        pairs2.items.push(createPair(key, value, ctx));
      }
    return pairs2;
  }
  var pairs = {
    collection: "seq",
    default: false,
    tag: "tag:yaml.org,2002:pairs",
    resolve: resolvePairs,
    createNode: createPairs
  };

  // node_modules/yaml/browser/dist/schema/yaml-1.1/omap.js
  var YAMLOMap = class _YAMLOMap extends YAMLSeq {
    constructor() {
      super();
      this.add = YAMLMap.prototype.add.bind(this);
      this.delete = YAMLMap.prototype.delete.bind(this);
      this.get = YAMLMap.prototype.get.bind(this);
      this.has = YAMLMap.prototype.has.bind(this);
      this.set = YAMLMap.prototype.set.bind(this);
      this.tag = _YAMLOMap.tag;
    }
    /**
     * If `ctx` is given, the return type is actually `Map<unknown, unknown>`,
     * but TypeScript won't allow widening the signature of a child method.
     */
    toJSON(_, ctx) {
      if (!ctx)
        return super.toJSON(_);
      const map2 = /* @__PURE__ */ new Map();
      if (ctx?.onCreate)
        ctx.onCreate(map2);
      for (const pair of this.items) {
        let key, value;
        if (isPair(pair)) {
          key = toJS(pair.key, "", ctx);
          value = toJS(pair.value, key, ctx);
        } else {
          key = toJS(pair, "", ctx);
        }
        if (map2.has(key))
          throw new Error("Ordered maps must not include duplicate keys");
        map2.set(key, value);
      }
      return map2;
    }
    static from(schema4, iterable, ctx) {
      const pairs2 = createPairs(schema4, iterable, ctx);
      const omap2 = new this();
      omap2.items = pairs2.items;
      return omap2;
    }
  };
  YAMLOMap.tag = "tag:yaml.org,2002:omap";
  var omap = {
    collection: "seq",
    identify: (value) => value instanceof Map,
    nodeClass: YAMLOMap,
    default: false,
    tag: "tag:yaml.org,2002:omap",
    resolve(seq2, onError) {
      const pairs2 = resolvePairs(seq2, onError);
      const seenKeys = [];
      for (const { key } of pairs2.items) {
        if (isScalar(key)) {
          if (seenKeys.includes(key.value)) {
            onError(`Ordered maps must not include duplicate keys: ${key.value}`);
          } else {
            seenKeys.push(key.value);
          }
        }
      }
      return Object.assign(new YAMLOMap(), pairs2);
    },
    createNode: (schema4, iterable, ctx) => YAMLOMap.from(schema4, iterable, ctx)
  };

  // node_modules/yaml/browser/dist/schema/yaml-1.1/bool.js
  function boolStringify({ value, source }, ctx) {
    const boolObj = value ? trueTag : falseTag;
    if (source && boolObj.test.test(source))
      return source;
    return value ? ctx.options.trueStr : ctx.options.falseStr;
  }
  var trueTag = {
    identify: (value) => value === true,
    default: true,
    tag: "tag:yaml.org,2002:bool",
    test: /^(?:Y|y|[Yy]es|YES|[Tt]rue|TRUE|[Oo]n|ON)$/,
    resolve: () => new Scalar(true),
    stringify: boolStringify
  };
  var falseTag = {
    identify: (value) => value === false,
    default: true,
    tag: "tag:yaml.org,2002:bool",
    test: /^(?:N|n|[Nn]o|NO|[Ff]alse|FALSE|[Oo]ff|OFF)$/,
    resolve: () => new Scalar(false),
    stringify: boolStringify
  };

  // node_modules/yaml/browser/dist/schema/yaml-1.1/float.js
  var floatNaN2 = {
    identify: (value) => typeof value === "number",
    default: true,
    tag: "tag:yaml.org,2002:float",
    test: /^(?:[-+]?\.(?:inf|Inf|INF)|\.nan|\.NaN|\.NAN)$/,
    resolve: (str) => str.slice(-3).toLowerCase() === "nan" ? NaN : str[0] === "-" ? Number.NEGATIVE_INFINITY : Number.POSITIVE_INFINITY,
    stringify: stringifyNumber
  };
  var floatExp2 = {
    identify: (value) => typeof value === "number",
    default: true,
    tag: "tag:yaml.org,2002:float",
    format: "EXP",
    test: /^[-+]?(?:[0-9][0-9_]*)?(?:\.[0-9_]*)?[eE][-+]?[0-9]+$/,
    resolve: (str) => parseFloat(str.replace(/_/g, "")),
    stringify(node) {
      const num = Number(node.value);
      return isFinite(num) ? num.toExponential() : stringifyNumber(node);
    }
  };
  var float2 = {
    identify: (value) => typeof value === "number",
    default: true,
    tag: "tag:yaml.org,2002:float",
    test: /^[-+]?(?:[0-9][0-9_]*)?\.[0-9_]*$/,
    resolve(str) {
      const node = new Scalar(parseFloat(str.replace(/_/g, "")));
      const dot = str.indexOf(".");
      if (dot !== -1) {
        const f = str.substring(dot + 1).replace(/_/g, "");
        if (f[f.length - 1] === "0")
          node.minFractionDigits = f.length;
      }
      return node;
    },
    stringify: stringifyNumber
  };

  // node_modules/yaml/browser/dist/schema/yaml-1.1/int.js
  var intIdentify3 = (value) => typeof value === "bigint" || Number.isInteger(value);
  function intResolve2(str, offset, radix, { intAsBigInt }) {
    const sign = str[0];
    if (sign === "-" || sign === "+")
      offset += 1;
    str = str.substring(offset).replace(/_/g, "");
    if (intAsBigInt) {
      switch (radix) {
        case 2:
          str = `0b${str}`;
          break;
        case 8:
          str = `0o${str}`;
          break;
        case 16:
          str = `0x${str}`;
          break;
      }
      const n2 = BigInt(str);
      return sign === "-" ? BigInt(-1) * n2 : n2;
    }
    const n = parseInt(str, radix);
    return sign === "-" ? -1 * n : n;
  }
  function intStringify2(node, radix, prefix) {
    const { value } = node;
    if (intIdentify3(value)) {
      const str = value.toString(radix);
      return value < 0 ? "-" + prefix + str.substr(1) : prefix + str;
    }
    return stringifyNumber(node);
  }
  var intBin = {
    identify: intIdentify3,
    default: true,
    tag: "tag:yaml.org,2002:int",
    format: "BIN",
    test: /^[-+]?0b[0-1_]+$/,
    resolve: (str, _onError, opt) => intResolve2(str, 2, 2, opt),
    stringify: (node) => intStringify2(node, 2, "0b")
  };
  var intOct2 = {
    identify: intIdentify3,
    default: true,
    tag: "tag:yaml.org,2002:int",
    format: "OCT",
    test: /^[-+]?0[0-7_]+$/,
    resolve: (str, _onError, opt) => intResolve2(str, 1, 8, opt),
    stringify: (node) => intStringify2(node, 8, "0")
  };
  var int2 = {
    identify: intIdentify3,
    default: true,
    tag: "tag:yaml.org,2002:int",
    test: /^[-+]?[0-9][0-9_]*$/,
    resolve: (str, _onError, opt) => intResolve2(str, 0, 10, opt),
    stringify: stringifyNumber
  };
  var intHex2 = {
    identify: intIdentify3,
    default: true,
    tag: "tag:yaml.org,2002:int",
    format: "HEX",
    test: /^[-+]?0x[0-9a-fA-F_]+$/,
    resolve: (str, _onError, opt) => intResolve2(str, 2, 16, opt),
    stringify: (node) => intStringify2(node, 16, "0x")
  };

  // node_modules/yaml/browser/dist/schema/yaml-1.1/set.js
  var YAMLSet = class _YAMLSet extends YAMLMap {
    constructor(schema4) {
      super(schema4);
      this.tag = _YAMLSet.tag;
    }
    add(key) {
      let pair;
      if (isPair(key))
        pair = key;
      else if (key && typeof key === "object" && "key" in key && "value" in key && key.value === null)
        pair = new Pair(key.key, null);
      else
        pair = new Pair(key, null);
      const prev = findPair(this.items, pair.key);
      if (!prev)
        this.items.push(pair);
    }
    /**
     * If `keepPair` is `true`, returns the Pair matching `key`.
     * Otherwise, returns the value of that Pair's key.
     */
    get(key, keepPair) {
      const pair = findPair(this.items, key);
      return !keepPair && isPair(pair) ? isScalar(pair.key) ? pair.key.value : pair.key : pair;
    }
    set(key, value) {
      if (typeof value !== "boolean")
        throw new Error(`Expected boolean value for set(key, value) in a YAML set, not ${typeof value}`);
      const prev = findPair(this.items, key);
      if (prev && !value) {
        this.items.splice(this.items.indexOf(prev), 1);
      } else if (!prev && value) {
        this.items.push(new Pair(key));
      }
    }
    toJSON(_, ctx) {
      return super.toJSON(_, ctx, Set);
    }
    toString(ctx, onComment, onChompKeep) {
      if (!ctx)
        return JSON.stringify(this);
      if (this.hasAllNullValues(true))
        return super.toString(Object.assign({}, ctx, { allNullValues: true }), onComment, onChompKeep);
      else
        throw new Error("Set items must all have null values");
    }
    static from(schema4, iterable, ctx) {
      const { replacer } = ctx;
      const set2 = new this(schema4);
      if (iterable && Symbol.iterator in Object(iterable))
        for (let value of iterable) {
          if (typeof replacer === "function")
            value = replacer.call(iterable, value, value);
          set2.items.push(createPair(value, null, ctx));
        }
      return set2;
    }
  };
  YAMLSet.tag = "tag:yaml.org,2002:set";
  var set = {
    collection: "map",
    identify: (value) => value instanceof Set,
    nodeClass: YAMLSet,
    default: false,
    tag: "tag:yaml.org,2002:set",
    createNode: (schema4, iterable, ctx) => YAMLSet.from(schema4, iterable, ctx),
    resolve(map2, onError) {
      if (isMap(map2)) {
        if (map2.hasAllNullValues(true))
          return Object.assign(new YAMLSet(), map2);
        else
          onError("Set items must all have null values");
      } else
        onError("Expected a mapping for this tag");
      return map2;
    }
  };

  // node_modules/yaml/browser/dist/schema/yaml-1.1/timestamp.js
  function parseSexagesimal(str, asBigInt) {
    const sign = str[0];
    const parts = sign === "-" || sign === "+" ? str.substring(1) : str;
    const num = (n) => asBigInt ? BigInt(n) : Number(n);
    const res = parts.replace(/_/g, "").split(":").reduce((res2, p) => res2 * num(60) + num(p), num(0));
    return sign === "-" ? num(-1) * res : res;
  }
  function stringifySexagesimal(node) {
    let { value } = node;
    let num = (n) => n;
    if (typeof value === "bigint")
      num = (n) => BigInt(n);
    else if (isNaN(value) || !isFinite(value))
      return stringifyNumber(node);
    let sign = "";
    if (value < 0) {
      sign = "-";
      value *= num(-1);
    }
    const _60 = num(60);
    const parts = [value % _60];
    if (value < 60) {
      parts.unshift(0);
    } else {
      value = (value - parts[0]) / _60;
      parts.unshift(value % _60);
      if (value >= 60) {
        value = (value - parts[0]) / _60;
        parts.unshift(value);
      }
    }
    return sign + parts.map((n) => String(n).padStart(2, "0")).join(":").replace(/000000\d*$/, "");
  }
  var intTime = {
    identify: (value) => typeof value === "bigint" || Number.isInteger(value),
    default: true,
    tag: "tag:yaml.org,2002:int",
    format: "TIME",
    test: /^[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+$/,
    resolve: (str, _onError, { intAsBigInt }) => parseSexagesimal(str, intAsBigInt),
    stringify: stringifySexagesimal
  };
  var floatTime = {
    identify: (value) => typeof value === "number",
    default: true,
    tag: "tag:yaml.org,2002:float",
    format: "TIME",
    test: /^[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*$/,
    resolve: (str) => parseSexagesimal(str, false),
    stringify: stringifySexagesimal
  };
  var timestamp = {
    identify: (value) => value instanceof Date,
    default: true,
    tag: "tag:yaml.org,2002:timestamp",
    // If the time zone is omitted, the timestamp is assumed to be specified in UTC. The time part
    // may be omitted altogether, resulting in a date format. In such a case, the time part is
    // assumed to be 00:00:00Z (start of day, UTC).
    test: RegExp("^([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})(?:(?:t|T|[ \\t]+)([0-9]{1,2}):([0-9]{1,2}):([0-9]{1,2}(\\.[0-9]+)?)(?:[ \\t]*(Z|[-+][012]?[0-9](?::[0-9]{2})?))?)?$"),
    resolve(str) {
      const match = str.match(timestamp.test);
      if (!match)
        throw new Error("!!timestamp expects a date, starting with yyyy-mm-dd");
      const [, year, month, day, hour, minute, second] = match.map(Number);
      const millisec = match[7] ? Number((match[7] + "00").substr(1, 3)) : 0;
      let date = Date.UTC(year, month - 1, day, hour || 0, minute || 0, second || 0, millisec);
      const tz = match[8];
      if (tz && tz !== "Z") {
        let d = parseSexagesimal(tz, false);
        if (Math.abs(d) < 30)
          d *= 60;
        date -= 6e4 * d;
      }
      return new Date(date);
    },
    stringify: ({ value }) => value?.toISOString().replace(/(T00:00:00)?\.000Z$/, "") ?? ""
  };

  // node_modules/yaml/browser/dist/schema/yaml-1.1/schema.js
  var schema3 = [
    map,
    seq,
    string,
    nullTag,
    trueTag,
    falseTag,
    intBin,
    intOct2,
    int2,
    intHex2,
    floatNaN2,
    floatExp2,
    float2,
    binary,
    merge,
    omap,
    pairs,
    set,
    intTime,
    floatTime,
    timestamp
  ];

  // node_modules/yaml/browser/dist/schema/tags.js
  var schemas = /* @__PURE__ */ new Map([
    ["core", schema],
    ["failsafe", [map, seq, string]],
    ["json", schema2],
    ["yaml11", schema3],
    ["yaml-1.1", schema3]
  ]);
  var tagsByName = {
    binary,
    bool: boolTag,
    float,
    floatExp,
    floatNaN,
    floatTime,
    int,
    intHex,
    intOct,
    intTime,
    map,
    merge,
    null: nullTag,
    omap,
    pairs,
    seq,
    set,
    timestamp
  };
  var coreKnownTags = {
    "tag:yaml.org,2002:binary": binary,
    "tag:yaml.org,2002:merge": merge,
    "tag:yaml.org,2002:omap": omap,
    "tag:yaml.org,2002:pairs": pairs,
    "tag:yaml.org,2002:set": set,
    "tag:yaml.org,2002:timestamp": timestamp
  };
  function getTags(customTags, schemaName, addMergeTag) {
    const schemaTags = schemas.get(schemaName);
    if (schemaTags && !customTags) {
      return addMergeTag && !schemaTags.includes(merge) ? schemaTags.concat(merge) : schemaTags.slice();
    }
    let tags = schemaTags;
    if (!tags) {
      if (Array.isArray(customTags))
        tags = [];
      else {
        const keys = Array.from(schemas.keys()).filter((key) => key !== "yaml11").map((key) => JSON.stringify(key)).join(", ");
        throw new Error(`Unknown schema "${schemaName}"; use one of ${keys} or define customTags array`);
      }
    }
    if (Array.isArray(customTags)) {
      for (const tag of customTags)
        tags = tags.concat(tag);
    } else if (typeof customTags === "function") {
      tags = customTags(tags.slice());
    }
    if (addMergeTag)
      tags = tags.concat(merge);
    return tags.reduce((tags2, tag) => {
      const tagObj = typeof tag === "string" ? tagsByName[tag] : tag;
      if (!tagObj) {
        const tagName = JSON.stringify(tag);
        const keys = Object.keys(tagsByName).map((key) => JSON.stringify(key)).join(", ");
        throw new Error(`Unknown custom tag ${tagName}; use one of ${keys}`);
      }
      if (!tags2.includes(tagObj))
        tags2.push(tagObj);
      return tags2;
    }, []);
  }

  // node_modules/yaml/browser/dist/schema/Schema.js
  var sortMapEntriesByKey = (a, b) => a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
  var Schema = class _Schema {
    constructor({ compat, customTags, merge: merge2, resolveKnownTags, schema: schema4, sortMapEntries, toStringDefaults }) {
      this.compat = Array.isArray(compat) ? getTags(compat, "compat") : compat ? getTags(null, compat) : null;
      this.name = typeof schema4 === "string" && schema4 || "core";
      this.knownTags = resolveKnownTags ? coreKnownTags : {};
      this.tags = getTags(customTags, this.name, merge2);
      this.toStringOptions = toStringDefaults ?? null;
      Object.defineProperty(this, MAP, { value: map });
      Object.defineProperty(this, SCALAR, { value: string });
      Object.defineProperty(this, SEQ, { value: seq });
      this.sortMapEntries = typeof sortMapEntries === "function" ? sortMapEntries : sortMapEntries === true ? sortMapEntriesByKey : null;
    }
    clone() {
      const copy = Object.create(_Schema.prototype, Object.getOwnPropertyDescriptors(this));
      copy.tags = this.tags.slice();
      return copy;
    }
  };

  // node_modules/yaml/browser/dist/stringify/stringifyDocument.js
  function stringifyDocument(doc, options) {
    const lines = [];
    let hasDirectives = options.directives === true;
    if (options.directives !== false && doc.directives) {
      const dir = doc.directives.toString(doc);
      if (dir) {
        lines.push(dir);
        hasDirectives = true;
      } else if (doc.directives.docStart)
        hasDirectives = true;
    }
    if (hasDirectives)
      lines.push("---");
    const ctx = createStringifyContext(doc, options);
    const { commentString } = ctx.options;
    if (doc.commentBefore) {
      if (lines.length !== 1)
        lines.unshift("");
      const cs = commentString(doc.commentBefore);
      lines.unshift(indentComment(cs, ""));
    }
    let chompKeep = false;
    let contentComment = null;
    if (doc.contents) {
      if (isNode(doc.contents)) {
        if (doc.contents.spaceBefore && hasDirectives)
          lines.push("");
        if (doc.contents.commentBefore) {
          const cs = commentString(doc.contents.commentBefore);
          lines.push(indentComment(cs, ""));
        }
        ctx.forceBlockIndent = !!doc.comment;
        contentComment = doc.contents.comment;
      }
      const onChompKeep = contentComment ? void 0 : () => chompKeep = true;
      let body = stringify(doc.contents, ctx, () => contentComment = null, onChompKeep);
      if (contentComment)
        body += lineComment(body, "", commentString(contentComment));
      if ((body[0] === "|" || body[0] === ">") && lines[lines.length - 1] === "---") {
        lines[lines.length - 1] = `--- ${body}`;
      } else
        lines.push(body);
    } else {
      lines.push(stringify(doc.contents, ctx));
    }
    if (doc.directives?.docEnd) {
      if (doc.comment) {
        const cs = commentString(doc.comment);
        if (cs.includes("\n")) {
          lines.push("...");
          lines.push(indentComment(cs, ""));
        } else {
          lines.push(`... ${cs}`);
        }
      } else {
        lines.push("...");
      }
    } else {
      let dc = doc.comment;
      if (dc && chompKeep)
        dc = dc.replace(/^\n+/, "");
      if (dc) {
        if ((!chompKeep || contentComment) && lines[lines.length - 1] !== "")
          lines.push("");
        lines.push(indentComment(commentString(dc), ""));
      }
    }
    return lines.join("\n") + "\n";
  }

  // node_modules/yaml/browser/dist/doc/Document.js
  var Document = class _Document {
    constructor(value, replacer, options) {
      this.commentBefore = null;
      this.comment = null;
      this.errors = [];
      this.warnings = [];
      Object.defineProperty(this, NODE_TYPE, { value: DOC });
      let _replacer = null;
      if (typeof replacer === "function" || Array.isArray(replacer)) {
        _replacer = replacer;
      } else if (options === void 0 && replacer) {
        options = replacer;
        replacer = void 0;
      }
      const opt = Object.assign({
        intAsBigInt: false,
        keepSourceTokens: false,
        logLevel: "warn",
        prettyErrors: true,
        strict: true,
        stringKeys: false,
        uniqueKeys: true,
        version: "1.2"
      }, options);
      this.options = opt;
      let { version } = opt;
      if (options?._directives) {
        this.directives = options._directives.atDocument();
        if (this.directives.yaml.explicit)
          version = this.directives.yaml.version;
      } else
        this.directives = new Directives({ version });
      this.setSchema(version, options);
      this.contents = value === void 0 ? null : this.createNode(value, _replacer, options);
    }
    /**
     * Create a deep copy of this Document and its contents.
     *
     * Custom Node values that inherit from `Object` still refer to their original instances.
     */
    clone() {
      const copy = Object.create(_Document.prototype, {
        [NODE_TYPE]: { value: DOC }
      });
      copy.commentBefore = this.commentBefore;
      copy.comment = this.comment;
      copy.errors = this.errors.slice();
      copy.warnings = this.warnings.slice();
      copy.options = Object.assign({}, this.options);
      if (this.directives)
        copy.directives = this.directives.clone();
      copy.schema = this.schema.clone();
      copy.contents = isNode(this.contents) ? this.contents.clone(copy.schema) : this.contents;
      if (this.range)
        copy.range = this.range.slice();
      return copy;
    }
    /** Adds a value to the document. */
    add(value) {
      if (assertCollection(this.contents))
        this.contents.add(value);
    }
    /** Adds a value to the document. */
    addIn(path, value) {
      if (assertCollection(this.contents))
        this.contents.addIn(path, value);
    }
    /**
     * Create a new `Alias` node, ensuring that the target `node` has the required anchor.
     *
     * If `node` already has an anchor, `name` is ignored.
     * Otherwise, the `node.anchor` value will be set to `name`,
     * or if an anchor with that name is already present in the document,
     * `name` will be used as a prefix for a new unique anchor.
     * If `name` is undefined, the generated anchor will use 'a' as a prefix.
     */
    createAlias(node, name) {
      if (!node.anchor) {
        const prev = anchorNames(this);
        node.anchor = // eslint-disable-next-line @typescript-eslint/prefer-nullish-coalescing
        !name || prev.has(name) ? findNewAnchor(name || "a", prev) : name;
      }
      return new Alias(node.anchor);
    }
    createNode(value, replacer, options) {
      let _replacer = void 0;
      if (typeof replacer === "function") {
        value = replacer.call({ "": value }, "", value);
        _replacer = replacer;
      } else if (Array.isArray(replacer)) {
        const keyToStr = (v) => typeof v === "number" || v instanceof String || v instanceof Number;
        const asStr = replacer.filter(keyToStr).map(String);
        if (asStr.length > 0)
          replacer = replacer.concat(asStr);
        _replacer = replacer;
      } else if (options === void 0 && replacer) {
        options = replacer;
        replacer = void 0;
      }
      const { aliasDuplicateObjects, anchorPrefix, flow, keepUndefined, onTagObj, tag } = options ?? {};
      const { onAnchor, setAnchors, sourceObjects } = createNodeAnchors(
        this,
        // eslint-disable-next-line @typescript-eslint/prefer-nullish-coalescing
        anchorPrefix || "a"
      );
      const ctx = {
        aliasDuplicateObjects: aliasDuplicateObjects ?? true,
        keepUndefined: keepUndefined ?? false,
        onAnchor,
        onTagObj,
        replacer: _replacer,
        schema: this.schema,
        sourceObjects
      };
      const node = createNode(value, tag, ctx);
      if (flow && isCollection(node))
        node.flow = true;
      setAnchors();
      return node;
    }
    /**
     * Convert a key and a value into a `Pair` using the current schema,
     * recursively wrapping all values as `Scalar` or `Collection` nodes.
     */
    createPair(key, value, options = {}) {
      const k = this.createNode(key, null, options);
      const v = this.createNode(value, null, options);
      return new Pair(k, v);
    }
    /**
     * Removes a value from the document.
     * @returns `true` if the item was found and removed.
     */
    delete(key) {
      return assertCollection(this.contents) ? this.contents.delete(key) : false;
    }
    /**
     * Removes a value from the document.
     * @returns `true` if the item was found and removed.
     */
    deleteIn(path) {
      if (isEmptyPath(path)) {
        if (this.contents == null)
          return false;
        this.contents = null;
        return true;
      }
      return assertCollection(this.contents) ? this.contents.deleteIn(path) : false;
    }
    /**
     * Returns item at `key`, or `undefined` if not found. By default unwraps
     * scalar values from their surrounding node; to disable set `keepScalar` to
     * `true` (collections are always returned intact).
     */
    get(key, keepScalar) {
      return isCollection(this.contents) ? this.contents.get(key, keepScalar) : void 0;
    }
    /**
     * Returns item at `path`, or `undefined` if not found. By default unwraps
     * scalar values from their surrounding node; to disable set `keepScalar` to
     * `true` (collections are always returned intact).
     */
    getIn(path, keepScalar) {
      if (isEmptyPath(path))
        return !keepScalar && isScalar(this.contents) ? this.contents.value : this.contents;
      return isCollection(this.contents) ? this.contents.getIn(path, keepScalar) : void 0;
    }
    /**
     * Checks if the document includes a value with the key `key`.
     */
    has(key) {
      return isCollection(this.contents) ? this.contents.has(key) : false;
    }
    /**
     * Checks if the document includes a value at `path`.
     */
    hasIn(path) {
      if (isEmptyPath(path))
        return this.contents !== void 0;
      return isCollection(this.contents) ? this.contents.hasIn(path) : false;
    }
    /**
     * Sets a value in this document. For `!!set`, `value` needs to be a
     * boolean to add/remove the item from the set.
     */
    set(key, value) {
      if (this.contents == null) {
        this.contents = collectionFromPath(this.schema, [key], value);
      } else if (assertCollection(this.contents)) {
        this.contents.set(key, value);
      }
    }
    /**
     * Sets a value in this document. For `!!set`, `value` needs to be a
     * boolean to add/remove the item from the set.
     */
    setIn(path, value) {
      if (isEmptyPath(path)) {
        this.contents = value;
      } else if (this.contents == null) {
        this.contents = collectionFromPath(this.schema, Array.from(path), value);
      } else if (assertCollection(this.contents)) {
        this.contents.setIn(path, value);
      }
    }
    /**
     * Change the YAML version and schema used by the document.
     * A `null` version disables support for directives, explicit tags, anchors, and aliases.
     * It also requires the `schema` option to be given as a `Schema` instance value.
     *
     * Overrides all previously set schema options.
     */
    setSchema(version, options = {}) {
      if (typeof version === "number")
        version = String(version);
      let opt;
      switch (version) {
        case "1.1":
          if (this.directives)
            this.directives.yaml.version = "1.1";
          else
            this.directives = new Directives({ version: "1.1" });
          opt = { resolveKnownTags: false, schema: "yaml-1.1" };
          break;
        case "1.2":
        case "next":
          if (this.directives)
            this.directives.yaml.version = version;
          else
            this.directives = new Directives({ version });
          opt = { resolveKnownTags: true, schema: "core" };
          break;
        case null:
          if (this.directives)
            delete this.directives;
          opt = null;
          break;
        default: {
          const sv = JSON.stringify(version);
          throw new Error(`Expected '1.1', '1.2' or null as first argument, but found: ${sv}`);
        }
      }
      if (options.schema instanceof Object)
        this.schema = options.schema;
      else if (opt)
        this.schema = new Schema(Object.assign(opt, options));
      else
        throw new Error(`With a null YAML version, the { schema: Schema } option is required`);
    }
    // json & jsonArg are only used from toJSON()
    toJS({ json, jsonArg, mapAsMap, maxAliasCount, onAnchor, reviver } = {}) {
      const ctx = {
        anchors: /* @__PURE__ */ new Map(),
        doc: this,
        keep: !json,
        mapAsMap: mapAsMap === true,
        mapKeyWarned: false,
        maxAliasCount: typeof maxAliasCount === "number" ? maxAliasCount : 100
      };
      const res = toJS(this.contents, jsonArg ?? "", ctx);
      if (typeof onAnchor === "function")
        for (const { count, res: res2 } of ctx.anchors.values())
          onAnchor(res2, count);
      return typeof reviver === "function" ? applyReviver(reviver, { "": res }, "", res) : res;
    }
    /**
     * A JSON representation of the document `contents`.
     *
     * @param jsonArg Used by `JSON.stringify` to indicate the array index or
     *   property name.
     */
    toJSON(jsonArg, onAnchor) {
      return this.toJS({ json: true, jsonArg, mapAsMap: false, onAnchor });
    }
    /** A YAML representation of the document. */
    toString(options = {}) {
      if (this.errors.length > 0)
        throw new Error("Document with errors cannot be stringified");
      if ("indent" in options && (!Number.isInteger(options.indent) || Number(options.indent) <= 0)) {
        const s = JSON.stringify(options.indent);
        throw new Error(`"indent" option must be a positive integer, not ${s}`);
      }
      return stringifyDocument(this, options);
    }
  };
  function assertCollection(contents) {
    if (isCollection(contents))
      return true;
    throw new Error("Expected a YAML collection as document contents");
  }

  // node_modules/yaml/browser/dist/errors.js
  var YAMLError = class extends Error {
    constructor(name, pos, code, message) {
      super();
      this.name = name;
      this.code = code;
      this.message = message;
      this.pos = pos;
    }
  };
  var YAMLParseError = class extends YAMLError {
    constructor(pos, code, message) {
      super("YAMLParseError", pos, code, message);
    }
  };
  var YAMLWarning = class extends YAMLError {
    constructor(pos, code, message) {
      super("YAMLWarning", pos, code, message);
    }
  };
  var prettifyError = (src, lc) => (error) => {
    if (error.pos[0] === -1)
      return;
    error.linePos = error.pos.map((pos) => lc.linePos(pos));
    const { line, col } = error.linePos[0];
    error.message += ` at line ${line}, column ${col}`;
    let ci = col - 1;
    let lineStr = src.substring(lc.lineStarts[line - 1], lc.lineStarts[line]).replace(/[\n\r]+$/, "");
    if (ci >= 60 && lineStr.length > 80) {
      const trimStart = Math.min(ci - 39, lineStr.length - 79);
      lineStr = "…" + lineStr.substring(trimStart);
      ci -= trimStart - 1;
    }
    if (lineStr.length > 80)
      lineStr = lineStr.substring(0, 79) + "…";
    if (line > 1 && /^ *$/.test(lineStr.substring(0, ci))) {
      let prev = src.substring(lc.lineStarts[line - 2], lc.lineStarts[line - 1]);
      if (prev.length > 80)
        prev = prev.substring(0, 79) + "…\n";
      lineStr = prev + lineStr;
    }
    if (/[^ ]/.test(lineStr)) {
      let count = 1;
      const end = error.linePos[1];
      if (end?.line === line && end.col > col) {
        count = Math.max(1, Math.min(end.col - col, 80 - ci));
      }
      const pointer = " ".repeat(ci) + "^".repeat(count);
      error.message += `:

${lineStr}
${pointer}
`;
    }
  };

  // node_modules/yaml/browser/dist/compose/resolve-props.js
  function resolveProps(tokens, { flow, indicator, next, offset, onError, parentIndent, startOnNewline }) {
    let spaceBefore = false;
    let atNewline = startOnNewline;
    let hasSpace = startOnNewline;
    let comment = "";
    let commentSep = "";
    let hasNewline = false;
    let reqSpace = false;
    let tab = null;
    let anchor = null;
    let tag = null;
    let newlineAfterProp = null;
    let comma = null;
    let found = null;
    let start = null;
    for (const token of tokens) {
      if (reqSpace) {
        if (token.type !== "space" && token.type !== "newline" && token.type !== "comma")
          onError(token.offset, "MISSING_CHAR", "Tags and anchors must be separated from the next token by white space");
        reqSpace = false;
      }
      if (tab) {
        if (atNewline && token.type !== "comment" && token.type !== "newline") {
          onError(tab, "TAB_AS_INDENT", "Tabs are not allowed as indentation");
        }
        tab = null;
      }
      switch (token.type) {
        case "space":
          if (!flow && (indicator !== "doc-start" || next?.type !== "flow-collection") && token.source.includes("	")) {
            tab = token;
          }
          hasSpace = true;
          break;
        case "comment": {
          if (!hasSpace)
            onError(token, "MISSING_CHAR", "Comments must be separated from other tokens by white space characters");
          const cb = token.source.substring(1) || " ";
          if (!comment)
            comment = cb;
          else
            comment += commentSep + cb;
          commentSep = "";
          atNewline = false;
          break;
        }
        case "newline":
          if (atNewline) {
            if (comment)
              comment += token.source;
            else if (!found || indicator !== "seq-item-ind")
              spaceBefore = true;
          } else
            commentSep += token.source;
          atNewline = true;
          hasNewline = true;
          if (anchor || tag)
            newlineAfterProp = token;
          hasSpace = true;
          break;
        case "anchor":
          if (anchor)
            onError(token, "MULTIPLE_ANCHORS", "A node can have at most one anchor");
          if (token.source.endsWith(":"))
            onError(token.offset + token.source.length - 1, "BAD_ALIAS", "Anchor ending in : is ambiguous", true);
          anchor = token;
          start ?? (start = token.offset);
          atNewline = false;
          hasSpace = false;
          reqSpace = true;
          break;
        case "tag": {
          if (tag)
            onError(token, "MULTIPLE_TAGS", "A node can have at most one tag");
          tag = token;
          start ?? (start = token.offset);
          atNewline = false;
          hasSpace = false;
          reqSpace = true;
          break;
        }
        case indicator:
          if (anchor || tag)
            onError(token, "BAD_PROP_ORDER", `Anchors and tags must be after the ${token.source} indicator`);
          if (found)
            onError(token, "UNEXPECTED_TOKEN", `Unexpected ${token.source} in ${flow ?? "collection"}`);
          found = token;
          atNewline = indicator === "seq-item-ind" || indicator === "explicit-key-ind";
          hasSpace = false;
          break;
        case "comma":
          if (flow) {
            if (comma)
              onError(token, "UNEXPECTED_TOKEN", `Unexpected , in ${flow}`);
            comma = token;
            atNewline = false;
            hasSpace = false;
            break;
          }
        // else fallthrough
        default:
          onError(token, "UNEXPECTED_TOKEN", `Unexpected ${token.type} token`);
          atNewline = false;
          hasSpace = false;
      }
    }
    const last = tokens[tokens.length - 1];
    const end = last ? last.offset + last.source.length : offset;
    if (reqSpace && next && next.type !== "space" && next.type !== "newline" && next.type !== "comma" && (next.type !== "scalar" || next.source !== "")) {
      onError(next.offset, "MISSING_CHAR", "Tags and anchors must be separated from the next token by white space");
    }
    if (tab && (atNewline && tab.indent <= parentIndent || next?.type === "block-map" || next?.type === "block-seq"))
      onError(tab, "TAB_AS_INDENT", "Tabs are not allowed as indentation");
    return {
      comma,
      found,
      spaceBefore,
      comment,
      hasNewline,
      anchor,
      tag,
      newlineAfterProp,
      end,
      start: start ?? end
    };
  }

  // node_modules/yaml/browser/dist/compose/util-contains-newline.js
  function containsNewline(key) {
    if (!key)
      return null;
    switch (key.type) {
      case "alias":
      case "scalar":
      case "double-quoted-scalar":
      case "single-quoted-scalar":
        if (key.source.includes("\n"))
          return true;
        if (key.end) {
          for (const st of key.end)
            if (st.type === "newline")
              return true;
        }
        return false;
      case "flow-collection":
        for (const it of key.items) {
          for (const st of it.start)
            if (st.type === "newline")
              return true;
          if (it.sep) {
            for (const st of it.sep)
              if (st.type === "newline")
                return true;
          }
          if (containsNewline(it.key) || containsNewline(it.value))
            return true;
        }
        return false;
      default:
        return true;
    }
  }

  // node_modules/yaml/browser/dist/compose/util-flow-indent-check.js
  function flowIndentCheck(indent, fc, onError) {
    if (fc?.type === "flow-collection") {
      const end = fc.end[0];
      if (end.indent === indent && (end.source === "]" || end.source === "}") && containsNewline(fc)) {
        const msg = "Flow end indicator should be more indented than parent";
        onError(end, "BAD_INDENT", msg, true);
      }
    }
  }

  // node_modules/yaml/browser/dist/compose/util-map-includes.js
  function mapIncludes(ctx, items, search) {
    const { uniqueKeys } = ctx.options;
    if (uniqueKeys === false)
      return false;
    const isEqual = typeof uniqueKeys === "function" ? uniqueKeys : (a, b) => a === b || isScalar(a) && isScalar(b) && a.value === b.value;
    return items.some((pair) => isEqual(pair.key, search));
  }

  // node_modules/yaml/browser/dist/compose/resolve-block-map.js
  var startColMsg = "All mapping items must start at the same column";
  function resolveBlockMap({ composeNode: composeNode2, composeEmptyNode: composeEmptyNode2 }, ctx, bm, onError, tag) {
    const NodeClass = tag?.nodeClass ?? YAMLMap;
    const map2 = new NodeClass(ctx.schema);
    if (ctx.atRoot)
      ctx.atRoot = false;
    let offset = bm.offset;
    let commentEnd = null;
    for (const collItem of bm.items) {
      const { start, key, sep, value } = collItem;
      const keyProps = resolveProps(start, {
        indicator: "explicit-key-ind",
        next: key ?? sep?.[0],
        offset,
        onError,
        parentIndent: bm.indent,
        startOnNewline: true
      });
      const implicitKey = !keyProps.found;
      if (implicitKey) {
        if (key) {
          if (key.type === "block-seq")
            onError(offset, "BLOCK_AS_IMPLICIT_KEY", "A block sequence may not be used as an implicit map key");
          else if ("indent" in key && key.indent !== bm.indent)
            onError(offset, "BAD_INDENT", startColMsg);
        }
        if (!keyProps.anchor && !keyProps.tag && !sep) {
          commentEnd = keyProps.end;
          if (keyProps.comment) {
            if (map2.comment)
              map2.comment += "\n" + keyProps.comment;
            else
              map2.comment = keyProps.comment;
          }
          continue;
        }
        if (keyProps.newlineAfterProp || containsNewline(key)) {
          onError(key ?? start[start.length - 1], "MULTILINE_IMPLICIT_KEY", "Implicit keys need to be on a single line");
        }
      } else if (keyProps.found?.indent !== bm.indent) {
        onError(offset, "BAD_INDENT", startColMsg);
      }
      ctx.atKey = true;
      const keyStart = keyProps.end;
      const keyNode = key ? composeNode2(ctx, key, keyProps, onError) : composeEmptyNode2(ctx, keyStart, start, null, keyProps, onError);
      if (ctx.schema.compat)
        flowIndentCheck(bm.indent, key, onError);
      ctx.atKey = false;
      if (mapIncludes(ctx, map2.items, keyNode))
        onError(keyStart, "DUPLICATE_KEY", "Map keys must be unique");
      const valueProps = resolveProps(sep ?? [], {
        indicator: "map-value-ind",
        next: value,
        offset: keyNode.range[2],
        onError,
        parentIndent: bm.indent,
        startOnNewline: !key || key.type === "block-scalar"
      });
      offset = valueProps.end;
      if (valueProps.found) {
        if (implicitKey) {
          if (value?.type === "block-map" && !valueProps.hasNewline)
            onError(offset, "BLOCK_AS_IMPLICIT_KEY", "Nested mappings are not allowed in compact mappings");
          if (ctx.options.strict && keyProps.start < valueProps.found.offset - 1024)
            onError(keyNode.range, "KEY_OVER_1024_CHARS", "The : indicator must be at most 1024 chars after the start of an implicit block mapping key");
        }
        const valueNode = value ? composeNode2(ctx, value, valueProps, onError) : composeEmptyNode2(ctx, offset, sep, null, valueProps, onError);
        if (ctx.schema.compat)
          flowIndentCheck(bm.indent, value, onError);
        offset = valueNode.range[2];
        const pair = new Pair(keyNode, valueNode);
        if (ctx.options.keepSourceTokens)
          pair.srcToken = collItem;
        map2.items.push(pair);
      } else {
        if (implicitKey)
          onError(keyNode.range, "MISSING_CHAR", "Implicit map keys need to be followed by map values");
        if (valueProps.comment) {
          if (keyNode.comment)
            keyNode.comment += "\n" + valueProps.comment;
          else
            keyNode.comment = valueProps.comment;
        }
        const pair = new Pair(keyNode);
        if (ctx.options.keepSourceTokens)
          pair.srcToken = collItem;
        map2.items.push(pair);
      }
    }
    if (commentEnd && commentEnd < offset)
      onError(commentEnd, "IMPOSSIBLE", "Map comment with trailing content");
    map2.range = [bm.offset, offset, commentEnd ?? offset];
    return map2;
  }

  // node_modules/yaml/browser/dist/compose/resolve-block-seq.js
  function resolveBlockSeq({ composeNode: composeNode2, composeEmptyNode: composeEmptyNode2 }, ctx, bs, onError, tag) {
    const NodeClass = tag?.nodeClass ?? YAMLSeq;
    const seq2 = new NodeClass(ctx.schema);
    if (ctx.atRoot)
      ctx.atRoot = false;
    if (ctx.atKey)
      ctx.atKey = false;
    let offset = bs.offset;
    let commentEnd = null;
    for (const { start, value } of bs.items) {
      const props = resolveProps(start, {
        indicator: "seq-item-ind",
        next: value,
        offset,
        onError,
        parentIndent: bs.indent,
        startOnNewline: true
      });
      if (!props.found) {
        if (props.anchor || props.tag || value) {
          if (value?.type === "block-seq")
            onError(props.end, "BAD_INDENT", "All sequence items must start at the same column");
          else
            onError(offset, "MISSING_CHAR", "Sequence item without - indicator");
        } else {
          commentEnd = props.end;
          if (props.comment)
            seq2.comment = props.comment;
          continue;
        }
      }
      const node = value ? composeNode2(ctx, value, props, onError) : composeEmptyNode2(ctx, props.end, start, null, props, onError);
      if (ctx.schema.compat)
        flowIndentCheck(bs.indent, value, onError);
      offset = node.range[2];
      seq2.items.push(node);
    }
    seq2.range = [bs.offset, offset, commentEnd ?? offset];
    return seq2;
  }

  // node_modules/yaml/browser/dist/compose/resolve-end.js
  function resolveEnd(end, offset, reqSpace, onError) {
    let comment = "";
    if (end) {
      let hasSpace = false;
      let sep = "";
      for (const token of end) {
        const { source, type } = token;
        switch (type) {
          case "space":
            hasSpace = true;
            break;
          case "comment": {
            if (reqSpace && !hasSpace)
              onError(token, "MISSING_CHAR", "Comments must be separated from other tokens by white space characters");
            const cb = source.substring(1) || " ";
            if (!comment)
              comment = cb;
            else
              comment += sep + cb;
            sep = "";
            break;
          }
          case "newline":
            if (comment)
              sep += source;
            hasSpace = true;
            break;
          default:
            onError(token, "UNEXPECTED_TOKEN", `Unexpected ${type} at node end`);
        }
        offset += source.length;
      }
    }
    return { comment, offset };
  }

  // node_modules/yaml/browser/dist/compose/resolve-flow-collection.js
  var blockMsg = "Block collections are not allowed within flow collections";
  var isBlock = (token) => token && (token.type === "block-map" || token.type === "block-seq");
  function resolveFlowCollection({ composeNode: composeNode2, composeEmptyNode: composeEmptyNode2 }, ctx, fc, onError, tag) {
    const isMap2 = fc.start.source === "{";
    const fcName = isMap2 ? "flow map" : "flow sequence";
    const NodeClass = tag?.nodeClass ?? (isMap2 ? YAMLMap : YAMLSeq);
    const coll = new NodeClass(ctx.schema);
    coll.flow = true;
    const atRoot = ctx.atRoot;
    if (atRoot)
      ctx.atRoot = false;
    if (ctx.atKey)
      ctx.atKey = false;
    let offset = fc.offset + fc.start.source.length;
    for (let i = 0; i < fc.items.length; ++i) {
      const collItem = fc.items[i];
      const { start, key, sep, value } = collItem;
      const props = resolveProps(start, {
        flow: fcName,
        indicator: "explicit-key-ind",
        next: key ?? sep?.[0],
        offset,
        onError,
        parentIndent: fc.indent,
        startOnNewline: false
      });
      if (!props.found) {
        if (!props.anchor && !props.tag && !sep && !value) {
          if (i === 0 && props.comma)
            onError(props.comma, "UNEXPECTED_TOKEN", `Unexpected , in ${fcName}`);
          else if (i < fc.items.length - 1)
            onError(props.start, "UNEXPECTED_TOKEN", `Unexpected empty item in ${fcName}`);
          if (props.comment) {
            if (coll.comment)
              coll.comment += "\n" + props.comment;
            else
              coll.comment = props.comment;
          }
          offset = props.end;
          continue;
        }
        if (!isMap2 && ctx.options.strict && containsNewline(key))
          onError(
            key,
            // checked by containsNewline()
            "MULTILINE_IMPLICIT_KEY",
            "Implicit keys of flow sequence pairs need to be on a single line"
          );
      }
      if (i === 0) {
        if (props.comma)
          onError(props.comma, "UNEXPECTED_TOKEN", `Unexpected , in ${fcName}`);
      } else {
        if (!props.comma)
          onError(props.start, "MISSING_CHAR", `Missing , between ${fcName} items`);
        if (props.comment) {
          let prevItemComment = "";
          loop: for (const st of start) {
            switch (st.type) {
              case "comma":
              case "space":
                break;
              case "comment":
                prevItemComment = st.source.substring(1);
                break loop;
              default:
                break loop;
            }
          }
          if (prevItemComment) {
            let prev = coll.items[coll.items.length - 1];
            if (isPair(prev))
              prev = prev.value ?? prev.key;
            if (prev.comment)
              prev.comment += "\n" + prevItemComment;
            else
              prev.comment = prevItemComment;
            props.comment = props.comment.substring(prevItemComment.length + 1);
          }
        }
      }
      if (!isMap2 && !sep && !props.found) {
        const valueNode = value ? composeNode2(ctx, value, props, onError) : composeEmptyNode2(ctx, props.end, sep, null, props, onError);
        coll.items.push(valueNode);
        offset = valueNode.range[2];
        if (isBlock(value))
          onError(valueNode.range, "BLOCK_IN_FLOW", blockMsg);
      } else {
        ctx.atKey = true;
        const keyStart = props.end;
        const keyNode = key ? composeNode2(ctx, key, props, onError) : composeEmptyNode2(ctx, keyStart, start, null, props, onError);
        if (isBlock(key))
          onError(keyNode.range, "BLOCK_IN_FLOW", blockMsg);
        ctx.atKey = false;
        const valueProps = resolveProps(sep ?? [], {
          flow: fcName,
          indicator: "map-value-ind",
          next: value,
          offset: keyNode.range[2],
          onError,
          parentIndent: fc.indent,
          startOnNewline: false
        });
        if (valueProps.found) {
          if (!isMap2 && !props.found && ctx.options.strict) {
            if (sep)
              for (const st of sep) {
                if (st === valueProps.found)
                  break;
                if (st.type === "newline") {
                  onError(st, "MULTILINE_IMPLICIT_KEY", "Implicit keys of flow sequence pairs need to be on a single line");
                  break;
                }
              }
            if (props.start < valueProps.found.offset - 1024)
              onError(valueProps.found, "KEY_OVER_1024_CHARS", "The : indicator must be at most 1024 chars after the start of an implicit flow sequence key");
          }
        } else if (value) {
          if ("source" in value && value.source?.[0] === ":")
            onError(value, "MISSING_CHAR", `Missing space after : in ${fcName}`);
          else
            onError(valueProps.start, "MISSING_CHAR", `Missing , or : between ${fcName} items`);
        }
        const valueNode = value ? composeNode2(ctx, value, valueProps, onError) : valueProps.found ? composeEmptyNode2(ctx, valueProps.end, sep, null, valueProps, onError) : null;
        if (valueNode) {
          if (isBlock(value))
            onError(valueNode.range, "BLOCK_IN_FLOW", blockMsg);
        } else if (valueProps.comment) {
          if (keyNode.comment)
            keyNode.comment += "\n" + valueProps.comment;
          else
            keyNode.comment = valueProps.comment;
        }
        const pair = new Pair(keyNode, valueNode);
        if (ctx.options.keepSourceTokens)
          pair.srcToken = collItem;
        if (isMap2) {
          const map2 = coll;
          if (mapIncludes(ctx, map2.items, keyNode))
            onError(keyStart, "DUPLICATE_KEY", "Map keys must be unique");
          map2.items.push(pair);
        } else {
          const map2 = new YAMLMap(ctx.schema);
          map2.flow = true;
          map2.items.push(pair);
          const endRange = (valueNode ?? keyNode).range;
          map2.range = [keyNode.range[0], endRange[1], endRange[2]];
          coll.items.push(map2);
        }
        offset = valueNode ? valueNode.range[2] : valueProps.end;
      }
    }
    const expectedEnd = isMap2 ? "}" : "]";
    const [ce, ...ee] = fc.end;
    let cePos = offset;
    if (ce?.source === expectedEnd)
      cePos = ce.offset + ce.source.length;
    else {
      const name = fcName[0].toUpperCase() + fcName.substring(1);
      const msg = atRoot ? `${name} must end with a ${expectedEnd}` : `${name} in block collection must be sufficiently indented and end with a ${expectedEnd}`;
      onError(offset, atRoot ? "MISSING_CHAR" : "BAD_INDENT", msg);
      if (ce && ce.source.length !== 1)
        ee.unshift(ce);
    }
    if (ee.length > 0) {
      const end = resolveEnd(ee, cePos, ctx.options.strict, onError);
      if (end.comment) {
        if (coll.comment)
          coll.comment += "\n" + end.comment;
        else
          coll.comment = end.comment;
      }
      coll.range = [fc.offset, cePos, end.offset];
    } else {
      coll.range = [fc.offset, cePos, cePos];
    }
    return coll;
  }

  // node_modules/yaml/browser/dist/compose/compose-collection.js
  function resolveCollection(CN2, ctx, token, onError, tagName, tag) {
    const coll = token.type === "block-map" ? resolveBlockMap(CN2, ctx, token, onError, tag) : token.type === "block-seq" ? resolveBlockSeq(CN2, ctx, token, onError, tag) : resolveFlowCollection(CN2, ctx, token, onError, tag);
    const Coll = coll.constructor;
    if (tagName === "!" || tagName === Coll.tagName) {
      coll.tag = Coll.tagName;
      return coll;
    }
    if (tagName)
      coll.tag = tagName;
    return coll;
  }
  function composeCollection(CN2, ctx, token, props, onError) {
    const tagToken = props.tag;
    const tagName = !tagToken ? null : ctx.directives.tagName(tagToken.source, (msg) => onError(tagToken, "TAG_RESOLVE_FAILED", msg));
    if (token.type === "block-seq") {
      const { anchor, newlineAfterProp: nl } = props;
      const lastProp = anchor && tagToken ? anchor.offset > tagToken.offset ? anchor : tagToken : anchor ?? tagToken;
      if (lastProp && (!nl || nl.offset < lastProp.offset)) {
        const message = "Missing newline after block sequence props";
        onError(lastProp, "MISSING_CHAR", message);
      }
    }
    const expType = token.type === "block-map" ? "map" : token.type === "block-seq" ? "seq" : token.start.source === "{" ? "map" : "seq";
    if (!tagToken || !tagName || tagName === "!" || tagName === YAMLMap.tagName && expType === "map" || tagName === YAMLSeq.tagName && expType === "seq") {
      return resolveCollection(CN2, ctx, token, onError, tagName);
    }
    let tag = ctx.schema.tags.find((t) => t.tag === tagName && t.collection === expType);
    if (!tag) {
      const kt = ctx.schema.knownTags[tagName];
      if (kt?.collection === expType) {
        ctx.schema.tags.push(Object.assign({}, kt, { default: false }));
        tag = kt;
      } else {
        if (kt) {
          onError(tagToken, "BAD_COLLECTION_TYPE", `${kt.tag} used for ${expType} collection, but expects ${kt.collection ?? "scalar"}`, true);
        } else {
          onError(tagToken, "TAG_RESOLVE_FAILED", `Unresolved tag: ${tagName}`, true);
        }
        return resolveCollection(CN2, ctx, token, onError, tagName);
      }
    }
    const coll = resolveCollection(CN2, ctx, token, onError, tagName, tag);
    const res = tag.resolve?.(coll, (msg) => onError(tagToken, "TAG_RESOLVE_FAILED", msg), ctx.options) ?? coll;
    const node = isNode(res) ? res : new Scalar(res);
    node.range = coll.range;
    node.tag = tagName;
    if (tag?.format)
      node.format = tag.format;
    return node;
  }

  // node_modules/yaml/browser/dist/compose/resolve-block-scalar.js
  function resolveBlockScalar(ctx, scalar, onError) {
    const start = scalar.offset;
    const header = parseBlockScalarHeader(scalar, ctx.options.strict, onError);
    if (!header)
      return { value: "", type: null, comment: "", range: [start, start, start] };
    const type = header.mode === ">" ? Scalar.BLOCK_FOLDED : Scalar.BLOCK_LITERAL;
    const lines = scalar.source ? splitLines(scalar.source) : [];
    let chompStart = lines.length;
    for (let i = lines.length - 1; i >= 0; --i) {
      const content = lines[i][1];
      if (content === "" || content === "\r")
        chompStart = i;
      else
        break;
    }
    if (chompStart === 0) {
      const value2 = header.chomp === "+" && lines.length > 0 ? "\n".repeat(Math.max(1, lines.length - 1)) : "";
      let end2 = start + header.length;
      if (scalar.source)
        end2 += scalar.source.length;
      return { value: value2, type, comment: header.comment, range: [start, end2, end2] };
    }
    let trimIndent = scalar.indent + header.indent;
    let offset = scalar.offset + header.length;
    let contentStart = 0;
    for (let i = 0; i < chompStart; ++i) {
      const [indent, content] = lines[i];
      if (content === "" || content === "\r") {
        if (header.indent === 0 && indent.length > trimIndent)
          trimIndent = indent.length;
      } else {
        if (indent.length < trimIndent) {
          const message = "Block scalars with more-indented leading empty lines must use an explicit indentation indicator";
          onError(offset + indent.length, "MISSING_CHAR", message);
        }
        if (header.indent === 0)
          trimIndent = indent.length;
        contentStart = i;
        if (trimIndent === 0 && !ctx.atRoot) {
          const message = "Block scalar values in collections must be indented";
          onError(offset, "BAD_INDENT", message);
        }
        break;
      }
      offset += indent.length + content.length + 1;
    }
    for (let i = lines.length - 1; i >= chompStart; --i) {
      if (lines[i][0].length > trimIndent)
        chompStart = i + 1;
    }
    let value = "";
    let sep = "";
    let prevMoreIndented = false;
    for (let i = 0; i < contentStart; ++i)
      value += lines[i][0].slice(trimIndent) + "\n";
    for (let i = contentStart; i < chompStart; ++i) {
      let [indent, content] = lines[i];
      offset += indent.length + content.length + 1;
      const crlf = content[content.length - 1] === "\r";
      if (crlf)
        content = content.slice(0, -1);
      if (content && indent.length < trimIndent) {
        const src = header.indent ? "explicit indentation indicator" : "first line";
        const message = `Block scalar lines must not be less indented than their ${src}`;
        onError(offset - content.length - (crlf ? 2 : 1), "BAD_INDENT", message);
        indent = "";
      }
      if (type === Scalar.BLOCK_LITERAL) {
        value += sep + indent.slice(trimIndent) + content;
        sep = "\n";
      } else if (indent.length > trimIndent || content[0] === "	") {
        if (sep === " ")
          sep = "\n";
        else if (!prevMoreIndented && sep === "\n")
          sep = "\n\n";
        value += sep + indent.slice(trimIndent) + content;
        sep = "\n";
        prevMoreIndented = true;
      } else if (content === "") {
        if (sep === "\n")
          value += "\n";
        else
          sep = "\n";
      } else {
        value += sep + content;
        sep = " ";
        prevMoreIndented = false;
      }
    }
    switch (header.chomp) {
      case "-":
        break;
      case "+":
        for (let i = chompStart; i < lines.length; ++i)
          value += "\n" + lines[i][0].slice(trimIndent);
        if (value[value.length - 1] !== "\n")
          value += "\n";
        break;
      default:
        value += "\n";
    }
    const end = start + header.length + scalar.source.length;
    return { value, type, comment: header.comment, range: [start, end, end] };
  }
  function parseBlockScalarHeader({ offset, props }, strict, onError) {
    if (props[0].type !== "block-scalar-header") {
      onError(props[0], "IMPOSSIBLE", "Block scalar header not found");
      return null;
    }
    const { source } = props[0];
    const mode = source[0];
    let indent = 0;
    let chomp = "";
    let error = -1;
    for (let i = 1; i < source.length; ++i) {
      const ch = source[i];
      if (!chomp && (ch === "-" || ch === "+"))
        chomp = ch;
      else {
        const n = Number(ch);
        if (!indent && n)
          indent = n;
        else if (error === -1)
          error = offset + i;
      }
    }
    if (error !== -1)
      onError(error, "UNEXPECTED_TOKEN", `Block scalar header includes extra characters: ${source}`);
    let hasSpace = false;
    let comment = "";
    let length = source.length;
    for (let i = 1; i < props.length; ++i) {
      const token = props[i];
      switch (token.type) {
        case "space":
          hasSpace = true;
        // fallthrough
        case "newline":
          length += token.source.length;
          break;
        case "comment":
          if (strict && !hasSpace) {
            const message = "Comments must be separated from other tokens by white space characters";
            onError(token, "MISSING_CHAR", message);
          }
          length += token.source.length;
          comment = token.source.substring(1);
          break;
        case "error":
          onError(token, "UNEXPECTED_TOKEN", token.message);
          length += token.source.length;
          break;
        /* istanbul ignore next should not happen */
        default: {
          const message = `Unexpected token in block scalar header: ${token.type}`;
          onError(token, "UNEXPECTED_TOKEN", message);
          const ts = token.source;
          if (ts && typeof ts === "string")
            length += ts.length;
        }
      }
    }
    return { mode, indent, chomp, comment, length };
  }
  function splitLines(source) {
    const split = source.split(/\n( *)/);
    const first = split[0];
    const m = first.match(/^( *)/);
    const line0 = m?.[1] ? [m[1], first.slice(m[1].length)] : ["", first];
    const lines = [line0];
    for (let i = 1; i < split.length; i += 2)
      lines.push([split[i], split[i + 1]]);
    return lines;
  }

  // node_modules/yaml/browser/dist/compose/resolve-flow-scalar.js
  function resolveFlowScalar(scalar, strict, onError) {
    const { offset, type, source, end } = scalar;
    let _type;
    let value;
    const _onError = (rel, code, msg) => onError(offset + rel, code, msg);
    switch (type) {
      case "scalar":
        _type = Scalar.PLAIN;
        value = plainValue(source, _onError);
        break;
      case "single-quoted-scalar":
        _type = Scalar.QUOTE_SINGLE;
        value = singleQuotedValue(source, _onError);
        break;
      case "double-quoted-scalar":
        _type = Scalar.QUOTE_DOUBLE;
        value = doubleQuotedValue(source, _onError);
        break;
      /* istanbul ignore next should not happen */
      default:
        onError(scalar, "UNEXPECTED_TOKEN", `Expected a flow scalar value, but found: ${type}`);
        return {
          value: "",
          type: null,
          comment: "",
          range: [offset, offset + source.length, offset + source.length]
        };
    }
    const valueEnd = offset + source.length;
    const re = resolveEnd(end, valueEnd, strict, onError);
    return {
      value,
      type: _type,
      comment: re.comment,
      range: [offset, valueEnd, re.offset]
    };
  }
  function plainValue(source, onError) {
    let badChar = "";
    switch (source[0]) {
      /* istanbul ignore next should not happen */
      case "	":
        badChar = "a tab character";
        break;
      case ",":
        badChar = "flow indicator character ,";
        break;
      case "%":
        badChar = "directive indicator character %";
        break;
      case "|":
      case ">": {
        badChar = `block scalar indicator ${source[0]}`;
        break;
      }
      case "@":
      case "`": {
        badChar = `reserved character ${source[0]}`;
        break;
      }
    }
    if (badChar)
      onError(0, "BAD_SCALAR_START", `Plain value cannot start with ${badChar}`);
    return unfoldLines(source);
  }
  function singleQuotedValue(source, onError) {
    if (source[source.length - 1] !== "'" || source.length === 1)
      onError(source.length, "MISSING_CHAR", "Missing closing 'quote");
    return unfoldLines(source.slice(1, -1)).replace(/''/g, "'");
  }
  function unfoldLines(source) {
    const line = /(.*?)\r?\n/sy;
    let match = line.exec(source);
    if (!match)
      return source;
    let trimEnd, trimBoth;
    try {
      trimEnd = new RegExp("(?<![ 	])[ 	]+$");
      trimBoth = new RegExp("^[ 	]+|(?<![ 	])[ 	]+$", "g");
    } catch {
      trimEnd = /[ \t]+$/;
      trimBoth = /^[ \t]+|[ \t]+$/g;
    }
    let res = match[1].replace(trimEnd, "");
    let sep = " ";
    let pos = line.lastIndex;
    while (match = line.exec(source)) {
      const lm = match[1].replace(trimBoth, "");
      if (lm === "") {
        if (sep === "\n")
          res += sep;
        else
          sep = "\n";
      } else {
        res += sep + lm;
        sep = " ";
      }
      pos = line.lastIndex;
    }
    const last = /[ \t]*(.*)/sy;
    last.lastIndex = pos;
    match = last.exec(source);
    return res + sep + (match?.[1] ?? "");
  }
  function doubleQuotedValue(source, onError) {
    let res = "";
    for (let i = 1; i < source.length - 1; ++i) {
      const ch = source[i];
      if (ch === "\r" && source[i + 1] === "\n")
        continue;
      if (ch === "\n") {
        const { fold, offset } = foldNewline(source, i);
        res += fold;
        i = offset;
      } else if (ch === "\\") {
        let next = source[++i];
        const cc = escapeCodes[next];
        if (cc)
          res += cc;
        else if (next === "\n") {
          next = source[i + 1];
          while (next === " " || next === "	")
            next = source[++i + 1];
        } else if (next === "\r" && source[i + 1] === "\n") {
          next = source[++i + 1];
          while (next === " " || next === "	")
            next = source[++i + 1];
        } else if (next === "x" || next === "u" || next === "U") {
          const length = next === "x" ? 2 : next === "u" ? 4 : 8;
          res += parseCharCode(source, i + 1, length, onError);
          i += length;
        } else {
          const raw = source.substr(i - 1, 2);
          onError(i - 1, "BAD_DQ_ESCAPE", `Invalid escape sequence ${raw}`);
          res += raw;
        }
      } else if (ch === " " || ch === "	") {
        const wsStart = i;
        let next = source[i + 1];
        while (next === " " || next === "	")
          next = source[++i + 1];
        if (next !== "\n" && !(next === "\r" && source[i + 2] === "\n"))
          res += i > wsStart ? source.slice(wsStart, i + 1) : ch;
      } else {
        res += ch;
      }
    }
    if (source[source.length - 1] !== '"' || source.length === 1)
      onError(source.length, "MISSING_CHAR", 'Missing closing "quote');
    return res;
  }
  function foldNewline(source, offset) {
    let fold = "";
    let ch = source[offset + 1];
    while (ch === " " || ch === "	" || ch === "\n" || ch === "\r") {
      if (ch === "\r" && source[offset + 2] !== "\n")
        break;
      if (ch === "\n")
        fold += "\n";
      offset += 1;
      ch = source[offset + 1];
    }
    if (!fold)
      fold = " ";
    return { fold, offset };
  }
  var escapeCodes = {
    "0": "\0",
    // null character
    a: "\x07",
    // bell character
    b: "\b",
    // backspace
    e: "\x1B",
    // escape character
    f: "\f",
    // form feed
    n: "\n",
    // line feed
    r: "\r",
    // carriage return
    t: "	",
    // horizontal tab
    v: "\v",
    // vertical tab
    N: "",
    // Unicode next line
    _: " ",
    // Unicode non-breaking space
    L: "\u2028",
    // Unicode line separator
    P: "\u2029",
    // Unicode paragraph separator
    " ": " ",
    '"': '"',
    "/": "/",
    "\\": "\\",
    "	": "	"
  };
  function parseCharCode(source, offset, length, onError) {
    const cc = source.substr(offset, length);
    const ok = cc.length === length && /^[0-9a-fA-F]+$/.test(cc);
    const code = ok ? parseInt(cc, 16) : NaN;
    try {
      return String.fromCodePoint(code);
    } catch {
      const raw = source.substr(offset - 2, length + 2);
      onError(offset - 2, "BAD_DQ_ESCAPE", `Invalid escape sequence ${raw}`);
      return raw;
    }
  }

  // node_modules/yaml/browser/dist/compose/compose-scalar.js
  function composeScalar(ctx, token, tagToken, onError) {
    const { value, type, comment, range } = token.type === "block-scalar" ? resolveBlockScalar(ctx, token, onError) : resolveFlowScalar(token, ctx.options.strict, onError);
    const tagName = tagToken ? ctx.directives.tagName(tagToken.source, (msg) => onError(tagToken, "TAG_RESOLVE_FAILED", msg)) : null;
    let tag;
    if (ctx.options.stringKeys && ctx.atKey) {
      tag = ctx.schema[SCALAR];
    } else if (tagName)
      tag = findScalarTagByName(ctx.schema, value, tagName, tagToken, onError);
    else if (token.type === "scalar")
      tag = findScalarTagByTest(ctx, value, token, onError);
    else
      tag = ctx.schema[SCALAR];
    let scalar;
    try {
      const res = tag.resolve(value, (msg) => onError(tagToken ?? token, "TAG_RESOLVE_FAILED", msg), ctx.options);
      scalar = isScalar(res) ? res : new Scalar(res);
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      onError(tagToken ?? token, "TAG_RESOLVE_FAILED", msg);
      scalar = new Scalar(value);
    }
    scalar.range = range;
    scalar.source = value;
    if (type)
      scalar.type = type;
    if (tagName)
      scalar.tag = tagName;
    if (tag.format)
      scalar.format = tag.format;
    if (comment)
      scalar.comment = comment;
    return scalar;
  }
  function findScalarTagByName(schema4, value, tagName, tagToken, onError) {
    if (tagName === "!")
      return schema4[SCALAR];
    const matchWithTest = [];
    for (const tag of schema4.tags) {
      if (!tag.collection && tag.tag === tagName) {
        if (tag.default && tag.test)
          matchWithTest.push(tag);
        else
          return tag;
      }
    }
    for (const tag of matchWithTest)
      if (tag.test?.test(value))
        return tag;
    const kt = schema4.knownTags[tagName];
    if (kt && !kt.collection) {
      schema4.tags.push(Object.assign({}, kt, { default: false, test: void 0 }));
      return kt;
    }
    onError(tagToken, "TAG_RESOLVE_FAILED", `Unresolved tag: ${tagName}`, tagName !== "tag:yaml.org,2002:str");
    return schema4[SCALAR];
  }
  function findScalarTagByTest({ atKey, directives, schema: schema4 }, value, token, onError) {
    const tag = schema4.tags.find((tag2) => (tag2.default === true || atKey && tag2.default === "key") && tag2.test?.test(value)) || schema4[SCALAR];
    if (schema4.compat) {
      const compat = schema4.compat.find((tag2) => tag2.default && tag2.test?.test(value)) ?? schema4[SCALAR];
      if (tag.tag !== compat.tag) {
        const ts = directives.tagString(tag.tag);
        const cs = directives.tagString(compat.tag);
        const msg = `Value may be parsed as either ${ts} or ${cs}`;
        onError(token, "TAG_RESOLVE_FAILED", msg, true);
      }
    }
    return tag;
  }

  // node_modules/yaml/browser/dist/compose/util-empty-scalar-position.js
  function emptyScalarPosition(offset, before, pos) {
    if (before) {
      pos ?? (pos = before.length);
      for (let i = pos - 1; i >= 0; --i) {
        let st = before[i];
        switch (st.type) {
          case "space":
          case "comment":
          case "newline":
            offset -= st.source.length;
            continue;
        }
        st = before[++i];
        while (st?.type === "space") {
          offset += st.source.length;
          st = before[++i];
        }
        break;
      }
    }
    return offset;
  }

  // node_modules/yaml/browser/dist/compose/compose-node.js
  var CN = { composeNode, composeEmptyNode };
  function composeNode(ctx, token, props, onError) {
    const atKey = ctx.atKey;
    const { spaceBefore, comment, anchor, tag } = props;
    let node;
    let isSrcToken = true;
    switch (token.type) {
      case "alias":
        node = composeAlias(ctx, token, onError);
        if (anchor || tag)
          onError(token, "ALIAS_PROPS", "An alias node must not specify any properties");
        break;
      case "scalar":
      case "single-quoted-scalar":
      case "double-quoted-scalar":
      case "block-scalar":
        node = composeScalar(ctx, token, tag, onError);
        if (anchor)
          node.anchor = anchor.source.substring(1);
        break;
      case "block-map":
      case "block-seq":
      case "flow-collection":
        try {
          node = composeCollection(CN, ctx, token, props, onError);
          if (anchor)
            node.anchor = anchor.source.substring(1);
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          onError(token, "RESOURCE_EXHAUSTION", message);
        }
        break;
      default: {
        const message = token.type === "error" ? token.message : `Unsupported token (type: ${token.type})`;
        onError(token, "UNEXPECTED_TOKEN", message);
        isSrcToken = false;
      }
    }
    node ?? (node = composeEmptyNode(ctx, token.offset, void 0, null, props, onError));
    if (anchor && node.anchor === "")
      onError(anchor, "BAD_ALIAS", "Anchor cannot be an empty string");
    if (atKey && ctx.options.stringKeys && (!isScalar(node) || typeof node.value !== "string" || node.tag && node.tag !== "tag:yaml.org,2002:str")) {
      const msg = "With stringKeys, all keys must be strings";
      onError(tag ?? token, "NON_STRING_KEY", msg);
    }
    if (spaceBefore)
      node.spaceBefore = true;
    if (comment) {
      if (token.type === "scalar" && token.source === "")
        node.comment = comment;
      else
        node.commentBefore = comment;
    }
    if (ctx.options.keepSourceTokens && isSrcToken)
      node.srcToken = token;
    return node;
  }
  function composeEmptyNode(ctx, offset, before, pos, { spaceBefore, comment, anchor, tag, end }, onError) {
    const token = {
      type: "scalar",
      offset: emptyScalarPosition(offset, before, pos),
      indent: -1,
      source: ""
    };
    const node = composeScalar(ctx, token, tag, onError);
    if (anchor) {
      node.anchor = anchor.source.substring(1);
      if (node.anchor === "")
        onError(anchor, "BAD_ALIAS", "Anchor cannot be an empty string");
    }
    if (spaceBefore)
      node.spaceBefore = true;
    if (comment) {
      node.comment = comment;
      node.range[2] = end;
    }
    return node;
  }
  function composeAlias({ options }, { offset, source, end }, onError) {
    const alias = new Alias(source.substring(1));
    if (alias.source === "")
      onError(offset, "BAD_ALIAS", "Alias cannot be an empty string");
    if (alias.source.endsWith(":"))
      onError(offset + source.length - 1, "BAD_ALIAS", "Alias ending in : is ambiguous", true);
    const valueEnd = offset + source.length;
    const re = resolveEnd(end, valueEnd, options.strict, onError);
    alias.range = [offset, valueEnd, re.offset];
    if (re.comment)
      alias.comment = re.comment;
    return alias;
  }

  // node_modules/yaml/browser/dist/compose/compose-doc.js
  function composeDoc(options, directives, { offset, start, value, end }, onError) {
    const opts = Object.assign({ _directives: directives }, options);
    const doc = new Document(void 0, opts);
    const ctx = {
      atKey: false,
      atRoot: true,
      directives: doc.directives,
      options: doc.options,
      schema: doc.schema
    };
    const props = resolveProps(start, {
      indicator: "doc-start",
      next: value ?? end?.[0],
      offset,
      onError,
      parentIndent: 0,
      startOnNewline: true
    });
    if (props.found) {
      doc.directives.docStart = true;
      if (value && (value.type === "block-map" || value.type === "block-seq") && !props.hasNewline)
        onError(props.end, "MISSING_CHAR", "Block collection cannot start on same line with directives-end marker");
    }
    doc.contents = value ? composeNode(ctx, value, props, onError) : composeEmptyNode(ctx, props.end, start, null, props, onError);
    const contentEnd = doc.contents.range[2];
    const re = resolveEnd(end, contentEnd, false, onError);
    if (re.comment)
      doc.comment = re.comment;
    doc.range = [offset, contentEnd, re.offset];
    return doc;
  }

  // node_modules/yaml/browser/dist/compose/composer.js
  function getErrorPos(src) {
    if (typeof src === "number")
      return [src, src + 1];
    if (Array.isArray(src))
      return src.length === 2 ? src : [src[0], src[1]];
    const { offset, source } = src;
    return [offset, offset + (typeof source === "string" ? source.length : 1)];
  }
  function parsePrelude(prelude) {
    let comment = "";
    let atComment = false;
    let afterEmptyLine = false;
    for (let i = 0; i < prelude.length; ++i) {
      const source = prelude[i];
      switch (source[0]) {
        case "#":
          comment += (comment === "" ? "" : afterEmptyLine ? "\n\n" : "\n") + (source.substring(1) || " ");
          atComment = true;
          afterEmptyLine = false;
          break;
        case "%":
          if (prelude[i + 1]?.[0] !== "#")
            i += 1;
          atComment = false;
          break;
        default:
          if (!atComment)
            afterEmptyLine = true;
          atComment = false;
      }
    }
    return { comment, afterEmptyLine };
  }
  var Composer = class {
    constructor(options = {}) {
      this.doc = null;
      this.atDirectives = false;
      this.prelude = [];
      this.errors = [];
      this.warnings = [];
      this.onError = (source, code, message, warning2) => {
        const pos = getErrorPos(source);
        if (warning2)
          this.warnings.push(new YAMLWarning(pos, code, message));
        else
          this.errors.push(new YAMLParseError(pos, code, message));
      };
      this.directives = new Directives({ version: options.version || "1.2" });
      this.options = options;
    }
    decorate(doc, afterDoc) {
      const { comment, afterEmptyLine } = parsePrelude(this.prelude);
      if (comment) {
        const dc = doc.contents;
        if (afterDoc) {
          doc.comment = doc.comment ? `${doc.comment}
${comment}` : comment;
        } else if (afterEmptyLine || doc.directives.docStart || !dc) {
          doc.commentBefore = comment;
        } else if (isCollection(dc) && !dc.flow && dc.items.length > 0) {
          let it = dc.items[0];
          if (isPair(it))
            it = it.key;
          const cb = it.commentBefore;
          it.commentBefore = cb ? `${comment}
${cb}` : comment;
        } else {
          const cb = dc.commentBefore;
          dc.commentBefore = cb ? `${comment}
${cb}` : comment;
        }
      }
      if (afterDoc) {
        for (let i = 0; i < this.errors.length; ++i)
          doc.errors.push(this.errors[i]);
        for (let i = 0; i < this.warnings.length; ++i)
          doc.warnings.push(this.warnings[i]);
      } else {
        doc.errors = this.errors;
        doc.warnings = this.warnings;
      }
      this.prelude = [];
      this.errors = [];
      this.warnings = [];
    }
    /**
     * Current stream status information.
     *
     * Mostly useful at the end of input for an empty stream.
     */
    streamInfo() {
      return {
        comment: parsePrelude(this.prelude).comment,
        directives: this.directives,
        errors: this.errors,
        warnings: this.warnings
      };
    }
    /**
     * Compose tokens into documents.
     *
     * @param forceDoc - If the stream contains no document, still emit a final document including any comments and directives that would be applied to a subsequent document.
     * @param endOffset - Should be set if `forceDoc` is also set, to set the document range end and to indicate errors correctly.
     */
    *compose(tokens, forceDoc = false, endOffset = -1) {
      for (const token of tokens)
        yield* this.next(token);
      yield* this.end(forceDoc, endOffset);
    }
    /** Advance the composer by one CST token. */
    *next(token) {
      switch (token.type) {
        case "directive":
          this.directives.add(token.source, (offset, message, warning2) => {
            const pos = getErrorPos(token);
            pos[0] += offset;
            this.onError(pos, "BAD_DIRECTIVE", message, warning2);
          });
          this.prelude.push(token.source);
          this.atDirectives = true;
          break;
        case "document": {
          const doc = composeDoc(this.options, this.directives, token, this.onError);
          if (this.atDirectives && !doc.directives.docStart)
            this.onError(token, "MISSING_CHAR", "Missing directives-end/doc-start indicator line");
          this.decorate(doc, false);
          if (this.doc)
            yield this.doc;
          this.doc = doc;
          this.atDirectives = false;
          break;
        }
        case "byte-order-mark":
        case "space":
          break;
        case "comment":
        case "newline":
          this.prelude.push(token.source);
          break;
        case "error": {
          const msg = token.source ? `${token.message}: ${JSON.stringify(token.source)}` : token.message;
          const error = new YAMLParseError(getErrorPos(token), "UNEXPECTED_TOKEN", msg);
          if (this.atDirectives || !this.doc)
            this.errors.push(error);
          else
            this.doc.errors.push(error);
          break;
        }
        case "doc-end": {
          if (!this.doc) {
            const msg = "Unexpected doc-end without preceding document";
            this.errors.push(new YAMLParseError(getErrorPos(token), "UNEXPECTED_TOKEN", msg));
            break;
          }
          this.doc.directives.docEnd = true;
          const end = resolveEnd(token.end, token.offset + token.source.length, this.doc.options.strict, this.onError);
          this.decorate(this.doc, true);
          if (end.comment) {
            const dc = this.doc.comment;
            this.doc.comment = dc ? `${dc}
${end.comment}` : end.comment;
          }
          this.doc.range[2] = end.offset;
          break;
        }
        default:
          this.errors.push(new YAMLParseError(getErrorPos(token), "UNEXPECTED_TOKEN", `Unsupported token ${token.type}`));
      }
    }
    /**
     * Call at end of input to yield any remaining document.
     *
     * @param forceDoc - If the stream contains no document, still emit a final document including any comments and directives that would be applied to a subsequent document.
     * @param endOffset - Should be set if `forceDoc` is also set, to set the document range end and to indicate errors correctly.
     */
    *end(forceDoc = false, endOffset = -1) {
      if (this.doc) {
        this.decorate(this.doc, true);
        yield this.doc;
        this.doc = null;
      } else if (forceDoc) {
        const opts = Object.assign({ _directives: this.directives }, this.options);
        const doc = new Document(void 0, opts);
        if (this.atDirectives)
          this.onError(endOffset, "MISSING_CHAR", "Missing directives-end indicator line");
        doc.range = [0, endOffset, endOffset];
        this.decorate(doc, false);
        yield doc;
      }
    }
  };

  // node_modules/yaml/browser/dist/parse/cst-visit.js
  var BREAK2 = Symbol("break visit");
  var SKIP2 = Symbol("skip children");
  var REMOVE2 = Symbol("remove item");
  function visit3(cst, visitor) {
    if ("type" in cst && cst.type === "document")
      cst = { start: cst.start, value: cst.value };
    _visit(Object.freeze([]), cst, visitor);
  }
  visit3.BREAK = BREAK2;
  visit3.SKIP = SKIP2;
  visit3.REMOVE = REMOVE2;
  visit3.itemAtPath = (cst, path) => {
    let item = cst;
    for (const [field, index] of path) {
      const tok = item?.[field];
      if (tok && "items" in tok) {
        item = tok.items[index];
      } else
        return void 0;
    }
    return item;
  };
  visit3.parentCollection = (cst, path) => {
    const parent = visit3.itemAtPath(cst, path.slice(0, -1));
    const field = path[path.length - 1][0];
    const coll = parent?.[field];
    if (coll && "items" in coll)
      return coll;
    throw new Error("Parent collection not found");
  };
  function _visit(path, item, visitor) {
    let ctrl = visitor(item, path);
    if (typeof ctrl === "symbol")
      return ctrl;
    for (const field of ["key", "value"]) {
      const token = item[field];
      if (token && "items" in token) {
        for (let i = 0; i < token.items.length; ++i) {
          const ci = _visit(Object.freeze(path.concat([[field, i]])), token.items[i], visitor);
          if (typeof ci === "number")
            i = ci - 1;
          else if (ci === BREAK2)
            return BREAK2;
          else if (ci === REMOVE2) {
            token.items.splice(i, 1);
            i -= 1;
          }
        }
        if (typeof ctrl === "function" && field === "key")
          ctrl = ctrl(item, path);
      }
    }
    return typeof ctrl === "function" ? ctrl(item, path) : ctrl;
  }

  // node_modules/yaml/browser/dist/parse/cst.js
  var BOM = "\uFEFF";
  var DOCUMENT = "";
  var FLOW_END = "";
  var SCALAR2 = "";
  function tokenType(source) {
    switch (source) {
      case BOM:
        return "byte-order-mark";
      case DOCUMENT:
        return "doc-mode";
      case FLOW_END:
        return "flow-error-end";
      case SCALAR2:
        return "scalar";
      case "---":
        return "doc-start";
      case "...":
        return "doc-end";
      case "":
      case "\n":
      case "\r\n":
        return "newline";
      case "-":
        return "seq-item-ind";
      case "?":
        return "explicit-key-ind";
      case ":":
        return "map-value-ind";
      case "{":
        return "flow-map-start";
      case "}":
        return "flow-map-end";
      case "[":
        return "flow-seq-start";
      case "]":
        return "flow-seq-end";
      case ",":
        return "comma";
    }
    switch (source[0]) {
      case " ":
      case "	":
        return "space";
      case "#":
        return "comment";
      case "%":
        return "directive-line";
      case "*":
        return "alias";
      case "&":
        return "anchor";
      case "!":
        return "tag";
      case "'":
        return "single-quoted-scalar";
      case '"':
        return "double-quoted-scalar";
      case "|":
      case ">":
        return "block-scalar-header";
    }
    return null;
  }

  // node_modules/yaml/browser/dist/parse/lexer.js
  function isEmpty(ch) {
    switch (ch) {
      case void 0:
      case " ":
      case "\n":
      case "\r":
      case "	":
        return true;
      default:
        return false;
    }
  }
  var hexDigits = new Set("0123456789ABCDEFabcdef");
  var tagChars = new Set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-#;/?:@&=+$_.!~*'()");
  var flowIndicatorChars = new Set(",[]{}");
  var invalidAnchorChars = new Set(" ,[]{}\n\r	");
  var isNotAnchorChar = (ch) => !ch || invalidAnchorChars.has(ch);
  var Lexer = class {
    constructor() {
      this.atEnd = false;
      this.blockScalarIndent = -1;
      this.blockScalarKeep = false;
      this.buffer = "";
      this.flowKey = false;
      this.flowLevel = 0;
      this.indentNext = 0;
      this.indentValue = 0;
      this.lineEndPos = null;
      this.next = null;
      this.pos = 0;
    }
    /**
     * Generate YAML tokens from the `source` string. If `incomplete`,
     * a part of the last line may be left as a buffer for the next call.
     *
     * @returns A generator of lexical tokens
     */
    *lex(source, incomplete = false) {
      if (source) {
        if (typeof source !== "string")
          throw TypeError("source is not a string");
        this.buffer = this.buffer ? this.buffer + source : source;
        this.lineEndPos = null;
      }
      this.atEnd = !incomplete;
      let next = this.next ?? "stream";
      while (next && (incomplete || this.hasChars(1)))
        next = yield* this.parseNext(next);
    }
    atLineEnd() {
      let i = this.pos;
      let ch = this.buffer[i];
      while (ch === " " || ch === "	")
        ch = this.buffer[++i];
      if (!ch || ch === "#" || ch === "\n")
        return true;
      if (ch === "\r")
        return this.buffer[i + 1] === "\n";
      return false;
    }
    charAt(n) {
      return this.buffer[this.pos + n];
    }
    continueScalar(offset) {
      let ch = this.buffer[offset];
      if (this.indentNext > 0) {
        let indent = 0;
        while (ch === " ")
          ch = this.buffer[++indent + offset];
        if (ch === "\r") {
          const next = this.buffer[indent + offset + 1];
          if (next === "\n" || !next && !this.atEnd)
            return offset + indent + 1;
        }
        return ch === "\n" || indent >= this.indentNext || !ch && !this.atEnd ? offset + indent : -1;
      }
      if (ch === "-" || ch === ".") {
        const dt = this.buffer.substr(offset, 3);
        if ((dt === "---" || dt === "...") && isEmpty(this.buffer[offset + 3]))
          return -1;
      }
      return offset;
    }
    getLine() {
      let end = this.lineEndPos;
      if (typeof end !== "number" || end !== -1 && end < this.pos) {
        end = this.buffer.indexOf("\n", this.pos);
        this.lineEndPos = end;
      }
      if (end === -1)
        return this.atEnd ? this.buffer.substring(this.pos) : null;
      if (this.buffer[end - 1] === "\r")
        end -= 1;
      return this.buffer.substring(this.pos, end);
    }
    hasChars(n) {
      return this.pos + n <= this.buffer.length;
    }
    setNext(state) {
      this.buffer = this.buffer.substring(this.pos);
      this.pos = 0;
      this.lineEndPos = null;
      this.next = state;
      return null;
    }
    peek(n) {
      return this.buffer.substr(this.pos, n);
    }
    *parseNext(next) {
      switch (next) {
        case "stream":
          return yield* this.parseStream();
        case "line-start":
          return yield* this.parseLineStart();
        case "block-start":
          return yield* this.parseBlockStart();
        case "doc":
          return yield* this.parseDocument();
        case "flow":
          return yield* this.parseFlowCollection();
        case "quoted-scalar":
          return yield* this.parseQuotedScalar();
        case "block-scalar":
          return yield* this.parseBlockScalar();
        case "plain-scalar":
          return yield* this.parsePlainScalar();
      }
    }
    *parseStream() {
      let line = this.getLine();
      if (line === null)
        return this.setNext("stream");
      if (line[0] === BOM) {
        yield* this.pushCount(1);
        line = line.substring(1);
      }
      if (line[0] === "%") {
        let dirEnd = line.length;
        let cs = line.indexOf("#");
        while (cs !== -1) {
          const ch = line[cs - 1];
          if (ch === " " || ch === "	") {
            dirEnd = cs - 1;
            break;
          } else {
            cs = line.indexOf("#", cs + 1);
          }
        }
        while (true) {
          const ch = line[dirEnd - 1];
          if (ch === " " || ch === "	")
            dirEnd -= 1;
          else
            break;
        }
        const n = (yield* this.pushCount(dirEnd)) + (yield* this.pushSpaces(true));
        yield* this.pushCount(line.length - n);
        this.pushNewline();
        return "stream";
      }
      if (this.atLineEnd()) {
        const sp = yield* this.pushSpaces(true);
        yield* this.pushCount(line.length - sp);
        yield* this.pushNewline();
        return "stream";
      }
      yield DOCUMENT;
      return yield* this.parseLineStart();
    }
    *parseLineStart() {
      const ch = this.charAt(0);
      if (!ch && !this.atEnd)
        return this.setNext("line-start");
      if (ch === "-" || ch === ".") {
        if (!this.atEnd && !this.hasChars(4))
          return this.setNext("line-start");
        const s = this.peek(3);
        if ((s === "---" || s === "...") && isEmpty(this.charAt(3))) {
          yield* this.pushCount(3);
          this.indentValue = 0;
          this.indentNext = 0;
          return s === "---" ? "doc" : "stream";
        }
      }
      this.indentValue = yield* this.pushSpaces(false);
      if (this.indentNext > this.indentValue && !isEmpty(this.charAt(1)))
        this.indentNext = this.indentValue;
      return yield* this.parseBlockStart();
    }
    *parseBlockStart() {
      const [ch0, ch1] = this.peek(2);
      if (!ch1 && !this.atEnd)
        return this.setNext("block-start");
      if ((ch0 === "-" || ch0 === "?" || ch0 === ":") && isEmpty(ch1)) {
        const n = (yield* this.pushCount(1)) + (yield* this.pushSpaces(true));
        this.indentNext = this.indentValue + 1;
        this.indentValue += n;
        return "block-start";
      }
      return "doc";
    }
    *parseDocument() {
      yield* this.pushSpaces(true);
      const line = this.getLine();
      if (line === null)
        return this.setNext("doc");
      let n = yield* this.pushIndicators();
      switch (line[n]) {
        case "#":
          yield* this.pushCount(line.length - n);
        // fallthrough
        case void 0:
          yield* this.pushNewline();
          return yield* this.parseLineStart();
        case "{":
        case "[":
          yield* this.pushCount(1);
          this.flowKey = false;
          this.flowLevel = 1;
          return "flow";
        case "}":
        case "]":
          yield* this.pushCount(1);
          return "doc";
        case "*":
          yield* this.pushUntil(isNotAnchorChar);
          return "doc";
        case '"':
        case "'":
          return yield* this.parseQuotedScalar();
        case "|":
        case ">":
          n += yield* this.parseBlockScalarHeader();
          n += yield* this.pushSpaces(true);
          yield* this.pushCount(line.length - n);
          yield* this.pushNewline();
          return yield* this.parseBlockScalar();
        default:
          return yield* this.parsePlainScalar();
      }
    }
    *parseFlowCollection() {
      let nl, sp;
      let indent = -1;
      do {
        nl = yield* this.pushNewline();
        if (nl > 0) {
          sp = yield* this.pushSpaces(false);
          this.indentValue = indent = sp;
        } else {
          sp = 0;
        }
        sp += yield* this.pushSpaces(true);
      } while (nl + sp > 0);
      const line = this.getLine();
      if (line === null)
        return this.setNext("flow");
      if (indent !== -1 && indent < this.indentNext && line[0] !== "#" || indent === 0 && (line.startsWith("---") || line.startsWith("...")) && isEmpty(line[3])) {
        const atFlowEndMarker = indent === this.indentNext - 1 && this.flowLevel === 1 && (line[0] === "]" || line[0] === "}");
        if (!atFlowEndMarker) {
          this.flowLevel = 0;
          yield FLOW_END;
          return yield* this.parseLineStart();
        }
      }
      let n = 0;
      while (line[n] === ",") {
        n += yield* this.pushCount(1);
        n += yield* this.pushSpaces(true);
        this.flowKey = false;
      }
      n += yield* this.pushIndicators();
      switch (line[n]) {
        case void 0:
          return "flow";
        case "#":
          yield* this.pushCount(line.length - n);
          return "flow";
        case "{":
        case "[":
          yield* this.pushCount(1);
          this.flowKey = false;
          this.flowLevel += 1;
          return "flow";
        case "}":
        case "]":
          yield* this.pushCount(1);
          this.flowKey = true;
          this.flowLevel -= 1;
          return this.flowLevel ? "flow" : "doc";
        case "*":
          yield* this.pushUntil(isNotAnchorChar);
          return "flow";
        case '"':
        case "'":
          this.flowKey = true;
          return yield* this.parseQuotedScalar();
        case ":": {
          const next = this.charAt(1);
          if (this.flowKey || isEmpty(next) || next === ",") {
            this.flowKey = false;
            yield* this.pushCount(1);
            yield* this.pushSpaces(true);
            return "flow";
          }
        }
        // fallthrough
        default:
          this.flowKey = false;
          return yield* this.parsePlainScalar();
      }
    }
    *parseQuotedScalar() {
      const quote = this.charAt(0);
      let end = this.buffer.indexOf(quote, this.pos + 1);
      if (quote === "'") {
        while (end !== -1 && this.buffer[end + 1] === "'")
          end = this.buffer.indexOf("'", end + 2);
      } else {
        while (end !== -1) {
          let n = 0;
          while (this.buffer[end - 1 - n] === "\\")
            n += 1;
          if (n % 2 === 0)
            break;
          end = this.buffer.indexOf('"', end + 1);
        }
      }
      const qb = this.buffer.substring(0, end);
      let nl = qb.indexOf("\n", this.pos);
      if (nl !== -1) {
        while (nl !== -1) {
          const cs = this.continueScalar(nl + 1);
          if (cs === -1)
            break;
          nl = qb.indexOf("\n", cs);
        }
        if (nl !== -1) {
          end = nl - (qb[nl - 1] === "\r" ? 2 : 1);
        }
      }
      if (end === -1) {
        if (!this.atEnd)
          return this.setNext("quoted-scalar");
        end = this.buffer.length;
      }
      yield* this.pushToIndex(end + 1, false);
      return this.flowLevel ? "flow" : "doc";
    }
    *parseBlockScalarHeader() {
      this.blockScalarIndent = -1;
      this.blockScalarKeep = false;
      let i = this.pos;
      while (true) {
        const ch = this.buffer[++i];
        if (ch === "+")
          this.blockScalarKeep = true;
        else if (ch > "0" && ch <= "9")
          this.blockScalarIndent = Number(ch) - 1;
        else if (ch !== "-")
          break;
      }
      return yield* this.pushUntil((ch) => isEmpty(ch) || ch === "#");
    }
    *parseBlockScalar() {
      let nl = this.pos - 1;
      let indent = 0;
      let ch;
      loop: for (let i2 = this.pos; ch = this.buffer[i2]; ++i2) {
        switch (ch) {
          case " ":
            indent += 1;
            break;
          case "\n":
            nl = i2;
            indent = 0;
            break;
          case "\r": {
            const next = this.buffer[i2 + 1];
            if (!next && !this.atEnd)
              return this.setNext("block-scalar");
            if (next === "\n")
              break;
          }
          // fallthrough
          default:
            break loop;
        }
      }
      if (!ch && !this.atEnd)
        return this.setNext("block-scalar");
      if (indent >= this.indentNext) {
        if (this.blockScalarIndent === -1)
          this.indentNext = indent;
        else {
          this.indentNext = this.blockScalarIndent + (this.indentNext === 0 ? 1 : this.indentNext);
        }
        do {
          const cs = this.continueScalar(nl + 1);
          if (cs === -1)
            break;
          nl = this.buffer.indexOf("\n", cs);
        } while (nl !== -1);
        if (nl === -1) {
          if (!this.atEnd)
            return this.setNext("block-scalar");
          nl = this.buffer.length;
        }
      }
      let i = nl + 1;
      ch = this.buffer[i];
      while (ch === " ")
        ch = this.buffer[++i];
      if (ch === "	") {
        while (ch === "	" || ch === " " || ch === "\r" || ch === "\n")
          ch = this.buffer[++i];
        nl = i - 1;
      } else if (!this.blockScalarKeep) {
        do {
          let i2 = nl - 1;
          let ch2 = this.buffer[i2];
          if (ch2 === "\r")
            ch2 = this.buffer[--i2];
          const lastChar = i2;
          while (ch2 === " ")
            ch2 = this.buffer[--i2];
          if (ch2 === "\n" && i2 >= this.pos && i2 + 1 + indent > lastChar)
            nl = i2;
          else
            break;
        } while (true);
      }
      yield SCALAR2;
      yield* this.pushToIndex(nl + 1, true);
      return yield* this.parseLineStart();
    }
    *parsePlainScalar() {
      const inFlow = this.flowLevel > 0;
      let end = this.pos - 1;
      let i = this.pos - 1;
      let ch;
      while (ch = this.buffer[++i]) {
        if (ch === ":") {
          const next = this.buffer[i + 1];
          if (isEmpty(next) || inFlow && flowIndicatorChars.has(next))
            break;
          end = i;
        } else if (isEmpty(ch)) {
          let next = this.buffer[i + 1];
          if (ch === "\r") {
            if (next === "\n") {
              i += 1;
              ch = "\n";
              next = this.buffer[i + 1];
            } else
              end = i;
          }
          if (next === "#" || inFlow && flowIndicatorChars.has(next))
            break;
          if (ch === "\n") {
            const cs = this.continueScalar(i + 1);
            if (cs === -1)
              break;
            i = Math.max(i, cs - 2);
          }
        } else {
          if (inFlow && flowIndicatorChars.has(ch))
            break;
          end = i;
        }
      }
      if (!ch && !this.atEnd)
        return this.setNext("plain-scalar");
      yield SCALAR2;
      yield* this.pushToIndex(end + 1, true);
      return inFlow ? "flow" : "doc";
    }
    *pushCount(n) {
      if (n > 0) {
        yield this.buffer.substr(this.pos, n);
        this.pos += n;
        return n;
      }
      return 0;
    }
    *pushToIndex(i, allowEmpty) {
      const s = this.buffer.slice(this.pos, i);
      if (s) {
        yield s;
        this.pos += s.length;
        return s.length;
      } else if (allowEmpty)
        yield "";
      return 0;
    }
    *pushIndicators() {
      let n = 0;
      loop: while (true) {
        switch (this.charAt(0)) {
          case "!":
            n += yield* this.pushTag();
            n += yield* this.pushSpaces(true);
            continue loop;
          case "&":
            n += yield* this.pushUntil(isNotAnchorChar);
            n += yield* this.pushSpaces(true);
            continue loop;
          case "-":
          // this is an error
          case "?":
          // this is an error outside flow collections
          case ":": {
            const inFlow = this.flowLevel > 0;
            const ch1 = this.charAt(1);
            if (isEmpty(ch1) || inFlow && flowIndicatorChars.has(ch1)) {
              if (!inFlow)
                this.indentNext = this.indentValue + 1;
              else if (this.flowKey)
                this.flowKey = false;
              n += yield* this.pushCount(1);
              n += yield* this.pushSpaces(true);
              continue loop;
            }
          }
        }
        break loop;
      }
      return n;
    }
    *pushTag() {
      if (this.charAt(1) === "<") {
        let i = this.pos + 2;
        let ch = this.buffer[i];
        while (!isEmpty(ch) && ch !== ">")
          ch = this.buffer[++i];
        return yield* this.pushToIndex(ch === ">" ? i + 1 : i, false);
      } else {
        let i = this.pos + 1;
        let ch = this.buffer[i];
        while (ch) {
          if (tagChars.has(ch))
            ch = this.buffer[++i];
          else if (ch === "%" && hexDigits.has(this.buffer[i + 1]) && hexDigits.has(this.buffer[i + 2])) {
            ch = this.buffer[i += 3];
          } else
            break;
        }
        return yield* this.pushToIndex(i, false);
      }
    }
    *pushNewline() {
      const ch = this.buffer[this.pos];
      if (ch === "\n")
        return yield* this.pushCount(1);
      else if (ch === "\r" && this.charAt(1) === "\n")
        return yield* this.pushCount(2);
      else
        return 0;
    }
    *pushSpaces(allowTabs) {
      let i = this.pos - 1;
      let ch;
      do {
        ch = this.buffer[++i];
      } while (ch === " " || allowTabs && ch === "	");
      const n = i - this.pos;
      if (n > 0) {
        yield this.buffer.substr(this.pos, n);
        this.pos = i;
      }
      return n;
    }
    *pushUntil(test) {
      let i = this.pos;
      let ch = this.buffer[i];
      while (!test(ch))
        ch = this.buffer[++i];
      return yield* this.pushToIndex(i, false);
    }
  };

  // node_modules/yaml/browser/dist/parse/line-counter.js
  var LineCounter = class {
    constructor() {
      this.lineStarts = [];
      this.addNewLine = (offset) => this.lineStarts.push(offset);
      this.linePos = (offset) => {
        let low = 0;
        let high = this.lineStarts.length;
        while (low < high) {
          const mid = low + high >> 1;
          if (this.lineStarts[mid] < offset)
            low = mid + 1;
          else
            high = mid;
        }
        if (this.lineStarts[low] === offset)
          return { line: low + 1, col: 1 };
        if (low === 0)
          return { line: 0, col: offset };
        const start = this.lineStarts[low - 1];
        return { line: low, col: offset - start + 1 };
      };
    }
  };

  // node_modules/yaml/browser/dist/parse/parser.js
  function includesToken(list2, type) {
    for (let i = 0; i < list2.length; ++i)
      if (list2[i].type === type)
        return true;
    return false;
  }
  function findNonEmptyIndex(list2) {
    for (let i = 0; i < list2.length; ++i) {
      switch (list2[i].type) {
        case "space":
        case "comment":
        case "newline":
          break;
        default:
          return i;
      }
    }
    return -1;
  }
  function isFlowToken(token) {
    switch (token?.type) {
      case "alias":
      case "scalar":
      case "single-quoted-scalar":
      case "double-quoted-scalar":
      case "flow-collection":
        return true;
      default:
        return false;
    }
  }
  function getPrevProps(parent) {
    switch (parent.type) {
      case "document":
        return parent.start;
      case "block-map": {
        const it = parent.items[parent.items.length - 1];
        return it.sep ?? it.start;
      }
      case "block-seq":
        return parent.items[parent.items.length - 1].start;
      /* istanbul ignore next should not happen */
      default:
        return [];
    }
  }
  function getFirstKeyStartProps(prev) {
    if (prev.length === 0)
      return [];
    let i = prev.length;
    loop: while (--i >= 0) {
      switch (prev[i].type) {
        case "doc-start":
        case "explicit-key-ind":
        case "map-value-ind":
        case "seq-item-ind":
        case "newline":
          break loop;
      }
    }
    while (prev[++i]?.type === "space") {
    }
    return prev.splice(i, prev.length);
  }
  function arrayPushArray(target, source) {
    if (source.length < 1e5)
      Array.prototype.push.apply(target, source);
    else
      for (let i = 0; i < source.length; ++i)
        target.push(source[i]);
  }
  function fixFlowSeqItems(fc) {
    if (fc.start.type === "flow-seq-start") {
      for (const it of fc.items) {
        if (it.sep && !it.value && !includesToken(it.start, "explicit-key-ind") && !includesToken(it.sep, "map-value-ind")) {
          if (it.key)
            it.value = it.key;
          delete it.key;
          if (isFlowToken(it.value)) {
            if (it.value.end)
              arrayPushArray(it.value.end, it.sep);
            else
              it.value.end = it.sep;
          } else
            arrayPushArray(it.start, it.sep);
          delete it.sep;
        }
      }
    }
  }
  var Parser = class {
    /**
     * @param onNewLine - If defined, called separately with the start position of
     *   each new line (in `parse()`, including the start of input).
     */
    constructor(onNewLine) {
      this.atNewLine = true;
      this.atScalar = false;
      this.indent = 0;
      this.offset = 0;
      this.onKeyLine = false;
      this.stack = [];
      this.source = "";
      this.type = "";
      this.lexer = new Lexer();
      this.onNewLine = onNewLine;
    }
    /**
     * Parse `source` as a YAML stream.
     * If `incomplete`, a part of the last line may be left as a buffer for the next call.
     *
     * Errors are not thrown, but yielded as `{ type: 'error', message }` tokens.
     *
     * @returns A generator of tokens representing each directive, document, and other structure.
     */
    *parse(source, incomplete = false) {
      if (this.onNewLine && this.offset === 0)
        this.onNewLine(0);
      for (const lexeme of this.lexer.lex(source, incomplete))
        yield* this.next(lexeme);
      if (!incomplete)
        yield* this.end();
    }
    /**
     * Advance the parser by the `source` of one lexical token.
     */
    *next(source) {
      this.source = source;
      if (this.atScalar) {
        this.atScalar = false;
        yield* this.step();
        this.offset += source.length;
        return;
      }
      const type = tokenType(source);
      if (!type) {
        const message = `Not a YAML token: ${source}`;
        yield* this.pop({ type: "error", offset: this.offset, message, source });
        this.offset += source.length;
      } else if (type === "scalar") {
        this.atNewLine = false;
        this.atScalar = true;
        this.type = "scalar";
      } else {
        this.type = type;
        yield* this.step();
        switch (type) {
          case "newline":
            this.atNewLine = true;
            this.indent = 0;
            if (this.onNewLine)
              this.onNewLine(this.offset + source.length);
            break;
          case "space":
            if (this.atNewLine && source[0] === " ")
              this.indent += source.length;
            break;
          case "explicit-key-ind":
          case "map-value-ind":
          case "seq-item-ind":
            if (this.atNewLine)
              this.indent += source.length;
            break;
          case "doc-mode":
          case "flow-error-end":
            return;
          default:
            this.atNewLine = false;
        }
        this.offset += source.length;
      }
    }
    /** Call at end of input to push out any remaining constructions */
    *end() {
      while (this.stack.length > 0)
        yield* this.pop();
    }
    get sourceToken() {
      const st = {
        type: this.type,
        offset: this.offset,
        indent: this.indent,
        source: this.source
      };
      return st;
    }
    *step() {
      const top = this.peek(1);
      if (this.type === "doc-end" && top?.type !== "doc-end") {
        while (this.stack.length > 0)
          yield* this.pop();
        this.stack.push({
          type: "doc-end",
          offset: this.offset,
          source: this.source
        });
        return;
      }
      if (!top)
        return yield* this.stream();
      switch (top.type) {
        case "document":
          return yield* this.document(top);
        case "alias":
        case "scalar":
        case "single-quoted-scalar":
        case "double-quoted-scalar":
          return yield* this.scalar(top);
        case "block-scalar":
          return yield* this.blockScalar(top);
        case "block-map":
          return yield* this.blockMap(top);
        case "block-seq":
          return yield* this.blockSequence(top);
        case "flow-collection":
          return yield* this.flowCollection(top);
        case "doc-end":
          return yield* this.documentEnd(top);
      }
      yield* this.pop();
    }
    peek(n) {
      return this.stack[this.stack.length - n];
    }
    *pop(error) {
      const token = error ?? this.stack.pop();
      if (!token) {
        const message = "Tried to pop an empty stack";
        yield { type: "error", offset: this.offset, source: "", message };
      } else if (this.stack.length === 0) {
        yield token;
      } else {
        const top = this.peek(1);
        if (token.type === "block-scalar") {
          token.indent = "indent" in top ? top.indent : 0;
        } else if (token.type === "flow-collection" && top.type === "document") {
          token.indent = 0;
        }
        if (token.type === "flow-collection")
          fixFlowSeqItems(token);
        switch (top.type) {
          case "document":
            top.value = token;
            break;
          case "block-scalar":
            top.props.push(token);
            break;
          case "block-map": {
            const it = top.items[top.items.length - 1];
            if (it.value) {
              top.items.push({ start: [], key: token, sep: [] });
              this.onKeyLine = true;
              return;
            } else if (it.sep) {
              it.value = token;
            } else {
              Object.assign(it, { key: token, sep: [] });
              this.onKeyLine = !it.explicitKey;
              return;
            }
            break;
          }
          case "block-seq": {
            const it = top.items[top.items.length - 1];
            if (it.value)
              top.items.push({ start: [], value: token });
            else
              it.value = token;
            break;
          }
          case "flow-collection": {
            const it = top.items[top.items.length - 1];
            if (!it || it.value)
              top.items.push({ start: [], key: token, sep: [] });
            else if (it.sep)
              it.value = token;
            else
              Object.assign(it, { key: token, sep: [] });
            return;
          }
          /* istanbul ignore next should not happen */
          default:
            yield* this.pop();
            yield* this.pop(token);
        }
        if ((top.type === "document" || top.type === "block-map" || top.type === "block-seq") && (token.type === "block-map" || token.type === "block-seq")) {
          const last = token.items[token.items.length - 1];
          if (last && !last.sep && !last.value && last.start.length > 0 && findNonEmptyIndex(last.start) === -1 && (token.indent === 0 || last.start.every((st) => st.type !== "comment" || st.indent < token.indent))) {
            if (top.type === "document")
              top.end = last.start;
            else
              top.items.push({ start: last.start });
            token.items.splice(-1, 1);
          }
        }
      }
    }
    *stream() {
      switch (this.type) {
        case "directive-line":
          yield { type: "directive", offset: this.offset, source: this.source };
          return;
        case "byte-order-mark":
        case "space":
        case "comment":
        case "newline":
          yield this.sourceToken;
          return;
        case "doc-mode":
        case "doc-start": {
          const doc = {
            type: "document",
            offset: this.offset,
            start: []
          };
          if (this.type === "doc-start")
            doc.start.push(this.sourceToken);
          this.stack.push(doc);
          return;
        }
      }
      yield {
        type: "error",
        offset: this.offset,
        message: `Unexpected ${this.type} token in YAML stream`,
        source: this.source
      };
    }
    *document(doc) {
      if (doc.value)
        return yield* this.lineEnd(doc);
      switch (this.type) {
        case "doc-start": {
          if (findNonEmptyIndex(doc.start) !== -1) {
            yield* this.pop();
            yield* this.step();
          } else
            doc.start.push(this.sourceToken);
          return;
        }
        case "anchor":
        case "tag":
        case "space":
        case "comment":
        case "newline":
          doc.start.push(this.sourceToken);
          return;
      }
      const bv = this.startBlockValue(doc);
      if (bv)
        this.stack.push(bv);
      else {
        yield {
          type: "error",
          offset: this.offset,
          message: `Unexpected ${this.type} token in YAML document`,
          source: this.source
        };
      }
    }
    *scalar(scalar) {
      if (this.type === "map-value-ind") {
        const prev = getPrevProps(this.peek(2));
        const start = getFirstKeyStartProps(prev);
        let sep;
        if (scalar.end) {
          sep = scalar.end;
          sep.push(this.sourceToken);
          delete scalar.end;
        } else
          sep = [this.sourceToken];
        const map2 = {
          type: "block-map",
          offset: scalar.offset,
          indent: scalar.indent,
          items: [{ start, key: scalar, sep }]
        };
        this.onKeyLine = true;
        this.stack[this.stack.length - 1] = map2;
      } else
        yield* this.lineEnd(scalar);
    }
    *blockScalar(scalar) {
      switch (this.type) {
        case "space":
        case "comment":
        case "newline":
          scalar.props.push(this.sourceToken);
          return;
        case "scalar":
          scalar.source = this.source;
          this.atNewLine = true;
          this.indent = 0;
          if (this.onNewLine) {
            let nl = this.source.indexOf("\n") + 1;
            while (nl !== 0) {
              this.onNewLine(this.offset + nl);
              nl = this.source.indexOf("\n", nl) + 1;
            }
          }
          yield* this.pop();
          break;
        /* istanbul ignore next should not happen */
        default:
          yield* this.pop();
          yield* this.step();
      }
    }
    *blockMap(map2) {
      const it = map2.items[map2.items.length - 1];
      switch (this.type) {
        case "newline":
          this.onKeyLine = false;
          if (it.value) {
            const end = "end" in it.value ? it.value.end : void 0;
            const last = Array.isArray(end) ? end[end.length - 1] : void 0;
            if (last?.type === "comment")
              end?.push(this.sourceToken);
            else
              map2.items.push({ start: [this.sourceToken] });
          } else if (it.sep) {
            it.sep.push(this.sourceToken);
          } else {
            it.start.push(this.sourceToken);
          }
          return;
        case "space":
        case "comment":
          if (it.value) {
            map2.items.push({ start: [this.sourceToken] });
          } else if (it.sep) {
            it.sep.push(this.sourceToken);
          } else {
            if (this.atIndentedComment(it.start, map2.indent)) {
              const prev = map2.items[map2.items.length - 2];
              const end = prev?.value?.end;
              if (Array.isArray(end)) {
                arrayPushArray(end, it.start);
                end.push(this.sourceToken);
                map2.items.pop();
                return;
              }
            }
            it.start.push(this.sourceToken);
          }
          return;
      }
      if (this.indent >= map2.indent) {
        const atMapIndent = !this.onKeyLine && this.indent === map2.indent;
        const atNextItem = atMapIndent && (it.sep || it.explicitKey) && this.type !== "seq-item-ind";
        let start = [];
        if (atNextItem && it.sep && !it.value) {
          const nl = [];
          for (let i = 0; i < it.sep.length; ++i) {
            const st = it.sep[i];
            switch (st.type) {
              case "newline":
                nl.push(i);
                break;
              case "space":
                break;
              case "comment":
                if (st.indent > map2.indent)
                  nl.length = 0;
                break;
              default:
                nl.length = 0;
            }
          }
          if (nl.length >= 2)
            start = it.sep.splice(nl[1]);
        }
        switch (this.type) {
          case "anchor":
          case "tag":
            if (atNextItem || it.value) {
              start.push(this.sourceToken);
              map2.items.push({ start });
              this.onKeyLine = true;
            } else if (it.sep) {
              it.sep.push(this.sourceToken);
            } else {
              it.start.push(this.sourceToken);
            }
            return;
          case "explicit-key-ind":
            if (!it.sep && !it.explicitKey) {
              it.start.push(this.sourceToken);
              it.explicitKey = true;
            } else if (atNextItem || it.value) {
              start.push(this.sourceToken);
              map2.items.push({ start, explicitKey: true });
            } else {
              this.stack.push({
                type: "block-map",
                offset: this.offset,
                indent: this.indent,
                items: [{ start: [this.sourceToken], explicitKey: true }]
              });
            }
            this.onKeyLine = true;
            return;
          case "map-value-ind":
            if (it.explicitKey) {
              if (!it.sep) {
                if (includesToken(it.start, "newline")) {
                  Object.assign(it, { key: null, sep: [this.sourceToken] });
                } else {
                  const start2 = getFirstKeyStartProps(it.start);
                  this.stack.push({
                    type: "block-map",
                    offset: this.offset,
                    indent: this.indent,
                    items: [{ start: start2, key: null, sep: [this.sourceToken] }]
                  });
                }
              } else if (it.value) {
                map2.items.push({ start: [], key: null, sep: [this.sourceToken] });
              } else if (includesToken(it.sep, "map-value-ind")) {
                this.stack.push({
                  type: "block-map",
                  offset: this.offset,
                  indent: this.indent,
                  items: [{ start, key: null, sep: [this.sourceToken] }]
                });
              } else if (isFlowToken(it.key) && !includesToken(it.sep, "newline")) {
                const start2 = getFirstKeyStartProps(it.start);
                const key = it.key;
                const sep = it.sep;
                sep.push(this.sourceToken);
                delete it.key;
                delete it.sep;
                this.stack.push({
                  type: "block-map",
                  offset: this.offset,
                  indent: this.indent,
                  items: [{ start: start2, key, sep }]
                });
              } else if (start.length > 0) {
                it.sep = it.sep.concat(start, this.sourceToken);
              } else {
                it.sep.push(this.sourceToken);
              }
            } else {
              if (!it.sep) {
                Object.assign(it, { key: null, sep: [this.sourceToken] });
              } else if (it.value || atNextItem) {
                map2.items.push({ start, key: null, sep: [this.sourceToken] });
              } else if (includesToken(it.sep, "map-value-ind")) {
                this.stack.push({
                  type: "block-map",
                  offset: this.offset,
                  indent: this.indent,
                  items: [{ start: [], key: null, sep: [this.sourceToken] }]
                });
              } else {
                it.sep.push(this.sourceToken);
              }
            }
            this.onKeyLine = true;
            return;
          case "alias":
          case "scalar":
          case "single-quoted-scalar":
          case "double-quoted-scalar": {
            const fs = this.flowScalar(this.type);
            if (atNextItem || it.value) {
              map2.items.push({ start, key: fs, sep: [] });
              this.onKeyLine = true;
            } else if (it.sep) {
              this.stack.push(fs);
            } else {
              Object.assign(it, { key: fs, sep: [] });
              this.onKeyLine = true;
            }
            return;
          }
          default: {
            const bv = this.startBlockValue(map2);
            if (bv) {
              if (bv.type === "block-seq") {
                if (!it.explicitKey && it.sep && !includesToken(it.sep, "newline")) {
                  yield* this.pop({
                    type: "error",
                    offset: this.offset,
                    message: "Unexpected block-seq-ind on same line with key",
                    source: this.source
                  });
                  return;
                }
              } else if (atMapIndent) {
                map2.items.push({ start });
              }
              this.stack.push(bv);
              return;
            }
          }
        }
      }
      yield* this.pop();
      yield* this.step();
    }
    *blockSequence(seq2) {
      const it = seq2.items[seq2.items.length - 1];
      switch (this.type) {
        case "newline":
          if (it.value) {
            const end = "end" in it.value ? it.value.end : void 0;
            const last = Array.isArray(end) ? end[end.length - 1] : void 0;
            if (last?.type === "comment")
              end?.push(this.sourceToken);
            else
              seq2.items.push({ start: [this.sourceToken] });
          } else
            it.start.push(this.sourceToken);
          return;
        case "space":
        case "comment":
          if (it.value)
            seq2.items.push({ start: [this.sourceToken] });
          else {
            if (this.atIndentedComment(it.start, seq2.indent)) {
              const prev = seq2.items[seq2.items.length - 2];
              const end = prev?.value?.end;
              if (Array.isArray(end)) {
                arrayPushArray(end, it.start);
                end.push(this.sourceToken);
                seq2.items.pop();
                return;
              }
            }
            it.start.push(this.sourceToken);
          }
          return;
        case "anchor":
        case "tag":
          if (it.value || this.indent <= seq2.indent)
            break;
          it.start.push(this.sourceToken);
          return;
        case "seq-item-ind":
          if (this.indent !== seq2.indent)
            break;
          if (it.value || includesToken(it.start, "seq-item-ind"))
            seq2.items.push({ start: [this.sourceToken] });
          else
            it.start.push(this.sourceToken);
          return;
      }
      if (this.indent > seq2.indent) {
        const bv = this.startBlockValue(seq2);
        if (bv) {
          this.stack.push(bv);
          return;
        }
      }
      yield* this.pop();
      yield* this.step();
    }
    *flowCollection(fc) {
      const it = fc.items[fc.items.length - 1];
      if (this.type === "flow-error-end") {
        let top;
        do {
          yield* this.pop();
          top = this.peek(1);
        } while (top?.type === "flow-collection");
      } else if (fc.end.length === 0) {
        switch (this.type) {
          case "comma":
          case "explicit-key-ind":
            if (!it || it.sep)
              fc.items.push({ start: [this.sourceToken] });
            else
              it.start.push(this.sourceToken);
            return;
          case "map-value-ind":
            if (!it || it.value)
              fc.items.push({ start: [], key: null, sep: [this.sourceToken] });
            else if (it.sep)
              it.sep.push(this.sourceToken);
            else
              Object.assign(it, { key: null, sep: [this.sourceToken] });
            return;
          case "space":
          case "comment":
          case "newline":
          case "anchor":
          case "tag":
            if (!it || it.value)
              fc.items.push({ start: [this.sourceToken] });
            else if (it.sep)
              it.sep.push(this.sourceToken);
            else
              it.start.push(this.sourceToken);
            return;
          case "alias":
          case "scalar":
          case "single-quoted-scalar":
          case "double-quoted-scalar": {
            const fs = this.flowScalar(this.type);
            if (!it || it.value)
              fc.items.push({ start: [], key: fs, sep: [] });
            else if (it.sep)
              this.stack.push(fs);
            else
              Object.assign(it, { key: fs, sep: [] });
            return;
          }
          case "flow-map-end":
          case "flow-seq-end":
            fc.end.push(this.sourceToken);
            return;
        }
        const bv = this.startBlockValue(fc);
        if (bv)
          this.stack.push(bv);
        else {
          yield* this.pop();
          yield* this.step();
        }
      } else {
        const parent = this.peek(2);
        if (parent.type === "block-map" && (this.type === "map-value-ind" && parent.indent === fc.indent || this.type === "newline" && !parent.items[parent.items.length - 1].sep)) {
          yield* this.pop();
          yield* this.step();
        } else if (this.type === "map-value-ind" && parent.type !== "flow-collection") {
          const prev = getPrevProps(parent);
          const start = getFirstKeyStartProps(prev);
          fixFlowSeqItems(fc);
          const sep = fc.end.splice(1, fc.end.length);
          sep.push(this.sourceToken);
          const map2 = {
            type: "block-map",
            offset: fc.offset,
            indent: fc.indent,
            items: [{ start, key: fc, sep }]
          };
          this.onKeyLine = true;
          this.stack[this.stack.length - 1] = map2;
        } else {
          yield* this.lineEnd(fc);
        }
      }
    }
    flowScalar(type) {
      if (this.onNewLine) {
        let nl = this.source.indexOf("\n") + 1;
        while (nl !== 0) {
          this.onNewLine(this.offset + nl);
          nl = this.source.indexOf("\n", nl) + 1;
        }
      }
      return {
        type,
        offset: this.offset,
        indent: this.indent,
        source: this.source
      };
    }
    startBlockValue(parent) {
      switch (this.type) {
        case "alias":
        case "scalar":
        case "single-quoted-scalar":
        case "double-quoted-scalar":
          return this.flowScalar(this.type);
        case "block-scalar-header":
          return {
            type: "block-scalar",
            offset: this.offset,
            indent: this.indent,
            props: [this.sourceToken],
            source: ""
          };
        case "flow-map-start":
        case "flow-seq-start":
          return {
            type: "flow-collection",
            offset: this.offset,
            indent: this.indent,
            start: this.sourceToken,
            items: [],
            end: []
          };
        case "seq-item-ind":
          return {
            type: "block-seq",
            offset: this.offset,
            indent: this.indent,
            items: [{ start: [this.sourceToken] }]
          };
        case "explicit-key-ind": {
          this.onKeyLine = true;
          const prev = getPrevProps(parent);
          const start = getFirstKeyStartProps(prev);
          start.push(this.sourceToken);
          return {
            type: "block-map",
            offset: this.offset,
            indent: this.indent,
            items: [{ start, explicitKey: true }]
          };
        }
        case "map-value-ind": {
          this.onKeyLine = true;
          const prev = getPrevProps(parent);
          const start = getFirstKeyStartProps(prev);
          return {
            type: "block-map",
            offset: this.offset,
            indent: this.indent,
            items: [{ start, key: null, sep: [this.sourceToken] }]
          };
        }
      }
      return null;
    }
    atIndentedComment(start, indent) {
      if (this.type !== "comment")
        return false;
      if (this.indent <= indent)
        return false;
      return start.every((st) => st.type === "newline" || st.type === "space");
    }
    *documentEnd(docEnd) {
      if (this.type !== "doc-mode") {
        if (docEnd.end)
          docEnd.end.push(this.sourceToken);
        else
          docEnd.end = [this.sourceToken];
        if (this.type === "newline")
          yield* this.pop();
      }
    }
    *lineEnd(token) {
      switch (this.type) {
        case "comma":
        case "doc-start":
        case "doc-end":
        case "flow-seq-end":
        case "flow-map-end":
        case "map-value-ind":
          yield* this.pop();
          yield* this.step();
          break;
        case "newline":
          this.onKeyLine = false;
        // fallthrough
        case "space":
        case "comment":
        default:
          if (token.end)
            token.end.push(this.sourceToken);
          else
            token.end = [this.sourceToken];
          if (this.type === "newline")
            yield* this.pop();
      }
    }
  };

  // node_modules/yaml/browser/dist/public-api.js
  function parseOptions(options) {
    const prettyErrors = options.prettyErrors !== false;
    const lineCounter = options.lineCounter || prettyErrors && new LineCounter() || null;
    return { lineCounter, prettyErrors };
  }
  function parseDocument(source, options = {}) {
    const { lineCounter, prettyErrors } = parseOptions(options);
    const parser = new Parser(lineCounter?.addNewLine);
    const composer = new Composer(options);
    let doc = null;
    for (const _doc of composer.compose(parser.parse(source), true, source.length)) {
      if (!doc)
        doc = _doc;
      else if (doc.options.logLevel !== "silent") {
        doc.errors.push(new YAMLParseError(_doc.range.slice(0, 2), "MULTIPLE_DOCS", "Source contains multiple documents; please use YAML.parseAllDocuments()"));
        break;
      }
    }
    if (prettyErrors && lineCounter) {
      doc.errors.forEach(prettifyError(source, lineCounter));
      doc.warnings.forEach(prettifyError(source, lineCounter));
    }
    return doc;
  }
  function parse(src, reviver, options) {
    let _reviver = void 0;
    if (typeof reviver === "function") {
      _reviver = reviver;
    } else if (options === void 0 && reviver && typeof reviver === "object") {
      options = reviver;
    }
    const doc = parseDocument(src, options);
    if (!doc)
      return null;
    doc.warnings.forEach((warning2) => warn(doc.options.logLevel, warning2));
    if (doc.errors.length > 0) {
      if (doc.options.logLevel !== "silent")
        throw doc.errors[0];
      else
        doc.errors = [];
    }
    return doc.toJS(Object.assign({ reviver: _reviver }, options));
  }
  function stringify3(value, replacer, options) {
    let _replacer = null;
    if (typeof replacer === "function" || Array.isArray(replacer)) {
      _replacer = replacer;
    } else if (options === void 0 && replacer) {
      options = replacer;
    }
    if (typeof options === "string")
      options = options.length;
    if (typeof options === "number") {
      const indent = Math.round(options);
      options = indent < 1 ? void 0 : indent > 8 ? { indent: 8 } : { indent };
    }
    if (value === void 0) {
      const { keepUndefined } = options ?? replacer ?? {};
      if (!keepUndefined)
        return void 0;
    }
    if (isDocument(value) && !_replacer)
      return value.toString(options);
    return new Document(value, _replacer, options).toString(options);
  }

  // frontend/yaml.ts
  function dumpMapYaml(map2) {
    return stringify3(map2, { version: "1.2", compat: "yaml-1.1", lineWidth: 0, directives: false });
  }
  function parseMapYaml(source) {
    const value = parse(source, { version: "1.1", maxAliasCount: 100 });
    return decodeMap(value);
  }
  function formatEntities(entities) {
    return stringify3(entities, { version: "1.2", compat: "yaml-1.1", lineWidth: 0, directives: false, collectionStyle: "flow" }).trim();
  }
  function parseEntities(source) {
    if (!source.trim()) return {};
    const value = parse(source, { version: "1.1", maxAliasCount: 100 });
    if (typeof value === "string") return { motion: value };
    return decodeEntitiesMap(value);
  }

  // frontend/paths.ts
  var strength = { neutral: 0, candidate: 1, history: 2, presence: 3 };
  function add(target, id, role, slot) {
    const previous = target.get(id) || { role: "neutral", slots: [] };
    target.set(id, { role: strength[role] > strength[previous.role] ? role : previous.role, slots: [.../* @__PURE__ */ new Set([...previous.slots, slot])].sort((a, b) => a - b) });
  }
  function indexUnique(rows) {
    const index = /* @__PURE__ */ new Map();
    for (const row of rows) index.set(row.node_id, index.has(row.node_id) ? void 0 : row);
    return index;
  }
  function validCount(count) {
    return Number.isInteger(count) && count >= 0 && count <= 2;
  }
  function projectPaths(map2, diagnostics, snapshotCount) {
    const result = { state: "selected", message: "", slots: [], nodes: /* @__PURE__ */ new Map(), zones: /* @__PURE__ */ new Map(), segments: [], frontierTokens: [], frontierZones: /* @__PURE__ */ new Set(), authorizedPaths: [] };
    for (const [id, node] of Object.entries(map2.nodes)) {
      result.nodes.set(id, { role: "neutral", slots: [] });
      result.zones.set(node.zone || id, { role: "neutral", slots: [] });
    }
    for (const zone of Object.keys(map2.zones || {})) result.zones.set(zone, { role: "neutral", slots: [] });
    if (diagnostics?.selected_paths_error) {
      result.state = "unavailable";
      result.message = `Selected paths unavailable: ${diagnostics.selected_paths_error}`;
      return result;
    }
    if (!diagnostics || !Object.hasOwn(diagnostics, "selected_paths")) {
      result.state = "legacy";
      result.message = "Legacy path display — selected paths not supplied by server";
      result.frontierTokens = diagnostics?.traversal_frontier || [];
      result.frontierZones = new Set(result.frontierTokens.flatMap((t) => t.zone ? [t.zone] : []));
      const tokens = new Map(result.frontierTokens.map((t) => [t.token_id, t]));
      const seen = /* @__PURE__ */ new Set();
      for (const auth of diagnostics?.authorizations || []) {
        if (!auth.authorized || !auth.target_zone) continue;
        for (const id of auth.source_token_ids || []) {
          const sourceZone = tokens.get(id)?.zone;
          const key = JSON.stringify([sourceZone, auth.target_zone]);
          if (sourceZone && sourceZone !== auth.target_zone && !seen.has(key)) {
            seen.add(key);
            result.authorizedPaths.push({ sourceZone, targetZone: auth.target_zone });
          }
        }
      }
      return result;
    }
    const paths = diagnostics.selected_paths;
    const counts = [snapshotCount, diagnostics.expected_occupants].filter((v) => v !== void 0);
    if (!paths || paths.length > 2 || diagnostics.unsupported_count || counts.some((count) => !validCount(count) || count !== paths.length)) {
      result.state = "unavailable";
      result.message = "Selected paths unavailable: inconsistent snapshot count";
      return result;
    }
    const episodes = indexUnique(diagnostics.episodes || []);
    const health2 = indexUnique(diagnostics.path_health || []);
    for (const [index, path] of paths.entries()) {
      const slot = index + 1;
      const row = { slot, path, occurrences: [] };
      result.slots.push(row);
      if (!path) continue;
      for (const visit4 of path.route) {
        const node = Object.hasOwn(map2.nodes, visit4.node_id) ? map2.nodes[visit4.node_id] : void 0;
        const valid = !!node && (node.zone || visit4.node_id) === visit4.zone;
        const episode2 = episodes.get(visit4.node_id);
        const state = health2.get(visit4.node_id);
        const identityMatches = valid && episode2?.zone === visit4.zone && state?.zone === visit4.zone;
        const generationMatches = identityMatches && episode2?.episode_id === visit4.episode_id;
        const presence = generationMatches && state?.phase === "on" && visit4.branch_active && episode2?.status !== "clearing";
        const role = presence ? "presence" : "history";
        const phase = valid && state?.zone === visit4.zone ? state.phase === "on" ? "ON" : state.phase === "off" ? "OFF" : "Unknown" : "Unknown";
        const issue = !valid ? "Map membership unavailable" : !identityMatches ? "Physical diagnostics unavailable" : !generationMatches ? "Earlier episode" : void 0;
        row.occurrences.push({ visit: visit4, role, valid, phase, issue });
        if (valid) {
          add(result.nodes, visit4.node_id, role, slot);
          add(result.zones, visit4.zone, role, slot);
        }
      }
      for (let i = 1; i < row.occurrences.length; i++) {
        const previous = row.occurrences[i - 1];
        const current = row.occurrences[i];
        if (!previous?.valid || !current?.valid) continue;
        if (map2.nodes[previous.visit.node_id]?.adjacent?.includes(current.visit.node_id)) {
          result.segments.push({ slot, from: previous.visit.node_id, to: current.visit.node_id, sourceZone: previous.visit.zone, targetZone: current.visit.zone });
        }
      }
    }
    for (const row of result.slots) {
      for (const occurrence of row.occurrences) {
        if (occurrence.role !== "presence") continue;
        for (const id of map2.nodes[occurrence.visit.node_id]?.adjacent || []) {
          const node = Object.hasOwn(map2.nodes, id) ? map2.nodes[id] : void 0;
          if (!node) continue;
          add(result.nodes, id, "candidate", row.slot);
          add(result.zones, node.zone || id, "candidate", row.slot);
        }
      }
    }
    result.message = paths.length ? "Selected anonymous paths" : "No selected paths";
    return result;
  }

  // frontend/styles.ts
  var panelStyles = `
  predictive-controls-panel { display:block; width:100%; min-width:0; --pc-presence:#00897b; --pc-history:#8053b3; --pc-candidate:#608e89; }
  predictive-controls-panel .pc-shell { padding:24px; color:var(--primary-text-color); min-width:0; box-sizing:border-box; }
  predictive-controls-panel header { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:16px; }
  predictive-controls-panel h1 { margin:0; font-size:28px; }
  predictive-controls-panel h2 { margin:0 0 12px; font-size:18px; }
  predictive-controls-panel h3 { margin:18px 0 8px; font-size:14px; }
  predictive-controls-panel p { color:var(--secondary-text-color); }
  predictive-controls-panel button { border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); border-radius:6px; padding:8px 12px; cursor:pointer; font:inherit; min-height:44px; touch-action:manipulation; }
  predictive-controls-panel button.primary, predictive-controls-panel button.active { background:var(--primary-color); color:var(--text-primary-color); border-color:var(--primary-color); }
  predictive-controls-panel button:disabled { opacity:.5; cursor:not-allowed; }
  predictive-controls-panel nav { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
  predictive-controls-panel .pc-actions { display:flex; gap:8px; flex-wrap:wrap; }
  predictive-controls-panel .map-layout { display:grid; grid-template-columns:280px minmax(420px, 1fr) 280px; gap:16px; min-height:640px; }
  predictive-controls-panel .entity-list, predictive-controls-panel .board-wrap, predictive-controls-panel .inspector, predictive-controls-panel .single-panel { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:8px; padding:16px; min-width:0; }
  predictive-controls-panel .entity-list input, predictive-controls-panel label input, predictive-controls-panel textarea, predictive-controls-panel select { width:100%; box-sizing:border-box; margin-top:6px; padding:8px; color:var(--primary-text-color); background:var(--secondary-background-color); border:1px solid var(--divider-color); border-radius:6px; font:inherit; min-height:44px; }
  predictive-controls-panel .entities { margin-top:12px; display:grid; gap:8px; max-height:560px; overflow:auto; }
  predictive-controls-panel .entity { border:1px solid var(--divider-color); border-radius:6px; padding:10px; cursor:grab; }
  predictive-controls-panel .entity span, predictive-controls-panel .entity small, predictive-controls-panel .node span, predictive-controls-panel .node small { display:block; color:var(--secondary-text-color); font-size:12px; overflow:hidden; text-overflow:ellipsis; }
  predictive-controls-panel .toolbar { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
  predictive-controls-panel .board { position:relative; min-height:580px; overflow:auto; background:var(--secondary-background-color); border:1px dashed var(--divider-color); border-radius:8px; }
  predictive-controls-panel .edges { position:absolute; inset:0; width:2000px; height:1200px; pointer-events:none; }
  predictive-controls-panel .edges line { stroke:var(--primary-color); stroke-width:3; opacity:.75; }
  predictive-controls-panel .node { position:absolute; width:180px; min-height:56px; text-align:left; cursor:grab; box-shadow:var(--ha-card-box-shadow, none); }
  predictive-controls-panel .node.selected { outline:3px solid var(--primary-color); }
  predictive-controls-panel .inspector label, predictive-controls-panel .settings label { display:block; margin-bottom:12px; }
  predictive-controls-panel .maintenance-section { margin-top:20px; padding-top:16px; border-top:1px solid var(--divider-color); }
  predictive-controls-panel .chips { display:flex; flex-wrap:wrap; gap:8px; }
  predictive-controls-panel textarea { min-height:520px; font-family:monospace; resize:vertical; }
  predictive-controls-panel textarea.small { min-height:96px; }
  predictive-controls-panel .occupancy-layout, predictive-controls-panel .reliability-layout, predictive-controls-panel .activity-layout { display:grid; grid-template-columns:minmax(0, 1fr); gap:16px; }
  predictive-controls-panel .occupancy-toolbar, predictive-controls-panel .track-section, predictive-controls-panel .diagnostics-panel, predictive-controls-panel .floor-section, predictive-controls-panel .transition-section, predictive-controls-panel .reliability-summary, predictive-controls-panel .reliability-section, predictive-controls-panel .ownership-section, predictive-controls-panel .activity-metrics, predictive-controls-panel .audit-section, predictive-controls-panel .activity-empty { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:8px; padding:16px; min-width:0; }
  predictive-controls-panel .occupancy-toolbar { display:flex; align-items:center; justify-content:space-between; gap:16px; }
  predictive-controls-panel .occupancy-toolbar p { margin:4px 0 0; }
  predictive-controls-panel .section-title h3 { margin:0; }
  predictive-controls-panel .section-title small { display:block; margin-top:4px; }
  predictive-controls-panel .track-list, predictive-controls-panel .reliability-list { display:grid; grid-template-columns:minmax(0, 1fr); margin-top:12px; }
  predictive-controls-panel .track-row, predictive-controls-panel .reliability-row { display:grid; gap:6px; padding:12px 0; border-top:1px solid var(--divider-color); }
  predictive-controls-panel .track-row:first-child, predictive-controls-panel .reliability-row:first-child { border-top:0; }
  predictive-controls-panel .track-row { grid-template-columns:minmax(140px, 1fr) auto minmax(200px, 2fr); align-items:center; }
  predictive-controls-panel .reliability-row { grid-template-columns:minmax(0, 1fr); }
  predictive-controls-panel .track-row div { display:grid; gap:2px; }
  predictive-controls-panel .track-row span, predictive-controls-panel .track-row small { color:var(--secondary-text-color); overflow:hidden; text-overflow:ellipsis; }
  predictive-controls-panel .track-state { text-align:right; }
  predictive-controls-panel .empty-state { margin:12px 0 0; }
  predictive-controls-panel .diagnostics-strip { display:flex; flex-wrap:wrap; gap:8px; }
  predictive-controls-panel .diagnostics-strip span { border:1px solid var(--divider-color); border-radius:999px; padding:4px 8px; }
  predictive-controls-panel .diagnostics-list { display:grid; gap:8px; margin-top:12px; }
  predictive-controls-panel .diagnostics-list p { margin:0; display:grid; gap:2px; }
  predictive-controls-panel .diagnostics-list span { color:var(--secondary-text-color); }
  predictive-controls-panel .section-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
  predictive-controls-panel .section-head small { color:var(--secondary-text-color); }
  predictive-controls-panel .reliability-metrics { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:1px; background:var(--divider-color); }
  predictive-controls-panel .reliability-metrics div { display:grid; gap:4px; padding:14px; background:var(--card-background-color); }
  predictive-controls-panel .reliability-metrics strong { font-size:24px; }
  predictive-controls-panel .reliability-metrics span, predictive-controls-panel .reliability-summary p, predictive-controls-panel .reliability-row p, predictive-controls-panel .reliability-row small { color:var(--secondary-text-color); }
  predictive-controls-panel .reliability-summary p, predictive-controls-panel .reliability-row p { margin:10px 0 0; }
  predictive-controls-panel .reliability-row-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
  predictive-controls-panel .reliability-row-head strong { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  predictive-controls-panel .reliability-row-head span { border:1px solid var(--warning-color, #f2a900); border-radius:999px; padding:3px 8px; white-space:nowrap; }
  predictive-controls-panel .ownership-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(min(260px, 100%), 1fr)); gap:1px; margin-top:14px; background:var(--divider-color); }
  predictive-controls-panel .ownership-row { min-width:0; padding:14px; background:var(--card-background-color); border-left:4px solid var(--disabled-text-color); }
  predictive-controls-panel .ownership-row.is-active { border-left-color:var(--success-color, #43a047); }
  predictive-controls-panel .ownership-name { display:flex; align-items:center; gap:9px; }
  predictive-controls-panel .ownership-name div { min-width:0; display:grid; gap:2px; }
  predictive-controls-panel .ownership-name strong, predictive-controls-panel .ownership-name small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  predictive-controls-panel .ownership-name small, predictive-controls-panel .ownership-row p, predictive-controls-panel .ownership-probabilities { color:var(--secondary-text-color); }
  predictive-controls-panel .state-indicator { width:9px; height:9px; flex:0 0 auto; border-radius:50%; background:var(--disabled-text-color); }
  predictive-controls-panel .is-active .state-indicator { background:var(--success-color, #43a047); box-shadow:0 0 0 4px color-mix(in srgb, var(--success-color, #43a047) 18%, transparent); }
  predictive-controls-panel .ownership-row p { min-height:2.7em; margin:10px 0; line-height:1.35; }
  predictive-controls-panel .ownership-probabilities { display:flex; flex-wrap:wrap; gap:6px 12px; font-size:12px; }
  predictive-controls-panel .activity-metrics { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:1px; background:var(--divider-color); }
  predictive-controls-panel .activity-metrics div { display:grid; gap:4px; padding:14px; background:var(--card-background-color); }
  predictive-controls-panel .activity-metrics strong { font-size:22px; }
  predictive-controls-panel .activity-metrics span, predictive-controls-panel .activity-metrics p { color:var(--secondary-text-color); }
  predictive-controls-panel .activity-metrics p { grid-column:1 / -1; margin:0; padding:12px 14px; background:var(--card-background-color); }
  predictive-controls-panel .audit-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
  predictive-controls-panel .activity-filters { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:6px; }
  predictive-controls-panel .activity-filters button { padding:6px 9px; }
  predictive-controls-panel .audit-list { margin-top:12px; }
  predictive-controls-panel .audit-row { display:grid; grid-template-columns:14px minmax(0, 1fr); gap:12px; padding:14px 0; border-top:1px solid var(--divider-color); }
  predictive-controls-panel .audit-row:first-child { border-top:0; }
  predictive-controls-panel .audit-marker { width:10px; height:10px; margin-top:5px; border-radius:50%; background:var(--disabled-text-color); }
  predictive-controls-panel .kind-edges .audit-marker { background:var(--primary-color); }
  predictive-controls-panel .kind-rejected .audit-marker { background:var(--warning-color, #f2a900); }
  predictive-controls-panel .kind-observations .audit-marker { background:var(--info-color, #4797ff); }
  predictive-controls-panel .audit-content { min-width:0; }
  predictive-controls-panel .audit-row-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
  predictive-controls-panel .audit-row-head div { min-width:0; display:flex; flex-wrap:wrap; gap:5px 10px; }
  predictive-controls-panel .audit-row-head span, predictive-controls-panel .audit-row-head time, predictive-controls-panel .audit-content p, predictive-controls-panel .audit-meta { color:var(--secondary-text-color); }
  predictive-controls-panel .audit-row-head time { flex:0 0 auto; font-size:12px; }
  predictive-controls-panel .audit-content p { margin:7px 0 9px; }
  predictive-controls-panel .audit-meta { display:flex; flex-wrap:wrap; gap:6px 12px; font-size:12px; }
  predictive-controls-panel .context-badge { border:1px solid var(--divider-color); border-radius:999px; padding:2px 7px; }
  predictive-controls-panel .show-more { width:100%; margin-top:10px; }
  predictive-controls-panel .activity-empty h3 { margin-top:0; }
  predictive-controls-panel .floor-section, predictive-controls-panel .transition-section { overflow:auto; }
  predictive-controls-panel .occupancy-graph-section h3 { margin-top:0; }
  predictive-controls-panel .graph-section-head { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
  predictive-controls-panel .graph-summary { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; }
  predictive-controls-panel .graph-summary span { border:1px solid var(--divider-color); border-radius:999px; padding:4px 8px; white-space:nowrap; }
  predictive-controls-panel .graph-legend { display:flex; flex-wrap:wrap; gap:16px; margin:12px 0; color:var(--secondary-text-color); font-size:12px; }
  predictive-controls-panel .graph-legend span { display:flex; align-items:center; gap:7px; }
  predictive-controls-panel .legend-line { display:inline-block; width:28px; height:0; border-top:3px solid var(--primary-color); }
  predictive-controls-panel .legend-line.frontier { border-top-style:dashed; opacity:.8; }
  predictive-controls-panel .legend-line.authorized { border-top-color:var(--success-color, #43a047); border-top-width:5px; }
  predictive-controls-panel .legend-zone { display:inline-block; width:18px; height:12px; border:2px solid var(--divider-color); border-radius:2px; }
  predictive-controls-panel .legend-zone.warning { border-color:#d32f2f; background:color-mix(in srgb, #d32f2f 12%, var(--card-background-color)); }
  predictive-controls-panel .occupancy-board { position:relative; overflow:auto; background:var(--secondary-background-color); border:1px solid var(--divider-color); border-radius:8px; }
  predictive-controls-panel .occupancy-graph { background:var(--secondary-background-color); }
  predictive-controls-panel .floor-band { position:absolute; left:12px; box-sizing:border-box; border:1px solid color-mix(in srgb, var(--divider-color) 78%, transparent); border-radius:8px; background:color-mix(in srgb, var(--card-background-color) 10%, transparent); pointer-events:none; }
  predictive-controls-panel .floor-band span { position:absolute; left:12px; top:10px; color:var(--primary-text-color); font-size:13px; font-weight:700; }
  predictive-controls-panel .zone-edges { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }
  predictive-controls-panel .zone-edges line { stroke:var(--primary-color); stroke-width:3; opacity:.5; }
  predictive-controls-panel .zone-edges .frontier-edge { stroke-dasharray:10 8; stroke-width:4; opacity:.9; }
  predictive-controls-panel .zone-edges .authorized-path { stroke:var(--success-color, #43a047); stroke-width:7; opacity:.95; }
  predictive-controls-panel .zone-edges marker path { fill:var(--success-color, #43a047); }
  predictive-controls-panel .zone-card { position:absolute; box-sizing:border-box; border:1px solid var(--divider-color); border-left-width:6px; border-radius:8px; padding:12px; background:var(--card-background-color); box-shadow:var(--ha-card-box-shadow, none); z-index:1; overflow-wrap:anywhere; }
  predictive-controls-panel .zone-card.is-active { box-shadow:0 0 0 2px color-mix(in srgb, var(--success-color, #43a047) 42%, transparent), var(--ha-card-box-shadow, none); }
  predictive-controls-panel .zone-card.has-frontier { outline:2px dashed var(--primary-color); outline-offset:3px; }
  predictive-controls-panel .zone-card-head { display:flex; align-items:center; justify-content:space-between; gap:8px; }
  predictive-controls-panel .zone-card-head strong, predictive-controls-panel .zone-card small { overflow:hidden; text-overflow:ellipsis; }
  predictive-controls-panel .zone-card-head strong { min-width:0; line-height:1.5; }
  predictive-controls-panel .zone-card-head > span { flex:0 0 auto; font-size:12px; }
  predictive-controls-panel .zone-card small { display:block; margin-top:6px; color:var(--secondary-text-color); }
  predictive-controls-panel .zone-belief-state { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-top:8px; flex-wrap:wrap; }
  predictive-controls-panel .zone-belief-state span { color:var(--secondary-text-color); font-size:12px; }
  predictive-controls-panel .path-frontier-label { color:var(--primary-color) !important; }
  predictive-controls-panel .zone-warning-label { color:#d32f2f !important; font-weight:700; }
  predictive-controls-panel .confidence-bar { height:8px; margin-top:10px; border-radius:999px; background:var(--divider-color); overflow:hidden; }
  predictive-controls-panel .confidence-bar span { display:block; height:100%; background:var(--primary-color); }
  predictive-controls-panel .status-rejected { border-left-color:var(--disabled-text-color); }
  predictive-controls-panel .status-suspect { border-left-color:var(--warning-color, #f2a900); }
  predictive-controls-panel .status-possible { border-left-color:var(--info-color, #4797ff); }
  predictive-controls-panel .status-probable { border-left-color:var(--success-color, #43a047); }
  predictive-controls-panel .status-confirmed { border-left-color:var(--primary-color); }
  predictive-controls-panel .transition-table { width:100%; border-collapse:collapse; margin-top:12px; }
  predictive-controls-panel .transition-table th, predictive-controls-panel .transition-table td { text-align:left; border-top:1px solid var(--divider-color); padding:10px 8px; vertical-align:top; overflow-wrap:anywhere; }
  predictive-controls-panel .transition-table th { color:var(--secondary-text-color); font-weight:600; }
  predictive-controls-panel .transition-table small { display:block; color:var(--secondary-text-color); margin-top:2px; }

  predictive-controls-panel .path-list-section { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:8px; padding:16px; min-width:0; }
  predictive-controls-panel .path-list-section h3 { margin-top:0; }
  predictive-controls-panel .selected-paths { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:8px; padding:16px; min-width:0; }
  predictive-controls-panel .selected-paths h3 { margin-top:0; }
  predictive-controls-panel .selected-paths .path-slot { font-weight:400; border-top:1px solid var(--divider-color); padding:12px 0; }
  predictive-controls-panel .path-badge { display:inline-block; border:1px solid var(--divider-color); border-radius:999px; padding:3px 8px; margin-bottom:10px; font-size:12px; }
  predictive-controls-panel .path-chips { counter-reset:route; }
  predictive-controls-panel .path-chip { counter-increment:route; }
  predictive-controls-panel .path-chip::before { content:counter(route) "."; font-size:12px; }
  predictive-controls-panel [data-error]:empty, predictive-controls-panel [data-status-banner]:empty { display:none; }
  predictive-controls-panel .path-list { display:grid; gap:12px; margin:12px 0 0; padding:0; list-style:none; }
  predictive-controls-panel .path-row { display:grid; gap:10px; min-width:0; padding:12px; border:1px solid var(--divider-color); border-radius:8px; }
  predictive-controls-panel .path-row-head { display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; }
  predictive-controls-panel .path-slot { font-weight:700; }
  predictive-controls-panel .path-confidence, predictive-controls-panel .path-membership { display:inline-flex; align-items:center; border:1px solid var(--divider-color); border-radius:999px; padding:3px 8px; font-size:12px; color:var(--primary-text-color); }
  predictive-controls-panel .path-confidence.confirmed { font-weight:700; }
  predictive-controls-panel .path-confidence.provisional { font-style:italic; }
  predictive-controls-panel .path-route, predictive-controls-panel .path-chips { display:flex; align-items:center; flex-wrap:wrap; gap:8px; min-width:0; margin:0; padding:0; list-style:none; }
  predictive-controls-panel .path-chip { display:inline-flex; flex-direction:column; gap:3px; min-width:0; max-width:100%; box-sizing:border-box; padding:7px 10px; border:1px solid var(--divider-color); border-radius:6px; background:var(--secondary-background-color); color:var(--primary-text-color); overflow-wrap:anywhere; }
  predictive-controls-panel .path-chip small, predictive-controls-panel .path-endpoint, predictive-controls-panel .path-eligibility, predictive-controls-panel .path-notice { color:var(--secondary-text-color); font-size:12px; overflow-wrap:anywhere; }
  predictive-controls-panel .path-arrow { color:var(--secondary-text-color); flex:0 0 auto; }
  predictive-controls-panel .path-role-label { display:block; font-weight:700; }
  predictive-controls-panel .zone-path-memberships { display:flex; flex-wrap:wrap; gap:4px; margin-top:8px; }
  predictive-controls-panel .zone-card .zone-warning-label, predictive-controls-panel .zone-card .path-role-label, predictive-controls-panel .zone-card .path-frontier-label, predictive-controls-panel .zone-card .path-membership { overflow:visible; white-space:normal; overflow-wrap:anywhere; }
  predictive-controls-panel .path-unavailable, predictive-controls-panel .status-error, predictive-controls-panel .status-stale, predictive-controls-panel .pc-error { padding:10px 12px; border-left:4px solid #d32f2f; color:var(--primary-text-color); background:color-mix(in srgb, #d32f2f 9%, var(--card-background-color)); overflow-wrap:anywhere; }
  predictive-controls-panel .path-legacy { padding:10px 12px; border-left:4px solid var(--warning-color, #f2a900); }

  predictive-controls-panel .zone-card.path-role-candidate, predictive-controls-panel .path-chip.path-role-candidate { border-color:var(--pc-candidate); border-style:dashed; background:color-mix(in srgb, var(--pc-candidate) 4%, var(--card-background-color)); }
  predictive-controls-panel .zone-card.path-role-history, predictive-controls-panel .path-chip.path-role-history { border:2px solid var(--pc-history); background:color-mix(in srgb, var(--pc-history) 7%, var(--card-background-color)); }
  predictive-controls-panel .zone-card.path-role-presence, predictive-controls-panel .path-chip.path-role-presence { border:2px solid var(--pc-presence); background:color-mix(in srgb, var(--pc-presence) 12%, var(--card-background-color)); font-weight:600; }
  predictive-controls-panel .zone-card.path-role-candidate { outline-color:var(--pc-candidate); box-shadow:var(--ha-card-box-shadow, none); }
  predictive-controls-panel .zone-card.path-role-history { border-left-width:6px; outline-color:var(--pc-history); box-shadow:0 0 0 1px color-mix(in srgb, var(--pc-history) 30%, transparent), var(--ha-card-box-shadow, none); }
  predictive-controls-panel .zone-card.path-role-presence { border-left-width:6px; outline-color:var(--pc-presence); box-shadow:0 0 0 3px color-mix(in srgb, var(--pc-presence) 40%, transparent), var(--ha-card-box-shadow, none); }
  predictive-controls-panel .zone-card.path-role-presence.has-frontier, predictive-controls-panel .zone-card.path-role-history.has-frontier { outline-style:solid; }
  predictive-controls-panel .zone-card.path-role-presence .confidence-bar span { background:var(--pc-presence); }
  predictive-controls-panel .zone-card.path-role-history .confidence-bar span { background:var(--pc-history); }
  predictive-controls-panel .zone-card.path-role-candidate .confidence-bar span { background:var(--pc-candidate); }
  predictive-controls-panel .legend-line.path-role-candidate { border-top:2px dashed var(--pc-candidate); }
  predictive-controls-panel .legend-line.path-role-history { border-top:4px solid var(--pc-history); }
  predictive-controls-panel .legend-line.path-role-presence { border-top:6px solid var(--pc-presence); }
  predictive-controls-panel .zone-edges .selected-path { fill:none; stroke:var(--pc-history); stroke-width:4; opacity:1; }
  predictive-controls-panel .zone-edges .selected-path-edge { stroke:var(--pc-history); stroke-width:5; opacity:1; }
  predictive-controls-panel .zone-edges .path-arrow { fill:none; stroke:var(--pc-history); stroke-width:4; opacity:1; }
  predictive-controls-panel .legend-line.candidate { border-top:2px dashed var(--pc-candidate); }
  predictive-controls-panel .legend-line.history { border-top:4px solid var(--pc-history); }
  predictive-controls-panel .legend-line.presence { border-top:6px solid var(--pc-presence); }
  predictive-controls-panel .zone-edges .path-role-candidate { stroke:var(--pc-candidate); stroke-width:2; stroke-dasharray:8 6; opacity:.65; }
  predictive-controls-panel .zone-edges .path-role-history { stroke:var(--pc-history); stroke-width:4; stroke-dasharray:none; opacity:.9; }
  predictive-controls-panel .zone-edges .path-role-presence { stroke:var(--pc-presence); stroke-width:6; stroke-dasharray:none; opacity:1; }
  predictive-controls-panel .zone-edges marker.path-role-presence path { fill:var(--pc-presence); }
  predictive-controls-panel .zone-edges marker.path-role-history path { fill:var(--pc-history); }

  predictive-controls-panel .zone-card.has-warning { border-color:#d32f2f; box-shadow:0 0 0 2px color-mix(in srgb, #d32f2f 52%, transparent), var(--ha-card-box-shadow, none); background:color-mix(in srgb, #d32f2f 9%, var(--card-background-color)); outline-color:#d32f2f; }
  predictive-controls-panel .zone-card.has-warning .confidence-bar span { background:#d32f2f; }
  predictive-controls-panel .path-chip.has-warning { border-color:#d32f2f; box-shadow:0 0 0 1px color-mix(in srgb, #d32f2f 52%, transparent); }
  predictive-controls-panel .zone-edges .has-warning { stroke:#d32f2f; }
  predictive-controls-panel .zone-edges marker.has-warning path { fill:#d32f2f; }

  predictive-controls-panel :is(button, input, select, textarea, a, [tabindex]):focus-visible { outline:3px solid var(--primary-color, #03a9f4); outline-offset:3px; }
  predictive-controls-panel [hidden] { display:none !important; }
  predictive-controls-panel .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap; border:0; }
  predictive-controls-panel .pc-shell :is(p, h1, h2, h3, label, .section-title, .path-membership) { overflow-wrap:anywhere; }

  @media (max-width:1000px) {
    predictive-controls-panel .map-layout { grid-template-columns:minmax(0, 1fr); }
  }
  @media (max-width:700px) {
    predictive-controls-panel .pc-shell { padding:12px; }
    predictive-controls-panel header, predictive-controls-panel .occupancy-toolbar, predictive-controls-panel .audit-heading, predictive-controls-panel .graph-section-head { align-items:flex-start; flex-direction:column; }
    predictive-controls-panel .graph-summary { justify-content:flex-start; }
    predictive-controls-panel .track-row { grid-template-columns:minmax(0, 1fr) auto; }
    predictive-controls-panel .track-row small { grid-column:1 / -1; }
    predictive-controls-panel .reliability-metrics { grid-template-columns:1fr; }
    predictive-controls-panel .activity-metrics { grid-template-columns:1fr; }
    predictive-controls-panel .activity-metrics p { grid-column:1; }
    predictive-controls-panel .activity-filters { justify-content:flex-start; }
    predictive-controls-panel .audit-row-head { display:grid; }
    predictive-controls-panel .section-head, predictive-controls-panel .reliability-row-head { flex-wrap:wrap; }
    predictive-controls-panel .reliability-row-head strong, predictive-controls-panel .reliability-row-head span { white-space:normal; overflow-wrap:anywhere; }
    predictive-controls-panel .path-list-section, predictive-controls-panel .path-row { padding:12px; }
    predictive-controls-panel .entities { max-height:320px; }
    predictive-controls-panel input, predictive-controls-panel select, predictive-controls-panel textarea { font-size:16px; }
  }
  @media (forced-colors:active) {
    predictive-controls-panel .zone-card, predictive-controls-panel .path-chip { border-color:CanvasText; box-shadow:none; }
    predictive-controls-panel .zone-card.path-role-presence { border-left-width:8px; }
    predictive-controls-panel .zone-card.has-warning, predictive-controls-panel .path-chip.has-warning { border-color:LinkText; outline:2px solid LinkText; outline-offset:2px; }
    predictive-controls-panel .zone-card.has-warning .confidence-bar span { background:LinkText; }
    predictive-controls-panel .zone-edges line, predictive-controls-panel .zone-edges .selected-path { stroke:CanvasText; }
    predictive-controls-panel :is(button, input, select, textarea, a, [tabindex]):focus-visible { outline-color:Highlight; }
  }
  @media (prefers-reduced-motion:reduce) {
    predictive-controls-panel, predictive-controls-panel *, predictive-controls-panel *::before, predictive-controls-panel *::after { animation:none !important; transition:none !important; scroll-behavior:auto !important; }
  }
`;

  // frontend/layout.ts
  function required(value, context) {
    if (value === void 0) throw new Error(`Missing layout value: ${context}`);
    return value;
  }
  function copyZone(zone, position = zone.position) {
    return {
      ...zone,
      position: { ...position },
      size: { ...zone.size },
      nodeIds: [...zone.nodeIds]
    };
  }
  function groupByFloor(zones) {
    const grouped = /* @__PURE__ */ new Map();
    for (const zone of zones) {
      const list2 = grouped.get(zone.floor) ?? [];
      list2.push(zone);
      grouped.set(zone.floor, list2);
    }
    return grouped;
  }
  function estimateCardHeight(zone) {
    const charsPerLine = Math.max(1, Math.floor((zone.size.width - 24) / 16));
    const titleLines = Math.max(1, Math.ceil(zone.label.length / charsPerLine));
    const estimated = 168 + 24 * (titleLines - 1);
    const contentHeight = zone.contentHeight ?? 0;
    if (!Number.isFinite(contentHeight) || contentHeight < 0) {
      throw new RangeError("Card contentHeight must be finite and nonnegative");
    }
    return Math.max(estimated, zone.size.height, contentHeight);
  }
  function separateFloorRows(zones, minGap = 48) {
    const adjustedY = /* @__PURE__ */ new Map();
    for (const list2 of groupByFloor(zones).values()) {
      const sorted = [...list2].sort(
        (a, b) => a.position.y - b.position.y || a.position.x - b.position.x
      );
      const placed = [];
      for (const zone of sorted) {
        const x = zone.position.x;
        const w = zone.size.width;
        const h = estimateCardHeight(zone);
        let y = zone.position.y;
        for (const previous of placed) {
          const overlapsX = x < previous.x + previous.w && x + w > previous.x;
          if (overlapsX && y < previous.y + previous.h + minGap) {
            y = previous.y + previous.h + minGap;
          }
        }
        placed.push({ x, y, w, h });
        adjustedY.set(zone.zoneId, Math.round(y));
      }
    }
    return zones.map((zone) => copyZone(zone, {
      x: zone.position.x,
      y: required(adjustedY.get(zone.zoneId), zone.zoneId)
    }));
  }
  function floorBands(zones) {
    const bands = /* @__PURE__ */ new Map();
    for (const zone of zones) {
      const top = zone.position.y;
      const bottom = top + estimateCardHeight(zone);
      const existing = bands.get(zone.floor) ?? { floor: zone.floor, top, bottom };
      existing.top = Math.min(existing.top, top);
      existing.bottom = Math.max(existing.bottom, bottom);
      bands.set(zone.floor, existing);
    }
    return [...bands.values()].sort(
      (left, right) => left.top - right.top || left.floor.localeCompare(right.floor)
    );
  }
  function stackFloorsByBand(zones, floorOrder = [], gap = 96) {
    const rank = (floor) => {
      const index = floorOrder.indexOf(floor);
      return index === -1 ? floorOrder.length : index;
    };
    const floors = [...groupByFloor(zones)].map(([floor, list2]) => ({
      floor,
      list: list2,
      top: Math.min(...list2.map((zone) => zone.position.y)),
      bottom: Math.max(...list2.map((zone) => zone.position.y + estimateCardHeight(zone)))
    })).sort(
      (left, right) => rank(left.floor) - rank(right.floor) || left.top - right.top || left.floor.localeCompare(right.floor)
    );
    const first = floors[0];
    if (first === void 0) return [];
    const result = [];
    let cursor = first.top;
    for (const { list: list2, top, bottom } of floors) {
      const shift = cursor - top;
      for (const zone of list2) {
        result.push(copyZone(zone, {
          x: zone.position.x,
          y: Math.round(zone.position.y + shift)
        }));
      }
      cursor += bottom - top + gap;
    }
    return result;
  }
  function zoneAdjacencyPairs(zones, nodes) {
    const zonesByNode = /* @__PURE__ */ new Map();
    for (const zone of zones) {
      for (const nodeId of zone.nodeIds) zonesByNode.set(nodeId, zone);
    }
    const seen = /* @__PURE__ */ new Set();
    const pairs2 = [];
    for (const zone of zones) {
      for (const nodeId of zone.nodeIds) {
        for (const targetId of nodes[nodeId]?.adjacent ?? []) {
          const target = zonesByNode.get(targetId);
          if (target === void 0 || target.zoneId === zone.zoneId) continue;
          const key = JSON.stringify([zone.zoneId, target.zoneId].sort());
          if (seen.has(key)) continue;
          seen.add(key);
          pairs2.push([zone.zoneId, target.zoneId]);
        }
      }
    }
    return pairs2;
  }
  function segmentsCross(a, b, c, d) {
    const direction = (p, q, r) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
    const d1 = direction(c, d, a);
    const d2 = direction(c, d, b);
    const d3 = direction(a, b, c);
    const d4 = direction(a, b, d);
    return d1 > 0 !== d2 > 0 && d3 > 0 !== d4 > 0;
  }
  function pointInRect(point2, box) {
    return point2.x >= box.x && point2.x <= box.x + box.w && point2.y >= box.y && point2.y <= box.y + box.h;
  }
  function segmentIntersectsRect(p1, p2, box) {
    if (pointInRect(p1, box) || pointInRect(p2, box)) return true;
    const corners = [
      { x: box.x, y: box.y },
      { x: box.x + box.w, y: box.y },
      { x: box.x + box.w, y: box.y + box.h },
      { x: box.x, y: box.y + box.h }
    ];
    for (let index = 0; index < corners.length; index += 1) {
      if (segmentsCross(
        p1,
        p2,
        required(corners[index], "rectangle corner"),
        required(corners[(index + 1) % corners.length], "next rectangle corner")
      )) return true;
    }
    return false;
  }
  function countCrossings(pairs2, centerById) {
    const center2 = (id) => required(
      Object.hasOwn(centerById, id) ? centerById[id] : void 0,
      `center ${id}`
    );
    let crossings = 0;
    for (let i = 0; i < pairs2.length; i += 1) {
      const [a1, a2] = required(pairs2[i], "edge");
      for (let j = i + 1; j < pairs2.length; j += 1) {
        const [b1, b2] = required(pairs2[j], "edge");
        if (a1 === b1 || a1 === b2 || a2 === b1 || a2 === b2) continue;
        if (segmentsCross(center2(a1), center2(a2), center2(b1), center2(b2))) {
          crossings += 1;
        }
      }
    }
    return crossings;
  }
  function minimizeCrossings(zones, nodes) {
    const pairs2 = zoneAdjacencyPairs(zones, nodes);
    if (zones.length < 3 || pairs2.length < 2) return zones.map((zone) => copyZone(zone));
    const size = /* @__PURE__ */ new Map();
    const originalPos = /* @__PURE__ */ new Map();
    const originalCenterX = /* @__PURE__ */ new Map();
    for (const zone of zones) {
      size.set(zone.zoneId, { width: zone.size.width, height: estimateCardHeight(zone) });
      originalPos.set(zone.zoneId, { ...zone.position });
      originalCenterX.set(zone.zoneId, zone.position.x + zone.size.width / 2);
    }
    const original = (id) => required(originalPos.get(id), `original ${id}`);
    const originalX = (id) => required(originalCenterX.get(id), `center ${id}`);
    const byFloor = /* @__PURE__ */ new Map();
    for (const [floor, list2] of groupByFloor(zones)) {
      byFloor.set(floor, list2.map((zone) => zone.zoneId));
    }
    const slots = /* @__PURE__ */ new Map();
    const identityOrder = /* @__PURE__ */ new Map();
    for (const [floor, ids] of byFloor) {
      const sorted = [...ids].sort(
        (a, b) => original(a).x - original(b).x || original(a).y - original(b).y
      );
      identityOrder.set(floor, sorted);
      slots.set(floor, sorted.map((id) => ({ ...original(id) })));
    }
    const position = /* @__PURE__ */ new Map();
    const current = (id) => required(position.get(id), `position ${id}`);
    const dimensions = (id) => required(size.get(id), `size ${id}`);
    const applyOrder = (order) => {
      for (const [floor, ids] of order) {
        const floorSlots = required(slots.get(floor), `floor ${floor}`);
        ids.forEach((id, index) => {
          position.set(id, { ...required(floorSlots[index], `slot ${floor}/${index}`) });
        });
      }
    };
    const rectOf = (id) => ({
      ...current(id),
      w: dimensions(id).width,
      h: dimensions(id).height
    });
    const cost = () => {
      const centers = Object.fromEntries(zones.map((zone) => [
        zone.zoneId,
        {
          x: current(zone.zoneId).x + dimensions(zone.zoneId).width / 2,
          y: current(zone.zoneId).y + dimensions(zone.zoneId).height / 2
        }
      ]));
      const center2 = (id) => required(centers[id], `center ${id}`);
      let total = countCrossings(pairs2, centers);
      for (const [a, b] of pairs2) {
        for (const zone of zones) {
          if (zone.zoneId === a || zone.zoneId === b) continue;
          if (segmentIntersectsRect(center2(a), center2(b), rectOf(zone.zoneId))) total += 4;
        }
      }
      return total;
    };
    const overlaps = () => {
      for (let i = 0; i < zones.length; i += 1) {
        const a = rectOf(required(zones[i], "zone").zoneId);
        for (let j = i + 1; j < zones.length; j += 1) {
          const b = rectOf(required(zones[j], "zone").zoneId);
          if (a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y) {
            return true;
          }
        }
      }
      return false;
    };
    const swap = (a, b) => {
      const saved = current(a);
      position.set(a, current(b));
      position.set(b, saved);
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
              const a = required(ids[i], "swap source");
              const b = required(ids[j], "swap target");
              swap(a, b);
              const trial = cost();
              if (trial < best && !overlaps()) {
                best = trial;
                improved = true;
              } else {
                swap(a, b);
              }
            }
          }
        }
      }
      return best;
    };
    const neighborsOf = (id) => pairs2.filter(([a, b]) => a === id || b === id).map(([a, b]) => a === id ? b : a);
    const bary = (id) => {
      const neighbors = neighborsOf(id);
      if (!neighbors.length) return originalX(id);
      return neighbors.reduce((sum, neighbor) => sum + originalX(neighbor), 0) / neighbors.length;
    };
    const barycenterOrder = /* @__PURE__ */ new Map();
    const reversedOrder = /* @__PURE__ */ new Map();
    for (const [floor, ids] of byFloor) {
      barycenterOrder.set(floor, [...ids].sort(
        (a, b) => bary(a) - bary(b) || original(a).x - original(b).x
      ));
      reversedOrder.set(floor, [...required(identityOrder.get(floor), floor)].reverse());
    }
    let bestCost = Infinity;
    let bestPositions = new Map(originalPos);
    for (const start of [identityOrder, barycenterOrder, reversedOrder]) {
      applyOrder(start);
      const result = localSearch();
      if (result < bestCost && !overlaps()) {
        bestCost = result;
        bestPositions = new Map(zones.map((zone) => [zone.zoneId, { ...current(zone.zoneId) }]));
      }
    }
    return zones.map((zone) => copyZone(
      zone,
      required(bestPositions.get(zone.zoneId), `best ${zone.zoneId}`)
    ));
  }
  function spacedZoneSummaries(zones, scaleX = 1.22, scaleY = 1.18) {
    if (!zones.length) return [];
    const originX = Math.min(...zones.map((zone) => zone.position.x));
    const originY = Math.min(...zones.map((zone) => zone.position.y));
    return zones.map((zone) => copyZone(zone, {
      x: Math.round(originX + (zone.position.x - originX) * scaleX),
      y: Math.round(originY + (zone.position.y - originY) * scaleY)
    }));
  }

  // frontend/components/zone-card.ts
  function renderZoneCard(zone, minX, minY, ctx, paths) {
    const state = ctx.status?.zone_states?.[zone.zoneId] || {};
    const model = policyModel(ctx.status);
    const policy2 = model?.policy?.[zone.zoneId];
    const belief = model?.beliefs?.[zone.zoneId] ?? state.confidence;
    const confidence = belief === void 0 ? 0 : Math.round(belief * 100);
    const frontier2 = paths.frontierTokens.find((t) => t.zone === zone.zoneId);
    const warnings = (model?.reliability_warnings || []).filter((w) => w.active && w.zone === zone.zoneId);
    const membership = paths.zones.get(zone.zoneId);
    const role = membership?.role || "neutral";
    return `<article class="zone-card status-${escapeHtml(state.status || "rejected")}${policy2?.active ? " is-active" : ""}${frontier2 ? " has-frontier" : ""}${warnings.length ? " has-warning" : ""}${role !== "neutral" ? ` path-role-${role}` : ""}" data-zone="${escapeHtml(zone.zoneId)}" style="left:${zone.position.x - minX + 24}px;top:${zone.position.y - minY + 24}px;width:${zone.size.width}px;min-height:${zone.size.height}px" title="${escapeHtml(state.reason || "no evidence")}">
    <div class="zone-card-head"><strong>${escapeHtml(zone.label)}</strong><span>${formatPercent(belief)}${belief !== void 0 ? " belief" : ""}</span></div>
    <div class="confidence-bar"><span style="width:${confidence}%"></span></div>
    <div class="zone-belief-state"><strong>${policy2 ? policy2.active ? "Active" : "Inactive" : "Policy unavailable"}</strong><span>${escapeHtml(policy2?.profile || "unprofiled")}</span></div>
    <small>${escapeHtml(titleFromId(state.status || "rejected"))} · ${escapeHtml(titleFromId(state.occupancy_behavior || zone.occupancyBehavior))} · ${escapeHtml(titleFromId(zone.role))}</small>
    <small>${zone.nodeIds.length} ${zone.nodeIds.length === 1 ? "sensor" : "sensors"}${state.last_node_id ? ` · ${escapeHtml(state.last_node_id)}` : ""}</small>
    ${role !== "neutral" ? `<small class="path-role-label">${role === "presence" ? "Current presence" : role === "history" ? "Retained history" : "One-hop candidate"} · ${(membership?.slots || []).map((n) => `Slot ${n}`).join(", ")}</small>` : ""}
    ${warnings.map((w) => `<small class="zone-warning-label">${escapeHtml(warningLabel(w))} warning · ${escapeHtml(w.node_id)} · active · ${escapeHtml(formatTimestamp(w.last_observed_at))}</small>`).join("")}
    ${frontier2 ? `<small class="path-frontier-label">Anonymous path frontier · until ${escapeHtml(formatTimestamp(frontier2.valid_until))}</small>` : ""}
  </article>`;
  }

  // frontend/components/graph.ts
  function center(zone, minX, minY) {
    return { x: zone.position.x - minX + zone.size.width / 2 + 24, y: zone.position.y - minY + estimateCardHeight(zone) / 2 + 24 };
  }
  function renderZoneEdges(zones, minX, minY, ctx, paths) {
    const byNode = new Map(zones.flatMap((z) => z.nodeIds.map((id) => [id, z])));
    const byZone = new Map(zones.map((z) => [z.zoneId, z]));
    const lines = [];
    const seen = /* @__PURE__ */ new Set();
    for (const zone of zones) for (const id of zone.nodeIds) for (const targetId of ctx.map.nodes[id]?.adjacent || []) {
      const target = byNode.get(targetId);
      if (!target || target.zoneId === zone.zoneId) continue;
      const key = [zone.zoneId, target.zoneId].sort().join("->");
      if (seen.has(key)) continue;
      seen.add(key);
      const a = center(zone, minX, minY);
      const b = center(target, minX, minY);
      const frontier2 = paths.frontierZones.has(zone.zoneId) || paths.frontierZones.has(target.zoneId);
      lines.push(`<line class="zone-edge${frontier2 ? " frontier-edge" : ""}" data-edge="${escapeHtml(key)}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />`);
    }
    const segments = paths.state === "legacy" ? paths.authorizedPaths.map((p) => ({ ...p, slot: 0 })) : paths.segments;
    for (const segment of segments) {
      const source = byZone.get(segment.sourceZone);
      const target = byZone.get(segment.targetZone);
      if (!source || !target || source.zoneId === target.zoneId) continue;
      const a = center(source, minX, minY);
      const b = center(target, minX, minY);
      const cls = paths.state === "legacy" ? "authorized-path" : "selected-path-edge";
      const angle = Math.atan2(b.y - a.y, b.x - a.x);
      const tx = a.x + (b.x - a.x) * 0.62;
      const ty = a.y + (b.y - a.y) * 0.62;
      lines.push(`<line class="${cls}" data-slot="${segment.slot}" data-path="${escapeHtml(`${source.zoneId}->${target.zoneId}`)}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" /><path class="path-arrow" d="M ${tx} ${ty} l ${-12 * Math.cos(angle - 0.5)} ${-12 * Math.sin(angle - 0.5)} M ${tx} ${ty} l ${-12 * Math.cos(angle + 0.5)} ${-12 * Math.sin(angle + 0.5)}" />`);
    }
    return lines.join("");
  }
  function renderGraph(input, ctx, paths, clientWidth) {
    const model = policyModel(ctx.status);
    const zones = input.map((zone) => {
      const warningChars = (model?.reliability_warnings || []).filter((w) => w.active && w.zone === zone.zoneId).reduce((n, w) => n + 130 + w.node_id.length, 0);
      const membership = paths.zones.get(zone.zoneId);
      const charsPerLine = Math.max(8, Math.floor((zone.size.width - 30) / 7));
      return { ...zone, contentHeight: estimateCardHeight(zone) + (membership?.slots.length ? 54 : 0) + Math.ceil(warningChars / charsPerLine) * 19 + (paths.frontierZones.has(zone.zoneId) ? 55 : 0) };
    });
    const layout = minimizeCrossings(stackFloorsByBand(separateFloorRows(spacedZoneSummaries(zones)), ctx.map.floors || []), ctx.map.nodes);
    const minX = (layout.length ? Math.min(...layout.map((z) => z.position.x)) : 0) - 64;
    const minY = layout.length ? Math.min(...layout.map((z) => z.position.y)) : 0;
    const maxX = layout.length ? Math.max(...layout.map((z) => z.position.x + z.size.width)) : 0;
    const maxY = layout.length ? Math.max(...layout.map((z) => z.position.y + estimateCardHeight(z))) : 0;
    const width = Math.max(900, maxX - minX + 48, clientWidth - 48);
    const bands = floorBands(layout);
    const bandBottom = bands.reduce((bottom, b) => Math.max(bottom, b.top - minY + 12 + Math.max(120, b.bottom - b.top + 72)), 0);
    const height = Math.max(520, maxY - minY + 48, bandBottom + 24);
    const expected = model?.expected_occupants ?? ctx.status?.expected_occupants;
    const active = Object.values(model?.policy || {}).filter((p) => p.active).length;
    return `<section class="floor-section occupancy-graph-section">
    <div class="graph-section-head"><div class="section-title"><h3>Believed Occupancy Graph</h3><small>Beliefs are zone-local; highlighted paths are anonymous and do not identify a person.</small></div>
      <div class="graph-summary"><span>Expected ${expected ?? "unavailable"}</span><span>${active} active ${active === 1 ? "zone" : "zones"}</span>
      <span>${paths.state === "legacy" ? `${paths.frontierTokens.length} path ${paths.frontierTokens.length === 1 ? "frontier" : "frontiers"}` : paths.state === "unavailable" ? "Selected slots unavailable" : `${paths.slots.length} anonymous slots`}</span>
      <span>${(model?.reliability_warnings || []).filter((w) => w.active).length} health warnings</span></div></div>
    <div class="graph-legend">${paths.state === "legacy" ? '<span><i class="legend-line frontier"></i>Possible next path</span><span><i class="legend-line authorized"></i>Recently authorized path</span>' : '<span><i class="legend-line presence"></i>Current presence</span><span><i class="legend-line history"></i>Retained history</span><span><i class="legend-line candidate"></i>One-hop candidate</span>'}<span><i class="legend-zone warning"></i>Sensor warning</span></div>
    <div class="occupancy-board occupancy-graph" data-scroll-key="graph" tabindex="0" aria-label="Occupancy graph, scroll to explore" style="height:${height}px;width:${width}px">
      ${bands.map((b) => `<div class="floor-band" style="top:${b.top - minY + 12}px;height:${Math.max(120, b.bottom - b.top + 72)}px;width:${width - 24}px"><span>${escapeHtml(titleFromId(b.floor))}</span></div>`).join("")}
      <svg class="zone-edges" aria-hidden="true" viewBox="0 0 ${width} ${height}">${renderZoneEdges(layout, minX, minY, ctx, paths)}</svg>
      ${layout.map((z) => renderZoneCard(z, minX, minY, ctx, paths)).join("")}
    </div></section>`;
  }

  // frontend/components/path-list.ts
  function renderPathList(paths, map2) {
    return `<section class="selected-paths" aria-label="Selected anonymous paths">
    <h3>${escapeHtml(paths.message)}</h3>
    ${paths.state === "selected" ? paths.slots.map((row) => {
      if (!row.path) return `<article class="path-slot"><strong>Slot ${row.slot} · Unlocated</strong></article>`;
      const last = row.occurrences.at(-1);
      return `<article class="path-slot" data-slot="${row.slot}">
        <strong>Slot ${row.slot}</strong> <span class="path-badge">${titleFromId(row.path.track_confidence)}</span>
        <ol class="path-chips">${row.occurrences.map((o) => `<li class="path-chip path-role-${o.role}" data-node-id="${escapeHtml(o.visit.node_id)}" data-episode-id="${escapeHtml(o.visit.episode_id)}">
          <strong>${escapeHtml(map2.nodes[o.visit.node_id]?.label || titleFromId(o.visit.node_id))}</strong>
          <span>${o.role === "presence" ? "Current presence" : "Retained history"} · ${o.phase}</span>
          ${o.issue ? `<small>${escapeHtml(o.issue)}</small>` : ""}</li>`).join("")}</ol>
        <p>Retained endpoint · ${last?.phase || "Unknown"} · Continuation eligible: ${row.path.endpoint_eligible ? "yes" : "no"}</p>
        <small>Retained history is not a claim of current physical presence.</small>
      </article>`;
    }).join("") : ""}
  </section>`;
  }

  // frontend/components/occupancy.ts
  function renderOccupancy(ctx, clientWidth) {
    const paths = projectPaths(ctx.map, ctx.status?.occupancy_diagnostics, ctx.status?.expected_occupants);
    const rows = learnedTransitionRows(ctx.map, ctx.status);
    return `<main class="occupancy-layout">
    <section class="occupancy-toolbar"><div><h2>Occupancy</h2><p>${ctx.statusError ? `Stale / unavailable: ${escapeHtml(ctx.statusError)}` : `Updated ${ctx.updated?.toLocaleTimeString() || "never"}`}</p></div><button data-action="refresh-status">Refresh</button></section>
    ${renderPathList(paths, ctx.map)}
    ${renderGraph(zoneSummaries(ctx.map), ctx, paths, clientWidth)}
    <section class="transition-section"><div class="section-head"><h3>Learned Transitions</h3><small>${rows.length} active ${rows.length === 1 ? "edge" : "edges"}</small></div>
      ${rows.length ? `<table class="transition-table"><thead><tr><th>From</th><th>To</th><th>Count</th></tr></thead><tbody>${rows.map((r) => `<tr><td><strong>${escapeHtml(r.sourceLabel)}</strong><small>${escapeHtml(r.sourceId)}</small></td><td><strong>${escapeHtml(r.targetLabel)}</strong><small>${escapeHtml(r.targetId)}</small></td><td>${r.count.toLocaleString(void 0, { maximumFractionDigits: 1 })}</td></tr>`).join("")}</tbody></table>` : "<p>No learned transitions yet.</p>"}
    </section></main>`;
  }

  // frontend/components/activity.ts
  var filterLabels = {
    edges: "Production edges",
    rejected: "Rejected decisions",
    observations: "Policy observations",
    all: "All retained"
  };
  var filters = ["edges", "rejected", "observations", "all"];
  var pageSize = 50;
  function auditTime(entry) {
    const time = entry.event_at === void 0 ? NaN : Date.parse(entry.event_at);
    return Number.isFinite(time) ? time : 0;
  }
  function renderOwnership(ctx, model, activeCount) {
    const entries = Object.entries(model.policy ?? {}).sort(
      ([left], [right]) => zoneLabel(ctx.map, left).localeCompare(zoneLabel(ctx.map, right))
    );
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
              <div><strong>${escapeHtml(zoneLabel(ctx.map, zone))}</strong><small>${state.active ? "Active" : "Inactive"}</small></div>
            </div>
            <p>${state.pending_release_since ? `Release dwell since ${escapeHtml(formatTimestamp(state.pending_release_since))}` : "No release dwell pending"}</p>
            <div class="ownership-probabilities">
              <span>Belief ${escapeHtml(formatPercent(model.beliefs?.[zone]))}</span>
              <span>${escapeHtml(state.profile || "unprofiled")}</span>
            </div>
          </article>
        `).join("") : '<p class="empty-state">No zone ownership state is available yet.</p>'}
      </div>
    </section>
  `;
  }
  function renderRetention(ordered, activeCount) {
    return `
    <section class="activity-metrics">
      <div><strong>${activeCount}</strong><span>Active now</span></div>
      <div><strong>${escapeHtml(ordered.length.toLocaleString())}</strong><span>Retained decisions</span></div>
      <p>Bounded audit &middot; ${escapeHtml(formatTimestamp(ordered[ordered.length - 1]?.event_at))} to ${escapeHtml(formatTimestamp(ordered[0]?.event_at))}</p>
    </section>
  `;
  }
  function renderAuditEntry(ctx, entry) {
    const [before, after] = auditTransition(entry);
    const kind = auditKind(entry);
    const title = kind === "edges" ? after ? "Turned on" : "Turned off" : kind === "rejected" ? "Decision rejected" : "Policy observation";
    const evidenceCount = entry.evidence_ids?.length ?? 0;
    return `
    <article class="audit-row kind-${kind}">
      <div class="audit-marker" aria-hidden="true"></div>
      <div class="audit-content">
        <div class="audit-row-head">
          <div><strong>${title}</strong><span>${escapeHtml(zoneLabel(ctx.map, entry.zone))}</span></div>
          <time>${escapeHtml(formatTimestamp(entry.event_at))}</time>
        </div>
        <p>${escapeHtml(decisionExplanation(entry))}</p>
        <div class="audit-meta">
          <span class="context-badge lightweight">Zone-local decision</span>
          ${kind === "edges" ? `<span>${before ? "On" : "Off"} to ${after ? "On" : "Off"}</span>` : ""}
          ${evidenceCount ? `<span>${evidenceCount} evidence ${evidenceCount === 1 ? "item" : "items"}</span>` : ""}
        </div>
      </div>
    </article>
  `;
  }
  function renderTimeline(ctx, ordered, filter, limit) {
    const filtered = filter === "all" ? ordered : ordered.filter((entry) => auditKind(entry) === filter);
    const rowLimit = Number.isFinite(limit) && limit >= pageSize ? Math.floor(limit / pageSize) * pageSize : pageSize;
    const visible = filtered.slice(0, rowLimit);
    return `
    <section class="audit-section">
      <div class="audit-heading">
        <div class="section-title"><h3>Decision Timeline</h3><small>Newest first</small></div>
        <div class="activity-filters" role="group" aria-label="Activity filter">
          ${filters.map((value) => `<button type="button" class="${filter === value ? "active" : ""}" data-activity-filter="${value}" aria-pressed="${filter === value ? "true" : "false"}">${filterLabels[value]}</button>`).join("")}
        </div>
      </div>
      <div class="audit-list">
        ${visible.length ? visible.map((entry) => renderAuditEntry(ctx, entry)).join("") : `<p class="empty-state">No ${escapeHtml(filterLabels[filter].toLowerCase())} in retained activity.</p>`}
      </div>
      ${filtered.length > visible.length ? '<button type="button" class="show-more" data-action="show-more-audit">Show 50 more</button>' : ""}
    </section>
  `;
  }
  function renderActivity(ctx, filter, limit) {
    const model = policyModel(ctx.status);
    const activeCount = Object.values(model?.policy ?? {}).filter((state) => state.active).length;
    const ordered = [...model?.policy_audit ?? []].sort((left, right) => auditTime(right) - auditTime(left));
    const statusText = ctx.statusError !== void 0 ? `Status unavailable: ${ctx.statusError}${ctx.status ? " · Showing the last successful snapshot (stale)." : ""}` : `Updated ${ctx.updated?.toLocaleTimeString() ?? "never"}`;
    return `
    <main class="activity-layout">
      <section class="occupancy-toolbar">
        <div>
          <h2>Activity</h2>
          <p${ctx.statusError !== void 0 ? ' class="status-stale" role="status"' : ""}>${escapeHtml(statusText)}</p>
        </div>
        <button type="button" data-action="refresh-status">Refresh</button>
      </section>
      ${model ? `${renderOwnership(ctx, model, activeCount)}${renderRetention(ordered, activeCount)}${renderTimeline(ctx, ordered, filter, limit)}` : `
        <section class="activity-empty">
          <h3>Waiting for zone-belief activity</h3>
          <p>Policy activity will appear after the first observation.</p>
        </section>
      `}
    </main>
  `;
  }
  function bindActivity(root, actions) {
    root.querySelectorAll("[data-activity-filter]").forEach((button) => {
      if (!(button instanceof HTMLButtonElement)) return;
      button.addEventListener("click", (event) => {
        const target = event.currentTarget;
        if (!(target instanceof HTMLButtonElement) || target.disabled) return;
        const value = target.dataset.activityFilter;
        if (value === "edges" || value === "rejected" || value === "observations" || value === "all") {
          actions.filter(value);
        }
      });
    });
    const more = root.querySelector('[data-action="show-more-audit"]');
    if (more instanceof HTMLButtonElement) {
      more.addEventListener("click", (event) => {
        if (event.currentTarget instanceof HTMLButtonElement && !event.currentTarget.disabled) actions.more();
      });
    }
  }

  // frontend/components/reliability.ts
  function renderReliability(ctx) {
    const diagnostics = ctx.status?.occupancy_diagnostics;
    const warnings = (diagnostics?.reliability_warnings ?? []).filter((warning2) => warning2.active);
    const statusText = ctx.statusError !== void 0 ? `Status unavailable: ${ctx.statusError}${ctx.status ? " · Showing the last successful snapshot (stale)." : ""}` : `Updated ${ctx.updated?.toLocaleTimeString() ?? "never"}`;
    return `
    <main class="reliability-layout">
      <section class="occupancy-toolbar">
        <div>
          <h2>Reliability</h2>
          <p${ctx.statusError !== void 0 ? ' class="status-stale" role="status"' : ""}>${escapeHtml(statusText)}</p>
        </div>
        <button type="button" data-action="refresh-status">Refresh</button>
      </section>
      <section class="reliability-summary">
        <div class="reliability-metrics">
          <div><strong>${diagnostics?.episodes?.length ?? 0}</strong><span>Physical nodes</span></div>
          <div><strong>${warnings.length}</strong><span>Health warnings</span></div>
          <div><strong>${escapeHtml(diagnostics?.processing?.token_count ?? 0)}</strong><span>Traversal tokens</span></div>
        </div>
        <p>Warnings reflect observed sensor patterns or unverified paths. Continuous presence alone does not establish a sensor fault.</p>
      </section>
      <section class="reliability-section">
        <div class="section-head">
          <h3>Sensor Health</h3>
          <small>${warnings.length} ${warnings.length === 1 ? "warning" : "warnings"}</small>
        </div>
        <div class="reliability-list">
          ${warnings.length ? warnings.map((warning2) => `
            <article class="reliability-row">
              <div class="reliability-row-head"><strong>${escapeHtml(warning2.node_id)}</strong><span>${escapeHtml(zoneLabel(ctx.map, warning2.zone))}</span></div>
              <p>${escapeHtml(warningLabel(warning2))}${warning2.reasons?.length ? ` &middot; ${warning2.reasons.map((reason) => escapeHtml(labelFromValue(reason))).join(" · ")}` : ""}</p>
              <small>Last observed ${escapeHtml(formatTimestamp(warning2.last_observed_at))}</small>
            </article>
          `).join("") : '<p class="empty-state">No sensor health warnings.</p>'}
        </div>
      </section>
    </main>
  `;
  }

  // frontend/components/map-editor.ts
  function nodeBehavior(map2, node) {
    const zone = Object.entries(map2.zones ?? {}).find(([zoneId]) => zoneId === node.zone)?.[1];
    return node.occupancy_behavior || zone?.occupancy_behavior || defaultBehaviorForRole(node.role);
  }
  function nodeEntitySummary(node, fallback) {
    const entities = Object.values(node.entities ?? {}).flatMap((value) => typeof value === "string" ? [value] : value);
    const first = entities[0];
    if (first === void 0) return fallback;
    return entities.length === 1 ? first : `${first} + ${entities.length - 1} more`;
  }
  function entityMappingText(node) {
    return formatEntities(node.entities ?? {});
  }
  function displayCoordinate(value) {
    return value !== void 0 && Number.isFinite(value) ? value : 80;
  }
  function renderEntities(entities, filter) {
    const query = filter.toLowerCase();
    let visible = 0;
    const rows = entities.map((entity) => {
      const matches = [entity.entity_id, entity.name, entity.device_class, entity.state].some((value) => value !== void 0 && value !== null && value.toLowerCase().includes(query));
      if (matches) visible += 1;
      return `
      <div class="entity" draggable="true" data-entity="${escapeHtml(entity.entity_id)}"${matches ? "" : " hidden"}>
        <strong>${escapeHtml(entity.name || entity.entity_id)}</strong>
        <span>${escapeHtml(entity.entity_id)}</span>
        <small>${escapeHtml(entity.device_class || "binary_sensor")} · ${escapeHtml(entity.state ?? "unknown")}</small>
        <button type="button" data-add-entity="${escapeHtml(entity.entity_id)}" aria-label="${escapeHtml(`Add ${entity.name || entity.entity_id} to map`)}">Add to Map</button>
      </div>
    `;
    }).join("");
    return rows + (visible ? "" : `<p class="empty-state">${entities.length ? "No entities match the filter." : "No motion entities available."}</p>`);
  }
  function renderNode(props, nodeId, node) {
    return `
    <button type="button" class="node ${props.selectedNode === nodeId ? "selected" : ""}" draggable="true" data-node="${escapeHtml(nodeId)}" aria-pressed="${props.selectedNode === nodeId ? "true" : "false"}" style="left:${displayCoordinate(node.position?.x)}px;top:${displayCoordinate(node.position?.y)}px">
      <strong>${escapeHtml(node.label || nodeId)}</strong>
      <span>${escapeHtml(nodeEntitySummary(node, nodeId))}</span>
      <small>${escapeHtml(labelFromValue(nodeBehavior(props.map, node)))} · ${escapeHtml(labelFromValue(node.role || "room_occupancy"))}</small>
    </button>
  `;
  }
  function renderEdges(nodes) {
    const seen = /* @__PURE__ */ new Set();
    const lines = [];
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
    return lines.join("");
  }
  function renderInspector(props, nodeId, node) {
    const adjacent = new Set(node.adjacent ?? []);
    for (const [sourceId, source] of Object.entries(props.map.nodes)) {
      if (source.adjacent?.includes(nodeId)) adjacent.add(sourceId);
    }
    return `
    <label>Node ID<input data-field="node_id" value="${escapeHtml(nodeId)}" /></label>
    <label>Label<input data-field="label" value="${escapeHtml(node.label || nodeId)}" /></label>
    <label>Zone<input data-field="zone" value="${escapeHtml(node.zone ?? "")}" placeholder="Defaults to node ID" /></label>
    <label>Floor<input data-field="floor" value="${escapeHtml(node.floor ?? "")}" /></label>
    <label>Role<input data-field="role" value="${escapeHtml(node.role || "room_occupancy")}" /></label>
    <label>Occupancy behavior<input data-field="occupancy_behavior" value="${escapeHtml(nodeBehavior(props.map, node))}" /></label>
    <label>Entities<textarea class="small" data-field="entities" spellcheck="false">${escapeHtml(entityMappingText(node))}</textarea></label>
    <small>One kind per line; use an array for aliases, for example motion: ["binary_sensor.a", "binary_sensor.b"].</small>
    <label>Sensor reliability<input data-field="reliability" type="number" min="0.01" max="1" step="0.01" value="${escapeHtml(node.reliability ?? 1)}" /></label>
    <label>Route prior weight<input data-field="route_prior_weight" type="number" min="0.01" step="0.01" value="${escapeHtml(node.route_prior_weight ?? 1)}" /></label>
    <label>X position<input data-field="x" type="number" min="0" step="1" value="${displayCoordinate(node.position?.x)}" /></label>
    <label>Y position<input data-field="y" type="number" min="0" step="1" value="${displayCoordinate(node.position?.y)}" /></label>
    <h3>Adjacent</h3>
    <div class="chips">
      ${adjacent.size ? [...adjacent].map((target) => `<button type="button" data-remove-adjacent="${escapeHtml(target)}" aria-label="${escapeHtml(`Remove edge to ${target} in both directions`)}">${escapeHtml(target)} ×</button>`).join("") : "<p>No edges yet.</p>"}
    </div>
  `;
  }
  function renderMap(props) {
    const nodes = new Map(Object.entries(props.map.nodes));
    const selected = props.selectedNode === void 0 ? void 0 : nodes.get(props.selectedNode);
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
          <button type="button" data-action="connect" class="${props.connectMode ? "active" : ""}" aria-pressed="${props.connectMode ? "true" : "false"}">Connect</button>
          <button type="button" data-action="delete"${selected ? "" : " disabled"}>Delete</button>
        </div>
        ${props.connectMode ? '<p role="status">Select a source node, then a different destination to connect them in both directions. Select Connect again to cancel.</p>' : ""}
        <div class="board" data-board role="group" aria-label="Editable motion graph">
          <svg class="edges" aria-hidden="true">${renderEdges(nodes)}</svg>
          ${[...nodes].map(([nodeId, node]) => renderNode(props, nodeId, node)).join("")}
        </div>
      </section>
      <section class="inspector">
        <h2>Node</h2>
        ${props.fieldError !== void 0 ? `<p class="pc-error" role="alert">${escapeHtml(props.fieldError)}</p>` : ""}
        ${selected && props.selectedNode !== void 0 ? renderInspector(props, props.selectedNode, selected) : "<p>Select a node to edit it.</p>"}
      </section>
    </main>
  `;
  }
  function bindButton(root, selector, action) {
    const button = root.querySelector(selector);
    if (!(button instanceof HTMLButtonElement)) return;
    button.addEventListener("click", (event) => {
      if (event.currentTarget instanceof HTMLButtonElement && !event.currentTarget.disabled) action();
    });
  }
  function startDrag(event, key, id) {
    const transfer = event.dataTransfer;
    if (!transfer) return;
    try {
      transfer.clearData("node_id");
      transfer.clearData("entity_id");
      transfer.setData(key, id);
      transfer.effectAllowed = key === "node_id" ? "move" : "copy";
    } catch {
      event.preventDefault();
    }
  }
  function bindDragAndDrop(root, actions) {
    const entityIds = /* @__PURE__ */ new Set();
    const nodeIds = /* @__PURE__ */ new Set();
    root.querySelectorAll("[data-entity]").forEach((item) => {
      if (!(item instanceof HTMLElement)) return;
      const entityId = item.dataset.entity;
      if (entityId === void 0) return;
      entityIds.add(entityId);
      item.addEventListener("dragstart", (event) => {
        const target = event.currentTarget;
        if (target instanceof HTMLElement && target.dataset.entity === entityId && !target.hidden) {
          startDrag(event, "entity_id", entityId);
        }
      });
    });
    root.querySelectorAll("[data-node]").forEach((button) => {
      if (!(button instanceof HTMLButtonElement)) return;
      const nodeId = button.dataset.node;
      if (nodeId === void 0) return;
      nodeIds.add(nodeId);
      button.addEventListener("click", (event) => {
        const target = event.currentTarget;
        if (target instanceof HTMLButtonElement && !target.disabled) actions.select(nodeId);
      });
      button.addEventListener("dragstart", (event) => {
        const target = event.currentTarget;
        if (target instanceof HTMLButtonElement && !target.disabled) startDrag(event, "node_id", nodeId);
      });
    });
    const board = root.querySelector("[data-board]");
    if (!(board instanceof HTMLElement)) return;
    board.addEventListener("dragover", (event) => {
      const transfer = event.dataTransfer;
      if (transfer && (transfer.types.includes("node_id") || transfer.types.includes("entity_id"))) {
        event.preventDefault();
      }
    });
    board.addEventListener("drop", (event) => {
      const target = event.currentTarget;
      const transfer = event.dataTransfer;
      if (!(target instanceof HTMLElement) || !transfer) return;
      event.preventDefault();
      let entityId;
      let nodeId;
      try {
        entityId = transfer.getData("entity_id");
        nodeId = transfer.getData("node_id");
      } catch {
        return;
      }
      if (entityId && nodeId) return;
      const rect = target.getBoundingClientRect();
      const x = Math.max(0, event.clientX - rect.left - target.clientLeft + target.scrollLeft - 90);
      const y = Math.max(0, event.clientY - rect.top - target.clientTop + target.scrollTop - 28);
      if (!Number.isFinite(x) || !Number.isFinite(y)) return;
      if (entityId && entityIds.has(entityId)) actions.addEntity(entityId, x, y);
      else if (nodeId && nodeIds.has(nodeId)) actions.move(nodeId, x, y);
    });
  }
  function bindMap(root, actions) {
    bindButton(root, '[data-action="add-empty"]', () => actions.add());
    bindButton(root, '[data-action="delete"]', () => actions.remove());
    bindButton(root, '[data-action="connect"]', () => actions.connect());
    bindDragAndDrop(root, actions);
    root.querySelectorAll("[data-add-entity]").forEach((button) => {
      if (!(button instanceof HTMLButtonElement)) return;
      button.addEventListener("click", (event) => {
        const target = event.currentTarget;
        if (!(target instanceof HTMLButtonElement) || target.disabled) return;
        const entityId = target.dataset.addEntity;
        if (entityId !== void 0) actions.addEntity(entityId, 80, 80);
      });
    });
    root.querySelectorAll("[data-field]").forEach((input) => {
      if (!(input instanceof HTMLInputElement) && !(input instanceof HTMLTextAreaElement)) return;
      input.addEventListener("change", (event) => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement) && !(target instanceof HTMLTextAreaElement)) return;
        if (target !== input || target.disabled || target.readOnly) return;
        const field = target.dataset.field;
        if (field === "node_id" || field === "label" || field === "zone" || field === "floor" || field === "role" || field === "occupancy_behavior" || field === "entities" || field === "reliability" || field === "route_prior_weight" || field === "x" || field === "y") {
          actions.updateField(field, target.value);
        }
      });
    });
    root.querySelectorAll("[data-remove-adjacent]").forEach((button) => {
      if (!(button instanceof HTMLButtonElement)) return;
      button.addEventListener("click", (event) => {
        const target = event.currentTarget;
        if (!(target instanceof HTMLButtonElement) || target.disabled) return;
        const adjacent = target.dataset.removeAdjacent;
        if (adjacent !== void 0) actions.removeEdge(adjacent);
      });
    });
    const filter = root.querySelector("[data-filter]");
    if (filter instanceof HTMLInputElement) {
      filter.addEventListener("input", (event) => {
        const target = event.target;
        if (target instanceof HTMLInputElement && target === filter && !target.disabled) actions.filter(target.value);
      });
    }
  }

  // frontend/components/settings.ts
  function renderSettings(config, cleanupMessage, busy) {
    const disabled = busy ? " disabled" : "";
    return `
    <main class="single-panel settings" aria-busy="${busy ? "true" : "false"}">
      <label>Transition window seconds<input data-setting="transition_window_seconds" type="number" min="1" step="1" value="${escapeHtml(config.transition_window_seconds)}"${disabled} /></label>
      <label>Expected occupants<input data-setting="expected_occupants" type="number" min="0" max="2" step="1" value="${escapeHtml(config.expected_occupants)}"${disabled} /></label>
      <label>Expected occupants entity<input data-setting="expected_occupants_entity" type="text" value="${escapeHtml(config.expected_occupants_entity ?? "")}"${disabled} /></label>
      <section class="maintenance-section">
        <h3>Entities</h3>
        <button type="button" data-action="cleanup-entities"${disabled}>Clean Stale Entities</button>
        ${cleanupMessage !== void 0 ? `<p role="status">${escapeHtml(cleanupMessage)}</p>` : ""}
      </section>
    </main>
  `;
  }
  function bindSettings(root, actions) {
    root.querySelectorAll("[data-setting]").forEach((input) => {
      if (!(input instanceof HTMLInputElement)) return;
      input.addEventListener("input", (event) => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement) || target !== input || target.disabled) return;
        const field = target.dataset.setting;
        if (field === "transition_window_seconds" || field === "expected_occupants" || field === "expected_occupants_entity") {
          actions.setting(field, target.value);
        }
      });
    });
    const cleanup = root.querySelector('[data-action="cleanup-entities"]');
    if (cleanup instanceof HTMLButtonElement) {
      cleanup.addEventListener("click", (event) => {
        if (event.currentTarget instanceof HTMLButtonElement && !event.currentTarget.disabled) actions.cleanup();
      });
    }
  }

  // frontend/components/yaml-editor.ts
  function renderYaml(yaml) {
    return `
    <main class="single-panel">
      <h2>Map YAML</h2>
      <textarea data-map-yaml aria-label="Map YAML" spellcheck="false">
${escapeHtml(yaml)}</textarea>
    </main>
  `;
  }
  function bindYaml(root, input) {
    const editor = root.querySelector("[data-map-yaml]");
    if (!(editor instanceof HTMLTextAreaElement)) return;
    editor.addEventListener("input", (event) => {
      const target = event.target;
      if (target instanceof HTMLTextAreaElement && target === editor && !target.disabled && !target.readOnly) {
        input(target.value);
      }
    });
  }

  // frontend/panel.ts
  var tabs = ["occupancy", "reliability", "activity", "map", "yaml", "settings"];
  function isTab(value) {
    return tabs.some((tab) => tab === value);
  }
  var PredictiveControlsPanel = class extends HTMLElement {
    _hass;
    _config;
    _status;
    _entities = [];
    _error;
    _statusError;
    _statusUpdated;
    _cleanupMessage;
    _selectedNode;
    _mapYamlDirty = false;
    _tab = "occupancy";
    _activityFilter = "edges";
    _auditLimit = 50;
    _connectMode = false;
    entityFilter = "";
    revision = 0;
    savedRevision = 0;
    generation = 0;
    loaded = false;
    detached = false;
    loading = false;
    saving = false;
    cleaning = false;
    fieldError;
    invalidFields = /* @__PURE__ */ new Map();
    deferredRender = false;
    finishDeferredRender = () => {
      queueMicrotask(() => {
        if (this.deferredRender && !this.detached) this.render(true);
      });
    };
    statusTask;
    statusTimer;
    narrow = false;
    panel;
    set hass(value) {
      this._hass = value;
      if (!this.loaded && !this.detached) {
        this.loaded = true;
        void this.loadData();
      }
    }
    get hass() {
      return this._hass;
    }
    connectedCallback() {
      const reconnect = this.detached;
      this.detached = false;
      if (this._hass && (!this.loaded || reconnect)) {
        this.loaded = true;
        void this.loadData();
      }
      this.startStatusRefresh();
      this.render();
    }
    disconnectedCallback() {
      this.detached = true;
      this.invalidate();
      if (this.statusTimer !== void 0) clearInterval(this.statusTimer);
      this.statusTimer = void 0;
    }
    invalidate() {
      this.generation++;
      this.statusTask = void 0;
      this.loading = false;
      return this.generation;
    }
    current(generation) {
      return generation === this.generation && !this.detached;
    }
    get nodes() {
      return this._config?.map?.nodes || {};
    }
    context() {
      return { map: this._config?.map || { nodes: {} }, status: this._status, statusError: this._statusError, updated: this._statusUpdated };
    }
    async loadData() {
      const hass = this._hass;
      if (!hass || this.detached) return;
      const generation = this.invalidate();
      const revision = this.revision;
      this.loading = true;
      this._error = void 0;
      const configTask = request(hass, { type: "predictive_controls/config" }).then(decodeConfig);
      const entitiesTask = request(hass, { type: "predictive_controls/entities" }).then(normalizeEntityResponse);
      const statusTask = request(hass, { type: "predictive_controls/status" }).then(decodeStatus);
      this.render();
      const [config, entities, status] = await Promise.allSettled([configTask, entitiesTask, statusTask]);
      if (!this.current(generation)) return;
      this.loading = false;
      if (config.status === "fulfilled") {
        if (this.revision === revision && this.revision === this.savedRevision) {
          this._config = config.value;
          this._selectedNode = void 0;
          this._mapYamlDirty = false;
        }
      } else this._error = `Configuration: ${errorMessage(config.reason)}`;
      if (entities.status === "fulfilled") this._entities = entities.value;
      else this._error = [this._error, `Entities: ${errorMessage(entities.reason)}`].filter(Boolean).join(" · ");
      if (status.status === "fulfilled") {
        this._status = status.value;
        this._statusError = void 0;
        this._statusUpdated = /* @__PURE__ */ new Date();
      } else this._statusError = errorMessage(status.reason);
      this.render();
    }
    startStatusRefresh() {
      if (this.statusTimer !== void 0) return;
      this.statusTimer = setInterval(() => {
        void this.refreshStatus();
      }, 5e3);
    }
    async refreshStatus() {
      if (this.statusTask) return this.statusTask;
      const hass = this._hass;
      const config = this._config;
      if (!hass || !config || this.detached || this.loading || this.saving) return;
      const generation = this.generation;
      const task = (async () => {
        try {
          const status = decodeStatus(await request(hass, { type: "predictive_controls/status", entry_id: config.entry_id }));
          if (!this.current(generation)) return;
          this._status = status;
          this._statusError = void 0;
          this._statusUpdated = /* @__PURE__ */ new Date();
        } catch (error) {
          if (!this.current(generation)) return;
          this._statusError = errorMessage(error);
        }
        if (this.current(generation) && ["occupancy", "reliability", "activity"].includes(this._tab)) this.render(true);
      })();
      this.statusTask = task;
      try {
        await task;
      } finally {
        if (this.statusTask === task) this.statusTask = void 0;
      }
    }
    render(automatic = false) {
      if (!this._hass) return;
      const focused = this.ownerDocument?.activeElement;
      if (automatic && focused && this.contains(focused) && focused.matches("input,textarea,select,button,[tabindex]")) {
        this.deferredRender = true;
        const banner = this.querySelector("[data-status-banner]");
        if (banner) banner.textContent = this._statusError ? `Stale / unavailable: ${this._statusError}. Displayed snapshot is not current.` : "New snapshot received; display will update when focus leaves the control.";
        return;
      }
      this.deferredRender = false;
      const scrolls = [...this.querySelectorAll("[data-scroll-key],.floor-section,.board,.entities")].map((el) => ({ key: el.getAttribute("data-scroll-key") || el.className, x: el.scrollLeft, y: el.scrollTop }));
      const top = this.scrollTop;
      const left = this.scrollLeft;
      this.innerHTML = `<style>${panelStyles}</style><div class="pc-shell">
      <header><div><h1>Predictive Controls</h1><p>Build the motion graph and configure one fast, evidence-aware active control per zone.</p></div>
        <div class="pc-actions"><button data-action="reload"${this.loading ? " disabled" : ""}>Reload</button><button class="primary" data-action="save"${this.saving || !this._config ? " disabled" : ""}>${this.saving ? "Saving…" : "Save"}</button></div></header>
      <p class="pc-error" role="alert" data-error>${escapeHtml(this._error || this.fieldError || "")}</p>
      <p role="status" data-status-banner>${this._statusError ? `Stale / unavailable: ${escapeHtml(this._statusError)}. Last successful snapshot is historical.` : ""}</p>
      ${this._config ? `<nav aria-label="Panel tabs">${tabs.map((tab) => `<button class="${this._tab === tab ? "active" : ""}" aria-pressed="${this._tab === tab}" data-tab="${tab}">${tab === "yaml" ? "YAML" : tab[0]?.toUpperCase() + tab.slice(1)}</button>`).join("\n")}</nav>${this.renderActiveTab()}` : `<p>${this._error ? "Unable to load configuration. Use Reload to retry." : "Loading Predictive Controls..."}</p>`}
    </div>`;
      this.scrollTop = top;
      this.scrollLeft = left;
      for (const element of this.querySelectorAll("[data-scroll-key],.floor-section,.board,.entities")) {
        const key = element.getAttribute("data-scroll-key") || element.className;
        const previous = scrolls.find((item) => item.key === key);
        if (previous) {
          element.scrollLeft = previous.x;
          element.scrollTop = previous.y;
        }
      }
      if (this.ownerDocument) {
        for (const input of this.querySelectorAll("[data-field]")) {
          if (!(input instanceof HTMLInputElement) && !(input instanceof HTMLTextAreaElement)) continue;
          const draft = this.invalidFields.get(`${this._selectedNode}\0${input.dataset.field}`);
          if (draft) {
            input.value = draft.value;
            input.setAttribute("aria-invalid", "true");
          }
        }
        if (this.saving) {
          for (const control of this.querySelectorAll(".map-layout button,.map-layout input,.map-layout textarea")) {
            if (control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement || control instanceof HTMLButtonElement) control.disabled = true;
          }
          for (const draggable of this.querySelectorAll(".map-layout [draggable]")) {
            if (draggable instanceof HTMLElement) draggable.draggable = false;
          }
        }
        this.bindEvents();
      }
    }
    renderActiveTab() {
      const config = this._config;
      if (!config) return "";
      const ctx = this.context();
      if (this._tab === "occupancy") return renderOccupancy(ctx, this.clientWidth || 0);
      if (this._tab === "reliability") return renderReliability(ctx);
      if (this._tab === "activity") return renderActivity(ctx, this._activityFilter, this._auditLimit);
      if (this._tab === "settings") return renderSettings(config, this._cleanupMessage, this.cleaning);
      if (this._tab === "yaml") {
        if (!this._mapYamlDirty) this.syncMapYamlFromMap();
        return renderYaml(config.map_yaml);
      }
      return renderMap({ map: ctx.map, entities: this._entities, selectedNode: this._selectedNode, connectMode: this._connectMode, filter: this.entityFilter, fieldError: this.fieldError });
    }
    /** Generated compatibility asset delegates the old test helper to the actual card component. */
    renderZoneCard(zone, minX, minY) {
      const ctx = this.context();
      const normalized = { ...zone, position: { x: zone.position.x ?? 80, y: zone.position.y ?? 80 }, size: { width: zone.size.width ?? 210, height: zone.size.height ?? 112 } };
      return renderZoneCard(normalized, minX, minY, ctx, projectPaths(ctx.map, ctx.status?.occupancy_diagnostics, ctx.status?.expected_occupants));
    }
    bindEvents() {
      this.removeEventListener("focusout", this.finishDeferredRender);
      this.addEventListener("focusout", this.finishDeferredRender);
      this.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => {
        if (!(button instanceof HTMLElement) || !isTab(button.dataset.tab)) return;
        if (button.dataset.tab === "map" && this._mapYamlDirty && this._config) {
          try {
            this._config.map = parseMapYaml(this._config.map_yaml);
            if (this._selectedNode && !Object.hasOwn(this.nodes, this._selectedNode)) this._selectedNode = void 0;
            for (const [key, draft] of this.invalidFields) if (!Object.hasOwn(this.nodes, draft.node)) this.invalidFields.delete(key);
            this.fieldError = this.invalidFields.values().next().value?.error;
            this._error = void 0;
          } catch (error) {
            this._error = errorMessage(error);
            this.render();
            return;
          }
        }
        this._tab = button.dataset.tab;
        this.render();
        if (["occupancy", "reliability", "activity"].includes(this._tab)) void this.refreshStatus();
      }));
      this.querySelector('[data-action="reload"]')?.addEventListener("click", () => {
        if (this.revision !== this.savedRevision || this.fieldError) {
          if (!confirm("Discard unsaved edits and reload configuration?")) return;
          this.savedRevision = ++this.revision;
          this.fieldError = void 0;
          this.invalidFields.clear();
        }
        void this.loadData();
      });
      this.querySelector('[data-action="save"]')?.addEventListener("click", () => {
        void this.save();
      });
      this.querySelector('[data-action="refresh-status"]')?.addEventListener("click", () => {
        void this.refreshStatus();
      });
      if (this._tab === "activity") bindActivity(this, { filter: (value) => {
        this._activityFilter = value;
        this._auditLimit = 50;
        this.render();
      }, more: () => {
        this._auditLimit += 50;
        this.render();
      } });
      if (this._tab === "map") bindMap(this, {
        select: (id) => this.selectOrConnect(id),
        add: () => this.addNode(),
        remove: () => this.deleteSelected(),
        connect: () => {
          this._connectMode = !this._connectMode;
          this.render();
        },
        move: (id, x, y) => this.moveNode(id, x, y),
        addEntity: (id, x, y) => this.addNodeForEntity(id, x, y),
        updateField: (field, value) => this.updateField(field, value),
        removeEdge: (target) => this.removeEdge(this._selectedNode, target),
        filter: (value) => this.filterEntities(value)
      });
      if (this._tab === "settings") bindSettings(this, {
        setting: (field, value) => {
          if (!this._config) return;
          if (field === "expected_occupants_entity") this._config.expected_occupants_entity = value;
          else if (field === "expected_occupants") this._config.expected_occupants = value.trim() ? Number(value) : NaN;
          else if (field === "transition_window_seconds") this._config.transition_window_seconds = value.trim() ? Number(value) : NaN;
          this.revision++;
        },
        cleanup: () => {
          void this.cleanupEntities();
        }
      });
      if (this._tab === "yaml") bindYaml(this, (value) => {
        if (!this._config) return;
        this._config.map_yaml = value;
        this._mapYamlDirty = true;
        this.revision++;
      });
    }
    edit(action, field) {
      const key = field ? `${field.node}\0${field.field}` : void 0;
      try {
        if (this._mapYamlDirty && this._config) this._config.map = parseMapYaml(this._config.map_yaml);
        action();
        if (key) this.invalidFields.delete(key);
        this.fieldError = this.invalidFields.values().next().value?.error;
        this.markMapChanged();
        this.render();
      } catch (error) {
        this.fieldError = errorMessage(error);
        if (field && key) this.invalidFields.set(key, { ...field, error: this.fieldError });
        const message = this.querySelector("[data-error]");
        if (message) message.textContent = this.fieldError;
      }
    }
    selectOrConnect(id) {
      if (!Object.hasOwn(this.nodes, id)) return;
      if (this._connectMode && this._selectedNode && this._selectedNode !== id) {
        this.addEdge(this._selectedNode, id);
        this._connectMode = false;
      }
      this._selectedNode = id;
      this.render();
    }
    addNodeForEntity(id, x, y) {
      this.edit(() => {
        const entity = this._entities.find((item) => item.entity_id === id);
        if (!entity) throw new Error("Entity is not in the current catalog");
        const { nodeId, node } = createNodeForEntity(this.nodes, entity, x, y);
        Object.defineProperty(this.nodes, nodeId, { value: node, enumerable: true, writable: true, configurable: true });
        this._selectedNode = nodeId;
      });
    }
    addNode() {
      this.edit(() => {
        const { nodeId, node } = createEmptyNode(this.nodes);
        this.nodes[nodeId] = node;
        this._selectedNode = nodeId;
      });
    }
    moveNode(id, x, y) {
      this.edit(() => {
        moveNode(this.nodes, id, x, y);
      });
    }
    updateField(field, value) {
      const selected = this._selectedNode;
      if (!selected) return;
      this.edit(() => {
        const id = this._selectedNode;
        const node = id ? this.nodes[id] : void 0;
        if (!node || !id) return;
        if (field === "node_id") {
          const renamed = renameNode(this.nodes, id, value);
          this._selectedNode = renamed;
          if (renamed !== id) for (const [key, draft] of [...this.invalidFields]) {
            if (draft.node !== id) continue;
            this.invalidFields.delete(key);
            if (draft.field !== "node_id") this.invalidFields.set(`${renamed}\0${draft.field}`, { ...draft, node: renamed });
          }
          return;
        }
        const changed = { ...node };
        if (field === "entities") changed.entities = parseEntities(value);
        else if (field === "x" || field === "y") {
          const number = value.trim() ? Number(value) : NaN;
          if (!Number.isFinite(number) || number < 0) throw new Error("Position must be finite and nonnegative");
          changed.position = { x: node.position?.x ?? 80, y: node.position?.y ?? 80, ...node.position, [field]: number };
        } else if (field === "reliability" || field === "route_prior_weight") {
          const number = value.trim() ? Number(value) : NaN;
          if (!(number > 0)) throw new Error("Weight must be positive");
          changed[field] = number;
        } else if (field === "label" || field === "role" || field === "occupancy_behavior" || field === "floor" || field === "zone") {
          if (field === "zone" && !value) delete changed.zone;
          else changed[field] = value;
        } else throw new Error("Unknown node field");
        this.nodes[id] = decodeNode(changed);
      }, { node: selected, field, value });
    }
    addEdge(source, target) {
      this.edit(() => {
        addBidirectionalEdge(this.nodes, source, target);
      });
    }
    removeEdge(source, target) {
      if (source) this.edit(() => {
        removeBidirectionalEdge(this.nodes, source, target);
      });
    }
    deleteSelected() {
      this.edit(() => {
        if (this._selectedNode) {
          deleteNode(this.nodes, this._selectedNode);
          for (const [key, draft] of this.invalidFields) if (draft.node === this._selectedNode) this.invalidFields.delete(key);
        }
        this._selectedNode = void 0;
      });
    }
    markMapChanged() {
      this.revision++;
      this._mapYamlDirty = false;
      this.syncMapYamlFromMap();
    }
    syncMapYamlFromMap() {
      if (this._config) this._config.map_yaml = dumpMapYaml(this._config.map);
    }
    filterEntities(value) {
      this.entityFilter = value;
      this.querySelectorAll("[data-entity]").forEach((item) => {
        if (!(item instanceof HTMLElement)) return;
        const entity = this._entities.find((row) => row.entity_id === item.dataset.entity);
        item.hidden = !entity || !entityMatchesFilter(entity, value);
      });
    }
    async save() {
      const hass = this._hass;
      const config = this._config;
      if (!hass || !config || this.saving || this.cleaning || this.loading || this.detached) return;
      let generation = this.generation;
      const revision = this.revision;
      this.saving = true;
      this._error = void 0;
      try {
        if (this.fieldError) throw new Error(this.fieldError);
        validateSettings(config);
        if (this._mapYamlDirty) parseMapYaml(config.map_yaml);
        else this.syncMapYamlFromMap();
        const message = {
          type: "predictive_controls/save_config",
          entry_id: config.entry_id,
          map: decodeMap(config.map),
          map_yaml: config.map_yaml,
          map_yaml_dirty: this._mapYamlDirty === true,
          transition_window_seconds: config.transition_window_seconds,
          expected_occupants: config.expected_occupants,
          expected_occupants_entity: config.expected_occupants_entity || ""
        };
        generation = this.invalidate();
        this._statusError = "Configuration save pending; awaiting a fresh runtime snapshot";
        this.render();
        const result = decodeConfig(await request(hass, message));
        if (!this.current(generation)) return;
        if (this.revision === revision) {
          this._config = result;
          this._mapYamlDirty = false;
          this.savedRevision = revision;
        }
      } catch (error) {
        if (this.current(generation)) this._error = errorMessage(error);
      } finally {
        this.saving = false;
        if (!this.detached) this.render();
      }
    }
    async cleanupEntities() {
      const hass = this._hass;
      const config = this._config;
      if (!hass || !config || this.cleaning || this.saving || this.detached) return;
      const generation = this.generation;
      this.cleaning = true;
      this._error = void 0;
      this.render();
      try {
        const count = decodeCleanup(await request(hass, { type: "predictive_controls/cleanup_entities", entry_id: config.entry_id, dry_run: true }), true);
        if (!this.current(generation)) return;
        if (!count) {
          this._cleanupMessage = "No stale entities found.";
          return;
        }
        if (!confirm(`Remove ${count} stale Predictive Controls entities?`)) return;
        if (!this.current(generation)) return;
        const removed = decodeCleanup(await request(hass, { type: "predictive_controls/cleanup_entities", entry_id: config.entry_id, dry_run: false }), false);
        if (this.current(generation)) this._cleanupMessage = `Removed ${removed} stale entities.`;
      } catch (error) {
        if (this.current(generation)) this._error = errorMessage(error);
      } finally {
        this.cleaning = false;
        if (!this.detached) this.render();
      }
    }
  };
  if (!customElements.get("predictive-controls-panel")) customElements.define("predictive-controls-panel", PredictiveControlsPanel);
})();
