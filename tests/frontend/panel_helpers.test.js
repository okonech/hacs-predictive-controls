import assert from "node:assert/strict";
import test from "node:test";

import {
  addBidirectionalEdge,
  createEmptyNode,
  createNodeForEntity,
  deleteNode,
  entityMatchesFilter,
  moveNode,
  normalizeEntityResponse,
  removeBidirectionalEdge,
  renameNode,
  sanitizeNodeId,
  uniqueNodeId,
} from "../../custom_components/predictive_controls/frontend/panel_helpers.js";

const liveEntityResponse = {
  entities: [
    {
      entity_id: "binary_sensor.entrance_mmwave_dimmer_motion_detection",
      name: "Entrance mmWave Dimmer Motion detection",
      state: "off",
      device_class: null,
    },
    {
      entity_id: "binary_sensor.apollo_msr_2_2cb8b0_radar_target",
      name: "Fireplace Monitor Left Radar Target",
      state: "off",
      device_class: null,
    },
    {
      entity_id: "binary_sensor.island_monitor_radar_zone_3_occupancy",
      name: "Fireplace Monitor Right Radar Zone 3 Occupancy",
      state: "off",
      device_class: null,
    },
  ],
};

test("normalizes the websocket entity shape used by the panel", () => {
  const entities = normalizeEntityResponse(liveEntityResponse);

  assert.deepEqual(
    entities.map((entity) => entity.entity_id),
    [
      "binary_sensor.apollo_msr_2_2cb8b0_radar_target",
      "binary_sensor.entrance_mmwave_dimmer_motion_detection",
      "binary_sensor.island_monitor_radar_zone_3_occupancy",
    ],
  );
});

test("creates a node from a live-shaped motion entity", () => {
  const nodes = {};
  const { nodeId, node } = createNodeForEntity(
    nodes,
    liveEntityResponse.entities[0],
    32.4,
    105.8,
  );

  assert.equal(nodeId, "entrance_mmwave_dimmer_motion_detection");
  assert.deepEqual(node, {
    label: "Entrance mmWave Dimmer Motion detection",
    entities: {
      motion: "binary_sensor.entrance_mmwave_dimmer_motion_detection",
    },
    adjacent: [],
    initial_weight: 1,
    position: { x: 32, y: 106 },
  });
});

test("sanitizes and uniquifies node ids", () => {
  const nodes = { node: {}, node_2: {}, kitchen_motion: {} };

  assert.equal(sanitizeNodeId("binary_sensor.kitchen motion"), "kitchen_motion");
  assert.equal(sanitizeNodeId("!!!"), "node");
  assert.equal(uniqueNodeId(nodes, "node"), "node_3");
  assert.equal(uniqueNodeId(nodes, "kitchen_motion"), "kitchen_motion_2");
});

test("creates empty nodes with default board placement", () => {
  const nodes = { node: {} };
  const { nodeId, node } = createEmptyNode(nodes);

  assert.equal(nodeId, "node_2");
  assert.equal(node.position.x, 80);
  assert.equal(node.position.y, 80);
});

test("moves nodes while clamping negative coordinates", () => {
  const nodes = { entry: { position: { x: 80, y: 80 } } };

  moveNode(nodes, "entry", -10.2, 33.8);
  moveNode(nodes, "missing", 100, 100);

  assert.deepEqual(nodes.entry.position, { x: 0, y: 34 });
});

test("adds and removes bidirectional edges without duplicates", () => {
  const nodes = {
    entry: { adjacent: [] },
    hall: { adjacent: [] },
  };

  addBidirectionalEdge(nodes, "entry", "hall");
  addBidirectionalEdge(nodes, "entry", "hall");
  addBidirectionalEdge(nodes, "entry", "entry");
  addBidirectionalEdge(nodes, "entry", "missing");

  assert.deepEqual(nodes.entry.adjacent, ["hall"]);
  assert.deepEqual(nodes.hall.adjacent, ["entry"]);

  removeBidirectionalEdge(nodes, "entry", "hall");
  removeBidirectionalEdge(nodes, "entry", "missing");

  assert.deepEqual(nodes.entry.adjacent, []);
  assert.deepEqual(nodes.hall.adjacent, []);
});

test("renames nodes and rewrites adjacency references", () => {
  const nodes = {
    entry: { adjacent: ["hall"] },
    hall: { adjacent: ["entry"] },
    kitchen: { adjacent: [] },
  };

  assert.equal(renameNode(nodes, "entry", "front door"), "front_door");
  assert.ok(nodes.front_door);
  assert.equal(nodes.entry, undefined);
  assert.deepEqual(nodes.hall.adjacent, ["front_door"]);
  assert.equal(renameNode(nodes, "front_door", "kitchen"), "front_door");
  assert.equal(renameNode(nodes, "missing", "other"), "missing");
});

test("deletes nodes and removes inbound adjacency", () => {
  const nodes = {
    entry: { adjacent: ["hall"] },
    hall: { adjacent: ["entry", "kitchen"] },
    kitchen: { adjacent: ["hall"] },
  };

  deleteNode(nodes, "hall");
  deleteNode(nodes, "missing");

  assert.equal(nodes.hall, undefined);
  assert.deepEqual(nodes.entry.adjacent, []);
  assert.deepEqual(nodes.kitchen.adjacent, []);
});

test("filters entities by live fields", () => {
  const entity = liveEntityResponse.entities[2];

  assert.equal(entityMatchesFilter(entity, "zone 3"), true);
  assert.equal(entityMatchesFilter(entity, "island_monitor"), true);
  assert.equal(entityMatchesFilter(entity, "garage"), false);
  assert.equal(entityMatchesFilter(entity, ""), true);
});
