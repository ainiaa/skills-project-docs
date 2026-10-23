import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

const runtime = new URL('./product_browser.mjs', import.meta.url).href;
function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'product runtime '));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const cli = join(root, 'mermaid/node_modules/@mermaid-js/mermaid-cli/src/cli.js');
  mkdirSync(join(root, 'mermaid/node_modules/@mermaid-js/mermaid-cli/src'), { recursive: true });
  writeFileSync(cli, '// fixture', { mode: 0o755 });
  const modules = join(root, 'mermaid/node_modules');
  mkdirSync(join(modules, 'puppeteer'));
  writeFileSync(join(modules, 'puppeteer/index.js'), `module.exports={launch:async options=>({options}),executablePath:()=>${JSON.stringify(join(root, 'missing-cache'))}}`);
  const chrome = join(root, 'Chrome with spaces');
  writeFileSync(chrome, '#!/bin/sh\nexit 0\n', { mode: 0o755 });
  const env = { ...process.env, UNDERSTAND_RENDERER_HOME: root, MERMAID_OFFICIAL_CLI: cli, PUPPETEER_EXECUTABLE_PATH: chrome };
  delete env.PRODUCT_BROWSER_MODULES;
  const run = changes => spawnSync(process.execPath, ['--input-type=module', '-e', `import {launchBrowser} from ${JSON.stringify(runtime)};try{console.log(JSON.stringify(await launchBrowser()))}catch(e){console.error(e.message);process.exitCode=2}`], { env: { ...env, ...changes }, encoding: 'utf8' });
  return { root, cli, modules, chrome, run };
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
