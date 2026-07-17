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
    /data-tab="occupancy">Occupancy<\/button>\s*<button[^>]+data-tab="reliability">Reliability<\/button>\s*<button[^>]+data-tab="activity">Activity<\/button>\s*<button[^>]+data-tab="map">Map<\/button>\s*<button[^>]+data-tab="yaml">YAML<\/button>\s*<button[^>]+data-tab="actions">Actions<\/button>\s*<button[^>]+data-tab="settings">Settings<\/button>/,
  );
  assert.match(panel.innerHTML, /Anonymous Tracks/);
  assert.match(panel.innerHTML, /No occupants are currently localized/);
});

test("activity workspace explains edges, rejections, and sampled snapshots", async () => {
  const Panel = await panelConstructor();
  const panel = new Panel();
  panel._hass = {};
  panel._config = {
    map: {
      zones: {
        office: { label: "Office", floor: "second_floor" },
        hallway: { label: "Hallway", floor: "second_floor" },
      },
      nodes: {},
    },
  };
  panel._statusUpdated = new Date("2026-07-17T12:01:00Z");
  panel._status = {
    occupancy_diagnostics: {
      joint: {
        policy: {
          office: {
            keep_on: true,
            reason: "arrival-supported posterior event",
            last_trusted_at: "2026-07-17T12:00:00Z",
            last_release_cause: null,
          },
          hallway: {
            keep_on: false,
            reason: "finalized release-safe posterior event",
            last_trusted_at: "2026-07-17T11:50:00Z",
            last_release_cause: "release_safe",
          },
        },
        arrival_supported_probabilities: { office: 0.84 },
        release_safe: {
          available: true,
          probabilities: { office: 0.12, hallway: 0.97 },
        },
        policy_audit_retention: {
          retention_hours: 12,
          entry_count: 3,
          context_compressed_bytes: 24576,
          oldest_decision_at: "2026-07-17T11:59:30Z",
          newest_decision_at: "2026-07-17T12:00:30Z",
        },
        policy_audit: [
          {
            decision_at: "2026-07-17T12:00:00Z",
            decision: {
              zone: "office",
              action: "activate",
              accepted: true,
              reason_code: "arrival_supported",
              gate_values: { probability: 0.84, threshold: 0.8 },
              evidence_ids: ["episode-office"],
            },
            prior_active: false,
            resulting_active: true,
            context_complete: true,
          },
          {
            decision_at: "2026-07-17T12:00:15Z",
            decision: {
              zone: "hallway",
              action: "activate",
              accepted: false,
              reason_code: "arrival_supported_not_met",
              gate_values: { probability: 0.31, threshold: 0.8 },
              evidence_ids: [],
            },
            prior_active: false,
            resulting_active: false,
            context_complete: false,
          },
          {
            decision_at: "2026-07-17T12:00:30Z",
            decision: {
              zone: "office",
              action: "observe",
              accepted: true,
              reason_code: "periodic_sample",
              gate_values: {},
              evidence_ids: [],
            },
            prior_active: true,
            resulting_active: true,
            context_complete: true,
          },
        ],
      },
    },
  };
  panel._tab = "activity";

  panel.render();

  assert.match(panel.innerHTML, /<main class="activity-layout">/);
  assert.match(panel.innerHTML, /1 active zone/);
  assert.match(panel.innerHTML, /Turned on/);
  assert.match(panel.innerHTML, /Arrival support reached 84% against the 80% threshold/);
  assert.match(panel.innerHTML, /Exact context/);
  assert.match(panel.innerHTML, /data-activity-filter="edges" aria-pressed="true"/);
  assert.doesNotMatch(panel.innerHTML, /Arrival support stayed below/);
  assert.doesNotMatch(panel.innerHTML, /Periodic exact snapshot/);

  panel._activityFilter = "rejected";
  panel.render();
  assert.match(panel.innerHTML, /Arrival support stayed below the 80% threshold at 31%/);
  assert.match(panel.innerHTML, /Lightweight decision/);

  panel._activityFilter = "snapshots";
  panel.render();
  assert.match(panel.innerHTML, /Periodic exact snapshot/);
});

test("activity workspace supports legacy edges and an empty exact state", async () => {
  const Panel = await panelConstructor();
  const panel = new Panel();
  panel._hass = {};
  panel._config = { map: { zones: {}, nodes: {} } };
  panel._tab = "activity";
  panel._status = { occupancy_diagnostics: {} };

  panel.render();
  assert.match(panel.innerHTML, /Exact policy activity will appear after the first observation/);

  panel._status.occupancy_diagnostics.joint = {
    policy: {},
    policy_audit: [
      {
        decision_at: "2026-07-17T12:00:00Z",
        decision: {
          zone: "entry",
          action: "release",
          accepted: true,
          reason_code: "authoritative_away",
          gate_values: {},
          evidence_ids: [],
        },
        previous: { keep_on: true },
        current: { keep_on: false },
        context: { encoding: "zlib-json-v1", data: "packed" },
      },
    ],
    policy_audit_retention: { entry_count: 1, context_compressed_bytes: 128 },
  };
  panel.render();

  assert.match(panel.innerHTML, /Turned off/);
  assert.match(panel.innerHTML, /Authoritative away state cleared ownership/);
  assert.match(panel.innerHTML, /Exact context/);
});

