import assert from 'node:assert/strict';
import { test } from 'node:test';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, realpathSync, writeFileSync, symlinkSync, unlinkSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const runtime = new URL('./product_browser.mjs', import.meta.url).href;
function fixture(t) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'product runtime ')));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const cli = join(root, 'mermaid/node_modules/@mermaid-js/mermaid-cli/src/cli.js');
  mkdirSync(join(root, 'mermaid/node_modules/@mermaid-js/mermaid-cli/src'), { recursive: true });
  writeFileSync(cli, '// fixture', { mode: 0o755 });
  const modules = join(root, 'mermaid/node_modules');
  mkdirSync(join(modules, 'puppeteer'));
  const launched = join(root, 'puppeteer-launched');
  writeFileSync(join(modules, 'puppeteer/index.js'), `
    const { writeFileSync } = require('node:fs');
    module.exports = {
      launch: async options => {
        writeFileSync(${JSON.stringify(launched)}, 'launched');
        return { options };
      },
      executablePath: async () => process.env.TEST_CACHED_BROWSER || ${JSON.stringify(join(root, 'missing-cache'))}
    };
  `);
  const chrome = join(root, 'Chrome with spaces');
  writeFileSync(chrome, '#!/bin/sh\nexit 0\n', { mode: 0o755 });
  const env = { ...process.env, UNDERSTAND_RENDERER_HOME: root, MERMAID_OFFICIAL_CLI: cli, PUPPETEER_EXECUTABLE_PATH: chrome };
  delete env.PRODUCT_BROWSER_MODULES;
  delete env.TEST_CACHED_BROWSER;
  const run = changes => spawnSync(process.execPath, ['--input-type=module', '-e', `import {launchBrowser} from ${JSON.stringify(runtime)};try{console.log(JSON.stringify(await launchBrowser()))}catch(e){console.error(e.message);process.exitCode=2}`], { env: { ...env, ...changes }, encoding: 'utf8' });
  return { root, cli, modules, chrome, env, launched, run };
}

function desktopBrowser(root) {
  const desktop = join(root, 'Google Chrome.app/Contents/MacOS/Google Chrome');
  mkdirSync(dirname(desktop), { recursive: true });
  writeFileSync(desktop, '#!/bin/sh\nexit 0\n', { mode: 0o755 });
  return desktop;
}

test('managed renderer symlink discovers Puppeteer without module configuration', t => {
  const f = fixture(t);
  mkdirSync(join(f.root, 'bin'));
  symlinkSync(f.cli, join(f.root, 'bin/mmdc'));
  const result = f.run({ MERMAID_OFFICIAL_CLI: '' });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).options.executablePath, f.chrome);
});

test('external wrapper discovers quoted module and browser configuration paths', t => {
  const f = fixture(t), config = join(f.root, 'puppeteer config.json'), wrapper = join(f.root, 'mmdc');
  writeFileSync(config, JSON.stringify({ executablePath: f.chrome }));
  writeFileSync(wrapper, `#!/bin/sh\nexec node '${f.cli}' -p '${config}' "$@"\n`, { mode: 0o755 });
  const result = f.run({ MERMAID_OFFICIAL_CLI: wrapper, PUPPETEER_EXECUTABLE_PATH: '' });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).options.executablePath, f.chrome);
});

test('CI wrapper resolves its executable symlink to the installed Mermaid modules', t => {
  const f = fixture(t), wrapper = join(f.root, 'mmdc-ci'), config = join(f.root, 'browser.json');
  mkdirSync(join(f.root, 'bin'));
  const executable = join(f.root, 'bin/mmdc');
  symlinkSync(f.cli, executable);
  writeFileSync(config, JSON.stringify({ executablePath: f.chrome }));
  writeFileSync(wrapper, `#!/bin/sh\nexec '${executable}' --puppeteerConfigFile '${config}' "$@"\n`, { mode: 0o755 });
  const result = f.run({ MERMAID_OFFICIAL_CLI: wrapper, PUPPETEER_EXECUTABLE_PATH: '' });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).options.executablePath, f.chrome);
});

test('explicit modules and browser take precedence; bad configuration never falls back', t => {
  const f = fixture(t);
  const empty = join(f.modules, 'empty');
  mkdirSync(empty);
  const valid = f.run({ PRODUCT_BROWSER_MODULES: f.modules });
  assert.equal(valid.status, 0, valid.stderr);
  for (const changes of [
    { PRODUCT_BROWSER_MODULES: join(f.root, 'missing') },
    { PRODUCT_BROWSER_MODULES: empty },
    { MERMAID_OFFICIAL_CLI: join(f.root, 'missing') },
    { PUPPETEER_EXECUTABLE_PATH: join(f.root, 'missing') },
    { PUPPETEER_EXECUTABLE_PATH: f.root },
  ]) {
    const result = f.run(changes);
    assert.equal(result.status, 2, result.stdout);
    assert.match(result.stderr, /PRODUCT_BROWSER_MODULES|MERMAID_OFFICIAL_CLI|PUPPETEER_EXECUTABLE_PATH/);
  }
});

