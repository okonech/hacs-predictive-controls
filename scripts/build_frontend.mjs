import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { build } from "esbuild";

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

const [manifest, packageData, constants] = await Promise.all([
  readFile(manifestPath, "utf8").then(JSON.parse),
  readFile(packagePath, "utf8").then(JSON.parse),
  readFile(constPath, "utf8"),
]);

assert.equal(packageData.version, manifest.version, "package versions must match");
const filename = `panel-v${manifest.version}.js`;
assert.match(constants, new RegExp(`VERSION = ["']${manifest.version}["']`));
assert.match(constants, new RegExp(`PANEL_FILENAME = ["']${filename}["']`));
const options = {
  absWorkingDir: root,
  bundle: true,
  write: false,
  platform: "browser",
  target: "es2022",
  charset: "utf8",
  legalComments: "inline",
  sourcemap: false,
  metafile: true,
  banner: { js: `// Generated from frontend/ by scripts/build_frontend.mjs. Version ${manifest.version}. DO NOT EDIT.` },
};
const panel = await build({ ...options, entryPoints: ["frontend/panel.ts"], format: "iife" });
const helpers = await build({ ...options, entryPoints: ["frontend/map-helpers.ts"], format: "esm" });
for (const result of [panel, helpers]) {
  for (const output of Object.values(result.metafile.outputs)) {
    assert.equal(output.imports.length, 0, "runtime assets must be self-contained");
  }
}
const source = panel.outputFiles[0].text;
assert.doesNotThrow(() => new vm.Script(source), "versioned asset must parse as a classic script");
assert.match(source, /customElements\.define\("predictive-controls-panel"/);
const assets = new Map([[filename, source], ["panel.js", source], ["panel_helpers.js", helpers.outputFiles[0].text]]);
const check = process.argv.includes("--check");
for (const [name, content] of assets) {
  const destination = path.join(frontendPath, name);
  if (check) assert.equal(await readFile(destination, "utf8"), content, `Stale generated asset: ${name}; run npm run build:frontend`);
  else await writeFile(destination, content);
  console.log(`${check ? "Verified" : "Built"} frontend/${name} (${Buffer.byteLength(content)} bytes)`);
}