test("activity workspace initially renders at most fifty audit rows", async () => {
  const Panel = await panelConstructor();
  const panel = new Panel();
  panel._hass = {};
  panel._config = { map: { zones: {}, nodes: {} } };
  panel._tab = "activity";
  panel._status = {
    occupancy_diagnostics: {
      joint: {
        policy: {},
        policy_audit_retention: { entry_count: 55 },
        policy_audit: Array.from({ length: 55 }, (_, index) => ({
          decision_at: new Date(Date.UTC(2026, 6, 17, 12, index)).toISOString(),
          decision: {
            zone: `zone_${index}`,
            action: index % 2 ? "activate" : "release",
            accepted: true,
            reason_code: index % 2 ? "arrival_supported" : "release_safe",
            gate_values: { probability: 0.9, threshold: 0.8 },
            evidence_ids: [],
          },
          prior_active: index % 2 === 0,
          resulting_active: index % 2 === 1,
          context_complete: true,
        })),
      },
    },
  };

  panel.render();

  assert.equal((panel.innerHTML.match(/class="audit-row kind-/g) || []).length, 50);
  assert.match(panel.innerHTML, /Show 50 more/);
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
  assert.match(panel.innerHTML, /Anonymous Tracks/);
  assert.match(panel.innerHTML, /Current Posterior/);
  assert.match(panel.innerHTML, /class="track-row"/);
  assert.match(panel.innerHTML, /track_1/);
  assert.match(panel.innerHTML, /binary_sensor\.living_still/);
  assert.match(panel.innerHTML, /Joined/);
  assert.match(panel.innerHTML, /Departed/);
  assert.match(panel.innerHTML, /Office/);
  assert.match(panel.innerHTML, /Kitchen/);
  assert.match(panel.innerHTML, /7/);
});

test("panel renders repeated reliability issues for proactive review", async () => {
  const Panel = await panelConstructor();
  const panel = new Panel();
  panel._hass = {};
  panel._config = {
    map: {
      zones: {
        office: { label: "Office", floor: "second_floor" },
      },
      nodes: {},
    },
  };
  panel._statusUpdated = new Date("2026-07-13T12:01:00Z");
  panel._status = {
    occupancy_diagnostics: {
      tracks: [],
      reliability: {
        criteria: { repeat_minimum: 2, flap_window_seconds: 30 },
        coverage: {
          observed_event_count: 4,
          oldest_event_at: "2026-07-13T12:00:00Z",
          newest_event_at: "2026-07-13T12:00:14Z",
        },
        rejected_motion_captures: [
          {
            entity_id: "binary_sensor.office_motion",
            zone: "office",
            capture_count: 2,
            last_capture_at: "2026-07-13T12:00:10Z",
            reason_counts: { occupied_gate_failed: 2 },
            max_occupied_marginal: 0.3,
          },
        ],
        low_confidence_flaps: [
          {
            entity_id: "binary_sensor.office_motion",
            zone: "office",
            pulse_count: 2,
            last_flap_at: "2026-07-13T12:00:14Z",
            shortest_pulse_seconds: 4,
            max_occupied_marginal: 0.3,
          },
        ],
      },
    },
  };
  panel._tab = "reliability";

  panel.render();

  assert.match(panel.innerHTML, /<main class="reliability-layout">/);
  assert.match(panel.innerHTML, /Repeated Rejected Motion/);
  assert.match(panel.innerHTML, /Low-Confidence Flaps/);
  assert.match(panel.innerHTML, /binary_sensor\.office_motion/);
  assert.match(panel.innerHTML, /Office/);
  assert.match(panel.innerHTML, /2 rejected/);
  assert.match(panel.innerHTML, /2 pulses/);
  assert.match(panel.innerHTML, /Occupied Gate Failed/);
  assert.match(panel.innerHTML, /Peak occupied 30%/);
  assert.match(panel.innerHTML, /4 observed events/);
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

test("panel orders occupancy floor bands by the configured floors list", async () => {
  const Panel = await panelConstructor();
  const panel = new Panel();
  panel._hass = {};
  panel._config = {
    map: {
      floors: ["basement", "first_floor", "second_floor"],
      zones: {
        gym: { label: "Gym", floor: "basement", position: { x: 100, y: 100 } },
        kitchen: { label: "Kitchen", floor: "first_floor", position: { x: 100, y: 100 } },
        office: { label: "Office", floor: "second_floor", position: { x: 100, y: 100 } },
      },
      nodes: {
        gym_motion: { zone: "gym", floor: "basement" },
        kitchen_motion: { zone: "kitchen", floor: "first_floor" },
        office_motion: { zone: "office", floor: "second_floor" },
      },
    },
  };
  panel._status = { zone_states: {}, occupancy_diagnostics: { tracks: [] } };
  panel._tab = "occupancy";

  panel.render();

  const bandLabels = [
    ...panel.innerHTML.matchAll(/class="floor-band"[^>]*>\s*<span>([^<]+)<\/span>/g),
  ].map((match) => match[1]);
  assert.deepEqual(bandLabels, ["Basement", "First Floor", "Second Floor"]);
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
  const source = await readFile(panelAssetUrl("panel-v0.2.1.js"), "utf8");

  assert.doesNotThrow(() => new vm.Script(source));
});

test("versioned panel asset matches the development panel asset", async () => {
  const [developmentSource, versionedSource] = await Promise.all([
    readFile(panelAssetUrl("panel.js"), "utf8"),
    readFile(panelAssetUrl("panel-v0.2.1.js"), "utf8"),
  ]);

  assert.equal(versionedSource, developmentSource);
});

function panelAssetUrl(filename) {
  return new URL(
    `../../custom_components/predictive_controls/frontend/${filename}`,
    import.meta.url,
  );
}