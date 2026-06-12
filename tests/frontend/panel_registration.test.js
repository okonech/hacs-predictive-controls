import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

class FakeHTMLElement {
  constructor() {
    this.innerHTML = "";
  }

  querySelectorAll() {
    return [];
  }

  querySelector() {
    return null;
  }
}

const registry = new Map();
globalThis.HTMLElement = FakeHTMLElement;
globalThis.customElements = {
  get(name) {
    return registry.get(name);
  },
  define(name, constructor) {
    registry.set(name, constructor);
  },
};

async function panelConstructor() {
  await import("../../custom_components/predictive_controls/frontend/panel.js");
  return registry.get("predictive-controls-panel");
}

test("panel module registers and renders websocket data", async () => {
  const Panel = await panelConstructor();
  assert.equal(typeof Panel, "function");

  const panel = new Panel();
  panel.hass = {
    callWS(message) {
      if (message.type === "predictive_controls/config") {
        return Promise.resolve({
          entry_id: "abc123",
          map: { nodes: {} },
          map_yaml: "nodes: {}\n",
          actions_yaml: "actions: {}\n",
          transition_window_seconds: 30,
          prediction_threshold: 0.6,
          expected_occupants: 2,
        });
      }
      if (message.type === "predictive_controls/entities") {
        return Promise.resolve({
          entities: [
            {
              entity_id: "binary_sensor.entrance_mmwave_dimmer_motion_detection",
              name: "Entrance mmWave Dimmer Motion detection",
              state: "off",
              device_class: null,
            },
          ],
        });
      }
      if (message.type === "predictive_controls/status") {
        return Promise.resolve({
          zone_states: {},
          recent_occupancy_events: [],
        });
      }
      throw new Error(`Unexpected websocket type: ${message.type}`);
    },
  };

  await new Promise((resolve) => setImmediate(resolve));

  assert.match(panel.innerHTML, /Predictive Controls/);
  assert.match(panel.innerHTML, /<main class="occupancy-layout">/);
  assert.equal(panel._entities[0].entity_id, "binary_sensor.entrance_mmwave_dimmer_motion_detection");
});

test("panel defaults to occupancy first and renders requested tab order", async () => {
  const Panel = await panelConstructor();
  const panel = new Panel();
  panel._hass = {};
  panel._config = {
    map: { nodes: {} },
    map_yaml: "nodes: {}\n",
    actions_yaml: "actions: {}\n",
    transition_window_seconds: 30,
    prediction_threshold: 0.6,
    expected_occupants: 2,
  };
  panel._status = { zone_states: {}, occupancy_diagnostics: { tracks: [] } };

  panel.render();

  assert.match(panel.innerHTML, /<main class="occupancy-layout">/);
  assert.match(
    panel.innerHTML,
    /data-tab="occupancy">Occupancy<\/button>\s*<button[^>]+data-tab="map">Map<\/button>\s*<button[^>]+data-tab="yaml">YAML<\/button>\s*<button[^>]+data-tab="actions">Actions<\/button>\s*<button[^>]+data-tab="settings">Settings<\/button>/,
  );
});

test("panel renders live occupancy zones from configured map data", async () => {
  const Panel = await panelConstructor();
  const panel = new Panel();
  panel._hass = {
    callWS(message) {
      assert.equal(message.type, "predictive_controls/status");
      return Promise.resolve({
        zone_states: {
          living_room: {
            confidence: 0.91,
            status: "confirmed",
            last_node_id: "living_left",
            reason: "still_target active at living_left; confidence is confirmed",
          },
        },
        recent_occupancy_events: [],
      });
    },
  };
  panel._config = {
    entry_id: "abc123",
    map: {
      zones: {
        living_room: {
          label: "Living Room",
          floor: "first_floor",
          role: "anchor_sensor",
          occupancy_behavior: "sticky",
          position: { x: 120, y: 220 },
          size: { width: 240, height: 130 },
        },
      },
      nodes: {
        living_left: {
          zone: "living_room",
          floor: "first_floor",
          role: "anchor_sensor",
          position: { x: 120, y: 220 },
          adjacent: [],
        },
      },
    },
  };
  panel._status = {
    zone_states: {
      living_room: {
        confidence: 0.91,
        status: "confirmed",
        occupancy_behavior: "sticky",
        last_node_id: "living_left",
        reason: "still_target active at living_left; confidence is confirmed",
      },
    },
    transition_counts: {
      living_left: { kitchen: 7 },
    },
        occupancy_diagnostics: {
          expected_occupants: 2,
          protected_corridor: ["living_room", "kitchen"],
          tracks: [
            {
              track_id: "track_1",
              zone: "living_room",
              confidence: 0.91,
              active: true,
              source_entities: ["binary_sensor.living_still"],
            },
          ],
          inferred_join_slots: [
            {
              zone: "living_room",
              source_zone: "foyer",
            },
          ],
          inferred_departures: [
            {
              zone: "office",
              via_zone: "hall",
              destination_zone: "kitchen",
            },
          ],
        },
  };
  panel._statusUpdated = new Date("2026-06-07T12:00:00Z");
  panel._tab = "occupancy";

  panel.render();

  assert.match(panel.innerHTML, /Occupancy/);
  assert.match(panel.innerHTML, /Living Room/);
  assert.match(panel.innerHTML, /91%/);
  assert.match(panel.innerHTML, /status-confirmed/);
  assert.match(panel.innerHTML, /Sticky/);
  assert.match(panel.innerHTML, /Anchor Sensor/);
  assert.match(panel.innerHTML, /living_left/);
  assert.match(panel.innerHTML, /Learned Transitions/);
  assert.match(panel.innerHTML, /Expected 2/);
  assert.match(panel.innerHTML, /track_1/);
  assert.match(panel.innerHTML, /binary_sensor\.living_still/);
  assert.match(panel.innerHTML, /Joined/);
  assert.match(panel.innerHTML, /Departed/);
  assert.match(panel.innerHTML, /Office/);
  assert.match(panel.innerHTML, /Kitchen/);
  assert.match(panel.innerHTML, /7/);
});