test('malformed wrapper browser configuration reports its path and fix', t => {
  const f = fixture(t), wrapper = join(f.root, 'mmdc'), config = join(f.root, 'bad.json');
  writeFileSync(config, '{bad');
  writeFileSync(wrapper, `#!/bin/sh\nexec node '${f.cli}' -p '${config}' "$@"\n`, { mode: 0o755 });
  const result = f.run({ MERMAID_OFFICIAL_CLI: wrapper, PUPPETEER_EXECUTABLE_PATH: '' });
  assert.equal(result.status, 2);
  assert.ok(result.stderr.includes(config), result.stderr);
  const override = f.run({ MERMAID_OFFICIAL_CLI: wrapper, PUPPETEER_EXECUTABLE_PATH: f.chrome });
  assert.equal(override.status, 0, override.stderr);
});

test('missing explicit module and browser are diagnosed together before launch', t => {
  const f = fixture(t);
  const result = f.run({ PRODUCT_BROWSER_MODULES: join(f.root, 'missing modules'), PUPPETEER_EXECUTABLE_PATH: join(f.root, 'missing browser') });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /Puppeteer unavailable/);
  assert.match(result.stderr, /browser path/);
});

test('explicit desktop paths and aliases never reach Puppeteer launch', t => {
  const f = fixture(t), desktop = desktopBrowser(f.root);
  const alias = join(f.root, 'browser-alias');
  symlinkSync(desktop, alias);
  for (const path of [desktop, alias]) {
    const result = f.run({ PUPPETEER_EXECUTABLE_PATH: path, TEST_CACHED_BROWSER: f.chrome });
    assert.equal(result.status, 2, result.stdout);
    assert.match(result.stderr, /desktop.*\.app/i);
    assert.ok(!existsSync(f.launched));
  }
});

test('desktop browser configured by Mermaid records an unverified receipt before running tests', t => {
  const f = fixture(t), desktop = desktopBrowser(f.root);
  const alias = join(f.root, 'browser-alias'), config = join(f.root, 'browser.json'), wrapper = join(f.root, 'mmdc');
  symlinkSync(desktop, alias);
  writeFileSync(config, JSON.stringify({ executablePath: alias }));
  writeFileSync(wrapper, `#!/bin/sh\nexec node '${f.cli}' -p '${config}' "$@"\n`, { mode: 0o755 });
  writeFileSync(join(f.root, 'journey.test.mjs'), 'throw new Error("should not run")');
  const result = spawnSync(process.execPath, [fileURLToPath(runtime), '--directory', f.root, '--test', 'journey.test.mjs'],
    { env: { ...f.env, MERMAID_OFFICIAL_CLI: wrapper, PUPPETEER_EXECUTABLE_PATH: '' }, encoding: 'utf8' });
  assert.equal(result.status, 2, result.stdout + result.stderr);
  const receipt = JSON.parse(readFileSync(join(f.root, 'evidence/browser.json'), 'utf8'));
  assert.equal(receipt.result, 'unverified');
  assert.equal(receipt.tests, 0);
  assert.match(receipt.errors.join('\n'), /desktop.*\.app/i);
  assert.ok(!existsSync(f.launched));
});

test('auto discovery skips desktop aliases and can use a standalone browser', t => {
  const f = fixture(t), desktop = desktopBrowser(f.root), bin = join(f.root, 'path');
  mkdirSync(bin);
  const python = spawnSync('python3', ['-c', 'import sys; print(sys.executable)'], { encoding: 'utf8' });
  assert.equal(python.status, 0, python.stderr);
  symlinkSync(python.stdout.trim(), join(bin, 'python3'));
  symlinkSync(desktop, join(bin, 'google-chrome'));
  const shellAlias = join(bin, 'chrome-headless-shell');
  symlinkSync(desktop, shellAlias);
  const changes = { PATH: bin, PUPPETEER_EXECUTABLE_PATH: '', TEST_CACHED_BROWSER: desktop };
  const blocked = f.run(changes);
  assert.equal(blocked.status, 2, blocked.stdout);
  assert.match(blocked.stderr, /desktop.*\.app/i);
  assert.ok(!existsSync(f.launched));
  const shell = join(f.root, 'chrome-headless-shell');
  writeFileSync(shell, '#!/bin/sh\nexit 0\n', { mode: 0o755 });
  unlinkSync(shellAlias);
  symlinkSync(shell, shellAlias);
  const allowed = f.run(changes);
  assert.equal(allowed.status, 0, allowed.stderr);
  assert.equal(JSON.parse(allowed.stdout).options.executablePath, shell);
  assert.equal(JSON.parse(allowed.stdout).options.headless, 'shell');
  const cached = f.run({ ...changes, TEST_CACHED_BROWSER: f.chrome });
  assert.equal(cached.status, 0, cached.stderr);
  assert.equal(JSON.parse(cached.stdout).options.executablePath, f.chrome);
});
