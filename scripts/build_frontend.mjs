import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const manifestPath = path.join(
  root,
  "custom_components/predictive_controls/manifest.json",
);
const packagePath = path.join(root, "package.json");
const constPath = path.join(
  root,
  "custom_components/predictive_controls/const.py",
);
const frontendPath = path.join(
  root,
  "custom_components/predictive_controls/frontend",
);

const [manifest, packageData, constants, source] = await Promise.all([
  readFile(manifestPath, "utf8").then(JSON.parse),
  readFile(packagePath, "utf8").then(JSON.parse),
  readFile(constPath, "utf8"),
  readFile(path.join(frontendPath, "panel.js"), "utf8"),
]);

assert.equal(packageData.version, manifest.version, "package versions must match");
const filename = `panel-v${manifest.version}.js`;
assert.match(constants, new RegExp(`VERSION = ["']${manifest.version}["']`));
assert.match(constants, new RegExp(`PANEL_FILENAME = ["']${filename}["']`));
assert.doesNotThrow(() => new vm.Script(source), "panel source must parse");
assert.match(source, /customElements\.define\("predictive-controls-panel"/);

await writeFile(path.join(frontendPath, filename), source);
console.log(`Built frontend/${filename} (${Buffer.byteLength(source)} bytes)`);
