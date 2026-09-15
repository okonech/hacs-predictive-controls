import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile, readdir, stat } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';
import ts from 'typescript';
import { build } from 'esbuild';

const root = fileURLToPath(new URL('../../', import.meta.url));
const assets = ['panel.js', 'panel-v0.2.6.js', 'panel_helpers.js'].map(name => path.join(root, 'custom_components/predictive_controls/frontend', name));
async function sources(directory) {
    const files = [];
    for (const item of await readdir(directory, { withFileTypes: true })) {
        const file = path.join(directory, item.name);
        if (item.isDirectory()) files.push(...await sources(file));
        else if (item.name.endsWith('.ts')) files.push(file);
    }
    return files;
}

test('production TypeScript has no untyped assertions or compiler-suppression escape hatches', async () => {
    const violations = [];
    for (const file of await sources(path.join(root, 'frontend'))) {
        const text = await readFile(file, 'utf8');
        const ast = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
        function visit(node) {
            if (node.kind === ts.SyntaxKind.AnyKeyword || ts.isAsExpression(node)
                || ts.isTypeAssertionExpression(node) || ts.isNonNullExpression(node)) {
                violations.push(`${path.relative(root, file)}:${ast.getLineAndCharacterOfPosition(node.getStart()).line + 1}: ${ts.SyntaxKind[node.kind]}`);
            }
            ts.forEachChild(node, visit);
        }
        visit(ast);
        assert.doesNotMatch(text, /@ts-(?:ignore|nocheck)|eslint-disable/, file);
    }
    assert.deepEqual(violations, []);
});

test('strict compiler flags and build/CI gates cannot silently disappear', async () => {
    const config = JSON.parse(await readFile(path.join(root, 'tsconfig.json'), 'utf8'));
    for (const key of ['strict', 'noUncheckedIndexedAccess', 'exactOptionalPropertyTypes', 'noUnusedLocals', 'noUnusedParameters', 'noEmit']) assert.equal(config.compilerOptions[key], true, key);
    const pkg = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'));
    assert.match(pkg.scripts['build:frontend'], /typecheck:frontend/);
    assert.match(pkg.scripts['check:frontend'], /typecheck:frontend.*--check/);
    const ci = await readFile(path.join(root, '.github/workflows/quality.yml'), 'utf8');
    assert.match(ci, /npm ci/);
    assert.match(ci, /npm run check:frontend/);
    assert.match(ci, /npm run test:frontend/);
    assert.doesNotMatch(ci, /run: npm run build:frontend[\s\S]*run: npm run check:frontend/);
});

test('freshness check verifies all committed assets without writing even their timestamps', async () => {
    const before = await Promise.all(assets.map(async file => ({ text: await readFile(file, 'utf8'), mtime: (await stat(file)).mtimeMs })));
    const output = execFileSync(process.execPath, ['scripts/build_frontend.mjs', '--check'], { cwd: root, encoding: 'utf8' });
    assert.equal((output.match(/Verified frontend\//g) || []).length, 3);
    const after = await Promise.all(assets.map(async file => ({ text: await readFile(file, 'utf8'), mtime: (await stat(file)).mtimeMs })));
    assert.deepEqual(after, before);
});

test('bundles compile deterministically in memory with zero external imports or source maps', async () => {
    const options = { absWorkingDir: root, entryPoints: ['frontend/panel.ts'], bundle: true, write: false, platform: 'browser', format: 'iife', target: 'es2022', charset: 'utf8', legalComments: 'inline', sourcemap: false, metafile: true };
    const first = await build(options);
    const second = await build(options);
    assert.equal(first.outputFiles.length, 1);
    assert.deepEqual(first.outputFiles[0].contents, second.outputFiles[0].contents);
    for (const output of Object.values(first.metafile.outputs)) assert.deepEqual(output.imports, []);
    const source = first.outputFiles[0].text;
    assert.doesNotThrow(() => new vm.Script(source));
    assert.doesNotMatch(source, /sourceMappingURL|\/home\/alex|import\s*\(|https?:\/\/[^\s"']+\.(?:m?js)/);
    assert.match(source, /Continuous presence detected; path unverified/);
});

test('package, manifest, Python loader and shipped filename remain exactly version 0.2.6', async () => {
    const pkg = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'));
    const manifest = JSON.parse(await readFile(path.join(root, 'custom_components/predictive_controls/manifest.json'), 'utf8'));
    const constants = await readFile(path.join(root, 'custom_components/predictive_controls/const.py'), 'utf8');
    assert.equal(pkg.version, '0.2.6'); assert.equal(manifest.version, pkg.version);
    assert.equal(constants.match(/^VERSION = ["']([^"']+)["']/m)?.[1], pkg.version);
    assert.equal(constants.match(/^PANEL_FILENAME = ["']([^"']+)["']/m)?.[1], 'panel-v0.2.6.js');
    for (const file of assets) assert.match(await readFile(file, 'utf8'), /^\/\/ Generated from frontend\//);
});