test("panel renders cross-floor zone adjacency as a graph edge", async () => {
  const Panel = await panelConstructor();
  const panel = new Panel();
  panel._hass = {};
  panel._config = {
    map: {
      zones: {
        staircase_bottom: {
          label: "Bottom of Staircase",
          floor: "first_floor",
          position: { x: 120, y: 120 },
        },
        upstairs_hallway: {
          label: "Upstairs Hallway",
          floor: "second_floor",
          position: { x: 120, y: 300 },
        },
      },
      nodes: {
        bottom_of_staircase_motion: {
          zone: "staircase_bottom",
          floor: "first_floor",
          adjacent: ["top_of_staircase_motion"],
        },
        top_of_staircase_motion: {
          zone: "upstairs_hallway",
          floor: "second_floor",
          adjacent: ["bottom_of_staircase_motion"],
        },
      },
    },
  };
  panel._status = { zone_states: {}, occupancy_diagnostics: { tracks: [] } };
  panel._tab = "occupancy";

  panel.render();

  assert.match(panel.innerHTML, /occupancy-graph/);
  assert.match(panel.innerHTML, /data-edge="staircase_bottom-&gt;upstairs_hallway"/);
  assert.match(panel.innerHTML, /Bottom of Staircase/);
  assert.match(panel.innerHTML, /Second Floor/);
  assert.match(panel.innerHTML, /Upstairs Hallway/);
  assert.doesNotMatch(panel.innerHTML, /floor-transitions/);
});

test("panel renders the editable map YAML tab", async () => {
  const Panel = await panelConstructor();
  const panel = new Panel();
  panel._hass = {};
  panel._config = {
    map: { nodes: { entry: { adjacent: [] } } },
    map_yaml: "nodes:\n  entry:\n    adjacent: []\n",
  };
  panel._tab = "yaml";

  panel.render();

  assert.match(panel.innerHTML, /Map YAML/);
  assert.match(panel.innerHTML, /data-map-yaml/);
  assert.match(panel.innerHTML, /entry:/);
});

test("panel renders map nodes with behavior and role labels", async () => {
  const Panel = await panelConstructor();
  const panel = new Panel();
  panel._hass = {};
  panel._config = {
    map: {
      zones: {
        office: { occupancy_behavior: "sustained" },
      },
      nodes: {
        office_motion: {
          label: "Office Motion",
          zone: "office",
          role: "room_occupancy",
          entities: { motion: "binary_sensor.office_motion" },
          adjacent: [],
          position: { x: 80, y: 80 },
        },
      },
    },
  };
  panel._tab = "map";

  panel.render();

  assert.match(panel.innerHTML, /Sustained/);
  assert.match(panel.innerHTML, /Room Occupancy/);
});

test("panel serializes multi-entity nodes into map YAML", async () => {
  const Panel = await panelConstructor();
  const panel = new Panel();
  panel._hass = {};
  panel._config = {
    map: {
      nodes: {
        fireplace: {
          label: "Fireplace Monitor",
          entities: {
            target: "binary_sensor.fireplace_target",
            moving_target: "binary_sensor.fireplace_moving_target",
          },
          adjacent: [],
        },
      },
    },
  };

  panel.syncMapYamlFromMap();

  assert.match(panel._config.map_yaml, /fireplace:/);
  assert.match(panel._config.map_yaml, /moving_target: binary_sensor\.fireplace_moving_target/);
});

