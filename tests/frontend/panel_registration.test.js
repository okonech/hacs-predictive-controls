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
  assert.match(panel.innerHTML, /Entrance mmWave Dimmer Motion detection/);
  assert.match(panel.innerHTML, /binary_sensor\.entrance_mmwave_dimmer_motion_detection/);
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
        last_node_id: "living_left",
        reason: "still_target active at living_left; confidence is confirmed",
      },
    },
    transition_counts: {
      living_left: { kitchen: 7 },
    },
  };
  panel._statusUpdated = new Date("2026-06-07T12:00:00Z");
  panel._tab = "occupancy";

  panel.render();

  assert.match(panel.innerHTML, /Occupancy/);
  assert.match(panel.innerHTML, /Living Room/);
  assert.match(panel.innerHTML, /91%/);
  assert.match(panel.innerHTML, /status-confirmed/);
  assert.match(panel.innerHTML, /living_left/);
  assert.match(panel.innerHTML, /Learned Transitions/);
  assert.match(panel.innerHTML, /Kitchen/);
  assert.match(panel.innerHTML, /7/);
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

test("panel script parses when Home Assistant loads it as a classic script", async () => {
  const source = await readFile(panelAssetUrl("panel-v0.1.6.js"), "utf8");

  assert.doesNotThrow(() => new vm.Script(source));
});

test("versioned panel asset matches the development panel asset", async () => {
  const [developmentSource, versionedSource] = await Promise.all([
    readFile(panelAssetUrl("panel.js"), "utf8"),
    readFile(panelAssetUrl("panel-v0.1.6.js"), "utf8"),
  ]);

  assert.equal(versionedSource, developmentSource);
});

function panelAssetUrl(filename) {
  return new URL(
    `../../custom_components/predictive_controls/frontend/${filename}`,
    import.meta.url,
  );
}