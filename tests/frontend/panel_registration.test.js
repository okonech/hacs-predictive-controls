import assert from "node:assert/strict";
import test from "node:test";

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

test("panel module registers and renders websocket data", async () => {
  const registry = new Map();
  globalThis.HTMLElement = FakeHTMLElement;
  globalThis.customElements = {
    define(name, constructor) {
      registry.set(name, constructor);
    },
  };

  await import("../../custom_components/predictive_controls/frontend/panel.js");

  const Panel = registry.get("predictive-controls-panel");
  assert.equal(typeof Panel, "function");

  const panel = new Panel();
  panel.hass = {
    callWS(message) {
      if (message.type === "predictive_controls/config") {
        return Promise.resolve({
          entry_id: "abc123",
          map: { nodes: {} },
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
      throw new Error(`Unexpected websocket type: ${message.type}`);
    },
  };

  await new Promise((resolve) => setImmediate(resolve));

  assert.match(panel.innerHTML, /Predictive Controls/);
  assert.match(panel.innerHTML, /Entrance mmWave Dimmer Motion detection/);
  assert.match(panel.innerHTML, /binary_sensor\.entrance_mmwave_dimmer_motion_detection/);
});