test("panel serializes empty nested collections inline", async () => {
  const Panel = await panelConstructor();
  const panel = new Panel();
  panel._hass = {};
  panel._config = {
    map: {
      nodes: {
        entry: {
          label: "Entry",
          entities: {},
          adjacent: [],
          position: { x: 80, y: 80 },
        },
      },
    },
  };

  panel.syncMapYamlFromMap();

  assert.match(panel._config.map_yaml, /entities: \{\}/);
  assert.match(panel._config.map_yaml, /adjacent: \[\]/);
  assert.doesNotMatch(panel._config.map_yaml, /^\[\]$/m);
  assert.doesNotMatch(panel._config.map_yaml, /^\{\}$/m);
});

test("panel marks raw map yaml dirty only for yaml editor saves", async () => {
  const Panel = await panelConstructor();
  const calls = [];
  const panel = new Panel();
  panel._hass = {
    callWS(message) {
      calls.push(message);
      return Promise.resolve(panel._config);
    },
  };
  panel._config = {
    entry_id: "abc123",
    map: { nodes: { entry: { adjacent: [] } } },
    map_yaml: "nodes:\n  entry:\n    adjacent:\n[]\n",
    actions_yaml: "actions: {}\n",
    transition_window_seconds: 30,
    prediction_threshold: 0.6,
    expected_occupants: 2,
    expected_occupants_entity: "input_number.expected_occupants",
  };

  await panel.save();
  panel._mapYamlDirty = true;
  await panel.save();

  assert.equal(calls[0].map_yaml_dirty, false);
  assert.equal(calls[0].expected_occupants_entity, "input_number.expected_occupants");
  assert.equal(calls[1].map_yaml_dirty, true);
});

test("panel renders expected occupants setting", async () => {
  const Panel = await panelConstructor();
  const panel = new Panel();
  panel._hass = {};
  panel._config = {
    transition_window_seconds: 30,
    prediction_threshold: 0.6,
    expected_occupants: 2,
    expected_occupants_entity: "input_number.expected_occupants",
  };
  panel._tab = "settings";

  panel.render();

  assert.match(panel.innerHTML, /Expected occupants/);
  assert.match(panel.innerHTML, /value="2"/);
  assert.match(panel.innerHTML, /Expected occupants entity/);
  assert.match(panel.innerHTML, /input_number\.expected_occupants/);
  assert.match(panel.innerHTML, /Clean Stale Entities/);
});

test("panel cleans stale entities after preview and confirmation", async () => {
  const Panel = await panelConstructor();
  const calls = [];
  const panel = new Panel();
  panel._hass = {
    callWS(message) {
      calls.push(message);
      if (message.dry_run) {
        return Promise.resolve({ stale_count: 3 });
      }
      return Promise.resolve({ removed_count: 3 });
    },
  };
  panel._config = { entry_id: "abc123" };
  panel._tab = "settings";
  globalThis.confirm = () => true;

  await panel.cleanupEntities();

  assert.deepEqual(calls, [
    {
      type: "predictive_controls/cleanup_entities",
      entry_id: "abc123",
      dry_run: true,
    },
    {
      type: "predictive_controls/cleanup_entities",
      entry_id: "abc123",
      dry_run: false,
    },
  ]);
  assert.match(panel.innerHTML, /Removed 3 stale entities\./);
});

test("panel reports when no stale entities are found", async () => {
  const Panel = await panelConstructor();
  const panel = new Panel();
  panel._hass = {
    callWS(message) {
      assert.equal(message.dry_run, true);
      return Promise.resolve({ stale_count: 0 });
    },
  };
  panel._config = { entry_id: "abc123" };
  panel._tab = "settings";

  await panel.cleanupEntities();

  assert.match(panel.innerHTML, /No stale entities found\./);
});

test("panel script parses when Home Assistant loads it as a classic script", async () => {
  const source = await readFile(panelAssetUrl("panel-v0.1.13.js"), "utf8");

  assert.doesNotThrow(() => new vm.Script(source));
});

test("versioned panel asset matches the development panel asset", async () => {
  const [developmentSource, versionedSource] = await Promise.all([
    readFile(panelAssetUrl("panel.js"), "utf8"),
    readFile(panelAssetUrl("panel-v0.1.13.js"), "utf8"),
  ]);

  assert.equal(versionedSource, developmentSource);
});

function panelAssetUrl(filename) {
  return new URL(
    `../../custom_components/predictive_controls/frontend/${filename}`,
    import.meta.url,
  );
}